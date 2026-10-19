"""Operational commands.

    python -m app.workers.cli ingest                 # sync sources/instruments and ingest all series
    python -m app.workers.cli create-user EMAIL --role administrator   (password read from ATLAS_NEW_USER_PASSWORD)
    python -m app.workers.cli backup [--keep N]       # consistent backup + manifest, then retention
    python -m app.workers.cli backups                 # list backups, newest first
    python -m app.workers.cli verify-backup [MANIFEST] # checksum, integrity, row counts (default: newest)
    python -m app.workers.cli restore MANIFEST [--target URL] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.auth.security import MIN_PASSWORD_LENGTH, hash_password
from app.core.config import get_settings
from app.core.db import Database
from app.integrations.catalog import build_providers
from app.models import User
from app.models.enums import Role
from app.services import backup as bk
from app.services.ingestion import ingest_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    cu = sub.add_parser("create-user")
    cu.add_argument("email")
    cu.add_argument("--role", default=Role.USER.value, choices=[r.value for r in Role])
    b = sub.add_parser("backup")
    b.add_argument("--keep", type=int, default=None, help="backups to retain (default ATLAS_BACKUP_KEEP)")
    b.add_argument("--quiet", action="store_true")
    sub.add_parser("backups")
    vb = sub.add_parser("verify-backup")
    vb.add_argument("manifest", nargs="?")
    rs = sub.add_parser("restore")
    rs.add_argument("manifest")
    rs.add_argument("--target", default=None, help="database URL (default ATLAS_DATABASE_URL)")
    rs.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.cmd in {"backup", "backups", "verify-backup", "restore"}:
        return _backup_cmd(args, settings)
    db = Database(settings.database_url)
    with db.sessionmaker() as s:
        if args.cmd == "ingest":
            results = ingest_all(s, build_providers(settings))
            summary = {r.status: 0 for r in results}
            for r in results:
                summary[r.status] += 1
            print(json.dumps({"runs": len(results), "by_status": summary,
                              "rows_written": sum(r.rows_written for r in results),
                              "rows_excluded": sum(r.rows_excluded for r in results),
                              "errors": [r.__dict__ for r in results if r.error]}, indent=2))
            return 0 if all(r.status == "succeeded" for r in results) else 1
        if args.cmd == "create-user":
            password = os.environ.get("ATLAS_NEW_USER_PASSWORD", "")
            if len(password) < MIN_PASSWORD_LENGTH:
                print(f"Set ATLAS_NEW_USER_PASSWORD (>= {MIN_PASSWORD_LENGTH} chars)", file=sys.stderr)
                return 2
            s.add(User(email=args.email.strip().lower(), password_hash=hash_password(password), role=args.role))
            s.commit()
            print(f"created {args.email} ({args.role})")
            return 0
    return 1


def _backup_cmd(args, settings) -> int:
    if args.cmd == "backup":
        manifest = bk.create_backup(settings.database_url, settings.backup_dir)
        report = bk.verify_backup(manifest)
        removed = bk.prune_backups(settings.backup_dir, args.keep or settings.backup_keep) if report.ok else []
        if not args.quiet or not report.ok:
            print(json.dumps({"manifest": str(manifest), "verified": report.ok, "checks": report.checks, "pruned": removed}, indent=2))
        return 0 if report.ok else 1
    if args.cmd == "backups":
        for m in bk.list_backups(settings.backup_dir):
            print(f"{m['created_at']}  {m['engine']:<10} {m['bytes']:>12,} B  rev {m['alembic_revision']}  {m['manifest']}")
        return 0
    if args.cmd == "verify-backup":
        manifest = args.manifest or next((m["manifest"] for m in bk.list_backups(settings.backup_dir)), None)
        if not manifest:
            print("no backups found", file=sys.stderr)
            return 1
        report = bk.verify_backup(manifest)
        print(json.dumps(report.__dict__, indent=2))
        return 0 if report.ok else 1
    print(bk.restore_backup(args.manifest, args.target or settings.database_url, force=args.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
