"""Evidence boundaries and bounded nested-support archive regression fixtures."""
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import nic_firmware as nic


def tar_bytes(members, compressed=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz" if compressed else "w") as archive:
        for name, content in members:
            if isinstance(content, tarfile.TarInfo):
                archive.addfile(content)
            else:
                data = content.encode() if isinstance(content, str) else content
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


class NicFirmwareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def test_both_generation_paths_and_vendor_variants_are_discovered(self):
        paths = [
            "V3/pstorage/flash/flash_history.log",
            "V4/pstorage/persist/fm/flash_history.log",
            "V3/tmp/fm.log", "V4/tmp/mctp_trace.log", "V4/var/log/pldm.log",
            "V3/tmp/ibmulog/bmu_fwrpm.log",
            "V4/tmp/ibmulog/brcm-lnvgy_fw_nic_1.2.log",
            "V4/tmp/ibmulog/brcm-lnvgy_fwutl_nic_1.2.log",
            "V4/tmp/ibmulog/mlnx-lnvgy_fw_nic_2.3.log",
        ]
        for path in paths:
            self.write(path, "firmware update observed\n")
        result = nic.collect_nic_firmware_evidence(self.root)
        present = {s["source"] for s in result["log_sources"] if s["available"]}
        self.assertEqual(present, set(paths))
        self.assertEqual(len(result["events"]), len(paths))
        self.assertTrue(all(e["status"] == "Observed" for e in result["events"]))

    def test_bmu_completion_is_support_evidence_and_not_nic_success(self):
        self.write("tmp/ibmulog/bmu_fwrpm.log", "BMU script completed successfully\nexit code=0\ndone\n")
        self.write("tmp/mctp_trace.log", "PLDM firmware update complete\n")
        self.write("tmp/ibmulog/brcm-lnvgy_fw_nic_1.log", "NIC firmware update failed\n")
        result = nic.collect_nic_firmware_evidence(self.root)
        bmu = [event for event in result["events"] if "bmu_fwrpm" in event["source"]]
        self.assertTrue(bmu)
        self.assertTrue(all(event["scope"] == "bmu_support" for event in bmu))
        self.assertTrue(all(event["status"] == "Observed" for event in result["events"]))
        self.assertIn("firmware_transport", {event["scope"] for event in result["events"]})

    def test_shared_vendor_names_do_not_establish_nic_identity(self):
        self.write("tmp/fm.log", "Broadcom RAID firmware update completed successfully\n"
                   "QLogic FC firmware update completed successfully\n"
                   "Mellanox firmware update observed\n"
                   "Broadcom Ethernet firmware update observed\n")
        self.write("tmp/ibmulog/brcm-lnvgy_fw_nic_1.log", "Broadcom update observed\n")
        result = nic.collect_nic_firmware_evidence(self.root)
        shared = [item for item in result["events"] if item["source"] == "tmp/fm.log"]
        self.assertEqual([item["scope"] for item in shared], [
            "firmware_transport", "firmware_transport", "firmware_transport", "nic_firmware"])
        vendor = [item for item in result["events"] if "_nic_" in item["source"]]
        self.assertTrue(vendor)
        self.assertTrue(all(item["scope"] == "nic_firmware" for item in vendor))

    def test_generic_lenovo_support_log_requires_explicit_network_identity(self):
        nested = tar_bytes([("var/log/Lenovo_Support/xxxx.log",
                             "Broadcom firmware update completed\n"
                             "QLogic firmware update completed\n"
                             "Broadcom NIC firmware update completed\n")])
        self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([("lenovobmu.tar", nested)], True))
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual([item["scope"] for item in result["events"]],
                         ["bmu_support", "bmu_support", "nic_firmware"])

    def test_nested_ibmu_and_lenovobmu_logs_are_readable_and_idempotent(self):
        ibmu = tar_bytes([("IBMU.log", "BMU start\nNIC firmware version=1.2\n")])
        lenovo = tar_bytes([("var/log/Lenovo_Support/adapter.log", "Broadcom firmware update\n"),
                            ("var/log/unrelated.log", "not selected")])
        self.write("tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz", tar_bytes([("IBMU.tar", ibmu)], True))
        self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([("lenovobmu.tar", lenovo)], True))
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["archive_members"]), 2)
        self.assertEqual(len(result["events"]), 3)
        for event in result["events"]:
            self.assertTrue(event["source"].startswith("_nic_firmware/"))
            text = (self.root / event["source"]).read_text().splitlines()
            self.assertEqual(text[event["line"] - 1], event["evidence"])
            self.assertIn(".tgz!", result["archive_members"][event["source"]])
            self.assertIn(".tar!", result["archive_members"][event["source"]])
        second = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(result, second)
        self.assertEqual(len(list((self.root / "_nic_firmware").rglob("*.log"))), 2)

    def test_unsafe_names_links_and_devices_are_never_materialized(self):
        sym = tarfile.TarInfo("sym/IBMU.log")
        sym.type, sym.linkname = tarfile.SYMTYPE, "/etc/passwd"
        hard = tarfile.TarInfo("hard/IBMU.log")
        hard.type, hard.linkname = tarfile.LNKTYPE, "IBMU.log"
        device = tarfile.TarInfo("device/IBMU.log")
        device.type = tarfile.CHRTYPE
        unsafe = [("../IBMU.log", "escape"), ("/IBMU.log", "absolute"),
                  ("C:/IBMU.log", "drive"), ("x\\IBMU.log", "backslash"),
                  (sym.name, sym), (hard.name, hard), (device.name, device),
                  ("good/IBMU.log", "NIC evidence\n")]
        self.write("tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz", tar_bytes(unsafe, True))
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["archive_members"]), 1)
        self.assertEqual(result["events"][0]["evidence"], "NIC evidence")
        self.assertEqual(sum("member skipped" in item for item in result["limitations"]), 7)

    def test_materialization_refuses_symlink_output_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "_nic_firmware").symlink_to(outside, target_is_directory=True)
            self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([("IBMU.log", "NIC data")], True))
            result = nic.collect_nic_firmware_evidence(self.root)
            self.assertFalse(result["archive_members"])
            self.assertEqual(list(Path(outside).iterdir()), [])
            self.assertTrue(any("Unable to materialize" in item for item in result["limitations"]))

    def test_discovery_and_files_mapping_reject_symlink_or_outside_sources(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "tmp/ibmulog/bmu_fwrpm.log"
            external.parent.mkdir(parents=True)
            external.write_text("private NIC firmware")
            (self.root / "tmp").symlink_to(Path(outside) / "tmp", target_is_directory=True)
            result = nic.collect_nic_firmware_evidence(self.root, {"external": external,
                         "linked": self.root / "tmp/ibmulog/bmu_fwrpm.log"})
            self.assertFalse(result["events"])
            self.assertTrue(all(not source["available"] for source in result["log_sources"]))

    def test_corrupt_archive_is_reported_without_losing_other_sources(self):
        self.write("tmp/ibmulog/lenovobmu.tgz", b"broken")
        self.write("tmp/fm.log", "NIC firmware start\n")
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["events"]), 1)
        self.assertTrue(any("unreadable" in item for item in result["limitations"]))

    def test_text_limit_preserves_exact_prefix_and_original_line_numbers(self):
        content = "\nNIC firmware start\n" + "x" * 200 + "\nNIC firmware end\n"
        self.write("tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz", tar_bytes([("IBMU.log", content)], True))
        with patch.object(nic, "MAX_TEXT_BYTES", 70):
            result = nic.collect_nic_firmware_evidence(self.root)
        source = next(iter(result["archive_members"]))
        self.assertEqual((self.root / source).read_bytes(), content.encode()[:70])
        self.assertEqual(result["events"][0]["line"], 2)
        entry = next(item for item in result["log_sources"] if item["source"] == source)
        self.assertTrue(entry["truncated"])
        self.assertTrue(any("truncated" in item for item in result["limitations"]))

    def test_archive_decompression_bound_applies_to_unselected_members(self):
        self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([
            ("unselected.bin", b"x" * 100000), ("IBMU.log", "NIC evidence")], True))
        with patch.object(nic, "MAX_ARCHIVE_EXPANDED_BYTES", 20000):
            result = nic.collect_nic_firmware_evidence(self.root)
        self.assertFalse(result["archive_members"])
        self.assertTrue(any("expanded-byte limit" in item for item in result["limitations"]))

    def test_nested_depth_and_member_count_bounds_are_explicit(self):
        nested = tar_bytes([("IBMU.log", "NIC evidence")])
        nested = tar_bytes([("second.tar", nested)])
        self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([("first.tar", nested)], True))
        with patch.object(nic, "MAX_ARCHIVE_DEPTH", 2):
            result = nic.collect_nic_firmware_evidence(self.root)
        self.assertFalse(result["archive_members"])
        self.assertTrue(any("depth limit" in item for item in result["limitations"]))
        with patch.object(nic, "MAX_ARCHIVE_MEMBERS", 1):
            result = nic.collect_nic_firmware_evidence(self.root)
        self.assertFalse(result["archive_members"])
        self.assertTrue(any("member-count limit" in item for item in result["limitations"]))

    def test_archive_size_total_text_and_event_caps_are_explicit(self):
        self.write("tmp/ibmulog/lenovobmu.tgz", b"oversized")
        self.write("tmp/fm.log", "NIC firmware start\n" * 10)
        self.write("var/log/pldm.log", "NIC firmware start\n" * 10)
        with patch.object(nic, "MAX_ARCHIVE_BYTES", 4), patch.object(nic, "MAX_TOTAL_TEXT_BYTES", 60), patch.object(nic, "MAX_EVENTS", 1):
            result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["events"]), 1)
        limitations = "\n".join(result["limitations"])
        self.assertIn("Compressed archive byte limit", limitations)
        self.assertIn("Total text-byte limit", limitations)
        self.assertIn("Event excerpts are bounded", limitations)

    def test_sensitive_configuration_line_not_in_event_summary(self):
        content = ("NIC firmware start\npassword=private\nNIC firmware next\n"
                   "Authorization Bearer hidden-token\nBearer standalone-token\n"
                   "firmware private key hidden-private-key\n"
                   "firmware api_key hidden-api-key\n")
        path = self.write("tmp/fm.log", content)
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual([item["line"] for item in result["events"]], [1, 3])
        self.assertNotIn("private", str(result))
        self.assertNotIn("hidden", str(result))
        self.assertNotIn("standalone-token", str(result))
        self.assertEqual(path.read_text(), content)

    def test_missing_files_are_explicit_and_never_reported_as_failures(self):
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["expected_sources"]), len(nic.EXPECTED_SOURCES))
        self.assertTrue(all(not item["available"] for item in result["expected_sources"]))
        self.assertTrue(all(not item["available"] for item in result["log_sources"]))
        self.assertFalse(result["events"])

    def test_rotated_pldm_log_is_discovered_as_update_evidence(self):
        path = self.write("var/log/pldm.log.1", "PLDM firmware update failed for EID 8\n")
        result = nic.collect_nic_firmware_evidence(self.root)
        source = next(item for item in result["log_sources"] if item["source"] == "var/log/pldm.log.1")
        self.assertTrue(source["available"])
        self.assertEqual(source["category"], "pldm")
        self.assertEqual(result["events"][0]["source"], "var/log/pldm.log.1")
        self.assertEqual(path.read_text(), "PLDM firmware update failed for EID 8\n")

    def test_duplicate_members_preserve_first_evidence_and_record_ambiguity(self):
        self.write("tmp/ibmulog/lenovobmu.tgz", tar_bytes([
            ("IBMU.log", "NIC first\n"), ("IBMU.log", "NIC second\n")], True))
        result = nic.collect_nic_firmware_evidence(self.root)
        self.assertEqual(len(result["archive_members"]), 1)
        self.assertEqual(result["events"][0]["evidence"], "NIC first")
        self.assertTrue(any("Duplicate" in item for item in result["limitations"]))


if __name__ == "__main__":
    unittest.main()
