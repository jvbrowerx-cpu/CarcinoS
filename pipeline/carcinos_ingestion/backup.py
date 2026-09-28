"""
CarcinoS — Supabase auto-backup module.

Called automatically at the end of every --persist pipeline run.
Exports key tables to timestamped JSON files in CarcinoS/backups/.
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

TABLES = ["alerts", "users", "subscriptions", "disease_sites", "pipeline_runs"]

# CarcinoS/backups/ — three levels up from this file
# (carcinos_ingestion/ → pipeline/ → CarcinoS/)
_BACKUP_ROOT = Path(__file__).parent.parent.parent / "backups"


def run_backup(supabase_url: str, service_role_key: str) -> Path:
    """
    Export all key Supabase tables to a timestamped folder.
    Returns the backup directory path.
    Raises on unrecoverable errors so the caller can log a warning.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("'requests' package not available — skipping backup")

    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    backup_dir = _BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int | str] = {}
    for table in TABLES:
        url = f"{supabase_url}/rest/v1/{table}?select=*"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            (backup_dir / f"{table}.json").write_text(
                json.dumps(data, indent=2, default=str)
            )
            summary[table] = len(data)
            log.info("[backup] %-22s %d rows", table, len(data))
        else:
            summary[table] = f"ERROR {resp.status_code}"
            log.warning("[backup] %s: HTTP %s — %s", table, resp.status_code, resp.text[:120])

    # Manifest
    manifest = {
        "backup_timestamp": timestamp,
        "supabase_url": supabase_url,
        "tables": summary,
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    successful = sum(1 for v in summary.values() if isinstance(v, int))
    log.info("[backup] %d/%d tables saved → backups/%s/", successful, len(TABLES), timestamp)

    # Keep only the 10 most recent backups to avoid unbounded disk growth
    _prune_old_backups(keep=10)

    return backup_dir


def _prune_old_backups(keep: int = 10) -> None:
    """Remove oldest backup folders beyond the keep limit."""
    if not _BACKUP_ROOT.exists():
        return
    folders = sorted(
        [d for d in _BACKUP_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    to_delete = folders[:-keep] if len(folders) > keep else []
    for old in to_delete:
        try:
            import shutil
            shutil.rmtree(old)
            log.info("[backup] pruned old backup: %s", old.name)
        except Exception as e:
            log.warning("[backup] could not prune %s: %s", old.name, e)
