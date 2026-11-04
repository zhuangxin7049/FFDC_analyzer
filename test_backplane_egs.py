"""EGS/Genoa SEP profiles from the supplied v0.81 reference."""
import json
import unittest

import app


EGS = {
    "40": ("E2142100", "SEP 4MW", "SAS/SATA/NVMe", "egs_anybay"),
    "42": ("100A11A0", "SEP 8SW", "SAS/SATA", "egs_sas_sata"),
    "44": ("E2142100", "SEP 4MEG", "SAS/SATA/NVMe", "egs_anybay"),
    "45": ("E2142100", "SEP 8EEG", "EDSFF", "egs_edsff"),
    "49": ("E2142100", "SEP 2MEG", "SATA/NVMe", "egs_2meg"),
}


def capture(app_id, values, *, silicon=None, start=0, configuration=1,
            communication=0xD3, enabled=0xBE, result=0):
    silicon = silicon or EGS[app_id][0]
    ctrl = [0] * 32
    ctrl[:4] = [0x50, 0x53, 0x6F, 0x43]
    ctrl[4:8] = list(bytes.fromhex(silicon))
    ctrl[8] = 0x26
    ctrl[12:15] = [result, configuration, enabled]
    ctrl[16] = int(app_id, 16)
    ctrl[23:25] = [len(values), start]
    ctrl[26] = 7
    n = len(values)
    status = [0x26, n, (-0x26 - n) & 0xFF, communication, *values, 4, 0x13]
    status.append((-sum(status[3:])) & 0xFF)
    extended = [0x81] * n
    status.extend(extended)
    status.append((-sum(extended)) & 0xFF)
    lines = []
    for name, data in (("ctrl", ctrl), ("status", status)):
        lines.append(f"#cio -n bp1_sep0_{name} -m block -t wr 32 0")
        lines.extend(app.split_v4_register_dump(" ".join(f"{value:02X}" for value in data)))
    return app.parse_sep_info("\n".join(lines), "v1_v3")


class EgsGenoaSepTests(unittest.TestCase):
    def test_all_requested_egs_apids_select_their_own_profile(self):
        cases = {
            "40": (0xC0, 0xC3),
            "42": (0x80, 0x83),
            "44": (0xC1, 0xC3),
            "45": (0xC2, 0xC0),
            "49": (0xC0, 0xC1),
        }
        for app_id, values in cases.items():
            with self.subTest(app_id=app_id):
                ctrl, status = capture(app_id, values)
                self.assertEqual(ctrl["decode_profile"], "egs_genoa")
                self.assertEqual(ctrl["application"], EGS[app_id][1])
                self.assertEqual(ctrl["bp_capability"], EGS[app_id][2])
                self.assertEqual(status["status_profile"], EGS[app_id][3])
                self.assertEqual(status["data_validation"]["profile"], "egs_genoa")
                self.assertTrue(status["diagnostics_valid"])
                self.assertFalse(status["unknown_slots"])

    def test_egs_edsff_uses_v081_c2_c0_80_encoding(self):
        rows = capture("45", (0xC2, 0xC0, 0x80))
        status = rows[1]
        self.assertIn("EDSFF x4 Drive Installed", status["slot_status"])
        self.assertIn("EDSFF x8 Drive Installed", status["slot_status"])
        self.assertIn("EDSFF x16 Drive Installed", status["slot_status"])
        self.assertNotIn("Unknown", status["slot_status"])

    def test_egs_c4_type_fault_is_actionable_only_on_sas_nvme_profiles(self):
        for app_id in ("40", "44", "45", "49"):
            with self.subTest(app_id=app_id):
                rows = capture(app_id, (0xC4,))
                status = rows[1]
                self.assertEqual(status["bp_type_fault_slots"], "0")
                self.assertTrue(any("BP type fault indication" in json.dumps(check)
                                    for check in app.run_automated_checks({
                                        "id": "egs-test", "format": "v1_v3", "system": {}, "firmware": [],
                                        "source_file": "test", "files": {}, "events": [], "fru": [],
                                        "pci": {"adapters": [], "storage": []}, "sep_info": rows,
                                        "sep_vpd": [], "backplane_scope": {"applicable": True},
                                    })))
        for app_id in ("42",):
            with self.subTest(app_id=app_id):
                rows = capture(app_id, (0xC4,))
                self.assertFalse(rows[1]["bp_type_fault_slots"])
                self.assertEqual(rows[1]["unknown_slots"], "0")
                self.assertTrue(rows[1]["slot_observations"][0]["limitations"])

    def test_egs_identity_mismatch_is_not_decoded_as_a_sibling_layout(self):
        rows = capture("42", (0x80,), silicon="E2142100")
        ctrl, status = rows
        self.assertNotEqual(ctrl["decode_profile"], "egs_genoa")
        self.assertFalse(status["diagnostics_valid"])
        self.assertFalse(status["fail_slots"])
        self.assertTrue(status["slot_observations"][0]["limitations"])

    def test_egs_slot_capacity_is_enforced(self):
        rows = capture("49", (0xC0, 0xC1, 0xC3))
        status = rows[1]
        self.assertFalse(status["diagnostics_valid"])
        self.assertIn("exceeds this EGS/Genoa SEP application", json.dumps(status))
        self.assertFalse(status["fail_slots"])


if __name__ == "__main__":
    unittest.main()
