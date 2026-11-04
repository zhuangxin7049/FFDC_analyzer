import tempfile
import unittest
from pathlib import Path

import app
import workspace_ui


class StandaloneLogTests(unittest.TestCase):
    def test_mctp_trace_parser_keeps_operations_endpoints_and_errors(self):
        text = "\n".join([
            "2026-08-05T08:00:20.22881 XMIT >>>> 00>>09, tag 0, VDM, 00h, 44h",
            "2026-08-05T08:00:20.318727 RECV(80) << 08<<09, tag 0, CTRL, Discover,",
            "2026-08-05T08:00:21 RECV timeout waiting for response",
        ])
        result = app.parse_standalone_mctp_trace(text, "mctp_trace.log")
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["endpoints"][0]["endpoint"], "00>>09")
        self.assertEqual(result["operations"][0]["operation"], "Discover")
        self.assertEqual(result["findings"][0]["severity"], "Critical")

    def test_pldm_parser_includes_update_status_tids_and_sensor_error(self):
        text = "\n".join([
            "2026-08-05T06:49:14 pldmd: TID 17, EID 0x09, Component 4, package transfered 5%",
            "2026-08-05T06:49:15 pldmd: GetSensorReading response failed TID = 2",
        ])
        result = app.parse_standalone_pldm_log(text, "pldm.log")
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["tids"][0]["tid"], "17")
        self.assertEqual(result["eids"][0]["eid"], "0x09")
        self.assertEqual(result["findings"][0]["severity"], "Critical")

    def test_upload_dispatches_plain_logs_and_writes_source_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pldm.log"
            path.write_text("TID 3, EID 0x09, GetSensorReading response failed\n")
            report = app.analyze_standalone_log(path, cleanup=False)
            self.addCleanup(lambda: __import__("shutil").rmtree(app.REPORT_DIR / report["id"], ignore_errors=True))
            self.assertEqual(report["format"], "standalone_pldm")
            self.assertTrue((app.REPORT_DIR / report["id"] / "report.json").exists())
            self.assertTrue((app.REPORT_DIR / report["id"] / "ffdc.tar").exists())
            self.assertIn("Standalone PLDM log Analysis", app.render_report(report))

    def test_upload_extension_and_ui_accept_standalone_logs(self):
        self.assertTrue(app.is_standalone_log_upload(Path("mctp_trace.log")))
        self.assertTrue(app.is_standalone_log_upload(Path("pldm.log.1")))
        self.assertTrue(app.is_standalone_log_upload(Path("pldm.txt")))
        self.assertFalse(app.is_standalone_log_upload(Path("capture.tar.zst")))
        self.assertIn(".log", workspace_ui.render_workspace_page())
        self.assertIn(".log", app.index_page())


if __name__ == "__main__":
    unittest.main()
