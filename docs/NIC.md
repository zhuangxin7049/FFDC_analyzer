# NIC inventory and firmware evidence

The 2026-10-15 implementation follows the user-supplied `FFDC AI analysis for NIC.xlsx`, Sheet1 A1:B29. The sheet supplies field examples and log locations, not a vendor-independent firmware outcome grammar.

## Inventory

- V3: `tmp/ffdc_live_dbg/dmdb_pci_dumper.txt`. Parse NIC adapter blocks with EID, explicit segment/bus/device/function, VID/DID/SVID/SDID, slot, named firmware components, PLDM bitmask and stated capabilities. Link status codes are 0=NotSupported, 1=Unknown, 2=Down, 3=Up. An absent port identifier or speed unit remains unspecified.
- Multiple Ethernet Controller sections remain functions of one physical adapter. The first function with a usable EID supplies the management identity; all function identities are retained separately. Physical ports retain their function BDF, explicit port index and permanent MAC, without borrowing values from logical ports.
- V4: `tmp/io_devices.txt`. Parse Slot/Onboard inventory and per-port MAC/state/speed. Join the PLDM endpoint table using both EID and address; ambiguous TIDs remain unspecified. Preserve packed `Addr` as reported rather than inferring an undocumented PCI BDF encoding.
- Records retain relative source paths and 1-based line numbers. Inventory Down/zero-speed observations are informational and do not independently prove a faulty NIC.
- The report displays primary-management PLDM types and capabilities in PCIe Device Details for all collected PCIe devices, including NIC, RAID and HBA. Explicit zero masks and N flags are preserved; absent fields remain not reported. V4 endpoint conflicts remain ambiguous rather than combining different capabilities. The separate PLDM capabilities and NIC PCI functions disclosures are removed; the parsed NIC function records remain available to AI and API consumers.
- An independent PCIe enrichment marker refreshes PLDM metadata in older reports without re-running NIC archive collection. Matching requires unique device identity, and updates retain existing firmware, drive and virtual-drive data. API and AI adapter details include the same PLDM values and source references.
- PCIe enrichment version 2 distinguishes same-slot, same-name functions by explicit serial identity; conflicting serials remain unmatched. Fresh V4 minilog merges also use unique serial identity rather than repeatedly overwriting the last function in a slot. Legacy inventory identities remain unchanged when PLDM metadata is refreshed.
- Complete V4 numeric PLDM type lists supply named support using [DSP0245 Table 1](https://www.dmtf.org/sites/default/files/standards/documents/DSP0245_1.3.pdf): type 2 Monitoring and Control, 4 FRU, 5 Firmware Update and 6 RDE. Explicit named flags take precedence. Missing or partial type lists remain unspecified. Conflicting endpoint records remain ambiguous. Refresh updates PCIe and existing network PLDM fields in memory without repeating firmware archive collection or rewriting stored reports.

## Firmware sources

| Evidence | V3 | V4 |
| --- | --- | --- |
| Flash history | `pstorage/flash/flash_history.log` | `pstorage/persist/fm/flash_history.log` |
| Firmware manager | `tmp/fm.log` | If collected at a supported location |
| Transport | `tmp/mctp_trace.log` | `tmp/mctp_trace.log`, `var/log/pldm.log` |
| BMU script status | `tmp/ibmulog/bmu_fwrpm.log` | `tmp/ibmulog/bmu_fwrpm.log` |
| Nested support logs | `tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz` and `tmp/ibmulog/lenovobmu.tgz` | If collected |
| Vendor update log | `var/log/Lenovo_Support/*.log` inside the Lenovo BMU archive | `tmp/ibmulog/*_fw*_nic_*.log`, including Broadcom fw/fwutl examples |

The collector streams nested tar/gzip members within depth, file-count, compressed/expanded-byte and text budgets. It materializes selected text under the report's `_nic_firmware/` directory using safe deterministic names. Each readable path retains its original archive-member chain. It rejects unsafe names and non-regular members, and reports missing, unreadable or truncated evidence explicitly.

`report.network` owns inventory and port snapshots displayed in the report. `report.nic_firmware` owns source coverage, observations and archive origins for system-summary export, API, Network Agent and chat evidence tools. The dedicated NIC Firmware Update Evidence section, including its source table, log excerpts and explanatory notes, is hidden from the report page at the user's request. Existing reports with retained raw files are enriched in memory on access; source logs and historic report files are not rewritten by reads. A subsequent explicitly requested analysis can save the enriched report through its normal workflow.

Shared PLDM/MCTP logs are transport evidence; BMU launch/completion is support evidence. Vendor names alone do not prove NIC ownership. New collected event statuses remain `Observed`: successful BMU execution cannot establish NIC upgrade success, and missing logs cannot establish failure. Existing validated PLDM attempt parsing continues independently. Device identity, timestamps, terminal results and post-update versions must be correlated before the AI states an upgrade outcome.

## Validation

Run `python3 -m unittest test_nic_inventory test_nic_firmware test_nic_workspace test_nic_integration` plus the existing workspace, JIRA, domain-pack, SnapDump and guarded-release tests. Fixtures cover the sheet's examples, multiple devices, missing fields, legacy report enrichment, nested logs, bounded/invalid archives, evidence citations and HTML escaping. Release staging records actual server file hashes before installation and requires a checksum-verified full backup.
