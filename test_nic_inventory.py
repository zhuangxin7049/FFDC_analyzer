import unittest
from unittest.mock import patch

import nic_inventory
from nic_inventory import parse_nic_inventory, parse_pcie_inventory


V3 = """PCI Adapter 1 : Intel E810 Ethernet Adapter
  EID                 : 0xb
  PLDM                : types(0x75) { Monitor&Control(Y), FRU(Y), FwUpdate(Y), RDE(Y) }
  Seg|Bus|Dev|Func    : 0 | 97(0x61) | 0 | 0
  VID|DID|SVID|SDID   : 0x8086 | 0x159B | 0x8086 | 0x4003
  slot number     : 1
  manufacturer    : Intel
  model           : E810
  part number     : PN-123
  serial number   : SN-123
  firmware 1:
      firmware name   : Combined Option ROM Image
      version string  : 1.4009.0
      description     : Combined Option ROM Image
  firmware 2:
      firmware name   : Etrack ID
      version string  : 5.00 (0x80021D17)
      description     : Etrack ID
  Link Status   : 2(0-Not Support, 1-Unknown, 2-Down, 3-Up)
  Link Speed   : 0
"""
V4_CARD = "  Slot 06, Addr 0x00EA0000, [8086 1249 8086 0005], devmgr, E835 Network Adapter, EID(0x0C), 2.10 (0x8001990E)"
V4_PORT = "  [Port 1]  44:49:88:09:3A:50;  State: LinkDown;  Speed(Gbps): 0.0"
TABLE = """  TID | EID | Address | VID | PLDM Types | Event Types
 005 | 0x0C | 0x00EA0000 | 0x8086 |0, 2, 4, 5, 6 |0, 2, 3, 4, 5 (Async)
"""


class NicInventoryTests(unittest.TestCase):
    def test_v3_spreadsheet_fields_are_preserved(self):
        data = parse_nic_inventory(dmdb_text=V3)
        self.assertEqual(len(data["adapters"]), 1)
        adapter = data["adapters"][0]
        self.assertEqual(adapter["pci_bdf"], "0000:61:00.0")
        self.assertEqual(adapter["pci_ids"], {"vid": "0x8086", "did": "0x159b", "svid": "0x8086", "sdid": "0x4003"})
        self.assertEqual(adapter["pldm_types"], [0, 2, 4, 5, 6])
        self.assertEqual(adapter["pldm_mask"], "0x75")
        self.assertEqual(adapter["pldm_capabilities"], {"Monitor&Control": True, "FRU": True, "FwUpdate": True, "RDE": True})
        self.assertEqual(adapter["eid"], "0xb")
        self.assertEqual(adapter["slot"], "1")
        self.assertEqual(adapter["manufacturer"], "Intel")
        self.assertEqual(adapter["part_number"], "PN-123")
        self.assertEqual(adapter["serial"], "SN-123")
        self.assertEqual(adapter["firmware_components"][1]["version"], "5.00 (0x80021D17)")
        self.assertIn("Combined Option ROM Image: 1.4009.0", adapter["firmware"])
        port = data["ports"][0]
        self.assertEqual((port["port"], port["state"], port["state_code"]), ("", "Down", 2))
        self.assertEqual((port["speed"], port["speed_unit"]), ("0", ""))
        self.assertIn("0-Not Support", port["raw"])
        self.assertEqual(port["line"], 19)
        self.assertEqual(adapter["line"], 1)

    def test_v3_decimal_pci_ids_are_normalized_to_hex(self):
        text = """PCI Adapter 1 : Intel Ethernet Adapter
  VID|DID|SVID|SDID : 32902 | 4681 | 32902 | 16387
  slot number : 7
"""
        adapter = parse_pcie_inventory(dmdb_text=text)["adapters"][0]
        self.assertEqual(adapter["pci_ids"], {
            "vid": "0x8086", "did": "0x1249", "svid": "0x8086", "sdid": "0x4003"
        })

    def test_v4_spreadsheet_table_before_and_after_inventory(self):
        for content in (TABLE + V4_CARD + "\n" + V4_PORT,
                        V4_CARD + "\n" + V4_PORT + "\n" + TABLE):
            with self.subTest(content=content):
                data = parse_nic_inventory(io_text=content)
                adapter = data["adapters"][0]
                self.assertEqual(adapter["name"], "E835 Network Adapter")
                self.assertEqual(adapter["address"], "0x00EA0000")
                self.assertEqual(adapter["pci_bdf"], "")
                self.assertEqual(adapter["tid"], "005")
                self.assertEqual(adapter["firmware"], "2.10 (0x8001990E)")
                self.assertEqual(adapter["pldm_types"], [0, 2, 4, 5, 6])
                self.assertEqual(adapter["event_types"], [0, 2, 3, 4, 5])
                self.assertIn("Async", adapter["event_types_raw"])
                self.assertEqual(adapter["pldm_capabilities"], {"Monitor&Control": True, "FRU": True, "FwUpdate": True, "RDE": True})
                port = data["ports"][0]
                self.assertEqual((port["port"], port["mac"], port["state"]), ("1", "44:49:88:09:3A:50", "Down"))
                self.assertEqual((port["speed"], port["speed_unit"]), ("0.0", "Gbps"))
                self.assertEqual(port["slot"], "6")

    def test_v4_tid_requires_both_eid_and_address(self):
        wrong_rows = """001 | 0x0D | 0x00EA0000 | 0x8086 |5 |0
002 | 0x0C | 0x00EB0000 | 0x8086 |2 |0
"""
        adapter = parse_nic_inventory(io_text=wrong_rows + V4_CARD)["adapters"][0]
        self.assertEqual(adapter["tid"], "")
        self.assertEqual(adapter["pldm_types"], [])

    def test_v4_inventory_scopes_ports_and_metadata(self):
        content = "\n".join((V4_CARD, V4_PORT,
            "P/N: NIC-PN; SKU: SKU-1; S/N: NIC-SN; Manufacture: Intel",
            "Onboard 01, Addr 0x00EB0000, [14E4 1657 17AA 4104], devmgr, Broadcom Ethernet Adapter, EID(0x0D), 230.0.3.1",
            "[Port 2] 44:49:88:09:3A:51; State: LinkUp; Speed(Gbps): 25.0",
            "Slot 08, Addr 0x00EC0000, [1000 0014 17AA 1234], lsa, Broadcom RAID Adapter, EID(0x0E), 1.0",
            "P/N: RAID-PN; SKU: SKU-R; S/N: RAID-SN; Manufacture: Broadcom",
            "[Port 3] 44:49:88:09:3A:52; State: LinkUp; Speed(Gbps): 100.0"))
        data = parse_nic_inventory(io_text=content)
        self.assertEqual(len(data["adapters"]), 2)
        self.assertEqual(len(data["ports"]), 2)
        self.assertEqual(data["adapters"][0]["part_number"], "NIC-PN")
        self.assertEqual(data["adapters"][1]["part_number"], "")
        self.assertEqual(data["ports"][1]["slot"], "Onboard 1")
        self.assertEqual(data["ports"][1]["eid"], "0x0D")

    def test_v3_storage_block_cannot_leak_links_or_firmware(self):
        content = V3 + """PCI Adapter 2 : Broadcom RAID 940-8i
slot number : 2
EID : 0x0e
Link Status : 3
Link Speed : 12
firmware 1:
firmware name : RAID firmware
version string : 99.0
"""
        data = parse_nic_inventory(dmdb_text=content)
        self.assertEqual(len(data["adapters"]), 1)
        self.assertEqual(len(data["ports"]), 1)
        self.assertEqual(len(data["adapters"][0]["firmware_components"]), 2)

    def test_v3_unknown_link_codes_and_explicit_port_units(self):
        for code, state in ((0, "NotSupported"), (1, "Unknown"), (2, "Down"), (3, "Up"), (9, "Unknown")):
            with self.subTest(code=code):
                text = "PCI Adapter 1 : Ethernet Adapter\nPort 2:\nLink Status : {}\nLink Speed (Gbps) : 25.0\nEID : 0x0a\nslot number : 4".format(code)
                port = parse_nic_inventory(dmdb_text=text)["ports"][0]
                self.assertEqual(port["state"], state)
                self.assertEqual(port["state_code"], code)
                self.assertEqual((port["port"], port["speed"], port["speed_unit"]), ("2", "25.0", "Gbps"))
                self.assertEqual((port["slot"], port["eid"]), ("4", "0x0a"))

    def test_v3_multiple_functions_keep_management_identity_and_physical_ports(self):
        # Synthetic fixture reflects real controller/physical/logical nesting.
        # MACs and part/serial fields from production evidence are not embedded.
        controller = """  Ethernet Controller
    EID : {eid}
    PLDM : types({mask}) {{ Monitor&Control({flag}), FRU({flag}), FwUpdate({flag}), RDE({flag}) }}
    Seg|Bus|Dev|Func : 0 | 67(0x43) | 0 | {function}
    VID|DID|SVID|SDID : 0x8086 | 0x159B | 0x8086 | 0x4003
    slot number : 1
    firmware 1:
      firmware name : Combined Option ROM Image
      version string : 1.4009.0
    firmware 2:
      firmware name : Etrack ID
      version string : 5.00 (0x80021D15)
    nb of physical ports : 1
      physical port 1:
        port index : {port}
        permanent address : 02000000000{port}
        Link Speed : {speed}
        Link Status : {state}(0-Not Support, 1-Unknown, 2-Down, 3-Up)
        logical port 1:
          permanent address : 02FFFFFFFFFF
          physical port index : {port}
          logical port index : 99
          Link Speed : 99999
          Link Status : 1
"""
        first = controller.format(eid="0xa", mask="0x75", flag="Y", function=0, port=1, speed=25000, state=3)
        second = controller.format(eid="N/A", mask="0x0", flag="N", function=1, port=2, speed=0, state=2)
        text = "PCI Adapter 3 : Intel E810-DA2 10/25GbE SFP28 2-Port OCP Ethernet Adapter\nslot number : 1\n" + first + second
        data = parse_nic_inventory(dmdb_text=text)
        self.assertEqual(len(data["adapters"]), 1)
        card = data["adapters"][0]
        self.assertEqual((card["eid"], card["pci_bdf"], card["pldm_mask"]), ("0xa", "0000:43:00.0", "0x75"))
        self.assertEqual(card["pldm_types"], [0, 2, 4, 5, 6])
        self.assertEqual(len(card["firmware_components"]), 2)
        self.assertEqual(len(card["functions"]), 2)
        self.assertEqual(card["functions"][1]["eid"], "N/A")
        self.assertEqual(card["functions"][1]["pci_bdf"], "0000:43:00.1")
        self.assertEqual(card["functions"][1]["pldm_types"], [])
        self.assertEqual(len(card["functions"][1]["firmware_components"]), 2)
        ports = data["ports"]
        self.assertEqual(len(ports), 2)
        self.assertEqual([p["port"] for p in ports], ["1", "2"])
        self.assertEqual([p["mac"] for p in ports], ["02:00:00:00:00:01", "02:00:00:00:00:02"])
        self.assertEqual([p["state"] for p in ports], ["Up", "Down"])
        self.assertEqual([p["speed"] for p in ports], ["25000", "0"])
        self.assertEqual([p["speed_unit"] for p in ports], ["", ""])
        self.assertEqual([p["eid"] for p in ports], ["0xa", "N/A"])
        self.assertEqual([p["pci_bdf"] for p in ports], ["0000:43:00.0", "0000:43:00.1"])
        self.assertEqual(ports[1]["function_line"], card["functions"][1]["line"])
        self.assertNotIn("02FFFFFFFFFF", ports[1]["raw"])

        # The first valid management EID can be later in the card's function list.
        reverse = parse_nic_inventory(dmdb_text="PCI Adapter 3 : Ethernet Adapter\n" + second + first)
        self.assertEqual(reverse["adapters"][0]["eid"], "0xa")
        self.assertEqual(reverse["adapters"][0]["pci_bdf"], "0000:43:00.0")

    def test_v4_gbe_product_name_is_network_without_vendor_only_guess(self):
        card = "Slot 13, Addr 0x000D0000, [14E4 1657 17AA 0001], devmgr, Broadcom 5719 1GbE, EID(0x00), 227.0.3.1"
        ports = ["[Port {}] 02:00:00:00:00:0{}; State: LinkDown; Speed(Gbps): 0.0".format(n, n) for n in range(1, 5)]
        data = parse_nic_inventory(io_text="\n".join([card] + ports))
        self.assertEqual(len(data["adapters"]), 1)
        self.assertEqual(data["adapters"][0]["name"], "Broadcom 5719 1GbE")
        self.assertEqual(data["adapters"][0]["slot"], "13")
        self.assertEqual([p["port"] for p in data["ports"]], ["1", "2", "3", "4"])
        for name in ("Broadcom RAID Adapter", "Broadcom Controller", "Broadcom RAID 1GbE management"):
            with self.subTest(name=name):
                data = parse_nic_inventory(io_text=card.replace("Broadcom 5719 1GbE", name) + "\n" + ports[0])
                self.assertEqual(data["adapters"], [])
                self.assertEqual(data["ports"], [])

    def test_v4_unprefixed_broadcom_ids_are_hexadecimal(self):
        card = "Slot 05, Addr 0x004C0000, [14E4 1657 17AA 402D], devmgr, Broadcom NetXtreme PCIe 1Gb 4-Port RJ45 Ethernet Adapter, EID(0x00), 20.6.1.4"
        adapter = parse_nic_inventory(io_text=card)["adapters"][0]
        self.assertEqual(adapter["pci_ids"], {
            "vid": "0x14e4", "did": "0x1657", "svid": "0x17aa", "sdid": "0x402d"
        })

    def test_v4_decimal_broadcom_ids_are_normalized_to_hex(self):
        card = "Slot 05, Addr 0x004C0000, [5348 5719 6058 16429], devmgr, Broadcom NetXtreme PCIe 1Gb 4-Port RJ45 Ethernet Adapter, EID(0x00), 20.6.1.4"
        adapter = parse_nic_inventory(io_text=card)["adapters"][0]
        self.assertEqual(adapter["pci_ids"], {
            "vid": "0x14e4", "did": "0x1657", "svid": "0x17aa", "sdid": "0x402d"
        })

    def test_repeated_identical_inventory_and_table_are_not_duplicate_cards(self):
        text = "\n".join((V4_CARD, V4_PORT, V4_CARD, V4_PORT, TABLE, TABLE))
        data = parse_nic_inventory(io_text=text)
        self.assertEqual(len(data["adapters"]), 1)
        self.assertEqual(len(data["ports"]), 1)
        self.assertEqual(len(data["adapters"][0]["pldm_endpoints"]), 1)

    def test_missing_sources_and_missing_optional_fields(self):
        self.assertEqual(parse_nic_inventory(), {"adapters": [], "ports": [], "notes": []})
        data = parse_nic_inventory(dmdb_text="PCI Adapter 1 : Ethernet Adapter", dmdb_source="custom/dump.txt")
        adapter = data["adapters"][0]
        for key in ("slot", "eid", "tid", "address", "pci_bdf", "firmware", "manufacturer", "model", "part_number", "serial"):
            self.assertEqual(adapter[key], "")
        self.assertEqual(adapter["source"], "custom/dump.txt")
        self.assertEqual(data["ports"], [])

    def test_non_nic_boundary_and_malformed_header_end_current_card(self):
        for boundary in ("Backplane 1: location=Rear", "Slot 07, unrecognized format", "Storage:"):
            with self.subTest(boundary=boundary):
                data = parse_nic_inventory(io_text=V4_CARD + "\n" + boundary + "\n" + V4_PORT)
                self.assertEqual(data["ports"], [])

    def test_ambiguous_endpoint_keeps_evidence_without_inventing_tid(self):
        data = parse_nic_inventory(io_text=V4_CARD + "\n" + TABLE + TABLE.replace("005 |", "006 |"))
        adapter = data["adapters"][0]
        self.assertEqual(adapter["tid"], "")
        self.assertEqual(len(adapter["pldm_endpoints"]), 2)
        self.assertTrue(data["notes"])

    def test_limits_are_reported(self):
        with patch.object(nic_inventory, "MAX_LINES", 1):
            data = parse_nic_inventory(io_text=V4_CARD + "\n" + V4_PORT)
        self.assertEqual(len(data["adapters"]), 1)
        self.assertEqual(data["ports"], [])
        self.assertTrue(data["notes"])


class PcieInventoryTests(unittest.TestCase):
    def test_v3_raid_hba_display_sata_and_missing_are_isolated(self):
        # Synthetic controller records; no production serials or raw logs.
        content = """PCI Adapter 1 : Sample VGA
slot number : 1
  Display Controller
    EID : N/A
    PLDM : types(0x0) { Monitor&Control(N), FRU(N), FwUpdate(N), RDE(N) }
    Seg|Bus|Dev|Func : 0 | 2(0x2) | 0 | 0
PCI Adapter 2 : Integrated SATA Controller
slot number : 2
  SATA Controller
    EID : N/A
    PLDM : types(0x0) { Monitor&Control(N), FRU(N), FwUpdate(N), RDE(N) }
PCI Adapter 3 : ThinkSystem RAID Adapter
slot number : 8
  RAID Controller
    EID : 0xb
    PLDM : types(0x21) { Monitor&Control(N), FRU(N), FwUpdate(Y), RDE(N) }
    Seg|Bus|Dev|Func : 0 | 87(0x57) | 0 | 0
    firmware 1:
      firmware name : Controller Firmware
      version string : 1.2.3
PCI Adapter 4 : Sample SAS HBA
slot number : 9
  SAS Controller
    EID : 0xc
    PLDM : types(0x31) { Monitor&Control(N), FRU(Y), FwUpdate(Y), RDE(N) }
    Seg|Bus|Dev|Func : 0 | 88(0x58) | 0 | 0
    Link Status : 3
    Link Speed : 12
PCI Adapter 5 : Sample HBA without capability record
slot number : 10
  HBA Controller
    EID : 0xd
"""
        result = parse_pcie_inventory(dmdb_text=content, dmdb_source="fixture/pci.txt")
        self.assertEqual(len(result["adapters"]), 5)
        self.assertEqual(result["ports"], [])
        display, sata, raid, hba, missing = result["adapters"]
        for row in (display, sata):
            self.assertEqual(row["pldm_types"], [])
            self.assertEqual(row["pldm_mask"], "0x0")
            self.assertEqual(row["pldm_capabilities"], {"Monitor&Control": False, "FRU": False, "FwUpdate": False, "RDE": False})
        self.assertEqual(raid["eid"], "0xb")
        self.assertEqual(raid["pldm_types"], [0, 5])
        self.assertEqual(raid["pldm_capabilities"], {"Monitor&Control": False, "FRU": False, "FwUpdate": True, "RDE": False})
        self.assertEqual(raid["firmware"], "Controller Firmware: 1.2.3")
        self.assertEqual(hba["pldm_types"], [0, 4, 5])
        self.assertEqual(hba["firmware_components"], [])
        self.assertEqual(missing["pldm_mask"], "")
        self.assertEqual(missing["pldm_capabilities"], {})
        self.assertTrue(all(a["source"] == "fixture/pci.txt" for a in result["adapters"]))
        self.assertEqual(parse_nic_inventory(dmdb_text=content)["adapters"], [])

    def test_v3_multifunction_hba_uses_first_identified_function(self):
        content = """PCI Adapter 1 : Dual-function SAS HBA
slot number : 4
  SAS Controller
    EID : N/A
    PLDM : types(0x0) { FwUpdate(N) }
    Seg|Bus|Dev|Func : 0 | 86 | 0 | 0
  HBA Controller
    EID : 0x0e
    PLDM : types(0x21) { FwUpdate(Y) }
    Seg|Bus|Dev|Func : 0 | 86 | 0 | 1
  RAID Controller
    EID : N/A
    PLDM : types(0x0) { FwUpdate(N) }
    Seg|Bus|Dev|Func : 0 | 86 | 0 | 2
"""
        row = parse_pcie_inventory(dmdb_text=content)["adapters"][0]
        self.assertEqual((row["eid"], row["pci_bdf"], row["pldm_types"]), ("0x0e", "0000:56:00.1", [0, 5]))
        self.assertEqual(len(row["functions"]), 3)
        self.assertEqual([f["pci_bdf"] for f in row["functions"]], ["0000:56:00.0", "0000:56:00.1", "0000:56:00.2"])
        self.assertEqual(row["primary_function_line"], row["functions"][1]["line"])
        self.assertEqual(row["functions"][2]["pldm_capabilities"], {"FwUpdate": False})

    def test_v3_global_pldm_section_cannot_overwrite_last_adapter(self):
        content = """PCI Adapter 1 : Sample RAID
  RAID Controller
    EID : 0xb
    PLDM : types(0x21) { FwUpdate(Y) }
PLDM firmware:
    EID : 0x99
    PLDM : types(0x0) { FwUpdate(N) }
"""
        row = parse_pcie_inventory(dmdb_text=content)["adapters"][0]
        self.assertEqual(row["eid"], "0xb")
        self.assertEqual(row["pldm_types"], [0, 5])

    def test_v4_all_devices_require_exact_eid_and_address_association(self):
        content = """TID | EID | Address | VID | PLDM Types | Event Types
001 | 0x0B | 0x000A0000 | 0x1000 |0, 5 |0
002 | 0x0B | 0x000B0000 | 0x1000 |0, 4, 5 |0, 2
003 | 0x0C | 0x000A0000 | 0x1000 |0, 6 |0
004 | 0x0D | 0x000C0000 | 0x1000 |0, 2 |0
Slot 01, Addr 0x000A0000, [1000 0014 17AA 0001], lsa, Broadcom RAID Adapter, EID(0x0B), 1.0
Slot 02, Addr 0x000B0000, [1000 0015 17AA 0002], lsa, SAS HBA Adapter, EID(0x0B), 2.0
Onboard 01, Addr 0x000C0000, [1A03 2000 1A03 2000], devmgr, VGA Controller, EID(0x00), 3.0
"""
        rows = parse_pcie_inventory(io_text=content)["adapters"]
        self.assertEqual(len(rows), 3)
        self.assertEqual([(r["tid"], r["pldm_types"]) for r in rows], [("001", [0, 5]), ("002", [0, 4, 5]), ("", [])])
        self.assertEqual(rows[0]["pldm_capabilities"], {"Monitor&Control": False, "FRU": False, "FwUpdate": True, "RDE": False})
        self.assertTrue(rows[1]["pldm_capabilities"]["FRU"])
        self.assertEqual(rows[2]["pldm_capabilities"], {})
        self.assertEqual(rows[2]["slot"], "Onboard 1")
        self.assertEqual(parse_nic_inventory(io_text=content)["adapters"], [])

    def test_v4_conflicting_endpoints_do_not_invent_union_capability(self):
        content = """Slot 01, Addr 0x000A0000, [1000 0014 17AA 0001], lsa, RAID Controller, EID(0x0B), 1.0
001 | 0x0B | 0x000A0000 | 0x1000 |0, 5 |0
002 | 0x0B | 0x000A0000 | 0x1000 |0, 4 |0, 2
"""
        result = parse_pcie_inventory(io_text=content)
        row = result["adapters"][0]
        self.assertEqual(row["tid"], "")
        self.assertEqual(row["pldm_types"], [])
        self.assertEqual(row["event_types"], [])
        self.assertTrue(row["pldm_ambiguous"])
        self.assertEqual([e["pldm_types"] for e in row["pldm_endpoints"]], [[0, 5], [0, 4]])
        self.assertTrue(any("conflicting pldm_types" in note for note in result["notes"]))

    def test_v4_named_flags_are_only_kept_when_explicit(self):
        content = """Slot 01, Addr 0x000A0000, [1000 0014 17AA 0001], lsa, RAID Controller, EID(0x0B), 1.0
001 | 0x0B | 0x000A0000 | 0x1000 |0, 5 {FwUpdate(Y), FRU(N)} |0
"""
        row = parse_pcie_inventory(io_text=content)["adapters"][0]
        self.assertEqual(row["pldm_types"], [0, 5])
        self.assertEqual(row["pldm_capabilities"], {"FwUpdate": True, "FRU": False})

    def test_v4_numeric_capabilities_and_missing_types_remain_distinct(self):
        for value, expected in (("0, 2, 5, 6", {"Monitor&Control": True, "FRU": False, "FwUpdate": True, "RDE": True}),
                                ("0", {"Monitor&Control": False, "FRU": False, "FwUpdate": False, "RDE": False}),
                                ("N/A", {}), ("", {}), ("0, 5, ...", {}), ("0, 99", {})):
            with self.subTest(value=value):
                raw = V4_CARD + '\n005 | 0x0C | 0x00EA0000 | 0x8086 |' + value + '|0\n'
                row = parse_nic_inventory(io_text=raw)['adapters'][0]
                self.assertEqual(row['pldm_capabilities'], expected)
        self.assertEqual(nic_inventory._v4_capabilities('0, 5 {FwUpdate(N)}'), {'FwUpdate': False})

    def test_generic_entry_keeps_nic_behavior_and_empty_input(self):
        self.assertEqual(parse_pcie_inventory(), {"adapters": [], "ports": [], "notes": []})
        self.assertEqual(parse_pcie_inventory(dmdb_text=V3), parse_nic_inventory(dmdb_text=V3))
        text = V4_CARD + "\n" + V4_PORT + "\n" + TABLE
        self.assertEqual(parse_pcie_inventory(io_text=text), parse_nic_inventory(io_text=text))


if __name__ == "__main__":
    unittest.main()
