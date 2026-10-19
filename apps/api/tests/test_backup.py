"""Backup → verify → restore drill on SQLite, tamper detection, retention, and the PostgreSQL command shapes."""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import text

from app.core.db import Base, Database
from app.services import backup as bk


@pytest.fixture
def live_db(tmp_path):
    url = f"sqlite:///{(tmp_path / 'live.db').as_posix()}"
    database = Database(url)
    Base.metadata.create_all(database.engine)
    with database.engine.begin() as c:
        c.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        c.execute(text("insert into alembic_version values ('0003')"))
        c.execute(text("insert into users (user_id, email, password_hash, role, is_active, created_at) "
                       "values ('u1', 'a@example.com', 'x', 'user', 1, '2026-10-16 00:00:00')"))
    database.engine.dispose()
    return url, tmp_path


def test_backup_verify_restore_round_trip(live_db):
    url, tmp = live_db
    manifest = bk.create_backup(url, tmp / "backups")
    m = json.loads(manifest.read_text())
    assert m["engine"] == "sqlite" and m["alembic_revision"] == "0003" and m["table_rows"]["users"] == 1
    assert m["file"].endswith(".db.gz") and "password" not in m["source"]
    rep = bk.verify_backup(manifest)
    assert rep.ok and rep.checks["integrity"] == "ok" and rep.checks["revision"] == "0003"

    # Restore into a new location.
    target = tmp / "restored" / "atlas.db"
    assert "restored" in bk.restore_backup(manifest, f"sqlite:///{target.as_posix()}")
    con = sqlite3.connect(target)
    assert con.execute("select email from users").fetchall() == [("a@example.com",)]
    con.close()

    # The live database is never overwritten without --force, and is kept aside when it is.
    with pytest.raises(FileExistsError):
        bk.restore_backup(manifest, url)
    msg = bk.restore_backup(manifest, url, force=True)
    assert "previous database kept" in msg and list(tmp.glob("live.db.pre-restore-*"))


def test_tampered_or_truncated_backup_is_rejected(live_db):
    url, tmp = live_db
    manifest = bk.create_backup(url, tmp / "b")
    data = manifest.with_name(json.loads(manifest.read_text())["file"])
    raw = data.read_bytes()
    data.write_bytes(raw[: len(raw) // 2])
    rep = bk.verify_backup(manifest)
    assert not rep.ok and "SHA-256" in rep.checks["checksum"]
    with pytest.raises(RuntimeError, match="failed verification"):
        bk.restore_backup(manifest, f"sqlite:///{(tmp / 'x.db').as_posix()}")

    # Checksum matches but content disagrees with the manifest (e.g. a manifest from another backup).
    manifest2 = bk.create_backup(url, tmp / "c")
    m = json.loads(manifest2.read_text())
    m["table_rows"]["users"] = 5
    manifest2.write_text(json.dumps(m))
    rep2 = bk.verify_backup(manifest2)
    assert not rep2.ok and "users" in rep2.checks["row_counts"]


def test_backup_is_consistent_gzip_of_a_valid_database(live_db):
    url, tmp = live_db
    manifest = bk.create_backup(url, tmp / "b")
    data = manifest.with_name(json.loads(manifest.read_text())["file"])
    assert gzip.decompress(data.read_bytes())[:16] == b"SQLite format 3\x00"


def test_retention_keeps_newest(live_db):
    url, tmp = live_db
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(5):
        bk.create_backup(url, tmp / "r", now=t0 + timedelta(days=i))
    removed = bk.prune_backups(tmp / "r", keep=2)
    assert len(removed) == 6  # 3 backups × (data + manifest)
    kept = bk.list_backups(tmp / "r")
    assert [k["created_at"][:10] for k in kept] == ["2026-10-05", "2026-10-04"]
    with pytest.raises(ValueError):
        bk.prune_backups(tmp / "r", keep=0)


def test_postgres_commands_keep_password_out_of_argv(tmp_path, monkeypatch):
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0] == "pg_dump":
            Path(next(a for a in cmd if a.startswith("--file=")).removeprefix("--file=")).write_bytes(b"PGDMP fake")
        return NS(returncode=0)

    monkeypatch.setattr(bk, "_table_counts", lambda url: ({"users": 3}, "0003"))
    url = "postgresql+psycopg://atlas:s3cr3t@db.internal:5432/atlas"
    manifest = bk.create_backup(url, tmp_path, runner=runner)
    cmd, kw = calls[0]
    assert cmd[0] == "pg_dump" and "--format=custom" in cmd
    assert all("s3cr3t" not in a for a in cmd) and kw["env"]["PGPASSWORD"] == "s3cr3t"
    assert "--dbname=postgresql://atlas@db.internal:5432/atlas" in cmd
    m = json.loads(manifest.read_text())
    assert "s3cr3t" not in m["source"] and m["file"].endswith(".dump")
    assert bk.verify_backup(manifest, runner=runner).ok and calls[-1][0][:2] == ["pg_restore", "--list"]
    with pytest.raises(PermissionError):
        bk.restore_backup(manifest, url, runner=runner)
    bk.restore_backup(manifest, url, force=True, runner=runner)
    assert calls[-1][0][:3] == ["pg_restore", "--clean", "--if-exists"] and all("s3cr3t" not in a for a in calls[-1][0])


def test_cli_backup_command(live_db, monkeypatch):
    url, tmp = live_db
    from dataclasses import replace

    from app.workers import cli
    from tests.conftest import make_settings

    settings = replace(make_settings(url), backup_dir=(tmp / "cli").as_posix(), backup_keep=1)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["backup"]) == 0 and cli.main(["backup"]) == 0
    assert len(bk.list_backups(tmp / "cli")) == 1  # retention applied
    assert cli.main(["verify-backup"]) == 0
