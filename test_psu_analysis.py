import tempfile
import unittest
from pathlib import Path

import app
from psu_analysis import analyze_psu_logs, decode_d2, parse_psu_dump, parse_psu_log_info


class PsuAnalysisTests(unittest.TestCase):
    def test_psu_log_info_decodes_d0_d2_and_composite_flags(self):
        text = "\n".join([
            "Time: 2026-09-08 23:27:21 | PSU1 | D0h:04 09 1a 11 00 00 00 01 00 00 00 00 00 00 00 0b 00 00",
            "Time: 2026-09-08 23:27:21 | PSU1 | D2h:10 00 00 02 0a 00 0c 00 00 00 6d 01 f7 c8 d3 db 17 e2 c0 db fc 13 3f 1a 00",
            "                               D2h:10 00 00 00 0a 00 00 00 00 00 6e 01 00 00 3c e2 e4 e2 ff ff 9f 12 76 1a 00",
            "                               D2h:10 00 00 00 09 00 00 00 00 00 6e 01 34 da 3c e2 e4 e2 ff ff 9f 12 76 1a 00",
        ])
        psus = parse_psu_log_info(text, "v4", "psu_log_info")
        self.assertEqual(len(psus), 1)
        self.assertEqual(len(psus[0]["first_four"]), 4)
        self.assertEqual(psus[0]["first_four"][0]["decoded"]["date"], "2026-04-09")
        first_d2 = psus[0]["first_four"][1]["decoded"]
        self.assertEqual(first_d2["vbulk_volts"], 365)
        self.assertEqual({flag["name"] for flag in first_d2["active_flags"]}, {"VIN_UV_WARNING", "VIN_UV_FAULT"})

    def test_psu_dump_uses_fixed_record_envelopes_and_v5_timestamp(self):
        payload = [0x6D, 0, 1, 2, 0x3F, 7, 0, 0, 0, 0x20, 0x8E, 1, 0x2B, 0xE2, 0x39, 0xF8, 0x0B, 0, 0, 2, 0x10, 1, 0, 0, 0, 0x6A, 0xB0, 1, 0x9C, 0]
        numbers = [31, 0, 32, 35, 0] + [0, 0, 1, 0x20] + payload + [0]
        psus = parse_psu_dump("a{qay} " + " ".join(str(x) for x in numbers), "v5", "psu_dump.log")
        self.assertEqual(len(psus), 1)
        record = psus[0]["first_four"][0]["decoded"]
        self.assertEqual(record["record_number"], 1)
        self.assertEqual(record["vbulk_volts"], 398)
        self.assertTrue(record["system_timestamp_utc"].endswith(" UTC") or record["system_timestamp_utc"] == "")

    def test_analyze_psu_logs_discovers_sources_and_report_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "psu_log_info").write_text("PSU1 | D0h:04 09 1a 11 00 00 00 01 00 00 00 00 00 00 00 0b 00 00\nPSU1 | D2h:10 00 00 02 0a 00 0c 00 00 00 6d 01 f7 c8 d3 db 17 e2 c0 db fc 13 3f 1a 00\n")
            result = analyze_psu_logs(root, {"type_model": "SR650V3"})
            self.assertTrue(result["available"])
            self.assertEqual(result["platforms"], ["v4"])
            self.assertEqual(result["psus"][0]["name"], "PSU1")
            report = {"id": "psu-test", "format": "v1_v3", "source_file": "psu_log_info", "system": {"type_model": "SR650V3", "serial": ""}, "pci": {"storage": [], "other_drives": []}, "fru": [], "firmware": [], "events": [], "psu_analysis": result}
            html = app.render_psu_analysis(result)
            self.assertIn("PSU Analysis", html)
            self.assertIn("VIN_UV_FAULT", html)
            self.assertIn("<details class='config-details'><summary>Active status flags</summary>", html)
            self.assertNotIn("<details class='config-details' open><summary>Active status flags", html)

    def test_unrecognized_dump_layout_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "psu_dump.log").write_text("a{qay} 1 0 239 35 80 83 85 35 67 82 80 83 32 35 1 35 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 239 237 32 0 0 0 0\n")
            result = analyze_psu_logs(root, {"type_model": "SR650V4"})
            self.assertTrue(result["available"])
            self.assertTrue(any("no documented" in note for note in result["limitations"]))

    def test_direct_psu_log_upload_uses_standalone_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "psu_log_info"
            path.write_text("PSU1 | D0h:04 09 1a 11 00 00 00 01 00 00 00 00 00 00 00 0b 00 00\nPSU1 | D2h:10 00 00 02 0a 00 0c 00 00 00 6d 01 f7 c8 d3 db 17 e2 c0 db fc 13 3f 1a 00\n")
            report = app.analyze_standalone_log(path, cleanup=False)
            self.addCleanup(lambda: __import__("shutil").rmtree(app.REPORT_DIR / report["id"], ignore_errors=True))
            self.assertEqual(report["format"], "standalone_psu")
            self.assertIn("PSU Analysis", app.render_report(report))
            self.assertTrue(app.is_standalone_log_upload(Path("psu_log_info")))


if __name__ == "__main__":
    unittest.main()
