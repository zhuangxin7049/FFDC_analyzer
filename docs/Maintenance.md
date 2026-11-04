# FFDC Analyzer: Maintenance and Modification Guide

## Audit Method and Evidence

Baseline: 2026-09-30 local workspace. The audit performs full byte reads and hashes of source/data/artifact files, complete AST traversal of current runtime and historical Python files, import/configuration/call/return/effect extraction, exact-content duplicate detection, control-depth checks, numeric-literal indexing, and selected semantic inspection of critical product paths. Generated documentation and Git internals are excluded from the baseline inventory.

This is not a claim that every binary artifact was visually interpreted or that static analysis proves arbitrary Python call reachability. No production credentials are published and no live JIRA filter was modified. This update only extracts configuration and job persistence helpers; HTTP routes and report formats remain compatible. Where a check is heuristic, its limits are stated explicitly.

## Phase 1 Checklist

| Check | Conclusion | Evidence / boundary |
| --- | --- | --- |
| Exact duplicate files | **Found** | `app.py.correlationwork` and `app.py.ueficlean` are byte-identical. Additional artifacts are listed by hash in AuditInventory. |
| Highly similar files | **Found** | Eight historical `app.py.*` copies contain overlapping application logic; retain provenance before archiving. Their names are not runnable production entrypoints by default. |
| Referenced missing files | **Found, local baseline only** | Default sample/keyfiles/AI-key locations and deployment config are external to this snapshot. Runtime local module imports resolve. This does not prove the files are missing on production. |
| Redundant backups | **Found** | Eight root `app.py.*` copies, including an exact duplicate pair. Do not delete automatically: one test suite explicitly imports a backup. |
| Standard project metadata | **Added locally** | Root `requirements.txt`, `requirements-optional.txt`, `.gitignore`, `config/ffdc-analyzer.env.example`, and `deploy/ffdc-analyzer.service.example` now document runtime policy without embedding secrets. |
| print statements | **Found** | Current application has one startup-log print in `main`; no debug print in the other three runtime modules. Utility/test/backup prints are separately listed. |
| Unused imports | **Not found by whole-file name-use check in runtime modules** | This heuristic is not a scope-aware linter; imports used only by type/runtime dispatch need human judgment. Auxiliary findings are in the audit. |
| Uncalled functions | **Candidates found; dead-code status unproven** | Static name/attribute references do not reliably model HTTP dispatch, callbacks, dynamically named evidence tools or external imports. Candidate list supplied; never delete solely from it. |
| Numeric literals | **Found** | Timeouts, protocol/register values, limits, UI dimensions, thresholds and pagination constants are indexed. Their presence is not proof of a bug or placeholder. |
| Control nesting >3 | **Found** | The historical inventory counted 218 control nodes across the original four runtime modules. The new helper modules are intentionally small; regenerate the inventory after larger extraction steps. |
| Duplicate code blocks | **Found** | Both base and workspace `triage_ffdc` implementations maintain related scanning logic. Archive extraction also duplicates path checks. Exact normalized function bodies are separately indexed. |
| Module-level side effects | **Found** | Environment loading, TLS contexts, locks/semaphores, dictionaries, regular expressions. Server startup is guarded by `__main__`. |
| Entrypoint targets | **Current runtime targets exist; auxiliary portability gaps found** | The four module imports and shipped static assets exist. Diagnostic/patch scripts can require external case paths. Legacy monitor test intentionally imports `app.py.jira_monitor`. |
| Config resource paths | **Local gaps found / deployment validation required** | Secret/config/sample resources remain external by design. Sanitized environment and systemd examples are checked in; real credentials and the installed unit remain host-managed. |
| Repeated configuration loads | **Found** | `load_ai_config` reads its file per call; scheduler config is repeatedly loaded by scheduler and project credential resolution. |
| Repeated global assignment | **Found** | Job dictionaries and counters are mutated at multiple locations, often with explicit locks. Shared callback/handler data still needs race review. |
| Tab/space mixing | **No leading tabs found in runtime Python files** | UTF-8 code uses spaces; this does not assert full style compliance for all support/vendor files. |
| PEP 8 blank lines | **Potential violations found** | 13 top-level definition spacing candidates in `app.py`; detailed line list supplied. Entire-project PEP 8 certification was not performed. |
| Encoding | **Runtime Python uniformly UTF-8** | Binary/non-UTF-8 artifacts are expected and inventoried separately; not reported as source encoding failures. |

## Prioritized Findings

| Priority | Object | Issue | Recommended action |
| --- | --- | --- | --- |
| P1 | `app.py:62`, `64`, `108` | AI, JIRA and Project Tool use `ssl._create_unverified_context()`. Certificates and hostnames are not verified by these contexts. | Provision the enterprise CA chain and replace these contexts with verified service-specific contexts; test each integration before deployment. |
| P1 | `Handler.do_POST`, `app.py:13406`; `clear_reports`, `app.py:186` | Global report deletion has no application-level authentication/authorization check in the inspected handler. Other read/expensive-operation routes are also not protected by user ownership. | Gate administration and isolate report access. Audit the actual reverse proxy before describing internal exposure as safe. |
| P1 | `/api/report` branch in `Handler.do_GET`; `load_workspace_report`, `app.py:11435` | Legacy report-related GET branches join the query ID directly into paths, unlike the workspace's strict report-ID validator. Absolute/traversal-style paths are not uniformly rejected. | Apply one containment/ID validation policy to every report read/download/write route and test invalid IDs. |
| P1 | `run_jira_monitor_job`, `app.py:8335-8343`; `run_current_status_summary_job`, `app.py:6625-6656` | Completed afternoon review starts a summary job which reads the Project Tool tracker and may alter the saved JIRA filter. Main review flags alone do not enforce “no afternoon milestone refresh.” | Propagate the morning-reuse policy into the summary job; validate behavior across both jobs before claiming full afternoon reuse. |
| P1 | `safe_extract_tar`, `app.py:1578`; `unpack_ffdc`, `app.py:1608` | Standard FFDC TAR handling checks member paths but does not explicitly reject links/special files or enforce expanded-size/member limits. Behavior partly depends on Python extraction defaults; decompression has no explicit timeout. | Add explicit extraction policy and quotas for this path, with malicious-link/expansion tests. Separate archive validation already exists for JIRA log archives. |
| P2 | `classify_backplane_scope`, `app.py:1679`; `analyze`, `app.py:10207` | Any external controller causes report-wide internal-backplane suppression, including mixed internal/external configurations. | Evolve the evidence association per controller/path, with mixed-topology fixtures; do not let internal files diagnose external storage. |
| P2 | `test_jira_monitor_workflow.py:10`, `121`, `145` | Tests import a historical copy and no longer match the current staged review. One assertion fails and another test errors. | Update fixtures and mocks against current code; isolate all job/cache directories. Do not claim a green full regression suite. |
| P2 | `workspace_analysis.py:169` | Citation validation covers a specific backtick pattern and verifies read ranges, not factual entailment. | Test alternative citation forms; evaluate whether each conclusion follows from its evidence, not only whether a path was read. |
| P2 | `static/workspace.js:15`; `app.py:11220` | Client Bug extraction uses word boundaries, while backend explicitly fixes Chinese-adjacent Bug keys with ASCII boundaries. | Align both recognizers and add a browser regression for switching Bugs in Chinese while another report is selected. |
| P2 | `workspace_chat_response`, `app.py:11444`; `Handler.do_POST`, `app.py:13434` | 12,000 vs 16,000 character limits and generic error conversion can produce a 500 for a client validation problem. | Use the same limit and return a consistent 400 response. |
| P2 | `start_*_job`, scheduler/global dictionaries | Single-process state and daemon threads are not durable queues. Multiple server processes do not share semaphores or job dictionaries. | Keep one orchestrator unless job ownership/locking is redesigned; verify restart recovery and duplicate schedule protection. |
| P2 | `cleanup_reports`, `app.py:168`; `cleanup_uploads`, `app.py:158` | Thirty-day report cleanup is opportunistic; upload cleanup is count-based and can overlap active work. Cache retention is not identical to report retention. | Test cleanup during concurrent analyses; explicitly define/report independent retention policies and protect active inputs. |
| P2 | `load_ai_config`, `app.py:10470` | Key file parsing can silently override environment model/base URL, making deployments appear to ignore model settings. | Verify effective provider/model without logging tokens; simplify or document precedence during changes. |
| P2 | `jira_image_comment`, `app.py:6918` | Vision failure silently falls back to OCR or no attachment evidence; cached results may outlive a model change. | Preserve method/status visibility and intentionally invalidate cached interpretation when necessary. |
| P3 | `app.py` (14,500+ lines) | Parsing, AI, integrations, rendering and scheduling still share a large module. Configuration helpers and JIRA monitor job persistence now have tested module boundaries. | Continue extracting one ownership boundary at a time; retain behavior and source references. |
| P3 | Root metadata and backup files | No pinned runtime/tool support matrix, standard dependency metadata, or repository ignore rules. | Record tested Python/tool versions, protect secret/runtime paths, and archive obsolete copies only after migrating backup-dependent tests. |

P1 means a high-priority security or workflow correctness concern, not evidence of exploitation. Findings describe the local source; an external proxy can affect actual exposure and requires separate verification.

## Modification Map

| Desired change | Exact starting point |
| --- | --- |
| Archive format support | To adjust FFDC unpacking, modify `unpack_ffdc` in `app.py` (line 1608), together with `safe_extract_tar` (line 1578). |
| V4 parser coverage | To adjust minilog interpretation, modify `analyze_minilog_v4` in `app.py` (line 1397). |
| Network evidence | To adjust NIC/interface/event extraction, modify `parse_network_info` in `app.py` (line 1773), and review network keywords in `ffdc_chat.TRIAGE_COMPONENTS`. |
| BMU/BMC inband updates | To adjust firmware timelines, modify `parse_bmc_inband_firmware_updates` in `app.py` (line 2121) and `bmc_inband_event_stage` (line 2111). |
| PLDM updates | To adjust attempt/terminal-state interpretation, modify `parse_pldm_firmware_updates` in `app.py` (line 2020) and `finalize_pldm_update_attempt` (line 1985). |
| External storage exclusions | To adjust scope, modify `is_external_storage_adapter` and `classify_backplane_scope` in `app.py` (lines 1670 and 1679); verify checks and report suppression together. |
| Automated findings | To adjust deterministic warnings, modify `run_automated_checks` in `app.py` (line 3207). Add source-specific fixtures before changing register meanings. |
| Bug-to-FFDC routing | To adjust automatic attachment investigation, modify `workspace_chat_response` in `app.py` (line 11444), `call_workspace_chat` (line 11374), and `run_jira_analysis_job` (line 4875). |
| Answer focus and evidence quality | To adjust prepared evidence, modify `WorkspaceEvidenceTools.prepare` in `workspace_analysis.py` (line 148), with `INSTRUCTIONS` (line 19). |
| Tool budget and final synthesis | To adjust tool iteration, modify `run_chat` in `ffdc_chat.py` (line 414); treat per-call, per-file, total-time and browser limits separately. |
| Similar Bug precision | To adjust title query terms, modify `jira_similarity_title_query_tokens` in `app.py` (line 5978); ranking/assessment starts at `search_similar_jira_cases` (line 6196). |
| Schedule behavior | To adjust full/reuse selection, modify `jira_monitor_scheduler_loop` in `app.py` (line 8484), `run_jira_monitor_job` (line 8025), and the follow-on summary path (line 6625). |
| Milestone chat | To adjust query matching/output, modify `search_workspace_project_milestones` in `app.py` (line 8797). It reads a completed snapshot. |
| Milestone color rules | To adjust countdown styling, modify `current_status_countdown_class` in `app.py` (line 8873) and matching CSS selectors in `static/workspace-subpage.css`. |
| BMC update section folding | To adjust the report section, modify `render_bmc_inband_firmware_analysis` in `app.py` (line 11672), preserving the existing details/summary behavior. |
| Chat Markdown | To adjust browser rendering, modify `renderTokens` in `static/workspace.js` (line 56); server fallback starts at `render_workspace_chat_markdown` in `app.py` (line 12206). |
| Report button / no automatic navigation | To adjust completion behavior, modify `waitForJob` in `static/workspace.js` (line 231) and `renderContext` (line 163). |
| Shared page styling | To adjust the new shell, modify `render_workspace_subpage` in `workspace_ui.py` (line 49) and `static/workspace-subpage.css`. Preserve classic URLs. |
| Retention | To adjust report/usage cleanup, modify `cleanup_reports` in `app.py` (line 168) and `prune_usage_stats` (line 10284); browser recent retention is separate. |

Line numbers belong to this snapshot; use the function names and generated source hashes when code shifts.

## Tests and Debugging

The disposable validation run recorded in `_audit/validation.json` reports:

| Suite | Result | Meaning |
| --- | --- | --- |
| `test_ffdc_chat`, `test_workspace_quality`, `test_workspace_ui`, `test_ffdc_jobs`, `test_ffdc_config` | 79 tests passed | Read-only tools, redaction, path bounds, focus/recovery, Markdown, routing, context selection, UI-source behavior, bounded configuration parsing, and atomic job snapshots under local fixtures/mocks. |
| `test_jira_monitor_workflow` | 4 tests: 2 pass, 1 failure, 1 error | Loads `app.py.jira_monitor`, not current app. Expected old four-section prompt differs from staged review; mixed-source fixture fails before an issue row is available. |
| Live integrations | Not run for documentation | No fresh assertion about PAT validity, current model catalog, target server configuration, or real hardware diagnosis. |

The validation helper should be used instead of running auxiliary scripts in the product directory. Some historical tests and patch scripts have filesystem side effects. An initial direct legacy test execution during this task wrote the local `jira_monitor_jobs/job.json` fixture; subsequent verification was moved to disposable copies. Production service state was not involved.

There is no `FFDC_DEBUG` switch or structured logger in the inspected runtime. `main()` logs startup to stdout; the standard HTTP handler writes access logs to stderr. Most job exceptions become job JSON `error`/`message` values, while several helpers suppress exceptions. On a host with the existing service installed:

```bash
systemctl status ffdc-analyzer.service --no-pager
journalctl -u ffdc-analyzer.service -n 200 --no-pager
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/new-version
```

Run log inspection only where authorized; logs may contain internal filenames, URLs and issue descriptions. Never output key files, PATs or passwords to diagnose model selection.

## Troubleshooting

| Symptom | Likely cause | Inspect |
| --- | --- | --- |
| Website unavailable | Process stopped, bind/proxy port mismatch, network access | `main`, host/port settings, actual unit logs, Nginx upstream. |
| New UI still shows old labels | Old served static file or browser state | `workspace_ui.VERSION`, static response contents and version query; distinguish local edit from deployed file. |
| Bug answer says no FFDC | Wrong key routing, no supported attachment/link, failed download, expired report | `workspace_issue_key`, job JSON, `get_jira_ffdc_sources`, actual attachment filenames and errors. |
| Upload opens another page | Classic `/upload` route in use rather than workspace job path | Browser request route and `waitForJob`; classic redirect is intentional. |
| Unrelated errors dominate answer | Broad automatic checks or loss of focus/time scope | `WorkspaceEvidenceTools.prepare`, selected report ID, available raw excerpts, JIRA relevance brief. |
| English reply to Chinese question | Explicit language override, lost original question, provider noncompliance | `detect_user_language`, original question passed by `answerReport`, prompt language rule. |
| Markdown hashes/table clutter | Wrong renderer, stale asset, incompatible response | Marked script loaded; controlled token rendering; server normalization functions. |
| Report link expired | Directory removed by retention / local recent item remains | `reports/<id>/report.json`, cache restoration availability; recent-list clear does not restore files. |
| Image evidence missing | Unsupported MIME/size, model failed, OCR absent, unreadable image | `analysis_method`, vision return, tesseract executable/language data, cache key. |
| Afternoon new Bug lacks similar cases | No matching morning Bug key | `similar_bugs_source_job_id`, copied count, morning snapshot; this is not evidence of no related defects. |
| 13:00 still contacts Project Tool | Follow-on current status summary path | Parent review's `current_status_summary_job_id`, `run_current_status_summary_job`. |
| Review remains interrupted | Service restarted, stale in-memory job or failed retry | Latest persisted job, retry metadata, scheduler configuration and recovery branch. |
| Similar answer truncated | Provider token limit or response completeness check failed | `davy.status/error`, completeness retry, final Markdown sections. |
| External array gets internal BP diagnosis | Mixed topology or scope/classification mismatch | External-controller regex, `backplane_scope`, and source association. |

<!-- GENERATED AUDIT FINDINGS -->

## Detailed Static Findings

The following lists are exhaustive for the stated metric over the six current runtime modules, not proof that every entry is a defect.

### Deep Nesting

| Source | Depth | AST control |
| --- | --- | --- |
| [app.py:597](../app.py#L597) | 4 | If |
| [app.py:601](../app.py#L601) | 4 | If |
| [app.py:616](../app.py#L616) | 4 | If |
| [app.py:665](../app.py#L665) | 4 | If |
| [app.py:676](../app.py#L676) | 4 | If |
| [app.py:677](../app.py#L677) | 5 | If |
| [app.py:681](../app.py#L681) | 6 | If |
| [app.py:684](../app.py#L684) | 6 | If |
| [app.py:693](../app.py#L693) | 5 | If |
| [app.py:784](../app.py#L784) | 4 | If |
| [app.py:793](../app.py#L793) | 4 | If |
| [app.py:813](../app.py#L813) | 4 | If |
| [app.py:815](../app.py#L815) | 5 | If |
| [app.py:817](../app.py#L817) | 6 | If |
| [app.py:832](../app.py#L832) | 4 | If |
| [app.py:1055](../app.py#L1055) | 4 | If |
| [app.py:1142](../app.py#L1142) | 4 | If |
| [app.py:1144](../app.py#L1144) | 5 | If |
| [app.py:1146](../app.py#L1146) | 6 | If |
| [app.py:1147](../app.py#L1147) | 7 | If |
| [app.py:1151](../app.py#L1151) | 7 | If |
| [app.py:1153](../app.py#L1153) | 8 | If |
| [app.py:1156](../app.py#L1156) | 9 | If |
| [app.py:1159](../app.py#L1159) | 10 | If |
| [app.py:1161](../app.py#L1161) | 11 | If |
| [app.py:1683](../app.py#L1683) | 4 | For |
| [app.py:1684](../app.py#L1684) | 5 | If |
| [app.py:1686](../app.py#L1686) | 5 | If |
| [app.py:1791](../app.py#L1791) | 4 | With |
| [app.py:1793](../app.py#L1793) | 5 | For |
| [app.py:1795](../app.py#L1795) | 6 | If |
| [app.py:1799](../app.py#L1799) | 4 | If |
| [app.py:1800](../app.py#L1800) | 5 | If |
| [app.py:1803](../app.py#L1803) | 5 | If |
| [app.py:2022](../app.py#L2022) | 4 | If |
| [app.py:2024](../app.py#L2024) | 4 | If |
| [app.py:2026](../app.py#L2026) | 4 | If |
| [app.py:2028](../app.py#L2028) | 5 | If |
| [app.py:2033](../app.py#L2033) | 4 | If |
| [app.py:2035](../app.py#L2035) | 5 | If |
| [app.py:2068](../app.py#L2068) | 4 | For |
| [app.py:2069](../app.py#L2069) | 5 | If |
| [app.py:2071](../app.py#L2071) | 5 | If |
| [app.py:2074](../app.py#L2074) | 5 | If |
| [app.py:2339](../app.py#L2339) | 4 | If |
| [app.py:2352](../app.py#L2352) | 4 | If |
| [app.py:2354](../app.py#L2354) | 5 | If |
| [app.py:2356](../app.py#L2356) | 5 | If |
| [app.py:2573](../app.py#L2573) | 4 | If |
| [app.py:2576](../app.py#L2576) | 4 | If |
| [app.py:2579](../app.py#L2579) | 4 | If |
| [app.py:2584](../app.py#L2584) | 4 | If |
| [app.py:3290](../app.py#L3290) | 4 | If |
| [app.py:3293](../app.py#L3293) | 5 | If |
| [app.py:3345](../app.py#L3345) | 4 | If |
| [app.py:3359](../app.py#L3359) | 4 | If |
| [app.py:3608](../app.py#L3608) | 4 | If |
| [app.py:3610](../app.py#L3610) | 5 | If |
| [app.py:3633](../app.py#L3633) | 4 | If |
| [app.py:3997](../app.py#L3997) | 4 | If |
| [app.py:4007](../app.py#L4007) | 4 | Try |
| [app.py:4011](../app.py#L4011) | 4 | With |
| [app.py:4013](../app.py#L4013) | 4 | If |
| [app.py:4024](../app.py#L4024) | 4 | If |
| [app.py:4065](../app.py#L4065) | 4 | If |
| [app.py:4076](../app.py#L4076) | 4 | Try |
| [app.py:4080](../app.py#L4080) | 4 | With |
| [app.py:4082](../app.py#L4082) | 4 | If |
| [app.py:4512](../app.py#L4512) | 4 | For |
| [app.py:4806](../app.py#L4806) | 4 | If |
| [app.py:4895](../app.py#L4895) | 4 | If |
| [app.py:4898](../app.py#L4898) | 4 | If |
| [app.py:4901](../app.py#L4901) | 4 | If |
| [app.py:5274](../app.py#L5274) | 4 | If |
| [app.py:5279](../app.py#L5279) | 4 | Try |
| [app.py:5318](../app.py#L5318) | 4 | If |
| [app.py:5769](../app.py#L5769) | 4 | If |
| [app.py:5771](../app.py#L5771) | 4 | If |
| [app.py:5774](../app.py#L5774) | 4 | If |
| [app.py:5784](../app.py#L5784) | 4 | If |
| [app.py:6566](../app.py#L6566) | 4 | If |
| [app.py:6606](../app.py#L6606) | 4 | If |
| [app.py:6692](../app.py#L6692) | 4 | If |
| [app.py:6975](../app.py#L6975) | 4 | If |
| [app.py:6983](../app.py#L6983) | 4 | If |
| [app.py:7172](../app.py#L7172) | 4 | If |
| [app.py:7175](../app.py#L7175) | 4 | If |
| [app.py:7559](../app.py#L7559) | 4 | If |
| [app.py:7563](../app.py#L7563) | 4 | If |
| [app.py:7566](../app.py#L7566) | 5 | If |
| [app.py:7568](../app.py#L7568) | 4 | If |
| [app.py:7571](../app.py#L7571) | 5 | If |
| [app.py:7573](../app.py#L7573) | 4 | If |
| [app.py:7578](../app.py#L7578) | 5 | If |
| [app.py:8294](../app.py#L8294) | 4 | If |
| [app.py:8482](../app.py#L8482) | 4 | For |
| [app.py:8484](../app.py#L8484) | 5 | Try |
| [app.py:8488](../app.py#L8488) | 6 | If |
| [app.py:8518](../app.py#L8518) | 6 | If |
| [app.py:8524](../app.py#L8524) | 4 | If |
| [app.py:8800](../app.py#L8800) | 4 | If |
| [app.py:8806](../app.py#L8806) | 5 | If |
| [app.py:8963](../app.py#L8963) | 4 | If |
| [app.py:8965](../app.py#L8965) | 5 | If |
| [app.py:8975](../app.py#L8975) | 6 | If |
| [app.py:9699](../app.py#L9699) | 4 | If |
| [app.py:9701](../app.py#L9701) | 5 | If |
| [app.py:10041](../app.py#L10041) | 4 | If |
| [app.py:10059](../app.py#L10059) | 4 | If |
| [app.py:10318](../app.py#L10318) | 4 | If |
| [app.py:10320](../app.py#L10320) | 5 | If |
| [app.py:10322](../app.py#L10322) | 6 | If |
| [app.py:10744](../app.py#L10744) | 4 | If |
| [app.py:10746](../app.py#L10746) | 5 | If |
| [app.py:10748](../app.py#L10748) | 6 | If |
| [app.py:10755](../app.py#L10755) | 4 | For |
| [app.py:10756](../app.py#L10756) | 5 | If |
| [app.py:10758](../app.py#L10758) | 6 | If |
| [app.py:10761](../app.py#L10761) | 4 | If |
| [app.py:11728](../app.py#L11728) | 4 | If |
| [app.py:11908](../app.py#L11908) | 4 | If |
| [app.py:11913](../app.py#L11913) | 4 | If |
| [app.py:12097](../app.py#L12097) | 4 | If |
| [app.py:12138](../app.py#L12138) | 4 | If |
| [app.py:12333](../app.py#L12333) | 4 | Try |
| [app.py:12433](../app.py#L12433) | 4 | If |
| [app.py:12435](../app.py#L12435) | 4 | If |
| [app.py:12438](../app.py#L12438) | 5 | If |
| [app.py:12440](../app.py#L12440) | 5 | If |
| [app.py:12443](../app.py#L12443) | 6 | If |
| [app.py:12445](../app.py#L12445) | 6 | If |
| [app.py:12447](../app.py#L12447) | 7 | If |
| [app.py:12449](../app.py#L12449) | 8 | If |
| [app.py:12451](../app.py#L12451) | 9 | If |
| [app.py:12453](../app.py#L12453) | 10 | If |
| [app.py:12455](../app.py#L12455) | 11 | If |
| [app.py:12457](../app.py#L12457) | 12 | If |
| [app.py:12691](../app.py#L12691) | 4 | If |
| [app.py:12709](../app.py#L12709) | 4 | For |
| [app.py:12711](../app.py#L12711) | 5 | If |
| [app.py:12772](../app.py#L12772) | 4 | If |
| [app.py:12789](../app.py#L12789) | 4 | If |
| [app.py:12794](../app.py#L12794) | 4 | If |
| [app.py:13080](../app.py#L13080) | 4 | For |
| [app.py:13643](../app.py#L13643) | 4 | If |
| [app.py:13646](../app.py#L13646) | 5 | Try |
| [app.py:13648](../app.py#L13648) | 6 | If |
| [app.py:13659](../app.py#L13659) | 5 | If |
| [app.py:13661](../app.py#L13661) | 6 | If |
| [app.py:13663](../app.py#L13663) | 7 | If |
| [app.py:13668](../app.py#L13668) | 7 | If |
| [app.py:13672](../app.py#L13672) | 7 | If |
| [app.py:13682](../app.py#L13682) | 7 | If |
| [app.py:13686](../app.py#L13686) | 7 | If |
| [app.py:13688](../app.py#L13688) | 8 | For |
| [app.py:13689](../app.py#L13689) | 9 | Try |
| [app.py:13696](../app.py#L13696) | 8 | If |
| [app.py:13699](../app.py#L13699) | 8 | If |
| [app.py:13702](../app.py#L13702) | 8 | For |
| [app.py:13705](../app.py#L13705) | 8 | If |
| [app.py:13713](../app.py#L13713) | 9 | If |
| [app.py:13715](../app.py#L13715) | 10 | If |
| [app.py:13720](../app.py#L13720) | 9 | If |
| [app.py:13722](../app.py#L13722) | 9 | If |
| [app.py:13724](../app.py#L13724) | 9 | If |
| [app.py:13726](../app.py#L13726) | 9 | If |
| [app.py:13729](../app.py#L13729) | 9 | If |
| [app.py:13732](../app.py#L13732) | 10 | If |
| [app.py:13736](../app.py#L13736) | 10 | If |
| [app.py:13739](../app.py#L13739) | 11 | If |
| [app.py:13744](../app.py#L13744) | 11 | If |
| [app.py:13759](../app.py#L13759) | 11 | If |
| [app.py:13762](../app.py#L13762) | 12 | If |
| [app.py:13773](../app.py#L13773) | 12 | If |
| [app.py:13776](../app.py#L13776) | 13 | If |
| [app.py:13786](../app.py#L13786) | 13 | If |
| [app.py:13789](../app.py#L13789) | 14 | If |
| [app.py:13802](../app.py#L13802) | 14 | If |
| [app.py:13805](../app.py#L13805) | 15 | If |
| [app.py:13821](../app.py#L13821) | 15 | If |
| [app.py:13824](../app.py#L13824) | 16 | If |
| [app.py:13829](../app.py#L13829) | 16 | If |
| [app.py:13832](../app.py#L13832) | 17 | If |
| [app.py:13836](../app.py#L13836) | 17 | If |
| [app.py:13839](../app.py#L13839) | 18 | If |
| [app.py:13843](../app.py#L13843) | 18 | If |
| [app.py:13846](../app.py#L13846) | 19 | If |
| [app.py:13850](../app.py#L13850) | 19 | If |
| [app.py:13853](../app.py#L13853) | 20 | If |
| [app.py:13857](../app.py#L13857) | 20 | If |
| [app.py:13860](../app.py#L13860) | 21 | If |
| [app.py:13862](../app.py#L13862) | 21 | If |
| [app.py:13865](../app.py#L13865) | 21 | If |
| [app.py:13869](../app.py#L13869) | 21 | If |
| [app.py:13875](../app.py#L13875) | 21 | If |
| [app.py:13879](../app.py#L13879) | 21 | If |
| [app.py:13882](../app.py#L13882) | 22 | If |
| [app.py:13885](../app.py#L13885) | 22 | If |
| [app.py:13892](../app.py#L13892) | 22 | If |
| [app.py:13897](../app.py#L13897) | 23 | If |
| [app.py:13901](../app.py#L13901) | 23 | If |
| [app.py:13911](../app.py#L13911) | 23 | If |
| [app.py:13917](../app.py#L13917) | 24 | If |
| [app.py:13919](../app.py#L13919) | 25 | If |
| [app.py:13922](../app.py#L13922) | 24 | If |
| [app.py:13926](../app.py#L13926) | 24 | If |
| [app.py:13928](../app.py#L13928) | 25 | If |
| [app.py:13929](../app.py#L13929) | 26 | If |
| [app.py:13932](../app.py#L13932) | 26 | Try |
| [app.py:13934](../app.py#L13934) | 27 | If |
| [app.py:14411](../app.py#L14411) | 4 | For |
| [ffdc_chat.py:150](../ffdc_chat.py#L150) | 4 | If |
| [ffdc_chat.py:152](../ffdc_chat.py#L152) | 5 | If |
| [ffdc_chat.py:242](../ffdc_chat.py#L242) | 4 | If |
| [ffdc_chat.py:387](../ffdc_chat.py#L387) | 4 | If |
| [ffdc_chat.py:390](../ffdc_chat.py#L390) | 4 | If |
| [ffdc_chat.py:392](../ffdc_chat.py#L392) | 4 | For |
| [ffdc_chat.py:393](../ffdc_chat.py#L393) | 5 | If |
| [ffdc_chat.py:395](../ffdc_chat.py#L395) | 5 | If |
| [ffdc_chat.py:516](../ffdc_chat.py#L516) | 4 | Try |
| [ffdc_chat.py:518](../ffdc_chat.py#L518) | 5 | If |
| [workspace_analysis.py:129](../workspace_analysis.py#L129) | 4 | If |
| [workspace_analysis.py:132](../workspace_analysis.py#L132) | 4 | If |
| [workspace_analysis.py:136](../workspace_analysis.py#L136) | 4 | For |
| [workspace_analysis.py:137](../workspace_analysis.py#L137) | 5 | If |
| [workspace_analysis.py:138](../workspace_analysis.py#L138) | 6 | If |
| [workspace_analysis.py:140](../workspace_analysis.py#L140) | 6 | If |
| [workspace_analysis.py:143](../workspace_analysis.py#L143) | 5 | If |

### Top-Level Blank-Line Candidates

| Source | Observed blank lines before definition |
| --- | --- |
| [app.py:2522](../app.py#L2522) | 1 |
| [app.py:2567](../app.py#L2567) | 1 |
| [app.py:2613](../app.py#L2613) | 1 |
| [app.py:3069](../app.py#L3069) | 1 |
| [app.py:3079](../app.py#L3079) | 1 |
| [app.py:3208](../app.py#L3208) | 1 |
| [app.py:4864](../app.py#L4864) | 1 |
| [app.py:11068](../app.py#L11068) | 1 |
| [app.py:11547](../app.py#L11547) | 1 |
| [app.py:12627](../app.py#L12627) | 1 |
| [app.py:12658](../app.py#L12658) | 1 |
| [app.py:12822](../app.py#L12822) | 1 |
| [app.py:12898](../app.py#L12898) | 1 |

### Numeric Literal Index

Every nontrivial numeric literal (excluding -1, 0, 1 and 2) is listed with all line occurrences. Protocol encodings/register masks, HTML dimensions and legitimate budgets are included. No placeholder status is inferred from numeric presence alone.

#### `app.py`

| Literal | Source lines |
| --- | --- |
| 0.1 | 10978 |
| 0.2 | 10908, 10887 |
| 0.5 | 82, 4000, 4068 |
| 10 | 68, 134, 136, 808, 2379, 809, 5056, 11264, 10717, 11899, 8493 |
| 100 | 6220, 6237, 5000, 6242, 7071, 7458, 9631, 5061, 5238, 6778, 7014, 8619, 8880, 5070, 5146, 5179, 5241, 6209, 6242, 6836, 7034, 8652, 8859, 8882 |
| 1000 | 4609, 6047, 6054, 8431, 8438, 6858 |
| 1000000000 | 5002, 5003 |
| 1024 | 66, 67, 135, 136, 145, 146, 148, 1940, 66, 66, 67, 135, 136, 145, 146, 148, 1519, 2429, 2567, 1518, 2883, 2883, 13019, 13019, 13592, 13599, 1520, 14253, 14379, 313, 313, 4894, 4894, 7171, 7171, 2581, 5197, 5197, 5198, 5198, 5202, 5202, 7169, 7169, 5201, 7176, 7176, 5201 |
| 105 | 432 |
| 11 | 824, 825, 12493, 12494 |
| 110 | 7458 |
| 115 | 7458 |
| 12 | 1939, 2442, 4097, 9102, 131, 6280, 9110, 11100, 12384, 779, 780, 2411, 6539, 6627, 7915, 11216, 12059, 11188, 11213, 11258, 5269, 11336, 7578, 3446, 4824, 12598 |
| 120 | 7458, 5246 |
| 1200 | 10977, 8290, 11929, 9983 |
| 12000 | 11957 |
| 128 | 14470, 13592, 13599, 14253, 14379 |
| 14 | 9187, 788, 789, 10642 |
| 15 | 185, 183, 8869, 11719, 5863, 8543 |
| 150 | 12106, 10651, 10652 |
| 1500 | 6027, 6040, 8411, 8424 |
| 16 | 148, 1236, 717, 773, 960, 2793, 805, 2396, 3100, 7971, 12493, 801, 803, 1237, 841, 7979 |
| 160 | 12118, 7396, 7405 |
| 1600 | 8171, 11052, 11506, 7964 |
| 16000 | 14007 |
| 18 | 6485 |
| 180 | 4885, 4887, 2496, 2510, 2519 |
| 1800 | 10879, 10940, 6492, 11053, 7941, 9978, 9979 |
| 192 | 2567 |
| 20 | 11081, 135, 3826, 6944, 11101, 11191, 3816, 7480, 11133, 11170, 11217, 11218, 11263, 11286, 11287, 11288, 6400, 7480, 3897, 6564, 11333, 11361, 11362, 11363, 3768, 3870, 3777, 3786 |
| 200 | 13553, 13568, 13634, 14077, 14098, 14265, 14420, 13753, 13767, 13780, 13793, 13809, 13872 |
| 2000 | 9632, 3104 |
| 210 | 11717, 11735 |
| 220 | 2563 |
| 2200 | 11513 |
| 24 | 10567, 236 |
| 240 | 7505 |
| 2400 | 8179 |
| 25 | 9108, 4100, 6601, 11348, 11375 |
| 256 | 145, 2429, 1767 |
| 26 | 9233 |
| 260 | 2468 |
| 2600 | 11523 |
| 28 | 11995, 5190, 5192 |
| 3 | 144, 4794, 5979, 10940, 171, 2385, 7118, 11016, 11035, 11086, 1518, 2117, 2117, 2448, 3127, 5963, 6414, 7684, 8025, 8626, 11719, 479, 728, 3121, 6414, 13265, 13267, 487, 493, 498, 507, 510, 1206, 9250, 12427, 564, 575, 586, 8367, 12265, 12267 |
| 30 | 62, 69, 185, 5553, 5578, 7462, 8819, 8872, 6575, 11170, 11262, 7600, 5865, 11334, 11335, 11337, 11349, 11364, 5531, 5591, 5949, 11734 |
| 300 | 4635, 7358, 7510, 4202 |
| 3000 | 4527, 4572, 8271 |
| 303 | 13981, 14460, 14354, 14371, 14243, 14405, 13937 |
| 31 | 9638 |
| 32 | 67, 2802, 6284, 5191 |
| 365 | 9113 |
| 38 | 13747 |
| 4 | 79, 309, 486, 492, 774, 2382, 3527, 12295, 2118, 2118, 3518, 10651, 10652, 842, 3122, 3602, 6414, 507, 775, 3127, 9248, 11726, 776, 3528, 8218, 11911, 11911, 498, 510, 565, 576, 587, 2964, 3284, 3461, 3470, 6576, 8379, 12285, 12319, 12343, 12356, 12368, 9984, 12289 |
| 40 | 173, 2046, 6379, 7462, 2044, 2737, 10716, 10717, 11350, 11391, 7571 |
| 400 | 7540, 14301, 14441, 10896, 13973, 14005, 14008, 14049, 14113, 14121, 14138, 14197, 14285, 14294, 14314, 14455, 13658 |
| 4000 | 4152 |
| 401 | 4149, 4165, 4200, 4910, 13959, 4017, 4086, 14017, 14085, 14106, 14289 |
| 403 | 4149, 4165, 4200, 4910, 13951, 4017, 4086, 14146 |
| 404 | 4023, 10896, 14125, 14142, 14165, 14169, 14201, 14349, 14366, 13656, 13679, 13716, 13733, 13740, 13745, 13763, 13777, 13790, 13806, 13825, 13833, 13840, 13847, 13854, 13863, 13883, 13898, 13902, 13920, 13930 |
| 405 | 10896 |
| 409 | 14173, 13866, 13886, 13923 |
| 413 | 14435, 14254, 14304, 14380 |
| 420 | 9960 |
| 429 | 4019, 4088, 13962, 13990, 14033, 4005, 4074, 13971, 14025, 14060, 11726, 11728, 11727 |
| 44 | 80 |
| 45 | 5639, 6382, 6949, 8873, 390, 4145, 4162, 6577, 7196, 11503, 4002, 4070 |
| 5 | 185, 81, 183, 6064, 6311, 5051, 5988, 6938, 8864, 9608, 804, 7671, 8349, 8629, 9734, 9755, 805, 2978, 9246, 11168, 507, 10653, 11475, 566, 577, 8485, 11469, 8491, 6427 |
| 5.0 | 10953 |
| 50 | 7462, 7601, 7578 |
| 500 | 7485, 5616, 1963, 2284, 4652, 6033, 9973, 14465, 8417, 14027, 14062, 14131, 14156, 14180, 14211, 14249, 14272, 14296, 14316, 14326, 14332, 14341, 14358, 14375, 14428, 8290, 10914, 10984, 10897, 13941 |
| 5000 | 7130, 4568, 427 |
| 502 | 13975, 11727 |
| 503 | 11727 |
| 504 | 11727 |
| 512 | 1758 |
| 52 | 5189 |
| 6 | 12217, 178, 3026, 2982, 3040, 3054, 3066, 6564, 7571, 11911, 3033, 12918, 3461, 3470 |
| 60 | 131, 150, 153, 157, 160, 171, 178, 181, 184, 184, 192, 10623, 131, 150, 153, 157, 160, 171, 178, 181, 183, 183, 192, 236, 6381, 7460, 236, 5191, 6968, 10815, 4193, 6203, 4008, 4077, 7566 |
| 600 | 6442, 6465 |
| 64 | 193, 963, 2581 |
| 65 | 6378, 6380, 7461, 7461, 7461, 7461, 11510, 9234 |
| 68 | 6987 |
| 7 | 9185, 800, 801 |
| 70 | 6376, 6377, 7460, 7460, 6409 |
| 700 | 7669 |
| 730 | 9113 |
| 75 | 7460 |
| 76 | 6994, 6959 |
| 768 | 1940, 146 |
| 78 | 11518 |
| 8 | 150, 3134, 777, 802, 3561, 778, 2651, 3552, 4373, 5080, 5189, 5314, 5861, 7045, 7916, 7917, 7918, 7969, 7970, 7972, 8671, 8892, 10470, 10719, 11719, 12928, 4750, 6575, 12071, 307, 803, 806, 2731, 4875, 7155, 10450, 3562, 7566, 8464, 12343, 3423, 3479, 3581, 13178, 14444, 3433, 8489, 12359, 13999, 14043, 14056, 14119, 14191, 5201, 3735 |
| 80 | 7204, 7459, 7459, 2371, 2735, 2736, 5162 |
| 8000 | 147 |
| 8192 | 1954, 7477 |
| 82 | 7002 |
| 85 | 6577 |
| 88 | 8878, 8349 |
| 9 | 9824 |
| 90 | 81, 6374, 6375, 7353, 7459, 7166 |
| 9000 | 9991 |
| 94 | 8552, 8557 |
| 95 | 8563 |
| 96 | 8570 |
| 98 | 8586, 8593 |
| 999 | 5880, 5951, 5945 |
| 9999 | 9098 |
| 999999 | 9532, 9857 |

#### `ffdc_chat.py`

| Literal | Source lines |
| --- | --- |
| 0.2 | 500, 549 |
| 10 | 499 |
| 100 | 300, 195 |
| 1024 | 21, 22, 21, 22 |
| 12 | 22, 447 |
| 1200 | 307, 307, 330, 330 |
| 160 | 314, 339 |
| 16000 | 428, 495, 494 |
| 20 | 68, 429 |
| 2000 | 441 |
| 240 | 23 |
| 25 | 211 |
| 3 | 24 |
| 3000 | 65, 429 |
| 32 | 21 |
| 365 | 210 |
| 4 | 512 |
| 40 | 57, 327 |
| 400 | 322 |
| 4096 | 500, 549, 251 |
| 500 | 400, 399 |
| 6 | 314, 338, 191, 193 |
| 60 | 298 |
| 6000 | 70 |
| 730 | 210 |
| 8 | 44, 443, 492, 158 |
| 80 | 295, 295, 295 |
| 81 | 293 |

#### `workspace_analysis.py`

| Literal | Source lines |
| --- | --- |
| 1024 | 151, 151, 129, 129, 129 |
| 11 | 209, 178, 218 |
| 12 | 151, 129 |
| 20 | 79, 75, 79 |
| 240 | 122, 123 |
| 3 | 190, 206, 209, 218 |
| 32 | 65 |
| 4 | 148 |
| 40 | 226 |
| 500 | 172, 147, 146 |
| 512 | 129 |
| 6 | 175, 148 |
| 60 | 81 |
| 8 | 167, 215 |

#### `workspace_ui.py`

| Literal | Source lines |
| --- | --- |
| 10 | 9 |
| 1000 | 110 |
| 20 | 9 |
| 2026 | 9 |
| 3 | 9 |

#### `ffdc_config.py`

| Literal | Source lines |
| --- | --- |

#### `ffdc_jobs.py`

| Literal | Source lines |
| --- | --- |
| 100 | 72 |

### Potential Uncalled Functions

HTTP `do_GET`/`do_POST` and parser callbacks are framework dispatch, not dead code. This list is a review queue only.

| Source | Callable | Qualification |
| --- | --- | --- |
| [app.py:448](../app.py#L448) | table_rows_after | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:3108](../app.py#L3108) | parse_fpga_on_demand | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:4236](../app.py#L4236) | get_jira_session_credentials | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:5353](../app.py#L5353) | jira_monitor_job_path | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:6669](../app.py#L6669) | validate_tracker_project_jql | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:6829](../app.py#L6829) | has_running_current_status_summary_job | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:6841](../app.py#L6841) | normalize_current_status_summary_rows | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:8030](../app.py#L8030) | build_jira_monitor_prompt | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:9396](../app.py#L9396) | relative_calendar_age | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:9504](../app.py#L9504) | render_schedule_risk_summary | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:9585](../app.py#L9585) | jira_calendar_days_since | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:9908](../app.py#L9908) | render_schedule_ai_summary | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:10033](../app.py#L10033) | DefectReviewTableParser.handle_starttag | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:10044](../app.py#L10044) | DefectReviewTableParser.handle_data | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:10048](../app.py#L10048) | DefectReviewTableParser.handle_endtag | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:12228](../app.py#L12228) | collect_cross_log_correlations | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:12387](../app.py#L12387) | render_cross_log_correlations | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:12627](../app.py#L12627) | render_fpga_on | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:12811](../app.py#L12811) | render_ai_analysis | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:12898](../app.py#L12898) | build_default_jira_comment | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:13620](../app.py#L13620) | Handler.do_GET | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [app.py:13945](../app.py#L13945) | Handler.do_POST | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |
| [workspace_ui.py:46](../workspace_ui.py#L46) | classic_url | No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it. |

### Import-Time State

| Source | Statement type | Initializer / action |
| --- | --- | --- |
| [app.py:50](../app.py#L50) | Assign | ` BASE_DIR = Path(__file__).resolve().parent ` |
| [app.py:51](../app.py#L51) | Assign | ` DOMAIN_AUTHORING = DomainAuthoring(BASE_DIR / 'domain_drafts') ` |
| [app.py:52](../app.py#L52) | Assign | ` UPLOAD_DIR = BASE_DIR / 'uploads' ` |
| [app.py:53](../app.py#L53) | Assign | ` REPORT_DIR = BASE_DIR / 'reports' ` |
| [app.py:54](../app.py#L54) | Assign | ` FFDC_CACHE_DIR = BASE_DIR / 'ffdc_cache' ` |
| [app.py:55](../app.py#L55) | Assign | ` JIRA_OCR_CACHE_DIR = BASE_DIR / 'jira_ocr_cache' ` |
| [app.py:56](../app.py#L56) | Assign | ` JIRA_ATTACHMENT_CACHE_DIR = BASE_DIR / 'jira_attachment_cache' ` |
| [app.py:57](../app.py#L57) | Assign | ` JIRA_MONITOR_JOB_DIR = BASE_DIR / 'jira_monitor_jobs' ` |
| [app.py:58](../app.py#L58) | Assign | ` CURRENT_STATUS_SUMMARY_DIR = BASE_DIR / 'current_status_summary' ` |
| [app.py:59](../app.py#L59) | Assign | ` STATIC_DIR = BASE_DIR / 'static' ` |
| [app.py:60](../app.py#L60) | Assign | ` USAGE_STATS_FILE = BASE_DIR / 'usage_stats.json' ` |
| [app.py:61](../app.py#L61) | Assign | ` USAGE_STATS_LOCK = threading.Lock() ` |
| [app.py:62](../app.py#L62) | Assign | ` USAGE_STATS_RETENTION_DAYS = 30 ` |
| [app.py:63](../app.py#L63) | Assign | ` SAMPLE_FFDC = env_path('FFDC_SAMPLE', '/root/codx_test/7D6NCTO3WW_J902ZRCV_xcc_260324-030334_pass.tzz') ` |
| [app.py:64](../app.py#L64) | Assign | ` KEYFILES = env_path('FFDC_KEYFILES', '/root/codx_test/keyfiles.txt') ` |
| [app.py:65](../app.py#L65) | Assign | ` API_KEY_FILE = env_path('FFDC_API_KEY_FILE', '/root/codx_test/api_key.txt') ` |
| [app.py:66](../app.py#L66) | Assign | ` MAX_UPLOAD_BYTES = 1024 * 1024 * 1024 ` |
| [app.py:67](../app.py#L67) | Assign | ` DOMAIN_AUTHOR_REQUEST_MAX_BYTES = 32 * 1024 * 1024 ` |
| [app.py:68](../app.py#L68) | Assign | ` MAX_UPLOAD_FILES = 10 ` |
| [app.py:69](../app.py#L69) | Assign | ` REPORT_RETENTION_DAYS = 30 ` |
| [app.py:70](../app.py#L70) | Assign | ` OPENAI_MODEL = os.environ.get('FFDC_OPENAI_MODEL', 'gpt-5.2') ` |
| [app.py:71](../app.py#L71) | Assign | ` DEEP_INVESTIGATION_MODEL = os.environ.get('FFDC_DEEP_INVESTIGATION_MODEL', 'nemotron-3-ultra').strip() or 'nemotron-3-ultra' ` |
| [app.py:75](../app.py#L75) | Assign | ` CHAT_MODEL = os.environ.get('FFDC_CHAT_MODEL', 'nemotron-3-ultra').strip() or 'nemotron-3-ultra' ` |
| [app.py:79](../app.py#L79) | Assign | ` MAX_CONCURRENT_AI_REQUESTS = env_int('FFDC_MAX_CONCURRENT_AI_REQUESTS', 4, minimum=1) ` |
| [app.py:80](../app.py#L80) | Assign | ` MAX_QUEUED_AI_REQUESTS = env_int('FFDC_MAX_QUEUED_AI_REQUESTS', 44, minimum=0) ` |
| [app.py:81](../app.py#L81) | Assign | ` AI_REQUEST_QUEUE_TIMEOUT_SECONDS = env_int('FFDC_AI_REQUEST_QUEUE_TIMEOUT_SECONDS', 90, minimum=5) ` |
| [app.py:82](../app.py#L82) | Assign | ` AI_REQUEST_MIN_START_INTERVAL_SECONDS = env_float('FFDC_AI_MIN_START_INTERVAL_SECONDS', 0.5, minimum=0.0) ` |
| [app.py:83](../app.py#L83) | Assign | ` WORKSPACE_CHAT_LIMIT = threading.BoundedSemaphore(MAX_CONCURRENT_AI_REQUESTS) ` |
| [app.py:84](../app.py#L84) | Assign | ` AI_REQUEST_QUEUE_LOCK = threading.Lock() ` |
| [app.py:85](../app.py#L85) | Assign | ` AI_REQUESTS_ADMITTED = 0 ` |
| [app.py:86](../app.py#L86) | Assign | ` AI_REQUEST_RATE_LOCK = threading.Lock() ` |
| [app.py:87](../app.py#L87) | Assign | ` AI_REQUEST_NEXT_START = 0.0 ` |
| [app.py:88](../app.py#L88) | Assign | ` WORKSPACE_CHAT_MODEL = os.environ.get('FFDC_WORKSPACE_CHAT_MODEL', '').strip() ` |
| [app.py:89](../app.py#L89) | Assign | ` AI_SSL_CONTEXT = ssl._create_unverified_context() ` |
| [app.py:90](../app.py#L90) | Assign | ` JIRA_BASE_URL = env_url('FFDC_JIRA_BASE_URL', 'https://jira1.labs.lenovo.com') ` |
| [app.py:91](../app.py#L91) | Assign | ` JIRA_SSL_CONTEXT = ssl._create_unverified_context() ` |
| [app.py:130](../app.py#L130) | Assign | ` JIRA_SIMILAR_PAT_FILE = env_path('FFDC_JIRA_SIMILAR_PAT_FILE', BASE_DIR / '.jira_similar_pat') ` |
| [app.py:131](../app.py#L131) | Assign | ` JIRA_SIMILAR_CASES_TTL_SECONDS = 12 * 60 * 60 ` |
| [app.py:132](../app.py#L132) | Assign | ` FFDC_ATTACHMENT_EXTENSIONS = ('.tzz', '.tar.zst', '.tzst', '.tgz', '.tar.gz', '.tar', '.gz') ` |
| [app.py:133](../app.py#L133) | Assign | ` JIRA_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff') ` |
| [app.py:134](../app.py#L134) | Assign | ` MAX_JIRA_OCR_IMAGES = 10 ` |
| [app.py:135](../app.py#L135) | Assign | ` MAX_JIRA_IMAGE_BYTES = 20 * 1024 * 1024 ` |
| [app.py:136](../app.py#L136) | Assign | ` MAX_JIRA_VISION_IMAGE_BYTES = 10 * 1024 * 1024 ` |
| [app.py:137](../app.py#L137) | Assign | ` JIRA_VISION_IMAGE_MIME_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'} ` |
| [app.py:143](../app.py#L143) | Assign | ` JIRA_LOG_ARCHIVE_EXTENSIONS = ('.rar', '.zip', '.7z') ` |
| [app.py:144](../app.py#L144) | Assign | ` MAX_JIRA_LOG_ARCHIVES = 3 ` |
| [app.py:145](../app.py#L145) | Assign | ` MAX_JIRA_LOG_ARCHIVE_BYTES = 256 * 1024 * 1024 ` |
| [app.py:146](../app.py#L146) | Assign | ` MAX_JIRA_LOG_EXTRACTED_BYTES = 768 * 1024 * 1024 ` |
| [app.py:147](../app.py#L147) | Assign | ` MAX_JIRA_LOG_FILES = 8000 ` |
| [app.py:148](../app.py#L148) | Assign | ` MAX_JIRA_LOG_TEXT_FILE_BYTES = 16 * 1024 * 1024 ` |
| [app.py:149](../app.py#L149) | Assign | ` JIRA_SESSION_COOKIE = 'ffdc_jira_session' ` |
| [app.py:150](../app.py#L150) | Assign | ` JIRA_SESSION_TTL_SECONDS = 8 * 60 * 60 ` |
| [app.py:151](../app.py#L151) | Assign | ` JIRA_SESSIONS = {} ` |
| [app.py:152](../app.py#L152) | Assign | ` AUTHOR_SESSION_COOKIE = 'ffdc_author_session' ` |
| [app.py:153](../app.py#L153) | Assign | ` AUTHOR_SESSION_TTL_SECONDS = 2 * 60 * 60 ` |
| [app.py:154](../app.py#L154) | Assign | ` AUTHOR_SESSIONS = {} ` |
| [app.py:155](../app.py#L155) | Assign | ` JIRA_JOBS = {} ` |
| [app.py:156](../app.py#L156) | Assign | ` JIRA_JOBS_LOCK = threading.Lock() ` |
| [app.py:157](../app.py#L157) | Assign | ` JIRA_JOB_TTL_SECONDS = 2 * 60 * 60 ` |
| [app.py:158](../app.py#L158) | Assign | ` WORKSPACE_UPLOAD_JOBS = {} ` |
| [app.py:159](../app.py#L159) | Assign | ` WORKSPACE_UPLOAD_JOBS_LOCK = threading.Lock() ` |
| [app.py:160](../app.py#L160) | Assign | ` WORKSPACE_UPLOAD_JOB_TTL_SECONDS = 2 * 60 * 60 ` |
| [app.py:161](../app.py#L161) | Assign | ` JIRA_MONITOR_FILTER_ID = os.environ.get('FFDC_JIRA_MONITOR_FILTER_ID', '34570') ` |
| [app.py:162](../app.py#L162) | Assign | ` JIRA_MONITOR_CONFIG_FILE = env_path('FFDC_JIRA_MONITOR_CONFIG', BASE_DIR / 'defect_review_config.json') ` |
| [app.py:163](../app.py#L163) | Assign | ` DEFECT_REVIEW_EMAIL_TO = os.environ.get('FFDC_DEFECT_REVIEW_EMAIL_TO', 'RAIDAsia@LenovoBeijing.onmicrosoft.com').strip() ` |
| [app.py:167](../app.py#L167) | Assign | ` JIRA_MONITOR_LATEST_FILE = JIRA_MONITOR_JOB_DIR / 'latest.json' ` |
| [app.py:168](../app.py#L168) | Assign | ` JIRA_MONITOR_SCHEDULE_STATE_FILE = JIRA_MONITOR_JOB_DIR / 'schedule_state.json' ` |
| [app.py:169](../app.py#L169) | Assign | ` MILESTONE_TRACKER_CACHE_FILE = BASE_DIR / 'project_milestone_tracker.json' ` |
| [app.py:170](../app.py#L170) | Assign | ` PROJECT_TOOL_BASE_URL = env_url('FFDC_PROJECT_TOOL_BASE_URL', 'https://project-tool.labs.lenovo.com') ` |
| [app.py:171](../app.py#L171) | Assign | ` PROJECT_TOOL_CACHE_TTL_SECONDS = 3 * 60 * 60 ` |
| [app.py:172](../app.py#L172) | Assign | ` UPCOMING_MILESTONE_REPORT_ID = os.environ.get('FFDC_UPCOMING_MILESTONE_REPORT_ID', '562') ` |
| [app.py:173](../app.py#L173) | Assign | ` UPCOMING_MILESTONE_MAX_DAYS = 40 ` |
| [app.py:174](../app.py#L174) | Assign | ` PROJECT_TOOL_SSL_CONTEXT = ssl._create_unverified_context() ` |
| [app.py:175](../app.py#L175) | Assign | ` MILESTONE_CACHE_LOCK = threading.Lock() ` |
| [app.py:176](../app.py#L176) | Assign | ` JIRA_MONITOR_JOBS = {} ` |
| [app.py:177](../app.py#L177) | Assign | ` JIRA_MONITOR_JOBS_LOCK = threading.Lock() ` |
| [app.py:178](../app.py#L178) | Assign | ` JIRA_MONITOR_JOB_TTL_SECONDS = 6 * 60 * 60 ` |
| [app.py:179](../app.py#L179) | Assign | ` CURRENT_STATUS_SUMMARY_JOBS = {} ` |
| [app.py:180](../app.py#L180) | Assign | ` CURRENT_STATUS_SUMMARY_JOBS_LOCK = threading.Lock() ` |
| [app.py:181](../app.py#L181) | Assign | ` CURRENT_STATUS_SUMMARY_JOB_TTL_SECONDS = 2 * 60 * 60 ` |
| [app.py:182](../app.py#L182) | Assign | ` JIRA_MONITOR_SCHEDULER_LOCK = threading.Lock() ` |
| [app.py:183](../app.py#L183) | Assign | ` JIRA_MONITOR_SCHEDULE_RETRY_DELAYS_SECONDS = (5 * 60, 15 * 60) ` |
| [app.py:184](../app.py#L184) | Assign | ` JIRA_MONITOR_SCHEDULE_RETRY_MAX_AGE_SECONDS = 60 * 60 ` |
| [app.py:185](../app.py#L185) | Assign | ` JIRA_RATE_LIMIT_RETRY_DELAYS_SECONDS = (5, 15, 30) ` |
| [app.py:186](../app.py#L186) | Assign | ` JIRA_REQUEST_LOCK = threading.Lock() ` |
| [app.py:187](../app.py#L187) | Assign | ` JIRA_REQUEST_NEXT_AT = 0.0 ` |
| [app.py:188](../app.py#L188) | Assign | ` JIRA_REQUEST_MIN_INTERVAL_SECONDS = env_float('FFDC_JIRA_REQUEST_MIN_INTERVAL_SECONDS', 2, minimum=0.0) ` |
| [app.py:189](../app.py#L189) | Assign | ` FFDC_CACHE_LOCK = threading.Lock() ` |
| [app.py:190](../app.py#L190) | Assign | ` AGENT_JOBS = {} ` |
| [app.py:191](../app.py#L191) | Assign | ` AGENT_JOBS_LOCK = threading.Lock() ` |
| [app.py:192](../app.py#L192) | Assign | ` AGENT_JOB_TTL_SECONDS = 2 * 60 * 60 ` |
| [app.py:193](../app.py#L193) | Assign | ` MAX_CONCURRENT_ANALYSES = env_int('FFDC_MAX_CONCURRENT_ANALYSES', 64, minimum=1) ` |
| [app.py:194](../app.py#L194) | Assign | ` ANALYSIS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES) ` |
| [app.py:195](../app.py#L195) | Assign | ` ANALYSIS_STATE_LOCK = threading.Lock() ` |
| [app.py:196](../app.py#L196) | Assign | ` ANALYSIS_ACTIVE = 0 ` |
| [app.py:198](../app.py#L198) | Try | ` try:     import cgi except ModuleNotFoundError:     cgi = None ` |
| [app.py:204](../app.py#L204) | Assign | ` KEY_PATHS = {'service': ['tmp/service.txt', 'service.txt'], 'dmdb': ['tmp/ffdc_live_dbg/dmdb_pci_dumper.txt', 'tmp/ffdc_live_dbg/dmeb_pci_dumper.txt'], 'sep_info': ['tmp/ffdc_live_dbg/sep_info.txt'], 'sep_vpd': ['tmp/ffdc_live_dbg/sep_vpd.txt', 'tmp/sep_vpd.txt'], 'cds': ['tmp/ffdc_live_dbg/cds.xml'], 'fru': ['tmp/ffdc_live_dbg/vertiv_live_dbg/vertiv_ipmitool_fru.log'], 'minilog': ['minilog.json'], 'backplanes': ['backplanes.json', 'bpinventory.j ` |
| [app.py:846](../app.py#L846) | Assign | ` SEP_APPLICATIONS = {'BB': 'SEP 4MV4', 'BC': 'SEP 4MEV4', 'BD': 'SEP 12XV4', 'BE': 'SEP 8EV4', 'BF': 'SEP 4NV5', 'C0': 'SEP 6EV5', 'C1': 'SEP 4EV5'} ` |
| [app.py:856](../app.py#L856) | Assign | ` TRI_MODEL_BP_STATUS = {'C3': ('Empty', 'empty'), 'C0': ('SAS/SATA Drive Installed', 'sas_sata'), 'D0': ('SAS/SATA Drive Rebuilding', 'rebuild'), 'C8': ('SAS/SATA Drive Locate', 'locate'), 'E0': ('SAS/SATA Drive Fail', 'fail'), 'C5': ('Fault: NVMe Drive Installed', 'fault'), '85': ('Fault: NVMe Drive Installed', 'fault'), 'C6': ('Fault: SATA Express Drive Installed', 'fault'), 'C4': ('NVMe Only Auto-config 0xA0', 'nvme'), 'C1': ('NVMe Drive U.2 In ` |
| [app.py:876](../app.py#L876) | Assign | ` SAS_SATA_BP_STATUS = {'83': ('Empty', 'empty'), '80': ('SAS/SATA Drive Installed', 'sas_sata'), '90': ('SAS/SATA Drive Rebuilding', 'rebuild'), '88': ('SAS/SATA Drive Locate', 'locate'), 'A0': ('SAS/SATA Drive Fail', 'fail'), '85': ('Fault: NVMe Drive Installed', 'fault'), '86': ('Fault: SATA Express Drive Installed', 'fault')} ` |
| [app.py:886](../app.py#L886) | Assign | ` V1_SAS_SATA_BP_STATUS = {**SAS_SATA_BP_STATUS, '84': ('Fault: SAS/SATA Drive Installed', 'fault')} ` |
| [app.py:891](../app.py#L891) | Assign | ` EDSFF_BP_STATUS = {'C3': ('Empty', 'empty'), 'C2': ('EDSFF x4 Drive Installed', 'edsff'), 'C0': ('EDSFF x8 Drive Installed', 'edsff'), '80': ('EDSFF x16 Drive Installed', 'edsff'), 'D2': ('EDSFF x4 Drive Rebuilding', 'rebuild'), 'CA': ('EDSFF x4 Drive Locate', 'locate'), 'E2': ('EDSFF x4 Drive Fail', 'fail'), 'D0': ('EDSFF x8 Drive Rebuilding', 'rebuild'), 'C8': ('EDSFF x8 Drive Locate', 'locate'), 'E0': ('EDSFF x8 Drive Fail', 'fail'), '90': ('E ` |
| [app.py:907](../app.py#L907) | Assign | ` TRI_MODEL_EDSFF_BP_STATUS = {**TRI_MODEL_BP_STATUS, '83': ('EDSFF x4 Drive Installed', 'edsff'), '82': ('EDSFF x8 Drive Installed', 'edsff'), '93': ('EDSFF x4 Drive Rebuilding', 'rebuild'), '8B': ('EDSFF x4 Drive Locate', 'locate'), 'A3': ('EDSFF x4 Drive Fail', 'fail'), '92': ('EDSFF x8 Drive Rebuilding', 'rebuild'), '8A': ('EDSFF x8 Drive Locate', 'locate'), 'A2': ('EDSFF x8 Drive Fail', 'fail')} ` |
| [app.py:919](../app.py#L919) | Assign | ` V4_4MEV4_BP_STATUS = {**TRI_MODEL_BP_STATUS, 'C2': ('EDSFF x4 Drive Installed', 'edsff'), '42': ('EDSFF x8 Drive Installed', 'edsff'), 'D2': ('EDSFF x4 Drive Rebuilding', 'rebuild'), 'CA': ('EDSFF x4 Drive Locate', 'locate'), 'E2': ('EDSFF x4 Drive Fail', 'fail'), '52': ('EDSFF x8 Drive Rebuilding', 'rebuild'), '4A': ('EDSFF x8 Drive Locate', 'locate'), '62': ('EDSFF x8 Drive Fail', 'fail')} ` |
| [app.py:931](../app.py#L931) | Assign | ` V4_8EV4_BP_STATUS = {'C1': ('Empty', 'empty'), 'C0': ('EDSFF x4 Drive Installed', 'edsff'), '40': ('EDSFF x8 Drive Installed', 'edsff'), 'D0': ('EDSFF x4 Drive Rebuilding', 'rebuild'), 'C8': ('EDSFF x4 Drive Locate', 'locate'), 'E0': ('EDSFF x4 Drive Fail', 'fail'), '50': ('EDSFF x8 Drive Rebuilding', 'rebuild'), '48': ('EDSFF x8 Drive Locate', 'locate'), '60': ('EDSFF x8 Drive Fail', 'fail')} ` |
| [app.py:943](../app.py#L943) | Assign | ` V4_4NV5_BP_STATUS = {'C3': ('Empty', 'empty'), 'C4': ('Fault: SAS/SATA Drive Installed', 'fault'), 'C6': ('Fault: SATA Express Drive Installed', 'fault'), 'C1': ('NVMe Drive U.2 Installed', 'nvme'), 'E1': ('NVMe Drive U.2 Fail', 'fail')} ` |
| [app.py:951](../app.py#L951) | Assign | ` EDSFF_ONLY_CODES = {'C2', 'CA', 'E2'} ` |
| [app.py:952](../app.py#L952) | Assign | ` TRI_MODEL_EDSFF_CODES = {'82', '8A', '8B', '92', '93', 'A2', 'A3'} ` |
| [app.py:1829](../app.py#L1829) | Assign | ` EXTERNAL_STORAGE_MODEL_RE = re.compile('\\b(?:\\d{3,5}\\s*[-/]\\s*\\d+\\s*e\|\\d{4,7}e)\\b', re.I) ` |
| [app.py:1832](../app.py#L1832) | Assign | ` BUILT_IN_BACKPLANE_EVIDENCE_FILES = ('sep_info.txt', 'sep_vpd.txt', 'backplanes.txt', 'backplanes.json') ` |
| [app.py:1921](../app.py#L1921) | Assign | ` NETWORK_ADAPTER_RE = re.compile('\\b(?:ethernet\|network controller\|nic\\b\|mellanox\|connectx\|netxtreme\|broadcom\|intel\\s+(?:i\\d+\|x\\d+\|e\\d+)\|\\b(?:i40e\|ice\|igb\|ixgbe\|bnxt)\\b\|marvell\|qlogic)\\b', re.I) ` |
| [app.py:1926](../app.py#L1926) | Assign | ` NETWORK_INTERFACE_RE = re.compile('\\b(?:en[opsx][a-zA-Z0-9_.:-]*\|eth\\d+\|bond\\d+\|team\\d+\|ib\\d+)\\b', re.I) ` |
| [app.py:1930](../app.py#L1930) | Assign | ` NETWORK_LOG_NAME_RE = re.compile('(?:journal\|syslog\|messages\|dmesg\|kernel\|network\|netdev\|ethernet\|nic\|ethtool\|link)', re.I) ` |
| [app.py:1934](../app.py#L1934) | Assign | ` NETWORK_SENSITIVE_RE = re.compile('\\b(?:password\|passwd\|api[_ -]?key\|authorization\|bearer\|access[_ -]?token\|private[_ -]?key\|secret)\\b', re.I) ` |
| [app.py:1938](../app.py#L1938) | Assign | ` NETWORK_DRIVER_RE = re.compile('\\b(?:i40e\|ice\|igb\|ixgbe\|bnxt_en\|bnx2x\|mlx[45]_core\|tg3\|e1000e\|ena)\\b', re.I) ` |
| [app.py:1939](../app.py#L1939) | Assign | ` MAX_NETWORK_LOG_FILES = 12 ` |
| [app.py:1940](../app.py#L1940) | Assign | ` MAX_NETWORK_LOG_BYTES_PER_FILE = 768 * 1024 ` |
| [app.py:2137](../app.py#L2137) | Assign | ` PLDM_UPDATE_START_RE = re.compile('^(?P<timestamp>\\S+).*?==== Run update on the device \\[TID=(?P<tid>[^,]+),\\s*EID=(?P<eid>[^,]+),\\s*ADDR=(?P<address>[^\\]]+)\\],\\s*Activate=(?P<activate>\\w+) ====', re.I) ` |
| [app.py:2143](../app.py#L2143) | Assign | ` PLDM_COMPONENT_VERSION_RE = re.compile('Component\\s+(?P<component>\\d+),\\s*version:\\s*(?P<version>.+)$', re.I) ` |
| [app.py:2144](../app.py#L2144) | Assign | ` PLDM_COMPAT_RESPONSE_RE = re.compile('compCompatabilityRespCode\\s*=\\s*(?P<code>\\d+)', re.I) ` |
| [app.py:2265](../app.py#L2265) | Assign | ` BMC_INBAND_LOG_NAME_RE = re.compile('(?:flash\|firmware\|fwupdate\|fw_update\|in.?band\|pldm\|mctp\|journal\|syslog\|messages)', re.I) ` |
| [app.py:2269](../app.py#L2269) | Assign | ` BMC_INBAND_CONTEXT_RE = re.compile('\\b(?:bmc\|bmu\|in[- ]?band\|redfish\|update service)\\b', re.I) ` |
| [app.py:2270](../app.py#L2270) | Assign | ` BMC_INBAND_ACTION_RE = re.compile('\\b(?:firmware\|firmware update\|fw update\|flash(?:ing)?\|startfwupdate\|activate\|download(?:ing)?\|transfer(?:ring)?\|verify(?:ing)?\|rollback)\\b', re.I) ` |
| [app.py:2275](../app.py#L2275) | Assign | ` BMC_INBAND_FAILURE_RE = re.compile('\\b(?:failed\|failure\|error\|timeout\|timed out\|abort(?:ed)?\|rollback\|reject(?:ed)?)\\b', re.I) ` |
| [app.py:2276](../app.py#L2276) | Assign | ` BMC_INBAND_SUCCESS_RE = re.compile('\\b(?:succeeded\|success(?:ful(?:ly)?)?\|completed\|complete\|activated\|done)\\b', re.I) ` |
| [app.py:2277](../app.py#L2277) | Assign | ` BMC_INBAND_START_RE = re.compile('\\b(?:start(?:ed\|ing)?\|begin\|prepare\|download(?:ing)?\|transfer(?:ring)?\|flash(?:ing)?)\\b', re.I) ` |
| [app.py:2438](../app.py#L2438) | Assign | ` UEFI_KEYWORD_RE = re.compile('\\b(error\|failed\|fail\|warning\|timeout\|assert\|exception\|hang\|critical\|fatal\|degraded\|offline\|mismatch\|not found\|cannot\|unable)\\b\|PCIe\|NVMe\|RAID\|Option ROM\|Link\|Training', re.I) ` |
| [app.py:2439](../app.py#L2439) | Assign | ` UEFI_STRONG_RE = re.compile('\\b(error\|failed\|fail\|timeout\|assert\|exception\|hang\|critical\|fatal\|degraded\|offline\|mismatch)\\b', re.I) ` |
| [app.py:2744](../app.py#L2744) | Assign | ` RAID_TTY_STRONG_RE = re.compile('\\b(fatal\|panic\|exception\|degraded\|offline)\\b', re.I) ` |
| [app.py:2745](../app.py#L2745) | Assign | ` RAID_TTY_CAPACITOR_RE = re.compile('supercap\|capacitor\|capacitance\|bbu\|battery\|cachevault\|cvpm\|cache vault\|retention', re.I) ` |
| [app.py:2746](../app.py#L2746) | Assign | ` RAID_TTY_CAPACITOR_BAD_RE = re.compile('failed\|fail\|fault\|bad\|missing\|not present\|replacement\|required\|low\|critical(?! temperature)\|warning', re.I) ` |
| [app.py:2747](../app.py#L2747) | Assign | ` RAID_TTY_PCIE_LINK_RE = re.compile('PCIE\\s+Link\\s+Status/Ctrl.*?Speeds:\\s*max=([0-9.]+)\\s*GT/s\\s+neg=([0-9.]+)\\s*GT/s,\\s*Widths:\\s*max=(\\d+)\\s+neg=(\\d+)', re.I) ` |
| [app.py:7422](../app.py#L7422) | Assign | ` JIRA_LOG_TEXT_EXTENSIONS = {'.log', '.txt', '.out', '.err', '.json', '.xml', '.csv', '.conf', '.cfg', '.ini', '.yaml', '.yml', '.trace', '.dmesg', '.journal'} ` |
| [app.py:7426](../app.py#L7426) | Assign | ` JIRA_LOG_ERROR_RE = re.compile('\\b(?:timed?\\s*out\|timeout\|abort(?:ed\|ing)?\|failed\|failure\|fatal\|critical\|panic\|hung\|reset(?:ting)?\|link\\s+(?:down\|fail\\w*)\|i/o\\s+error\|medium\\s+error\|degraded\|offline\|not\\s+responding\|device\\s+not\\s+ready\|uncorrectable)\\b', re.I) ` |
| [app.py:7432](../app.py#L7432) | Assign | ` JIRA_LOG_VERSION_RE = re.compile('\\b(?:driver\|firmware\|kernel\|module\|megaraid_sas\|mpt3sas\|storcli\|perccli\|sas3ircu)\\b.{0,80}\\b(?:version\|build\|release\|[0-9]+\\.[0-9]+(?:\\.[0-9]+){1,3})\\b\|\\b(?:version\|build\|release)\\b.{0,80}\\b(?:driver\|firmware\|kernel\|module)\\b', re.I) ` |
| [app.py:7438](../app.py#L7438) | Assign | ` JIRA_LOG_BOOT_RE = re.compile('\\b(?:post\\s*end\|postend\|boot\\s+progress\|uefi\|bds\|pcie\|pci\\s+express\|nvme\|e3\\.s\|cd8p\|enumerat(?:e\|ion)\|initiali[sz](?:e\|ation)\|watchdog)\\b', re.I) ` |
| [app.py:7443](../app.py#L7443) | Assign | ` JIRA_LOG_BOOT_FAILURE_RE = re.compile('\\b(?:post\\s*end\|postend\|hang(?:s\|ed\|ing)?\|hung\|assert(?:ion)?\|exception\|watchdog\|timeout\|timed?\\s*out\|abort(?:ed\|ing)?\|fail(?:ed\|ure)?)\\b', re.I) ` |
| [app.py:7448](../app.py#L7448) | Assign | ` JIRA_LOG_SENSITIVE_RE = re.compile('\\b(?:password\|passwd\|api[_ -]?key\|authorization\|bearer\|access[_ -]?token\|private[_ -]?key\|secret)\\b', re.I) ` |
| [app.py:13385](../app.py#L13385) | Assign | ` HTML_HEAD = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ThinkSystem FFDC Analyzer for RAID team</title><style>\n:root{color-scheme:light;--bg:#f6f7f9;--panel:#fff;--text:#1b2430;--muted:#667085;--line:#d9dee7;--accent:#246bfe;--ok:#0f8a5f}*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--text)}main{max-w ` |
| [app.py:14487](../app.py#L14487) | If | ` if __name__ == '__main__':     main() ` |
| [ffdc_chat.py:19](../ffdc_chat.py#L19) | Assign | ` TEXT_SUFFIXES = {'', '.txt', '.log', '.out', '.json', '.xml', '.csv', '.trace', '.journal', '.dmesg'} ` |
| [ffdc_chat.py:20](../ffdc_chat.py#L20) | Assign | ` SECRET = re.compile('password\|passwd\|authorization\|bearer\|api[_ -]?key\|access[_ -]?token\|private[_ -]?key\|secret', re.I) ` |
| [ffdc_chat.py:21](../ffdc_chat.py#L21) | Assign | ` MAX_SCAN_BYTES = 32 * 1024 * 1024 ` |
| [ffdc_chat.py:22](../ffdc_chat.py#L22) | Assign | ` TRIAGE_SCAN_BYTES = 12 * 1024 * 1024 ` |
| [ffdc_chat.py:23](../ffdc_chat.py#L23) | Assign | ` TRIAGE_MAX_FILES = 240 ` |
| [ffdc_chat.py:24](../ffdc_chat.py#L24) | Assign | ` TRIAGE_MATCHES_PER_CATEGORY = 3 ` |
| [ffdc_chat.py:25](../ffdc_chat.py#L25) | Assign | ` TRIAGE_FOCUSES = {'all', 'storage', 'pcie', 'network', 'firmware', 'system'} ` |
| [ffdc_chat.py:26](../ffdc_chat.py#L26) | Assign | ` TRIAGE_FAILURE = re.compile('\\b(?:error\|fail(?:ed\|ure)?\|critical\|fatal\|timeout\|unsupported\|degraded\|predictive(?:failure)?\|uncorrectable\|unrecoverable\|panic\|assert\|offline\|not detected\|link down\|carrier lost\|reset\|aborted)\\b', re.I) ` |
| [ffdc_chat.py:32](../ffdc_chat.py#L32) | Assign | ` TRIAGE_COMPONENTS = {'storage': re.compile('\\b(?:raid\|hba\|drive\|disk\|nvme\|sas\|sata\|scsi\|backplane\|sep\|ubm\|controller\|media)\\b', re.I), 'pcie': re.compile('\\b(?:pcie\|pci\|aer\|completion\|surprise down\|link width\|link speed\|slot)\\b', re.I), 'network': re.compile('\\b(?:ethernet\|network\|netdev\|nic\|carrier\|tx\|rx\|mlx\|i40e\|ice\|bnxt\|e1000\|igb)\\b', re.I), 'firmware': re.compile('\\b(?:firmware\|flash\|pldm\|mctp\|psoc\|bmc\|bmu\|update)\\b', re.I), 'system': ` |
| [workspace_analysis.py:11](../workspace_analysis.py#L11) | Assign | ` FOCUS_WORDS = {'network': '网卡\|网络\|丢包\|以太\|\\b(?:nic\|ethernet\|network\|netdev\|mlx\\w*\|bnxt\\w*\|link down\|carrier)\\b', 'storage': '背板\|磁盘\|硬盘\|盘符\|\\b(?:raid\|hba\|drive\|disk\|nvme\|backplane\|psoc\|ubm)\\b', 'firmware': '固件\|刷写\|升级\|\\b(?:firmware\|flash\|pldm\|mctp\|bmu\|in.?band)\\b', 'pcie': '通道\|链路宽\|\\b(?:pcie\|aer\|link width\|link speed)\\b', 'system': '内存\|电源\|温度\|\\b(?:dimm\|memory\|cpu\|thermal\|power\|watchdog\|panic)\\b'} ` |
| [workspace_analysis.py:18](../workspace_analysis.py#L18) | Assign | ` BENIGN = re.compile('\\b(?:no errors?\|0 errors?\|errors?\\s*[:=]\\s*0\\b\|failures?\\s*[:=]\\s*0\\b\|error handling\|error injection\|supported error)\\b', re.I) ` |
| [workspace_analysis.py:19](../workspace_analysis.py#L19) | Assign | ` URGENT = re.compile('\\b(?:fatal\|uncorrectable\|panic\|critical\|failed\|timeout\|unsupported\|not detected)\\b', re.I) ` |
| [workspace_analysis.py:20](../workspace_analysis.py#L20) | Assign | ` DISCOVERY_SIGNAL = re.compile('\\b(?:fault\|mismatch\|invalid\|exception\|assert(?:ed\|ion)?\|over.?temp\|over.?current\|under.?voltage\|retry\|retries\|unexpected\|changed\|transition(?:ed)?\|corrupt(?:ed\|ion)?)\\b', re.I) ` |
| [workspace_analysis.py:24](../workspace_analysis.py#L24) | Assign | ` INSTRUCTIONS = 'You are investigating the currently selected FFDC, not writing a generic report.\nAnswer the latest question directly. For broad findings: a 1-2 sentence conclusion, at most 5 ranked findings with short evidence/meaning/next-check bullets, then the most useful unresolved question. For focused follow-ups answer only the requested point; do not repeat the entire investigation or unrelated JIRA boilerplate.\nUse the user\'s requested ` |
| [workspace_ui.py:8](../workspace_ui.py#L8) | Assign | ` VERSION = '20261008-drop1' ` |
| [workspace_ui.py:9](../workspace_ui.py#L9) | Assign | ` MAINTENANCE_END = datetime(2026, 10, 3, 20, 0, tzinfo=ZoneInfo('Asia/Shanghai')) ` |
| [workspace_ui.py:11](../workspace_ui.py#L11) | Assign | ` WORKSPACE_NAV = (('defect', '/Defect_review?view=workspace', 'list-checks', 'Defect Review'), ('milestones', '/Current_bug_status_summary?view=workspace', 'calendar-days', 'Milestones'), ('reports', '/reports?view=workspace', 'files', 'Reports'), ('usage', '/usage-stats?view=workspace', 'chart-no-axes-combined', 'Usage')) ` |

### All Root Python print Calls

Current service startup prints are logging. Test/debug/probe scripts print their diagnostic output by design. Historical backup prints are not current production logging.

| Source | Role | Expression |
| --- | --- | --- |
| [app.py:14483](../app.py#L14483) | startup log | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.agentwork:4778](../app.py.agentwork#L4778) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.ai_work:9399](../app.py.ai_work#L9399) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.correlationwork:4932](../app.py.correlationwork#L4932) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.defect_tags_work:10124](../app.py.defect_tags_work#L10124) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.jira_monitor:8473](../app.py.jira_monitor#L8473) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.remote:9244](../app.py.remote#L9244) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.riser_work:9337](../app.py.riser_work#L9337) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [app.py.ueficlean:4932](../app.py.ueficlean#L4932) | test / historical / diagnostic output | ` print(f'FFDC Analyzer listening on http://{host}:{port}', flush=True) ` |
| [compare_ioss8312_dmesg.py:40](../compare_ioss8312_dmesg.py#L40) | test / historical / diagnostic output | ` print(node_dir.name) ` |
| [compare_ioss8312_dmesg.py:41](../compare_ioss8312_dmesg.py#L41) | test / historical / diagnostic output | ` print('  ' + ' '.join((f'{key}={value}' for key, value in counts.items()))) ` |
| [compare_ioss8312_dmesg.py:42](../compare_ioss8312_dmesg.py#L42) | test / historical / diagnostic output | ` print('  controllers=' + ', '.join((f'{key}:{value}' for key, value in controllers.most_common()))) ` |
| [compare_ioss8312_dmesg.py:43](../compare_ioss8312_dmesg.py#L43) | test / historical / diagnostic output | ` print('  disks=' + ', '.join((f'{key}:{value}' for key, value in affected.most_common(20)))) ` |
| [compare_uefi_bay_paths.py:33](../compare_uefi_bay_paths.py#L33) | test / historical / diagnostic output | ` print(f'\n=== {title} ===') ` |
| [compare_uefi_bay_paths.py:54](../compare_uefi_bay_paths.py#L54) | test / historical / diagnostic output | ` print('VROC:') ` |
| [compare_uefi_bay_paths.py:52](../compare_uefi_bay_paths.py#L52) | test / historical / diagnostic output | ` print(f'Bay {bay}: ' + (' \|\| '.join(result) if result else 'NOT PRESENT')) ` |
| [compare_uefi_bay_paths.py:58](../compare_uefi_bay_paths.py#L58) | test / historical / diagnostic output | ` print(path.relative_to(root), data.replace('\n', ' ')[:2400]) ` |
| [compare_vmd_current_values.py:27](../compare_vmd_current_values.py#L27) | test / historical / diagnostic output | ` print(f'\n=== {report_id} {path.name} ===') ` |
| [compare_vmd_current_values.py:29](../compare_vmd_current_values.py#L29) | test / historical / diagnostic output | ` print('TOP_LEVEL', list(data)[:20] if isinstance(data, dict) else type(data).__name__) ` |
| [compare_vmd_current_values.py:17](../compare_vmd_current_values.py#L17) | test / historical / diagnostic output | ` print(f'{child_path}={rendered[:1800]}') ` |
| [compare_vroc_compact.py:37](../compare_vroc_compact.py#L37) | test / historical / diagnostic output | ` print(f"\n=== {report_id} / {report.get('system', {}).get('serial', 'unknown')} ===") ` |
| [compare_vroc_compact.py:38](../compare_vroc_compact.py#L38) | test / historical / diagnostic output | ` print('EVENTS') ` |
| [compare_vroc_compact.py:28](../compare_vroc_compact.py#L28) | test / historical / diagnostic output | ` print(f'{label} [{term}]: {folded[begin:end]}') ` |
| [compare_vroc_compact.py:42](../compare_vroc_compact.py#L42) | test / historical / diagnostic output | ` print(compact(json.dumps(event, ensure_ascii=False))) ` |
| [compare_vroc_compact.py:51](../compare_vroc_compact.py#L51) | test / historical / diagnostic output | ` print('BACKPLANE_BAY', json.dumps(keep, ensure_ascii=False)) ` |
| [compare_vroc_compact.py:62](../compare_vroc_compact.py#L62) | test / historical / diagnostic output | ` print('NVMED_BAY', bay, json.dumps(keep, ensure_ascii=False)) ` |
| [compare_vroc_compact.py:64](../compare_vroc_compact.py#L64) | test / historical / diagnostic output | ` print('NVMED_BAY', bay, 'MISSING') ` |
| [compare_vroc_focus.py:28](../compare_vroc_focus.py#L28) | test / historical / diagnostic output | ` print(f"\n=== {report_id} / {report['system'].get('serial', '')} ===") ` |
| [compare_vroc_focus.py:29](../compare_vroc_focus.py#L29) | test / historical / diagnostic output | ` print('EVENTS') ` |
| [compare_vroc_focus.py:37](../compare_vroc_focus.py#L37) | test / historical / diagnostic output | ` print('BACKPLANE_BAYS', json.dumps(bays, ensure_ascii=False)) ` |
| [compare_vroc_focus.py:51](../compare_vroc_focus.py#L51) | test / historical / diagnostic output | ` print('\nNVMED_DRIVE_8_9') ` |
| [compare_vroc_focus.py:40](../compare_vroc_focus.py#L40) | test / historical / diagnostic output | ` print(f'DRIVE_BAY_{bay}', path.read_text(errors='replace')[:2200] if path.exists() else 'MISSING') ` |
| [compare_vroc_focus.py:44](../compare_vroc_focus.py#L44) | test / historical / diagnostic output | ` print(f'\n{relative}') ` |
| [compare_vroc_focus.py:33](../compare_vroc_focus.py#L33) | test / historical / diagnostic output | ` print(json.dumps(event, ensure_ascii=False)) ` |
| [compare_vroc_focus.py:55](../compare_vroc_focus.py#L55) | test / historical / diagnostic output | ` print(line[:500]) ` |
| [compare_vroc_focus.py:48](../compare_vroc_focus.py#L48) | test / historical / diagnostic output | ` print(block) ` |
| [compare_vroc_slot89.py:25](../compare_vroc_slot89.py#L25) | test / historical / diagnostic output | ` print(f'\n=== {report_id} / {root.name} ===') ` |
| [compare_vroc_slot89.py:29](../compare_vroc_slot89.py#L29) | test / historical / diagnostic output | ` print('BACKPLANES', compact(data, 6000)) ` |
| [compare_vroc_slot89.py:32](../compare_vroc_slot89.py#L32) | test / historical / diagnostic output | ` print(f'DRIVE_BAY_{bay}', compact(json.loads(path.read_text(errors='replace')), 4000) if path.exists() else 'MISSING') ` |
| [compare_vroc_slot89.py:35](../compare_vroc_slot89.py#L35) | test / historical / diagnostic output | ` print(f'\n{relative}') ` |
| [compare_vroc_slot89.py:36](../compare_vroc_slot89.py#L36) | test / historical / diagnostic output | ` print('\n'.join(matching_lines(path, ('vmd', 'nvme', 'bay 8', 'bay8', 'slot 8', 'slot8', 'port 8', 'port8', 'pcie2', 'pcie 2')))) ` |
| [deep_compare_vmd.py:25](../deep_compare_vmd.py#L25) | test / historical / diagnostic output | ` print('=== BIOS CURRENTVALUE DIFFERENCES ===') ` |
| [deep_compare_vmd.py:76](../deep_compare_vmd.py#L76) | test / historical / diagnostic output | ` print(f'\n=== {report_id} UEFI INVENTORY BAY TOPOLOGY ===') ` |
| [deep_compare_vmd.py:114](../deep_compare_vmd.py#L114) | test / historical / diagnostic output | ` print(f'\n=== {report_id} UEFI/BOOT LOG HITS ===') ` |
| [deep_compare_vmd.py:28](../deep_compare_vmd.py#L28) | test / historical / diagnostic output | ` print(f'{key}: BAD={bad_values.get(key)!r} \| GOOD={good_values.get(key)!r}') ` |
| [deep_compare_vmd.py:78](../deep_compare_vmd.py#L78) | test / historical / diagnostic output | ` print(f'BAY {bay}') ` |
| [deep_compare_vmd.py:132](../deep_compare_vmd.py#L132) | test / historical / diagnostic output | ` print('No matching UEFI/boot-log lines found.') ` |
| [deep_compare_vmd.py:80](../deep_compare_vmd.py#L80) | test / historical / diagnostic output | ` print(context[:5000]) ` |
| [deep_compare_vmd.py:125](../deep_compare_vmd.py#L125) | test / historical / diagnostic output | ` print(row) ` |
| [domain_documents.py:195](../domain_documents.py#L195) | test / historical / diagnostic output | ` print(json.dumps(output, ensure_ascii=True)) ` |
| [extract_ioss8312.py:47](../extract_ioss8312.py#L47) | test / historical / diagnostic output | ` print(f'FILES={len(all_files)}') ` |
| [extract_ioss8312.py:48](../extract_ioss8312.py#L48) | test / historical / diagnostic output | ` print(f'BYTES={sum((path.stat().st_size for path in all_files))}') ` |
| [extract_ioss8312.py:49](../extract_ioss8312.py#L49) | test / historical / diagnostic output | ` print('EXTENSIONS=' + ', '.join((f'{key}:{value}' for key, value in extensions.most_common()))) ` |
| [extract_ioss8312.py:53](../extract_ioss8312.py#L53) | test / historical / diagnostic output | ` print(path.relative_to(EXTRACT_DIR)) ` |
| [focused_uefi_vmd_evidence.py:36](../focused_uefi_vmd_evidence.py#L36) | test / historical / diagnostic output | ` print(f'\n=== {label_name} {report_id} ===') ` |
| [focused_uefi_vmd_evidence.py:58](../focused_uefi_vmd_evidence.py#L58) | test / historical / diagnostic output | ` print('ACTUAL UEFI EVENTS') ` |
| [focused_uefi_vmd_evidence.py:70](../focused_uefi_vmd_evidence.py#L70) | test / historical / diagnostic output | ` print('VROC PCIe INVENTORY') ` |
| [focused_uefi_vmd_evidence.py:40](../focused_uefi_vmd_evidence.py#L40) | test / historical / diagnostic output | ` print(f'BAY {bay}') ` |
| [focused_uefi_vmd_evidence.py:54](../focused_uefi_vmd_evidence.py#L54) | test / historical / diagnostic output | ` print(' -> '.join(levels)) ` |
| [focused_uefi_vmd_evidence.py:56](../focused_uefi_vmd_evidence.py#L56) | test / historical / diagnostic output | ` print('NOT FOUND') ` |
| [focused_uefi_vmd_evidence.py:74](../focused_uefi_vmd_evidence.py#L74) | test / historical / diagnostic output | ` print(path.relative_to(root), re.sub('\\s+', ' ', text)[:1800]) ` |
| [focused_uefi_vmd_evidence.py:68](../focused_uefi_vmd_evidence.py#L68) | test / historical / diagnostic output | ` print(path.name, one_line[:1000]) ` |
| [inspect_bay191.py:6](../inspect_bay191.py#L6) | test / historical / diagnostic output | ` print(f'==={p}===') ` |
| [inspect_bay191.py:7](../inspect_bay191.py#L7) | test / historical / diagnostic output | ` print(p.read_text(errors='ignore')) ` |
| [inspect_bay191.py:16](../inspect_bay191.py#L16) | test / historical / diagnostic output | ` print(f'==={p}===') ` |
| [inspect_bay191.py:19](../inspect_bay191.py#L19) | test / historical / diagnostic output | ` print(text[:20000]) ` |
| [inspect_bay191.py:21](../inspect_bay191.py#L21) | test / historical / diagnostic output | ` print('missing') ` |
| [inspect_bios_vmd.py:28](../inspect_bios_vmd.py#L28) | test / historical / diagnostic output | ` print('\n===', report_id, '===') ` |
| [inspect_bios_vmd.py:16](../inspect_bios_vmd.py#L16) | test / historical / diagnostic output | ` print(child_path, '=', json.dumps(child, ensure_ascii=False)) ` |
| [inspect_bios_vmd.py:18](../inspect_bios_vmd.py#L18) | test / historical / diagnostic output | ` print(child_path, '=', json.dumps(child, ensure_ascii=False)[:1200]) ` |
| [inspect_ioss8312.py:83](../inspect_ioss8312.py#L83) | test / historical / diagnostic output | ` print(json.dumps({'archive': filename, 'archive_bytes': target.stat().st_size, 'integrity': 'ok' if test.returncode == 0 else 'failed', 'file_count': len(files), 'uncompressed_bytes': total_size, 'interesting_count': len(interesting), 'inte ` |
| [inspect_vmd_values.py:7](../inspect_vmd_values.py#L7) | test / historical / diagnostic output | ` print('\n===', report_id, '===') ` |
| [inspect_vmd_values.py:14](../inspect_vmd_values.py#L14) | test / historical / diagnostic output | ` print(relative) ` |
| [inspect_vmd_values.py:11](../inspect_vmd_values.py#L11) | test / historical / diagnostic output | ` print(relative, 'MISSING') ` |
| [inspect_vmd_values.py:17](../inspect_vmd_values.py#L17) | test / historical / diagnostic output | ` print(token, 'hits', len(matches)) ` |
| [inspect_vmd_values.py:21](../inspect_vmd_values.py#L21) | test / historical / diagnostic output | ` print(re.sub('\\s+', ' ', text[begin:end])) ` |
| [map_ioss8312_failures.py:38](../map_ioss8312_failures.py#L38) | test / historical / diagnostic output | ` print(node_dir.name) ` |
| [map_ioss8312_failures.py:36](../map_ioss8312_failures.py#L36) | test / historical / diagnostic output | ` print(f'{node_dir.name}: no runtime timeout/abort sequence') ` |
| [map_ioss8312_failures.py:48](../map_ioss8312_failures.py#L48) | test / historical / diagnostic output | ` print(f"  host={host} target={target} controller={sorted(details['controllers'])} disk={sorted(details['disks'])} abort={details['abort']} timeout={details['timeout']} soft={details['soft']} {mapping}") ` |
| [patch_defect_review_brand_link.py:15](../patch_defect_review_brand_link.py#L15) | test / historical / diagnostic output | ` print('Updated 3 Defect Review brand links') ` |
| [patch_jira_attachment_ocr.py:306](../patch_jira_attachment_ocr.py#L306) | test / historical / diagnostic output | ` print(f'patched {APP}') ` |
| [summarize_ioss8312.py:32](../summarize_ioss8312.py#L32) | test / historical / diagnostic output | ` print(f'NODE {node}') ` |
| [summarize_ioss8312.py:59](../summarize_ioss8312.py#L59) | test / historical / diagnostic output | ` print('  TOTAL ' + ' '.join((f'{key}={value}' for key, value in node_totals.items()))) ` |
| [summarize_ioss8312.py:51](../summarize_ioss8312.py#L51) | test / historical / diagnostic output | ` print(f"  HBA{hba} slot={field(show, 'PCI Slot Number') or '?'} sas={field(show, 'SAS Address') or '?'} fw={field(show, 'Package Version') or '?'} drv={field(show, 'Driver Version') or '?'} pd={field(show, 'PD Drive Count') or '?'} encl={fi ` |
| [summarize_ioss8312_snapdumps.py:37](../summarize_ioss8312_snapdumps.py#L37) | test / historical / diagnostic output | ` print(f'{node} {hba} {archive.name}') ` |
| [summarize_ioss8312_snapdumps.py:38](../summarize_ioss8312_snapdumps.py#L38) | test / historical / diagnostic output | ` print(f"  type={snap_type or '?'}") ` |
| [summarize_ioss8312_snapdumps.py:39](../summarize_ioss8312_snapdumps.py#L39) | test / historical / diagnostic output | ` print(f"  fault={fault or '?'}") ` |
| [summarize_ioss8312_snapdumps.py:40](../summarize_ioss8312_snapdumps.py#L40) | test / historical / diagnostic output | ` print(f"  package={package or '?'}") ` |
| [summarize_ioss8312_snapdumps.py:41](../summarize_ioss8312_snapdumps.py#L41) | test / historical / diagnostic output | ` print(f"  reason={reason or '?'}") ` |
| [v4_batch_validate.py:163](../v4_batch_validate.py#L163) | test / historical / diagnostic output | ` print(out_txt) ` |
| [v4_batch_validate.py:164](../v4_batch_validate.py#L164) | test / historical / diagnostic output | ` print(out_csv) ` |
| [v4_batch_validate.py:165](../v4_batch_validate.py#L165) | test / historical / diagnostic output | ` print(out_json) ` |
| [v4_batch_validate.py:124](../v4_batch_validate.py#L124) | test / historical / diagnostic output | ` print(f'[{idx}/{len(files)}] analyzing {f.name}', flush=True) ` |
| [vision_capability_test.py:26](../vision_capability_test.py#L26) | test / historical / diagnostic output | ` print('RESULT=accepted') ` |
| [vision_capability_test.py:27](../vision_capability_test.py#L27) | test / historical / diagnostic output | ` print('TEXT=' + str(app.extract_response_text(data)).replace('\n', ' ')[:200]) ` |
| [vision_capability_test.py:29](../vision_capability_test.py#L29) | test / historical / diagnostic output | ` print('RESULT=rejected') ` |
| [vision_capability_test.py:30](../vision_capability_test.py#L30) | test / historical / diagnostic output | ` print('ERROR=' + str(exc).replace('\n', ' ')[:500]) ` |

### Exact Normalized Function-Body Duplicates

| File | Function names and lines |
| --- | --- |
| app.py.ai_work | jira_image_ocr_cache_key:4522, jira_log_archive_cache_key:4697 |
| app.py.defect_tags_work | jira_image_ocr_cache_key:4784, jira_log_archive_cache_key:4959 |
| app.py.remote | jira_image_ocr_cache_key:4430, jira_log_archive_cache_key:4605 |
| app.py.riser_work | jira_image_ocr_cache_key:4522, jira_log_archive_cache_key:4697 |

