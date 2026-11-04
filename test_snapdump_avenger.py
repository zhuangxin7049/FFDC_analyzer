"""Avenger document-derived relationships and their uncertainty boundaries."""
import unittest
import json

from snapdump import analyze_snapdump, public_result
from snapdump_avenger import configuration, controller_identity, device_mapping, host_functions, operating_mode
from snapdump_chat import build_snapdump_chat, verified_snapdump_answer
from test_snapdump import zipped


def modern(extra=None, mode="IOPI_FW_OPMODE_PERFIT", identity="ChipName: SAS4116W\ncurrent personality 0\nOEM/ProfileIdentifier: 1/3\n"):
    files = {"Summary.txt": "SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nFwMode: " + mode + "\n",
             "CrashDump.txt": "Ver Name: 8.19\n" + identity}
    files.update(extra or {})
    return analyze_snapdump("test.zip", zipped(files))


TABLE = "DEVICE PERSISTENT TABLE: devprstSlots 80\nIndex EnclD PerID NumPrstIDs StSlot NE PE PH IsEx IsR MsgCnt SesP ChnI MPI\n"
ROW = "0 500e0eca0a295200 100 12 0 ff 0 f000 0 1 1 f 0 ff ff\n"


def pd(pid="105", slot="5", scsi="0"):
    return (f"PD={pid} infoPtr=1234\n  scsiType={scsi}, state=0(UNCONFIGURED_GOOD) enclid 111\n"
            f"enclIndex = 2, slotNumber = {slot}, enclDeviceId = 111\n"
            "productIdentification=ExampleDisk\nserialNumber=SN-12345\n"
            "mediaErrCount=0 otherErrCount=0 predFailCount=0\n")


class OperatingModeTests(unittest.TestCase):
    def test_profile_pairs(self):
        for personality, profile, expected in [(0, 0, "PerfIT"), (0, 3, "PerfIT"), (0, 4, "PerfIT"),
                                               (0, 1, "EVP"), (0, 2, "FeatureHBA"), (2, 0, "RAID")]:
            with self.subTest(profile=profile, personality=personality):
                mode = operating_mode({"CrashDump.txt": f"ChipName: SAS4116W\ncurrent personality {personality}\nOEM/ProfileIdentifier: 1/{profile}\n"})
                self.assertEqual(mode["name"], expected)
                self.assertEqual(mode["raid_counts_applicable"], expected in {"RAID", "EVP"})

    def test_unknown_runtime_and_profile_are_unverified(self):
        self.assertEqual(modern(mode="IOPI_FW_OPMODE_FUTURE")["operating_mode"]["name"], "Unverified")
        result = modern(mode="", identity="current personality 0\nOEM/ProfileIdentifier: 1/f\n")
        self.assertEqual(result["operating_mode"]["name"], "Unverified")

    def test_history_candidates_do_not_supply_current_profile(self):
        result = modern({"Tty.txt": "Board Data ProfileId: 01 Pers:00\nRunning with Personality 0, profileID 1\n"},
                        identity="current personality 0\n")
        self.assertEqual(result["operating_mode"]["name"], "PerfIT")
        self.assertEqual(result["operating_mode"]["profile_id"], "")

    def test_conflicting_snapshot_disables_managed_counts(self):
        result = modern(mode="IOPI_FW_OPMODE_RAID")
        self.assertTrue(result["operating_mode"]["conflict"])
        self.assertFalse(result["operating_mode"]["raid_counts_applicable"])
        self.assertTrue(any(c["title"] == "Operating mode conflict" for c in result["checks"]))

    def test_evp_enables_counts_and_perfit_does_not(self):
        crash = ("Ver Name: 8.19\ncurrent personality 0\nOEM/ProfileIdentifier: 1/1\n"
                 "Ld/PD device counts:\nldPresentCnt=2 ldDegradedCnt=1 ldOfflineCnt=0\n"
                 "pdDiskPresentCnt=a pdDiskFailedCnt=0 pdDiskPredFailureCnt=0\nAdapter Status:\n")
        result = modern({"CrashDump.txt": crash, "Pd.txt": pd()}, mode="IOPI_FW_OPMODE_EVP")
        self.assertEqual(result["snapshot"]["pd_disks"], 10)
        self.assertEqual(result["snapshot"]["ld_degraded"], 1)
        self.assertEqual(result["operating_mode"]["name"], "EVP")
        self.assertNotIn("mem_correctable", result["snapshot"])
        self.assertFalse(any(c["title"] == "Memory error counters" for c in result["checks"]))
        result = modern({"CrashDump.txt": crash.replace("1/1", "1/3"), "Pd.txt": pd()})
        self.assertNotIn("pd_disks", result["snapshot"])
        self.assertEqual(len(result["device_mapping"]["devices"]), 1)

    def test_av2_profile_does_not_conflict_with_explicit_runtime(self):
        result = modern(mode="IOPI_FW_OPMODE_RAID", identity="ChipName: SAS5116W\ncurrent personality 0\nOEM/ProfileIdentifier: 1/3\n")
        self.assertEqual(result["operating_mode"]["name"], "RAID")
        self.assertFalse(result["operating_mode"]["profile_table_applicable"])
        self.assertFalse(result["operating_mode"]["external_ddr_applicable"])
        self.assertFalse(result["operating_mode"]["conflict"])

    def test_unknown_and_av2_chips_cannot_use_av1_profile_fallback(self):
        for chip in ("", "SAS5032W", "SAS5116W", "SASFUTURE"):
            mode = operating_mode({"CrashDump.txt": f"ChipName: {chip}\ncurrent personality 0\nOEM/ProfileIdentifier: 1/1\n"})
            self.assertEqual(mode["name"], "Unverified")
            self.assertFalse(mode["raid_counts_applicable"])

    def test_identity_uses_snapshot_and_separates_roc_ioc(self):
        for chip, generation, role in [("SAS4116W", "AV1", "RoC"), ("SAS4016", "AV1", "IOC"),
                                       ("SAS5032W", "AV2", "IOC"), ("SAS5116W", "AV2", "RoC")]:
            identity = controller_identity({"CrashDump.txt": f"ChipName: {chip}\nBoardName: Example\nBoardTracerNumber: ABC123\n", "Tty.txt": "ChipName: SAS4116W\n"})
            self.assertEqual((identity["generation"], identity["chip_role"]), (generation, role))
            self.assertEqual(identity["board_tracer"], "ABC123")
        self.assertEqual(controller_identity({"Tty.txt": "ChipName: SAS4116W\n"})["generation"], "Unverified")

    def test_identity_conflicts_disable_mode_checks(self):
        result = modern(identity="ChipName: SAS5032W\nChipName: SAS4116W\n")
        self.assertTrue(result["controller_identity"]["conflict"])
        self.assertEqual(result["operating_mode"]["name"], "Unverified")
        self.assertFalse(result["operating_mode"]["raid_counts_applicable"])

    def test_only_av1_roc_raid_uses_external_memory_counters(self):
        counts = ("Ld/PD device counts:\nldPresentCnt=1 ldDegradedCnt=0 ldOfflineCnt=0\n"
                  "pdDiskPresentCnt=2 pdDiskFailedCnt=0 pdDiskPredFailureCnt=0\n"
                  "memCorrectableErrCnt=0 memUnCorrectableErrCnt=0\nAdapter Status:\n")
        for chip, memory in [("SAS4116W", True), ("SAS5032W", False), ("SAS5116W", False), ("", False)]:
            result = modern({"CrashDump.txt": f"Ver Name: 8.19\nChipName: {chip}\n" + counts}, mode="IOPI_FW_OPMODE_RAID")
            self.assertEqual("mem_correctable" in result["snapshot"], memory)
            self.assertEqual(any(c["title"] == "Memory error counters" for c in result["checks"]), memory)
            self.assertEqual(result["snapshot"]["pd_disks"], 2)


HOST = ("---------------Host Interface Information----------------\n"
        "IocEnabled 000000000000000f MurActive 0000000000000000\n"
        "NumPceFunc : MPI 04 NVMe 00\nMaxSupportedIocCount 04\n\n"
        "ioc 00:\nFlags 0 IocFaultCode 00000000\nMaxMsixVec 0101 MaxOpQueues 0100\n"
        "ShutdownData 00 IocState 00\nEtpDevIndex 05 EtpDevType 02 BusNum 23 DeviceFunc 00\n"
        "ioc 01:\nFlags 0 IocFaultCode 00000000\nEtpDevType 02 BusNum 24 DeviceFunc 00\n"
        "*** Generic Config ***\nNumberOfIocs: 1\n")


class HostFunctionTests(unittest.TestCase):
    def test_multiple_iocs_are_not_a_physical_card_count(self):
        functions = host_functions({"IopBase.txt": HOST})
        self.assertEqual([f["ioc_index"] for f in functions["functions"]], [0, 1])
        self.assertEqual(functions["summary"]["mpi_functions_reported"], 4)
        self.assertEqual(functions["summary"]["IocEnabled"], 15)
        self.assertEqual(functions["functions"][1]["raw_fields"]["BusNum"], 0x24)
        self.assertEqual(functions["generic_ioc_counters"][0]["raw"], "1")
        self.assertIsNone(functions["physical_card_count"])
        self.assertEqual(functions["functions"][0]["role"], "Unverified")
        sources = functions["evidence"] + [g["source"] for g in functions["generic_ioc_counters"]]
        sources += [r for f in functions["functions"] for r in f["sources"]]
        for s in sources:
            self.assertEqual(s["excerpt"], "\n".join(HOST.splitlines()[s["start_line"] - 1:s["end_line"]]))

    def test_tty_and_queue_fragments_do_not_create_functions(self):
        functions = host_functions({"Tty.txt": HOST, "IopBase.txt": "IOC 3 Q be Reply\nNumberOfIocs: 1\n"})
        self.assertEqual(functions["functions"], [])
        self.assertEqual(functions["summary"], {})

    def test_duplicate_iop_files_do_not_merge_cards(self):
        self.assertEqual(host_functions({"c0/IopBase.txt": HOST, "c1/IopBase.txt": HOST})["functions"], [])

    def test_davy_reopens_function_header_and_both_counter_scopes(self):
        result = modern({"IopBase.txt": HOST}, identity="ChipName: SAS5032W\nBoardName: 460-16e HBA\n")
        _, prompt, sources = build_snapdump_chat(result, "为什么有多个 IOC 功能？NumberOfIocs 是什么？")
        self.assertTrue(any("NumPceFunc : MPI 04" in s["excerpt"] for s in sources))
        self.assertTrue(any("ioc 01:" in s["excerpt"] and "BusNum 24" in s["excerpt"] for s in sources))
        self.assertTrue(any("NumberOfIocs: 1" in s["excerpt"] for s in sources))
        self.assertIn("SAS5032W is AV2 IOC", prompt)
        self.assertIn("noncontiguous DSN is valid", prompt)

    def test_verified_function_answer_keeps_generic_semantics_and_states_unverified(self):
        result = modern({"IopBase.txt": HOST}, identity="ChipName: SAS5032W\nBoardName: 460-16e HBA\n")
        for question in ("为什么有多个IOC功能？NumberOfIocs 是什么？", "Explain multiple IOC functions and NumberOfIocs"):
            _, _, sources = build_snapdump_chat(result, question)
            answer = verified_snapdump_answer(result, question, sources)
            self.assertIn("SAS5032W", answer)
            self.assertIn("AV2 / IOC", answer)
            self.assertIn("IocState=0x0", answer)
            self.assertIn("NumberOfIocs: 1", answer)
            self.assertNotIn("均为正常", answer)
            self.assertNotIn("仅有一个 IOC 实例", answer)
            self.assertIsNone(verified_snapdump_answer(result, question, []))


class PersistentMappingTests(unittest.TestCase):
    def test_verified_device_answer_calculates_hex_range_end_and_does_not_infer_slot(self):
        row = ROW.replace(" 100 12 0 ", " 165 12 ff ")
        result = modern({"DevPrst.txt": TABLE + row, "Pd.txt": pd("16e", "10").replace("enclDeviceId = 111", "enclDeviceId = 176")})
        question = "PD 0x16e 的 enclosure、槽位、型号和 Persistent ID 范围是什么？"
        _, _, sources = build_snapdump_chat(result, question)
        answer = verified_snapdump_answer(result, question, sources)
        self.assertIn("0x176 (374 decimal)", answer)
        self.assertIn("16 (0x10)", answer)
        self.assertIn("0x165–0x176", answer)
        self.assertIn("18 IDs (`0x12`)", answer)
        self.assertIn("offset 9", answer)
        self.assertIn("范围偏移不是物理槽号", answer)
        self.assertIsNone(verified_snapdump_answer(result, question, []))

    def test_diagnosis_and_legacy_do_not_use_fixed_fact_answer(self):
        result = modern({"Pd.txt": pd()})
        for question in ("PD 0x105 的槽位错误是什么故障？", "What failed on PD 0x105 in this slot?", "Give PD 0x105 firmware and model", "Enable IOC functions", "What is PD 0x999 slot?"):
            _, _, sources = build_snapdump_chat(result, question)
            self.assertIsNone(verified_snapdump_answer(result, question, sources))
        self.assertIsNone(verified_snapdump_answer({"format": {"id": "megaraid_legacy"}}, "PD 0x105 slot?", []))

    def test_davy_targeted_ids_keep_hex_numeric_enclosure_and_slot_bases(self):
        result = modern({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd().replace("enclid 111", "enclid 176").replace("enclDeviceId = 111", "enclDeviceId = 176")})
        messages, prompt, sources = build_snapdump_chat(result, "PD 0x105 的 enclosure、槽位、Persistent ID 是什么？")
        evidence = json.loads(messages[0]["content"].split("\n", 1)[1])
        fact = evidence["metadata"]["avenger"]["requested_device_facts"][0]
        self.assertEqual(fact["pd_id_hex"], "0x105")
        self.assertEqual((fact["enclosure_id_hex"], fact["enclosure_id_decimal"]), ("0x176", 374))
        self.assertEqual(fact["observed_slot_decimal"], 5)
        self.assertIn("PD=16e line supplies", prompt)
        self.assertIn("not decimal 176", prompt)
        self.assertTrue(any("PD=105" in s["excerpt"] and "enclDeviceId = 176" in s["excerpt"] for s in sources))

    def test_two_word_phy_and_hex_range_slot_join(self):
        mapping = device_mapping({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd() + pd("110", "ffff", "d")})
        self.assertEqual(mapping["ranges"][0]["phy_bitmap_words"], ["f000", "0"])
        disk, ses = mapping["devices"]
        self.assertEqual((disk["slot"], disk["range_id_offset"], disk["persistent_id"]), (5, 5, 0x105))
        self.assertIsNone(disk["range_slot"])
        self.assertEqual(disk["enclosure_id"], 0x111)
        self.assertEqual(disk["serial"], "SN-12345")
        self.assertEqual(disk["range_status"], "range candidate")
        self.assertEqual(ses["kind"], "SES")
        self.assertIsNone(ses["slot"])

    def test_different_physical_slot_is_not_a_range_conflict(self):
        mapping = device_mapping({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd(slot="a")})
        disk = mapping["devices"][0]
        self.assertEqual(disk["slot"], 10)
        self.assertEqual(disk["range_status"], "range candidate")
        self.assertIsNone(disk["range_slot"])

    def test_overlap_is_ambiguous(self):
        second = ROW.replace("500e0eca0a295200", "500e0eca0a295201")
        mapping = device_mapping({"DevPrst.txt": TABLE + ROW + second, "Pd.txt": pd()})
        self.assertEqual(mapping["devices"][0]["range_status"], "ambiguous")

    def test_unused_malformed_and_absent_ranges_do_not_invent_disks(self):
        mapping = device_mapping({"DevPrst.txt": TABLE + "0 0 ffff 0 0 ff ff 0 0 1 1 0 0 ff ff\n1 abc 100 12\n"})
        self.assertEqual(mapping["ranges"], [])
        self.assertEqual(mapping["devices"], [])
        self.assertEqual(mapping["malformed_rows"], 1)

    def test_duplicate_sources_do_not_join_controllers(self):
        mapping = device_mapping({"c0/DevPrst.txt": TABLE + ROW, "c1/DevPrst.txt": TABLE + ROW, "Pd.txt": pd()})
        self.assertEqual(mapping["ranges"], [])
        self.assertEqual(mapping["devices"][0]["range_status"], "unresolved")

    def test_chained_noncontiguous_range_has_its_own_start_slot(self):
        row = ROW.replace(" 100 12 0 ", " 200 6 10 ")
        disk = device_mapping({"DevPrst.txt": TABLE + row, "Pd.txt": pd("201", "11")})["devices"][0]
        self.assertEqual((disk["slot"], disk["range_id_offset"]), (17, 1))
        self.assertIsNone(disk["range_slot"])

    def test_document_noncontiguous_slot_example(self):
        # EncReq Table 1: DSN 1,2,3,4,16... maps to PID X+0,X+1,...X+4.
        mapping = device_mapping({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd("104", "10")})
        disk = mapping["devices"][0]
        self.assertEqual((disk["slot"], disk["range_id_offset"]), (16, 4))
        self.assertEqual(disk["range_status"], "range candidate")

    def test_missing_slot_is_not_filled_from_pid(self):
        disk = device_mapping({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd(slot="ffff")})["devices"][0]
        self.assertIsNone(disk["slot"])
        self.assertIsNone(disk["range_slot"])

    def test_pdprst_missing_record_is_not_assumed_to_be_current_pd(self):
        mapping = device_mapping({"PdPrst.txt": "INDEX :0x0\nUniqueId :0x12345678\nPdType :01 pdConfiguration :01 pdIsBad :00 pdIsMissing:01\nPdRebuildNeeded:00\n"})
        self.assertEqual(mapping["persistent_records"][0]["pdIsMissing"], 1)
        self.assertEqual(mapping["devices"], [])


class ConfigurationAndDiagnosticsTests(unittest.TestCase):
    def pages(self, current="00000002", size="0x2"):
        return ("====Read DEFAULT Configuration Pages====\n"
                "PageType MFG: PageNum 47 for IocNum 0 PageAddr 0x0 Size 0x2 words:\n"
                "AAAA: 00000001 00000000\n"
                "====Read CURRENT Configuration Pages====\n"
                f"PageType MFG: PageNum 47 for IocNum 0 PageAddr 0x0 Size {size} words:\n"
                f"BBBB: {current} 00000000\n"
                "====Read PERSISTENT Configuration Pages====\n")

    def test_region_and_address_independent_raw_difference(self):
        config = configuration({"ConfigPages.txt": self.pages()}, "AV1")
        self.assertEqual(config["regions"], {"DEFAULT": 1, "CURRENT": 1})
        self.assertEqual(len(config["current_default_differences"]), 1)
        self.assertEqual(config["pages"][0]["label"], "Persistent device table")
        self.assertFalse(configuration({"ConfigPages.txt": self.pages("00000001")})["current_default_differences"])

    def test_av2_does_not_borrow_av1_page_labels(self):
        config = configuration({"ConfigPages.txt": self.pages()}, "AV2")
        self.assertIn("unverified", config["pages"][0]["label"])
        self.assertEqual(len(config["current_default_differences"]), 1)

    def test_management_error_namespaces_and_zero_validity(self):
        result = modern({"Oob.txt": "SLStatus=0x20000005 comStatus=0x10\nSLStatus=0 comStatus=0\ninvalid sequence, incomplete buffer\n"})
        diag = result["diagnostics"]
        self.assertEqual(diag["counts"]["management_status"], 1)
        self.assertEqual(diag["observations"][0]["management_status_fields"], {"SLStatus": "0x20000005", "comStatus": "0x10"})
        self.assertIn("Collection/transport", diag["observations"][1]["interpretation"])
        self.assertFalse(any(c["severity"] == "critical" for c in result["checks"]))

    def test_incomplete_or_ambiguous_pages_are_not_compared(self):
        self.assertFalse(configuration({"ConfigPages.txt": self.pages(size="0x3")})["current_default_differences"])
        text = self.pages() + self.pages()
        self.assertFalse(configuration({"ConfigPages.txt": text})["current_default_differences"])

    def test_zero_run_is_bounded_and_equal_to_visible_zeros(self):
        text = self.pages("00000001").replace("AAAA: 00000001 00000000", "AAAA: 00000001\n[skipped 0x1 empty dwords]")
        self.assertFalse(configuration({"ConfigPages.txt": text})["current_default_differences"])
        text = text.replace("0x1 empty", "0xffffffff empty")
        self.assertFalse(configuration({"ConfigPages.txt": text})["current_default_differences"])

    def test_structured_observations_preserve_codes_and_history(self):
        tty = ("[old boot] ASSERT: File raid.c line 1321 ECode 0x8108\n"
               "ERR: CiUpload REPLY: IOCStatus 000080b2, IOCLogInfo 30010453\n"
               "EVT#339-T1: 1=Unexpected sense PD 0x105(e0x111/s5) CDB 28 Sense 3/11/00\n"
               "Running in Safe Mode\nCache offload failed\n")
        result = modern({"Tty.txt": tty, "DevPrst.txt": TABLE + ROW, "Pd.txt": pd()})
        observations = result["diagnostics"]["observations"]
        status = next(o for o in observations if "command_status" in o["kinds"])
        self.assertEqual((status["ioc_status"], status["ioc_log_info"]), ("000080b2", "30010453"))
        sense = next(o for o in observations if "sense" in o["kinds"])
        self.assertEqual(sense["sense"], "3/11/00")
        self.assertEqual(sense["device"]["slot"], 5)
        self.assertFalse(any(c["severity"] == "critical" for c in result["checks"]))
        self.assertEqual(result["diagnostics"]["counts"]["safe_mode"], 1)

    def test_policy_and_zero_status_are_not_incidents(self):
        result = modern({"Tty.txt": "SafeMode=0\nBoot Action: Safe Mode\nmemUnCorrectableErrCnt=0\nIOCStatus 0\nIOCStatus 0x00000000, IOCLogInfo 0x0\n"})
        self.assertEqual(result["diagnostics"]["observations"], [])

    def test_observation_retention_is_bounded(self):
        result = modern({"Tty.txt": "Cache offload failed\n" * 200})
        self.assertEqual(len(result["diagnostics"]["observations"]), 120)
        self.assertEqual(result["diagnostics"]["counts"]["cache"], 200)

    def test_collected_binary_is_not_decoded_or_executed(self):
        result = modern({"RingBuffer.bin": b"\x00\x01", "SnapDumpUtils.zip": b"untrusted executable bundle"})
        self.assertEqual(len(result["intake"]["unparsed_entries"]), 2)
        self.assertNotIn("RingBuffer.bin", result["_file_text"])
        self.assertNotIn("_file_text", public_result(result))

    def test_all_reference_lines_match_original_and_davy_reopens_mapping(self):
        result = modern({"DevPrst.txt": TABLE + ROW, "Pd.txt": pd(), "ConfigPages.txt": self.pages(),
                         "Tty.txt": "Cache offload failed\n"})
        sources = result["operating_mode"]["evidence"]
        sources += [r["source"] for r in result["device_mapping"]["ranges"]]
        sources += [p["source"] for p in result["configuration"]["pages"]]
        sources += [o["source"] for o in result["diagnostics"]["observations"]]
        for device in result["device_mapping"]["devices"]:
            sources += device["sources"]
        for source in sources:
            original = result["_file_text"][source["name"]].splitlines()
            self.assertEqual(source["excerpt"], "\n".join(original[source["start_line"] - 1:source["end_line"]]))
        _, _, retrieved = build_snapdump_chat(result, "PD 0x105 对应什么槽位和 Persistent ID 范围？")
        self.assertTrue(any(s["name"] == "DevPrst.txt" and "500e0eca0a295200" in s["excerpt"] for s in retrieved))
        self.assertTrue(any(s["name"] == "Pd.txt" and "slotNumber = 5" in s["excerpt"] for s in retrieved))

    def test_sparse_pd_identity_fields_and_range_header_share_original_context(self):
        sparse = "PD=105 infoPtr=1234\nscsiType=0 state=0(UNCONFIGURED_GOOD)\n" + "unrelated field\n" * 14
        sparse += "enclIndex = 2, slotNumber = 5, enclDeviceId = 111\nSCSI Inquiry:\nvendorIdentification=Example\nproductIdentification=SPARSE-MODEL\n"
        result = modern({"Pd.txt": sparse, "DevPrst.txt": TABLE + ROW})
        _, prompt, sources = build_snapdump_chat(result, "PD 0x105 对应什么槽位、什么型号、什么 Persistent ID 范围？")
        self.assertTrue(any("PD=105" in s["excerpt"] and "slotNumber = 5" in s["excerpt"] and "SPARSE-MODEL" in s["excerpt"] for s in sources))
        self.assertTrue(any("Index EnclD PerID" in s["excerpt"] and "500e0eca0a295200" in s["excerpt"] for s in sources))
        self.assertIn("EnclD is the enclosure ELID", prompt)


if __name__ == "__main__":
    unittest.main()
