# FFDC Analyzer Current Status

## 2026-10-30 — Collapsible PSU status flags (20261030-psu-collapse1)

- Active status flags in PSU analysis are now shown in a closed-by-default details panel and expand on demand.

## 2026-10-30 — Release metadata consistency (20261030-about-cleanup2)

- The current-release date now comes from the active release note and is shared by the About page and retained `/api/version` response.

## 2026-10-30 — About page cleanup (20261030-about-cleanup1)

- Removed the Public version endpoint explanation from the About & releases page.
- Release notes remain explicitly maintained in the workspace source; deployments do not infer note text from a code diff.

## 2026-10-30 — Defect Review multi-tab launcher (20261030-defect-links2)

- The assignee launcher opens each Bug URL with a regular new-tab request and clears opener access after creation, improving compatibility with browser popup handling.

## 2026-10-30 — Defect Review assignee bug links (20261030-defect-links1)

- Engineer names in the Defect Review workload table now open every JIRA bug assigned to that engineer in separate browser tabs.
- Defect Review pages no longer show Try New version or Reports in their classic top navigation.

## 2026-10-29 — In-app maintenance unread count (local, not deployed)

- The shared workspace navigation now displays a red unread badge beside Maintenance log when records were created after the current browser's last-read marker.
- Opening the Maintenance log page marks the currently visible records read for that browser. The count refreshes every 30 seconds and does not require SMTP or email delivery.
- Focused workspace, SnapDump, and workspace-quality validation passed: 59 tests, plus Python compilation and JavaScript syntax checks. Production deployment has not been performed.

## 2026-10-29 — Workspace language-aware FFDC upload (local, not deployed)

- The shared top-bar English / Chinese control now selects the automatic question used when an FFDC is uploaded without typed text. Chinese mode sends `请分析这个 FFDC 并总结关键发现。`; English mode keeps the existing English prompt. Rule-authoring document uploads follow the same language choice.
- The homepage workspace sidebar no longer exposes the Milestones link. The direct milestones route remains available for existing links and backend behavior.
- Focused workspace, SnapDump, and workspace-quality validation passed: 58 tests, plus Python compilation and JavaScript syntax checks. Production deployment has not been performed.

## 2026-10-28 — Workspace language, version, and maintenance tools (20261028-workspace-tools1)

- The existing workspace layout now exposes a persistent English / Chinese page-language switch.
- About & releases shows the deployed product marker and the public `/api/version` response.
- Maintenance registration stores bounded, reviewable records under the runtime data directory.

## 2026-10-28 — Davy vision model switched to Nemotron VL (20261028-ai-vision1)

- FFDC JIRA screenshots and rendered reference-document pages now default to Davy `nemotron-3.5-super-vl`, which currently has two workers and a 1048576-token context limit. Text chat and deep investigation model routing is unchanged.
- The `FFDC_VISION_MODEL` environment override remains available for an intentional rollback or comparison. Focused model-routing tests cover the new default.

## 2026-10-27 — Davy Nemotron Ultra replacement (20261027-ai-model1)

- Davy's `nemotron-3-ultra` entry is stale and has no healthy worker. Chat, deep investigation, standard report calls, and legacy environment/configuration values now route it to the live `nemotron-3-super-120b` model, which currently has two workers and a 262144-token context limit.
- Added a focused regression suite for default routing and protected `api_key.txt` model compatibility. Local validation and production deployment are recorded under `work/releases/20261027-ai-model1/`.

## 2026-10-27 — PCIe VID/DID decimal inventory normalization (20261027-pci-id-hex1)

- PCIe JSON inventory fields such as `VendorId=32902` and `DeviceId=4681` are now rendered as the conventional 16-bit hexadecimal IDs `0x8086` and `0x1249`; subsystem IDs receive the same normalization.
- The parser keeps the original decimal source values in the evidence text for traceability and also exposes a structured `pci_ids` mapping for the UEFI enumeration rows.
- V3 text inventory accepts decimal VID/DID groups when the source uses decimal-width values while preserving the existing hexadecimal interpretation for normal four-digit/`0x` tokens.
- Focused validation: 40 NIC inventory/integration tests passed; Python compilation and JavaScript syntax checks passed. Production deployment is not claimed for this local change.

## 2026-10-27 — AI outage fallback for workspace chat (20261027-ai-fallback1)

- When the configured AI service is unavailable or returns a malformed response, focused parsed-report explanations use only retained deterministic evidence; greetings return immediately and other questions receive a clear retry message instead of exposing `tuple index out of range` or HTTP 500 details.
- The fallback does not invent diagnostic conclusions. The normal AI path remains unchanged when the provider is healthy.
- Added regression coverage for provider failure, greeting fast-path, and report-warning explanation fallback.

## 2026-10-27 — EGS/Genoa SEP profiles added (20261027-egs-sep2)

- Added a separate `egs_genoa` parser profile for APIDs `0x40` (SEP 4MW), `0x42` (SEP 8SW), `0x44` (SEP 4MEG), `0x45` (SEP 8EEG), and `0x49` (SEP 2MEG), using their documented Silicon IDs and the supplied EagleStream-Genoa SEP FW Specification v0.81.
- EGS/Genoa status tables no longer borrow BHS/V4/V5 meanings: SAS/SATA-only, SAS/SATA/NVMe, EDSFF `0xC2/0xC0/0x80`, checksums, logical slot counts, communication/PGOOD, AutoConfig, identity mismatch and EGS capacity limits are decoded separately. SP-000008 v1.06 remains the V4/V5 baseline.
- Added regression fixtures for all five APIDs, EDSFF presence decoding, C4 type faults, wrong Silicon IDs and over-capacity status records. Focused backplane suites pass locally before deployment.

## 2026-10-27 — CFF PSU v4/v5 log analysis skill integrated

- Added deterministic PSU parsing from the supplied CFF Power Supply v4 Rev. 3.1, v5 Rev. 2.4 and spec-to-log comparison guide. The analyzer discovers `psu_log_info` and `psu_dump.log`, selects v4/v5 from platform/source evidence, retains raw records, decodes D0h/D2h composite status flags, converts VBULK, and keeps unsupported telemetry conversions raw.
- PSU1/PSU2 first-four-record views, electrical/protocol distinction, source lines, raw bytes, unknown-layout limitations, compact AI context and PSU agent evidence are included.
- Local and server-stage validation: 118 focused tests passed, Python/JavaScript syntax checks passed. Release `20261027-psu-skill6` is deployed with a verified backup at `/root/data2/ffdc-analyzer-backups/20261027-psu-skill6`; live verification covered both embedded PSU evidence and direct `psu_log_info` upload.

## 2026-10-27 — standalone MCTP trace and PLDM log analysis (20261027-standalone-logs1)

- Plain `.log`, `.txt`, `.trace`, `.out`, `.journal`, `.dmesg`, and numeric rotated log copies can be uploaded directly from the workspace or classic upload page. The analyzer identifies MCTP traces and PLDM logs from the filename/content and creates a standalone report.
- MCTP reports include direction, endpoint pairs, CTRL operations, error/timeout lines, bounded event excerpts, and identity limitations. PLDM reports include categories, TID/EID observations, sensor and firmware-update evidence, terminal update status, error/timeout lines, and source line numbers.
- Standalone reports retain the original log in the report download archive. They do not assign a physical NIC, RAID adapter, or backplane without separate identity evidence. Full FFDC archive analysis remains unchanged.
- Local validation: 113 focused tests passed, Python compilation and JavaScript syntax checks passed, and retained MCTP/PLDM logs were replayed.

## 2026-10-23 — rotated PLDM logs are retained as evidence (20261023-pldm-rotated2)

- Numeric rotated text logs such as `var/log/pldm.log.1` are now accepted by the raw evidence tools, listed by the workspace, readable by path, searchable, and included in NIC/firmware evidence discovery.
- The analyzer discovers the full PLDM log family during a new parse, uses a rotated copy when the current `pldm.log` is absent, and passes all discovered copies to PLDM/BMC evidence parsing. The original report remains evidence-scoped and no archive file is modified.
- Replayed the retained E835 FFDC `1792731009-db6412a5-7DG9CTO1WW_JPHYHS02_xcc3_DebugLog_260813-131304.tar.zst`: both `var/log/pldm.log` and `var/log/pldm.log.1` are now reported as available sources. Release evidence is recorded in `work/releases/20261023-pldm-rotated2/`.

## 2026-10-20 — English header contact (20261020-contact-en1)

- The shared upper-right contact now reads “For any questions, please contact: zhuangxin2@lenovo.com”, with English language metadata and the existing mailto link.
- Existing shared desktop and mobile header layout is retained. Release tests and live verification are recorded under `work/releases/20261020-contact-en1/`.

## 2026-10-20 — Header support contact (20261020-contact2)

- The shared workspace header now displays “如有任何问题请联系：zhuangxin2@lenovo.com” at the far right with a mailto link, on both the conversation workspace and themed subpages.
- Deployment navigation checks follow the installed WORKSPACE_NAV declaration, allowing the current sidebar without requiring the removed Defect Review item.
- Desktop header dimensions remain unchanged. On narrow screens the contact moves to its own right-aligned row; a shared header-height variable keeps the main content and navigation/context drawers aligned.
- Workspace/SnapDump and deployment tests pass (85 local checks). Browser checks cover desktop right alignment, complete 320px contact visibility, and both main/subpage drawer offsets. Production verification is recorded under `work/releases/20261020-contact2/`.

## 2026-10-20 — Workspace navigation cleanup

- Removed Defect Review from the shared workspace sidebar. The existing `/Defect_review` route and its workspace view remain directly accessible.
- Renamed the `/reports` navigation item and report-list page to History. The classic history page retains its Try New version link.
- Local and remote focused suites passed 67 tests (2 remote skips). Live checks confirmed the new sidebar, history page, direct Defect Review route, and active service after deployment. Targeted rollback backups are `sidebar-history-20261020-101354` and `sidebar-history-20261020-101601` under the server application's `backups/` directory.

## 2026-10-19 — report completion links in the conversation (20261019-report-link1)

- The first successful FFDC answer now ends with a highlighted "Analysis report generated" card and an "Open full analysis report" link. JIRA collections list every distinct report with its attachment filename. Links open the existing workspace report in a new tab.
- Report link metadata stays with the completed answer across refreshes and later report selections. Follow-up answers for the same report do not repeat the card; historical answers with a retained report ID get a compatible direct link. Errors, empty answers, general project chat and rule authoring do not announce completion.
- Card wording follows the question language. Controls are rendered by the UI and are excluded from model history and copied answer text. Existing upload defaults, sidebar links and report routes are preserved.
- Regression and deployment evidence is recorded in work/releases/20261019-report-link1/.

## 2026-10-19 — English default FFDC upload question (20261019-upload-english2)

- Submitting an attached FFDC with an empty question now sends "Analyze this FFDC and summarize the key findings." The existing language selection chooses English from that question without an additional language instruction in the conversation. Chooser/drop uploads and Enter/Send use the same existing upload and report-chat flow.
- Explicit questions retain their text and requested language. Rule-authoring document prompts, Shift+Enter and IME composition retain their existing behavior.
- Targeted DOM-event regression follows the upload job through the final report-chat payload, including a Chinese browser locale and prior Chinese conversation. Release evidence is recorded in work/releases/20261019-upload-english2/.

## 2026-10-19 — visible BP/SEP Unknown reasons (20261019-unknown1)

- Every retained Unknown slot group now has an always-visible explanation next to its badge, with the affected reported slots or unmapped local indices and raw bytes. Identical causes are grouped without dropping later slots or reasons.
- Identity context includes raw APID, Silicon ID and communication byte when collected. Missing control, unsupported layouts, PGOOD/communication/initialization limits, extended validity and reserved-bit conflicts retain their specific reasons. Unknown SEP Type and Protocol Support metadata also explain the unmapped field.
- Historical Unknown summaries without per-slot evidence explicitly say the reason was not retained and request the original registers. The generic Snapshot validation label remains hidden.
- This is a presentation change. SEP decoding, classification, counts, independent fault flags, raw sources, stored reports and historical AI output are unchanged. Local and deployment verification is recorded in work/releases/20261019-unknown1/.

## 2026-10-19 — retained FFDC backplane regression (20261019-sep6b)

- Audited 306 report/cache locations and 366 original-archive locations in active retention, including uploaded, incoming, cached and collection-member inputs. SHA256 and aliases are recorded for 1,550 source files. The frozen corpus contains 383 distinct evidence/report contexts; these are not 383 independent machines. Runtime/source backups are excluded from active retention.
- Replayed 338 contexts containing original SEP register evidence. Another 42 original sources contain no usable SEP snapshot, two contexts lack retained register sources, and one is a non-FFDC attachment. All 51 unreadable archive locations (48 empty, two copies of a truncated tar, one 53-byte input) remain explicit coverage gaps, never passes.
- Fixed silent loss of per-SEP status observations when the whole-board/next-SEP boundary is shorter. Keep every declared raw byte with a local index, keep unmapped observations Unknown, and withhold ambiguous topology mappings. Missing control/start data retains local observations without inventing physical bay numbers. A partial set of SEP controls cannot establish the board's full boundary.
- Recovered empty historical backplane reports from their own retained structured source, with report-local path containment. This restores the C5 type-fault indication in report 20261006-191340-e20d1e60 while preserving its format, other inventory and stored AI result.
- Unknown legacy identities stay unverified, including APID51 and APID54 without an applicable firmware table. Unsupported HFC semantics cannot create mapping conflicts. Modern and documented legacy SEP tables are unchanged; original categories and independent fail/type-fault flags remain stable in all shared observations.
- Fixed comma-list whitespace dropping later slots from generic Drive Fail/Rebuilding/Locate badges. Added per-SEP visible-badge/backend-set equality checks: 23 mismatches in the original corpus, zero in the final candidate. The guard cannot be waived as a data gap.
- Reviewed 1,486 exact before/after field changes in 75 contexts. Gate: zero unreviewed changes, zero dropped status observations, zero invalid-data fault assertions. There are 429 reviewed data/identity/range limitations and 44 context-level source gaps. A historical VPD summary differs only by a location label; identities and conclusions agree.
- Local validation: 447 tests, 3 skipped for unavailable real SnapDump fixtures; staged suite: 433 tests with the same 3 skips. The audit/collector tests add 14 checks. Server staged suite: 433 tests, 7 skipped (five unavailable real SnapDump fixtures and two Node.js checks covered locally). Live deployment must be verified separately. Audit artifacts: work/backplane-regression-20261019/.

## 2026-10-16 SnapDump verified factual answers

- Release `20261016-avenger5` answers narrow MPI3 device identity/range and IOC-count questions directly from parsed values and complete original-log citations. Numeric conversions, range ends and enum uncertainty do not depend on model arithmetic. For example 0x165 plus 0x12 reserved IDs ends at 0x176, while its offset is independent of physical DSN.
- Slot/model/ID questions require unique matching PD records and sufficient authorized raw excerpts. IOC answers preserve NumberOfIocs internal semantics and IocState/EtpDevType uncertainty. Open diagnosis, health, firmware and action questions continue through the configured Davy provider. Unsupported, ambiguous or insufficiently cited facts also retain the provider path.
- Existing ownership, question validation, rate/concurrency and post-response stale checks apply to both answer paths. Validation: 240 local tests, including HTTP isolation/provider-fallback checks; unchanged parser has 127-location corpus evidence. Deployment and live evidence are recorded under `work/releases/20261016-avenger5/`.

## 2026-10-16 SnapDump Davy hexadecimal identity context

- Release `20261016-avenger4` retains the AV1/AV2 parser, slot and IOC changes in avenger3 and strengthens the actual Davy device-question path. Requested PD identifiers receive a bounded fact sheet with hexadecimal/decimal enclosure and observed slot values, current PD ID and address-identity limitations.
- MPI3 Pd numeric fields remain hexadecimal even with digit-only tokens: raw enclDeviceId=176 is 0x176 (374 decimal). PD=16e already supplies the current PD/Persistent ID 0x16e; PdPrst INDEX/UniqueId and addr[0] are not presumed WWN joins. Raw log excerpts remain required for citations. Davy is instructed to cite source IDs without inventing line numbers inside a supplied excerpt.
- Validation: 236 focused/regression tests; the unchanged avenger3 parser parsed all 127 corpus locations without prior snapshot/severity drift. Guarded deployment and actual Davy answer checks are recorded under `work/releases/20261016-avenger4/`.

## 2026-10-16 AV1 / AV2 SnapDump rule boundaries

- Release `20261016-avenger3` identifies generation and RoC/IOC role from current snapshot ChipName. AV1 profile fallback and external-DDR checks require matching AV1 identity; explicit known FwMode remains usable for AV2. Conflicting identity suppresses mode-dependent checks. AV2 pages do not borrow AV1 manufacturing-page purpose labels.
- Persistent ID range membership and ID offset are separate from the observed Pd slotNumber. Noncontiguous DSN is valid; no physical slot is calculated from PID arithmetic and no mapping conflict is inferred from that arithmetic. `range_slot` remains null for compatibility.
- Host Interface evidence inventories IOC indices, raw bus/device-function/state fields and function counts. Generic Config NumberOfIocs remains a separately scoped literal counter. Physical-card count and Supervisor role remain unverified without explicit identity/mapping evidence; management visibility is separate from OS visibility.
- StoreLib/communication status and collection-context observations preserve their namespaces and source lines. Zero return data requires command validity, populated bits and transferred length; collection errors do not become active media failures. Davy retains complete required excerpts even when nearby context overlaps.
- The English evidence panel and Davy expose these boundaries with original-log navigation. Davy stays below the results. The supplied reference catalog records which candidate rules have been implemented and which remain documentation-only.
- Validation: 235 local focused/regression tests and all 127 corpus locations passed; existing corpus snapshot fields and severity counts are unchanged. Additional 460 capture verification confirms SAS5032W AV2 IOC, PerfIT, four Host Interface IOC records and a separately scoped Generic Config counter of 1. Production evidence is recorded separately under `work/releases/20261016-avenger3/`.

## 2026-10-16 Legacy SEP identity compatibility

- Release `20261016-sep5` recognizes legacy PSoC APIDs 60-66 only with their matching Silicon ID, using the 2017 SEP FW Rev 1.08 legacy definitions. The user-confirmed SP-000008 v1.06 baseline remains unchanged for V4/V5. Unknown identities still do not borrow another status table.
- The NEW29 report `20261016-110542-99b905f1` contains APID 63 / SEP 8S100 and APID 64 / SEP 2M, with 8 and 2 SAS/SATA-present status bytes 80. The prior identity tightening omitted these older APIDs and showed Unknown.
- Legacy per-SEP slot counts now use Status[01], and starting bays use the documented Group ID mapping or NVMe Bay ID in A0 mode. Modern reserved control fields are not interpreted as slot/HFC/configuration data. Unequal per-SEP counts do not create false modern total/HFC conflicts.
- Legacy snapshots have their own checksum, power, initialization, status-valid and capacity guards. Type-fault bit 2 and drive-fail/attention bits retain separate checks. Marker 5 refreshes retained reports in memory without altering report.json or source logs. Deployment proof is staged under `/home/zhuangxin2/ffdc_release_stages/20261016-sep5/`.

## 2026-10-16 Avenger SnapDump evidence

- Release `20261016-avenger2` adds MPI3-specific operating mode, device mapping, configuration coverage and diagnostic observations using the user-supplied July/August 2025 Avenger references. Legacy module decoding remains separate.
- Snapshot personality/profile/runtime are reconciled; EVP may use managed LD/PD counts without requiring DDR counters. PerfIT and FeatureHBA do not borrow RAID counts, unknown enums remain unverified, and conflicting modes suppress mode-dependent checks. Historical TTY profile candidates never select the current mode.
- DevPrst ranges preserve both PHY words and distinguish explicit PD slots from range candidates/conflicts/overlaps. SES is separate from disks. PdPrst INDEX/UniqueId and old missing-device flags are not assumed to identify current disks or current failures.
- ConfigPages records identify DEFAULT/CURRENT/PERSISTENT, page/IOC/address and collected word coverage. Complete, unambiguous page bodies may be compared as raw data; no unsupported field offsets, board pinouts or link-rate enums are invented.
- Bounded diagnostic observations preserve exact source lines for ASSERT, IOCStatus/IOCLogInfo, Sense, Safe Mode, DDR/ECC, NAND and cache offload/restore. Categories receive separate retention space. History and current health remain separate; suggested additional evidence is problem-specific. Binary traces and bundled utilities are inventoried without execution or decoding.
- Davy groups sparse PD header/slot/inquiry fields into one bounded original excerpt and retains DevPrst column headings. Enclosure ELID, range PerID and PdPrst UniqueId meanings remain distinct.
- The English Evidence details panel provides source navigation and keeps Davy at the bottom. Davy can reopen mapping/profile/configuration sources while retaining existing browser-session and JIRA boundaries.
- Validation artifacts are in `work/avenger-upgrade-20261016/`; 127 corpus locations parsed with no existing snapshot/severity drift. Deployment status must be checked using `/new-version` and `/home/zhuangxin2/ffdc_release_stages/20261016-avenger2/result.json`, not inferred from this document.

## 2026-10-15 SnapDump corpus compatibility

- Release `20261015-snapdump2` addresses the `/mnt` corpus: 115 ZIPs and 12 unpacked snapshots represent 114 distinct text-log sets across 14 controller models. The four ZIP members of `snapdump.7z` are byte-identical duplicates. Other TAR/TGZ and LZO FFDC containers were inspected for additional SnapDump members; none were found.
- All 127 input locations parse successfully. Seven large `PL_MODULE.txt` exports and three unpacked copies previously failed the 16 MiB per-entry limit. ZIP text entries now permit 40 MiB within the existing 64 MiB total/50 MiB upload bounds; standalone text stays 16 MiB. Cache accounting includes actual Python object sizes, Unicode and result structures within the unchanged 128 MiB cap.
- Named single-dword NVRAM reset exports, MPI3 RAID Cnt fields/Pd.txt, empty firmware fields, hexadecimal slot tokens and missing-field explanations are covered. HBA/PerfIT does not borrow RAID disk counts; packed per-volume states and unnamed POR/HIP memory data remain undecoded. Three no-PL snapshots and one raw-NVRAM snapshot retain their genuine evidence gaps.
- Davy retrieval preserves current identity/PCIe fields, prioritizes nonzero drive-error evidence, and opens cited line ranges beyond the 500,000-character raw-file preview. Event display distinguishes records shown from parsed historical totals. Navigation and bottom-of-results chat are retained.
- Validation: 99 SnapDump/parser/provider/session/UI tests, 85 existing workspace/chat/JIRA tests, 16 deployment-helper tests, Python compilation and JavaScript syntax. The complete per-sample HTML/CSV/JSON report is under `deliverables/snapdump-corpus-20261015/`; reproducible offline analysis is in `work/analyze_snapdump_corpus.py`.
- Deployment evidence is staged under `/home/zhuangxin2/ffdc_release_stages/20261015-snapdump2/`; consult `result.json` and the served `/new-version` marker for live status. The complete verified pre-release backup is managed by `work/deploy_release.py`.

## 2026-10-15 SEP-specific type-fault audit

- Release `20261015-sep4` selects modern drive-status layouts by APID: BF uses NVMe-only Table 62, BB uses AnyBay Table 59, BC uses mixed Table 60, and BE/C0/C1 use EDSFF Table 61. Legacy identity uses its explicit capability; unknown identity and unexpected codes remain unverified instead of guessing a table from status bytes.
- Validated Drive Type Fault bit 2 now reaches the same BP Type Fault warning/badge for 4NV5 84/86 and AnyBay C4/C5/C6/85. Combined Fail/Rebuild/Locate bits are preserved independently, so a full-byte lookup cannot hide a type fault. Per-slot, per-SEP, power, checksum, initialization and reserved-bit guards remain enforced.
- A0 alone remains a supported configuration. Healthy NVMe/empty/attention states do not become type faults. Marker 4 refreshes historical reports in memory without rewriting original reports or logs. Deployment evidence is staged under `/home/zhuangxin2/ffdc_release_stages/20261015-sep4/`.

## 2026-10-15 C4 Drive Type Fault decoding

- Release `20261015-sep3` corrects C4 in the supported tri-model/AnyBay status tables: Drive Type Fault bit 2 is asserted, so the status produces a Warning and a red BP Type Fault badge. Supported Auto-config A0 alone remains legal and cannot suppress an asserted fault bit. This indication does not establish a cable or physical backplane failure.
- Real report `20261015-162329-534e41e2` has Trinculo SAS/SATA/NVMe BP3 SEP0 C4 on bays 16-19 with Control 0D=05; SEP1 bays 20-23 remain normal. Invalid snapshots and unrelated layouts retain their validation guards.
- In-memory enrichment marker 3 refreshes retained old report bytes for API, AI and UI without changing report.json or raw logs. Deployment evidence is staged under `/home/zhuangxin2/ffdc_release_stages/20261015-sep3/`.

## 2026-10-15 Backplane identity and mapping columns

- Release `20261015-bp-layout3` removes controller_slot, eid and evidence columns from the controller-to-bay mapping table. Backend identity and confidence evidence are unchanged.
- Configuration type labels now include the collected VPD board description and the SEP application when identified. All-unavailable optional width, active-protocol and UBM columns are omitted, with the evidence gap explained. Collected zero/none and invalid configuration bits remain visible; legacy registers never borrow V4/V5 meanings.
- Screenshot report `20261015-151409-beda9979` contains legacy V3 SEP data and an explicit NEW28 1x8 2.5 SATA/SAS VPD description. The prior UI ignored that name and displayed modern configuration columns without usable data. Deployment proof is staged under `/home/zhuangxin2/ffdc_release_stages/20261015-bp-layout3/`.

## 2026-10-15 Backplane firmware evidence display

- Release `20261015-bp-layout2` hides the complete Backplane Firmware Update Evidence subsection from reports: title, explanatory text, firmware/debug policy table, upgrade events and firmware-collection limitations. Backplane configuration and controller-to-bay mapping remain visible.
- Backend collection, API, summary export and AI firmware evidence remain available. Stored reports and raw files are unchanged. Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-bp-layout2/` in `result.json` and `live-verification.json`.

## 2026-10-15 Same-slot NIC PLDM identity and numeric capabilities

- Release `20261015-pcie-pldm2` fixes V4 same-slot NIC function merging and PLDM metadata association using explicit unique serial identity. Conflicting identities remain unmatched. Existing PCIe identities, drives, virtual drives, firmware evidence and prior AI results are preserved during in-memory enrichment.
- Complete V4 numeric type lists now provide named Monitoring/Control, FRU, Firmware Update and RDE support according to DSP0245 Table 1; explicit flags take precedence, while missing/partial lists and conflicting endpoints remain unspecified. PCIe enrichment marker 2 refreshes both PCIe and cached network PLDM metadata from retained logs without archive recollection or report-file writes.
- Real report `20261015-151344-9ad8f1b6` has two E610 functions in slot 13, EIDs 0x08/0x09, with type list 0,2,5,6. Deployment and live evidence are staged under `/home/zhuangxin2/ffdc_release_stages/20261015-pcie-pldm2/`.

## 2026-10-15 Deep Investigation context budgets

- Release `20261015-deep-context1` bounds the serialized Deep Investigation and JIRA relevance evidence to 160,000 UTF-8 bytes. This is a conservative size budget, not an exact tokenizer count. Structured sampling retains JSON, source citations, critical/warning rows and head/tail evidence with explicit omission markers; stored reports and raw logs remain complete.
- Recognized structured prompts recover from provider context-length errors with up to two smaller evidence samples, preserving instructions, model and requested output. Other HTTP 400 errors and unstructured prompts are not silently cut or retried as context errors. Responses context errors bypass an identical chat-endpoint fallback.
- Validation includes the exact reported 259,945-input plus 2,200-output boundary error, large Unicode/nested evidence, critical citations, JIRA relevance, bounded retries, provider routing and Deep Investigation recovery. Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-deep-context1/`.

## 2026-10-15 Backplane validation label display

- Release `20261015-bp-layout1` hides the Snapshot validation status line from backplane register cards. Specific validation reasons, raw register details, backend validation and API/AI evidence remain available.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-bp-layout1/` in `result.json` and `live-verification.json`.

## 2026-10-15 NIC firmware evidence display

- Release `20261015-nic-layout3` hides the entire NIC Firmware Update Evidence section from the report page, including source rows, collected log excerpts and explanatory notes. Backend collection, API, summary export and AI evidence remain available. PCIe PLDM details, network inventory and backplane sections retain their existing display.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-nic-layout3/` in `result.json` and `live-verification.json`.

## 2026-10-15 Backplane configuration and correlation

- The user confirmed Lenovo Backplane FW Specification SP-000008 v1.06 as the latest project baseline. Release `20261015-sep2` pins that revision in parsed evidence, workspace instructions and documentation; the PDF takes precedence over earlier firmware specs and the draft DOCX.
- Validated, applicable SEP snapshots now expose UBM overrides and AnyBay/NVMe-only/EDSFF configuration. Configured width is separate from negotiated width. Conflicting Table 53 examples remain explicit limitations rather than invented cable-failure conclusions.
- Controller-to-bay mapping records confirmed identity, candidates, ambiguity and unresolved controllers. Unique serial or explicit backplane references plus reported ranges are required for confirmation. Boot/data namespaces and external-storage boundaries remain separate.
- Development-firmware update blocks, captured SEP debug-response metadata and bounded, line-cited update log observations are available in API, report UI, summary export, Backplane Agent and chat. Script/transport success and one version snapshot do not prove update success. Binary debug payloads are not inferred from response metadata.
- Old reports refresh from their own retained data in memory through `backplane_details_version=2`; raw evidence and stored report files are unchanged. Proof is staged under `/home/zhuangxin2/ffdc_release_stages/20261015-sep2/` in `result.json` and `live-verification.json`.

## 2026-10-15 Backplane diagnostic validity

- Release `20261015-sep1` corrects VMD port bitmap decoding and SEP 4NV5 status definitions. Modern SEP snapshots validate header, status and collected extended checksums, PGOOD, initialization, profile-specific valid bits and unambiguous control/status pairing before diagnostic flags become findings.
- CIO read or signature failures are evidence-quality warnings, not firmware-crash diagnoses. Supported NVMe-only configuration is not classified as a cable fault. Valid drive-fail indications remain Critical; drive-type/management indications are configuration warnings. BA with enabled, valid status retains drive indications while requesting configuration verification.
- Retained legacy register snapshots refresh in memory for API, AI and report rendering; stored report files and source logs are unchanged. Boot and older layouts keep their own status definitions. Specification conflicts remain explicit limitations.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-sep1/` in `result.json` and `live-verification.json`.

## 2026-10-15 NIC source coverage display

- Release `20261015-nic-layout2` removes the V3 / V4 source coverage disclosure from the report. Source collection, firmware evidence and PCIe PLDM details continue through their existing paths.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-nic-layout2/` in `result.json` and the live verification receipt.

## 2026-10-15 PLDM for all PCIe adapters

- Release `20261015-pcie-pldm1` adds raw-log PLDM types and named capabilities for RAID, HBA and other PCIe devices to PCIe Device Details, alongside NICs. Explicit mask zero and N flags remain distinct from absent evidence. V4 endpoint association requires EID and address; conflicting records remain ambiguous.
- Existing reports receive only PLDM fields and provenance through an independent PCIe version marker, including reports already at NIC version 1. Device identity, firmware, drives and virtual drives are retained; NIC nested-log collection is not repeated solely for this update. API and AI adapter details include the same metadata and collection-aware source paths.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-pcie-pldm1/` in `result.json` and the live verification receipt.

## 2026-10-15 NIC report layout

- Release `20261015-nic-layout1` moves PLDM types and capabilities into the existing PCIe Device Details table, matching the primary NIC management identity to the corresponding physical device row. The separate PLDM capabilities and NIC PCI functions disclosures are removed; parsed function and AI evidence data remain available.
- Deployment proof is recorded under `/home/zhuangxin2/ffdc_release_stages/20261015-nic-layout1/` in `result.json` and the live verification receipt.

## 2026-10-15 NIC inventory and firmware evidence

- Release `20261015-nic1` implements the supplied NIC spreadsheet's V3/V4 inventory, EID/TID/PCI identity, named firmware components, PLDM capabilities, per-port MAC/state/speed and firmware log discovery. V4 packed addresses remain raw; unitless V3 speeds remain unspecified.
- Bounded IBMU/Lenovo BMU archive processing exposes selected nested logs to report rendering and raw-evidence tools with original archive origins and line numbers. Missing/unreadable/truncated sources are explicit. BMU script completion and shared transport activity are not treated as NIC upgrade outcomes; Down/zero-speed inventory alone does not trigger a fault.
- The report, API, summary export, Network Agent and workspace chat use the new sections. Older reports with retained raw files are enriched in memory on access. Existing SnapDump and JIRA session boundaries remain covered by regression tests.
- Implementation and validation details are in `docs/NIC.md`. The immutable release manifest and deployment receipt are staged separately under `/home/zhuangxin2/ffdc_release_stages/20261015-nic1/`; check `result.json` and the live `/new-version` response for deployment proof.

## 2026-10-13 SnapDump integration

- Release `20261013-snapdump1` adds an independent `/snapdump` page directly after Defect Review in the workspace navigation. It includes MPI3 and MegaRAID parsing, health checks, event history, raw-file browsing, and Davy Q&A at the bottom of the results.
- The parser and evidence retrieval are copied from the current Knowledge Hub implementation. FFDC uses its own AI configuration and shared request capacity; ordinary SnapDump uploads and questions do not request JIRA credentials.
- SnapDump evidence is held in a bounded process-local cache, scoped to an HttpOnly browser session, with a two-hour expiry and one current analysis per browser. Restarting the service clears these temporary analyses. The feature has no dependency on port 8087 and does not use port 8089.
- Local Chrome verification parsed the supplied B540p ZIP, showing the firmware, degraded RAID 1, and raw-log browser. Navigation placement and bottom-of-page Davy controls were verified. Automated parser, UI, session-boundary, provider, and existing workspace/JIRA tests passed.
- Release `20261013-snapdump1` is deployed on port 8088. The guarded release verified a complete backup at `/root/data2/ffdc-analyzer-backups/20261013-snapdump1`, installed all 33 manifest files, and restarted `ffdc-analyzer.service` successfully. The prior release was `20261013-memory-agent1`.
- Live checks passed for service status, `/new-version`, `/snapdump` (including `?view=workspace`), navigation order, served assets, browser-session isolation, and the existing authoring login boundary. Both actual ZIP fixtures parsed correctly: 460-16e HBA with firmware `8.19.0.150-01000-00008` (30 text files) and B540p with a degraded RAID 1 (15 text files). A real Davy request correctly answered the B540p identity, firmware, and RAID state with log citations.
- This status document was finalized after the immutable code release. The staged original remains available for the guarded rollback baseline; `work/releases/20261013-snapdump1/post-deploy-documentation.json` records the documentation hash change. Read-only verification is recorded in `work/snapdump_live_readonly_verification.json`.

## 2026-10-12 Continuation

- Local FFDC workspace questions no longer request JIRA credentials merely because an older conversation mentioned a Bug or the current text says attachment/defect. Explicit JIRA keys, JIRA-specific questions, and JIRA-linked reports still require the user's JIRA session.
- Focused validation passed: 85 tests across `test_workspace_ui`, `test_ffdc_chat`, `test_workspace_jira_auth`, and `test_workspace_quality`; changed Python modules compile successfully.
- The live service was reachable at `/new-version` and reported release `20261008-drop1`; SSH and `systemctl` verification were initially blocked until the server credentials were supplied, then confirmed `active`, `running`, and `NRestarts=0`. Release `20261012-jira-auth1` is now deployed with a verified backup at `/root/data2/ffdc-analyzer-backups/20261012-jira-auth1`; served manifest hashes and the credential gate passed post-deployment checks.

## Working Capabilities

- Upload and parse ThinkSystem FFDC archives.
- Analyze a JIRA Bug ID and retrieve associated FFDC attachments when the required JIRA access is available.
- Display structured evidence for storage, RAID/HBA, PCIe, drives, backplanes, UEFI, network, FPGA, PLDM, MCTP, BMC/BMU in-band firmware, and system events when the source files are present.
- Keep internal backplane evidence separate from external E-suffix storage paths.
- Show report findings, source evidence, severity, and analysis traces.
- Continue the investigation through a natural-language chat workspace.
- Search raw logs and read surrounding lines through bounded read-only tools.
- Use JIRA title, description, reproduction steps, comments, status, and engineer context for Bug-scoped analysis.
- Interpret JIRA screenshots through the configured vision model, with OCR fallback; PDF reference pages in Agent mode are rendered and sent to the vision model without OCR fallback.
- Query project milestone data through the project tool when credentials and cached snapshots are available.
- Keep report history and usage statistics for 30 days.

## Current AI Behavior

The main chat path uses the configured Davy text model, with source defaults of `nemotron-3-ultra` for chat and deep investigation. Standard report generation falls back to `gpt-5.2` unless server configuration overrides it. JIRA image interpretation defaults to `gemma-4-31b-it`.

Model names in source are defaults and routing rules. The server's protected AI configuration can override the base URL and text model. Confirm the live configuration before documenting production model usage.

## Known Limitations

- The service uses a hand-written HTTP router and dynamic JSON dictionaries; there is no published OpenAPI contract.
- Runtime jobs and sessions are held in process memory. There is no shared database or cross-process job queue.
- Raw-log triage is bounded. A limited scan cannot prove that an error is absent.
- Deterministic checks can identify abnormal evidence but do not prove a root cause on their own.
- AI answers depend on the evidence made available by the parser and tools. Missing or unreadable files must be reported as unavailable evidence.
- JIRA and Project Tool availability depends on network access, credentials, rate limits, and the current server configuration.
- The service is an internal tool and needs a security review before wider network exposure.
- The current source package intentionally excludes runtime FFDC, reports, caches, logs, credentials, and historical backups.

## Verification Checklist

Run focused tests from the project root:

```bash
python3 -m unittest test_workspace_ui test_ffdc_chat test_workspace_jira_auth test_workspace_quality
python3 -m py_compile app.py ffdc_chat.py workspace_analysis.py workspace_ui.py evidence_index.py
```

For a live deployment, verify:

```bash
systemctl is-active ffdc-analyzer.service
curl -fsS http://127.0.0.1:8088/new-version
```

The current source exposes `/new-version` as the lightweight HTTP smoke
check; it does not expose a separate `/health` route. Use the service manager
check together with this route after a restart.

Never print the contents of protected AI or JIRA credential files during verification.

## Recommended Next Work

1. Add an explicit evidence confidence field to every automated check.
2. Record parser coverage and scan limits in the report UI.
3. Add regression fixtures for mixed internal `9350-8i` and external `940-8e` systems.
4. Add end-to-end tests for screenshot evidence, Chinese-language answers, and unsupported citation handling.
5. Move runtime jobs and sessions to a durable store if multiple service workers are introduced.
6. Keep the sanitized environment template and systemd deployment example in `config/` and `deploy/` as references. Preserve the existing production unit and protected configuration when upgrading an existing installation.
