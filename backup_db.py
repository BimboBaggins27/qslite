"""Nightly DB backup script.

Run by Windows Task Scheduler (or cron on Pi):
    python backup_db.py

Behaviour:
    1. Atomic SQLite-API backup (WAL-safe) → data/backups/memory-YYYY-MM-DD.sqlite
    2. Keep last 30 daily snapshots; older ones deleted
    3. If $WORK_FOLDER is set and reachable, ALSO copy to {work_folder}/qslite-backups/
    4. If $B2_KEY_ID + $B2_APP_KEY + $B2_BUCKET are set, upload to Backblaze B2
       (requires `pip install b2sdk` — installed only when needed)

Exit code 0 on success, non-zero on failure.

POPIA: backups inherit the live DB's encryption posture. Use SQLCipher
(see memory.py task) for at-rest encryption — until then, keep the
backup folder ACL-restricted on the host.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "memory.sqlite"
BACKUP_DIR = ROOT / "data" / "backups"
RETAIN_DAYS = 30


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def local_backup() -> Path:
    """Use SQLite's online backup API (WAL-safe). Returns the snapshot path."""
    from memory import backup_to  # lazy: avoid pulling Streamlit on cron runs
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = BACKUP_DIR / f"memory-{_today_stamp()}.sqlite"
    return backup_to(out)


def prune_local(retain_days: int = RETAIN_DAYS) -> int:
    """Delete snapshots older than `retain_days`. Returns count removed."""
    if not BACKUP_DIR.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=retain_days)
    n = 0
    for f in BACKUP_DIR.glob("memory-*.sqlite"):
        try:
            stamp = f.stem.replace("memory-", "")
            d = datetime.strptime(stamp, "%Y-%m-%d")
            if d < cutoff:
                f.unlink()
                n += 1
        except (ValueError, OSError):
            continue
    return n


def mirror_to_work_folder(src: Path) -> Path | None:
    """If a work folder is configured and exists, copy snapshot there too.
    Reads work_folder from data/.work_folder file (set by the app)."""
    marker = ROOT / "data" / ".work_folder"
    if not marker.exists():
        return None
    try:
        wf = Path(marker.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    if not wf.exists() or not wf.is_dir():
        return None
    target_dir = wf / "qslite-backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / src.name
    shutil.copy2(src, dst)
    return dst


def upload_to_b2(src: Path) -> str | None:
    """Upload to Backblaze B2 if credentials are set.
    Requires: pip install b2sdk
    Env vars: B2_KEY_ID, B2_APP_KEY, B2_BUCKET (B2_PREFIX optional)."""
    key_id = os.environ.get("B2_KEY_ID")
    app_key = os.environ.get("B2_APP_KEY")
    bucket_name = os.environ.get("B2_BUCKET")
    prefix = os.environ.get("B2_PREFIX", "qslite/").rstrip("/") + "/"
    if not (key_id and app_key and bucket_name):
        return None
    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api  # type: ignore
    except ImportError:
        print("b2sdk not installed; skipping B2 upload (run: pip install b2sdk)", file=sys.stderr)
        return None
    try:
        info = InMemoryAccountInfo()
        b2 = B2Api(info)
        b2.authorize_account("production", key_id, app_key)
        bucket = b2.get_bucket_by_name(bucket_name)
        remote = f"{prefix}{src.name}"
        bucket.upload_local_file(local_file=str(src), file_name=remote)
        return f"b2://{bucket_name}/{remote}"
    except Exception as e:
        print(f"B2 upload failed: {e}", file=sys.stderr)
        return None


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}", file=sys.stderr)
        return 2

    started = datetime.now()
    result = {"started": started.isoformat(timespec="seconds")}

    try:
        local = local_backup()
        result["local"] = str(local)
        result["size_bytes"] = local.stat().st_size
    except Exception as e:
        print(f"Local backup failed: {e}", file=sys.stderr)
        return 3

    pruned = prune_local()
    result["pruned"] = pruned

    work = mirror_to_work_folder(local)
    if work:
        result["work_folder_copy"] = str(work)

    b2 = upload_to_b2(local)
    if b2:
        result["b2_upload"] = b2

    result["finished"] = datetime.now().isoformat(timespec="seconds")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
