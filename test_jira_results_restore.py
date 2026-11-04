import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class JiraResultsRestoreTests(unittest.TestCase):
    def test_reconstructs_completed_job_from_saved_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for report_id, attachment in [("report-a", "first.tzz"), ("report-b", "second.tzz")]:
                report_dir = root / report_id
                report_dir.mkdir()
                report = {
                    "id": report_id,
                    "format": "ffdc",
                    "source_file": attachment,
                    "jira": {
                        "issue": "IOSS-8361",
                        "attachment": attachment,
                        "results_job_id": "job-123",
                    },
                }
                (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            with patch.object(app, "REPORT_DIR", root):
                restored = app.reconstruct_jira_job_from_reports("job-123")
            self.assertEqual(restored["status"], "done")
            self.assertEqual(restored["issue"], "IOSS-8361")
            self.assertEqual([item["attachment"] for item in restored["reports"]], ["first.tzz", "second.tzz"])

    def test_unknown_job_is_still_missing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "REPORT_DIR", Path(tmp)):
            self.assertIsNone(app.reconstruct_jira_job_from_reports("missing-job"))


if __name__ == "__main__":
    unittest.main()
