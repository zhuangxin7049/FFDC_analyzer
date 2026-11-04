import json
import tempfile
import threading
import unittest
from pathlib import Path

from ffdc_jobs import cleanup_jobs, latest_job_id, load_job, persist_job, safe_job_id


class JobPersistenceTests(unittest.TestCase):
    def test_persist_and_reload_use_atomic_json_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs"
            latest = jobs / "latest.json"
            job = {"id": "job-1", "status": "done", "created": 1, "issues": [{"key": "RAID-1"}]}
            persist_job(job, jobs, latest)
            self.assertEqual(latest_job_id(latest), "job-1")
            self.assertEqual(load_job("job-1", jobs)["issues"][0]["key"], "RAID-1")
            self.assertEqual(json.loads((jobs / "job-1.json").read_text())["status"], "done")

    def test_running_job_is_marked_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs"
            latest = jobs / "latest.json"
            persist_job({"id": "job", "status": "running", "created": 1}, jobs, latest)
            updated = load_job("job", jobs, persist=lambda value: persist_job(value, jobs, latest), now=20)
            self.assertEqual(updated["status"], "error")
            self.assertIn("service restart", updated["message"])
            self.assertEqual(load_job("job", jobs)["status"], "error")

    def test_cleanup_only_removes_expired_memory_entries(self):
        jobs = {"old": {"created": 1}, "new": {"created": 99}}
        cleanup_jobs(jobs, threading.Lock(), ttl_seconds=10, now=100)
        self.assertEqual(set(jobs), {"new"})

    def test_job_ids_are_safe_for_filenames(self):
        self.assertEqual(safe_job_id("../job 1"), "job1")


if __name__ == "__main__":
    unittest.main()
