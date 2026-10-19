"""Database backup, verification, restore and retention.

SQLite (development): the online backup API gives a consistent copy while the API is running; it is gzipped.
PostgreSQL (production): `pg_dump --format=custom`; the password goes through PGPASSWORD, never the command line.
Every backup has a JSON manifest next to it: SHA-256, size, migration revision and per-table row counts. `verify`
checks the checksum and, for SQLite, restores into a temporary file, runs `PRAGMA integrity_check` and compares row
counts with the manifest. A backup that has not been verified is not a backup.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url


@dataclass
class VerifyReport:
    backup: str
    ok: bool
    checks: dict[str, str] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _redacted(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _sqlite_path(url: str) -> Path:
    db = make_url(url).database
    if not db or db == ":memory:":
        raise ValueError("in-memory SQLite databases cannot be backed up")
    return Path(db)


def _table_counts(url: str) -> tuple[dict[str, int], str | None]:
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            tables = sorted(inspect(c).get_table_names())
            counts = {t: int(c.execute(text(f'select count(*) from "{t}"')).scalar()) for t in tables}
            revision = None
            if "alembic_version" in tables:
                revision = c.execute(text("select version_num from alembic_version")).scalar()
        return counts, revision
    finally:
        engine.dispose()


def _pg_env_and_dsn(url: str) -> tuple[dict[str, str], str]:
    u = make_url(url)
    env = {**os.environ}
    if u.password:
        env["PGPASSWORD"] = u.password
    # URL.set(password=None) would keep the password; build the libpq URL without it.
    dsn = URL.create("postgresql", username=u.username, host=u.host, port=u.port, database=u.database,
                     query=u.query).render_as_string(hide_password=False)
    return env, dsn


def create_backup(url: str, backup_dir: str | Path, now: datetime | None = None, runner=subprocess.run) -> Path:
    """Write a backup and its manifest; returns the manifest path."""
    now = now or datetime.now(timezone.utc)
    out_dir = Path(backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    engine_name = make_url(url).get_backend_name()
    counts, revision = _table_counts(url)
    if engine_name == "sqlite":
        target = out_dir / f"atlas-sqlite-{stamp}.db.gz"
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy.db"
            src = sqlite3.connect(_sqlite_path(url))
            dst = sqlite3.connect(copy)
            try:
                src.backup(dst)  # consistent snapshot, safe while the API writes
            finally:
                dst.close()
                src.close()
            with copy.open("rb") as fi, gzip.open(target, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo)
    elif engine_name == "postgresql":
        target = out_dir / f"atlas-postgresql-{stamp}.dump"
        env, dsn = _pg_env_and_dsn(url)
        runner(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={target}", f"--dbname={dsn}"],
               env=env, check=True, capture_output=True)
    else:
        raise ValueError(f"unsupported database for backup: {engine_name}")
    manifest = {
        "file": target.name, "engine": engine_name, "created_at": now.isoformat(), "source": _redacted(url),
        "sha256": _sha256(target), "bytes": target.stat().st_size, "alembic_revision": revision, "table_rows": counts,
        "note": "PostgreSQL row counts are read just before pg_dump; concurrent writes may differ slightly."
        if engine_name == "postgresql" else "Consistent snapshot (SQLite online backup API).",
    }
    path = target.with_name(target.name.split(".")[0] + ".json")
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def list_backups(backup_dir: str | Path) -> list[dict]:
    """Manifests, newest first."""
    out = []
    for m in Path(backup_dir).glob("atlas-*.json"):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({**data, "manifest": str(m)})
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def _restore_sqlite_file(gz: Path, dest: Path) -> None:
    with gzip.open(gz, "rb") as fi, dest.open("wb") as fo:
        shutil.copyfileobj(fi, fo)


def verify_backup(manifest_path: str | Path, runner=subprocess.run) -> VerifyReport:
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = manifest_path.with_name(m["file"])
    rep = VerifyReport(backup=str(data), ok=True)

    def fail(check: str, msg: str) -> VerifyReport:
        rep.ok = False
        rep.checks[check] = msg
        return rep

    if not data.exists():
        return fail("file", "missing")
    if _sha256(data) != m["sha256"]:
        return fail("checksum", "SHA-256 differs from the manifest (corrupted or modified)")
    rep.checks["checksum"] = "ok"
    if m["engine"] == "sqlite":
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "restore-test.db"
            try:
                _restore_sqlite_file(data, db)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                return fail("decompress", str(exc))
            con = sqlite3.connect(db)
            try:
                integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                con.close()
            if integrity != "ok":
                return fail("integrity", integrity)
            rep.checks["integrity"] = "ok"
            counts, revision = _table_counts(f"sqlite:///{db.as_posix()}")
        diffs = {t: (n, counts.get(t)) for t, n in m["table_rows"].items() if counts.get(t) != n}
        if diffs:
            return fail("row_counts", f"differ from manifest: {diffs}")
        rep.checks["row_counts"] = f"ok ({sum(counts.values())} rows in {len(counts)} tables)"
        if revision != m["alembic_revision"]:
            return fail("revision", f"{revision} != {m['alembic_revision']}")
        rep.checks["revision"] = str(revision)
    else:
        res = runner(["pg_restore", "--list", str(data)], check=False, capture_output=True)
        if res.returncode != 0:
            return fail("archive", "pg_restore --list failed")
        rep.checks["archive"] = "ok (pg_restore --list); run a full restore drill into a scratch database"
    return rep


def restore_backup(manifest_path: str | Path, target_url: str, force: bool = False, runner=subprocess.run) -> str:
    """Restore after verifying. Never overwrites without `force`; an existing SQLite file is kept aside first."""
    report = verify_backup(manifest_path, runner=runner)
    if not report.ok:
        raise RuntimeError(f"backup failed verification, not restoring: {report.checks}")
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = manifest_path.with_name(m["file"])
    engine_name = make_url(target_url).get_backend_name()
    if engine_name != m["engine"]:
        raise ValueError(f"backup is {m['engine']}, target is {engine_name}")
    if engine_name == "sqlite":
        dest = _sqlite_path(target_url)
        kept = None
        if dest.exists():
            if not force:
                raise FileExistsError(f"{dest} exists; stop the API and pass --force to replace it")
            kept = dest.with_name(f"{dest.name}.pre-restore-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
            shutil.copy2(dest, kept)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".restoring")
        _restore_sqlite_file(data, tmp)
        os.replace(tmp, dest)
        return f"restored {data.name} → {dest}" + (f" (previous database kept at {kept})" if kept else "")
    if not force:
        raise PermissionError("restoring PostgreSQL drops and recreates objects; pass --force")
    env, dsn = _pg_env_and_dsn(target_url)
    runner(["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges", f"--dbname={dsn}", str(data)],
           env=env, check=True, capture_output=True)
    return f"restored {data.name} → {_redacted(target_url)}"


def prune_backups(backup_dir: str | Path, keep: int) -> list[str]:
    """Delete all but the newest `keep` backups (data file + manifest). Returns removed file names."""
    if keep < 1:
        raise ValueError("keep must be >= 1")
    removed = []
    for m in list_backups(backup_dir)[keep:]:
        for p in (Path(m["manifest"]).with_name(m["file"]), Path(m["manifest"])):
            if p.exists():
                p.unlink()
                removed.append(p.name)
    return removed
