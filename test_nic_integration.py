"""End-to-end NIC report contracts using fixtures derived from the supplied sheet."""
import io
import json
import tarfile
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import app
from workspace_analysis import WorkspaceEvidenceTools


V3 = """PCI Adapter 1 : Intel E810 Network Adapter
 EID : 0xb
 PLDM : types(0x75) { Monitor&Control(Y), FRU(Y), FwUpdate(Y), RDE(Y) }
 Seg|Bus|Dev|Func : 0 | 97(0x61) | 0 | 0
 VID|DID|SVID|SDID : 0x8086 | 0x159B | 0x8086 | 0x4003
 slot number : 1
 firmware 1:
   firmware name : Combined Option ROM Image
   version string : 1.4009.0
 firmware 2:
   firmware name : Etrack ID
   version string : 5.00 (0x80021D17)
 Link Status : 2(0-Not Support, 1-Unknown, 2-Down, 3-Up)
 Link Speed : 0
"""
V4 = """Slot 06, Addr 0x00EA0000, [8086 1249 8086 0005], devmgr, E835 Network Adapter, EID(0x0C), 2.10 (0x8001990E)
 [Port 1] 44:49:88:09:3A:50; State: LinkDown; Speed(Gbps): 0.0
 TID | EID | Address | VID | PLDM Types | Event Types
 005 | 0x0C | 0x00EA0000 | 0x8086 |0, 2, 4, 5, 6 |0, 2, 3, 4, 5 (Async)
"""

PCIE_MIXED = V3 + """PCI Adapter 2 : ThinkSystem RAID 540-16i Adapter
 slot number : 8
  RAID Controller
    EID : 0xc
    PLDM : types(0x21) { Monitor&Control(N), FRU(N), FwUpdate(Y), RDE(N) }
    firmware 1:
      firmware name : RAID Firmware
      version string : 52.1
PCI Adapter 3 : ThinkSystem 460-16e HBA
 slot number : 9
  SAS Controller
    EID : 0xd
    PLDM : types(0x25) { Monitor&Control(Y), FRU(N), FwUpdate(Y), RDE(N) }
PCI Adapter 4 : ASPEED VGA
 slot number : 1
  Display Controller
    EID : N/A
    PLDM : types(0x0) { Monitor&Control(N), FRU(N), FwUpdate(N), RDE(N) }
PCI Adapter 5 : Unknown Device
 slot number : 7
 EID : N/A
"""


DUAL_NIC_V4 = """TID | EID | Address | VID | PLDM Types | Event Types
001 | 0x09 | 0x00180000 | 0x8086 |0, 2, 5, 6 |0, 2, 3, 4, 5 (Async)
002 | 0x08 | 0x00170000 | 0x8086 |0, 2, 5, 6 |0, 2, 3, 4, 5 (Async)
Slot 13, Addr 0x00170000, [8086 57B0 8086 0003], devmgr, E610 Network Adapter for OCP 3.0, EID(0x08), 1.50
P/N: TEST-PN; SKU: E610; S/N: TEST-NIC-A; Manufacture: Intel
Slot 13, Addr 0x00180000, [8086 57B0 8086 0003], devmgr, E610 Network Adapter for OCP 3.0, EID(0x09), 1.50
P/N: TEST-PN; SKU: E610; S/N: TEST-NIC-B; Manufacture: Intel
"""


def tar_bytes(files, mode="w"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode=mode) as archive:
        for name, data in files.items():
            data = data.encode() if isinstance(data, str) else data
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


class NicIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        self.settings = patch.object(app, "REPORT_DIR", self.reports)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        key_path = patch.object(app, "API_KEY_FILE", self.root / "unused-test-key.txt")
        key_path.start()
        self.addCleanup(key_path.stop)

    def analyze(self, files):
        upload = self.root / "nic-test.tar.gz"
        upload.write_bytes(tar_bytes(files, "w:gz"))
        return app.analyze(upload, cleanup=False)

    def test_v3_analyze_render_and_ai_context_preserve_details(self):
        report = self.analyze({"tmp/ffdc_live_dbg/dmdb_pci_dumper.txt": V3})
        self.assertEqual(len(report["network"]["adapters"]), 1)
        adapter = report["network"]["adapters"][0]
        self.assertEqual(adapter["pci_bdf"], "0000:61:00.0")
        self.assertEqual(adapter["pldm_types"], [0, 2, 4, 5, 6])
        self.assertIn("1.4009.0", adapter["firmware"])
        self.assertIn("0x80021D17", adapter["firmware"])
        self.assertEqual(report["network"]["ports"][0]["speed_unit"], "")
        self.assertTrue(all(row["severity"] == "Info" for row in report["automated_checks"] if row["category"] == "Network"))
        page = app.render_report(report)
        for text in ("PCI identity", "Physical Port Snapshot", "0000:61:00.0"):
            self.assertIn(text, page)
        self.assertNotIn("NIC Firmware Update Evidence", page)
        self.assertNotIn("<summary>Collected update log excerpts</summary>", page)
        pcie = page.split("<h2>PCIe Device Details</h2>", 1)[1].split("</section>", 1)[0]
        for text in ("PLDM types", "capabilities", "0, 2, 4, 5, 6", "Monitor&amp;Control: Y", "FwUpdate: Y"):
            self.assertIn(text, pcie)
        self.assertNotIn("<summary>PLDM capabilities</summary>", page)
        self.assertNotIn("<summary>NIC PCI functions</summary>", page)
        context = app.compact_report_for_ai(report)
        self.assertEqual(context["network"], report["network"])
        self.assertIn("nic_firmware", context)
        self.assertIn("EID 0xb", app.build_system_summary_text(report))

    def test_v4_nested_log_survives_report_and_evidence_read(self):
        nested = tar_bytes({"IBMU.tar": tar_bytes({"IBMU.log": "BMU launched update script\nBMU script completed\n"})}, "w:gz")
        report = self.analyze({
            "tmp/io_devices.txt": V4,
            "tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz": nested,
            "tmp/ibmulog/brcm-lnvgy_fw_nic_nx1-test.log": "NIC firmware update status requires review\n",
        })
        adapter = report["network"]["adapters"][0]
        self.assertEqual(adapter["name"], "E835 Network Adapter")
        self.assertEqual(adapter["address"], "0x00EA0000")
        self.assertEqual(adapter["pci_bdf"], "")
        self.assertEqual(int(adapter["tid"]), 5)
        self.assertEqual(report["network"]["ports"][0]["state"], "Down")
        evidence = report["nic_firmware"]
        self.assertTrue(evidence["archive_members"])
        source = next(iter(evidence["archive_members"]))
        tools = WorkspaceEvidenceTools(self.reports / report["id"] / "extract", sections=app.compact_report_for_ai(report))
        self.assertIn("BMU script completed", json.dumps(tools.read_log(source, 1, 10)))
        self.assertTrue(all(event["status"] == "Observed" for event in evidence["events"]))
        prepared = tools.prepare("网卡的 PLDM 和固件升级详情")
        self.assertIn("E835", json.dumps(prepared))
        page = app.render_report(report)
        self.assertIn("44:49:88:09:3A:50", page)
        self.assertNotIn("NIC Firmware Update Evidence", page)
        self.assertNotIn("Collected update log excerpts", page)
        self.assertNotIn("IBMU.tgz", page)
        pcie = app.render_pcie_device_details(app.parse_v4_io_devices(V4), report["network"])
        self.assertIn("0, 2, 4, 5, 6", pcie)

    def test_uefi_json_vid_did_decimal_fields_are_rendered_as_hex(self):
        payload = {
            "PCIeDeviceComplexes": [{
                "SlotNumber": 7,
                "LocationNumber": 1,
                "VendorId": 32902,
                "DeviceId": 4681,
                "SubsystemVendorId": 32902,
                "SubsystemId": 16387,
                "PCIeDevice": {"Name": "Intel(R) Ethernet Network Adapter E835-C-Q2"},
            }]
        }
        rows = app.parse_v4_pcie_inventory("pstorage/persist/hdr/PCIeDeviceComplexes.json", json.dumps(payload))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pci_ids"], {
            "vid": "0x8086", "did": "0x1249", "svid": "0x8086", "sdid": "0x4003"
        })
        self.assertIn("VID/DID 0x8086/0x1249", rows[0]["evidence"])
        self.assertIn("source values 32902/4681", rows[0]["evidence"])
        page = app.render_uefi_boot({"pcie_enumeration": rows})
        self.assertIn("VID/DID 0x8086/0x1249", page)
        self.assertNotIn("VID/DID 32902/4681", page)

    def test_uefi_json_broadcom_ids_are_rendered_as_hex(self):
        payload = {
            "PCIeDeviceComplexes": [{
                "SlotNumber": 5,
                "LocationNumber": 1,
                "VendorId": 5348,
                "DeviceId": 5719,
                "SubsystemVendorId": 6058,
                "SubsystemId": 16429,
                "PCIeDevice": {"Name": "Broadcom NetXtreme PCIe Ethernet Adapter"},
            }, {
                "SlotNumber": 8,
                "VendorId": 4096,
                "DeviceId": 179,
                "SubsystemVendorId": 6058,
                "SubsystemId": 30796,
                "PCIeDevice": {"Name": "ThinkSystem RAID 960W PCIe Gen5 Adapter"},
            }]
        }
        rows = app.parse_v4_pcie_inventory("pstorage/persist/hdr/PCIeDeviceComplexes.json", json.dumps(payload))
        self.assertEqual([row["pci_ids"] for row in rows], [{
            "vid": "0x14E4", "did": "0x1657", "svid": "0x17AA", "sdid": "0x402D"
        }, {
            "vid": "0x1000", "did": "0x00B3", "svid": "0x17AA", "sdid": "0x784C"
        }])
        self.assertIn("VID/DID 0x14E4/0x1657", rows[0]["evidence"])
        self.assertIn("VID/DID 0x1000/0x00B3", rows[1]["evidence"])

    def test_uefi_json_nested_unprefixed_broadcom_ids_are_hexadecimal(self):
        payload = {
            "PCIeDeviceComplexes": [{
                "SlotNumber": 5,
                "PCIeDevice": {"Name": "Broadcom NetXtreme Ethernet Adapter"},
                "PCIeFunctions": [{
                    "VendorId": "14E4", "DeviceId": "0x1657",
                    "SubsystemVendorId": "17AA", "SubsystemId": "0x402D",
                }],
            }]
        }
        rows = app.parse_v4_pcie_inventory("var/lib/lsa/0x4c0000_pcie.json", json.dumps(payload))
        self.assertEqual(rows[0]["pci_ids"], {
            "vid": "0x14E4", "did": "0x1657", "svid": "0x17AA", "sdid": "0x402D"
        })

    def test_multifunction_card_reaches_report_and_ai_with_both_ports(self):
        raw = """PCI Adapter 3 : Intel E810 Ethernet Adapter
 slot number : 1
  Ethernet Controller
    EID : 0xa
    PLDM : types(0x75)
    Seg|Bus|Dev|Func : 0 | 67(0x43) | 0 | 0
      physical port 1:
        port index : 1
        permanent address : B4969190A9C8
        Link Speed : 25000
        Link Status : 3
  Ethernet Controller
    EID : N/A
    PLDM : types(0x0)
    Seg|Bus|Dev|Func : 0 | 67(0x43) | 0 | 1
      physical port 1:
        port index : 2
        permanent address : B4969190A9C9
        Link Speed : 0
        Link Status : 2
"""
        report = self.analyze({"tmp/ffdc_live_dbg/dmdb_pci_dumper.txt": raw})
        network = report["network"]
        self.assertEqual(len(network["adapters"]), 1)
        self.assertEqual(network["adapters"][0]["eid"], "0xa")
        self.assertEqual({p["port"] for p in network["ports"]}, {"1", "2"})
        page = app.render_report(report)
        for value in ("0000:43:00.0", "0000:43:00.1", "B4:96:91:90:A9:C8", "B4:96:91:90:A9:C9"):
            self.assertIn(value, page)
        context = app.compact_report_for_ai(report)
        self.assertEqual(len(context["network"]["adapters"][0]["functions"]), 2)

    def test_legacy_report_refreshes_in_memory_with_raw_logs(self):
        extract = self.reports / "legacy" / "extract" / "tmp"
        extract.mkdir(parents=True)
        (extract / "io_devices.txt").write_text(V4)
        report = {"id": "legacy", "network": {"adapters": []}, "pci": {}}
        stored = self.reports / "legacy" / "report.json"
        stored.write_text(json.dumps(report))
        original = stored.read_bytes()
        loaded = app.load_workspace_report("legacy")
        self.assertEqual(loaded["network"]["adapters"][0]["name"], "E835 Network Adapter")
        self.assertEqual(stored.read_bytes(), original)
        with patch.object(app, "parse_network_info", side_effect=AssertionError("duplicate refresh")):
            app.enrich_nic_report(loaded)

    def test_unavailable_legacy_raw_data_preserves_existing_report(self):
        report = {"id": "gone", "network": {"adapters": [{"name": "recorded NIC"}]}}
        self.assertEqual(app.enrich_nic_report(report)["network"]["adapters"][0]["name"], "recorded NIC")

    def test_all_pcie_pldm_survives_analyze_render_api_context(self):
        report = self.analyze({"tmp/ffdc_live_dbg/dmdb_pci_dumper.txt": PCIE_MIXED})
        devices = report["pci"]["adapters"]
        self.assertEqual(len(devices), 5)
        self.assertEqual(len(report["network"]["adapters"]), 1)
        self.assertEqual(devices[1]["pldm_types"], [0, 5])
        self.assertEqual(devices[2]["pldm_types"], [0, 2, 5])
        self.assertEqual(devices[1]["pldm_capabilities"], {"Monitor&Control": False, "FRU": False, "FwUpdate": True, "RDE": False})
        self.assertIsInstance(devices[1]["firmware"], list)
        self.assertEqual(devices[1]["firmware version"], "RAID Firmware: 52.1")
        self.assertEqual(devices[3]["pldm_mask"], "0x0")
        self.assertEqual(devices[4]["pldm_mask"], "")
        page = app.render_report(report)
        pcie = page.split("<h2>PCIe Device Details</h2>", 1)[1].split("</section>", 1)[0]
        for value in ("0, 5", "0, 2, 5", "None (mask 0x0)", "Monitor&amp;Control: N; FRU: N; FwUpdate: Y; RDE: N", "not reported"):
            self.assertIn(value, pcie)
        context = app.compact_report_for_ai(report)
        self.assertEqual(context["adapter_details"][1]["pldm_types"], [0, 5])
        loaded = app.load_workspace_report(report["id"])
        self.assertEqual(loaded["pcie_details_version"], 2)
        self.assertEqual(loaded["pci"]["adapters"][2]["pldm_types"], [0, 2, 5])

    def test_pcie_refresh_preserves_nic_v1_and_storage_history(self):
        extract = self.reports / "legacy" / "extract" / "tmp" / "ffdc_live_dbg"
        extract.mkdir(parents=True)
        (extract / "dmdb_pci_dumper.txt").write_text(PCIE_MIXED)
        pci = app.parse_dmdb(PCIE_MIXED)
        pci["storage"] = [{"controller": "RAID", "adapter": dict(pci["adapters"][1]),
                           "drives": [{"bay": "1", "serial": "retained"}],
                           "virtual_drives": [{"raid_level": "RAID 1"}]}]
        report = {"id": "legacy", "pci": pci, "nic_details_version": 1,
                  "network": {"adapters": [{"name": "cached NIC"}]},
                  "nic_firmware": {"events": [{"evidence": "retained nested evidence"}]}}
        stored = self.reports / "legacy" / "report.json"
        stored.write_text(json.dumps(report))
        before = stored.read_bytes()
        with patch.object(app, "collect_nic_firmware_evidence", side_effect=AssertionError("NIC evidence must not be recollected")):
            refreshed = app.load_workspace_report("legacy")
        self.assertEqual(refreshed["network"], report["network"])
        self.assertEqual(refreshed["nic_firmware"], report["nic_firmware"])
        self.assertEqual(refreshed["pci"]["storage"][0]["adapter"]["pldm_types"], [0, 5])
        self.assertEqual(refreshed["pci"]["storage"][0]["drives"], pci["storage"][0]["drives"])
        self.assertEqual(refreshed["pci"]["storage"][0]["virtual_drives"], pci["storage"][0]["virtual_drives"])
        self.assertEqual(stored.read_bytes(), before)

    def test_v4_pcie_refresh_keeps_device_and_attachment_boundaries(self):
        raw = """Slot 08, Addr 0x00080000, [1000 0014 17AA 1234], lsa, ThinkSystem RAID Adapter, EID(0x0C), 52.1
Slot 09, Addr 0x00090000, [1000 00A5 17AA 5678], lsa, ThinkSystem HBA, EID(0x0D), 8.1
TID | EID | Address | VID | PLDM Types | Event Types
005 | 0x0C | 0x00080000 | 0x1000 |0, 5 |0
006 | 0x0D | 0x00090000 | 0x1000 |0, 2, 5 |0
"""
        extract = self.reports / "v4" / "extract" / "tmp"
        extract.mkdir(parents=True)
        (extract / "io_devices.txt").write_text(raw)
        report = {"id": "v4", "nic_details_version": 1, "pci": app.parse_v4_io_devices(raw)}
        app.enrich_nic_report(report)
        self.assertEqual([d["pldm_types"] for d in report["pci"]["adapters"]], [[0, 5], [0, 2, 5]])
        self.assertEqual(report["pci"]["adapters"][0]["pldm_capabilities"], {"Monitor&Control": False, "FRU": False, "FwUpdate": True, "RDE": False})
        context = app.compact_report_for_ai(report)
        namespaced = self.reports / "v4" / "workspace_extract" / "01-v4" / "tmp"
        namespaced.mkdir(parents=True)
        (namespaced / "io_devices.txt").write_text(raw)
        app.qualify_nic_collection_sources(context, {"root_report_id": "v4", "attachments": [{"id": "v4", "namespace": "01-v4"}]}, "v4")
        self.assertEqual(context["adapter_details"][0]["pldm_evidence"]["source"], "01-v4/tmp/io_devices.txt")
        self.assertEqual(report["pci"]["adapters"][0]["pldm_evidence"]["source"], "tmp/io_devices.txt")

    def test_pcie_ambiguous_or_conflicting_inventory_does_not_borrow_pldm(self):
        extract = self.reports / "mixed" / "extract" / "tmp" / "ffdc_live_dbg"
        extract.mkdir(parents=True)
        (extract / "dmdb_pci_dumper.txt").write_text(PCIE_MIXED)
        pci = app.parse_dmdb(PCIE_MIXED)
        pci["adapters"][1]["eid"] = "0xff"
        pci["adapters"].append(dict(pci["adapters"][2]))
        report = {"id": "mixed", "pci": pci}
        app.enrich_pcie_report(report)
        self.assertNotIn("pldm_types", pci["adapters"][1])
        self.assertNotIn("pldm_types", pci["adapters"][2])
        self.assertEqual(pci["adapters"][0]["pldm_types"], [0, 2, 4, 5, 6])

    def test_same_slot_nic_pldm_refresh_uses_serial_and_preserves_history(self):
        report = self.analyze({'tmp/io_devices.txt': DUAL_NIC_V4})
        report['pci']['adapters'] = app.parse_v4_io_devices(DUAL_NIC_V4)['adapters']
        report['pcie_details_version'] = 1
        for device in report['pci']['adapters']:
            for key in list(device):
                if key.startswith('pldm_') or key in {'tid', 'event_types', 'event_types_raw'}:
                    device.pop(key)
        first = report['pci']['adapters'][0]
        first['eid'] = ''; first.pop('address', None)
        for device in report['network']['adapters']:
            device['pldm_capabilities'] = {}
        report['agent_analysis'] = {'status': 'ok', 'content': 'retained previous analysis'}
        stored = self.reports / report['id'] / 'report.json'
        stored.write_text(json.dumps(report)); before = stored.read_bytes()
        with patch.object(app, 'collect_nic_firmware_evidence', side_effect=AssertionError('No archive recollection')):
            updated = app.load_workspace_report(report['id'])
        expected = {'Monitor&Control': True, 'FRU': False, 'FwUpdate': True, 'RDE': True}
        for device in updated['pci']['adapters'] + updated['network']['adapters']:
            self.assertEqual(device['pldm_types'], [0, 2, 5, 6])
            self.assertEqual(device['pldm_capabilities'], expected)
        self.assertEqual([r['tid'] for r in updated['pci']['adapters']], ['002', '001'])
        self.assertEqual(updated['pci']['adapters'][0]['eid'], '')
        self.assertEqual(updated['agent_analysis'], report['agent_analysis'])
        self.assertEqual(updated['nic_firmware'], report['nic_firmware'])
        self.assertEqual(updated['network']['ports'], report['network']['ports'])
        self.assertEqual(updated['pcie_details_version'], 2)
        page = app.render_report(updated).split('<h2>PCIe Device Details</h2>')[1].split('</section>')[0]
        self.assertEqual(page.count('0, 2, 5, 6'), 2)
        self.assertEqual(page.count('Monitor&amp;Control: Y; FRU: N; FwUpdate: Y; RDE: Y'), 2)
        self.assertEqual(stored.read_bytes(), before)

    def test_pcie_serial_conflicts_and_unidentified_same_slot_devices_stay_unmatched(self):
        candidates = app.parse_pcie_inventory(io_text=DUAL_NIC_V4)['adapters']
        device = dict(candidates[0]); device['serial'] = 'CONFLICT'
        self.assertFalse(app.pcie_device_matches(device, candidates[0]))
        devices = [{'name': candidates[0]['name'], 'slot': '13', 'eid': ''}, dict(candidates[1])]
        devices[1]['serial'] = ''
        self.assertIsNone(app.unique_pcie_details(devices[0], devices, candidates))
        self.assertIsNone(app.unique_pcie_details(devices[1], devices, candidates))

    def test_v4_minilog_same_slot_functions_merge_by_serial_without_overwrite(self):
        path = self.root / 'io_devices.txt'; path.write_text(DUAL_NIC_V4)
        rows = [{'device_name': 'E610 Network Adapter for OCP 3.0', 'slot': '13',
                 'serial_number': serial, 'model': 'retained model'} for serial in ('TEST-NIC-A', 'TEST-NIC-B')]
        with patch.object(app, 'load_minilog_json', return_value={}), patch.object(app, 'minilog_sections', return_value={}), patch.object(app, 'section_rows', side_effect=lambda sections, title: rows if title == 'Adapter' else []):
            report = app.analyze_minilog_v4(path, path, self.root, self.root, {'io_devices': path})
        devices = report['pci']['adapters']
        self.assertEqual(len(devices), 2)
        self.assertEqual([(r['serial'], r['eid'], r['address']) for r in devices],
                         [('TEST-NIC-A', '0x08', '0x00170000'), ('TEST-NIC-B', '0x09', '0x00180000')])
        self.assertTrue(all(r['model'] == 'retained model' for r in devices))

    def test_storage_vendor_not_nic_and_html_escaped(self):
        self.assertFalse(app.is_network_adapter({"name": "Broadcom MegaRAID 960-8i", "manufacturer": "Broadcom"}))
        page = app.render_network_analysis({"adapters": [{"name": "<script>bad</script>", "slot": "1"}]})
        self.assertNotIn("<script>bad</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_missing_eid_does_not_merge_different_nics(self):
        dmdb = self.root / "dmdb.txt"
        dmdb.write_text("PCI Adapter 1 : Intel E810 Network Adapter\n")
        network = app.parse_network_info(self.root, {"adapters": [
            {"name": "QLogic FastLinQ 41000", "slot": "", "eid": ""}]}, {"dmdb": dmdb})
        self.assertEqual(len(network["adapters"]), 2)

    def test_present_unread_source_is_not_displayed_as_collected_excerpt(self):
        page = app.render_nic_firmware_analysis({"log_sources": [
            {"source": "tmp/fm.log", "available": True, "readable": False, "kind": "text"}]})
        self.assertIn("No readable NIC firmware-update source", page)
        self.assertNotIn("<td>tmp/fm.log</td>", page)

    def test_legacy_ai_agent_and_summary_use_refreshed_network(self):
        extract = self.reports / "legacy" / "extract" / "tmp"
        extract.mkdir(parents=True)
        (extract / "io_devices.txt").write_text(V4)
        def legacy():
            return {"id": "legacy", "system": {}, "network": {"adapters": []}, "pci": {}}
        self.assertIn("E835", json.dumps(app.compact_report_for_ai(legacy())))
        self.assertIn("E835", json.dumps(app.collect_agent_tasks(legacy())))
        self.assertIn("E835", app.build_system_summary_text(legacy()))

    def test_live_handler_api_and_download_refresh_legacy_report(self):
        extract = self.reports / "legacy" / "extract" / "tmp"
        extract.mkdir(parents=True)
        (extract / "io_devices.txt").write_text(V4)
        stored = self.reports / "legacy" / "report.json"
        stored.write_text(json.dumps({"id": "legacy", "system": {}, "pci": {}}))
        server = app.FFDCThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_address[1])
            with urllib.request.urlopen(base + "/api/report?id=legacy", timeout=5) as response:
                report = json.load(response)
            self.assertEqual(report["nic_details_version"], 1)
            self.assertEqual(report["network"]["adapters"][0]["address"], "0x00EA0000")
            with urllib.request.urlopen(base + "/download-summary?id=legacy", timeout=5) as response:
                summary = response.read().decode()
            self.assertIn("E835", summary)
            self.assertIn("44:49:88:09:3A:50", summary)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
