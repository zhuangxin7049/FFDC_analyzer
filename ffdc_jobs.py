"""Persistence primitives for background FFDC jobs.

The web application still owns job dictionaries and workflow policy. This
module owns the filesystem mechanics so a future queue/database adapter can
replace them without changing HTTP routes or JIRA monitor logic.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path


def safe_job_id(job_id):
    """Keep the historical alphanumeric job-id normalization behavior."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(job_id or ""))


def job_path(directory, job_id):
    normalized = safe_job_id(job_id)
    return Path(directory) / f"{normalized}.json" if normalized else None


def _atomic_write_json(path, payload):
    """Write JSON next to the target and replace it atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def persist_job(job, directory, latest_path):
    """Persist a job and update the latest pointer when appropriate."""
    job_id = safe_job_id((job or {}).get("id", ""))
    if not job_id:
        return
    directory = Path(directory)
    _atomic_write_json(job_path(directory, job_id), job)
    if job.get("scheduled") or job.get("status") == "done":
        _atomic_write_json(latest_path, {"job_id": job_id, "updated": job.get("updated", time.time())})


def load_job(job_id, directory, persist=None, now=None):
    """Load a job and mark interrupted running work after a restart."""
    path = job_path(directory, job_id)
    if not path or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    normalized = safe_job_id(job_id)
    data.setdefault("id", normalized)
    if data.get("status") == "running":
        data.update({
            "status": "error",
            "percent": 100,
            "message": "Stopped after service restart. The next scheduled review will run normally.",
            "error": "The previous scheduled review job was interrupted by a service restart.",
            "updated": time.time() if now is None else now,
        })
        if persist:
            persist(data)
    return data


def cleanup_jobs(jobs, lock, ttl_seconds, now=None):
    """Remove expired in-memory jobs while leaving disk snapshots intact."""
    current = time.time() if now is None else now
    with lock:
        expired = [
            job_id for job_id, job in jobs.items()
            if current - job.get("created", current) > ttl_seconds
        ]
        for job_id in expired:
            jobs.pop(job_id, None)


def latest_job_id(latest_path):
    """Read and validate the persisted latest-job pointer."""
    try:
        data = json.loads(Path(latest_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ""
    return safe_job_id(data.get("job_id", "")) if isinstance(data, dict) else ""
