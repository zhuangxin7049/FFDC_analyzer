# SnapDump parser and corpus validation

The FFDC workspace exposes `/snapdump` below Defect Review. `snapdump.py` parses the supplied text files, `snapdump_chat.py` prepares bounded raw evidence, and `ffdc_snapdump.py` owns browser-scoped HTTP sessions/cache. Davy uses the existing FFDC AI configuration. Raw SnapDump uploads and questions do not require JIRA login.

The 2026-10-15 corpus contains 115 ZIPs and 12 unpacked captures under server `/mnt`. Exact text-file comparison identifies 114 distinct log sets and 14 controller model strings. Four nested ZIPs in the 7z collection duplicate already analyzed archives. Every input location has an individual result, including duplicate/previous-error provenance. Generated input copies and analysis artifacts are outside the runtime module set; original `/mnt` files are not modified.

## Format boundaries

- Legacy module exports use `crashDump.txt` Generic/LD/PD sections, `PL_MODULE.txt`, `NVRAM_MODULE.txt`, labelled host `HWREG.txt` PCIe registers, and `event_dump.txt`. Controller/drive numeric fields are hexadecimal. VirtualSES/enclosure records are not counted as storage disks.
- NVRAM reset values accept the named plain scalar and an immediately following, fully visible single-dword hex dump. A multiword/partially unavailable memory structure is not interpreted as that scalar.
- MPI3 uses `Summary.txt`, `CrashDump.txt`, `Cpu.txt`, `Nvram.txt`, `PlBase.txt`, `DmBase.txt`, `IopBase.txt`, `Encl.txt` and `ControllerPEL.txt`. Explicit `IOPI_FW_OPMODE_RAID` additionally enables hexadecimal `Cnt` controller inventory and `Pd.txt` physical-drive state/counters. HBA/PerfIT does not reuse RAID-managed disk counts. Packed per-LD state and unnamed POR/HIP raw memory are not decoded.
- Slot tokens retain their literal representation; A-F/0x values are hexadecimal. The displayed slot count is the maximum reported enclosure count, not a total physical disk inventory.
- Snapshot identity/state is distinct from historical TTY/events. Fault codes, queued I/O, historical counters and file names alone do not establish a root cause or an active fault. Missing fields remain missing.

## Bounds

- ZIP upload: 50 MiB; one decoded text entry: 40 MiB; total decoded text: 64 MiB; maximum archive files: 250. Standalone text is limited to 16 MiB. No original entry is silently truncated.
- Evidence cache: 128 MiB of estimated retained Python objects, one current analysis per browser, two-hour expiry. Accounting includes actual Unicode representation, containers and shared objects. Existing session isolation, rates, concurrency and stale-result guards apply.
- Davy: 20 sources/40,000 excerpt characters, exact original line ranges, bounded history/metadata. Current snapshot and relevant nonzero errors precede historical evidence. Clicking a source opens nearby original lines even past the default file preview; other file browsing remains bounded to 500,000 preview characters.

## Verification

```bash
python3 -m unittest test_snapdump_corpus test_snapdump test_snapdump_pcie test_snapdump_chat test_ffdc_snapdump test_snapdump_ui test_snapdump_provider
python3 work/analyze_snapdump_corpus.py work/snapdump-corpus-20261015/input work/snapdump-corpus-20261015/after
python3 work/build_snapdump_corpus_report.py work/snapdump-corpus-20261015 deliverables/snapdump-corpus-20261015
```

The analysis report records 18 distinct OFFLINE captures, two DEGRADED captures and 19 with nonzero failed-disk counts; categories overlap and repeated captures are not independent incidents. Four samples still have genuine missing evidence: three have no PL module, and one MPI3 export has raw NVRAM without named POR/HIP fields. Successful parsing is not a complete hardware health certification.

## Avenger reference-based evidence (2026-10-16)

`snapdump_avenger.py` enriches MPI3 exports using the supplied Avenger Drive ordering and Persistent ID, Avenger Overview (July 2025), NVDATA (August 2025) and Avenger Debug documents. These overview documents do not supply a complete ROP/MPI3/MFG bit dictionary. The reference PDFs/PPTX and their embedded debug commands/utilities are not deployed or executed.

- Current snapshot Personality/Profile and explicit runtime determine RAID/PerfIT/EVP/FeatureHBA applicability. Inconsistencies and unknown runtime enums remain unverified. EVP uses managed LD/PD Cnt fields without DDR checks. Historical candidate/alternate profiles are excluded.
- DevPrst text rows use a two-word PHY field. Ranges are enclosure/slot candidates, never global disk identity or proof of disk presence. Explicit Pd slot values are retained on conflict; overlapping ranges are ambiguous. SES records are distinct. PdPrst INDEX and 32-bit UniqueId are not joined to PD IDs or WWNs without a proven relationship. Missing records are retained without becoming current failed disks. Duplicate source basenames are excluded from cross-file enrichment.
- ConfigPages separates three regions and inventories page/type/IOC/address/word coverage. SHA-256 compares canonical raw words, ignoring output memory addresses and normalizing bounded zero runs. Only complete, unambiguous DEFAULT/CURRENT pairs are compared. Differences include header changes and do not identify a changed feature or a fault. No cross-generation page schema or example-board pinout is applied.
- Diagnostic source lines are sampled across ASSERT, nonzero IOCStatus/IOCLogInfo, Sense, Safe Mode, memory/NAND and cache events; up to 120 lines are retained with category balance in original file order. Relative/absolute clocks are not merged into a fabricated timeline. Historical events do not change current check severity. Scanned files/lines and long-line omissions are recorded.
- Limits: 2048 decoded PD records, 1024 exposed persistent ranges, 2048 PdPrst records and 2048 configuration records. The UI states its smaller visible row counts. Upload/decompression/cache limits are unchanged. Binary logs/StringTable/utility ZIPs are listed as collected/not decoded; matching vendor decoding remains a separate prerequisite.
- Source buttons reopen the original authorized file/line window. Davy receives bounded summaries, document-derived interpretation constraints and question-specific original evidence. These rules do not provide complete firmware fault-code or SCSI Sense dictionaries.

Focused additions: `python3 -m unittest test_snapdump_avenger test_snapdump_ui test_ffdc_snapdump test_snapdump_chat`. The full release also runs the existing SnapDump suite, deployment-helper checks and workspace/JIRA regressions.

Sparse PD header/slot/inquiry fields are reopened together (up to 80 original lines within the unchanged excerpt budget), and DevPrst range excerpts retain their column header. This prevents overlap deduplication from hiding a requested slot/model and avoids confusing enclosure ELID with disk Persistent ID or WWN.

## AV1 / AV2 reference library study (2026-10-16)

The supplied AV1_Spec.zip and AV2_SPEC.zip contain 40 PDF files including nested archives, 39 unique PDF contents and 1217 pages (1107 pages after content deduplication). All pages have a local text index; 20 scanned certificate pages have separately marked OCR text. Four STP models are inventoried as mechanical assets and are not diagnostic specifications. Core SnapDump, generation, MPF, enclosure, StoreLib/OOB and error-handling chapters were reviewed; indexing is not a claim that every bit field has been validated.

- `docs/avenger_reference_catalog.json` records 38 candidate rules, source hashes/pages, document scope and six version/interpretation conflicts. It is a study artifact, not an enabled parser-rule pack.
- `work/avenger-spec-study-20261016/pages.sqlite` and `search.py` provide read-only source-page retrieval. For example: `python3 work/avenger-spec-study-20261016/search.py '"SlotIndex"' --doc AV1-023`.
- The retained 460 capture has SAS5032W and ThinkSystem 460-16e PCIe Gen5 identity strings in DEFAULT/CURRENT/PERSISTENT MFG0 pages. `460-generation-evidence.json` records source header lines and the extraction method. This is captured evidence, not a new hardware query. AV2 IOC scope must precede applying an AV1 profile/caching table.
- Highest-priority follow-up: physical card versus PF/controller grouping; Supervisor/Non-supervisor visibility; SlotIndex/CEI/DSN separation before range-slot conflict inference; populated/length/status validation; and explicit event/error namespaces. AV1-023 page 6 supplies a counterexample where DSN=16 maps to PID=X+4.
- The AV2 package includes an older 9600 software guide. StorCLI2 filename UG101 has a UG102 v1.2 cover. PF state commands differ across documents and FW-Diff v1.1 removes the command. Keep these caveats attached to any future rule or follow-up recommendation.
- A complete binary/configuration/fault decoder still requires matching MPI/Configuration Programming Guide/ROP/header definitions, trusted matching binary decoders and, for exact lane wiring, board schematics.

## AV1 / AV2 implementation (20261016-avenger3)

Current snapshot ChipName selects AV1/AV2 and the documented RoC/IOC family. No firmware-version or archive-name heuristic selects generation. AV1 personality/profile fallback and external-DDR counters are restricted to matching identity (DDR additionally needs AV1 RoC RAID). Explicit known FwMode can identify AV2 runtime without decoding AV1 profile enums. Unknown/conflicting identity or runtime remains unverified. MFG page-purpose labels are AV1-only; raw coverage/differences remain available on other generations.

`device_mapping.devices[].range_id_offset` is PID minus range start, not DSN. `slot` always comes from literal Pd slotNumber. `range_slot` is retained as null for API compatibility. Noncontiguous physical slots do not create range conflicts. DevPrst StSlot remains a raw range field, while ELID remains candidate enclosure identity. EncReq AN100 p.6 explicitly demonstrates DSN 16 at PID X+4.

`controller_identity` and `host_functions` preserve source lines. Host Interface IOC blocks (up to 64), MPI/NVMe function counts, enabled bitmap and supported count are separate from Generic Config NumberOfIocs. BusNum/DeviceFunc without PCI domain is not a full BDF. No physical-card count, Supervisor role or device visibility is guessed from IOC index or undecoded EtpDevType. PF assignment/Mgmt only/Exposed to Host are evidence requests, not inferred properties of an absent disk.

Management observations include nonzero literal SLStatus/comStatus/DCMDStatus/SCSIStatus/NVMeStatus and invalid-sequence/incomplete-buffer context in the existing selected files plus storelib8debug.txt. Their namespaces remain distinct from MPI IOCStatus and firmware FaultCode; matching vendor headers/base/version are still required for full decoding. These observations do not change active-health severity. Return-buffer length/populated validity is requested before interpreting returned zero values; opaque returned structures remain undecoded.

Davy receives the same generation, slot and namespace constraints. Required source spans may overlap nearby context when necessary to retain a complete second device/IOC record, within the unchanged 20-source/40,000-character budget. The UI displays observed slots, range membership/ID offset, current chip identity and raw IOC evidence; chat remains at the bottom.

This release deliberately does not implement a complete firmware status dictionary, binary decoder, arbitrary MPF command generation, or complete StorCLI JSON ingestion. See `avenger_reference_catalog.json` implementation status and the source/version caveats in `AvengerStudyNotes.txt`.

### Davy hexadecimal identity context (20261016-avenger4)

Actual provider validation found a digit-only enclosure token interpreted as decimal despite the parser's correct hexadecimal value. Targeted PD questions now receive bounded structured facts ahead of broad report metadata: PD ID, hexadecimal/decimal enclosure, hexadecimal/decimal observed slot, model and candidate range offset. The prompt states that PD=16e is the current PD identifier, that raw enclosure token 176 means 0x176/374 decimal, and that EnclD/addr[0]/PdPrst UniqueId must not become an invented WWN join. Matching original PD excerpts remain mandatory; sources use IDs instead of fabricated individual line numbers. These hints constrain model interpretation but do not replace the original logs or deterministic parser.

### Verified factual answers (20261016-avenger5)

Narrow MPI3 PD identity/slot/model/range questions and multiple-IOC count questions can be answered directly from parsed facts when each required source field is present in the current authorized evidence bundle. This prevents provider arithmetic from turning hexadecimal NumPrstIDs=12 into 12 decimal or IocState=00 into an undocumented healthy enum. Range end is first_id + reserved_ids - 1; range offset does not become physical slot. Generic Config NumberOfIocs is displayed without inventing its internal semantics.

The handler still validates question/history, owns the session, enforces rate/concurrency and rejects replaced/expired results after answer generation. Diagnostic, health, firmware and action questions retain Davy provider reasoning, as do unsupported or insufficiently cited facts. The source list and normal UI follow-up path are unchanged. These factual answers make no provider-call claim; they are labelled verified facts in the user's language.
