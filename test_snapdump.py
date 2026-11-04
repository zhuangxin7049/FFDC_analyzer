"""Evidence interpretation and bounded upload regression tests."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import snapdump


def zipped(files, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return stream.getvalue()


def check(result, title):
    return next(item for item in result["checks"] if item["title"] == title)


def legacy_crash(controller="", logical="", physical="", identity=""):
    """Small independent module-format fixture with explicit section boundaries."""
    return ("===SnapDump Generic Info Start===\n" + identity + "\n"
            "===Controller Information===\n"
            "Controller Info: (All values are in hex)\n" + controller + "\n"
            "===SnapDump Generic Info End===\n"
            "===SnapDump LD Info Start===\n" + logical + "\n"
            "===SnapDump LD Info END===\n"
            "===SnapDump PD Info Start===\n" + physical + "\n"
            "===SnapDump PD Info End===\n")


class SnapdumpEvidenceTests(unittest.TestCase):
    def test_missing_fields_are_not_normal_or_critical(self):
        result = snapdump.analyze_snapdump("Summary.txt", b"unrelated text")
        self.assertTrue(all(item["severity"] == "info" for item in result["checks"]))
        self.assertEqual(result["coverage"]["health_fields_present"], 0)
        self.assertTrue(any("Insufficient evidence" in note for note in result["notes"]))
        self.assertIsNone(result["snapshot"]["failed_por"])

    def test_queue_activity_is_not_a_fault(self):
        result = snapdump.analyze_snapdump("renamed.log", b"Outstanding IOs: 57 Pending IOs: 12")
        self.assertEqual(check(result, "I/O queues")["severity"], "info")
        self.assertEqual(result["snapshot"]["outstanding_io"], 57)
        self.assertEqual(check(result, "I/O queues")["evidence"], "renamed.log")

    def test_partial_zero_fields_do_not_pass(self):
        result = snapdump.analyze_snapdump("Summary.txt", b"Outstanding IOs: 0\nActive TM Count: 0")
        self.assertEqual(check(result, "I/O queues")["severity"], "info")
        self.assertEqual(check(result, "Task management and failed I/O")["severity"], "info")

    def test_hex_fields_support_prefix_letters_and_digit_only(self):
        result = snapdump.analyze_snapdump("sample.zip", zipped({
            "Nvram.txt": "FailedPorCount: 0A\nFailedHipCount: 10",
            "IopBase.txt": "IocFaultCode 00008600\nIocFaultCode: 0xABCD\nIocFaultCode=00000000",
        }))
        self.assertEqual(result["snapshot"]["failed_por"], 10)
        self.assertEqual(result["snapshot"]["failed_hip"], 16)
        self.assertEqual(set(result["snapshot"]["ioc_faults"]), {"0x8600", "0xABCD"})
        self.assertEqual(check(result, "NVRAM / IOC fault")["severity"], "critical")

    def test_zero_nvram_requires_ioc_evidence(self):
        result = snapdump.analyze_snapdump("Nvram.txt", b"FailedPorCount: 00\nFailedHipCount: 00")
        self.assertEqual(check(result, "NVRAM / IOC fault")["severity"], "info")
        self.assertIn("IOC faults Unknown", check(result, "NVRAM / IOC fault")["detail"])

    def test_repeated_counter_does_not_hide_later_error(self):
        result = snapdump.analyze_snapdump("PlBase.txt", b"Num HW Errors: 0\nNum HW Errors: 3")
        self.assertEqual(result["snapshot"]["hw_errors"], 3)
        self.assertEqual(check(result, "Hardware and discovery counters")["severity"], "warn")

    def test_backend_speed_is_not_current_host_link(self):
        result = snapdump.analyze_snapdump("CrashDump.txt", b"maxPciLinkSpeed=10 maxPortWidth=8\npciLinkSpeed=1f SasSataSpeed=7")
        self.assertEqual(result["pcie"]["current_speed_code"], "")
        self.assertEqual(result["pcie"]["max_speed_code"], "10")
        result = snapdump.analyze_snapdump("CrashDump.txt", b"pciLinkSpeed=1f\ncurrentPciLinkSpeed=8 currentPortWidth=8")
        self.assertEqual(result["pcie"]["current_speed_code"], "8")

    def test_faultcode_does_not_override_explicit_ondemand_evidence(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "Summary.txt": "SNAPDUMPI_FAILURE_TYPE_ONDEMAND",
            "CrashDump.txt": "SnapDump for FaultCode 0x8600\nRelease Level: ALPHA",
            "Cpu.txt": "SnapDump trigger not due to any Fault, hence no associated CPU reg dump",
        }))
        self.assertEqual(check(result, "Snapshot trigger")["severity"], "ok")
        self.assertEqual(check(result, "Firmware release level")["severity"], "warn")
        self.assertFalse(any(item["severity"] == "critical" for item in result["checks"]))

    def test_standalone_crash_identity(self):
        result = snapdump.analyze_snapdump("export.log", b"BoardName: 460-16e HBA\nVer Name: 8.19.0\nPackage Ver Name: 8.19.package")
        self.assertEqual(result["firmware"]["version"], "8.19.0")
        self.assertEqual(result["firmware"]["board"], "460-16e HBA")
        self.assertFalse(result["coverage"]["complete"])

    def test_raw_logs_are_not_in_public_response(self):
        result = snapdump.analyze_snapdump("Summary.txt", b"private text")
        self.assertNotIn("_file_text", snapdump.public_result(result))


class LegacySnapdumpEvidenceTests(unittest.TestCase):
    def test_multiple_objects_keep_their_states_and_exclude_ses(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "nested/crashDump.txt": legacy_crash(
                "ldPresentCount=2, ldDegradedCount=1, ldOfflineCount=0\n"
                "pdDiskPresentCount=2, pdDiskFailedCount=0, pdDiskPredFailureCount=0",
                logical="Ld =0 LdTargetId=0\n Level 1\n Status 2 (DEGRADED)\n"
                        " state=2(DEGRADED)\n"
                        "Ld =1 LdTargetId=1\n Level 0\n Status 3 (OPTIMAL)\n"
                        " state=3(OPTIMAL)",
                physical="PD=02 infoPtr=1\n scsiType=0, state=18(ONLINE)\n"
                         " mediaErrCount=0, otherErrCount=2, predFailCount=0\n"
                         "PD=0e infoPtr=2\n scsiType=d, state=0(UNCONFIGURED_GOOD)\n"
                         " productIdentification=VirtualSES\n"
                         " mediaErrCount=ff, otherErrCount=ff, predFailCount=ff\n"
                         "PD=03 infoPtr=3\n scsiType=0, state=0(UNCONFIGURED_GOOD)\n"
                         " mediaErrCount=0, otherErrCount=0, predFailCount=0",
            ),
        }))
        self.assertEqual(result["format"]["id"], "megaraid_legacy")
        self.assertEqual([(d["id"], d["raid_level"], d["state"]) for d in result["logical_drives"]],
                         [("0", "1", "DEGRADED"), ("1", "0", "OPTIMAL")])
        self.assertEqual([(d["id"], d["state"]) for d in result["physical_drives"]],
                         [("02", "ONLINE"), ("03", "UNCONFIGURED_GOOD")])
        self.assertEqual(check(result, "Logical drive state")["severity"], "warn")
        self.assertEqual(check(result, "Logical drive state")["evidence"], "nested/crashDump.txt")
        self.assertEqual(check(result, "Physical disk state")["severity"], "ok")
        self.assertNotIn("PD 0e", check(result, "Physical disk error counters")["detail"])

    def test_offline_second_ld_is_not_hidden_by_optimal_first_ld(self):
        crash = legacy_crash(logical="Ld =0\n Level 0\n Status 3 (OPTIMAL)\n"
                                      "Ld =1\n Level 1\n Status 0 (OFFLINE)")
        result = snapdump.analyze_snapdump("crashDump.txt", crash.encode())
        self.assertEqual(check(result, "Logical drive state")["severity"], "critical")
        self.assertEqual(result["logical_drives"][1]["state"], "OFFLINE")

    def test_controller_and_disk_counts_are_hexadecimal(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "crashDump.txt": legacy_crash(
                "ldPresentCount=10, ldDegradedCount=0A, ldOfflineCount=0\n"
                "pdDiskPresentCount=20, pdDiskFailedCount=00, pdDiskPredFailureCount=0xA\n"
                "memCorrectableErrorCount=0f, memUnCorrectableErrorCount=0",
                physical="PD=02\n scsiType=0, state=18(ONLINE)\n"
                         " mediaErrCount=0A, otherErrCount=10, predFailCount=0x0B",
            ),
            "NVRAM_MODULE.txt": "CtrlResetCount 10",
        }))
        snapshot = result["snapshot"]
        self.assertEqual((snapshot["ld_present"], snapshot["ld_degraded"], snapshot["pd_disks"]),
                         (16, 10, 32))
        self.assertEqual(snapshot["pd_predictive"], 10)
        self.assertEqual(snapshot["mem_correctable"], 15)
        disk = result["physical_drives"][0]
        self.assertEqual((disk["media_errors"], disk["other_errors"], disk["predictive_failures"]),
                         (10, 16, 11))
        self.assertEqual(snapshot["controller_resets"], "10")
        self.assertEqual(check(result, "Controller reset counter")["severity"], "warn")

    def test_missing_fields_never_become_zero_or_normal(self):
        result = snapdump.analyze_snapdump("crashDump.txt", legacy_crash().encode())
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["health_fields_present"], 0)
        self.assertTrue(all(item["severity"] == "info" for item in result["checks"]))
        for field in ("ld_present", "ld_degraded", "ld_offline", "pd_disks", "pd_failed",
                      "pd_predictive", "outstanding_io", "pending_io", "controller_resets"):
            self.assertIsNone(result["snapshot"][field], field)

    def test_partial_queue_and_disk_counters_do_not_pass(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "crashDump.txt": legacy_crash("ldDegradedCount=0, pdDiskFailedCount=0"),
            "PL_MODULE.txt": "Total Outstanding IOs: 0",
        }))
        for title in ("I/O queues", "Logical drive state", "Physical disk state"):
            self.assertEqual(check(result, title)["severity"], "info", title)
        self.assertIsNone(result["snapshot"]["pending_io"])

    def test_history_never_replaces_current_identity_or_drive_state(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "crashDump.txt": legacy_crash(
                'productName=Current RAID, serialNo=sample\nFW packageVersion=""',
                identity="Firmware version 5.320.current built on Aug 19 2025 at 17:26:56\n"
                         "driverVersion=--NA--",
                logical="Ld =0\n Level 1\n Status 2 (DEGRADED)",
            ),
            "TTY.txt": "Firmware version 1.0.OLD built on Jan 1 2020 at 00:00:00\n"
                       "Package Version: old-package\ndriverVersion=old-driver\n"
                       "Ld =0\n Level 1\n Status 3 (OPTIMAL)",
            "event_dump.txt": "EVT#00001-T0: 100=Firmware version 0.9.OLDER\n"
                              "EVT#00002-T1: 100=VD 0 is now OPTIMAL",
        }))
        self.assertEqual(result["firmware"]["version"], "5.320.current")
        self.assertEqual(result["firmware"]["board"], "Current RAID")
        self.assertEqual(result["firmware"]["package"], "")
        self.assertEqual(result["firmware"]["driver"], "")
        self.assertEqual(result["logical_drives"][0]["state"], "DEGRADED")
        self.assertEqual(check(result, "Logical drive state")["severity"], "warn")

    def test_faultcode_header_is_raw_evidence_not_a_crash_verdict(self):
        header = ("SnapDump for faultingModule 0 bmp 1df6f faultFunc 0 "
                  "FaultCode 1 SnapArg 0 taken at 08/21/25  3:40:35")
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "crashDump.txt": header + "\n" + legacy_crash(),
            "TTY.txt": "08/21/25  3:40:34.497: C0:SnapDumpDcmd: Trigger SnapDump",
        }))
        self.assertEqual(result["trigger"], header)
        self.assertEqual(check(result, "Snapshot trigger")["severity"], "info")
        self.assertEqual(result["snapshot"]["ioc_faults"], [])
        self.assertFalse(any(item["severity"] == "critical" for item in result["checks"]))

    def test_relative_and_calendar_events_are_both_preserved(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "crashDump.txt": legacy_crash(),
            "event_dump.txt": "EVT#00001-T0: 638=Controller reset type POWERON RESET is detected\n"
                              "EVT#00002-T6.250: 100=Firmware initialization started\n"
                              "EVT#00003-08/21/25  3:18:42: 389=Host driver is loaded and operational\n",
        }))
        self.assertEqual(result["events"]["total_count"], 3)
        self.assertEqual([event["time"] for event in result["events"]["events"]],
                         ["T0", "T6.250", "08/21/25  3:18:42"])
        self.assertEqual(result["events"]["counts"]["driver_loaded"], 1)
        self.assertIsNone(result["snapshot"]["controller_resets"])
        self.assertEqual(check(result, "Controller reset counter")["severity"], "info")

    def test_explicit_module_sections_are_not_overridden_by_generic_summary(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "Summary.txt": "SNAPDUMP TYPE\n-----------\nOnDemand",
            "crashDump.txt": legacy_crash(logical="Ld =0\n Level 1\n Status 2 (DEGRADED)"),
        }))
        self.assertEqual(result["format"]["id"], "megaraid_legacy")
        self.assertEqual(result["logical_drives"][0]["state"], "DEGRADED")

    def test_spaced_state_fields_stay_with_their_object(self):
        crash = legacy_crash(
            logical="Ld =0\n Level 1\n state = 2 (DEGRADED)\n"
                    "Ld =1\n Level 0\n state = 3 (OPTIMAL)",
            physical="PD = 02\n scsiType=0, state = 18 (ONLINE)\n"
                     "PD = 03\n scsiType=0, state = 0 (UNCONFIGURED_GOOD)",
        )
        result = snapdump.analyze_snapdump("crashDump.txt", crash.encode())
        self.assertEqual([item["state"] for item in result["logical_drives"]], ["DEGRADED", "OPTIMAL"])
        self.assertEqual([item["state"] for item in result["physical_drives"]], ["ONLINE", "UNCONFIGURED_GOOD"])

    def test_mpi3_section_format_keeps_its_own_health_fields(self):
        result = snapdump.analyze_snapdump("modern.zip", zipped({
            "Summary.txt": "SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nOutstanding IOs: 0\nPending IOs: 0\n"
                           "Active TM Count: 0\ngDmIoFailedList Count: 0",
            "CrashDump.txt": "Ver Name: 8.19.current\nBoardName: 460-16e HBA",
            "Cpu.txt": "SnapDump trigger not due to any Fault, hence no associated CPU reg dump",
            "Nvram.txt": "FailedPorCount: 0\nFailedHipCount: 0",
            "PlBase.txt": "Num HW Errors: 0\nNum Hard Resets: 0\nSAS Device Discovery Error Event Counter: 0",
            "DmBase.txt": "Topology Error Present: 0\nIs Topo Error Critical: 0",
            "IopBase.txt": "IocFaultCode 00000000",
        }))
        self.assertEqual(result["format"]["id"], "mpi3")
        self.assertEqual(result["firmware"]["version"], "8.19.current")
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(check(result, "Snapshot trigger")["severity"], "ok")
        self.assertEqual(check(result, "NVRAM / IOC fault")["severity"], "ok")
        self.assertNotIn("ld_degraded", result["snapshot"])


class SnapdumpUploadTests(unittest.TestCase):
    def test_binary_and_unsafe_paths_are_not_parsed(self):
        result = snapdump.analyze_snapdump("dump.zip", zipped({
            "nested/Summary.txt": "Outstanding IOs: 0 Pending IOs: 0",
            "raw.bin": b"\x00\xff",
            "../Nvram.txt": "FailedPorCount: FF",
        }))
        self.assertEqual(result["file_count"], 1)
        self.assertIsNone(result["snapshot"]["failed_por"])

    def test_binary_with_text_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Binary content"):
            snapdump.analyze_snapdump("dump.zip", zipped({"Summary.txt": b"abc\x00def"}))

    def test_corrupt_zip_crc_becomes_readable_error(self):
        raw = zipped({"Summary.txt": "unique-payload"})
        raw = raw.replace(b"unique-payload", b"broken-payload")
        with self.assertRaisesRegex(ValueError, "Cannot read the SnapDump ZIP"):
            snapdump.analyze_snapdump("dump.zip", raw)

    def test_corrupt_zip_header_becomes_readable_error(self):
        with self.assertRaisesRegex(ValueError, "Cannot read the SnapDump ZIP"):
            snapdump.analyze_snapdump("dump.zip", b"not a zip")

    def test_entry_decompression_limit(self):
        with patch.object(snapdump, "MAX_FILE_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "decompression limit"):
                snapdump.analyze_snapdump("dump.zip", zipped({"Summary.txt": "x" * 101}, zipfile.ZIP_DEFLATED))

    def test_aggregate_decompression_limit(self):
        with patch.object(snapdump, "MAX_TOTAL_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "total decompression limit"):
                snapdump.analyze_snapdump("dump.zip", zipped({"Summary.txt": "x" * 60, "Cpu.txt": "y" * 60}, zipfile.ZIP_DEFLATED))

    def test_standalone_limit_rejects_instead_of_truncating(self):
        with patch.object(snapdump, "MAX_FILE_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "Standalone text"):
                snapdump.analyze_snapdump("Summary.txt", b"x" * 101)

    def test_no_supported_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No supported text"):
            snapdump.analyze_snapdump("dump.zip", zipped({"image.png": b"abc"}))


class RealSnapdumpTests(unittest.TestCase):
    @unittest.skipUnless(Path("/Users/mr.wen/Downloads/snapdump_c0_id1_2025_08_21_03_40_44.zip").is_file(),
                         "Local MegaRAID real-dump fixture unavailable")
    def test_real_b540p_module_snapshot(self):
        path = Path("/Users/mr.wen/Downloads/snapdump_c0_id1_2025_08_21_03_40_44.zip")
        result = snapdump.analyze_snapdump(path.name, path.read_bytes())
        self.assertEqual(result["format"]["id"], "megaraid_legacy")
        self.assertEqual(result["firmware"]["board"], "RAID B540p-2HS")
        self.assertEqual(result["firmware"]["version"], "5.320.04-4206-TEST-SCHAPARA-0529")
        self.assertEqual(result["firmware"]["driver"], "")
        self.assertEqual(result["firmware"]["package"], "")
        self.assertEqual(result["logical_drives"], [{"id": "0", "raid_level": "1", "state": "DEGRADED"}])
        self.assertEqual(len(result["physical_drives"]), 1)
        self.assertEqual(result["physical_drives"][0]["id"], "02")
        self.assertEqual(result["physical_drives"][0]["state"], "ONLINE")
        self.assertEqual(result["physical_drives"][0]["other_errors"], 2)
        self.assertEqual(result["snapshot"]["ld_degraded"], 1)
        self.assertEqual(result["snapshot"]["ld_offline"], 0)
        self.assertEqual(result["snapshot"]["pd_disks"], 1)
        self.assertEqual(result["snapshot"]["outstanding_io"], 0)
        self.assertEqual(result["snapshot"]["pending_io"], 0)
        self.assertEqual(check(result, "Logical drive state")["severity"], "warn")
        self.assertEqual(check(result, "Snapshot trigger")["severity"], "info")
        self.assertIn("FaultCode 1", result["trigger"])
        self.assertTrue(result["coverage"]["complete"])
        self.assertGreater(result["events"]["total_count"], 80)

    @unittest.skipUnless(Path("/tmp/460-snapdump-current.zip").is_file(), "Local real-dump fixture unavailable")
    def test_real_460_snapshot(self):
        path = Path("/tmp/460-snapdump-current.zip")
        result = snapdump.analyze_snapdump(path.name, path.read_bytes())
        self.assertEqual(result["firmware"]["board"], "460-16e HBA")
        self.assertEqual(result["firmware"]["release_level"], "ALPHA")
        self.assertEqual(result["pcie"]["current_speed_code"], "8")
        self.assertEqual(result["snapshot"]["ioc_faults"], [])
        self.assertTrue(result["snapshot"]["cpu_no_fault"])
        self.assertEqual(result["snapshot"]["failed_por"], 0)
        self.assertTrue(result["coverage"]["complete"])
        self.assertFalse(any(item["severity"] == "critical" for item in result["checks"]))


if __name__ == "__main__":
    unittest.main()
