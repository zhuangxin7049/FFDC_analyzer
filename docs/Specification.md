# FFDC Analyzer: Technical Specification

## Contract and Scope

Baseline: local source read on 2026-09-14. The application has a hand-written HTTP router, dynamically shaped Python dictionaries, and no published OpenAPI specification or static type contract. The API reference below distinguishes declared types from conservative AST inferences; an unannotated argument is not assigned an invented strict type.

All module-level functions and directly declared class methods in the four runtime modules are indexed, including constructors and private helpers. Nested implementation helpers are not public API; inherited standard-library methods are described by their base classes rather than duplicated. Auxiliary scripts and tests are separately indexed in AuditInventory; historical application copies are not current public APIs.

## Main HTTP Request/Response Models

| Operation | Request | Response / behavior |
| --- | --- | --- |
| `POST /workspace-chat` | JSON: `message`, optional `history` of `{role, content}` | `{answer, answer_html, model, analysis, issue, report}`; or additionally `ffdc_job_id` and progress `message` while JIRA attachments are retrieved. |
| `POST /workspace-report-chat` | JSON: `id`, `message`, optional `history` | Same conversation envelope, scoped to a validated selected report. A different explicit Bug key clears previous history. |
| `POST /workspace-upload-start` | Multipart `ffdc`, positive Content-Length, at most 1 GiB total body | `{job_id}`. Poll `/api/workspace-upload-job?id=...`; keep the current conversation open. |
| `POST /workspace-jira-download-start` | URL-encoded `issue` | `{job_id}` using server PAT; explicit username/password fields are rejected by this endpoint. |
| `GET /api/workspace-report` | Query `id` | `{report}` with ID, file, URL, collection/report timestamp, Bug metadata, attachment count. |
| `GET /api/workspace-evidence` | Query `id`, relative `path`, `start` (default 1), `count` (default 40) | `{path, lines:[{line,text,text_truncated}], scan_byte_limit, file_exceeds_scan_limit}`; path containment and supported-text checks apply. |
| `POST /similar-jira-cases` | JSON `id` | Requires a JIRA-linked report; saves result into report and returns `{status, case_count}`. A standalone upload gets 403. |
| `POST /defect-similar-jira-cases` | JSON `job`, `issue` | Refreshes and persists that review item's related cases; conflict while saving can return 409. |
| `POST /jira-comment` | Form: `id`, `issue`, `comment`, user `username`/`password` or valid JIRA session | Actual JIRA comment write, followed by 303 redirect or HTML result. Server PAT is not the intended identity for this write. |
| `POST /Defect_review_start` | Form `username`, `password` | Starts manual full review and returns `{job_id}`. |
| `POST /current-bug-status-summary-start` | No meaningful body | Starts current summary; may refresh Project Tool data and update saved JIRA filter. |

JSON/form helpers reject bodies above 128 KiB. Workspace HTTP routing checks 16,000 message characters, but `workspace_chat_response` enforces 12,000; a message between these limits currently reaches a generic error handler instead of a consistently classified validation response. Workspace chat concurrency is capped at four. The two workspace chat routes return 429 when that semaphore is unavailable.

Responses are not streamed token-by-token. Upload and JIRA analysis jobs are polled; model answers arrive as complete JSON responses. `answer_html` is provided for compatibility, while the new browser renderer uses `answer` and its controlled Markdown token renderer.

## Evidence Tool Contracts

| Tool | Arguments | Result / limits |
| --- | --- | --- |
| `list_logs` | `contains=''`, `offset=0` | 80 text-file entries per page; `next_offset`, `available`. |
| `search_logs` | `terms` (1-6 nonempty strings, each <=160 characters), optional relative `path` | Literal case-insensitive OR search; at most 40 results, 400 files, 32 MiB accumulated scan; `limited` flag. |
| `read_log` | `path`, `start`, `count=60` | Up to 100 lines, each displayed up to 1,200 characters; source scan limited to 32 MiB. |
| `triage_ffdc` | `focus='all'` or storage/pcie/network/firmware/system | Failure-keyword candidates with paths/lines; not validated root causes. |
| `read_report_section` | `section`, `offset=0` | Workspace-only; list sections paged by 20 records, then compacted; `total`, `next_offset`. |
| `get_jira_issue` | `key` | Validated Bug key; live title/description/status/assignee/update and recent comments; no attachment retrieval in this tool itself. |
| `search_jira` | `jql` (<=2,000 characters) | Read-only search, at most 8 issues returned; does not save a filter. |
| `search_project_milestones` | `query=''`, optional `within_days`, `limit=12` | Search latest completed local project snapshot, with source timestamp; not a direct Project Tool refresh. |

Schemas are enabled only when the required root/callback/context is available. `execute` checks the active allowlist and redacts results. The base triage collects up to three matches per category; workspace triage instead distributes a 512 KiB per-file budget across at most 240 files, up to 12 MiB total, retains four candidates per category, and prepares at most eight contextual excerpts. These are separate implementations, not interchangeable settings.

## AI Models and Prompt Locations

| Feature | Model selection in inspected source | Prompt / implementation |
| --- | --- | --- |
| Standard AI report | Configured model returned by `load_ai_config`; code fallback `gpt-5.2` | `build_ai_analysis_prompt`, `generate_ai_analysis`, `app.py:10530`, `10710`. JIRA-linked analysis first builds a relevance evidence brief. |
| Deep Investigation | `FFDC_DEEP_INVESTIGATION_MODEL`, default `nemotron-3-ultra` | `build_agent_analysis_prompt`, `generate_agent_analysis`, `app.py:11068`, `11158`; placeholder retry, then evidence-based deterministic fallback if still placeholder. |
| Classic report chat and Defect Review assistant | `FFDC_CHAT_MODEL`, default `nemotron-3-ultra` | `call_evidence_chat`, `app.py:11295`; conversational policy in `ffdc_chat.run_chat`. |
| New workspace conversation | Nonempty `FFDC_WORKSPACE_CHAT_MODEL`, otherwise `CHAT_MODEL`, otherwise configured model | Same evidence loop plus `workspace_analysis.INSTRUCTIONS` at line 19. |
| Defect Review per-Bug evidence and final review | Configured model through `call_ai_prompt` | `build_jira_monitor_evidence_prompt`, `build_jira_monitor_review_prompt`, `generate_jira_monitor_ai_summary`, `app.py:7790`, `7820`, `7862`. |
| Similar Bug assessment | Configured model through `call_ai_prompt`; not hardcoded to an earlier screenshot's model | `davy_rank_similar_jira_cases`, `app.py:6152`. It receives retrieved candidates and selects at most three in the requested table format. |
| Milestone risk narrative | Configured model through `call_ai_prompt` | `build_schedule_risk_ai_prompt`, `generate_schedule_risk_ai_summary`, `app.py:7893`, `7960`. |
| JIRA screenshot interpretation | `FFDC_VISION_MODEL`, default `gemma-4-31b-it` | `_call_ai_vision_once`, `app.py:10652`; up to 1,200 output tokens, temperature 0.1, then OCR fallback through `jira_image_comment`. |

These are **source defaults and selection rules**, not verification that these model IDs are currently served by Davy. The file loader can override the text model and base URL. A function named `call_openai_chat` does not imply a particular hosted provider: it sends to the configured base URL.

`_call_ai_prompt_once` first tries `/responses` for non-Davy base URLs; selected unsupported-request HTTP statuses (400/404/405) fall back to `/chat/completions`. Davy URLs go directly to chat completions. The interactive tool loop also uses chat completions. General prompt calls retry recognized transient failures up to three attempts; workspace completion separately retries HTTP 502/503/504 once. These retry policies are not a single shared global policy.

## Configuration Precedence

`load_ai_config` starts with environment/code defaults, then reads the AI key file. A URL found in that file overrides the base URL; labelled model lines override the model. Per-feature `model_override` and workspace/chat variables can override that configured text model later. Missing key files raise an explicit error; setting only a base URL is insufficient.

`load_jira_monitor_schedule_config` starts disabled, takes username/password defaults from environment, and then merges a JSON dictionary from its configured file. It normalizes `times` into HH:MM strings. Its validation checks the format but does not fully validate hour/minute ranges. Project Tool credentials prefer dedicated project credentials, then scheduled JIRA credentials, then function fallbacks.

No `argparse`/Click CLI is declared for `app.py`. `main()` takes no CLI parameters; host, port, credentials and model selections are configured through environment/files. Auxiliary scripts are a separate interface and often contain hardcoded diagnostic paths.

### Scheduler JSON Fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Enables the configured scheduler. Use a JSON boolean; a string is normalized with Python truthiness rather than strict boolean parsing. |
| `username` | string | `FFDC_JIRA_MONITOR_USERNAME` or empty | Scheduled JIRA identity. |
| `password` | string, secret | `FFDC_JIRA_MONITOR_PASSWORD` or empty | Scheduled JIRA credential. |
| `times` | list of strings or delimited string | `["05:00", "13:00"]` | Host-local schedule times; only literal 05:00 gets full-refresh flags in the normal loop. |
| `project_tool_username` | string | empty | Dedicated Project Tool identity; falls back to scheduled JIRA username. |
| `project_tool_password` | string, secret | empty | Dedicated Project Tool credential; falls back to scheduled JIRA password. |

### Network Destinations

| Destination pattern | Trigger | Operation / credential |
| --- | --- | --- |
| `{JIRA_BASE_URL}/rest/api/2/issue/{key}` and `/comment` | Bug lookup, review, comments | GET evidence; explicit comment POST is a write. Read identity depends on route; comment uses user login/session. |
| `{JIRA_BASE_URL}/rest/api/2/search` | Filter/related-case/tool searches | GET JQL results with bounded/page-specific limits. |
| `{JIRA_BASE_URL}/rest/api/2/filter/{id}` | Review and summary | GET filter; PUT when summary adds valid project clauses. |
| JIRA CSV export URL built by `jira_export_current_fields_csv` | Current status summary | Export current fields under scheduled/user identity. |
| Attachment `content`/`self` or extracted FFDC link | Bug/report analysis | Download bytes. PAT forwarding is restricted to the JIRA origin for the server-PAT path. |
| `{PROJECT_TOOL_BASE_URL}/?next=/projects/` and URLs built by project helpers | Tracker and milestone refresh | Cookie/CSRF login followed by authenticated requests. |
| `{configured AI base}/responses` | Non-Davy generic prompt path | POST text evidence; compatible-error fallback to chat completions. |
| `{configured AI base}/chat/completions` | Davy prompt, chat, vision | POST context/tool definitions or image payload using server API credential. |

The configured JIRA default is `https://jira1.labs.lenovo.com`; Project Tool defaults to `https://project-tool.labs.lenovo.com`. A private attachment download host is data-derived, not a fixed provider. Outbound permission and destination validation must be reviewed separately from whether a token is forwarded.

## Core Data Structures

| Structure | Fields / semantics |
| --- | --- |
| Parsed report | `id`, `created_at`, `source_file`, `format`, `files`, `system`, `firmware`, `fru`, `events`, `pci`, `sep_info`, `sep_vpd`, `system_config`; added evidence modules include `flash_mctp`, `raid_tty`, `uefi_boot`, `pldm_updates`, `bmc_inband_fw`, `cff_pcie`, `network`, `backplane_scope`, `automated_checks`. Fields vary with classic/V4/JIRA-only report type. |
| File map | `files` maps KEY_PATHS category to relative extracted file path or the string `missing`; absence is not a fault diagnosis. |
| Automated check | `severity`, `category`, `title`, `conclusion`, `evidence`, built by `add_check`; generated parser observations may need corroboration. |
| Backplane scope | `scope` = `external_storage` or `built_in_backplane`; `applicable`, `reason`, `external_adapters`, `excluded_evidence`. |
| Network evidence | `adapters`, `interfaces`, `events`, `log_sources`; bounded parsing of observed inventory/logs, not active probing. |
| Inband firmware evidence | `attempts`, `events`, `log_sources`; missing terminal event is distinct from observed failure. |
| JIRA report context | `jira` records Bug ID, attachment, attachment count and `issue_context`; live conversational issue data may be added in a copy as `live_issue`. |
| Similar cases | `status`, `generated_at`, `terms`, `cases`, optional `davy`; deterministic rows include `key`, `summary`, `status`, `priority`, `assignee`, `updated`, `score`, `similarity`, `matching_evidence`. Model assessment has its own status/content/model or error. |
| AI report / investigation | `status` such as `ok`, `error`, `unavailable`, `model`, `generated_at`, `content`, optional `error`; deep investigation also records task/tool summaries. |
| Background job | `id`, `status`, `percent`, `message`, `created`, `updated` and operation-specific result fields. Most worker state uses `running`, `done`, `error`; exact schemas are dynamic. |
| Review item | Bug title/state/assignee/severity/priority, comments, reproduction and closure fields, FFDC reports/errors, attachment evidence, AI review, similar cases, optional schedule risk. |
| Review snapshot | `issues`, `schedule_risks`, `milestone_status`, `schedule_ai_summary`, refresh flags, morning source IDs, result URL and version markers. |
| Workspace answer | `answer`, `answer_html`, `model`, `analysis`, `issue`, `report`; asynchronous Bug retrieval additionally carries `ffdc_job_id`. |
| Analysis trace | `sources`, `scan`, `tool_calls`, `elapsed_seconds`, `citation_check`, `model`. Source kinds include `log`, `report`, `jira`, `projects`. |
| Browser conversation | `messages`, `report`, `reports`, `issue`, `analysis`, `pending`; sessionStorage retains up to 24 messages; requests use the last eight scoped messages. |

## Persistence and Side Effects

| Target / action | Trigger and mode | Implementation |
| --- | --- | --- |
| `uploads/` | Multipart/download writes in binary mode; cleanup retains newest 10 files by mtime. | `stream_multipart_upload`, `jira_download_attachment`, `cleanup_uploads`. |
| `reports/<id>/` | Create directory, write `ffdc.tar`, extracted files, UTF-8 `report.json`; AI/similar/comment metadata can rewrite JSON. | `analyze`, route handlers, JIRA and AI workers. |
| Reports retention | On analysis/review cleanup, remove directories older than 30 days except protected IDs. Not a continuous daily deletion job. | `cleanup_reports`. |
| All reports deletion | `/clear-reports` deletes all report directories, not just browser recent history. | `clear_reports`; no route-level login check in inspected handler. |
| `ffdc_cache/` | Read/write cached JIRA report data and supporting payloads; restoration can recreate a report directory. | `load_cached_jira_ffdc_report`, `save_cached_jira_ffdc_report`, restoration helpers. |
| Image/archive caches | Reuse interpretation JSON; temporary downloaded images and log archives are removed in cleanup paths. | `jira_image_comment`, `jira_log_archive_evidence`. |
| `jira_monitor_jobs/` | JSON job snapshots, latest pointer, schedule state, retry data. | `persist_jira_monitor_job`, `save_jira_monitor_schedule_state`. |
| `current_status_summary/` | Current fields/tracker snapshot and latest pointer. | `persist_current_status_summary_job`. |
| `project_milestone_tracker.json` | Read/write cached project milestone rows. | `load_milestone_cache`, `save_milestone_cache`. |
| `usage_stats.json` | GET-request usage aggregation; prune days older than 30 during write flow. Client identifier is hashed, not a registered account. | `record_usage`, `prune_usage_stats`. |
| Browser storage | Conversation in sessionStorage, recent metadata in localStorage; clear-recent removes only the local list. | `static/workspace.js:6-29`, `294-306`. |
| JIRA REST | Reads issues/filter/comments/attachments, throttles requests; comment POST uses user credentials. Summary refresh may also PUT an updated saved filter. | JIRA request helpers, `jira_post_comment`, `jira_save_filter_jql`. |
| AI API | JSON POST to configured API with server credential and report/JIRA/image evidence; timeout 60 seconds per `post_json`. | `post_json`, prompt/vision/conversation callers. |
| Project Tool | Login with cookie jar/CSRF token, read custom report/project milestone endpoints; local cache can be written. | `project_tool_login` and related functions. |
| Processes | Launch `lzop`, `zstd`, `tar`, `7z`, `tesseract`; no arbitrary shell command exposed as a conversation tool. | `unpack_ffdc`, JIRA archive/OCR helpers. |
| Threads/global state | Worker daemon threads; dictionaries, locks, semaphores and analysis counters are shared within one server process. | `start_*_job`, `main`, scheduler loop. |

On import, the main module evaluates environment defaults and regular expressions, creates locks/semaphores and global dictionaries, and creates unverified TLS contexts. The `main()` guard prevents HTTP server startup merely from importing `app`. No production database or cross-process job queue is implemented. In-memory JIRA sessions hold user credentials until expiry/cleanup; they are not persistent user accounts.

There is no backend browser automation in the four runtime modules. Browser navigation, report popups, clipboard actions, state clearing and cancellation of waiting occur in client JavaScript. Presentation/video scripts in `deliverables/` use different tooling and must not be confused with the deployed analyzer.

<!-- GENERATED REFERENCE -->

## Complete HTTP Route Index

This index is derived from all path-condition branches in `Handler`. Method and path matching are case-sensitive. Most POST branches compare the full `self.path`, so appending query parameters is not generally equivalent to the same path without a query; `/clear-reports` is handled differently.

| Method | Path | Input keys observed | Delegated handlers / response operations | Source |
| --- | --- | --- | --- | --- |
| GET | /static/ | path prefix /static/&lt;filename&gt; | self.send_response | [app.py:13626](../app.py#L13626) |
| GET | / | None observed in query/form/JSON; inspect route body | render_workspace_page, self.send_html | [app.py:13639](../app.py#L13639) |
| GET | /new-version | None observed in query/form/JSON; inspect route body | render_workspace_page, self.send_html | [app.py:13639](../app.py#L13639) |
| GET | /old-version | None observed in query/form/JSON; inspect route body | index_page, self.send_html | [app.py:13641](../app.py#L13641) |
| GET | /api/workspace-evidence | count, id, path, start | load_workspace_report, self.send_json, workspace_report_summary | [app.py:13643](../app.py#L13643) |
| GET | /api/workspace-report | id | load_workspace_report, self.send_json, workspace_report_summary | [app.py:13643](../app.py#L13643) |
| GET | /Defect_review | None observed in query/form/JSON; inspect route body | render_jira_monitor_page, self.send_html | [app.py:13659](../app.py#L13659) |
| GET | /Current_bug_status_summary | job, start | get_current_status_summary_job, get_latest_current_status_summary_job, render_current_status_summary, render_current_status_summary_loading, render_jira_monitor_page, self.send_html, start_current_status_summary_job | [app.py:13661](../app.py#L13661) |
| GET | /reports | cleared | esc, render_table, self.send_html | [app.py:13686](../app.py#L13686) |
| GET | /report | auto_similar, defect_issue, from_defect_job, from_jira_job, id | index_page, render_report, restore_cached_jira_ffdc_report_by_id, self.send_html | [app.py:13705](../app.py#L13705) |
| GET | /api/report | id | self.send_json | [app.py:13729](../app.py#L13729) |
| GET | /download-ai-report | id | index_page, self.send_html, self.send_response | [app.py:13736](../app.py#L13736) |
| GET | /download-summary | id | build_system_summary_text, index_page, self.send_html, self.send_response | [app.py:13759](../app.py#L13759) |
| GET | /download-tar | id | index_page, self.send_html, self.send_response | [app.py:13773](../app.py#L13773) |
| GET | /download-current-bug-status-csv | job | build_current_status_summary_csv, get_current_status_summary_job, index_page, safe_current_status_summary_job_id, self.send_html, self.send_response | [app.py:13786](../app.py#L13786) |
| GET | /download-current-bug-status-xlsx | job | build_current_status_summary_xlsx, get_current_status_summary_job, index_page, safe_current_status_summary_job_id, self.send_html, self.send_response | [app.py:13802](../app.py#L13802) |
| GET | /api/jira-job | id | get_jira_job, self.send_json | [app.py:13821](../app.py#L13821) |
| GET | /api/workspace-upload-job | id | get_workspace_upload_job, self.send_json | [app.py:13829](../app.py#L13829) |
| GET | /api/defect-review-job | id | get_jira_monitor_job, self.send_json | [app.py:13836](../app.py#L13836) |
| GET | /api/current-bug-status-summary-job | id | get_current_status_summary_job, self.send_json | [app.py:13843](../app.py#L13843) |
| GET | /api/agent-job | id | get_agent_job, self.send_json | [app.py:13850](../app.py#L13850) |
| GET | /jira-results | job, view | get_jira_job, index_page, reconstruct_jira_job_from_reports, render_jira_results, render_workspace_subpage, self.send_html, self.send_response | [app.py:13857](../app.py#L13857) |
| GET | /Defect_review_result | job | get_jira_monitor_job, index_page, render_jira_monitor_result, self.send_html | [app.py:13879](../app.py#L13879) |
| GET | /Defect_review_similar | auto_similar, issue, job | get_defect_review_issue, get_jira_monitor_job, index_page, render_defect_review_similar_page, self.send_html | [app.py:13892](../app.py#L13892) |
| GET | /Defect_review_ffdcs | current, issue, job | get_jira_monitor_job, index_page, reconstruct_defect_job_from_report, render_jira_monitor_ffdc_list, self.send_html | [app.py:13911](../app.py#L13911) |
| GET | /usage-stats | None observed in query/form/JSON; inspect route body | render_usage_stats_page, self.send_html | [app.py:13926](../app.py#L13926) |
| GET | /sample | None observed in query/form/JSON; inspect route body | analyze_with_capacity, index_page, self.send_html, self.send_response | [app.py:13928](../app.py#L13928) |
| POST | /workspace-domain-author | domain, message, token | acquire_workspace_chat_slot, domain_author_response, get_author_session, read_domain_author_request, release_workspace_chat_slot, self.send_json | [app.py:13947](../app.py#L13947) |
| POST | /clear-reports | view | add_workspace_view, clear_reports, self.send_response | [app.py:13979](../app.py#L13979) |
| POST | /workspace-chat | history, message | acquire_workspace_chat_slot, authoring_mention, get_author_session, get_jira_session, release_workspace_chat_slot, self.read_json_body, self.send_json, workspace_chat_response | [app.py:13988](../app.py#L13988) |
| POST | /workspace-report-chat | history, id, message, previous_sources | acquire_workspace_chat_slot, get_jira_session, release_workspace_chat_slot, self.read_json_body, self.send_json, workspace_chat_response | [app.py:14031](../app.py#L14031) |
| POST | /workspace-author-login | password, username | create_author_session, jira_request_json, self.read_json_body, self.send_json, self.send_response | [app.py:14066](../app.py#L14066) |
| POST | /workspace-jira-login | issue, password, username | create_jira_session, jira_request_json, self.read_json_body, self.send_json, self.send_response | [app.py:14087](../app.py#L14087) |
| POST | /chat | history, id, message | call_openai_chat, render_workspace_chat_markdown, self.read_json_body, self.send_json | [app.py:14108](../app.py#L14108) |
| POST | /similar-jira-cases | id | search_similar_jira_cases, self.read_json_body, self.send_json | [app.py:14133](../app.py#L14133) |
| POST | /defect-similar-jira-cases | issue, job | build_defect_review_similar_report, get_defect_review_issue, get_jira_monitor_job, persist_defect_review_similar_cases, safe_jira_monitor_job_id, search_similar_jira_cases, self.read_json_body, self.send_json | [app.py:14158](../app.py#L14158) |
| POST | /defect-review-chat | history, job, message | backfill_jira_monitor_defect_actions, backfill_jira_monitor_health, backfill_jira_monitor_labels, backfill_jira_monitor_priorities, backfill_jira_monitor_schedule_risks, call_defect_review_chat, get_jira_monitor_job, render_chat_markdown, self.read_json_body, self.send_json | [app.py:14182](../app.py#L14182) |
| POST | /jira-comment | comment, id, issue, password, username | get_jira_session, index_page, jira_post_comment, self.read_form, self.send_html, self.send_response | [app.py:14213](../app.py#L14213) |
| POST | /jira-download-start | issue, password, username | create_jira_session, self.send_json, self.send_response, start_jira_job | [app.py:14251](../app.py#L14251) |
| POST | /workspace-jira-download-start | issue, password, username | get_jira_session, self.read_form, self.send_json, start_jira_job | [app.py:14274](../app.py#L14274) |
| POST | /workspace-upload-start | multipart field ffdc; Content-Length | self.send_json, start_workspace_upload_job, stream_multipart_upload | [app.py:14298](../app.py#L14298) |
| POST | /Defect_review_start | password, username | self.read_form, self.send_json, start_jira_monitor_job | [app.py:14318](../app.py#L14318) |
| POST | /current-bug-status-summary-start | None observed in query/form/JSON; inspect route body | self.send_json, start_current_status_summary_job | [app.py:14328](../app.py#L14328) |
| POST | /agent-analysis-start | id | self.read_form, self.send_json, start_agent_job | [app.py:14334](../app.py#L14334) |
| POST | /generate-ai-report | id | generate_ai_analysis, index_page, self.read_form, self.send_html, self.send_response | [app.py:14343](../app.py#L14343) |
| POST | /agent-analysis | id | generate_agent_analysis, index_page, self.read_form, self.send_html, self.send_response | [app.py:14360](../app.py#L14360) |
| POST | /jira-download | issue, password, username | analyze_with_capacity, cleanup_uploads, create_jira_session, esc, index_page, jira_download_ffdcs, self.send_html, self.send_response, update_report_jira_context | [app.py:14377](../app.py#L14377) |
| POST | /upload | multipart field ffdc; Content-Length | Legacy multipart upload; analyze_with_capacity; redirect 303 to report. The router rejects all other unmatched POST paths. | [app.py:14430](../app.py#L14430) |

## Complete Environment Variable Index

Defaults are code expressions, not values read from an administrator's deployed secret files. Most variables are read on module import; file loader variables are read at call time.

| Configuration key | Type | Code default / precedence | Purpose | Source |
| --- | --- | --- | --- | --- |
| FFDC_CHAT_MODEL | environment string; parsed by caller | ` 'nemotron-3-ultra' ` | Default evidence conversation model. | [app.py:76](../app.py#L76) |
| FFDC_DEEP_INVESTIGATION_MODEL | environment string; parsed by caller | ` 'nemotron-3-ultra' ` | Model used by the deep investigation stages. | [app.py:72](../app.py#L72) |
| FFDC_DEFECT_REVIEW_EMAIL_TO | environment string; parsed by caller | ` 'RAIDAsia@LenovoBeijing.onmicrosoft.com' ` | Recipient shown in the review email drafting workflow; not an SMTP account. | [app.py:163](../app.py#L163) |
| FFDC_HOST | environment string; parsed by caller | ` '0.0.0.0' ` | HTTP bind address read in main. | [app.py:14481](../app.py#L14481) |
| FFDC_JIRA_MONITOR_FILTER_ID | environment string; parsed by caller | ` '34570' ` | Saved defect filter used by reviews and current status export. | [app.py:161](../app.py#L161) |
| FFDC_JIRA_MONITOR_PASSWORD | environment string; parsed by caller | ` '' ` | Scheduled JIRA password fallback; JSON can override it; never log. | [app.py:5493](../app.py#L5493) |
| FFDC_JIRA_MONITOR_USERNAME | environment string; parsed by caller | ` '' ` | Scheduled JIRA username fallback; JSON can override it. | [app.py:5492](../app.py#L5492) |
| FFDC_OPENAI_BASE_URL | environment string; parsed by caller | ` 'https://api.openai.com/v1' ` | Base AI API URL; a URL in the key file takes precedence. | [app.py:10780](../app.py#L10780) |
| FFDC_OPENAI_MODEL | environment string; parsed by caller | ` 'gpt-5.2' ` | Base text model; key-file model and per-feature overrides can take precedence. | [app.py:70](../app.py#L70) |
| FFDC_OPENAI_MODEL | environment string; parsed by caller | ` OPENAI_MODEL ` | Base text model; key-file model and per-feature overrides can take precedence. | [app.py:10781](../app.py#L10781) |
| FFDC_PORT | environment string; parsed by caller | ` '8088' ` | HTTP listening port converted to integer in main. | [app.py:14482](../app.py#L14482) |
| FFDC_UPCOMING_MILESTONE_REPORT_ID | environment string; parsed by caller | ` '562' ` | Project Tool custom report ID used to identify tracker projects. | [app.py:172](../app.py#L172) |
| FFDC_VISION_MODEL | environment string; parsed by caller | ` 'gemma-4-31b-it' ` | Model used for supported screenshot images before OCR fallback. | [app.py:10963](../app.py#L10963) |
| FFDC_WORKSPACE_CHAT_MODEL | environment string; parsed by caller | ` '' ` | Optional new-workspace-specific override; empty falls back to CHAT_MODEL. | [app.py:88](../app.py#L88) |

## Module Constants and Shared State

The full assignment index includes configuration, regular expressions, protocol tables and mutable job state. Long default expressions are summarized instead of reproducing HTML/prompts verbatim. These constants have no stable external configuration schema unless exposed through an environment variable or file loader.

### `app.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |
| BASE_DIR | Attribute expression | ` Path(__file__).resolve().parent ` | base dir; module-level state/definition, not necessarily user-configurable. | [app.py:50](../app.py#L50) |
| DOMAIN_AUTHORING | Call expression | ` DomainAuthoring(BASE_DIR / 'domain_drafts') ` | domain authoring; module-level state/definition, not necessarily user-configurable. | [app.py:51](../app.py#L51) |
| UPLOAD_DIR | BinOp expression | ` BASE_DIR / 'uploads' ` | upload dir; module-level state/definition, not necessarily user-configurable. | [app.py:52](../app.py#L52) |
| REPORT_DIR | BinOp expression | ` BASE_DIR / 'reports' ` | report dir; module-level state/definition, not necessarily user-configurable. | [app.py:53](../app.py#L53) |
| FFDC_CACHE_DIR | BinOp expression | ` BASE_DIR / 'ffdc_cache' ` | FFDC cache dir; module-level state/definition, not necessarily user-configurable. | [app.py:54](../app.py#L54) |
| JIRA_OCR_CACHE_DIR | BinOp expression | ` BASE_DIR / 'jira_ocr_cache' ` | JIRA ocr cache dir; module-level state/definition, not necessarily user-configurable. | [app.py:55](../app.py#L55) |
| JIRA_ATTACHMENT_CACHE_DIR | BinOp expression | ` BASE_DIR / 'jira_attachment_cache' ` | JIRA attachment cache dir; module-level state/definition, not necessarily user-configurable. | [app.py:56](../app.py#L56) |
| JIRA_MONITOR_JOB_DIR | BinOp expression | ` BASE_DIR / 'jira_monitor_jobs' ` | JIRA monitor job dir; module-level state/definition, not necessarily user-configurable. | [app.py:57](../app.py#L57) |
| CURRENT_STATUS_SUMMARY_DIR | BinOp expression | ` BASE_DIR / 'current_status_summary' ` | current status summary dir; module-level state/definition, not necessarily user-configurable. | [app.py:58](../app.py#L58) |
| STATIC_DIR | BinOp expression | ` BASE_DIR / 'static' ` | static dir; module-level state/definition, not necessarily user-configurable. | [app.py:59](../app.py#L59) |
| USAGE_STATS_FILE | BinOp expression | ` BASE_DIR / 'usage_stats.json' ` | usage stats file; module-level state/definition, not necessarily user-configurable. | [app.py:60](../app.py#L60) |
| USAGE_STATS_LOCK | Call expression | ` threading.Lock() ` | usage stats lock; module-level state/definition, not necessarily user-configurable. | [app.py:61](../app.py#L61) |
| USAGE_STATS_RETENTION_DAYS | Constant expression | ` 30 ` | usage stats retention days; module-level state/definition, not necessarily user-configurable. | [app.py:62](../app.py#L62) |
| SAMPLE_FFDC | Call expression | ` env_path('FFDC_SAMPLE', '/root/codx_test/7D6NCTO3WW_J902ZRCV_xcc_260324-030334_pass.tzz') ` | sample FFDC; module-level state/definition, not necessarily user-configurable. | [app.py:63](../app.py#L63) |
| KEYFILES | Call expression | ` env_path('FFDC_KEYFILES', '/root/codx_test/keyfiles.txt') ` | keyfiles; module-level state/definition, not necessarily user-configurable. | [app.py:64](../app.py#L64) |
| API_KEY_FILE | Call expression | ` env_path('FFDC_API_KEY_FILE', '/root/codx_test/api_key.txt') ` | api key file; module-level state/definition, not necessarily user-configurable. | [app.py:65](../app.py#L65) |
| MAX_UPLOAD_BYTES | BinOp expression | ` 1024 * 1024 * 1024 ` | max upload bytes; module-level state/definition, not necessarily user-configurable. | [app.py:66](../app.py#L66) |
| DOMAIN_AUTHOR_REQUEST_MAX_BYTES | BinOp expression | ` 32 * 1024 * 1024 ` | domain author request max bytes; module-level state/definition, not necessarily user-configurable. | [app.py:67](../app.py#L67) |
| MAX_UPLOAD_FILES | Constant expression | ` 10 ` | max upload files; module-level state/definition, not necessarily user-configurable. | [app.py:68](../app.py#L68) |
| REPORT_RETENTION_DAYS | Constant expression | ` 30 ` | report retention days; module-level state/definition, not necessarily user-configurable. | [app.py:69](../app.py#L69) |
| OPENAI_MODEL | Call expression | ` os.environ.get('FFDC_OPENAI_MODEL', 'gpt-5.2') ` | openai model; module-level state/definition, not necessarily user-configurable. | [app.py:70](../app.py#L70) |
| DEEP_INVESTIGATION_MODEL | BoolOp expression | ` os.environ.get('FFDC_DEEP_INVESTIGATION_MODEL', 'nemotron-3-ultra').strip() or 'nemotron-3-ultra' ` | deep investigation model; module-level state/definition, not necessarily user-configurable. | [app.py:71](../app.py#L71) |
| CHAT_MODEL | BoolOp expression | ` os.environ.get('FFDC_CHAT_MODEL', 'nemotron-3-ultra').strip() or 'nemotron-3-ultra' ` | chat model; module-level state/definition, not necessarily user-configurable. | [app.py:75](../app.py#L75) |
| MAX_CONCURRENT_AI_REQUESTS | Call expression | ` env_int('FFDC_MAX_CONCURRENT_AI_REQUESTS', 4, minimum=1) ` | max concurrent ai requests; module-level state/definition, not necessarily user-configurable. | [app.py:79](../app.py#L79) |
| MAX_QUEUED_AI_REQUESTS | Call expression | ` env_int('FFDC_MAX_QUEUED_AI_REQUESTS', 44, minimum=0) ` | max queued ai requests; module-level state/definition, not necessarily user-configurable. | [app.py:80](../app.py#L80) |
| AI_REQUEST_QUEUE_TIMEOUT_SECONDS | Call expression | ` env_int('FFDC_AI_REQUEST_QUEUE_TIMEOUT_SECONDS', 90, minimum=5) ` | ai request queue timeout seconds; module-level state/definition, not necessarily user-configurable. | [app.py:81](../app.py#L81) |
| AI_REQUEST_MIN_START_INTERVAL_SECONDS | Call expression | ` env_float('FFDC_AI_MIN_START_INTERVAL_SECONDS', 0.5, minimum=0.0) ` | ai request min start interval seconds; module-level state/definition, not necessarily user-configurable. | [app.py:82](../app.py#L82) |
| WORKSPACE_CHAT_LIMIT | Call expression | ` threading.BoundedSemaphore(MAX_CONCURRENT_AI_REQUESTS) ` | workspace chat limit; module-level state/definition, not necessarily user-configurable. | [app.py:83](../app.py#L83) |
| AI_REQUEST_QUEUE_LOCK | Call expression | ` threading.Lock() ` | ai request queue lock; module-level state/definition, not necessarily user-configurable. | [app.py:84](../app.py#L84) |
| AI_REQUESTS_ADMITTED | Constant expression | ` 0 ` | ai requests admitted; module-level state/definition, not necessarily user-configurable. | [app.py:85](../app.py#L85) |
| AI_REQUEST_RATE_LOCK | Call expression | ` threading.Lock() ` | ai request rate lock; module-level state/definition, not necessarily user-configurable. | [app.py:86](../app.py#L86) |
| AI_REQUEST_NEXT_START | Constant expression | ` 0.0 ` | ai request next start; module-level state/definition, not necessarily user-configurable. | [app.py:87](../app.py#L87) |
| WORKSPACE_CHAT_MODEL | Call expression | ` os.environ.get('FFDC_WORKSPACE_CHAT_MODEL', '').strip() ` | workspace chat model; module-level state/definition, not necessarily user-configurable. | [app.py:88](../app.py#L88) |
| AI_SSL_CONTEXT | Call expression | ` ssl._create_unverified_context() ` | ai ssl context; module-level state/definition, not necessarily user-configurable. | [app.py:89](../app.py#L89) |
| JIRA_BASE_URL | Call expression | ` env_url('FFDC_JIRA_BASE_URL', 'https://jira1.labs.lenovo.com') ` | JIRA base url; module-level state/definition, not necessarily user-configurable. | [app.py:90](../app.py#L90) |
| JIRA_SSL_CONTEXT | Call expression | ` ssl._create_unverified_context() ` | JIRA ssl context; module-level state/definition, not necessarily user-configurable. | [app.py:91](../app.py#L91) |
| JIRA_SIMILAR_PAT_FILE | Call expression | ` env_path('FFDC_JIRA_SIMILAR_PAT_FILE', BASE_DIR / '.jira_similar_pat') ` | JIRA similar pat file; module-level state/definition, not necessarily user-configurable. | [app.py:130](../app.py#L130) |
| JIRA_SIMILAR_CASES_TTL_SECONDS | BinOp expression | ` 12 * 60 * 60 ` | JIRA similar cases ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:131](../app.py#L131) |
| FFDC_ATTACHMENT_EXTENSIONS | Tuple expression | ` ('.tzz', '.tar.zst', '.tzst', '.tgz', '.tar.gz', '.tar', '.gz') ` | FFDC attachment extensions; module-level state/definition, not necessarily user-configurable. | [app.py:132](../app.py#L132) |
| JIRA_IMAGE_EXTENSIONS | Tuple expression | ` ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff') ` | JIRA image extensions; module-level state/definition, not necessarily user-configurable. | [app.py:133](../app.py#L133) |
| MAX_JIRA_OCR_IMAGES | Constant expression | ` 10 ` | max JIRA ocr images; module-level state/definition, not necessarily user-configurable. | [app.py:134](../app.py#L134) |
| MAX_JIRA_IMAGE_BYTES | BinOp expression | ` 20 * 1024 * 1024 ` | max JIRA image bytes; module-level state/definition, not necessarily user-configurable. | [app.py:135](../app.py#L135) |
| MAX_JIRA_VISION_IMAGE_BYTES | BinOp expression | ` 10 * 1024 * 1024 ` | max JIRA vision image bytes; module-level state/definition, not necessarily user-configurable. | [app.py:136](../app.py#L136) |
| JIRA_VISION_IMAGE_MIME_TYPES | Dict expression | ` {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'} ` | JIRA vision image mime types; module-level state/definition, not necessarily user-configurable. | [app.py:137](../app.py#L137) |
| JIRA_LOG_ARCHIVE_EXTENSIONS | Tuple expression | ` ('.rar', '.zip', '.7z') ` | JIRA log archive extensions; module-level state/definition, not necessarily user-configurable. | [app.py:143](../app.py#L143) |
| MAX_JIRA_LOG_ARCHIVES | Constant expression | ` 3 ` | max JIRA log archives; module-level state/definition, not necessarily user-configurable. | [app.py:144](../app.py#L144) |
| MAX_JIRA_LOG_ARCHIVE_BYTES | BinOp expression | ` 256 * 1024 * 1024 ` | max JIRA log archive bytes; module-level state/definition, not necessarily user-configurable. | [app.py:145](../app.py#L145) |
| MAX_JIRA_LOG_EXTRACTED_BYTES | BinOp expression | ` 768 * 1024 * 1024 ` | max JIRA log extracted bytes; module-level state/definition, not necessarily user-configurable. | [app.py:146](../app.py#L146) |
| MAX_JIRA_LOG_FILES | Constant expression | ` 8000 ` | max JIRA log files; module-level state/definition, not necessarily user-configurable. | [app.py:147](../app.py#L147) |
| MAX_JIRA_LOG_TEXT_FILE_BYTES | BinOp expression | ` 16 * 1024 * 1024 ` | max JIRA log text file bytes; module-level state/definition, not necessarily user-configurable. | [app.py:148](../app.py#L148) |
| JIRA_SESSION_COOKIE | Constant expression | ` 'ffdc_jira_session' ` | JIRA session cookie; module-level state/definition, not necessarily user-configurable. | [app.py:149](../app.py#L149) |
| JIRA_SESSION_TTL_SECONDS | BinOp expression | ` 8 * 60 * 60 ` | JIRA session ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:150](../app.py#L150) |
| JIRA_SESSIONS | Dict expression | ` {} ` | JIRA sessions; module-level state/definition, not necessarily user-configurable. | [app.py:151](../app.py#L151) |
| AUTHOR_SESSION_COOKIE | Constant expression | ` 'ffdc_author_session' ` | author session cookie; module-level state/definition, not necessarily user-configurable. | [app.py:152](../app.py#L152) |
| AUTHOR_SESSION_TTL_SECONDS | BinOp expression | ` 2 * 60 * 60 ` | author session ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:153](../app.py#L153) |
| AUTHOR_SESSIONS | Dict expression | ` {} ` | author sessions; module-level state/definition, not necessarily user-configurable. | [app.py:154](../app.py#L154) |
| JIRA_JOBS | Dict expression | ` {} ` | JIRA jobs; module-level state/definition, not necessarily user-configurable. | [app.py:155](../app.py#L155) |
| JIRA_JOBS_LOCK | Call expression | ` threading.Lock() ` | JIRA jobs lock; module-level state/definition, not necessarily user-configurable. | [app.py:156](../app.py#L156) |
| JIRA_JOB_TTL_SECONDS | BinOp expression | ` 2 * 60 * 60 ` | JIRA job ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:157](../app.py#L157) |
| WORKSPACE_UPLOAD_JOBS | Dict expression | ` {} ` | workspace upload jobs; module-level state/definition, not necessarily user-configurable. | [app.py:158](../app.py#L158) |
| WORKSPACE_UPLOAD_JOBS_LOCK | Call expression | ` threading.Lock() ` | workspace upload jobs lock; module-level state/definition, not necessarily user-configurable. | [app.py:159](../app.py#L159) |
| WORKSPACE_UPLOAD_JOB_TTL_SECONDS | BinOp expression | ` 2 * 60 * 60 ` | workspace upload job ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:160](../app.py#L160) |
| JIRA_MONITOR_FILTER_ID | Call expression | ` os.environ.get('FFDC_JIRA_MONITOR_FILTER_ID', '34570') ` | JIRA monitor filter id; module-level state/definition, not necessarily user-configurable. | [app.py:161](../app.py#L161) |
| JIRA_MONITOR_CONFIG_FILE | Call expression | ` env_path('FFDC_JIRA_MONITOR_CONFIG', BASE_DIR / 'defect_review_config.json') ` | JIRA monitor config file; module-level state/definition, not necessarily user-configurable. | [app.py:162](../app.py#L162) |
| DEFECT_REVIEW_EMAIL_TO | Call expression | ` os.environ.get('FFDC_DEFECT_REVIEW_EMAIL_TO', 'RAIDAsia@LenovoBeijing.onmicrosoft.com').strip() ` | defect review email to; module-level state/definition, not necessarily user-configurable. | [app.py:163](../app.py#L163) |
| JIRA_MONITOR_LATEST_FILE | BinOp expression | ` JIRA_MONITOR_JOB_DIR / 'latest.json' ` | JIRA monitor latest file; module-level state/definition, not necessarily user-configurable. | [app.py:167](../app.py#L167) |
| JIRA_MONITOR_SCHEDULE_STATE_FILE | BinOp expression | ` JIRA_MONITOR_JOB_DIR / 'schedule_state.json' ` | JIRA monitor schedule state file; module-level state/definition, not necessarily user-configurable. | [app.py:168](../app.py#L168) |
| MILESTONE_TRACKER_CACHE_FILE | BinOp expression | ` BASE_DIR / 'project_milestone_tracker.json' ` | milestone tracker cache file; module-level state/definition, not necessarily user-configurable. | [app.py:169](../app.py#L169) |
| PROJECT_TOOL_BASE_URL | Call expression | ` env_url('FFDC_PROJECT_TOOL_BASE_URL', 'https://project-tool.labs.lenovo.com') ` | project tool base url; module-level state/definition, not necessarily user-configurable. | [app.py:170](../app.py#L170) |
| PROJECT_TOOL_CACHE_TTL_SECONDS | BinOp expression | ` 3 * 60 * 60 ` | project tool cache ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:171](../app.py#L171) |
| UPCOMING_MILESTONE_REPORT_ID | Call expression | ` os.environ.get('FFDC_UPCOMING_MILESTONE_REPORT_ID', '562') ` | upcoming milestone report id; module-level state/definition, not necessarily user-configurable. | [app.py:172](../app.py#L172) |
| UPCOMING_MILESTONE_MAX_DAYS | Constant expression | ` 40 ` | upcoming milestone max days; module-level state/definition, not necessarily user-configurable. | [app.py:173](../app.py#L173) |
| PROJECT_TOOL_SSL_CONTEXT | Call expression | ` ssl._create_unverified_context() ` | project tool ssl context; module-level state/definition, not necessarily user-configurable. | [app.py:174](../app.py#L174) |
| MILESTONE_CACHE_LOCK | Call expression | ` threading.Lock() ` | milestone cache lock; module-level state/definition, not necessarily user-configurable. | [app.py:175](../app.py#L175) |
| JIRA_MONITOR_JOBS | Dict expression | ` {} ` | JIRA monitor jobs; module-level state/definition, not necessarily user-configurable. | [app.py:176](../app.py#L176) |
| JIRA_MONITOR_JOBS_LOCK | Call expression | ` threading.Lock() ` | JIRA monitor jobs lock; module-level state/definition, not necessarily user-configurable. | [app.py:177](../app.py#L177) |
| JIRA_MONITOR_JOB_TTL_SECONDS | BinOp expression | ` 6 * 60 * 60 ` | JIRA monitor job ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:178](../app.py#L178) |
| CURRENT_STATUS_SUMMARY_JOBS | Dict expression | ` {} ` | current status summary jobs; module-level state/definition, not necessarily user-configurable. | [app.py:179](../app.py#L179) |
| CURRENT_STATUS_SUMMARY_JOBS_LOCK | Call expression | ` threading.Lock() ` | current status summary jobs lock; module-level state/definition, not necessarily user-configurable. | [app.py:180](../app.py#L180) |
| CURRENT_STATUS_SUMMARY_JOB_TTL_SECONDS | BinOp expression | ` 2 * 60 * 60 ` | current status summary job ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:181](../app.py#L181) |
| JIRA_MONITOR_SCHEDULER_LOCK | Call expression | ` threading.Lock() ` | JIRA monitor scheduler lock; module-level state/definition, not necessarily user-configurable. | [app.py:182](../app.py#L182) |
| JIRA_MONITOR_SCHEDULE_RETRY_DELAYS_SECONDS | Tuple expression | ` (5 * 60, 15 * 60) ` | JIRA monitor schedule retry delays seconds; module-level state/definition, not necessarily user-configurable. | [app.py:183](../app.py#L183) |
| JIRA_MONITOR_SCHEDULE_RETRY_MAX_AGE_SECONDS | BinOp expression | ` 60 * 60 ` | JIRA monitor schedule retry max age seconds; module-level state/definition, not necessarily user-configurable. | [app.py:184](../app.py#L184) |
| JIRA_RATE_LIMIT_RETRY_DELAYS_SECONDS | Tuple expression | ` (5, 15, 30) ` | JIRA rate limit retry delays seconds; module-level state/definition, not necessarily user-configurable. | [app.py:185](../app.py#L185) |
| JIRA_REQUEST_LOCK | Call expression | ` threading.Lock() ` | JIRA request lock; module-level state/definition, not necessarily user-configurable. | [app.py:186](../app.py#L186) |
| JIRA_REQUEST_NEXT_AT | Constant expression | ` 0.0 ` | JIRA request next at; module-level state/definition, not necessarily user-configurable. | [app.py:187](../app.py#L187) |
| JIRA_REQUEST_MIN_INTERVAL_SECONDS | Call expression | ` env_float('FFDC_JIRA_REQUEST_MIN_INTERVAL_SECONDS', 2, minimum=0.0) ` | JIRA request min interval seconds; module-level state/definition, not necessarily user-configurable. | [app.py:188](../app.py#L188) |
| FFDC_CACHE_LOCK | Call expression | ` threading.Lock() ` | FFDC cache lock; module-level state/definition, not necessarily user-configurable. | [app.py:189](../app.py#L189) |
| AGENT_JOBS | Dict expression | ` {} ` | agent jobs; module-level state/definition, not necessarily user-configurable. | [app.py:190](../app.py#L190) |
| AGENT_JOBS_LOCK | Call expression | ` threading.Lock() ` | agent jobs lock; module-level state/definition, not necessarily user-configurable. | [app.py:191](../app.py#L191) |
| AGENT_JOB_TTL_SECONDS | BinOp expression | ` 2 * 60 * 60 ` | agent job ttl seconds; module-level state/definition, not necessarily user-configurable. | [app.py:192](../app.py#L192) |
| MAX_CONCURRENT_ANALYSES | Call expression | ` env_int('FFDC_MAX_CONCURRENT_ANALYSES', 64, minimum=1) ` | max concurrent analyses; module-level state/definition, not necessarily user-configurable. | [app.py:193](../app.py#L193) |
| ANALYSIS_SEMAPHORE | Call expression | ` threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES) ` | analysis semaphore; module-level state/definition, not necessarily user-configurable. | [app.py:194](../app.py#L194) |
| ANALYSIS_STATE_LOCK | Call expression | ` threading.Lock() ` | analysis state lock; module-level state/definition, not necessarily user-configurable. | [app.py:195](../app.py#L195) |
| ANALYSIS_ACTIVE | Constant expression | ` 0 ` | analysis active; module-level state/definition, not necessarily user-configurable. | [app.py:196](../app.py#L196) |
| KEY_PATHS | Dict expression | ` {'service': ['tmp/service.txt', 'service.txt'], 'dmdb': ['tmp/ffdc_live_dbg/dmdb_pci_dumper.txt', 'tmp/ffdc_live_dbg/dmeb_pci_dumper.txt'], 'sep_info': ['tmp/ffdc_live_dbg/sep_info.txt'], 'sep_vpd': [ ... [expression length 926; full definition at source] ` | key paths; module-level state/definition, not necessarily user-configurable. | [app.py:204](../app.py#L204) |
| SEP_APPLICATIONS | Dict expression | ` {'BB': 'SEP 4MV4', 'BC': 'SEP 4MEV4', 'BD': 'SEP 12XV4', 'BE': 'SEP 8EV4', 'BF': 'SEP 4NV5', 'C0': 'SEP 6EV5', 'C1': 'SEP 4EV5'} ` | sep applications; module-level state/definition, not necessarily user-configurable. | [app.py:846](../app.py#L846) |
| TRI_MODEL_BP_STATUS | Dict expression | ` {'C3': ('Empty', 'empty'), 'C0': ('SAS/SATA Drive Installed', 'sas_sata'), 'D0': ('SAS/SATA Drive Rebuilding', 'rebuild'), 'C8': ('SAS/SATA Drive Locate', 'locate'), 'E0': ('SAS/SATA Drive Fail', 'fai ... [expression length 750; full definition at source] ` | tri model bp status; module-level state/definition, not necessarily user-configurable. | [app.py:856](../app.py#L856) |
| SAS_SATA_BP_STATUS | Dict expression | ` {'83': ('Empty', 'empty'), '80': ('SAS/SATA Drive Installed', 'sas_sata'), '90': ('SAS/SATA Drive Rebuilding', 'rebuild'), '88': ('SAS/SATA Drive Locate', 'locate'), 'A0': ('SAS/SATA Drive Fail', 'fai ... [expression length 308; full definition at source] ` | sas sata bp status; module-level state/definition, not necessarily user-configurable. | [app.py:876](../app.py#L876) |
| V1_SAS_SATA_BP_STATUS | Dict expression | ` {**SAS_SATA_BP_STATUS, '84': ('Fault: SAS/SATA Drive Installed', 'fault')} ` | v1 sas sata bp status; module-level state/definition, not necessarily user-configurable. | [app.py:886](../app.py#L886) |
| EDSFF_BP_STATUS | Dict expression | ` {'C3': ('Empty', 'empty'), 'C2': ('EDSFF x4 Drive Installed', 'edsff'), 'C0': ('EDSFF x8 Drive Installed', 'edsff'), '80': ('EDSFF x16 Drive Installed', 'edsff'), 'D2': ('EDSFF x4 Drive Rebuilding', ' ... [expression length 555; full definition at source] ` | edsff bp status; module-level state/definition, not necessarily user-configurable. | [app.py:891](../app.py#L891) |
| TRI_MODEL_EDSFF_BP_STATUS | Dict expression | ` {**TRI_MODEL_BP_STATUS, '83': ('EDSFF x4 Drive Installed', 'edsff'), '82': ('EDSFF x8 Drive Installed', 'edsff'), '93': ('EDSFF x4 Drive Rebuilding', 'rebuild'), '8B': ('EDSFF x4 Drive Locate', 'locat ... [expression length 373; full definition at source] ` | tri model edsff bp status; module-level state/definition, not necessarily user-configurable. | [app.py:907](../app.py#L907) |
| V4_4MEV4_BP_STATUS | Dict expression | ` {**TRI_MODEL_BP_STATUS, 'C2': ('EDSFF x4 Drive Installed', 'edsff'), '42': ('EDSFF x8 Drive Installed', 'edsff'), 'D2': ('EDSFF x4 Drive Rebuilding', 'rebuild'), 'CA': ('EDSFF x4 Drive Locate', 'locat ... [expression length 373; full definition at source] ` | v4 4mev4 bp status; module-level state/definition, not necessarily user-configurable. | [app.py:919](../app.py#L919) |
| V4_8EV4_BP_STATUS | Dict expression | ` {'C1': ('Empty', 'empty'), 'C0': ('EDSFF x4 Drive Installed', 'edsff'), '40': ('EDSFF x8 Drive Installed', 'edsff'), 'D0': ('EDSFF x4 Drive Rebuilding', 'rebuild'), 'C8': ('EDSFF x4 Drive Locate', 'lo ... [expression length 376; full definition at source] ` | v4 8ev4 bp status; module-level state/definition, not necessarily user-configurable. | [app.py:931](../app.py#L931) |
| V4_4NV5_BP_STATUS | Dict expression | ` {'C3': ('Empty', 'empty'), 'C4': ('Fault: SAS/SATA Drive Installed', 'fault'), 'C6': ('Fault: SATA Express Drive Installed', 'fault'), 'C1': ('NVMe Drive U.2 Installed', 'nvme'), 'E1': ('NVMe Drive U.2 Fail', 'fail')} ` | v4 4nv5 bp status; module-level state/definition, not necessarily user-configurable. | [app.py:943](../app.py#L943) |
| EDSFF_ONLY_CODES | Set expression | ` {'C2', 'CA', 'E2'} ` | edsff only codes; module-level state/definition, not necessarily user-configurable. | [app.py:951](../app.py#L951) |
| TRI_MODEL_EDSFF_CODES | Set expression | ` {'82', '8A', '8B', '92', '93', 'A2', 'A3'} ` | tri model edsff codes; module-level state/definition, not necessarily user-configurable. | [app.py:952](../app.py#L952) |
| EXTERNAL_STORAGE_MODEL_RE | Call expression | ` re.compile('\\b(?:\\d{3,5}\\s*[-/]\\s*\\d+\\s*e\|\\d{4,7}e)\\b', re.I) ` | external storage model re; module-level state/definition, not necessarily user-configurable. | [app.py:1829](../app.py#L1829) |
| BUILT_IN_BACKPLANE_EVIDENCE_FILES | Tuple expression | ` ('sep_info.txt', 'sep_vpd.txt', 'backplanes.txt', 'backplanes.json') ` | built in backplane evidence files; module-level state/definition, not necessarily user-configurable. | [app.py:1832](../app.py#L1832) |
| NETWORK_ADAPTER_RE | Call expression | ` re.compile('\\b(?:ethernet\|network controller\|nic\\b\|mellanox\|connectx\|netxtreme\|broadcom\|intel\\s+(?:i\\d+\|x\\d+\|e\\d+)\|\\b(?:i40e\|ice\|igb\|ixgbe\|bnxt)\\b\|marvell\|qlogic)\\b', re.I) ` | network adapter re; module-level state/definition, not necessarily user-configurable. | [app.py:1921](../app.py#L1921) |
| NETWORK_INTERFACE_RE | Call expression | ` re.compile('\\b(?:en[opsx][a-zA-Z0-9_.:-]*\|eth\\d+\|bond\\d+\|team\\d+\|ib\\d+)\\b', re.I) ` | network interface re; module-level state/definition, not necessarily user-configurable. | [app.py:1926](../app.py#L1926) |
| NETWORK_LOG_NAME_RE | Call expression | ` re.compile('(?:journal\|syslog\|messages\|dmesg\|kernel\|network\|netdev\|ethernet\|nic\|ethtool\|link)', re.I) ` | network log name re; module-level state/definition, not necessarily user-configurable. | [app.py:1930](../app.py#L1930) |
| NETWORK_SENSITIVE_RE | Call expression | ` re.compile('\\b(?:password\|passwd\|api[_ -]?key\|authorization\|bearer\|access[_ -]?token\|private[_ -]?key\|secret)\\b', re.I) ` | network sensitive re; module-level state/definition, not necessarily user-configurable. | [app.py:1934](../app.py#L1934) |
| NETWORK_DRIVER_RE | Call expression | ` re.compile('\\b(?:i40e\|ice\|igb\|ixgbe\|bnxt_en\|bnx2x\|mlx[45]_core\|tg3\|e1000e\|ena)\\b', re.I) ` | network driver re; module-level state/definition, not necessarily user-configurable. | [app.py:1938](../app.py#L1938) |
| MAX_NETWORK_LOG_FILES | Constant expression | ` 12 ` | max network log files; module-level state/definition, not necessarily user-configurable. | [app.py:1939](../app.py#L1939) |
| MAX_NETWORK_LOG_BYTES_PER_FILE | BinOp expression | ` 768 * 1024 ` | max network log bytes per file; module-level state/definition, not necessarily user-configurable. | [app.py:1940](../app.py#L1940) |
| PLDM_UPDATE_START_RE | Call expression | ` re.compile('^(?P<timestamp>\\S+).*?==== Run update on the device \\[TID=(?P<tid>[^,]+),\\s*EID=(?P<eid>[^,]+),\\s*ADDR=(?P<address>[^\\]]+)\\],\\s*Activate=(?P<activate>\\w+) ====', re.I) ` | PLDM update start re; module-level state/definition, not necessarily user-configurable. | [app.py:2137](../app.py#L2137) |
| PLDM_COMPONENT_VERSION_RE | Call expression | ` re.compile('Component\\s+(?P<component>\\d+),\\s*version:\\s*(?P<version>.+)$', re.I) ` | PLDM component version re; module-level state/definition, not necessarily user-configurable. | [app.py:2143](../app.py#L2143) |
| PLDM_COMPAT_RESPONSE_RE | Call expression | ` re.compile('compCompatabilityRespCode\\s*=\\s*(?P<code>\\d+)', re.I) ` | PLDM compat response re; module-level state/definition, not necessarily user-configurable. | [app.py:2144](../app.py#L2144) |
| BMC_INBAND_LOG_NAME_RE | Call expression | ` re.compile('(?:flash\|firmware\|fwupdate\|fw_update\|in.?band\|pldm\|mctp\|journal\|syslog\|messages)', re.I) ` | bmc inband log name re; module-level state/definition, not necessarily user-configurable. | [app.py:2265](../app.py#L2265) |
| BMC_INBAND_CONTEXT_RE | Call expression | ` re.compile('\\b(?:bmc\|bmu\|in[- ]?band\|redfish\|update service)\\b', re.I) ` | bmc inband context re; module-level state/definition, not necessarily user-configurable. | [app.py:2269](../app.py#L2269) |
| BMC_INBAND_ACTION_RE | Call expression | ` re.compile('\\b(?:firmware\|firmware update\|fw update\|flash(?:ing)?\|startfwupdate\|activate\|download(?:ing)?\|transfer(?:ring)?\|verify(?:ing)?\|rollback)\\b', re.I) ` | bmc inband action re; module-level state/definition, not necessarily user-configurable. | [app.py:2270](../app.py#L2270) |
| BMC_INBAND_FAILURE_RE | Call expression | ` re.compile('\\b(?:failed\|failure\|error\|timeout\|timed out\|abort(?:ed)?\|rollback\|reject(?:ed)?)\\b', re.I) ` | bmc inband failure re; module-level state/definition, not necessarily user-configurable. | [app.py:2275](../app.py#L2275) |
| BMC_INBAND_SUCCESS_RE | Call expression | ` re.compile('\\b(?:succeeded\|success(?:ful(?:ly)?)?\|completed\|complete\|activated\|done)\\b', re.I) ` | bmc inband success re; module-level state/definition, not necessarily user-configurable. | [app.py:2276](../app.py#L2276) |
| BMC_INBAND_START_RE | Call expression | ` re.compile('\\b(?:start(?:ed\|ing)?\|begin\|prepare\|download(?:ing)?\|transfer(?:ring)?\|flash(?:ing)?)\\b', re.I) ` | bmc inband start re; module-level state/definition, not necessarily user-configurable. | [app.py:2277](../app.py#L2277) |
| UEFI_KEYWORD_RE | Call expression | ` re.compile('\\b(error\|failed\|fail\|warning\|timeout\|assert\|exception\|hang\|critical\|fatal\|degraded\|offline\|mismatch\|not found\|cannot\|unable)\\b\|PCIe\|NVMe\|RAID\|Option ROM\|Link\|Training', re.I) ` | UEFI keyword re; module-level state/definition, not necessarily user-configurable. | [app.py:2438](../app.py#L2438) |
| UEFI_STRONG_RE | Call expression | ` re.compile('\\b(error\|failed\|fail\|timeout\|assert\|exception\|hang\|critical\|fatal\|degraded\|offline\|mismatch)\\b', re.I) ` | UEFI strong re; module-level state/definition, not necessarily user-configurable. | [app.py:2439](../app.py#L2439) |
| RAID_TTY_STRONG_RE | Call expression | ` re.compile('\\b(fatal\|panic\|exception\|degraded\|offline)\\b', re.I) ` | raid tty strong re; module-level state/definition, not necessarily user-configurable. | [app.py:2744](../app.py#L2744) |
| RAID_TTY_CAPACITOR_RE | Call expression | ` re.compile('supercap\|capacitor\|capacitance\|bbu\|battery\|cachevault\|cvpm\|cache vault\|retention', re.I) ` | raid tty capacitor re; module-level state/definition, not necessarily user-configurable. | [app.py:2745](../app.py#L2745) |
| RAID_TTY_CAPACITOR_BAD_RE | Call expression | ` re.compile('failed\|fail\|fault\|bad\|missing\|not present\|replacement\|required\|low\|critical(?! temperature)\|warning', re.I) ` | raid tty capacitor bad re; module-level state/definition, not necessarily user-configurable. | [app.py:2746](../app.py#L2746) |
| RAID_TTY_PCIE_LINK_RE | Call expression | ` re.compile('PCIE\\s+Link\\s+Status/Ctrl.*?Speeds:\\s*max=([0-9.]+)\\s*GT/s\\s+neg=([0-9.]+)\\s*GT/s,\\s*Widths:\\s*max=(\\d+)\\s+neg=(\\d+)', re.I) ` | raid tty PCIe link re; module-level state/definition, not necessarily user-configurable. | [app.py:2747](../app.py#L2747) |
| JIRA_LOG_TEXT_EXTENSIONS | Set expression | ` {'.log', '.txt', '.out', '.err', '.json', '.xml', '.csv', '.conf', '.cfg', '.ini', '.yaml', '.yml', '.trace', '.dmesg', '.journal'} ` | JIRA log text extensions; module-level state/definition, not necessarily user-configurable. | [app.py:7422](../app.py#L7422) |
| JIRA_LOG_ERROR_RE | Call expression | ` re.compile('\\b(?:timed?\\s*out\|timeout\|abort(?:ed\|ing)?\|failed\|failure\|fatal\|critical\|panic\|hung\|reset(?:ting)?\|link\\s+(?:down\|fail\\w*)\|i/o\\s+error\|medium\\s+error\|degraded\|offline\|not\\s+responding\|device\\s+not\\s+ready\|uncorrectable)\\b', re.I) ` | JIRA log error re; module-level state/definition, not necessarily user-configurable. | [app.py:7426](../app.py#L7426) |
| JIRA_LOG_VERSION_RE | Call expression | ` re.compile('\\b(?:driver\|firmware\|kernel\|module\|megaraid_sas\|mpt3sas\|storcli\|perccli\|sas3ircu)\\b.{0,80}\\b(?:version\|build\|release\|[0-9]+\\.[0-9]+(?:\\.[0-9]+){1,3})\\b\|\\b(?:version\|build\|release)\\b.{0,80}\\b(?:driver\|firmware\|kernel\|module)\\b', re.I) ` | JIRA log version re; module-level state/definition, not necessarily user-configurable. | [app.py:7432](../app.py#L7432) |
| JIRA_LOG_BOOT_RE | Call expression | ` re.compile('\\b(?:post\\s*end\|postend\|boot\\s+progress\|uefi\|bds\|pcie\|pci\\s+express\|nvme\|e3\\.s\|cd8p\|enumerat(?:e\|ion)\|initiali[sz](?:e\|ation)\|watchdog)\\b', re.I) ` | JIRA log boot re; module-level state/definition, not necessarily user-configurable. | [app.py:7438](../app.py#L7438) |
| JIRA_LOG_BOOT_FAILURE_RE | Call expression | ` re.compile('\\b(?:post\\s*end\|postend\|hang(?:s\|ed\|ing)?\|hung\|assert(?:ion)?\|exception\|watchdog\|timeout\|timed?\\s*out\|abort(?:ed\|ing)?\|fail(?:ed\|ure)?)\\b', re.I) ` | JIRA log boot failure re; module-level state/definition, not necessarily user-configurable. | [app.py:7443](../app.py#L7443) |
| JIRA_LOG_SENSITIVE_RE | Call expression | ` re.compile('\\b(?:password\|passwd\|api[_ -]?key\|authorization\|bearer\|access[_ -]?token\|private[_ -]?key\|secret)\\b', re.I) ` | JIRA log sensitive re; module-level state/definition, not necessarily user-configurable. | [app.py:7448](../app.py#L7448) |
| HTML_HEAD | Constant expression | ` "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ThinkSystem FFDC Analyzer for RAID team</title><style>\n:root{color-scheme:l ... [expression length 19261; full definition at source] ` | html head; module-level state/definition, not necessarily user-configurable. | [app.py:13385](../app.py#L13385) |

### `ffdc_chat.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |
| TEXT_SUFFIXES | Set expression | ` {'', '.txt', '.log', '.out', '.json', '.xml', '.csv', '.trace', '.journal', '.dmesg'} ` | text suffixes; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:19](../ffdc_chat.py#L19) |
| SECRET | Call expression | ` re.compile('password\|passwd\|authorization\|bearer\|api[_ -]?key\|access[_ -]?token\|private[_ -]?key\|secret', re.I) ` | secret; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:20](../ffdc_chat.py#L20) |
| MAX_SCAN_BYTES | BinOp expression | ` 32 * 1024 * 1024 ` | max scan bytes; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:21](../ffdc_chat.py#L21) |
| TRIAGE_SCAN_BYTES | BinOp expression | ` 12 * 1024 * 1024 ` | triage scan bytes; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:22](../ffdc_chat.py#L22) |
| TRIAGE_MAX_FILES | Constant expression | ` 240 ` | triage max files; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:23](../ffdc_chat.py#L23) |
| TRIAGE_MATCHES_PER_CATEGORY | Constant expression | ` 3 ` | triage matches per category; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:24](../ffdc_chat.py#L24) |
| TRIAGE_FOCUSES | Set expression | ` {'all', 'storage', 'pcie', 'network', 'firmware', 'system'} ` | triage focuses; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:25](../ffdc_chat.py#L25) |
| TRIAGE_FAILURE | Call expression | ` re.compile('\\b(?:error\|fail(?:ed\|ure)?\|critical\|fatal\|timeout\|unsupported\|degraded\|predictive(?:failure)?\|uncorrectable\|unrecoverable\|panic\|assert\|offline\|not detected\|link down\|carrier lost\|reset\|aborted)\\b', re.I) ` | triage failure; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:26](../ffdc_chat.py#L26) |
| TRIAGE_COMPONENTS | Dict expression | ` {'storage': re.compile('\\b(?:raid\|hba\|drive\|disk\|nvme\|sas\|sata\|scsi\|backplane\|sep\|ubm\|controller\|media)\\b', re.I), 'pcie': re.compile('\\b(?:pcie\|pci\|aer\|completion\|surprise down\|link width\|link spe ... [expression length 515; full definition at source] ` | triage components; module-level state/definition, not necessarily user-configurable. | [ffdc_chat.py:32](../ffdc_chat.py#L32) |

### `workspace_analysis.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |
| FOCUS_WORDS | Dict expression | ` {'network': '网卡\|网络\|丢包\|以太\|\\b(?:nic\|ethernet\|network\|netdev\|mlx\\w*\|bnxt\\w*\|link down\|carrier)\\b', 'storage': '背板\|磁盘\|硬盘\|盘符\|\\b(?:raid\|hba\|drive\|disk\|nvme\|backplane\|psoc\|ubm)\\b', 'firmware': '固件\|刷写\|升 ... [expression length 387; full definition at source] ` | focus words; module-level state/definition, not necessarily user-configurable. | [workspace_analysis.py:11](../workspace_analysis.py#L11) |
| BENIGN | Call expression | ` re.compile('\\b(?:no errors?\|0 errors?\|errors?\\s*[:=]\\s*0\\b\|failures?\\s*[:=]\\s*0\\b\|error handling\|error injection\|supported error)\\b', re.I) ` | benign; module-level state/definition, not necessarily user-configurable. | [workspace_analysis.py:18](../workspace_analysis.py#L18) |
| URGENT | Call expression | ` re.compile('\\b(?:fatal\|uncorrectable\|panic\|critical\|failed\|timeout\|unsupported\|not detected)\\b', re.I) ` | urgent; module-level state/definition, not necessarily user-configurable. | [workspace_analysis.py:19](../workspace_analysis.py#L19) |
| DISCOVERY_SIGNAL | Call expression | ` re.compile('\\b(?:fault\|mismatch\|invalid\|exception\|assert(?:ed\|ion)?\|over.?temp\|over.?current\|under.?voltage\|retry\|retries\|unexpected\|changed\|transition(?:ed)?\|corrupt(?:ed\|ion)?)\\b', re.I) ` | discovery signal; module-level state/definition, not necessarily user-configurable. | [workspace_analysis.py:20](../workspace_analysis.py#L20) |
| INSTRUCTIONS | Constant expression | ` 'You are investigating the currently selected FFDC, not writing a generic report.\nAnswer the latest question directly. For broad findings: a 1-2 sentence conclusion, at most 5 ranked findings with sh ... [expression length 4709; full definition at source] ` | instructions; module-level state/definition, not necessarily user-configurable. | [workspace_analysis.py:24](../workspace_analysis.py#L24) |

### `workspace_ui.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |
| VERSION | Constant expression | ` '20261008-drop1' ` | version; module-level state/definition, not necessarily user-configurable. | [workspace_ui.py:8](../workspace_ui.py#L8) |
| MAINTENANCE_END | Call expression | ` datetime(2026, 10, 3, 20, 0, tzinfo=ZoneInfo('Asia/Shanghai')) ` | maintenance end; module-level state/definition, not necessarily user-configurable. | [workspace_ui.py:9](../workspace_ui.py#L9) |
| WORKSPACE_NAV | Tuple expression | ` (('defect', '/Defect_review?view=workspace', 'list-checks', 'Defect Review'), ('milestones', '/Current_bug_status_summary?view=workspace', 'calendar-days', 'Milestones'), ('reports', '/reports?view=wo ... [expression length 307; full definition at source] ` | workspace nav; module-level state/definition, not necessarily user-configurable. | [workspace_ui.py:11](../workspace_ui.py#L11) |

### `ffdc_config.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |

### `ffdc_jobs.py` assignments

| Name | Type representation | Default / initializer | Purpose | Source |
| --- | --- | --- | --- | --- |

## Class Instance Attributes

Only directly assigned `self` attributes are enumerated. Inherited HTTP handler fields (`path`, `headers`, `rfile`, `wfile`, `client_address`, `server`) originate in `BaseHTTPRequestHandler`. Inherited `EvidenceTools` attributes remain available to `WorkspaceEvidenceTools`.

### `AIServiceBusyError`

Source: [app.py:94-95](../app.py#L94); bases: RuntimeError.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [app.py:94](../app.py#L94) |

### `SameOriginAuthorizationRedirectHandler`

Source: [app.py:4317-4324](../app.py#L4317); bases: urllib.request.HTTPRedirectHandler.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [app.py:4317](../app.py#L4317) |

### `DefectReviewTableParser`

Source: [app.py:10025-10061](../app.py#L10025); bases: HTMLParser.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| tables | list | ` [] ` | [app.py:10028](../app.py#L10028) |
| table | NoneType | ` None ` | [app.py:10061](../app.py#L10061) |
| row | NoneType | ` None ` | [app.py:10057](../app.py#L10057) |
| cell | list | ` [] ` | [app.py:10040](../app.py#L10040) |

### `AnalysisBusyError`

Source: [app.py:10532-10533](../app.py#L10532); bases: RuntimeError.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [app.py:10532](../app.py#L10532) |

### `Handler`

Source: [app.py:13550-14465](../app.py#L13550); bases: BaseHTTPRequestHandler.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [app.py:13550](../app.py#L13550) |

### `FFDCThreadingHTTPServer`

Source: [app.py:14468-14470](../app.py#L14468); bases: ThreadingHTTPServer.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [app.py:14468](../app.py#L14468) |

### `JiraLoginRequired`

Source: [ffdc_chat.py:15-16](../ffdc_chat.py#L15); bases: ValueError.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| None directly assigned | — | Uses inherited state or is a marker exception. | [ffdc_chat.py:15](../ffdc_chat.py#L15) |

### `EvidenceTools`

Source: [ffdc_chat.py:175-450](../ffdc_chat.py#L175); bases: .

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| root | dynamic (not annotated) | ` Path(root).resolve() if root else None ` | [ffdc_chat.py:177](../ffdc_chat.py#L177) |
| jira_request | dynamic (not annotated) | ` jira_request ` | [ffdc_chat.py:178](../ffdc_chat.py#L178) |
| jira_base | dynamic (not annotated) | ` jira_base.rstrip('/') ` | [ffdc_chat.py:179](../ffdc_chat.py#L179) |
| project_search | dynamic (not annotated) | ` project_search ` | [ffdc_chat.py:180](../ffdc_chat.py#L180) |
| audit | list | ` [] ` | [ffdc_chat.py:181](../ffdc_chat.py#L181) |
| unreadable_paths | int | ` 0 ` | [ffdc_chat.py:374](../ffdc_chat.py#L374) |

### `WorkspaceEvidenceTools`

Source: [workspace_analysis.py:43-243](../workspace_analysis.py#L43); bases: EvidenceTools.

| Attribute | Inferred type | Assignment / meaning | Source |
| --- | --- | --- | --- |
| sections | bool | ` sections or {} ` | [workspace_analysis.py:46](../workspace_analysis.py#L46) |
| sources | list | ` [] ` | [workspace_analysis.py:47](../workspace_analysis.py#L47) |
| source_keys | set | ` set() ` | [workspace_analysis.py:48](../workspace_analysis.py#L48) |
| scan | dict | ` {key: result[key] for key in ('files_scanned', 'bytes_scanned', 'limited', 'unreadable_files')} ` | [workspace_analysis.py:159](../workspace_analysis.py#L159) |
| started | dynamic (not annotated) | ` time.monotonic() ` | [workspace_analysis.py:50](../workspace_analysis.py#L50) |
| cached_results | dict | ` {} ` | [workspace_analysis.py:51](../workspace_analysis.py#L51) |
| reopened_sources | dynamic (not annotated) | ` len(excerpts) ` | [workspace_analysis.py:181](../workspace_analysis.py#L181) |
| domain_packs | dynamic (not annotated) | ` DomainPackRegistry() ` | [workspace_analysis.py:53](../workspace_analysis.py#L53) |
| unreadable_paths | int | ` 0 ` | [workspace_analysis.py:117](../workspace_analysis.py#L117) |

## Full Runtime Python Callable Reference

The current runtime modules include the HTTP entrypoint, evidence/UI modules, bounded configuration helpers, and job persistence primitives. This catalogue includes private helpers/constructors as well as public functions. Signatures have no inferred enforcement; descriptions marked inferred use full-body structure and observed delegates. Return expressions are abbreviated for readability, with complete implementations linked by line.

| Module | Functions and methods | Source SHA-256 |
| --- | --- | --- |
| app.py | 461 | f65f8a4f7bd78b4abd92b07278c8d6ca464cc0c9b7585b4a55536ec9629ec45b |
| ffdc_chat.py | 21 | 521c3ac47752065a2ecfed7e8c6d1bec97193164110b82387770633133e9995e |
| workspace_analysis.py | 14 | d429f1f5431051436f394bbd695083be08f4e303f98b395d0d1d8e291662aff9 |
| workspace_ui.py | 5 | aeca598fd05cc581e55e8cd3cc445ee3e9c4d5c7544c555fd645d9fc6e570c15 |
| ffdc_config.py | 4 | fbd4eabdcedab2f8a3de7a6af85da37e182437e3dc0bf68624745bf32223666b |
| ffdc_jobs.py | 7 | fc781215b8c985de9d152e36d5d3e216158ed7aa2bcd37654dde6cfc31ae966d |

## `app.py` Callable Details

### `acquire_workspace_chat_slot`

Source: [app.py:98-111](../app.py#L98).

Admit a bounded queue and limit simultaneous calls to the model service.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 104 | bool | ` False ` |
| 108 | bool | ` True ` |

Global declarations: `AI_REQUESTS_ADMITTED`.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 106 | ` WORKSPACE_CHAT_LIMIT.acquire(timeout=AI_REQUEST_QUEUE_TIMEOUT_SECONDS) ` |

### `release_workspace_chat_slot`

Source: [app.py:114-118](../app.py#L114).

Release workspace chat slot. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Global declarations: `AI_REQUESTS_ADMITTED`.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 116 | ` WORKSPACE_CHAT_LIMIT.release() ` |

### `wait_for_ai_request_start`

Source: [app.py:121-129](../app.py#L121).

Spread model request starts so queued users do not create an upstream burst.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Global declarations: `AI_REQUEST_NEXT_START`.

### `cleanup_uploads`

Source: [app.py:224-231](../app.py#L224).

Clean up uploads. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| limit | dynamic (not annotated) | ` MAX_UPLOAD_FILES ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 229 | ` old.unlink() ` |

### `cleanup_reports`

Source: [app.py:234-249](../app.py#L234).

Clean up reports. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| keep_ids | NoneType | ` None ` | Keep ids; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 247 | ` shutil.rmtree(old) ` |

### `clear_reports`

Source: [app.py:252-262](../app.py#L252).

Clear reports. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 262 | dynamic (not annotated) | ` count ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 258 | ` shutil.rmtree(report_dir) ` |

### `stream_multipart_upload`

Source: [app.py:265-329](../app.py#L265).

Stream the single FFDC multipart field to a sanitized timestamped upload path, maintaining boundary lookbehind and rejecting incomplete payloads.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rfile | not annotated | ` (required) ` | Rfile; operation-specific input consumed by this function. No stricter schema is declared. |
| content_type | not annotated | ` (required) ` | Content type; operation-specific input consumed by this function. No stricter schema is declared. |
| content_length | not annotated | ` (required) ` | Content length; operation-specific input consumed by this function. No stricter schema is declared. |
| expected_field | str | ` 'ffdc' ` | Expected field; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 321 | dynamic (not annotated) | ` upload_path ` |

Raises directly: `ValueError('Invalid multipart upload: boundary is missing')` (line 271); `ValueError('Invalid multipart upload: starting boundary not found')` (line 287); `ValueError(f'No {expected_field} file uploaded')` (line 304); `ValueError('Invalid multipart upload: closing boundary not found')` (line 329). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 311 | ` upload_path.open('wb') ` |
| 326 | ` upload_path.unlink() ` |

### `read_domain_author_request`

Source: [app.py:332-371](../app.py#L332).

Read JSON or one bounded knowledge document for the authoring endpoint.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| handler | not annotated | ` (required) ` | Handler; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 343 | tuple | ` (payload, None) ` |
| 371 | tuple | ` (payload, document) ` |

Raises directly: `ValueError('Knowledge document request is empty or larger than 32 MB.')` (line 337); `ValueError('JSON object required.')` (line 342); `ValueError('JSON or multipart form data is required.')` (line 347); `ValueError('Invalid multipart request.')` (line 351); `ValueError('Attach one knowledge document at a time.')` (line 362); `ValueError('Knowledge document must be 24 MB or smaller.')` (line 364). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_pdf_pages_for_vision`

Source: [app.py:374-409](../app.py#L374).

Render a bounded set of PDF pages for visual analysis; never OCR them here.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| pdf_bytes | not annotated | ` (required) ` | Pdf bytes; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 378 | tuple | ` ([], ['PDF page rendering is unavailable; embedded images were not analyzed.']) ` |
| 394 | tuple | ` ([], ['PDF pages could not be rendered for visual analysis.']) ` |
| 409 | tuple | ` (images, warnings) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 384 | ` pdf_path.write_bytes(pdf_bytes) ` |
| 386 | ` subprocess.run([renderer, '-f', '1', '-l', str(DOCUMENT_VISION_MAX_PAGES), '-jpeg', '-r', '110', str(pdf_path), str(prefix)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=45, check=True) ` |

### `enrich_pdf_document_with_vision`

Source: [app.py:412-433](../app.py#L412).

Add page-level Davy vision notes while discarding rendered image bytes.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| document | not annotated | ` (required) ` | Document; operation-specific input consumed by this function. No stricter schema is declared. |
| pdf_bytes | not annotated | ` (required) ` | Pdf bytes; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 433 | dynamic (not annotated) | ` enriched ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `read_text`

Source: [app.py:436-440](../app.py#L436).

Read text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 438 | str | ` '' ` |
| 440 | str | ` data.decode('utf-8', errors='replace') ` |

### `first_match`

Source: [app.py:443-445](../app.py#L443).

First match. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| pattern | not annotated | ` (required) ` | Pattern; operation-specific input consumed by this function. No stricter schema is declared. |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| flags | int | ` 0 ` | Flags; operation-specific input consumed by this function. No stricter schema is declared. |
| default | str | ` '' ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 445 | dynamic (not annotated) | ` m.group(1).strip() if m else default ` |

### `table_rows_after`

Source: [app.py:448-467](../app.py#L448).

Table rows after. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| header | not annotated | ` (required) ` | Header; operation-specific input consumed by this function. No stricter schema is declared. |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 456 | list | ` [] ` |
| 467 | dynamic (not annotated) | ` rows ` |

### `parse_service`

Source: [app.py:470-499](../app.py#L470).

Parse service. Delegates to `first_match`. Literal result/intermediate fields include `build_id`, `entity_id`, `events`, `firmware`, `fru`, `fru_id`, `level`, `message`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 499 | dynamic (not annotated) | ` info ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 480 | ` first_match('System Status\\s+(.+?)\\s+OS bootedState', text, re.S).replace('\r', ' ').strip() ` |
| 480 | ` first_match('System Status\\s+(.+?)\\s+OS bootedState', text, re.S).replace('\r', ' ') ` |
| 481 | ` first_match('Date Time Information\\s+(.+?)\\s+System Status', text, re.S).replace('\r', ' ').strip() ` |
| 481 | ` first_match('Date Time Information\\s+(.+?)\\s+System Status', text, re.S).replace('\r', ' ') ` |

### `parse_dmdb`

Source: [app.py:502-620](../app.py#L502).

Parse dmdb. Delegates to `first_match`. Literal result/intermediate fields include `adapters`, `bay`, `bus`, `capacity`, `controller`, `dev`, `drives`, `eid`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 620 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_fru_log`

Source: [app.py:623-710](../app.py#L623).

Parse fru log. Delegates to `first_match`. Literal result/intermediate fields include `FRU`, `boards`, `cores`, `cpu`, `device`, `firmware`, `fru`, `item`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 632 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_rdata_line`

Source: [app.py:713-717](../app.py#L713).

Parse rdata line. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 716 | tuple | ` (None, []) ` |
| 717 | tuple | ` (int(m.group(1), 16), re.findall('[0-9A-Fa-f]{2}', m.group(2).upper())) ` |

### `interpret_sep_block`

Source: [app.py:720-843](../app.py#L720).

Interpret sep block. Delegates to `decode_u3_mode`, `parse_rdata_line`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| block | not annotated | ` (required) ` | Block; operation-specific input consumed by this function. No stricter schema is declared. |
| platform_format | str | ` 'v1_v3' ` | Platform format; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 843 | dynamic (not annotated) | ` block ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 734 | ` block['bp'].replace('_', ' ').title() ` |
| 734 | ` block['bp'].replace('_', ' ') ` |

### `decode_m2_drive_type`

Source: [app.py:955-975](../app.py#L955).

Decode m2 drive type. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 958 | tuple | ` ('M.2 Drive Normal', 'm2') ` |
| 962 | tuple | ` (f'Unknown {value}', 'unknown') ` |
| 974 | tuple | ` ('Unsupported', 'fault') ` |
| 975 | dynamic (not annotated) | ` mapping.get(key, (f'Unknown {value}', 'unknown')) ` |

### `choose_bp_status_table`

Source: [app.py:978-999](../app.py#L978).

Choose bp status table. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| capability_code | not annotated | ` (required) ` | Capability code; operation-specific input consumed by this function. No stricter schema is declared. |
| values | NoneType | ` None ` | Values; operation-specific input consumed by this function. No stricter schema is declared. |
| application_id | str | ` '' ` | Application id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 981 | dynamic (not annotated) | ` TRI_MODEL_BP_STATUS ` |
| 983 | dynamic (not annotated) | ` V4_4MEV4_BP_STATUS ` |
| 985 | dynamic (not annotated) | ` V4_8EV4_BP_STATUS ` |
| 987 | dynamic (not annotated) | ` V4_4NV5_BP_STATUS ` |
| 991 | dynamic (not annotated) | ` V1_SAS_SATA_BP_STATUS ` |
| 994 | dynamic (not annotated) | ` TRI_MODEL_EDSFF_BP_STATUS ` |
| 996 | dynamic (not annotated) | ` EDSFF_BP_STATUS ` |
| 999 | dynamic (not annotated) | ` SAS_SATA_BP_STATUS ` |

### `decode_u3_mode`

Source: [app.py:1002-1008](../app.py#L1002).

Decode u3 mode. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| code | not annotated | ` (required) ` | Code; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1005 | str | ` 'x1' ` |
| 1007 | str | ` 'x4' ` |
| 1008 | dynamic (not annotated) | ` 'Mixed' if code else '' ` |

### `decode_bp_slot_status`

Source: [app.py:1011-1040](../app.py#L1011).

Decode bp slot status. Delegates to `choose_bp_status_table`, `decode_m2_drive_type`. Literal result/intermediate fields include `00`, `01`, `03`, `81`, `83`, `C0`, `C1`, `C3`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| capability_code | not annotated | ` (required) ` | Capability code; operation-specific input consumed by this function. No stricter schema is declared. |
| values | NoneType | ` None ` | Values; operation-specific input consumed by this function. No stricter schema is declared. |
| application_id | str | ` '' ` | Application id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1015 | tuple | ` ('Boot Drive Normal', 'boot_drive') ` |
| 1024 | dynamic (not annotated) | ` boot_status.get(value_text, (f'Unknown {value}', 'unknown')) ` |
| 1036 | dynamic (not annotated) | ` boot_status[value_text] ` |
| 1037 | dynamic (not annotated) | ` decode_m2_drive_type(value) ` |
| 1040 | tuple | ` (label, category) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_sep_info`

Source: [app.py:1043-1176](../app.py#L1043).

Parse sep info. Delegates to `decode_bp_slot_status`, `interpret_sep_block`. Literal result/intermediate fields include `application`, `application_id`, `bp`, `capability`, `capability_code`, `command`, `effective_slots`, `error`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| platform_format | str | ` 'v1_v3' ` | Platform format; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1176 | dynamic (not annotated) | ` parsed ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 1145 | ` label.replace(' Drive Installed', '') ` |
| 1150 | ` label.replace(' Installed', '') ` |
| 1152 | ` label.replace(' Installed', '') ` |

### `clean_vpd_value`

Source: [app.py:1179-1180](../app.py#L1179).

Normalize vpd value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1180 | str | ` re.sub('[\\x00\\[\\]th]+$', '', str(value or '')).strip() ` |

### `parse_sep_vpd`

Source: [app.py:1183-1217](../app.py#L1183).

Parse sep vpd. Delegates to `clean_vpd_value`, `first_match`. Literal result/intermediate fields include `bp`, `name`, `raw`, `summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1197 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_normal_7mm_boot_vpd_unknown`

Source: [app.py:1220-1230](../app.py#L1220).

Test normal 7mm boot vpd unknown. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| row | not annotated | ` (required) ` | Row; operation-specific input consumed by this function. No stricter schema is declared. |
| all_rows | NoneType | ` None ` | All rows; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1223 | bool | ` False ` |
| 1229 | bool | ` True ` |

### `split_v4_register_dump`

Source: [app.py:1233-1240](../app.py#L1233).

Split v4 register dump. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| dump | not annotated | ` (required) ` | Dump; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1240 | dynamic (not annotated) | ` lines ` |

### `is_v4_storage_io_device`

Source: [app.py:1243-1261](../app.py#L1243).

Test v4 storage io device. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| service | not annotated | ` (required) ` | Service; operation-specific input consumed by this function. No stricter schema is declared. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1245 | dynamic (not annotated) | ` any((token in combined for token in ['lsa', 'raid', 'megaraid', 'hba', 'storage adapter', 'storage controller', 'sas/sata', 'b545', 'b540', 'b540p', 'm.2', 'm2', 'raid boot', 'boot adapter', 'nvme'])) ` |

### `is_v4_vroc_io_device`

Source: [app.py:1264-1266](../app.py#L1264).

Test v4 vroc io device. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| service | not annotated | ` (required) ` | Service; operation-specific input consumed by this function. No stricter schema is declared. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1266 | bool | ` 'vroc' in combined or 'virtual raid on cpu' in combined ` |

### `parse_v4_io_drive_line`

Source: [app.py:1269-1296](../app.py#L1269).

Parse v4 io drive line. Literal result/intermediate fields include `bay`, `description`, `drive`, `firmware`, `fru_no`, `l2pt`, `model`, `name`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1272 | NoneType | ` None ` |
| 1282 | dict | ` {'bay': bay, 'res_id': resid.strip(), 'drive': drive.strip(), 'description': parts[0] if len(parts) > 0 else '', 'vendor': parts[-2] if len(parts) > 1 else '', 'name': parts[-1] if parts else '', 'model': parts[-1] if parts else '', 'serial': sn.strip(), 'l2pt': proto, 'fru_no': (pn or '').strip(), 'part_no': (pn or '').strip(), 'firmware': firmware, 'raw': line.strip()} ` |

### `normalize_raid_level`

Source: [app.py:1299-1304](../app.py#L1299).

Normalize raid level. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1303 | str | ` f'RAID {m.group(1).upper()}' ` |
| 1304 | dynamic (not annotated) | ` text ` |

### `parse_v4_virtual_drive_line`

Source: [app.py:1307-1332](../app.py#L1307).

Parse v4 virtual drive line. Delegates to `first_match`, `normalize_raid_level`. Literal result/intermediate fields include `attributes`, `capacity`, `drives`, `raid_level`, `raw`, `res_id`, `status`, `volume`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1310 | NoneType | ` None ` |
| 1323 | dict | ` {'volume': re.sub('\\s+', '', volume.strip()), 'res_id': (resid or '').strip(), 'raid_level': normalize_raid_level(raid_level), 'capacity': capacity.strip(), 'status': first_match('\\bStatus\\s*=?\\s*([^,;]+)', attrs) or '', 'drives': drives, 'attributes': attrs, 'raw': clean} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_v4_io_devices`

Source: [app.py:1335-1400](../app.py#L1335).

Parse v4 io devices. Delegates to `is_v4_storage_io_device`, `is_v4_vroc_io_device`, `parse_v4_io_drive_line`, `parse_v4_virtual_drive_line`. Literal result/intermediate fields include `adapter`, `adapters`, `address`, `backplane_locations`, `controller`, `device_type`, `drives`, `eid`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1400 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `infer_backplane_location`

Source: [app.py:1403-1411](../app.py#L1403).

Infer backplane location. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| description | str | ` '' ` | Description; operation-specific input consumed by this function. No stricter schema is declared. |
| form_factor | str | ` '' ` | Form factor; operation-specific input consumed by this function. No stricter schema is declared. |
| explicit_location | str | ` '' ` | Explicit location; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1406 | str | ` 'Rear' ` |
| 1408 | str | ` 'Front' ` |
| 1411 | str | ` str(explicit_location or '') ` |

### `parse_v4_backplanes_json`

Source: [app.py:1414-1508](../app.py#L1414).

Parse v4 backplanes json. Delegates to `infer_backplane_location`, `parse_sep_info`, `path.read_text`, `split_v4_register_dump`. Literal result/intermediate fields include `bp`, `detected`, `error`, `location`, `name`, `raw`, `sep_info`, `sep_vpd`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| bp_locations | NoneType | ` None ` | Bp locations; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1420 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_capacity_gb`

Source: [app.py:1511-1521](../app.py#L1511).

Parse capacity gb. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1515 | str | ` '' ` |
| 1520 | str | ` f'{gb / 1024:.1f} TB' ` |
| 1521 | str | ` f'{gb:.0f} GB' ` |

### `load_minilog_json`

Source: [app.py:1524-1531](../app.py#L1524).

Load minilog json. Delegates to `read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1531 | JSON value | ` json.loads(text) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `minilog_sections`

Source: [app.py:1534-1546](../app.py#L1534).

Minilog sections. Literal result/intermediate fields include `body`, `header`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| obj | not annotated | ` (required) ` | Obj; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1546 | dynamic (not annotated) | ` sections ` |

### `section_rows`

Source: [app.py:1549-1555](../app.py#L1549).

Section rows. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| sections | not annotated | ` (required) ` | Sections; operation-specific input consumed by this function. No stricter schema is declared. |
| title | not annotated | ` (required) ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1555 | dynamic (not annotated) | ` rows ` |

### `html_breaks_to_text`

Source: [app.py:1558-1559](../app.py#L1558).

Html breaks to text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1559 | str | ` re.sub('<br\\s*/?>', ' \| ', str(value or ''), flags=re.I).strip(' \|') ` |

### `firmware_version_from_v4`

Source: [app.py:1562-1564](../app.py#L1562).

Firmware version from v4. Delegates to `first_match`, `html_breaks_to_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1564 | dynamic (not annotated) | ` first_match('Version\\s*:\\s*([^\|]+)', text) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `analyze_minilog_v4`

Source: [app.py:1567-1745](../app.py#L1567).

Analyze minilog v4. Delegates to `firmware_version_from_v4`, `first_match`, `html_breaks_to_text`, `is_v4_vroc_io_device`, `load_minilog_json`. Literal result/intermediate fields include `FRU`, `adapters`, `api_key_configured`, `bay`, `boards`, `bp`, `build_id`, `controller`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| minilog_path | not annotated | ` (required) ` | Minilog path; operation-specific input consumed by this function. No stricter schema is declared. |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |
| work | not annotated | ` (required) ` | Work; operation-specific input consumed by this function. No stricter schema is declared. |
| extract | not annotated | ` (required) ` | Extract; operation-specific input consumed by this function. No stricter schema is declared. |
| files | not annotated | ` (required) ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1745 | dynamic (not annotated) | ` report ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `safe_extract_tar`

Source: [app.py:1748-1755](../app.py#L1748).

Check resolved member names against the destination then extract the TAR. No explicit extraction filter or expansion quota is supplied in this implementation.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| tar_path | not annotated | ` (required) ` | Tar path; operation-specific input consumed by this function. No stricter schema is declared. |
| dest | not annotated | ` (required) ` | Dest; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Raises directly: `ValueError(f'unsafe archive path: {member.name}')` (line 1754). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 1749 | ` tarfile.open(tar_path) ` |
| 1755 | ` tf.extractall(dest) ` |

### `read_magic`

Source: [app.py:1758-1763](../app.py#L1758).

Read magic. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| size | int | ` 512 ` | Size; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1761 | dynamic (not annotated) | ` fh.read(size) ` |
| 1763 | bytes | ` b'' ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 1760 | ` path.open('rb') ` |

### `looks_like_text_error`

Source: [app.py:1766-1775](../app.py#L1766).

Looks like text error. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1768 | bool | ` sample.startswith(b'<!doctype') or sample.startswith(b'<html') or sample.startswith(b'{') or (b'<title>' in sample) or (b'login' in sample) or (b'error' in sample) ` |

### `unpack_ffdc`

Source: [app.py:1778-1806](../app.py#L1778).

Select the decompressor using magic bytes and suffix, produce ffdc.tar/extract, and reject unexpected login/error payloads or unsupported inputs.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |
| dest | not annotated | ` (required) ` | Dest; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Raises directly: `ValueError(f'unsafe archive path: {member.name}')` (line 1796); `ValueError('downloaded FFDC is not an archive. Jira or FFDC parser may have returned an HTML/JSON login or error page.')` (line 1804); `ValueError('unsupported FFDC format or corrupted archive; expected .tzz, .tar, .tar.zst, .tgz, .tar.gz, or .gz')` (line 1806). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 1783 | ` raw_tar.open('wb') ` |
| 1784 | ` subprocess.run(['lzop', '-dc', str(upload_path)], stdout=out, check=True) ` |
| 1787 | ` raw_tar.open('wb') ` |
| 1788 | ` subprocess.run(['zstd', '-dc', str(upload_path)], stdout=out, check=True) ` |
| 1791 | ` tarfile.open(upload_path, 'r:gz') ` |
| 1797 | ` tf.extractall(dest / 'extract') ` |
| 1798 | ` subprocess.run(['tar', '-cf', str(raw_tar), '-C', str(dest / 'extract'), '.'], check=True) ` |

### `find_file`

Source: [app.py:1809-1818](../app.py#L1809).

Locate file. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| candidates | not annotated | ` (required) ` | Candidates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1813 | dynamic (not annotated) | ` path ` |
| 1818 | NoneType | ` None ` |

### `is_storage_oob_adapter`

Source: [app.py:1821-1826](../app.py#L1821).

Test storage oob adapter. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| adapter | not annotated | ` (required) ` | Adapter; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1824 | bool | ` False ` |
| 1826 | dynamic (not annotated) | ` any((k in name for k in keywords)) ` |

### `is_external_storage_adapter`

Source: [app.py:1840-1846](../app.py#L1840).

E-suffix storage controller models are externally attached storage.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| adapter | not annotated | ` (required) ` | Adapter; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1846 | bool | ` bool(EXTERNAL_STORAGE_MODEL_RE.search(text)) ` |

### `classify_backplane_scope`

Source: [app.py:1849-1898](../app.py#L1849).

Classify the entire report as external storage when any adapter model matches the E-suffix regex; return excluded built-in evidence names.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1867 | dict | ` {'scope': 'mixed_storage', 'applicable': True, 'reason': 'Both external and internal storage adapters were detected. Built-in-backplane evidence remains applicable to the internal storage path, but is not used to diagnose the external path.', 'internal_adapters': adapter_summary(internal), 'external_adapters': adapter_summary(external), 'excluded_evidence_for_external': list(BUILT_IN_BACKPLANE_EVI ` |
| 1880 | dict | ` {'scope': 'external_storage', 'applicable': False, 'reason': 'A storage adapter model ending in E (for example 940-8e) was detected. This is treated as externally attached storage, so built-in-backplane evidence is not applicable.', 'internal_adapters': [], 'external_adapters': adapter_summary(external), 'excluded_evidence': list(BUILT_IN_BACKPLANE_EVIDENCE_FILES)} ` |
| 1891 | dict | ` {'scope': 'built_in_backplane', 'applicable': True, 'reason': 'No E-suffix external storage adapter was identified.', 'internal_adapters': adapter_summary(internal), 'external_adapters': [], 'excluded_evidence': []} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backplane_evidence_applicable`

Source: [app.py:1901-1908](../app.py#L1901).

Backplane evidence applicable. Delegates to `is_external_storage_adapter`, `is_storage_oob_adapter`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| pci | NoneType | ` None ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1908 | bool | ` not external or internal ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_eid_required_adapter`

Source: [app.py:1911-1918](../app.py#L1911).

Test eid required adapter. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| adapter | not annotated | ` (required) ` | Adapter; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1914 | bool | ` False ` |
| 1918 | dynamic (not annotated) | ` any((k in name for k in keywords)) ` |

### `is_network_adapter`

Source: [app.py:1943-1945](../app.py#L1943).

Test network adapter. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| adapter | not annotated | ` (required) ` | Adapter; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1945 | bool | ` bool(NETWORK_ADAPTER_RE.search(text)) ` |

### `read_network_log_excerpt`

Source: [app.py:1948-1956](../app.py#L1948).

Read network log excerpt. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1953 | str | ` '' ` |
| 1956 | str | ` data.decode('utf-8', errors='replace') ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 1950 | ` Path(path).open('rb') ` |

### `clean_network_log_line`

Source: [app.py:1959-1963](../app.py#L1959).

Normalize network log line. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 1962 | str | ` '[sensitive configuration line omitted]' ` |
| 1963 | dynamic (not annotated) | ` text[:500] ` |

### `parse_network_info`

Source: [app.py:1966-2048](../app.py#L1966).

Combine PCI inventory and selected log excerpts into network adapters, interface observations, events and source paths; does not actively probe the machine.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| pci | NoneType | ` None ` | Parsed PCI/controller inventory. |
| files | NoneType | ` None ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2048 | dict | ` {'adapters': adapters, 'interfaces': list(interfaces.values()), 'events': events, 'log_sources': [str(path.relative_to(extract_dir)) if path.is_relative_to(extract_dir) else path.name for path in candidates]} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `eid_missing`

Source: [app.py:2051-2053](../app.py#L2051).

Eid missing. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| eid | not annotated | ` (required) ` | Eid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2053 | bool | ` value in {'', '--', 'n/a', 'na', 'none'} ` |

### `read_mctp_trace_text`

Source: [app.py:2057-2082](../app.py#L2057).

Read mctp trace text. Delegates to `read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| files | not annotated | ` (required) ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2082 | str | ` '\n'.join(parts) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2067 | ` tarfile.open(tgz_path, 'r:gz') ` |

### `flash_history_line_is_pcie`

Source: [app.py:2085-2089](../app.py#L2085).

Flash history line is PCIe. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2088 | bool | ` False ` |
| 2089 | dynamic (not annotated) | ` any((token in low for token in ['pcie', 'hba', 'raid', 'sas', 'sata', 'nvme', 'adapter', 'controller'])) ` |

### `flash_history_line_failed`

Source: [app.py:2092-2100](../app.py#L2092).

Flash history line failed. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2095 | bool | ` False ` |
| 2099 | bool | ` True ` |
| 2100 | dynamic (not annotated) | ` any((token in low for token in [' error ', ': error', 'failed', 'failure', 'fail ', 'timeout', 'timed out', 'aborted', 'rollback'])) ` |

### `parse_flash_history_for_pcie_failures`

Source: [app.py:2103-2134](../app.py#L2103).

Parse flash history for PCIe failures. Delegates to `flash_history_line_failed`, `flash_history_line_is_pcie`. Literal result/intermediate fields include `begin_line`, `device`, `failure_line`, `slot`, `software_id`, `timestamp`, `version`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2106 | dynamic (not annotated) | ` failures ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `normalize_eid_value`

Source: [app.py:2147-2154](../app.py#L2147).

Normalize eid value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2150 | NoneType | ` None ` |
| 2152 | int | ` int(text, 0) ` |

### `pldm_adapter_label`

Source: [app.py:2157-2165](../app.py#L2157).

Pldm adapter label. Delegates to `normalize_eid_value`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| attempt | not annotated | ` (required) ` | Attempt; operation-specific input consumed by this function. No stricter schema is declared. |
| pci | not annotated | ` (required) ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2164 | dynamic (not annotated) | ` f'PCIe Slot {slot}: {name}' if slot and name else name or f'PCIe Slot {slot}' ` |
| 2165 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `adapter_disallows_same_version_update`

Source: [app.py:2168-2171](../app.py#L2168).

The *60 RAID family, such as 960/960W, does not support flat updates.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| device | not annotated | ` (required) ` | Device; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2171 | bool | ` bool(re.search('\\b(?:raid\|megaraid\|storage)\\s+\\d*60w?(?:\\b\|[-\\s])', name)) ` |

### `firmware_update_device_name`

Source: [app.py:2174-2175](../app.py#L2174).

Firmware update device name. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| device | not annotated | ` (required) ` | Device; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2175 | dynamic (not annotated) | ` re.sub('^PCIe\\s+Slot\\s+[^:]+:\\s*', '', str(device or '').strip(), flags=re.I) ` |

### `finalize_pldm_update_attempt`

Source: [app.py:2178-2210](../app.py#L2178).

Finalize PLDM update attempt. Literal result/intermediate fields include `reason`, `severity`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| attempt | not annotated | ` (required) ` | Attempt; operation-specific input consumed by this function. No stricter schema is declared. |
| terminal_line | str | ` '' ` | Terminal line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2180 | NoneType | ` None ` |
| 2210 | dynamic (not annotated) | ` attempt ` |

### `parse_pldm_firmware_updates`

Source: [app.py:2213-2262](../app.py#L2213).

Track PLDM firmware attempts, compatibility responses, component versions and terminal outcomes, enriched with controller identity.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| pci | NoneType | ` None ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2217 | dynamic (not annotated) | ` attempts ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2218 | ` text.replace('\x00', '').splitlines() ` |
| 2218 | ` text.replace('\x00', '') ` |

### `clean_firmware_log_line`

Source: [app.py:2280-2284](../app.py#L2280).

Normalize firmware log line. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2283 | str | ` '[sensitive configuration line omitted]' ` |
| 2284 | dynamic (not annotated) | ` text[:500] ` |

### `bmc_inband_log_files`

Source: [app.py:2287-2301](../app.py#L2287).

Bmc inband log files. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| files | NoneType | ` None ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2301 | dynamic (not annotated) | ` candidates[:MAX_NETWORK_LOG_FILES] ` |

### `bmc_inband_event_stage`

Source: [app.py:2304-2311](../app.py#L2304).

Bmc inband event stage. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2306 | tuple | ` ('Failed', 'Critical') ` |
| 2308 | tuple | ` ('Completed', 'Pass') ` |
| 2310 | tuple | ` ('Started', 'Info') ` |
| 2311 | tuple | ` ('PLDM/MCTP activity', 'Info') ` |

### `parse_bmc_inband_firmware_updates`

Source: [app.py:2314-2371](../app.py#L2314).

Assemble BMC/BMU inband firmware attempts and events from selected update/PLDM/MCTP logs, preserving terminal-state uncertainty.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| files | NoneType | ` None ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2371 | dict | ` {'attempts': attempts, 'events': events[:80], 'log_sources': [str(path.relative_to(extract_dir)) if path.is_relative_to(extract_dir) else path.name for path in bmc_inband_log_files(extract_dir, files)]} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `mctp_relevance_score`

Source: [app.py:2374-2386](../app.py#L2374).

Mctp relevance score. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |
| failure | not annotated | ` (required) ` | Failure; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2386 | dynamic (not annotated) | ` score ` |

### `summarize_mctp_for_flash_failures`

Source: [app.py:2389-2418](../app.py#L2389).

Summarize mctp for flash failures. Delegates to `mctp_relevance_score`. Literal result/intermediate fields include `evidence`, `failure`, `summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| failures | not annotated | ` (required) ` | Failures; operation-specific input consumed by this function. No stricter schema is declared. |
| mctp_text | not annotated | ` (required) ` | Mctp text; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2391 | list | ` [] ` |
| 2418 | dynamic (not annotated) | ` results ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `short_rel`

Source: [app.py:2422-2426](../app.py#L2422).

Short rel. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| root | not annotated | ` (required) ` | Optional raw-evidence root; absence disables raw log tools. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2424 | str | ` str(path.relative_to(root)) ` |
| 2426 | str | ` str(path) ` |

### `read_limited_text`

Source: [app.py:2429-2435](../app.py#L2429).

Read limited text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| limit | dynamic (not annotated) | ` 256 * 1024 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2431 | str | ` '' ` |
| 2433 | str | ` path.read_bytes()[:limit].decode('utf-8', errors='replace') ` |

### `summarize_uefi_text`

Source: [app.py:2442-2469](../app.py#L2442).

Summarize UEFI text. Literal result/intermediate fields include `line`, `link_training`, `nvme`, `option_rom`, `pcie`, `raid`, `source`, `strong`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| max_lines | int | ` 12 ` | Max lines; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2469 | tuple | ` (counts, lines) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2446 | ` text.replace('\x00', '').splitlines() ` |
| 2446 | ` text.replace('\x00', '') ` |

### `parse_uefi_enumeration_lines`

Source: [app.py:2474-2520](../app.py#L2474).

Parse UEFI enumeration lines. Literal result/intermediate fields include `bay`, `evidence`, `root_port`, `slot`, `source`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2520 | tuple | ` (pcie_rows, nvme_rows, mctp_rows) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2481 | ` text.replace('\x00', '').splitlines() ` |
| 2481 | ` text.replace('\x00', '') ` |

### `parse_v4_pcie_inventory`

Source: [app.py:2522-2565](../app.py#L2522).

Parse v4 PCIe inventory. Literal result/intermediate fields include `evidence`, `pcie_device`, `root_port`, `slot`, `source`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2527 | dynamic (not annotated) | ` rows ` |

### `read_uefilog_tgz`

Source: [app.py:2567-2588](../app.py#L2567).

Read UEFIlog tgz. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| limit_per_archive | dynamic (not annotated) | ` 192 * 1024 ` | Limit per archive; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2587 | str | ` f'Unable to read {path.name}: {exc}' ` |
| 2588 | str | ` '\n'.join(chunks) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2571 | ` tarfile.open(path, 'r:*') ` |

### `enrich_uefi_pcie_device_names`

Source: [app.py:2592-2611](../app.py#L2592).

Enrich UEFI PCIe device names. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| uefi | not annotated | ` (required) ` | Uefi; operation-specific input consumed by this function. No stricter schema is declared. |
| pci | not annotated | ` (required) ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2594 | dynamic (not annotated) | ` uefi ` |

### `parse_uefi_boot_logs`

Source: [app.py:2613-2740](../app.py#L2613).

Parse UEFI boot logs. Delegates to `parse_uefi_enumeration_lines`, `parse_v4_pcie_inventory`, `read_limited_text`, `read_uefilog_tgz`, `short_rel`. Literal result/intermediate fields include `file`, `files`, `findings`, `item`, `link_training`, `mctp_root_ports`, `nvme`, `nvme_enumeration`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| files | NoneType | ` None ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2615 | dict | ` {} ` |
| 2732 | dict | ` {'summary': summary, 'findings': findings[:1], 'pcie_enumeration': pcie_enumeration[:80], 'nvme_enumeration': nvme_enumeration[:80], 'mctp_root_ports': mctp_root_ports[:40], 'files': files_rows, 'total_counts': total_counts} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `adapter_name_by_slot`

Source: [app.py:2753-2759](../app.py#L2753).

Adapter name by slot. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| pci | not annotated | ` (required) ` | Parsed PCI/controller inventory. |
| slot | not annotated | ` (required) ` | Slot; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2755 | str | ` '' ` |
| 2758 | bool | ` adapter.get('name', '') or adapter.get('model', '') or '' ` |

### `parse_raid_tty_pcie_link`

Source: [app.py:2762-2786](../app.py#L2762).

Parse raid tty PCIe link. Literal result/intermediate fields include `degraded_speed`, `degraded_width`, `line_no`, `max_speed`, `max_width`, `neg_speed`, `neg_width`, `raw`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| lines | not annotated | ` (required) ` | Lines; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2786 | dynamic (not annotated) | ` rows ` |

### `parse_hex_value`

Source: [app.py:2789-2795](../app.py#L2789).

Parse hex value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2791 | NoneType | ` None ` |
| 2793 | int | ` int(str(value), 16) ` |

### `bit_indexes_from_hex`

Source: [app.py:2798-2802](../app.py#L2798).

Bit indexes from hex. Delegates to `parse_hex_value`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2801 | list | ` [] ` |
| 2802 | list | ` [idx for idx in range(32) if num & 1 << idx] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `compact_indexes`

Source: [app.py:2805-2817](../app.py#L2805).

Compact indexes. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| indexes | not annotated | ` (required) ` | Indexes; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2807 | str | ` '' ` |
| 2817 | str | ` ', '.join(ranges) ` |

### `parse_raid_tty_backplane_detect`

Source: [app.py:2820-2847](../app.py#L2820).

Parse raid tty backplane detect. Delegates to `bit_indexes_from_hex`, `compact_indexes`, `first_match`. Literal result/intermediate fields include `conn_mod`, `flags`, `i2c`, `phys`, `phys_bitmask`, `raw`, `sio_bp_phys`, `sris_drive_presence`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2823 | list | ` [] ` |
| 2847 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `summarize_raid_tty_backplane_detect`

Source: [app.py:2850-2867](../app.py#L2850).

Summarize raid tty backplane detect. Delegates to `parse_hex_value`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2852 | tuple | ` ('Not found', 'No BkplnDetectInfo section found in this TTY log.', '') ` |
| 2864 | tuple | ` ('OK', 'Backplane UBM/I2C path is detected in BkplnDetectInfo.', evidence) ` |
| 2866 | tuple | ` ('Warning', 'UBM mode is not detected. The adapter appears to use SIO/GPIO/SGPIO style backplane detection.', evidence) ` |
| 2867 | tuple | ` ('Warning', 'BkplnDetectInfo exists, but no UBM/I2C or SIO backplane presence was decoded.', evidence) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 2853 | ` row.get('i2c', '').replace('0x', '') ` |
| 2854 | ` row.get('sio_bp_phys', '').replace('0x', '') ` |
| 2855 | ` row.get('sris_drive_presence', '').replace('0x', '') ` |

### `parse_raid_tty_logs`

Source: [app.py:2870-3067](../app.py#L2870).

Parse raid tty logs. Delegates to `adapter_name_by_slot`, `backplane_evidence_applicable`, `first_match`, `parse_raid_tty_backplane_detect`, `parse_raid_tty_pcie_link`. Literal result/intermediate fields include `adapter`, `boot_process`, `conclusion`, `controller_status`, `degradation_type`, `detail`, `evidence`, `findings`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| extract_dir | not annotated | ` (required) ` | Directory containing extracted FFDC source files. |
| pci | NoneType | ` None ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 2873 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `analyze_flash_history_and_mctp`

Source: [app.py:3069-3077](../app.py#L3069).

Analyze flash history and mctp. Delegates to `parse_flash_history_for_pcie_failures`, `read_mctp_trace_text`, `read_text`, `summarize_mctp_for_flash_failures`. Literal result/intermediate fields include `mctp_correlations`, `pcie_update_failures`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| files | not annotated | ` (required) ` | Evidence category-to-path mapping assembled from KEY_PATHS. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3072 | dict | ` {'pcie_update_failures': [], 'mctp_correlations': []} ` |
| 3074 | dict | ` {'pcie_update_failures': failures, 'mctp_correlations': summarize_mctp_for_flash_failures(failures, mctp_text)} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `fpga_register_value`

Source: [app.py:3079-3081](../app.py#L3079).

Fpga register value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| registers | not annotated | ` (required) ` | Registers; operation-specific input consumed by this function. No stricter schema is declared. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3081 | dynamic (not annotated) | ` row.get('value', '') if row else '' ` |

### `fpga_bool`

Source: [app.py:3084-3085](../app.py#L3084).

Fpga bool. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3085 | bool | ` bool(value) and value.lower() not in {'0x00', '0', 'none', ''} ` |

### `parse_fpga_build_section`

Source: [app.py:3088-3105](../app.py#L3088).

Parse fpga build section. Delegates to `first_match`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| title | not annotated | ` (required) ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3092 | dict | ` {} ` |
| 3105 | dynamic (not annotated) | ` fields ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_fpga_on_demand`

Source: [app.py:3108-3206](../app.py#L3108).

Parse fpga on demand. Delegates to `first_match`, `fpga_bool`, `fpga_register_value`, `parse_fpga_build_section`. Literal result/intermediate fields include `description`, `findings`, `item`, `name`, `offset`, `register`, `registers`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3110 | dict | ` {} ` |
| 3206 | dict | ` {'summary': summary, 'status': status, 'findings': findings, 'registers': registers} ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 3111 | ` text.replace('\x00', '') ` |

### `add_check`

Source: [app.py:3208-3215](../app.py#L3208).

Add check. Literal result/intermediate fields include `category`, `conclusion`, `evidence`, `severity`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| checks | not annotated | ` (required) ` | Checks; operation-specific input consumed by this function. No stricter schema is declared. |
| severity | not annotated | ` (required) ` | Severity; operation-specific input consumed by this function. No stricter schema is declared. |
| category | not annotated | ` (required) ` | Category; operation-specific input consumed by this function. No stricter schema is declared. |
| title | not annotated | ` (required) ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |
| conclusion | not annotated | ` (required) ` | Conclusion; operation-specific input consumed by this function. No stricter schema is declared. |
| evidence | str | ` '' ` | Evidence; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `describe_drive_for_conflict`

Source: [app.py:3218-3220](../app.py#L3218).

Describe drive for conflict. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| controller | not annotated | ` (required) ` | Controller; operation-specific input consumed by this function. No stricter schema is declared. |
| drive | not annotated | ` (required) ` | Drive; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3220 | str | ` f'{controller} -> Drive {bay}' ` |

### `is_m2_internal_drive`

Source: [app.py:3223-3225](../app.py#L3223).

Test m2 internal drive. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| drive | not annotated | ` (required) ` | Drive; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3225 | bool | ` bool(re.search('\\bM\\.?2\\s+Drive\\s+\\d+\\b', raw, re.I)) ` |

### `drive_missing_fields`

Source: [app.py:3228-3241](../app.py#L3228).

Drive missing fields. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| drive | not annotated | ` (required) ` | Drive; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3241 | dynamic (not annotated) | ` missing ` |

### `adapter_detail_by_slot`

Source: [app.py:3244-3249](../app.py#L3244).

Adapter detail by slot. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| pci | not annotated | ` (required) ` | Parsed PCI/controller inventory. |
| slot | not annotated | ` (required) ` | Slot; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3248 | dynamic (not annotated) | ` adapter ` |
| 3249 | dict | ` {} ` |

### `parse_pcie_width_from_text`

Source: [app.py:3252-3255](../app.py#L3252).

Parse PCIe width from text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3255 | dynamic (not annotated) | ` int(matches[-1]) if matches else None ` |

### `collect_pcie_link_reasoning`

Source: [app.py:3258-3324](../app.py#L3258).

Collect PCIe link reasoning. Delegates to `adapter_detail_by_slot`, `adapter_name_by_slot`, `parse_pcie_width_from_text`. Literal result/intermediate fields include `adapter`, `downgrade`, `eid`, `likely_area`, `next_action`, `slot`, `tty_evidence`, `uefi_evidence`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3324 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `dbus_value`

Source: [app.py:3327-3331](../app.py#L3327).

Dbus value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| interface | not annotated | ` (required) ` | Interface; operation-specific input consumed by this function. No stricter schema is declared. |
| key | not annotated | ` (required) ` | Key; operation-specific input consumed by this function. No stricter schema is declared. |
| default | str | ` '' ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3330 | dynamic (not annotated) | ` value.get('data', default) ` |
| 3331 | dynamic (not annotated) | ` value ` |

### `analyze_cff_pcie_inventory`

Source: [app.py:3334-3397](../app.py#L3334).

Analyze cff PCIe inventory. Delegates to `dbus_value`, `vpdd_path.read_text`. Literal result/intermediate fields include `card_type`, `cff_presence_evidence`, `fru`, `missing_cards`, `name`, `part_number`, `raid_vpd_cards`, `serial`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| files | not annotated | ` (required) ` | Evidence category-to-path mapping assembled from KEY_PATHS. |
| pci | not annotated | ` (required) ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3397 | dynamic (not annotated) | ` result ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 3343 | ` journal_path.open('r', encoding='utf-8', errors='replace') ` |

### `run_automated_checks`

Source: [app.py:3400-3973](../app.py#L3400).

Evaluate parsed inventories and logs for structured severity/category findings, applying component and backplane scope rules. Findings are parser observations, not proven root causes.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3973 | dynamic (not annotated) | ` checks ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_basic_headers`

Source: [app.py:3976-3982](../app.py#L3976).

Jira basic headers. Literal result/intermediate fields include `Accept`, `Authorization`, `User-Agent`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 3978 | dict | ` {'Authorization': f'Basic {token}', 'Accept': 'application/json', 'User-Agent': 'ThinkSystem-FFDC-Analyzer/1.0'} ` |

### `jira_request_bytes`

Source: [app.py:3985-4033](../app.py#L3985).

Jira request bytes. Delegates to `jira_basic_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |
| accept | str | ` 'application/json' ` | Accept; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4003 | dynamic (not annotated) | ` resp.read(MAX_UPLOAD_BYTES) ` |

Raises directly: `ValueError('Jira login failed. Please check username/password.')` (line 4018); `ValueError('Jira API rate limit (HTTP 429) persisted after automatic retries. Please try again shortly.')` (line 4020); `ValueError('JIRA issue was not found, or this account does not have permission to view it.')` (line 4025); `ValueError('JIRA REST API returned HTTP 404. Please check the JIRA base URL or virtual path.')` (line 4028); `ValueError(f'Jira API request failed with HTTP {exc.code}.')` (line 4031); `ValueError(f'Cannot connect to Jira: {exc.reason}')` (line 4033). Delegated exceptions may also propagate.

Global declarations: `JIRA_REQUEST_NEXT_AT`.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4002 | ` urllib.request.urlopen(req, timeout=45, context=JIRA_SSL_CONTEXT) ` |

### `jira_request_json`

Source: [app.py:4036-4041](../app.py#L4036).

Jira request json. Delegates to `jira_request_bytes`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4039 | JSON value | ` json.loads(data.decode('utf-8', errors='replace')) ` |

Raises directly: `ValueError('Jira API returned invalid JSON.')` (line 4041). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_similar_pat_headers`

Source: [app.py:4044-4055](../app.py#L4044).

Jira similar pat headers. Delegates to `JIRA_SIMILAR_PAT_FILE.read_text`. Literal result/intermediate fields include `Accept`, `Authorization`, `User-Agent`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4051 | dict | ` {'Authorization': f'[REDACTED]', 'Accept': 'application/json', 'User-Agent': 'ThinkSystem-FFDC-Analyzer/1.0'} ` |

Raises directly: `ValueError('Similar JIRA bug search is not configured on this server.')` (line 4050). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_similar_pat_request_json`

Source: [app.py:4058-4094](../app.py#L4058).

Jira similar pat request json. Delegates to `jira_similar_pat_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4072 | JSON value | ` json.loads(data.decode('utf-8', errors='replace')) ` |

Raises directly: `ValueError('Similar JIRA bug search authentication was rejected. Check the server PAT.')` (line 4087); `ValueError('JIRA rate limit persisted after automatic retries. Please try again shortly.')` (line 4089); `ValueError(f'Similar JIRA bug search failed with HTTP {exc.code}.')` (line 4090); `ValueError(f'Cannot connect to JIRA for similar bug search: {exc.reason}')` (line 4092); `ValueError('JIRA returned invalid JSON during similar bug search.')` (line 4094). Delegated exceptions may also propagate.

Global declarations: `JIRA_REQUEST_NEXT_AT`.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4070 | ` urllib.request.urlopen(req, timeout=45, context=JIRA_SSL_CONTEXT) ` |

### `jira_similar_pat_search`

Source: [app.py:4097-4102](../app.py#L4097).

Jira similar pat search. Delegates to `jira_similar_pat_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| jql | not annotated | ` (required) ` | Jql; operation-specific input consumed by this function. No stricter schema is declared. |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| max_results | int | ` 12 ` | Max results; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4102 | bool | ` jira_similar_pat_request_json(url).get('issues') or [] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_export_current_fields_csv`

Source: [app.py:4105-4120](../app.py#L4105).

Use the same CSV (Current fields) endpoint as the JIRA issue navigator.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| filter_id | not annotated | ` (required) ` | Filter id; operation-specific input consumed by this function. No stricter schema is declared. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4114 | dynamic (not annotated) | ` jira_request_bytes(url, username, password, on_rate_limit=on_rate_limit, accept='text/csv,text/plain,*/*') ` |

Raises directly: `ValueError('JIRA filter ID is missing.')` (line 4109). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_save_filter_jql`

Source: [app.py:4123-4154](../app.py#L4123).

Update a saved JIRA filter using authenticated REST; summary generation can call this when tracker project IDs change.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| filter_data | not annotated | ` (required) ` | Filter data; operation-specific input consumed by this function. No stricter schema is declared. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| jql | not annotated | ` (required) ` | Jql; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4147 | dynamic (not annotated) | ` json.loads(data.decode('utf-8', errors='replace')) if data else payload ` |

Raises directly: `ValueError('JIRA filter ID is missing.')` (line 4127); `ValueError('JIRA filter save failed. The configured account needs edit permission for Filter 34570.')` (line 4150); `ValueError(f'JIRA filter save failed with HTTP {exc.code}: {detail[:4000]}')` (line 4152); `ValueError(f'Cannot connect to Jira while saving the filter: {exc.reason}')` (line 4154). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4145 | ` urllib.request.urlopen(req, timeout=45, context=JIRA_SSL_CONTEXT) ` |

### `jira_request_text`

Source: [app.py:4157-4169](../app.py#L4157).

Jira request text. Delegates to `jira_basic_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4163 | str | ` resp.read(MAX_UPLOAD_BYTES).decode('utf-8', errors='replace') ` |

Raises directly: `ValueError('Jira login failed. Please check username/password.')` (line 4166); `ValueError(f'Jira page request failed with HTTP {exc.code}.')` (line 4167); `ValueError(f'Cannot connect to Jira: {exc.reason}')` (line 4169). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4162 | ` urllib.request.urlopen(req, timeout=45, context=JIRA_SSL_CONTEXT) ` |

### `jira_post_comment`

Source: [app.py:4172-4204](../app.py#L4172).

Submit an actual JIRA comment using explicit user credentials; this is a write operation, not an evidence tool.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| comment | not annotated | ` (required) ` | Comment; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4196 | JSON value | ` json.loads(data.decode('utf-8', errors='replace')) ` |
| 4197 | dict | ` {'status': resp.status} ` |

Raises directly: `ValueError('Bug ID is required.')` (line 4177); `ValueError('Jira username and password are required.')` (line 4179); `ValueError('Jira comment is required.')` (line 4181); `ValueError('Jira comment failed. Please check username/password or comment permission.')` (line 4201); `ValueError(f'Jira comment failed with HTTP {exc.code}: {detail[:300]}')` (line 4202); `ValueError(f'Cannot connect to Jira: {exc.reason}')` (line 4204). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4193 | ` urllib.request.urlopen(req, timeout=60, context=JIRA_SSL_CONTEXT) ` |

### `cleanup_jira_sessions`

Source: [app.py:4207-4211](../app.py#L4207).

Clean up JIRA sessions. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `create_jira_session`

Source: [app.py:4214-4224](../app.py#L4214).

Create JIRA session. Delegates to `cleanup_jira_sessions`. Literal result/intermediate fields include `created`, `issue`, `last_used`, `password`, `username`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| issue | str | ` '' ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4224 | dynamic (not annotated) | ` sid ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_jira_session`

Source: [app.py:4227-4233](../app.py#L4227).

Retrieve JIRA session. Delegates to `cleanup_jira_sessions`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| sid | not annotated | ` (required) ` | Sid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4231 | dict | ` {} ` |
| 4233 | dynamic (not annotated) | ` data ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_jira_session_credentials`

Source: [app.py:4236-4238](../app.py#L4236).

Retrieve JIRA session credentials. Delegates to `get_jira_session`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| sid | not annotated | ` (required) ` | Sid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4238 | tuple | ` (data.get('username', ''), data.get('password', '')) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `cleanup_author_sessions`

Source: [app.py:4241-4246](../app.py#L4241).

Clean up author sessions. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `create_author_session`

Source: [app.py:4249-4257](../app.py#L4249).

Create author session. Delegates to `cleanup_author_sessions`. Literal result/intermediate fields include `created`, `last_used`, `username`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4257 | dynamic (not annotated) | ` sid ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_author_session`

Source: [app.py:4260-4266](../app.py#L4260).

Retrieve author session. Delegates to `cleanup_author_sessions`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| sid | not annotated | ` (required) ` | Sid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4264 | dict | ` {} ` |
| 4266 | dynamic (not annotated) | ` data ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_ffdc_attachment`

Source: [app.py:4269-4271](../app.py#L4269).

Test FFDC attachment. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| filename | not annotated | ` (required) ` | Filename; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4271 | dynamic (not annotated) | ` any((lower.endswith(ext) for ext in FFDC_ATTACHMENT_EXTENSIONS)) ` |

### `is_jira_image_attachment`

Source: [app.py:4274-4276](../app.py#L4274).

Test JIRA image attachment. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| filename | not annotated | ` (required) ` | Filename; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4276 | dynamic (not annotated) | ` any((lower.endswith(ext) for ext in JIRA_IMAGE_EXTENSIONS)) ` |

### `sort_ffdc_candidates`

Source: [app.py:4279-4284](../app.py#L4279).

Sort FFDC candidates. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| candidates | not annotated | ` (required) ` | Candidates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4284 | dynamic (not annotated) | ` sorted(candidates, key=rank) ` |

### `get_jira_ffdc_attachments`

Source: [app.py:4287-4299](../app.py#L4287).

Retrieve JIRA FFDC attachments. Delegates to `is_ffdc_attachment`, `sort_ffdc_candidates`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| attachments | not annotated | ` (required) ` | Attachments; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4299 | dynamic (not annotated) | ` sort_ffdc_candidates(candidates) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_jira_ffdc_sources`

Source: [app.py:4302-4314](../app.py#L4302).

Return every distinct FFDC source exposed by a Jira issue.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4314 | dynamic (not annotated) | ` sort_ffdc_candidates(unique) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `SameOriginAuthorizationRedirectHandler.redirect_request`

Source: [app.py:4320-4324](../app.py#L4320).

Redirect request. Delegates to `super().redirect_request`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| req | not annotated | ` (required) ` | Req; operation-specific input consumed by this function. No stricter schema is declared. |
| fp | not annotated | ` (required) ` | Fp; operation-specific input consumed by this function. No stricter schema is declared. |
| code | not annotated | ` (required) ` | Code; operation-specific input consumed by this function. No stricter schema is declared. |
| msg | not annotated | ` (required) ` | Msg; operation-specific input consumed by this function. No stricter schema is declared. |
| headers | not annotated | ` (required) ` | Headers; operation-specific input consumed by this function. No stricter schema is declared. |
| newurl | not annotated | ` (required) ` | Newurl; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4324 | dynamic (not annotated) | ` redirected ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_ffdc_cache_key`

Source: [app.py:4327-4339](../app.py#L4327).

Jira FFDC cache key. Literal result/intermediate fields include `content`, `created`, `filename`, `id`, `issue`, `self`, `size`, `source_type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4339 | dynamic (not annotated) | ` hashlib.sha256(raw.encode('utf-8')).hexdigest() ` |

### `update_report_jira_context`

Source: [app.py:4342-4359](../app.py#L4342).

Update report JIRA context. Literal result/intermediate fields include `attachment`, `attachment_count`, `issue`, `source`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| attachment_name | not annotated | ` (required) ` | Attachment name; operation-specific input consumed by this function. No stricter schema is declared. |
| attachment_count | not annotated | ` (required) ` | Attachment count; operation-specific input consumed by this function. No stricter schema is declared. |
| monitor_job_id | str | ` '' ` | Monitor job id; operation-specific input consumed by this function. No stricter schema is declared. |
| issue_context | NoneType | ` None ` | Issue context; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4359 | dynamic (not annotated) | ` report ` |

### `create_jira_attachment_report`

Source: [app.py:4362-4410](../app.py#L4362).

Create JIRA attachment report. Delegates to `update_report_jira_context`. Literal result/intermediate fields include `adapters`, `api_key_configured`, `attachment_evidence`, `automated_checks`, `boards`, `cpu`, `created_at`, `events`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| issue_context | not annotated | ` (required) ` | Issue context; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4410 | dynamic (not annotated) | ` report ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4375 | ` work.mkdir(parents=True, exist_ok=True) ` |
| 4407 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `load_cached_jira_ffdc_report`

Source: [app.py:4413-4439](../app.py#L4413).

Load cached JIRA FFDC report. Delegates to `(report_dir / 'report.json').read_text`, `cached_report_path.read_text`, `jira_ffdc_cache_key`, `meta_path.read_text`, `update_report_jira_context`. Literal result/intermediate fields include `cached_at`, `key`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |
| attachment_count | not annotated | ` (required) ` | Attachment count; operation-specific input consumed by this function. No stricter schema is declared. |
| monitor_job_id | str | ` '' ` | Monitor job id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4419 | NoneType | ` None ` |
| 4439 | dynamic (not annotated) | ` report ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4432 | ` shutil.rmtree(report_dir) ` |
| 4438 | ` (report_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `save_cached_jira_ffdc_report`

Source: [app.py:4442-4463](../app.py#L4442).

Save cached JIRA FFDC report. Delegates to `jira_ffdc_cache_key`. Literal result/intermediate fields include `attachment`, `cached_at`, `format`, `issue`, `key`, `report_id`, `source_type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4447 | dynamic (not annotated) | ` None ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4449 | ` cache_dir.mkdir(parents=True, exist_ok=True) ` |
| 4452 | ` shutil.rmtree(cached_report_dir) ` |
| 4463 | ` (cache_dir / 'cache.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `restore_cached_jira_ffdc_report_by_id`

Source: [app.py:4466-4502](../app.py#L4466).

Restore cached JIRA FFDC report by id. Delegates to `(report_dir / 'report.json').read_text`, `meta_path.read_text`, `update_report_jira_context`. Literal result/intermediate fields include `cached_at`, `key`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report_id | not annotated | ` (required) ` | Report identifier used for filesystem/metadata lookup. |
| monitor_job_id | str | ` '' ` | Monitor job id; operation-specific input consumed by this function. No stricter schema is declared. |
| issue_key | str | ` '' ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4469 | NoneType | ` None ` |
| 4473 | JSON value | ` json.loads((report_dir / 'report.json').read_text(encoding='utf-8')) ` |
| 4501 | dynamic (not annotated) | ` report ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4489 | ` shutil.rmtree(report_dir) ` |
| 4500 | ` (report_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `iter_text_values`

Source: [app.py:4505-4513](../app.py#L4505).

Iter text values. Delegates to `iter_text_values`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `clean_jira_text`

Source: [app.py:4516-4524](../app.py#L4516).

Normalize JIRA text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4524 | str | ` text.strip() ` |

### `truncate_text`

Source: [app.py:4527-4531](../app.py#L4527).

Truncate text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| limit | int | ` 3000 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4530 | dynamic (not annotated) | ` text ` |
| 4531 | dynamic (not annotated) | ` text[:limit].rstrip() + f'\n... truncated {len(text) - limit} char(s)' ` |

### `extract_jira_reproduce_steps`

Source: [app.py:4534-4560](../app.py#L4534).

Extract JIRA reproduce steps. Delegates to `clean_jira_text`, `iter_text_values`, `truncate_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4550 | dynamic (not annotated) | ` truncate_text(text) ` |
| 4559 | dynamic (not annotated) | ` truncate_text(match.group(1).strip()) ` |
| 4560 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_description`

Source: [app.py:4563-4569](../app.py#L4563).

Extract JIRA description. Delegates to `clean_jira_text`, `iter_text_values`, `truncate_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4568 | dynamic (not annotated) | ` truncate_text(text, 5000) ` |
| 4569 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_named_field`

Source: [app.py:4572-4587](../app.py#L4572).

Extract JIRA named field. Delegates to `clean_jira_text`, `iter_text_values`, `truncate_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |
| name_patterns | NoneType | ` None ` | Name patterns; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 3000 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4586 | dynamic (not annotated) | ` truncate_text(text, limit) ` |
| 4587 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_closure_fields`

Source: [app.py:4590-4611](../app.py#L4590).

Extract JIRA closure fields. Delegates to `extract_jira_named_field`. Literal result/intermediate fields include `build_fixed`, `root_cause_explanation`, `solution_explanation`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4591 | dict | ` {'root_cause_explanation': extract_jira_named_field(fields, field_names, rendered_fields, ['\\broot\\s*cause\\b.*\\bexplanation\\b', '\\brca\\b']), 'solution_explanation': extract_jira_named_field(fields, field_names, rendered_fields, ['\\bsolution\\b.*\\bexplanation\\b', '\\bfix\\b.*\\bexplanation\\b']), 'build_fixed': extract_jira_named_field(fields, field_names, rendered_fields, ['\\bbuild\\s*f ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_defect_action`

Source: [app.py:4614-4626](../app.py#L4614).

Extract JIRA defect action. Delegates to `iter_text_values`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4623 | str | ` 'Limitation Candidate' ` |
| 4625 | str | ` 'Limitation Temporary' ` |
| 4626 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_limitation_status`

Source: [app.py:4629-4643](../app.py#L4629).

Extract JIRA limitation status. Delegates to `clean_jira_text`, `extract_jira_named_field`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4643 | str | ` ' '.join(dict.fromkeys(values)) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_flags`

Source: [app.py:4646-4653](../app.py#L4646).

Extract JIRA flags. Delegates to `extract_jira_named_field`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |
| rendered_fields | NoneType | ` None ` | Rendered fields; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4647 | dynamic (not annotated) | ` extract_jira_named_field(fields, field_names, rendered_fields, ['^flags?$', '^flagged$'], limit=500) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_limitation_state`

Source: [app.py:4656-4663](../app.py#L4656).

Jira limitation state. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4660 | tuple | ` ('', '') ` |
| 4662 | tuple | ` ('approved', 'Limitation Approved / Temporary Candidate') ` |
| 4663 | tuple | ` ('pending', 'Limitation Pending Approval') ` |

### `parse_jira_defect_actions`

Source: [app.py:4666-4679](../app.py#L4666).

Parse JIRA defect actions. Delegates to `clean_jira_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| page_html | not annotated | ` (required) ` | Page html; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4679 | dynamic (not annotated) | ` actions ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_issue_defect_actions`

Source: [app.py:4682-4694](../app.py#L4682).

Jira issue defect actions. Delegates to `jira_request_text`, `parse_jira_defect_actions`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4685 | list | ` [] ` |
| 4694 | dynamic (not annotated) | ` parse_jira_defect_actions(page_html) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_jira_issue_ai_context`

Source: [app.py:4697-4755](../app.py#L4697).

Build JIRA issue ai context. Delegates to `collect_jira_clone_evidence`, `collect_jira_log_archive_evidence`, `extract_jira_assignee`, `extract_jira_attributes`, `extract_jira_blocking`. Literal result/intermediate fields include `assignee`, `attachment_evidence`, `attributes`, `blocking`, `closure_fields`, `created`, `defect_action`, `defect_actions`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | str | ` '' ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | str | ` '' ` | Authentication secret; never include in browser responses or persisted documentation. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |
| auth_headers | NoneType | ` None ` | Optional prebuilt server-side authorization headers; must respect destination-origin policy. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4721 | dict | ` {'key': issue_key, 'summary': fields.get('summary', ''), 'description': extract_jira_description(fields, rendered_fields), 'reproduce_steps': extract_jira_reproduce_steps(fields, field_names, rendered_fields), 'status': (fields.get('status') or {}).get('name', ''), 'priority': extract_jira_priority(fields), 'severity': extract_jira_severity(fields, field_names), 'blocking': extract_jira_blocking(f ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_clone_links`

Source: [app.py:4758-4780](../app.py#L4758).

Extract JIRA clone links. Delegates to `clean_jira_text`. Literal result/intermediate fields include `direction`, `key`, `relation`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4780 | dynamic (not annotated) | ` links ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_issue_detail`

Source: [app.py:4783-4791](../app.py#L4783).

Jira issue detail. Delegates to `jira_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4786 | dict | ` {} ` |
| 4791 | dynamic (not annotated) | ` jira_request_json(url, username, password) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `collect_jira_clone_evidence`

Source: [app.py:4794-4832](../app.py#L4794).

Collect JIRA clone evidence. Delegates to `extract_jira_clone_links`, `extract_jira_closure_fields`, `extract_jira_description`, `extract_jira_reproduce_steps`, `jira_issue_comments`. Literal result/intermediate fields include `closure_fields`, `description`, `direction`, `error`, `issue_key`, `recent_comments`, `relation`, `reproduce_steps`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |
| cache | NoneType | ` None ` | Cache; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 3 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4796 | list | ` [] ` |
| 4832 | dynamic (not annotated) | ` evidence ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_jira_ffdc_data_links`

Source: [app.py:4835-4862](../app.py#L4835).

Retrieve JIRA FFDC data links. Delegates to `iter_text_values`, `sort_ffdc_candidates`. Literal result/intermediate fields include `content`, `filename`, `name`, `source_type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4838 | list | ` [] ` |
| 4862 | dynamic (not annotated) | ` sort_ffdc_candidates(links) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_download_attachment`

Source: [app.py:4864-4919](../app.py#L4864).

Jira download attachment. Delegates to `jira_basic_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |
| max_bytes | dynamic (not annotated) | ` MAX_UPLOAD_BYTES ` | Max bytes; operation-specific input consumed by this function. No stricter schema is declared. |
| auth_headers | NoneType | ` None ` | Optional prebuilt server-side authorization headers; must respect destination-origin policy. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4919 | dynamic (not annotated) | ` upload_path ` |

Raises directly: `ValueError('Jira attachment is larger than the supported limit.')` (line 4892); `ValueError('Jira attachment is larger than the supported limit.')` (line 4899); `ValueError('Jira attachment download failed. Please check login permission.')` (line 4911); `ValueError(f'Jira attachment download failed with HTTP {exc.code}.')` (line 4912); `ValueError(f'Cannot download Jira attachment: {exc.reason}')` (line 4918). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 4885 | ` opener.open(req, timeout=180) ` |
| 4887 | ` urllib.request.urlopen(req, timeout=180, context=JIRA_SSL_CONTEXT) ` |
| 4888 | ` upload_path.open('wb') ` |
| 4907 | ` upload_path.unlink() ` |
| 4915 | ` upload_path.unlink() ` |

### `jira_download_ffdcs`

Source: [app.py:4922-4938](../app.py#L4922).

Jira download FFDCs. Delegates to `build_jira_issue_ai_context`, `get_jira_ffdc_sources`, `jira_download_attachment`, `jira_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4938 | tuple | ` (issue_key, downloads, build_jira_issue_ai_context(issue, username, password)) ` |

Raises directly: `ValueError('Bug ID is required.')` (line 4926); `ValueError('Jira username and password are required.')` (line 4928); `ValueError('没有找到FFDC')` (line 4933). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `cleanup_jira_jobs`

Source: [app.py:4941-4946](../app.py#L4941).

Clean up JIRA jobs. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `set_jira_job`

Source: [app.py:4949-4955](../app.py#L4949).

Update JIRA job. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| **updates | dict | ` (variadic) ` | **updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4953 | dynamic (not annotated) | ` None ` |

### `get_jira_job`

Source: [app.py:4958-4962](../app.py#L4958).

Retrieve JIRA job. Delegates to `cleanup_jira_jobs`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4962 | dynamic (not annotated) | ` dict(job) if job else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `reconstruct_jira_job_from_reports`

Source: [app.py:4965-5007](../app.py#L4965).

Restore a completed JIRA result list after an in-memory job is gone.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 4969 | NoneType | ` None ` |
| 4997 | dict | ` {'id': job_id, 'status': 'done', 'percent': 100, 'message': 'Restored from saved reports', 'created': latest / 1000000000 if latest else time.time(), 'updated': latest / 1000000000 if latest else time.time(), 'issue': issue, 'reports': reports, 'jira_sid': ''} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `cleanup_workspace_upload_jobs`

Source: [app.py:5010-5019](../app.py#L5010).

Clean up workspace upload jobs. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `set_workspace_upload_job`

Source: [app.py:5022-5028](../app.py#L5022).

Update workspace upload job. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| **updates | dict | ` (variadic) ` | **updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5026 | dynamic (not annotated) | ` None ` |

### `get_workspace_upload_job`

Source: [app.py:5031-5035](../app.py#L5031).

Retrieve workspace upload job. Delegates to `cleanup_workspace_upload_jobs`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5035 | dynamic (not annotated) | ` dict(job) if job else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `workspace_report_suggested_questions`

Source: [app.py:5038-5051](../app.py#L5038).

Workspace report suggested questions. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5051 | dynamic (not annotated) | ` questions[:5] ` |

### `run_workspace_upload_job`

Source: [app.py:5054-5075](../app.py#L5054).

Run workspace upload job. Delegates to `analyze_with_capacity`, `cleanup_uploads`, `set_workspace_upload_job`, `workspace_report_suggested_questions`, `workspace_report_summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `start_workspace_upload_job`

Source: [app.py:5078-5096](../app.py#L5078).

Start workspace upload job. Delegates to `cleanup_workspace_upload_jobs`, `threading.Thread(target=run_workspace_upload_job, args=(job_id, upload_path), daemon=True).start`. Literal result/intermediate fields include `created`, `file`, `id`, `message`, `percent`, `status`, `updated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5096 | dynamic (not annotated) | ` job_id ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5091 | ` threading.Thread(target=run_workspace_upload_job, args=(job_id, upload_path), daemon=True).start() ` |

### `jira_find_ffdc_sources`

Source: [app.py:5099-5112](../app.py#L5099).

Jira find FFDC sources. Delegates to `build_jira_issue_ai_context`, `get_jira_ffdc_sources`, `jira_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5112 | tuple | ` (issue_key, sources, issue_context) ` |

Raises directly: `ValueError('Bug ID is required.')` (line 5103); `ValueError('Jira username and password are required.')` (line 5105); `ValueError('No FFDC or supported log archive was found in JIRA.')` (line 5111). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_find_ffdc_sources_with_server_pat`

Source: [app.py:5115-5132](../app.py#L5115).

Read a Bug and its FFDC sources with the server's read-only JIRA PAT.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5132 | tuple | ` (issue_key, sources, issue_context) ` |

Raises directly: `ValueError('Bug ID is required.')` (line 5119). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_server_pat_attachment_headers`

Source: [app.py:5135-5142](../app.py#L5135).

Jira server pat attachment headers. Delegates to `jira_similar_pat_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| download_url | not annotated | ` (required) ` | Download url; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5142 | dynamic (not annotated) | ` headers ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_job_progress`

Source: [app.py:5145-5146](../app.py#L5145).

Jira job progress. Delegates to `set_jira_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| percent | not annotated | ` (required) ` | Percent; operation-specific input consumed by this function. No stricter schema is declared. |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `run_jira_analysis_job`

Source: [app.py:5149-5241](../app.py#L5149).

Run JIRA analysis job. Delegates to `analyze_with_capacity`, `build_jira_report_collection`, `cleanup_reports`, `cleanup_uploads`, `create_jira_attachment_report`. Literal result/intermediate fields include `attachment`, `format`, `id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| use_server_pat | bool | ` False ` | Use server pat; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5185 | dynamic (not annotated) | ` None ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5166 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 5230 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `_collection_path_part`

Source: [app.py:5244-5246](../app.py#L5244).

collection path part. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| fallback | not annotated | ` (required) ` | Fallback; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5246 | bool | ` value[:120] or fallback ` |

### `build_jira_report_collection`

Source: [app.py:5249-5308](../app.py#L5249).

Create one read-only, multi-attachment view for workspace follow-up chat.

Each attachment keeps its own report. The collection only adds hard links to
the already extracted text files, namespaced by attachment, so evidence tools
can search every FFDC without duplicating large archives on disk.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| reports | not annotated | ` (required) ` | Reports; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5258 | NoneType | ` None ` |
| 5308 | dynamic (not annotated) | ` collection ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5262 | ` shutil.rmtree(collection_root, ignore_errors=True) ` |
| 5263 | ` collection_root.mkdir(parents=True, exist_ok=True) ` |
| 5278 | ` destination.parent.mkdir(parents=True, exist_ok=True) ` |
| 5305 | ` report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `start_jira_job`

Source: [app.py:5311-5342](../app.py#L5311).

Start JIRA job. Delegates to `cleanup_jira_jobs`, `thread.start`. Literal result/intermediate fields include `auth_mode`, `created`, `id`, `issue`, `message`, `percent`, `reports`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | str | ` '' ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | str | ` '' ` | Authentication secret; never include in browser responses or persisted documentation. |
| use_server_pat | bool | ` False ` | Use server pat; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5323 | dynamic (not annotated) | ` existing_id ` |
| 5342 | dynamic (not annotated) | ` job_id ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5341 | ` thread.start() ` |

### `cleanup_jira_monitor_jobs`

Source: [app.py:5345-5346](../app.py#L5345).

Clean up JIRA monitor jobs. Delegates to `cleanup_jobs`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `safe_jira_monitor_job_id`

Source: [app.py:5349-5350](../app.py#L5349).

Safe JIRA monitor job id. Delegates to `safe_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5350 | dynamic (not annotated) | ` safe_job_id(job_id) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_monitor_job_path`

Source: [app.py:5353-5354](../app.py#L5353).

Jira monitor job path. Delegates to `job_path`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5354 | dynamic (not annotated) | ` job_path(JIRA_MONITOR_JOB_DIR, job_id) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `persist_jira_monitor_job`

Source: [app.py:5357-5361](../app.py#L5357).

Persist JIRA monitor job. Delegates to `persist_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_jira_monitor_job_from_disk`

Source: [app.py:5364-5365](../app.py#L5364).

Load JIRA monitor job from disk. Delegates to `load_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5365 | dynamic (not annotated) | ` load_job(job_id, JIRA_MONITOR_JOB_DIR, persist=persist_jira_monitor_job) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `set_jira_monitor_job`

Source: [app.py:5368-5375](../app.py#L5368).

Update JIRA monitor job. Delegates to `persist_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| **updates | dict | ` (variadic) ` | **updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5372 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_jira_monitor_job`

Source: [app.py:5378-5389](../app.py#L5378).

Retrieve JIRA monitor job. Delegates to `cleanup_jira_monitor_jobs`, `load_jira_monitor_job_from_disk`, `safe_jira_monitor_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5383 | dict | ` dict(job) ` |
| 5389 | NoneType | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_latest_jira_monitor_job`

Source: [app.py:5392-5394](../app.py#L5392).

Retrieve latest JIRA monitor job. Delegates to `get_jira_monitor_job`, `latest_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5394 | dynamic (not annotated) | ` get_jira_monitor_job(job_id) if job_id else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backfill_jira_monitor_priorities`

Source: [app.py:5397-5423](../app.py#L5397).

Backfill JIRA monitor priorities. Delegates to `extract_jira_priority`, `jira_request_json`, `load_jira_monitor_schedule_config`, `persist_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5401 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backfill_jira_monitor_labels`

Source: [app.py:5426-5455](../app.py#L5426).

Backfill JIRA monitor labels. Delegates to `jira_request_json`, `load_jira_monitor_schedule_config`, `persist_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5430 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backfill_jira_monitor_defect_actions`

Source: [app.py:5458-5486](../app.py#L5458).

Backfill JIRA monitor defect actions. Delegates to `jira_issue_defect_actions`, `load_jira_monitor_schedule_config`, `persist_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5462 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_jira_monitor_schedule_config`

Source: [app.py:5489-5512](../app.py#L5489).

Load JIRA monitor schedule config. Delegates to `JIRA_MONITOR_CONFIG_FILE.read_text`. Literal result/intermediate fields include `enabled`, `password`, `times`, `username`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5512 | dynamic (not annotated) | ` config ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `project_tool_credentials`

Source: [app.py:5515-5519](../app.py#L5515).

Project tool credentials. Delegates to `load_jira_monitor_schedule_config`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fallback_username | str | ` '' ` | Fallback username; operation-specific input consumed by this function. No stricter schema is declared. |
| fallback_password | str | ` '' ` | Fallback password; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5519 | tuple | ` (username.strip(), password) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `project_tool_login`

Source: [app.py:5522-5561](../app.py#L5522).

Project tool login. Literal result/intermediate fields include `Content-Type`, `Referer`, `csrfmiddlewaretoken`, `login`, `next`, `password`, `username`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5561 | tuple | ` (opener, csrf_token) ` |

Raises directly: `ValueError('Project Tool username and password are not configured.')` (line 5524); `ValueError('Project Tool login page did not provide a CSRF token.')` (line 5534); `ValueError('Project Tool login failed. Please check the configured username and password.')` (line 5557); `ValueError('Project Tool login did not create a CSRF session.')` (line 5560). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5531 | ` opener.open(login_url, timeout=30).read().decode('utf-8', 'replace') ` |
| 5531 | ` opener.open(login_url, timeout=30).read() ` |
| 5531 | ` opener.open(login_url, timeout=30) ` |
| 5544 | ` opener.open(urllib.request.Request(f'{PROJECT_TOOL_BASE_URL}/', data=login_data, headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': login_url}), timeout=30) ` |

### `project_tool_project_milestones`

Source: [app.py:5564-5582](../app.py#L5564).

Project tool project milestones. Literal result/intermediate fields include `Content-Type`, `Referer`, `X-CSRFToken`, `X-Requested-With`, `pid`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| opener | not annotated | ` (required) ` | Opener; operation-specific input consumed by this function. No stricter schema is declared. |
| csrf_token | not annotated | ` (required) ` | Csrf token; operation-specific input consumed by this function. No stricter schema is declared. |
| project_id | not annotated | ` (required) ` | Project id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5567 | list | ` [] ` |
| 5582 | bool | ` payload.get('data') or [] ` |

Raises directly: `ValueError('; '.join((str(value) for value in payload.get('errors') or [])))` (line 5581). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5578 | ` opener.open(request, timeout=30) ` |

### `project_tool_project_code_name`

Source: [app.py:5585-5606](../app.py#L5585).

Project tool project code name. Delegates to `clean_jira_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| opener | not annotated | ` (required) ` | Opener; operation-specific input consumed by this function. No stricter schema is declared. |
| project_id | not annotated | ` (required) ` | Project id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5588 | str | ` '' ` |
| 5600 | dynamic (not annotated) | ` clean_jira_text(html.unescape(match.group(1))) ` |
| 5606 | dynamic (not annotated) | ` clean_jira_text(html.unescape(title_match.group(1))) if title_match else '' ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5589 | ` opener.open(f'{PROJECT_TOOL_BASE_URL}/projects/{project_id}/', timeout=30).read().decode('utf-8', 'replace') ` |
| 5589 | ` opener.open(f'{PROJECT_TOOL_BASE_URL}/projects/{project_id}/', timeout=30).read() ` |
| 5589 | ` opener.open(f'{PROJECT_TOOL_BASE_URL}/projects/{project_id}/', timeout=30) ` |

### `project_tool_custom_report_rows`

Source: [app.py:5609-5643](../app.py#L5609).

Load the Project Tool report data behind its Export Page Data button.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| opener | not annotated | ` (required) ` | Opener; operation-specific input consumed by this function. No stricter schema is declared. |
| csrf_token | not annotated | ` (required) ` | Csrf token; operation-specific input consumed by this function. No stricter schema is declared. |
| report_id | dynamic (not annotated) | ` UPCOMING_MILESTONE_REPORT_ID ` | Report identifier used for filesystem/metadata lookup. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5643 | bool | ` payload.get('data') or [] ` |

Raises directly: `ValueError('Upcoming milestone tracker report ID is not configured.')` (line 5613); `ValueError('; '.join((str(value) for value in payload.get('errors') or [])))` (line 5642). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5639 | ` opener.open(request, timeout=45) ` |

### `project_tool_raw_value`

Source: [app.py:5646-5649](../app.py#L5646).

Project tool raw value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5648 | bool | ` value.get('raw') or value.get('human') or value.get('name') or '' ` |
| 5649 | bool | ` value or '' ` |

### `project_tool_ss_date`

Source: [app.py:5652-5662](../app.py#L5652).

Extract the SS plan date from the Upcoming milestone tracker row.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| row | not annotated | ` (required) ` | Row; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5662 | dynamic (not annotated) | ` min(dates) if dates else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `select_current_tracker_projects`

Source: [app.py:5665-5704](../app.py#L5665).

Mirror the provided project-ID script against the live tracker rows.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |
| today | NoneType | ` None ` | Today; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5704 | dynamic (not annotated) | ` sorted(candidates, key=lambda item: (int(item['project_id']), item['project_name'])) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `fetch_current_tracker_projects`

Source: [app.py:5707-5710](../app.py#L5707).

Fetch current tracker projects. Delegates to `project_tool_custom_report_rows`, `project_tool_login`, `select_current_tracker_projects`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5710 | tuple | ` (select_current_tracker_projects(rows), len(rows)) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_milestone_cache`

Source: [app.py:5713-5719](../app.py#L5713).

Load milestone cache. Delegates to `MILESTONE_TRACKER_CACHE_FILE.read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5717 | dynamic (not annotated) | ` payload if isinstance(payload, dict) else {} ` |
| 5719 | dict | ` {} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `save_milestone_cache`

Source: [app.py:5722-5729](../app.py#L5722).

Save milestone cache. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| cache | not annotated | ` (required) ` | Cache; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5726 | ` temp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 5727 | ` temp_path.replace(MILESTONE_TRACKER_CACHE_FILE) ` |

### `fetch_project_milestone_rows`

Source: [app.py:5732-5794](../app.py#L5732).

Fetch project milestone rows. Delegates to `load_milestone_cache`, `project_tool_login`, `project_tool_project_code_name`, `project_tool_project_milestones`, `save_milestone_cache`. Literal result/intermediate fields include `checked_at`, `errors`, `fetched_at`, `project_code_name`, `project_count`, `refreshed_count`, `rows`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| project_ids | not annotated | ` (required) ` | Project ids; operation-specific input consumed by this function. No stricter schema is declared. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5788 | tuple | ` (rows_by_project, names_by_project, {'status': 'ok' if not errors else 'partial', 'checked_at': now, 'project_count': len(project_ids), 'refreshed_count': len(refreshed_ids), 'errors': errors}) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_project_tool_date`

Source: [app.py:5797-5806](../app.py#L5797).

Parse project tool date. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5800 | NoneType | ` None ` |
| 5803 | dynamic (not annotated) | ` datetime.strptime(text, fmt).date() ` |

### `project_refs_from_found`

Source: [app.py:5809-5818](../app.py#L5809).

Project refs from found. Delegates to `next_match.start`. Literal result/intermediate fields include `project_id`, `project_name`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| project_found | not annotated | ` (required) ` | Project found; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5818 | dynamic (not annotated) | ` refs ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 5816 | ` (tail[:next_match.start()] if next_match else tail).strip(' ;,-') ` |
| 5816 | ` next_match.start() ` |

### `select_upcoming_project_milestone`

Source: [app.py:5821-5883](../app.py#L5821).

Select upcoming project milestone. Delegates to `parse_project_tool_date`. Literal result/intermediate fields include `countdown`, `date`, `date_source`, `milestone`, `risk`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |
| project_name | not annotated | ` (required) ` | Project name; operation-specific input consumed by this function. No stricter schema is declared. |
| today | NoneType | ` None ` | Today; operation-specific input consumed by this function. No stricter schema is declared. |
| max_countdown | NoneType | ` None ` | Max countdown; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5883 | dynamic (not annotated) | ` candidates[0] if candidates else {} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `collect_schedule_risks`

Source: [app.py:5886-5952](../app.py#L5886).

Collect schedule risks. Delegates to `fetch_project_milestone_rows`, `project_refs_from_found`, `project_tool_credentials`, `select_upcoming_project_milestone`. Literal result/intermediate fields include `assignee`, `bug`, `checked_at`, `errors`, `project_count`, `project_id`, `project_name`, `project_name_source`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issues | not annotated | ` (required) ` | Issues; operation-specific input consumed by this function. No stricter schema is declared. |
| fallback_username | str | ` '' ` | Fallback username; operation-specific input consumed by this function. No stricter schema is declared. |
| fallback_password | str | ` '' ` | Fallback password; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5896 | tuple | ` ([], {'status': 'ok', 'checked_at': time.time(), 'project_count': 0, 'refreshed_count': 0, 'errors': []}) ` |
| 5952 | tuple | ` (risks, status) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backfill_jira_monitor_schedule_risks`

Source: [app.py:5955-5984](../app.py#L5955).

Backfill JIRA monitor schedule risks. Delegates to `collect_schedule_risks`, `persist_jira_monitor_job`. Literal result/intermediate fields include `checked_at`, `errors`, `project_count`, `refreshed_count`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5965 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backfill_jira_monitor_health`

Source: [app.py:5987-6075](../app.py#L5987).

Backfill JIRA monitor health. Delegates to `extract_jira_attributes`, `extract_jira_blocking`, `extract_jira_duplicate_links`, `extract_jira_field_last_changed`, `extract_jira_named_field`. Literal result/intermediate fields include `checked_at`, `error`, `refreshed_count`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 5989 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_jira_monitor_schedule_state`

Source: [app.py:6078-6083](../app.py#L6078).

Load JIRA monitor schedule state. Delegates to `JIRA_MONITOR_SCHEDULE_STATE_FILE.read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6081 | dynamic (not annotated) | ` data if isinstance(data, dict) else {} ` |
| 6083 | dict | ` {} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `save_jira_monitor_schedule_state`

Source: [app.py:6086-6091](../app.py#L6086).

Save JIRA monitor schedule state. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| state | not annotated | ` (required) ` | State; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 6088 | ` JIRA_MONITOR_JOB_DIR.mkdir(exist_ok=True) ` |
| 6089 | ` JIRA_MONITOR_SCHEDULE_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `reuse_morning_similar_jira_cases`

Source: [app.py:6094-6115](../app.py#L6094).

Copy the completed 05:00 Similar-bug snapshot into the 13:00 review.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| items | not annotated | ` (required) ` | Items; operation-specific input consumed by this function. No stricter schema is declared. |
| today_key | NoneType | ` None ` | Optional host-local date key used to select the same-day morning snapshot. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6100 | tuple | ` ('', 0) ` |
| 6115 | tuple | ` (source_id, copied) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `save_morning_similar_jira_source`

Source: [app.py:6118-6123](../app.py#L6118).

Save morning similar JIRA source. Delegates to `load_jira_monitor_schedule_state`, `safe_jira_monitor_job_id`, `save_jira_monitor_schedule_state`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `reuse_morning_milestone_snapshot`

Source: [app.py:6126-6153](../app.py#L6126).

Reuse 05:00 Project Tool data while retaining fresh 13:00 JIRA fields.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| items | not annotated | ` (required) ` | Items; operation-specific input consumed by this function. No stricter schema is declared. |
| today_key | NoneType | ` None ` | Optional host-local date key used to select the same-day morning snapshot. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6132 | tuple | ` ('', [], {}, {}) ` |
| 6153 | tuple | ` (source_id, risks, milestone_status, schedule_ai_summary) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_transient_jira_monitor_error`

Source: [app.py:6156-6176](../app.py#L6156).

Test transient JIRA monitor error. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| error | not annotated | ` (required) ` | Error; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6176 | dynamic (not annotated) | ` any((marker in message for marker in transient_markers)) ` |

### `schedule_jira_monitor_retry`

Source: [app.py:6179-6205](../app.py#L6179).

Persist a delayed retry for transient scheduled-review failures.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| error | not annotated | ` (required) ` | Error; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6183 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_monitor_progress`

Source: [app.py:6208-6209](../app.py#L6208).

Jira monitor progress. Delegates to `set_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| percent | not annotated | ` (required) ` | Percent; operation-specific input consumed by this function. No stricter schema is declared. |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_filter_issues`

Source: [app.py:6212-6234](../app.py#L6212).

Jira filter issues. Delegates to `jira_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| filter_id | dynamic (not annotated) | ` JIRA_MONITOR_FILTER_ID ` | Filter id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6234 | tuple | ` (filter_data, issues, names) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_search_issues_for_jql`

Source: [app.py:6237-6256](../app.py#L6237).

Jira search issues for jql. Delegates to `jira_request_json`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| jql | not annotated | ` (required) ` | Jql; operation-specific input consumed by this function. No stricter schema is declared. |
| fields | NoneType | ` None ` | JIRA fields mapping or search-field selection according to the call site. |
| max_results | int | ` 100 ` | Max results; operation-specific input consumed by this function. No stricter schema is declared. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6256 | tuple | ` (issues, names) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jql_quote`

Source: [app.py:6259-6260](../app.py#L6259).

Jql quote. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6260 | dynamic (not annotated) | ` '"' + str(value or '').replace('\\', '\\\\').replace('"', '\\"') + '"' ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 6260 | ` str(value or '').replace('\\', '\\\\').replace('"', '\\"') ` |
| 6260 | ` str(value or '').replace('\\', '\\\\') ` |

### `jira_plain_text`

Source: [app.py:6263-6269](../app.py#L6263).

Jira plain text. Delegates to `jira_plain_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6266 | str | ` ' '.join((jira_plain_text(item) for item in preferred if item)) ` |
| 6268 | str | ` ' '.join((jira_plain_text(item) for item in value if item)) ` |
| 6269 | str | ` str(value or '') ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_similarity_title_tokens`

Source: [app.py:6272-6280](../app.py#L6272).

Jira similarity title tokens. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| title | not annotated | ` (required) ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6280 | dynamic (not annotated) | ` [token for token in tokens if token not in stop_words][:12] ` |

### `jira_similarity_title_query_tokens`

Source: [app.py:6283-6317](../app.py#L6283).

Jira similarity title query tokens. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| tokens | not annotated | ` (required) ` | Tokens; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6317 | dynamic (not annotated) | ` selected ` |

### `hydrate_similar_jira_issue_context`

Source: [app.py:6320-6359](../app.py#L6320).

Restore a report's current JIRA title from its Defect Review snapshot or JIRA.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6325 | dynamic (not annotated) | ` context ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `collect_similar_jira_search_terms`

Source: [app.py:6362-6414](../app.py#L6362).

Collect similar JIRA search terms. Delegates to `hydrate_similar_jira_issue_context`, `jira_similarity_title_query_tokens`, `jira_similarity_title_tokens`. Literal result/intermediate fields include `field`, `kind`, `phrase`, `query_tokens`, `title_tokens`, `weight`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6414 | dynamic (not annotated) | ` terms[:3] + ([title_term] if title_term else terms[3:4]) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_issue_similarity_document`

Source: [app.py:6417-6429](../app.py#L6417).

Jira issue similarity document. Delegates to `jira_plain_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6420 | dynamic (not annotated) | ` '\n'.join([jira_plain_text(issue.get('key')), jira_plain_text(fields.get('summary')), jira_plain_text(fields.get('description')), jira_plain_text(fields.get('labels')), jira_plain_text(fields.get('components')), '\n'.join((jira_plain_text(comment.get('body')) for comment in comments[:5]))]).lower() ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `similar_jira_davy_candidate`

Source: [app.py:6432-6443](../app.py#L6432).

Similar JIRA davy candidate. Delegates to `jira_plain_text`, `truncate_text`. Literal result/intermediate fields include `assignee`, `components`, `description`, `key`, `labels`, `priority`, `status`, `summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6434 | dict | ` {'key': jira_plain_text(issue.get('key')), 'summary': jira_plain_text(fields.get('summary')), 'status': jira_plain_text(fields.get('status')), 'priority': jira_plain_text(fields.get('priority')), 'assignee': jira_plain_text(fields.get('assignee')), 'labels': jira_plain_text(fields.get('labels')), 'components': jira_plain_text(fields.get('components')), 'description': truncate_text(jira_plain_text( ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_complete_davy_similar_response`

Source: [app.py:6446-6454](../app.py#L6446).

Test complete davy similar response. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| content | not annotated | ` (required) ` | Content; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6450 | bool | ` False ` |
| 6454 | dynamic (not annotated) | ` not re.search('(?:\\*\\*\|\\b(?:IOSS\|HWDHV\|HWDHPC)-?\|[\\-–—,:])$', last_line, re.I) ` |

### `davy_rank_similar_jira_cases`

Source: [app.py:6457-6498](../app.py#L6457).

Request a complete three-candidate Markdown assessment with engineer and differences, retry an incomplete result once, and fail rather than accept a placeholder.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| current_title | not annotated | ` (required) ` | Current title; operation-specific input consumed by this function. No stricter schema is declared. |
| terms | not annotated | ` (required) ` | Terms; operation-specific input consumed by this function. No stricter schema is declared. |
| candidates | not annotated | ` (required) ` | Candidates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6495 | dict | ` {'status': 'ok', 'content': content, 'model': model} ` |

Raises directly: `RuntimeError('Davy returned no similar-defect assessment.')` (line 6497); `RuntimeError('Davy returned an incomplete similar-defect assessment.')` (line 6498). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `search_similar_jira_cases`

Source: [app.py:6501-6629](../app.py#L6501).

Search narrow title/signature JQL using the server PAT, score candidates, optionally widen PSoC context for Davy, and retain separate deterministic/model results.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6504 | dict | ` {'status': 'empty', 'generated_at': time.time(), 'message': 'No specific controller, backplane, PCIe, or firmware failure signature was found in this FFDC.', 'terms': [], 'cases': []} ` |
| 6623 | dict | ` {'status': 'ok', 'generated_at': time.time(), 'terms': search_terms, 'cases': rows[:12], 'davy': davy} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `append_tracker_projects_to_jql`

Source: [app.py:6632-6660](../app.py#L6632).

Append missing tracker projects to Project/s Affected without removing saved values.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| base_jql | not annotated | ` (required) ` | Base jql; operation-specific input consumed by this function. No stricter schema is declared. |
| tracker_projects | not annotated | ` (required) ` | Tracker projects; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6647 | tuple | ` (str(base_jql or ''), [], sorted(existing_ids, key=int)) ` |
| 6660 | tuple | ` (merged, additions, sorted(existing_ids, key=int)) ` |

Raises directly: `ValueError('JIRA Filter 34570 does not contain a "Project/s Affected in (...)" clause.')` (line 6640). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 6656 | ` match.start('values') ` |

### `invalid_project_ids_from_filter_save_error`

Source: [app.py:6663-6666](../app.py#L6663).

Extract Project/s Affected values rejected by JIRA from a filter-save error.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| error | not annotated | ` (required) ` | Error; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6666 | set | ` set(re.findall("option '\\[(\\d{4,5})\\][^']*' for field 'Project/s Affected' does not exist", text)) ` |

### `validate_tracker_project_jql`

Source: [app.py:6669-6703](../app.py#L6669).

Use only Project Tool values that are valid JIRA Project/s Affected options.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| base_jql | not annotated | ` (required) ` | Base jql; operation-specific input consumed by this function. No stricter schema is declared. |
| additions | not annotated | ` (required) ` | Additions; operation-specific input consumed by this function. No stricter schema is declared. |
| on_rate_limit | NoneType | ` None ` | Optional callback invoked before rate-limit retry waits. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6676 | tuple | ` (issues, field_names, additions, [], query_jql) ` |
| 6703 | tuple | ` (issues, field_names, valid, skipped, query_jql) ` |

Raises directly: `None` (line 6679); `None` (line 6693). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_project_ids_from_jql`

Source: [app.py:6706-6720](../app.py#L6706).

Return Project Tool IDs embedded in the saved JIRA filter.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| jql_text | not annotated | ` (required) ` | Jql text; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6720 | dynamic (not annotated) | ` sorted(project_ids, key=int) ` |

### `cleanup_current_status_summary_jobs`

Source: [app.py:6723-6732](../app.py#L6723).

Clean up current status summary jobs. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `safe_current_status_summary_job_id`

Source: [app.py:6735-6736](../app.py#L6735).

Safe current status summary job id. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6736 | dynamic (not annotated) | ` re.sub('[^A-Za-z0-9_-]', '', str(job_id or '')) ` |

### `current_status_summary_job_path`

Source: [app.py:6739-6741](../app.py#L6739).

Current status summary job path. Delegates to `safe_current_status_summary_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6741 | dynamic (not annotated) | ` CURRENT_STATUS_SUMMARY_DIR / f'{safe_id}.json' if safe_id else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `persist_current_status_summary_job`

Source: [app.py:6744-6759](../app.py#L6744).

Persist current status summary job. Delegates to `current_status_summary_job_path`, `safe_current_status_summary_job_id`. Literal result/intermediate fields include `job_id`, `updated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6747 | dynamic (not annotated) | ` None ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 6749 | ` CURRENT_STATUS_SUMMARY_DIR.mkdir(exist_ok=True) ` |
| 6752 | ` path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 6754 | ` (CURRENT_STATUS_SUMMARY_DIR / 'latest.json').write_text(json.dumps({'job_id': job_id, 'updated': job.get('updated', time.time())}, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `load_current_status_summary_job_from_disk`

Source: [app.py:6762-6784](../app.py#L6762).

Load current status summary job from disk. Delegates to `current_status_summary_job_path`, `path.read_text`, `persist_current_status_summary_job`, `safe_current_status_summary_job_id`. Literal result/intermediate fields include `error`, `message`, `percent`, `status`, `updated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6765 | NoneType | ` None ` |
| 6784 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `set_current_status_summary_job`

Source: [app.py:6787-6794](../app.py#L6787).

Update current status summary job. Delegates to `persist_current_status_summary_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| **updates | dict | ` (variadic) ` | **updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6791 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_current_status_summary_job`

Source: [app.py:6797-6808](../app.py#L6797).

Retrieve current status summary job. Delegates to `cleanup_current_status_summary_jobs`, `load_current_status_summary_job_from_disk`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6802 | dict | ` dict(job) ` |
| 6808 | NoneType | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_latest_current_status_summary_job`

Source: [app.py:6811-6818](../app.py#L6811).

Retrieve latest current status summary job. Delegates to `get_current_status_summary_job`, `latest_path.read_text`, `safe_current_status_summary_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6816 | NoneType | ` None ` |
| 6818 | dynamic (not annotated) | ` get_current_status_summary_job(job_id) if job_id else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_running_current_status_summary_job`

Source: [app.py:6821-6826](../app.py#L6821).

Retrieve running current status summary job. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6825 | NoneType | ` None ` |
| 6826 | dict | ` dict(min(running, key=lambda item: float(item.get('created') or 0))) ` |

### `has_running_current_status_summary_job`

Source: [app.py:6829-6830](../app.py#L6829).

Test whether there is running current status summary job. Delegates to `get_running_current_status_summary_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6830 | bool | ` get_running_current_status_summary_job() is not None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `current_status_summary_progress`

Source: [app.py:6833-6838](../app.py#L6833).

Current status summary progress. Delegates to `set_current_status_summary_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| percent | not annotated | ` (required) ` | Percent; operation-specific input consumed by this function. No stricter schema is declared. |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `normalize_current_status_summary_rows`

Source: [app.py:6841-6869](../app.py#L6841).

Normalize current status summary rows. Delegates to `clean_jira_text`, `current_status_display_tags`, `extract_jira_assignee`, `extract_jira_attributes`, `extract_jira_blocking`. Literal result/intermediate fields include `action`, `assignee`, `attributes`, `blocking`, `display_tags`, `key`, `labels`, `limitation_status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issues | not annotated | ` (required) ` | Issues; operation-specific input consumed by this function. No stricter schema is declared. |
| field_names | not annotated | ` (required) ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6869 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `normalize_current_status_csv_rows`

Source: [app.py:6872-6909](../app.py#L6872).

Convert JIRA CSV (Current fields) data into the summary row shape.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| payload | not annotated | ` (required) ` | Payload; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6909 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `current_status_display_tags`

Source: [app.py:6912-6927](../app.py#L6912).

Current status display tags. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| labels | not annotated | ` (required) ` | Labels; operation-specific input consumed by this function. No stricter schema is declared. |
| attributes | not annotated | ` (required) ` | Attributes; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 6927 | str | ` ', '.join(dict.fromkeys(display_tags)) ` |

### `run_current_status_summary_job`

Source: [app.py:6930-7037](../app.py#L6930).

Read Project Tool tracker projects, conditionally update the saved JIRA filter, export current JIRA fields, normalize rows and persist summary state.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Raises directly: `ValueError('Scheduled JIRA credentials are not configured.')` (line 6936); `None` (line 6976). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `start_current_status_summary_job`

Source: [app.py:7040-7061](../app.py#L7040).

Start current status summary job. Delegates to `cleanup_current_status_summary_jobs`, `get_running_current_status_summary_job`, `persist_current_status_summary_job`, `threading.Thread(target=run_current_status_summary_job, args=(job_id,), daemon=True).start`. Literal result/intermediate fields include `created`, `id`, `message`, `parent_job_id`, `percent`, `rows`, `scheduled`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| scheduled | bool | ` False ` | Scheduled; operation-specific input consumed by this function. No stricter schema is declared. |
| trigger | str | ` 'manual' ` | Trigger; operation-specific input consumed by this function. No stricter schema is declared. |
| parent_job_id | str | ` '' ` | Parent job id; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7044 | dynamic (not annotated) | ` running_job.get('id', '') ` |
| 7061 | dynamic (not annotated) | ` job_id ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7060 | ` threading.Thread(target=run_current_status_summary_job, args=(job_id,), daemon=True).start() ` |

### `jira_issue_comments`

Source: [app.py:7064-7095](../app.py#L7064).

Jira issue comments. Delegates to `jira_request_json`. Literal result/intermediate fields include `author`, `body`, `created`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| issue_key | str | ` '' ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | str | ` '' ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | str | ` '' ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7095 | dynamic (not annotated) | ` comments ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_image_attachments`

Source: [app.py:7098-7113](../app.py#L7098).

Jira image attachments. Delegates to `is_jira_image_attachment`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7113 | dynamic (not annotated) | ` images[:MAX_JIRA_OCR_IMAGES] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_image_ocr_cache_key`

Source: [app.py:7116-7127](../app.py#L7116).

Jira image ocr cache key. Literal result/intermediate fields include `content`, `created`, `filename`, `id`, `issue`, `size`, `version`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7127 | dynamic (not annotated) | ` hashlib.sha256(raw.encode('utf-8')).hexdigest() ` |

### `normalize_jira_ocr_text`

Source: [app.py:7130-7142](../app.py#L7130).

Normalize JIRA ocr text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 5000 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7142 | dynamic (not annotated) | ` '\n'.join(lines).strip()[:limit] ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7133 | ` str(value or '').replace('\r', '\n').split('\n') ` |
| 7133 | ` str(value or '').replace('\r', '\n') ` |

### `download_jira_image_attachment`

Source: [app.py:7145-7181](../app.py#L7145).

Download JIRA image attachment. Delegates to `jira_basic_headers`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |
| auth_headers | NoneType | ` None ` | Optional prebuilt server-side authorization headers; must respect destination-origin policy. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7178 | dynamic (not annotated) | ` target ` |

Raises directly: `ValueError('JIRA image attachment has no download URL')` (line 7153); `ValueError(f'JIRA image attachment is larger than {MAX_JIRA_IMAGE_BYTES // (1024 * 1024)} MB')` (line 7169); `ValueError(f'JIRA image attachment is larger than {MAX_JIRA_IMAGE_BYTES // (1024 * 1024)} MB')` (line 7176); `None` (line 7181). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7154 | ` UPLOAD_DIR.mkdir(exist_ok=True) ` |
| 7166 | ` urllib.request.urlopen(request, timeout=90, context=JIRA_SSL_CONTEXT) ` |
| 7166 | ` target.open('wb') ` |
| 7180 | ` target.unlink(missing_ok=True) ` |

### `run_jira_attachment_ocr`

Source: [app.py:7184-7206](../app.py#L7184).

Run JIRA attachment ocr. Delegates to `normalize_jira_ocr_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_path | not annotated | ` (required) ` | Image path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7186 | str | ` '' ` |
| 7206 | dynamic (not annotated) | ` best ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7190 | ` subprocess.run(['tesseract', str(image_path), 'stdout', '-l', 'eng+chi_sim', '--psm', page_mode], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45, check=False) ` |

### `jira_image_vision_mime_type`

Source: [app.py:7209-7210](../app.py#L7209).

Jira image vision mime type. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_path | not annotated | ` (required) ` | Image path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7210 | dynamic (not annotated) | ` JIRA_VISION_IMAGE_MIME_TYPES.get(Path(image_path).suffix.lower(), '') ` |

### `jira_attachment_author`

Source: [app.py:7213-7220](../app.py#L7213).

Jira attachment author. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7215 | bool | ` author.get('displayName') or author.get('name') or author.get('emailAddress') or 'JIRA Engineer' ` |

### `jira_image_comment`

Source: [app.py:7223-7267](../app.py#L7223).

Reuse cached attachment interpretation or download an image, try vision then OCR, remove the temporary image and cache the resulting attributed evidence.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |
| auth_headers | NoneType | ` None ` | Optional prebuilt server-side authorization headers; must respect destination-origin policy. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7229 | dynamic (not annotated) | ` cached ` |
| 7252 | dict | ` {} ` |
| 7267 | dynamic (not annotated) | ` comment ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7250 | ` image_path.unlink(missing_ok=True) ` |
| 7263 | ` JIRA_OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True) ` |
| 7264 | ` cache_path.write_text(json.dumps(comment, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `merge_jira_attachment_comments`

Source: [app.py:7270-7299](../app.py#L7270).

Merge JIRA attachment comments. Delegates to `jira_image_attachments`, `jira_image_comment`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| comments | NoneType | ` None ` | Comments; operation-specific input consumed by this function. No stricter schema is declared. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |
| auth_headers | NoneType | ` None ` | Optional prebuilt server-side authorization headers; must respect destination-origin policy. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7280 | dynamic (not annotated) | ` merged ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_jira_log_archive`

Source: [app.py:7302-7304](../app.py#L7302).

Test JIRA log archive. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| filename | not annotated | ` (required) ` | Filename; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7304 | dynamic (not annotated) | ` any((lower.endswith(ext) for ext in JIRA_LOG_ARCHIVE_EXTENSIONS)) ` |

### `jira_log_archive_attachments`

Source: [app.py:7307-7322](../app.py#L7307).

Jira log archive attachments. Delegates to `is_jira_log_archive`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7322 | dynamic (not annotated) | ` archives[:MAX_JIRA_LOG_ARCHIVES] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_log_archive_cache_key`

Source: [app.py:7325-7336](../app.py#L7325).

Jira log archive cache key. Literal result/intermediate fields include `content`, `created`, `filename`, `id`, `issue`, `size`, `version`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7336 | dynamic (not annotated) | ` hashlib.sha256(raw.encode('utf-8')).hexdigest() ` |

### `safe_archive_member_path`

Source: [app.py:7339-7343](../app.py#L7339).

Safe archive member path. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7342 | bool | ` False ` |
| 7343 | dynamic (not annotated) | ` all((part not in {'', '.', '..'} for part in text.split('/'))) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7340 | ` str(value or '').replace('\\', '/').strip() ` |
| 7340 | ` str(value or '').replace('\\', '/') ` |

### `list_7z_archive_entries`

Source: [app.py:7346-7384](../app.py#L7346).

List 7z archive entries. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| archive_path | not annotated | ` (required) ` | Archive path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7384 | dynamic (not annotated) | ` entries ` |

Raises directly: `ValueError('Cannot inspect JIRA log archive: ' + detail[:300])` (line 7358). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7347 | ` subprocess.run(['7z', 'l', '-slt', '-ba', str(archive_path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90, check=False) ` |

### `validate_jira_log_archive`

Source: [app.py:7387-7419](../app.py#L7387).

Validate JIRA log archive. Delegates to `list_7z_archive_entries`, `safe_archive_member_path`. Literal result/intermediate fields include `file_count`, `total_size`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| archive_path | not annotated | ` (required) ` | Archive path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7419 | dict | ` {'file_count': file_count, 'total_size': total_size} ` |

Raises directly: `ValueError('JIRA log archive contains no readable entries.')` (line 7390); `ValueError(f'Unsafe path in JIRA log archive: {member[:160]}')` (line 7396); `ValueError('Encrypted JIRA log archives are not supported.')` (line 7398); `ValueError(f'Links are not supported in JIRA log archives: {member[:160]}')` (line 7405); `ValueError(f'JIRA log archive contains more than {MAX_JIRA_LOG_FILES} files.')` (line 7416); `ValueError('JIRA log archive expands beyond the supported size limit.')` (line 7418). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_log_file_priority`

Source: [app.py:7454-7466](../app.py#L7454).

Jira log file priority. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7466 | tuple | ` (-score, lower) ` |

### `read_jira_log_text`

Source: [app.py:7469-7482](../app.py#L7469).

Read JIRA log text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7473 | str | ` '' ` |
| 7482 | dynamic (not annotated) | ` text ` |

### `clean_jira_log_line`

Source: [app.py:7485-7491](../app.py#L7485).

Normalize JIRA log line. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 500 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7488 | str | ` '' ` |
| 7490 | str | ` '[sensitive configuration line omitted]' ` |
| 7491 | dynamic (not annotated) | ` text[:limit] ` |

### `analyze_jira_log_archive`

Source: [app.py:7494-7605](../app.py#L7494).

Analyze JIRA log archive. Delegates to `clean_jira_log_line`, `jira_attachment_author`, `read_jira_log_text`, `validate_jira_log_archive`. Literal result/intermediate fields include `archive_files`, `archive_size_bytes`, `author`, `boot_evidence`, `boot_hits`, `created`, `error_evidence`, `error_hits`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| archive_path | not annotated | ` (required) ` | Archive path; operation-specific input consumed by this function. No stricter schema is declared. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7591 | dict | ` {'status': 'ok', 'filename': attachment.get('filename') or attachment.get('name') or archive_path.name, 'author': jira_attachment_author(attachment), 'created': attachment.get('created', ''), 'archive_files': listed.get('file_count', len(files)), 'archive_size_bytes': archive_path.stat().st_size, 'extracted_size_bytes': extracted_size, 'text_files_scanned': scanned, 'groups': groups[:30], 'notable ` |

Raises directly: `ValueError('Cannot extract JIRA log archive: ' + detail[:300])` (line 7510); `ValueError('Extracted JIRA log archive exceeds the supported safety limit.')` (line 7527). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7498 | ` extract_dir.mkdir() ` |
| 7499 | ` subprocess.run(['7z', 'x', '-y', '-bd', '-bb0', f'-o{extract_dir}', str(archive_path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240, check=False) ` |

### `jira_log_archive_evidence`

Source: [app.py:7608-7636](../app.py#L7608).

Jira log archive evidence. Delegates to `analyze_jira_log_archive`, `cache_path.read_text`, `jira_download_attachment`, `jira_log_archive_cache_key`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7615 | dynamic (not annotated) | ` cached ` |
| 7636 | dynamic (not annotated) | ` evidence ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 7629 | ` archive_path.unlink(missing_ok=True) ` |
| 7632 | ` JIRA_ATTACHMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True) ` |
| 7633 | ` cache_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `collect_jira_log_archive_evidence`

Source: [app.py:7639-7653](../app.py#L7639).

Collect JIRA log archive evidence. Delegates to `jira_log_archive_attachments`, `jira_log_archive_evidence`. Literal result/intermediate fields include `error`, `filename`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7641 | list | ` [] ` |
| 7653 | dynamic (not annotated) | ` evidence ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_resolution_signals`

Source: [app.py:7656-7671](../app.py#L7656).

Extract resolution signals. Delegates to `clean_jira_text`, `truncate_text`. Literal result/intermediate fields include `author`, `created`, `evidence`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| comments | not annotated | ` (required) ` | Comments; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7671 | dynamic (not annotated) | ` signals[-5:] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `find_project_affected`

Source: [app.py:7674-7684](../app.py#L7674).

Locate project affected. Delegates to `iter_text_values`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7684 | str | ` '; '.join(candidates[:3]) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_project_found`

Source: [app.py:7687-7708](../app.py#L7687).

Extract JIRA project found. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7693 | dynamic (not annotated) | ` text ` |
| 7704 | str | ` '; '.join(parts) ` |
| 7708 | dynamic (not annotated) | ` ((fields or {}).get('project') or {}).get('name', '') ` |

### `extract_jira_assignee`

Source: [app.py:7711-7720](../app.py#L7711).

Extract JIRA assignee. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7714 | str | ` 'Unassigned' ` |
| 7715 | bool | ` assignee.get('displayName') or assignee.get('name') or assignee.get('emailAddress') or 'Unassigned' ` |

### `extract_jira_priority`

Source: [app.py:7723-7732](../app.py#L7723).

Extract JIRA priority. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7726 | bool | ` priority.get('name') or priority.get('value') or priority.get('id') or '' ` |
| 7732 | str | ` str(priority or '') ` |

### `extract_jira_severity`

Source: [app.py:7735-7767](../app.py#L7735).

Extract JIRA severity. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7748 | str | ` str(value.get('value') or value.get('name') or value.get('displayName') or '').strip() ` |
| 7755 | str | ` ', '.join((str(item.get('value') or item.get('name') or item.get('displayName') or '').strip() if isinstance(item, dict) else str(item or '').strip() for item in value if item)) ` |
| 7767 | str | ` str(value or '').strip() ` |

### `extract_jira_blocking`

Source: [app.py:7770-7803](../app.py#L7770).

Return the JIRA Blocking custom-field value without inferring it from priority.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7784 | str | ` str(value.get('value') or value.get('name') or value.get('displayName') or '').strip() ` |
| 7791 | str | ` ', '.join((str(item.get('value') or item.get('name') or item.get('displayName') or '').strip() if isinstance(item, dict) else str(item or '').strip() for item in value if item)) ` |
| 7803 | str | ` str(value or '').strip() ` |

### `extract_jira_attributes`

Source: [app.py:7806-7841](../app.py#L7806).

Extract JIRA attributes. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |
| field_names | NoneType | ` None ` | Field names; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7819 | str | ` ', '.join((str(item).strip() for item in (value.get('value'), value.get('name'), value.get('displayName')) if item)) ` |
| 7829 | str | ` ', '.join((str(item.get('value') or item.get('name') or item.get('displayName') or '').strip() if isinstance(item, dict) else str(item or '').strip() for item in value if item)) ` |
| 7841 | str | ` str(value or '').strip() ` |

### `extract_jira_status_since`

Source: [app.py:7844-7861](../app.py#L7844).

Extract JIRA status since. Delegates to `parse_jira_datetime`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| current_status | str | ` '' ` | Current status; operation-specific input consumed by this function. No stricter schema is declared. |
| created | str | ` '' ` | Created; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7859 | dynamic (not annotated) | ` max(transitions).isoformat() ` |
| 7861 | dynamic (not annotated) | ` parsed_created.isoformat() if parsed_created is not None else '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_field_last_changed`

Source: [app.py:7864-7876](../app.py#L7864).

Extract JIRA field last changed. Delegates to `parse_jira_datetime`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |
| field_patterns | not annotated | ` (required) ` | Field patterns; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7876 | dynamic (not annotated) | ` max(changed).isoformat() if changed else '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `extract_jira_duplicate_links`

Source: [app.py:7879-7902](../app.py#L7879).

Extract JIRA duplicate links. Literal result/intermediate fields include `key`, `role`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fields | not annotated | ` (required) ` | JIRA fields mapping or search-field selection according to the call site. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7902 | dynamic (not annotated) | ` links ` |

### `compact_monitor_report`

Source: [app.py:7905-7921](../app.py#L7905).

Compact monitor report. Delegates to `build_ffdc_evidence_chain`, `compact_report_for_ai`. Literal result/intermediate fields include `adapters`, `automated_checks`, `backplane_scope`, `backplanes`, `evidence_chain`, `firmware`, `format`, `report_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7907 | dict | ` {} ` |
| 7909 | dict | ` {'report_id': report.get('id', ''), 'source_file': report.get('source_file', ''), 'format': report.get('format', ''), 'system': ctx.get('system', {}), 'firmware': ctx.get('firmware', {}), 'automated_checks': ctx.get('automated_checks', [])[:12], 'adapters': ctx.get('adapters', [])[:8], 'storage': ctx.get('storage', [])[:8], 'backplanes': ctx.get('backplanes', [])[:8], 'backplane_scope': ctx.get('b ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_ffdc_evidence_chain`

Source: [app.py:7924-7981](../app.py#L7924).

Build FFDC evidence chain. Delegates to `truncate_text`. Literal result/intermediate fields include `adapter`, `adapter_inventory`, `bmc_pcie_events`, `category`, `conclusion`, `direct_critical_checks`, `eid`, `evidence`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7968 | dict | ` {'direct_critical_checks': critical_checks[:8], 'bmc_pcie_events': bmc_pcie_events[:8], 'uefi_pcie_enumeration': (uefi.get('pcie_enumeration', []) or [])[:16], 'raid_tty_pcie': tty_rows[:8], 'adapter_inventory': [{'slot': adapter.get('slot', ''), 'name': adapter.get('name', ''), 'eid': adapter.get('eid', '')} for adapter in (pci.get('adapters', []) or [])[:16]]} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `issue_ai_relevance_profile`

Source: [app.py:7984-7998](../app.py#L7984).

Issue ai relevance profile. Literal result/intermediate fields include `pcie`, `supercap`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 7989 | dict | ` {'pcie': bool(re.search('\\b(?:pcie\|pci-e\|link training\|bar init\|bar initialization\|root port\|enumerat\\w*\|can\\s*not\\s*recognize\|cannot\\s*recognize\|card\\s+(?:is\\s+)?(?:lost\|missing)\|adapter\\s+(?:is\\s+)?(?:lost\|missing\|not detected)\|raid\\s+card\\s+(?:is\\s+)?(?:lost\|missing))\\b', text, re.I)), 'supercap': bool(re.search('\\b(?:supercap\|capacitor\|cachevault\|cvpm\|bbu\|battery)\\b', text, re.I ` |

### `filter_monitor_ffdc_for_issue`

Source: [app.py:8001-8027](../app.py#L8001).

Keep only FFDC checks that the issue text permits Davy to treat as evidence.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| summary | not annotated | ` (required) ` | Summary; operation-specific input consumed by this function. No stricter schema is declared. |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8027 | dynamic (not annotated) | ` summary ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_jira_monitor_prompt`

Source: [app.py:8030-8092](../app.py#L8030).

Build JIRA monitor prompt. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8031 | dynamic (not annotated) | ` "You are the primary Lenovo ThinkSystem RAID/storage investigation engineer. Review this JIRA defect using the title, Description, status, project information, Reproduce Steps, closure fields, comments, and optional FFDC parsed evidence. First establish the event chronology and separate observed facts from engineer conclusions and your own hypotheses. Return concise English Markdown with exactly n ` |

### `build_jira_monitor_evidence_prompt`

Source: [app.py:8095-8122](../app.py#L8095).

Build JIRA monitor evidence prompt. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8096 | dynamic (not annotated) | ` "You are the evidence analyst for a Lenovo ThinkSystem RAID/storage defect review. Build an internal evidence brief only. Do not recommend actions, tests, commands, fixes, replacements, or log-collection procedures.\n\nReturn these compact sections:\n1. Issue domain: classify the component and software/hardware layer from title, Description, and Reproduce Steps.\n2. Reported symptom and trigger: q ` |

### `build_jira_monitor_review_prompt`

Source: [app.py:8125-8164](../app.py#L8125).

Build JIRA monitor review prompt. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |
| evidence_brief | not annotated | ` (required) ` | Evidence brief; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8126 | dynamic (not annotated) | ` "You are the senior reviewer for a Lenovo ThinkSystem RAID/storage defect investigation. Use the internal evidence brief and complete JIRA/FFDC JSON below to produce the final recommendation. Correct unsupported conclusions, stale conclusions, source mixing, chronology errors, and generic actions.\n\nReviewer checklist:\n- First identify the reported issue domain from the title, Description, and R ` |

### `generate_jira_monitor_ai_summary`

Source: [app.py:8167-8195](../app.py#L8167).

Generate JIRA monitor ai summary. Delegates to `build_jira_monitor_evidence_prompt`, `build_jira_monitor_review_prompt`, `call_ai_prompt`, `is_transient_ai_error`. Literal result/intermediate fields include `content`, `error`, `model`, `primary_model`, `review_error`, `reviewed`, `status`, `transient`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8173 | dict | ` {'status': 'error', 'transient': is_transient_ai_error(exc), 'error': str(exc), 'content': ''} ` |
| 8181 | dict | ` {'status': 'ok', 'model': review_model, 'primary_model': model, 'reviewed': True, 'content': content} ` |
| 8189 | dict | ` {'status': 'ok', 'model': model, 'reviewed': False, 'review_error': str(exc), 'content': evidence_brief} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_schedule_risk_ai_prompt`

Source: [app.py:8198-8235](../app.py#L8198).

Build schedule risk ai prompt. Literal result/intermediate fields include `action`, `assignee`, `bug`, `closure_fields`, `countdown_days`, `milestone`, `milestone_date`, `priority`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| schedule_risks | not annotated | ` (required) ` | Schedule risks; operation-specific input consumed by this function. No stricter schema is declared. |
| issues | not annotated | ` (required) ` | Issues; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8220 | dynamic (not annotated) | ` 'You are reviewing Lenovo RAID team defects that are approaching a project milestone. Use only the supplied JIRA workflow facts, milestone dates, actions, closure fields, and recent engineer comments. Do not repeat FFDC analysis and do not invent schedules, owners, builds, or technical causes.\n\nFor each bug, return one compact numbered item with exactly these four bold labels:\n**Stage**: choose ` |

### `parse_schedule_ai_blocks`

Source: [app.py:8238-8248](../app.py#L8238).

Parse schedule ai blocks. Delegates to `match.start`, `matches[index + 1].start`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| content | not annotated | ` (required) ` | Content; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8248 | dynamic (not annotated) | ` blocks ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8246 | ` matches[index + 1].start() ` |
| 8247 | ` content[match.start():end].strip() ` |
| 8247 | ` match.start() ` |

### `schedule_ai_block_complete`

Source: [app.py:8251-8258](../app.py#L8251).

Schedule ai block complete. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| block | not annotated | ` (required) ` | Block; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8258 | bool | ` bool(block) and all((label in block for label in required)) ` |

### `renumber_schedule_ai_block`

Source: [app.py:8261-8262](../app.py#L8261).

Renumber schedule ai block. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| block | not annotated | ` (required) ` | Block; operation-specific input consumed by this function. No stricter schema is declared. |
| index | not annotated | ` (required) ` | Index; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8262 | dynamic (not annotated) | ` re.sub('^\\s*\\d+\\.', f'{index}.', str(block or '').strip(), count=1) ` |

### `generate_schedule_risk_ai_summary`

Source: [app.py:8265-8327](../app.py#L8265).

Generate schedule risk ai summary. Delegates to `build_schedule_risk_ai_prompt`, `call_ai_prompt`, `is_transient_ai_error`, `parse_schedule_ai_blocks`, `renumber_schedule_ai_block`. Literal result/intermediate fields include `content`, `error`, `model`, `primary_model`, `retried`, `status`, `transient`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| schedule_risks | not annotated | ` (required) ` | Schedule risks; operation-specific input consumed by this function. No stricter schema is declared. |
| issues | not annotated | ` (required) ` | Issues; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8267 | dict | ` {'status': 'empty', 'content': ''} ` |
| 8307 | dict | ` {'status': 'error', 'transient': True, 'error': 'Davy returned incomplete milestone assessment for: ' + ', '.join(remaining), 'content': merged} ` |
| 8314 | dict | ` {'status': 'ok', 'model': retry_model or model, 'primary_model': model, 'retried': bool(incomplete), 'content': merged} ` |
| 8322 | dict | ` {'status': 'error', 'transient': is_transient_ai_error(exc), 'error': str(exc), 'content': ''} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `run_jira_monitor_job`

Source: [app.py:8330-8653](../app.py#L8330).

Fetch the current filter and each defect context/evidence, reuse or analyze FFDC, generate AI review, refresh/reuse related cases and milestones, persist the snapshot and start the scheduled summary follow-up.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8510 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `start_jira_monitor_job`

Source: [app.py:8656-8694](../app.py#L8656).

Start JIRA monitor job. Delegates to `cleanup_jira_monitor_jobs`, `persist_jira_monitor_job`, `thread.start`. Literal result/intermediate fields include `created`, `filter_id`, `filter_name`, `id`, `include_milestone_refresh`, `include_similar_bug_analysis`, `issues`, `message`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| username | not annotated | ` (required) ` | Authentication username, normally from explicit login or server configuration; never log credentials. |
| password | not annotated | ` (required) ` | Authentication secret; never include in browser responses or persisted documentation. |
| scheduled | bool | ` False ` | Scheduled; operation-specific input consumed by this function. No stricter schema is declared. |
| trigger | str | ` 'manual' ` | Trigger; operation-specific input consumed by this function. No stricter schema is declared. |
| retry_of | str | ` '' ` | Retry of; operation-specific input consumed by this function. No stricter schema is declared. |
| retry_count | int | ` 0 ` | Retry count; operation-specific input consumed by this function. No stricter schema is declared. |
| include_similar_bug_analysis | bool | ` True ` | True to search/analyze related defects; false to reuse a valid morning snapshot. |
| include_milestone_refresh | bool | ` True ` | True to refresh review milestone mapping; false to reuse morning mapping. Separate summary job currently has additional refresh behavior. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8694 | dynamic (not annotated) | ` job_id ` |

Raises directly: `ValueError('Jira username and password are required.')` (line 8669). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8693 | ` thread.start() ` |

### `has_running_scheduled_jira_monitor_job`

Source: [app.py:8697-8699](../app.py#L8697).

Test whether there is running scheduled JIRA monitor job. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8699 | dynamic (not annotated) | ` any((job.get('scheduled') and job.get('status') == 'running' for job in JIRA_MONITOR_JOBS.values())) ` |

### `start_scheduled_jira_monitor_job`

Source: [app.py:8702-8725](../app.py#L8702).

Start scheduled JIRA monitor job. Delegates to `has_running_scheduled_jira_monitor_job`, `load_jira_monitor_schedule_config`, `start_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| trigger | str | ` 'schedule' ` | Trigger; operation-specific input consumed by this function. No stricter schema is declared. |
| include_similar_bug_analysis | NoneType | ` None ` | True to search/analyze related defects; false to reuse a valid morning snapshot. |
| include_milestone_refresh | NoneType | ` None ` | True to refresh review milestone mapping; false to reuse morning mapping. Separate summary job currently has additional refresh behavior. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8709 | str | ` '' ` |
| 8718 | dynamic (not annotated) | ` start_jira_monitor_job(config.get('username'), config.get('password'), scheduled=True, trigger=trigger, include_similar_bug_analysis=include_similar_bug_analysis, include_milestone_refresh=include_milestone_refresh) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `maybe_retry_scheduled_jira_monitor_job`

Source: [app.py:8728-8786](../app.py#L8728).

Maybe retry scheduled JIRA monitor job. Delegates to `get_latest_jira_monitor_job`, `has_running_scheduled_jira_monitor_job`, `is_transient_jira_monitor_error`, `schedule_jira_monitor_retry`, `set_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| config | not annotated | ` (required) ` | Config; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8731 | str | ` '' ` |
| 8752 | dynamic (not annotated) | ` start_jira_monitor_job(config.get('username'), config.get('password'), scheduled=True, trigger='automatic recovery after service restart', retry_of=latest.get('id', ''), retry_count=max(0, int(latest.get('retry_count') or 0)) + 1, include_similar_bug_analysis=bool(latest.get('include_similar_bug_analysis')), include_milestone_refresh=bool(latest.get('include_milestone_refresh'))) ` |
| 8777 | dynamic (not annotated) | ` start_jira_monitor_job(config.get('username'), config.get('password'), scheduled=True, trigger=f'automatic retry {retry_count}/{len(JIRA_MONITOR_SCHEDULE_RETRY_DELAYS_SECONDS)}', retry_of=latest.get('id', ''), retry_count=retry_count, include_similar_bug_analysis=bool(latest.get('include_similar_bug_analysis')), include_milestone_refresh=bool(latest.get('include_milestone_refresh'))) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_monitor_scheduler_loop`

Source: [app.py:8789-8819](../app.py#L8789).

Jira monitor scheduler loop. Delegates to `load_jira_monitor_schedule_config`, `load_jira_monitor_schedule_state`, `maybe_retry_scheduled_jira_monitor_job`, `save_jira_monitor_schedule_state`, `start_scheduled_jira_monitor_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `start_jira_monitor_scheduler`

Source: [app.py:8822-8831](../app.py#L8822).

Start JIRA monitor scheduler. Delegates to `get_latest_jira_monitor_job`, `load_jira_monitor_schedule_config`, `start_scheduled_jira_monitor_job`, `thread.start`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8831 | ` thread.start() ` |

### `cleanup_agent_jobs`

Source: [app.py:8834-8839](../app.py#L8834).

Clean up agent jobs. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `set_agent_job`

Source: [app.py:8842-8848](../app.py#L8842).

Update agent job. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| **updates | dict | ` (variadic) ` | **updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8846 | dynamic (not annotated) | ` None ` |

### `get_agent_job`

Source: [app.py:8851-8855](../app.py#L8851).

Retrieve agent job. Delegates to `cleanup_agent_jobs`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8855 | dynamic (not annotated) | ` dict(job) if job else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `agent_job_progress`

Source: [app.py:8858-8859](../app.py#L8858).

Agent job progress. Delegates to `set_agent_job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| percent | not annotated | ` (required) ` | Percent; operation-specific input consumed by this function. No stricter schema is declared. |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `run_agent_analysis_job`

Source: [app.py:8862-8882](../app.py#L8862).

Run agent analysis job. Delegates to `agent_job_progress`, `collect_agent_tasks`, `generate_agent_analysis`, `path.read_text`, `set_agent_job`. Literal result/intermediate fields include `agent`, `goal`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| rid | not annotated | ` (required) ` | Report identifier; validation depends on the calling path. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Raises directly: `ValueError('Report not found')` (line 8867). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8879 | ` path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `start_agent_job`

Source: [app.py:8885-8906](../app.py#L8885).

Start agent job. Delegates to `cleanup_agent_jobs`, `thread.start`. Literal result/intermediate fields include `created`, `id`, `message`, `percent`, `report_id`, `status`, `tasks`, `updated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rid | not annotated | ` (required) ` | Report identifier; validation depends on the calling path. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8906 | dynamic (not annotated) | ` job_id ` |

Raises directly: `ValueError('Report ID is required')` (line 8889); `ValueError('Report not found')` (line 8891). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 8905 | ` thread.start() ` |

### `render_jira_results`

Source: [app.py:8909-8930](../app.py#L8909).

Render JIRA results. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 8921 | dynamic (not annotated) | ` HTML_HEAD + "<main><div class='topbar'><a href='/'>ThinkSystem FFDC Analyzer for RAID team</a><div class='nav-links'><a href='/reports'>Reports</a></div></div><section><h2>JIRA FFDC Analysis Results</h2><p class='hint'>" + esc(jira_issue) + ' found ' + str(len(reports)) + ' FFDC file(s). Each file was downloaded and analyzed.</p>' + ''.join(rows) + '</section></main></body></html>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_monitor_latest_panel`

Source: [app.py:8933-9000](../app.py#L8933).

Render JIRA monitor latest panel. Delegates to `esc`, `get_latest_current_status_summary_job`, `get_latest_jira_monitor_job`, `load_jira_monitor_schedule_config`, `render_severity_badge`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9000 | str | ` ''.join(body) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_monitor_page`

Source: [app.py:9003-9051](../app.py#L9003).

Render JIRA monitor page. Delegates to `defect_review_html_head`, `esc`, `render_jira_monitor_latest_panel`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9004 | dynamic (not annotated) | ` defect_review_html_head() + f"\n<main><div class='topbar'><a class='brand' href='/Defect_review'><img class='brand-logo' src='/static/lenovo_logo.png' alt='Lenovo'><span>Defect review with FFDC analyzer tool</span></a><div class='nav-links'><a href='/reports'>Reports</a></div></div>\n{render_jira_monitor_latest_panel()}\n<section class='jira-panel' style='grid-template-columns:minmax(0,1fr) minmax ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_current_status_summary_loading`

Source: [app.py:9054-9061](../app.py#L9054).

Render current status summary loading. Delegates to `defect_review_html_head`, `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9056 | dynamic (not annotated) | ` defect_review_html_head('IOSS key milestones and defects mapping') + "\n<main class='defect-review-wide'><div class='topbar'><a class='brand' href='/Defect_review'><img class='brand-logo' src='/static/lenovo_logo.png' alt='Lenovo'><span>Defect review with FFDC analyzer tool</span></a><div class='nav-links'><a href='/reports'>Reports</a></div></div>\n<section><div class='section-head'><h2>Current B ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `current_status_summary_project_rows`

Source: [app.py:9064-9099](../app.py#L9064).

Current status summary project rows. Delegates to `current_status_display_tags`. Literal result/intermediate fields include `assignee`, `display_tags`, `has_defects`, `issues`, `issues_text`, `key`, `summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9099 | dynamic (not annotated) | ` sorted(rows, key=lambda item: (countdown_sort_value(item), item.get('project_name', '').lower())) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `search_workspace_project_milestones`

Source: [app.py:9102-9175](../app.py#L9102).

Search the latest completed milestone snapshot without refreshing external systems.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| query | str | ` '' ` | Project/issue/name search string or parsed query data as used by this function. |
| within_days | NoneType | ` None ` | Within days; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 12 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9166 | dict | ` {'source': 'latest completed IOSS key milestones and defects mapping snapshot', 'snapshot_id': job.get('id', ''), 'snapshot_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(updated)) if updated else '', 'query': query, 'within_days': within_days, 'projects': matched, 'result_count': len(matched), 'result_limit': limit} ` |

Raises directly: `ValueError('No completed project milestone snapshot is available yet.')` (line 9106). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `current_status_countdown_class`

Source: [app.py:9178-9189](../app.py#L9178).

Current status countdown class. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| has_defects | bool | ` True ` | Has defects; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9180 | str | ` '' ` |
| 9186 | str | ` 'critical' ` |
| 9188 | str | ` 'warning' ` |

### `build_current_status_summary_csv`

Source: [app.py:9192-9212](../app.py#L9192).

Build current status summary csv. Delegates to `current_status_summary_project_rows`. Literal result/intermediate fields include `JIRA Issues`, `Next Dev. Milestone`, `Next Dev. Milestone Date`, `Next countdown (D)`, `Project Code Name`, `Project ID`, `SS`, `SS countdown (D)`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9212 | bytes or stream value | ` output.getvalue().encode('utf-8-sig') ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_current_status_summary_xlsx`

Source: [app.py:9215-9280](../app.py#L9215).

Build current status summary xlsx. Delegates to `current_status_countdown_class`, `current_status_summary_project_rows`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9280 | bytes or stream value | ` output.getvalue() ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_current_status_summary`

Source: [app.py:9283-9349](../app.py#L9283).

Render current status summary. Delegates to `current_status_countdown_class`, `current_status_summary_project_rows`, `defect_review_html_head`, `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9328 | dynamic (not annotated) | ` defect_review_html_head('IOSS key milestones and defects mapping') + '<style>.milestone-summary-table{width:100%;min-width:1120px;border-collapse:collapse}.milestone-summary-table th,.milestone-summary-table td{border:1px solid #bac4d1;padding:9px 10px;text-align:left;vertical-align:top}.milestone-summary-table th{background:#edf1f6}.milestone-summary-table td:nth-child(2),.milestone-summary-table ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `normalize_priority`

Source: [app.py:9352-9363](../app.py#L9352).

Normalize priority. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9355 | str | ` '' ` |
| 9358 | str | ` 'High' ` |
| 9360 | str | ` 'Medium' ` |
| 9362 | str | ` 'Low' ` |
| 9363 | dynamic (not annotated) | ` text ` |

### `compact_status_counts`

Source: [app.py:9366-9370](../app.py#L9366).

Compact status counts. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| counts | not annotated | ` (required) ` | Counts; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9370 | str | ` '; '.join(parts) ` |

### `parse_jira_datetime`

Source: [app.py:9373-9393](../app.py#L9373).

Parse JIRA datetime. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9376 | NoneType | ` None ` |
| 9393 | dynamic (not annotated) | ` parsed ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 9392 | ` parsed.replace(tzinfo=datetime.now().astimezone().tzinfo) ` |

### `relative_calendar_age`

Source: [app.py:9396-9408](../app.py#L9396).

Relative calendar age. Delegates to `parse_jira_datetime`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9399 | str | ` '' ` |
| 9405 | str | ` 'Today' ` |
| 9407 | str | ` 'Yesterday' ` |
| 9408 | str | ` f'{days} days ago' ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 9402 | ` local_now.replace(tzinfo=timezone.utc) ` |

### `render_bug_activity`

Source: [app.py:9411-9433](../app.py#L9411).

Render bug activity. Delegates to `esc`, `jira_limitation_state`, `render_jira_labels`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9417 | str | ` '' ` |
| 9433 | dynamic (not annotated) | ` "<div class='bug-label-row'>" + limitation_html + jira_labels + '</div>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_labels`

Source: [app.py:9436-9450](../app.py#L9436).

Render JIRA labels. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9449 | str | ` '' ` |
| 9450 | dynamic (not annotated) | ` "<span class='jira-labels' aria-label='JIRA labels'>" + ''.join(badges) + '</span>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_assignee_workload_summary`

Source: [app.py:9453-9501](../app.py#L9453).

Render assignee workload summary. Delegates to `compact_status_counts`, `normalize_priority`, `render_table`. Literal result/intermediate fields include `assignee`, `bug_status`, `bugs`, `ffdc_files`, `priority`, `priority_counts`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issues | not annotated | ` (required) ` | Issues; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9497 | dynamic (not annotated) | ` "<section><details open class='compact-details'><summary>Engineer Workload</summary>" + render_table(['assignee', 'bugs', 'bug_status', 'priority', 'ffdc_files'], rows) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_schedule_risk_summary`

Source: [app.py:9504-9582](../app.py#L9504).

Render schedule risk summary. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9582 | str | ` ''.join(body) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_calendar_days_since`

Source: [app.py:9585-9593](../app.py#L9585).

Jira calendar days since. Delegates to `parse_jira_datetime`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9588 | NoneType | ` None ` |
| 9590 | dynamic (not annotated) | ` max(0, (local_now.date() - parsed.astimezone(local_now.tzinfo).date()).days) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `jira_workdays_since`

Source: [app.py:9596-9611](../app.py#L9596).

Jira workdays since. Delegates to `parse_jira_datetime`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9599 | NoneType | ` None ` |
| 9604 | int | ` 0 ` |
| 9611 | dynamic (not annotated) | ` workdays ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_jira_action_date`

Source: [app.py:9614-9642](../app.py#L9614).

Parse the leading update date from an Action field, not later target dates.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| action | not annotated | ` (required) ` | Action; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9618 | NoneType | ` None ` |
| 9640 | dynamic (not annotated) | ` parsed ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 9639 | ` parsed.replace(year=year - 1) ` |

### `render_healthy_status_summary`

Source: [app.py:9645-9905](../app.py#L9645).

Render healthy status summary. Delegates to `esc`, `jira_limitation_state`, `jira_workdays_since`, `parse_jira_action_date`. Literal result/intermediate fields include `Healthy`, `Red`, `action_age_days`, `action_date`, `assignee`, `health`, `high_severity`, `key`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9905 | str | ` ''.join(body) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_schedule_ai_summary`

Source: [app.py:9908-9937](../app.py#L9908).

Render schedule ai summary. Delegates to `esc`, `render_ai_markdown`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9911 | str | ` '' ` |
| 9937 | str | ` ''.join(body) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `compact_defect_review_for_ai`

Source: [app.py:9940-9992](../app.py#L9940).

Build a compact, JIRA-only context for the Defect Review assistant.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| question | str | ` '' ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9987 | dict | ` {'review': {'filter': job.get('filter_name', ''), 'issue_count': len(issues)}, 'issues': overview, 'focused_issue_details': details, 'davy_milestone_assessment': truncate_text((job.get('schedule_ai_summary') or {}).get('content', ''), 9000)} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `call_defect_review_chat`

Source: [app.py:9995-9997](../app.py#L9995).

Call defect review chat. Delegates to `call_evidence_chat`, `compact_defect_review_for_ai`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 9997 | dynamic (not annotated) | ` call_evidence_chat(context, question, history, allow_jira=True) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_defect_review_ai_assistant`

Source: [app.py:10000-10022](../app.py#L10000).

Render defect review ai assistant. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10002 | dynamic (not annotated) | ` "<section class='review-ai-section'>\n<div class='section-head review-ai-head'><div><h2>AI Project Assistant</h2><p class='hint'>Ask about current projects, milestones, defect status, engineer comments, or workflow risks.</p></div><button id='review-chat-clear' class='button subtle' type='button'>Clear</button></div>\n<div id='review-chat-box' class='review-chat-box' aria-live='polite'><div class= ` |

### `DefectReviewTableParser.__init__`

Source: [app.py:10026-10031](../app.py#L10026).

init. Delegates to `super().__init__`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `DefectReviewTableParser.handle_starttag`

Source: [app.py:10033-10042](../app.py#L10033).

Handle starttag. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| tag | not annotated | ` (required) ` | Tag; operation-specific input consumed by this function. No stricter schema is declared. |
| attrs | not annotated | ` (required) ` | Attrs; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `DefectReviewTableParser.handle_data`

Source: [app.py:10044-10046](../app.py#L10044).

Handle data. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `DefectReviewTableParser.handle_endtag`

Source: [app.py:10048-10061](../app.py#L10048).

Handle endtag. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| tag | not annotated | ` (required) ` | Tag; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10052 | ` text.replace('\|', '/') ` |

### `html_table_rows`

Source: [app.py:10064-10069](../app.py#L10064).

Html table rows. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| markup | not annotated | ` (required) ` | Markup; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10068 | list | ` [] ` |
| 10069 | dynamic (not annotated) | ` parser.tables[0] ` |

### `build_defect_review_plain_email`

Source: [app.py:10072-10146](../app.py#L10072).

Build defect review plain email. Delegates to `html_table_rows`, `render_healthy_status_summary`. Literal result/intermediate fields include `body`, `subject`, `to`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10146 | dict | ` {'to': DEFECT_REVIEW_EMAIL_TO, 'subject': subject, 'body': body} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_defect_recommendation_badges`

Source: [app.py:10149-10176](../app.py#L10149).

Render defect recommendation badges. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |
| schedule_risk | not annotated | ` (required) ` | Schedule risk; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10171 | dynamic (not annotated) | ` "<span class='recommendation-tag schedule-badge " + risk_class + "' title='" + esc(risk_tip) + "'>Due date: " + esc(due_date) + '</span>' + "<span class='recommendation-tag schedule-badge " + health_class + "' title='" + esc(health_reason) + "'>Health: " + esc(health_label) + '</span>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `get_defect_review_issue`

Source: [app.py:10179-10187](../app.py#L10179).

Retrieve defect review issue. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10181 | dynamic (not annotated) | ` next((item for item in (job or {}).get('issues') or [] if str(item.get('key') or '').upper() == issue_key), None) ` |

### `build_defect_review_similar_report`

Source: [app.py:10190-10206](../app.py#L10190).

Build defect review similar report. Literal result/intermediate fields include `automated_checks`, `description`, `events`, `issue`, `issue_context`, `jira`, `pci`, `sep_vpd`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10193 | dict | ` {'jira': {'issue': str(item.get('key') or '').upper(), 'summary': summary, 'issue_context': {'summary': summary, 'description': str(item.get('description') or '')}}, 'automated_checks': [], 'events': [], 'pci': {}, 'sep_vpd': []} ` |

### `persist_defect_review_similar_cases`

Source: [app.py:10209-10220](../app.py#L10209).

Persist defect review similar cases. Delegates to `get_defect_review_issue`, `persist_jira_monitor_job`, `safe_jira_monitor_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |
| result | not annotated | ` (required) ` | Result; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10216 | bool | ` False ` |
| 10220 | bool | ` True ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `refresh_defect_review_similar_cases`

Source: [app.py:10223-10242](../app.py#L10223).

Refresh defect review similar cases. Delegates to `build_defect_review_similar_report`, `search_similar_jira_cases`. Literal result/intermediate fields include `cases`, `generated_at`, `message`, `status`, `terms`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| items | not annotated | ` (required) ` | Items; operation-specific input consumed by this function. No stricter schema is declared. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10242 | dynamic (not annotated) | ` items ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_defect_review_similar_page`

Source: [app.py:10245-10267](../app.py#L10245).

Render defect review similar page. Delegates to `build_defect_review_similar_report`, `defect_review_html_head`, `esc`, `render_similar_jira_cases`, `safe_jira_monitor_job_id`. Literal result/intermediate fields include `issue`, `job`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |
| auto_search | bool | ` False ` | Auto search; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10251 | dynamic (not annotated) | ` defect_review_html_head('Similar JIRA Bugs') + "<main class='defect-review-wide'><div class='topbar'><a class='brand' href='/Defect_review'><img class='brand-logo' src='/static/lenovo_logo.png' alt='Lenovo'><span>Defect review with FFDC analyzer tool</span></a></div>" + "<section><div class='section-head'><div><h2>Similar bugs for " + esc(issue_key) + "</h2><p class='hint'>" + esc(item.get('summar ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_defect_similar_jira_link`

Source: [app.py:10270-10277](../app.py#L10270).

Render defect similar JIRA link. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| item | not annotated | ` (required) ` | Item; operation-specific input consumed by this function. No stricter schema is declared. |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10271 | dynamic (not annotated) | ` "<a class='recommendation-button similar-jira-button' onclick='event.stopPropagation()' href='/Defect_review_similar?job=" + esc(job_id) + '&amp;issue=' + esc(issue_key) + "#similar-jira-cases'>Similar bugs</a>" ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_monitor_result`

Source: [app.py:10280-10383](../app.py#L10280).

Render JIRA monitor result. Delegates to `build_defect_review_plain_email`, `defect_review_html_head`, `esc`, `render_ai_markdown`, `render_assignee_workload_summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10366 | dynamic (not annotated) | ` defect_review_html_head() + '<style>.defect-recommendation summary{display:flex;align-items:center;gap:7px;flex-wrap:wrap;width:auto;border:0;border-radius:0;background:transparent;padding:0}.defect-recommendation .recommendation-button{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;background:#f8fafc;padding:5px 10px;font-size:13px;color:#344054;te ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10290 | ` json.dumps(build_defect_review_plain_email(job), ensure_ascii=False).replace('</', '<\\/') ` |

### `render_jira_monitor_ffdc_list`

Source: [app.py:10386-10411](../app.py#L10386).

Render JIRA monitor FFDC list. Delegates to `defect_review_html_head`, `esc`, `index_page`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10390 | dynamic (not annotated) | ` index_page('Defect Review issue not found') ` |
| 10401 | dynamic (not annotated) | ` defect_review_html_head() + "<main class='defect-review-wide'><div class='topbar'><a class='brand' href='/Defect_review'><img class='brand-logo' src='/static/lenovo_logo.png' alt='Lenovo'><span>Defect review with FFDC analyzer tool</span></a><div class='nav-links'><a href='/reports'>Reports</a></div></div>" + "<section><div class='section-head'><h2>Defect Review FFDC List</h2><a class='button seco ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `reconstruct_defect_job_from_report`

Source: [app.py:10414-10466](../app.py#L10414).

Reconstruct defect job from report. Delegates to `path.read_text`, `persist_jira_monitor_job`, `report_path.read_text`, `safe_jira_monitor_job_id`. Literal result/intermediate fields include `ai_summary`, `assignee`, `attachment`, `cache`, `error`, `ffdc_count`, `ffdc_reports`, `filter_name`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report_id | not annotated | ` (required) ` | Report identifier used for filesystem/metadata lookup. |
| job_id | str | ` '' ` | Background job identifier for lookup/progress/persistence. |
| issue_key | str | ` '' ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10418 | NoneType | ` None ` |
| 10466 | dynamic (not annotated) | ` job ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `analyze`

Source: [app.py:10469-10529](../app.py#L10469).

Unpack an FFDC, select classic or V4 parsing, enrich component evidence, apply external-storage scope, run automatic checks, persist report.json and return the report.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |
| cleanup | bool | ` True ` | Whether report retention cleanup is run after successful analysis. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10529 | dynamic (not annotated) | ` report ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10473 | ` work.mkdir(parents=True, exist_ok=True) ` |
| 10474 | ` extract.mkdir(parents=True, exist_ok=True) ` |
| 10526 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |

### `analyze_with_capacity`

Source: [app.py:10536-10549](../app.py#L10536).

Acquire the nonblocking analysis semaphore, track active work, call analyze, and release capacity in a finally block; raises AnalysisBusyError if busy.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| upload_path | not annotated | ` (required) ` | Path to an uploaded or downloaded FFDC archive. |
| cleanup | bool | ` True ` | Whether report retention cleanup is run after successful analysis. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10545 | dynamic (not annotated) | ` analyze(upload_path, cleanup=cleanup) ` |

Raises directly: `AnalysisBusyError(f'Analyzer is busy: {MAX_CONCURRENT_ANALYSES} FFDC analysis task(s) are already running. Please try again later.')` (line 10539). Delegated exceptions may also propagate.

Global declarations: `ANALYSIS_ACTIVE`.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10538 | ` ANALYSIS_SEMAPHORE.acquire(blocking=False) ` |
| 10549 | ` ANALYSIS_SEMAPHORE.release() ` |

### `analysis_capacity_snapshot`

Source: [app.py:10552-10555](../app.py#L10552).

Analysis capacity snapshot. Literal result/intermediate fields include `active`, `available`, `limit`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10555 | dict | ` {'active': active, 'limit': MAX_CONCURRENT_ANALYSES, 'available': max(0, MAX_CONCURRENT_ANALYSES - active)} ` |

### `esc`

Source: [app.py:10558-10559](../app.py#L10558).

Esc. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10559 | dynamic (not annotated) | ` html.escape(str(value if value is not None else '')) ` |

### `usage_client_id`

Source: [app.py:10562-10567](../app.py#L10562).

Usage client id. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| handler | not annotated | ` (required) ` | Handler; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10567 | dynamic (not annotated) | ` hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()[:24] ` |

### `load_usage_stats`

Source: [app.py:10570-10580](../app.py#L10570).

Load usage stats. Delegates to `USAGE_STATS_FILE.read_text`. Literal result/intermediate fields include `days`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10572 | dict | ` {'days': {}} ` |
| 10578 | dynamic (not annotated) | ` data ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `save_usage_stats`

Source: [app.py:10583-10586](../app.py#L10583).

Save usage stats. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10585 | ` tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 10586 | ` tmp.replace(USAGE_STATS_FILE) ` |

### `prune_usage_stats`

Source: [app.py:10589-10600](../app.py#L10589).

Prune usage stats. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10600 | dynamic (not annotated) | ` data ` |

### `record_usage`

Source: [app.py:10603-10620](../app.py#L10603).

Record usage. Delegates to `load_usage_stats`, `prune_usage_stats`, `save_usage_stats`, `usage_client_id`. Literal result/intermediate fields include `paths`, `total_requests`, `unique_clients`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| handler | not annotated | ` (required) ` | Handler; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10606 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `usage_stats_rows`

Source: [app.py:10623-10638](../app.py#L10623).

Usage stats rows. Delegates to `load_usage_stats`, `prune_usage_stats`. Literal result/intermediate fields include `date`, `home`, `jira_results`, `report_views`, `reports`, `total_requests`, `unique_users`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| limit | int | ` 60 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10638 | dynamic (not annotated) | ` rows ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_usage_bar_chart`

Source: [app.py:10641-10663](../app.py#L10641).

Render usage bar chart. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10644 | str | ` "<p class='hint'>No usage data has been recorded yet.</p>" ` |
| 10663 | dynamic (not annotated) | ` "<div class='usage-chart'>" + ''.join(bars) + '</div>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_usage_stats_page`

Source: [app.py:10666-10693](../app.py#L10666).

Render usage stats page. Delegates to `analysis_capacity_snapshot`, `esc`, `render_table`, `render_usage_bar_chart`, `usage_stats_rows`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10681 | dynamic (not annotated) | ` HTML_HEAD + "<main><div class='topbar'><a href='/'>ThinkSystem FFDC Analyzer for RAID team</a><div class='nav-links'><a href='/reports'>Reports</a></div></div>" + "<section><div class='section-head'><h2>Daily Usage Statistics</h2></div>" + "<p class='hint'>Shows the most recent 30 days only. Unique users are counted anonymously by hashing client IP and browser User-Agent. Static files and API poll ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `compact_report_for_ai`

Source: [app.py:10696-10723](../app.py#L10696).

Compact report for ai. Delegates to `classify_backplane_scope`, `collect_pcie_link_reasoning`. Literal result/intermediate fields include `adapter_details`, `automated_checks`, `backplane_registers`, `backplane_scope`, `backplane_vpd`, `drive_wear`, `firmware`, `fru_present`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10701 | dict | ` {'source_file': report.get('source_file'), 'system': report.get('system', {}), 'firmware': report.get('firmware', []), 'system_config': report.get('system_config', {}), 'fru_present': [x for x in report.get('fru', []) if x.get('status') == 'PRSENT'], 'pcie_devices': pci.get('summary', []), 'adapter_details': pci.get('adapters', []), 'storage': pci.get('storage', []), 'other_drives': pci.get('other ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `clean_ai_text`

Source: [app.py:10726-10729](../app.py#L10726).

Normalize ai text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10729 | str | ` text.strip() ` |

### `is_placeholder_ai_response`

Source: [app.py:10732-10734](../app.py#L10732).

Test placeholder ai response. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10734 | bool | ` normalized in {'', 'none', 'null', 'na', 'nadata', 'noresponse'} ` |

### `extract_response_text`

Source: [app.py:10737-10765](../app.py#L10737).

Extract response text. Delegates to `clean_ai_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10739 | dynamic (not annotated) | ` clean_ai_text(data['output_text']) ` |
| 10765 | dynamic (not annotated) | ` clean_ai_text('\n'.join((str(part) for part in parts if part))) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `split_config_value`

Source: [app.py:10768-10772](../app.py#L10768).

Split config value. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10771 | str | ` line.split(sep, 1)[1].strip() ` |
| 10772 | str | ` line.strip() ` |

### `load_ai_config`

Source: [app.py:10775-10802](../app.py#L10775).

Read the server AI configuration file, combine file/environment defaults and return base URL, secret key and model; callers must not expose the key.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10802 | tuple | ` (base_url.rstrip('/'), api_key, model) ` |

Raises directly: `RuntimeError('api_key.txt not found on server')` (line 10777); `RuntimeError('No API key was found in api_key.txt')` (line 10799); `RuntimeError('No model name was found in api_key.txt or FFDC_OPENAI_MODEL')` (line 10801). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `post_json`

Source: [app.py:10805-10816](../app.py#L10805).

Post json. Literal result/intermediate fields include `Authorization`, `Content-Type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |
| api_key | not annotated | ` (required) ` | Server API secret used for Authorization; never return it to the browser. |
| payload | not annotated | ` (required) ` | Payload; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10816 | JSON value | ` json.loads(resp.read().decode('utf-8')) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 10815 | ` urllib.request.urlopen(req, timeout=60, context=AI_SSL_CONTEXT) ` |

### `build_report_jira_relevance_item`

Source: [app.py:10820-10832](../app.py#L10820).

Build report JIRA relevance item. Delegates to `compact_monitor_report`, `compact_report_for_ai`, `filter_monitor_ffdc_for_issue`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10823 | dict | ` {} ` |
| 10832 | dynamic (not annotated) | ` item ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_ai_analysis_prompt`

Source: [app.py:10835-10876](../app.py#L10835).

Build ai analysis prompt. Delegates to `compact_report_for_ai`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| evidence_brief | str | ` '' ` | Evidence brief; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10848 | dynamic (not annotated) | ` 'You are an expert Lenovo ThinkSystem RAID/storage FFDC analysis engineer. Generate an English AI analysis report from the parsed FFDC facts and, when present, the associated JIRA issue context. Do not invent missing data. If evidence is missing, explicitly say it is not available. Focus on RAID/HBA, PCIe EID/OOB, drive inventory, virtual drives, backplane VPD/registers, firmware, and automated fi ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `_call_ai_prompt_once`

Source: [app.py:10879-10920](../app.py#L10879).

call ai prompt once. Delegates to `extract_response_text`, `load_ai_config`, `post_json`. Literal result/intermediate fields include `content`, `input`, `max_output_tokens`, `max_tokens`, `messages`, `model`, `role`, `temperature`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| prompt | not annotated | ` (required) ` | Prompt; operation-specific input consumed by this function. No stricter schema is declared. |
| max_tokens | int | ` 1800 ` | Max tokens; operation-specific input consumed by this function. No stricter schema is declared. |
| model_override | str | ` '' ` | Optional per-call model selection; otherwise use the configured text model. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10893 | tuple | ` (text, model) ` |

Raises directly: `RuntimeError(f'AI API error {exc.code}: {detail[:500]}')` (line 10897); `RuntimeError(f'AI API network error: {exc}')` (line 10899); `RuntimeError(f'AI API error {exc.code}: {detail[:500]}')` (line 10914); `RuntimeError(f'AI API network error: {exc}')` (line 10916); `RuntimeError('AI API returned no text')` (line 10920). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `is_transient_ai_error`

Source: [app.py:10923-10937](../app.py#L10923).

Test transient ai error. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| exc | not annotated | ` (required) ` | Exc; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10925 | dynamic (not annotated) | ` any((token in text for token in ('connection refused', 'connection reset', 'timed out', 'timeout', 'temporarily unavailable', 'service unavailable', 'bad gateway', 'gateway timeout', 'remote end closed', 'returned no text', 'returned no content'))) ` |

### `call_ai_prompt`

Source: [app.py:10940-10954](../app.py#L10940).

Call ai prompt. Delegates to `_call_ai_prompt_once`, `is_transient_ai_error`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| prompt | not annotated | ` (required) ` | Prompt; operation-specific input consumed by this function. No stricter schema is declared. |
| max_tokens | int | ` 1800 ` | Max tokens; operation-specific input consumed by this function. No stricter schema is declared. |
| retries | int | ` 3 ` | Retries; operation-specific input consumed by this function. No stricter schema is declared. |
| model_override | str | ` '' ` | Optional per-call model selection; otherwise use the configured text model. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10944 | dynamic (not annotated) | ` _call_ai_prompt_once(prompt, max_tokens=max_tokens, model_override=model_override) ` |

Raises directly: `last_exc` (line 10954). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `_call_ai_vision_bytes`

Source: [app.py:10957-10987](../app.py#L10957).

call ai vision bytes. Delegates to `extract_response_text`, `load_ai_config`, `post_json`. Literal result/intermediate fields include `content`, `image_url`, `max_tokens`, `messages`, `model`, `role`, `temperature`, `text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_bytes | not annotated | ` (required) ` | Image bytes; operation-specific input consumed by this function. No stricter schema is declared. |
| mime_type | not annotated | ` (required) ` | Mime type; operation-specific input consumed by this function. No stricter schema is declared. |
| filename | not annotated | ` (required) ` | Filename; operation-specific input consumed by this function. No stricter schema is declared. |
| prompt | not annotated | ` (required) ` | Prompt; operation-specific input consumed by this function. No stricter schema is declared. |
| max_bytes | dynamic (not annotated) | ` MAX_JIRA_VISION_IMAGE_BYTES ` | Max bytes; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10959 | str | ` '' ` |
| 10987 | dynamic (not annotated) | ` extract_response_text(data) ` |

Raises directly: `RuntimeError(f'AI vision API error {exc.code}: {detail[:500]}')` (line 10984); `RuntimeError(f'AI vision API network error: {exc}')` (line 10986). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `_call_ai_vision_once`

Source: [app.py:10990-11003](../app.py#L10990).

call ai vision once. Delegates to `_call_ai_vision_bytes`, `jira_image_vision_mime_type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_path | not annotated | ` (required) ` | Image path; operation-specific input consumed by this function. No stricter schema is declared. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 10993 | str | ` '' ` |
| 11003 | dynamic (not annotated) | ` _call_ai_vision_bytes(Path(image_path).read_bytes(), mime_type, filename, prompt) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `analyze_reference_document_image_with_davy`

Source: [app.py:11006-11029](../app.py#L11006).

Analyze a rendered PDF page with Davy vision; document flow has no OCR fallback.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_bytes | not annotated | ` (required) ` | Image bytes; operation-specific input consumed by this function. No stricter schema is declared. |
| mime_type | not annotated | ` (required) ` | Mime type; operation-specific input consumed by this function. No stricter schema is declared. |
| filename | not annotated | ` (required) ` | Filename; operation-specific input consumed by this function. No stricter schema is declared. |
| location | not annotated | ` (required) ` | Location; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11018 | dynamic (not annotated) | ` _call_ai_vision_bytes(image_bytes, mime_type, filename, prompt, max_bytes=DOCUMENT_VISION_MAX_IMAGE_BYTES) ` |
| 11029 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `analyze_jira_image_with_davy`

Source: [app.py:11032-11042](../app.py#L11032).

Return a visual summary when the Davy vision model is available, else let OCR handle it.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| image_path | not annotated | ` (required) ` | Image path; operation-specific input consumed by this function. No stricter schema is declared. |
| attachment | not annotated | ` (required) ` | JIRA attachment metadata, including filename/content or cached-source attributes. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11037 | dynamic (not annotated) | ` _call_ai_vision_once(image_path, attachment) ` |
| 11042 | str | ` '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `generate_ai_analysis`

Source: [app.py:11045-11066](../app.py#L11045).

Generate ai analysis. Delegates to `build_ai_analysis_prompt`, `build_jira_monitor_evidence_prompt`, `build_report_jira_relevance_item`, `call_ai_prompt`. Literal result/intermediate fields include `content`, `error`, `generated_at`, `model`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11047 | dict | ` {'status': 'unavailable', 'error': 'api_key.txt not found on server', 'content': ''} ` |
| 11054 | dict | ` {'status': 'ok', 'model': model, 'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'content': content} ` |
| 11061 | dict | ` {'status': 'error', 'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'error': str(exc), 'content': ''} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `filter_checks`

Source: [app.py:11068-11078](../app.py#L11068).

Filter checks. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| category | NoneType | ` None ` | Category; operation-specific input consumed by this function. No stricter schema is declared. |
| keywords | NoneType | ` None ` | Keywords; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11078 | dynamic (not annotated) | ` rows ` |

### `compact_rows`

Source: [app.py:11081-11082](../app.py#L11081).

Compact rows. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 20 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11082 | dynamic (not annotated) | ` rows[:limit] if isinstance(rows, list) else [] ` |

### `highest_tool_status`

Source: [app.py:11085-11092](../app.py#L11085).

Highest tool status. Literal result/intermediate fields include `critical`, `info`, `ok`, `warning`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| items | not annotated | ` (required) ` | Items; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11092 | dynamic (not annotated) | ` best ` |

### `make_agent_tool_result`

Source: [app.py:11095-11102](../app.py#L11095).

Make agent tool result. Delegates to `compact_rows`. Literal result/intermediate fields include `evidence`, `findings`, `status`, `summary`, `tool`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| status | str | ` 'ok' ` | Status; operation-specific input consumed by this function. No stricter schema is declared. |
| summary | str | ` '' ` | Summary; operation-specific input consumed by this function. No stricter schema is declared. |
| findings | NoneType | ` None ` | Findings; operation-specific input consumed by this function. No stricter schema is declared. |
| evidence | NoneType | ` None ` | Evidence; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11096 | dict | ` {'tool': name, 'status': status, 'summary': summary, 'findings': compact_rows(findings or [], 12), 'evidence': compact_rows(evidence or [], 20)} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_storage_oob_tool`

Source: [app.py:11105-11134](../app.py#L11105).

Check storage oob tool. Delegates to `compact_rows`, `filter_checks`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `adapter_count`, `conclusion`, `controllers`, `eid`, `evidence`, `firmware`, `name`, `physical_drives`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11134 | dynamic (not annotated) | ` make_agent_tool_result('storage_oob_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_backplane_health_tool`

Source: [app.py:11137-11171](../app.py#L11137).

Check backplane health tool. Delegates to `classify_backplane_scope`, `compact_rows`, `filter_checks`, `highest_tool_status`, `is_normal_7mm_boot_vpd_unknown`. Literal result/intermediate fields include `bp`, `conclusion`, `evidence`, `fault_slots`, `nvme_only_slots`, `registers`, `scope`, `sep`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11140 | dynamic (not annotated) | ` make_agent_tool_result('backplane_health_check', 'ok', 'Built-in-backplane evidence is not applicable to the detected external E-suffix storage adapter.', [], [{'scope': scope}]) ` |
| 11171 | dynamic (not annotated) | ` make_agent_tool_result('backplane_health_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_bmc_event_tool`

Source: [app.py:11174-11191](../app.py#L11174).

Check bmc event tool. Delegates to `compact_rows`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `count`, `evidence`, `status`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11191 | dynamic (not annotated) | ` make_agent_tool_result('bmc_event_check', highest_tool_status(findings), summary, findings, compact_rows(problem_events, 20)) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_raid_tty_tool`

Source: [app.py:11194-11220](../app.py#L11194).

Check raid tty tool. Delegates to `compact_rows`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `adapter`, `boot_process`, `conclusion`, `controller_status`, `evidence`, `overview`, `slot`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11220 | dynamic (not annotated) | ` make_agent_tool_result('raid_tty_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_firmware_mctp_tool`

Source: [app.py:11223-11249](../app.py#L11223).

Check firmware mctp tool. Delegates to `filter_checks`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `bmc_inband_fw`, `conclusion`, `evidence`, `flash_mctp`, `status`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11249 | dynamic (not annotated) | ` make_agent_tool_result('firmware_mctp_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_uefi_pcie_tool`

Source: [app.py:11252-11266](../app.py#L11252).

Check UEFI PCIe tool. Delegates to `compact_rows`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `evidence`, `findings`, `nvme_enumeration`, `pcie_enumeration`, `status`, `summary`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11266 | dynamic (not annotated) | ` make_agent_tool_result('uefi_pcie_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_network_tool`

Source: [app.py:11269-11290](../app.py#L11269).

Check network tool. Delegates to `compact_rows`, `filter_checks`, `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `adapters`, `conclusion`, `events`, `evidence`, `interfaces`, `status`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11290 | dynamic (not annotated) | ` make_agent_tool_result('network_check', highest_tool_status(findings), summary, findings, evidence) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `check_automated_findings_tool`

Source: [app.py:11293-11307](../app.py#L11293).

Check automated findings tool. Delegates to `highest_tool_status`, `make_agent_tool_result`. Literal result/intermediate fields include `category`, `conclusion`, `evidence`, `status`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11307 | dynamic (not annotated) | ` make_agent_tool_result('automated_findings_check', highest_tool_status(findings), summary, findings, findings) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `collect_agent_tool_results`

Source: [app.py:11310-11321](../app.py#L11310).

Collect agent tool results. Delegates to `check_automated_findings_tool`, `check_backplane_health_tool`, `check_bmc_event_tool`, `check_firmware_mctp_tool`, `check_network_tool`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11321 | list | ` [tool for tool in tools if tool.get('status') != 'ok' or tool.get('evidence') or tool.get('findings')] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `collect_agent_tasks`

Source: [app.py:11324-11400](../app.py#L11324).

Collect agent tasks. Delegates to `classify_backplane_scope`, `compact_report_for_ai`, `compact_rows`, `filter_checks`. Literal result/intermediate fields include `adapters`, `agent`, `backplane_registers`, `backplane_vpd`, `bmc_inband_fw`, `checks`, `events`, `evidence`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11400 | dynamic (not annotated) | ` tasks ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_agent_analysis_prompt`

Source: [app.py:11403-11454](../app.py#L11403).

Build agent analysis prompt. Literal result/intermediate fields include `agent_tasks`, `automated_checks`, `firmware`, `jira_issue_context`, `jira_relevance_evidence_brief`, `local_agent_tool_results`, `source_file`, `system`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| tasks | not annotated | ` (required) ` | Tasks; operation-specific input consumed by this function. No stricter schema is declared. |
| tool_results | NoneType | ` None ` | Tool results; operation-specific input consumed by this function. No stricter schema is declared. |
| evidence_brief | str | ` '' ` | Evidence brief; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11420 | dynamic (not annotated) | ` "You are a Lenovo ThinkSystem FFDC Analysis Agent orchestrator for RAID/storage support. The local Python tools are the source of truth for deterministic checks. Use the local_agent_tool_results first, then use agent_tasks only as supporting context. Do not override a local tool status. Do not invent missing logs or facts. For each selected agent, explain whether the local tools found an issue, wh ` |

### `build_deep_investigation_fallback`

Source: [app.py:11457-11490](../app.py#L11457).

Build deep investigation fallback. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| tasks | not annotated | ` (required) ` | Tasks; operation-specific input consumed by this function. No stricter schema is declared. |
| tool_results | not annotated | ` (required) ` | Tool results; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11483 | dynamic (not annotated) | ` '## Agent Findings\n' + findings_text + '\n\n## Cross-Log Correlation\n' + correlation + '\n\n## Most Likely Cause\n' + cause + '\n\n## Evidence Chain\n' + evidence_chain + '\n\n## Recommended Action\nReview the relevant raw logs and compare against a known-good system when the reported symptom requires a more specific conclusion.' + '\n\n## JIRA Comment Draft\nThe FFDC Deep Investigation reviewed ` |

### `generate_agent_analysis`

Source: [app.py:11493-11545](../app.py#L11493).

Generate agent analysis. Delegates to `build_agent_analysis_prompt`, `build_deep_investigation_fallback`, `build_jira_monitor_evidence_prompt`, `build_report_jira_relevance_item`, `call_ai_prompt`. Literal result/intermediate fields include `agent`, `content`, `error`, `generated_at`, `goal`, `model`, `status`, `summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| progress | NoneType | ` None ` | Optional callback for status/progress updates. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11495 | dict | ` {'status': 'unavailable', 'error': 'api_key.txt not found on server', 'content': ''} ` |
| 11529 | dict | ` {'status': 'ok', 'model': model, 'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'tasks': [{'agent': t.get('agent'), 'goal': t.get('goal')} for t in tasks], 'tools': [{'tool': t.get('tool'), 'status': t.get('status'), 'summary': t.get('summary')} for t in tool_results], 'content': content} ` |
| 11538 | dict | ` {'status': 'error', 'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'tasks': [{'agent': t.get('agent'), 'goal': t.get('goal')} for t in tasks], 'tools': [{'tool': t.get('tool'), 'status': t.get('status'), 'summary': t.get('summary')} for t in tool_results], 'error': str(exc), 'content': ''} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `detect_user_language`

Source: [app.py:11547-11552](../app.py#L11547).

Detect user language. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11549 | str | ` 'English' ` |
| 11551 | str | ` 'Chinese' ` |

### `workspace_issue_key`

Source: [app.py:11555-11560](../app.py#L11555).

Workspace issue key. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11560 | dynamic (not annotated) | ` match.group(0).upper() if match else '' ` |

### `workspace_question_requests_ffdc_analysis`

Source: [app.py:11563-11564](../app.py#L11563).

Workspace question requests FFDC analysis. Delegates to `workspace_issue_key`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11564 | bool | ` bool(workspace_issue_key(question)) and (not re.search('里程碑\|项目节点\|milestone\|countdown', question or '', re.I)) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `workspace_question_needs_jira`

Source: [app.py:11567-11572](../app.py#L11567).

Workspace question needs JIRA. Delegates to `workspace_issue_key`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11569 | bool | ` bool(workspace_issue_key(text) or re.search('\\bjira\\b\|历史bug\|相似bug\|相似缺陷\|comments?\|comment\|负责人\|工程师\|附件\|缺陷\|bug', text, re.I)) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `find_latest_workspace_jira_report`

Source: [app.py:11575-11592](../app.py#L11575).

Locate latest workspace JIRA report. Delegates to `path.read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_key | not annotated | ` (required) ` | JIRA Bug key; validate/normalize before constructing requests. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11578 | NoneType | ` None ` |
| 11592 | dynamic (not annotated) | ` max(candidates, key=lambda item: item[0])[1] if candidates else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `workspace_report_summary`

Source: [app.py:11595-11626](../app.py#L11595).

Workspace report summary. Literal result/intermediate fields include `attachment`, `attachment_count`, `created_at`, `engineer`, `file`, `id`, `issue`, `key`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11597 | NoneType | ` None ` |
| 11615 | dict | ` {'id': report.get('id', ''), 'file': filename, 'url': f"/report?id={quote(str(report.get('id') or ''))}", 'created_at': report.get('created_at', ''), 'issue': {'key': jira.get('issue'), 'status': issue.get('status'), 'engineer': issue.get('engineer') or issue.get('assignee')} if jira.get('issue') else None, 'attachment_count': jira.get('attachment_count', 1), 'related_reports': related_reports} ` |

### `workspace_jira_request`

Source: [app.py:11629-11642](../app.py#L11629).

Workspace JIRA request. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| credentials | not annotated | ` (required) ` | Credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11642 | dynamic (not annotated) | ` request ` |

### `call_workspace_report_chat`

Source: [app.py:11645-11661](../app.py#L11645).

Call workspace report chat. Delegates to `EvidenceTools(jira_request=workspace_jira_request(jira_credentials), jira_base=JIRA_BASE_URL).get_jira_issue`, `call_openai_chat`, `detect_user_language`, `workspace_jira_request`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| live_issue | NoneType | ` None ` | Live issue; operation-specific input consumed by this function. No stricter schema is declared. |
| trace | NoneType | ` None ` | Trace; operation-specific input consumed by this function. No stricter schema is declared. |
| previous_sources | NoneType | ` None ` | Previous sources; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11660 | dynamic (not annotated) | ` call_openai_chat(report_context, str(question or '').strip(), history, language=language, workspace=True, trace=trace, previous_sources=previous_sources, jira_credentials=jira_credentials) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `call_evidence_chat`

Source: [app.py:11664-11761](../app.py#L11664).

Select the configured chat model and evidence-tool class, prepare raw context, execute the bounded tool loop, verify supported citation ranges and return answer/model.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| context | not annotated | ` (required) ` | Evidence/context mapping supplied to parsing or model orchestration. |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| root | NoneType | ` None ` | Optional raw-evidence root; absence disables raw log tools. |
| allow_jira | bool | ` False ` | Allow jira; operation-specific input consumed by this function. No stricter schema is declared. |
| allow_projects | bool | ` False ` | Allow projects; operation-specific input consumed by this function. No stricter schema is declared. |
| auto_triage | bool | ` False ` | Auto triage; operation-specific input consumed by this function. No stricter schema is declared. |
| language | NoneType | ` None ` | Answer language selector; chat branches distinguish Chinese from English. |
| workspace | bool | ` False ` | Workspace; operation-specific input consumed by this function. No stricter schema is declared. |
| trace | NoneType | ` None ` | Trace; operation-specific input consumed by this function. No stricter schema is declared. |
| previous_sources | NoneType | ` None ` | Previous sources; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11761 | tuple | ` (answer, model) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 11755 | `` answer.replace('`' + citation + '`', '(unverified source)' if answer_language == 'English' else '（来源未核实）') `` |

### `call_workspace_chat`

Source: [app.py:11764-11801](../app.py#L11764).

Call workspace chat. Delegates to `EvidenceTools(jira_request=workspace_jira_request(jira_credentials), jira_base=JIRA_BASE_URL).get_jira_issue`, `call_evidence_chat`, `call_workspace_report_chat`, `find_latest_workspace_jira_report`, `workspace_issue_key`. Literal result/intermediate fields include `current_report`, `raw_logs_available`, `workspace`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| trace | NoneType | ` None ` | Trace; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11789 | tuple | ` (answer, model, issue, workspace_report_summary(report)) ` |
| 11790 | tuple | ` (None, '', issue, None) ` |
| 11801 | tuple | ` (answer, model, issue, None) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `call_openai_chat`

Source: [app.py:11804-11837](../app.py#L11804).

Call openai chat. Delegates to `build_jira_ffdc_comment_associations`, `call_evidence_chat`, `compact_report_for_ai`, `load_workspace_collection`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| language | NoneType | ` None ` | Answer language selector; chat branches distinguish Chinese from English. |
| workspace | bool | ` False ` | Workspace; operation-specific input consumed by this function. No stricter schema is declared. |
| trace | NoneType | ` None ` | Trace; operation-specific input consumed by this function. No stricter schema is declared. |
| previous_sources | NoneType | ` None ` | Previous sources; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11827 | dynamic (not annotated) | ` call_evidence_chat(context, question, history, root=root, allow_jira=bool((report.get('jira') or {}).get('issue')), auto_triage=True, language=language, allow_projects=workspace, workspace=workspace, trace=trace, previous_sources=previous_sources, jira_credentials=jira_credentials) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_workspace_report`

Source: [app.py:11840-11846](../app.py#L11840).

Load workspace report. Delegates to `path.read_text`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rid | not annotated | ` (required) ` | Report identifier; validation depends on the calling path. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11846 | JSON value | ` json.loads(path.read_text(encoding='utf-8')) ` |

Raises directly: `ValueError('Invalid report ID.')` (line 11842); `FileNotFoundError('Report expired or is unavailable. Upload the FFDC again.')` (line 11845). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_workspace_collection`

Source: [app.py:11849-11869](../app.py#L11849).

Return compact context for every FFDC in a JIRA attachment collection.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| collection | not annotated | ` (required) ` | Collection; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11869 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_jira_ffdc_comment_associations`

Source: [app.py:11872-11932](../app.py#L11872).

Map explicit JIRA comment references to the matching FFDC attachment.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| jira_context | not annotated | ` (required) ` | Jira context; operation-specific input consumed by this function. No stricter schema is declared. |
| collection_context | not annotated | ` (required) ` | Collection context; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11876 | list | ` [] ` |
| 11932 | dynamic (not annotated) | ` associations ` |

### `workspace_chat_response`

Source: [app.py:11935-11941](../app.py#L11935).

Validate message/report scope, discard conflicting Bug context, create an answer envelope, or start a PAT-backed JIRA FFDC job if no report is available.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| report_id | NoneType | ` None ` | Report identifier used for filesystem/metadata lookup. |
| previous_sources | NoneType | ` None ` | Previous sources; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |
| author_identity | NoneType | ` None ` | Author identity; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11937 | dynamic (not annotated) | ` domain_author_response(message, actor=author_identity) ` |
| 11939 | dynamic (not annotated) | ` _workspace_chat_response(message, history, report_id, previous_sources, jira_credentials) ` |
| 11941 | dict | ` {'answer': '', 'model': '', 'analysis': {'requires_jira_login': True}, 'answer_html': '', 'issue': None, 'report': None} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `domain_author_response`

Source: [app.py:11944-11953](../app.py#L11944).

Domain author response. Delegates to `DOMAIN_AUTHORING.respond`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |
| token | NoneType | ` None ` | Token; operation-specific input consumed by this function. No stricter schema is declared. |
| domain | NoneType | ` None ` | Domain; operation-specific input consumed by this function. No stricter schema is declared. |
| document | NoneType | ` None ` | Document; operation-specific input consumed by this function. No stricter schema is declared. |
| actor | NoneType | ` None ` | Actor; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11953 | dynamic (not annotated) | ` DOMAIN_AUTHORING.respond(message, complete, token=token, domain=domain, document=document, actor=actor) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `_workspace_chat_response`

Source: [app.py:11956-11987](../app.py#L11956).

workspace chat response. Delegates to `call_workspace_chat`, `call_workspace_report_chat`, `load_workspace_report`, `render_workspace_chat_markdown`, `start_jira_job`. Literal result/intermediate fields include `analysis`, `answer`, `answer_html`, `issue`, `model`, `report`, `requires_jira_login`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| message | not annotated | ` (required) ` | Request message or progress text, depending on this function. |
| history | NoneType | ` None ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| report_id | NoneType | ` None ` | Report identifier used for filesystem/metadata lookup. |
| previous_sources | NoneType | ` None ` | Previous sources; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_credentials | NoneType | ` None ` | Jira credentials; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 11970 | dict | ` {'answer': '', 'model': '', 'analysis': {'requires_jira_login': True}, 'answer_html': '', 'issue': None, 'report': None} ` |
| 11987 | dynamic (not annotated) | ` response ` |

Raises directly: `ValueError('Message must contain 1 to 12000 characters.')` (line 11958). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_system_summary_text`

Source: [app.py:11990-12084](../app.py#L11990).

Build system summary text. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12084 | dynamic (not annotated) | ` '\n'.join(lines).strip() + '\n' ` |

### `render_table`

Source: [app.py:12087-12103](../app.py#L12087).

Render table. Delegates to `esc`, `render_evidence_cell`, `render_severity_badge`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| headers | not annotated | ` (required) ` | Headers; operation-specific input consumed by this function. No stricter schema is declared. |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12103 | str | ` ''.join(out) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `evidence_summary`

Source: [app.py:12106-12110](../app.py#L12106).

Evidence summary. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| limit | int | ` 150 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12109 | dynamic (not annotated) | ` text ` |
| 12110 | dynamic (not annotated) | ` text[:limit].rstrip() + '...' ` |

### `render_evidence_cell`

Source: [app.py:12113-12125](../app.py#L12113).

Render evidence cell. Delegates to `esc`, `evidence_summary`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12116 | str | ` '' ` |
| 12119 | str | ` f"<div class='evidence-text'>{esc(text)}</div>" ` |
| 12120 | str | ` f"<details class='evidence-details'><summary>{esc(summary)}</summary><pre>{esc(text)}</pre></details>" ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_severity_badge`

Source: [app.py:12128-12140](../app.py#L12128).

Render severity badge. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12140 | str | ` f"<span class='severity-badge {cls}'>{esc(label)}</span>" ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_automated_checks`

Source: [app.py:12143-12158](../app.py#L12143).

Render automated checks. Delegates to `esc`, `render_evidence_cell`, `render_severity_badge`. Literal result/intermediate fields include `category`, `conclusion`, `evidence`, `severity`, `title`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| checks | not annotated | ` (required) ` | Checks; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12158 | str | ` ''.join(out) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_pldm_update_analysis`

Source: [app.py:12161-12187](../app.py#L12161).

Render PLDM update analysis. Delegates to `esc`, `render_table`. Literal result/intermediate fields include `address`, `conclusion`, `device`, `eid`, `evidence`, `pldm_response`, `status`, `timestamp`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| updates | not annotated | ` (required) ` | Updates; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12164 | str | ` '' ` |
| 12178 | dynamic (not annotated) | ` "<section><details class='compact-details'><summary>" + esc(title) + '</summary>' + render_table(['timestamp', 'device', 'eid', 'address', 'status', 'pldm_response', 'conclusion', 'evidence'], rows) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_bmc_inband_firmware_analysis`

Source: [app.py:12190-12214](../app.py#L12190).

Render bmc inband firmware analysis. Delegates to `render_table`. Literal result/intermediate fields include `conclusion`, `evidence`, `sources`, `status`, `timestamp`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12195 | str | ` '' ` |
| 12214 | dynamic (not annotated) | ` content + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `short_join`

Source: [app.py:12217-12220](../app.py#L12217).

Short join. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| items | not annotated | ` (required) ` | Items; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 6 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12220 | dynamic (not annotated) | ` '; '.join(values[:limit]) + suffix ` |

### `check_matches`

Source: [app.py:12223-12225](../app.py#L12223).

Check matches. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| check | not annotated | ` (required) ` | Check; operation-specific input consumed by this function. No stricter schema is declared. |
| *needles | tuple | ` (variadic) ` | *needles; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12225 | dynamic (not annotated) | ` any((n.lower() in text for n in needles)) ` |

### `collect_cross_log_correlations`

Source: [app.py:12228-12384](../app.py#L12228).

Collect cross log correlations. Delegates to `check_matches`, `collect_pcie_link_reasoning`, `short_join`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12384 | dynamic (not annotated) | ` rows[:12] ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_cross_log_correlations`

Source: [app.py:12387-12404](../app.py#L12387).

Render cross log correlations. Delegates to `esc`, `render_evidence_cell`, `render_severity_badge`. Literal result/intermediate fields include `confidence`, `correlation`, `evidence`, `impact`, `next_action`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12389 | str | ` '' ` |
| 12404 | str | ` ''.join(out) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `compact_slots`

Source: [app.py:12407-12420](../app.py#L12407).

Compact slots. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| values | not annotated | ` (required) ` | Values; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12410 | str | ` '' ` |
| 12420 | str | ` ', '.join(ranges) ` |

### `parse_slot_status_text`

Source: [app.py:12423-12464](../app.py#L12423).

Parse slot status text. Delegates to `compact_slots`. Literal result/intermediate fields include `Boot Drive`, `Drive Fail`, `EDSFF`, `Empty`, `Fault`, `Locate`, `M.2`, `NVMe`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12464 | dynamic (not annotated) | ` result ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 12432 | ` label.replace(' Drive ', ' ').replace(' Installed', '').replace('Fail', 'Fail').strip() ` |
| 12432 | ` label.replace(' Drive ', ' ').replace(' Installed', '').replace('Fail', 'Fail') ` |
| 12432 | ` label.replace(' Drive ', ' ').replace(' Installed', '') ` |
| 12432 | ` label.replace(' Drive ', ' ') ` |
| 12437 | ` label.replace(' Drive ', ' ').replace('Installed', '').strip() ` |
| 12437 | ` label.replace(' Drive ', ' ').replace('Installed', '') ` |
| 12437 | ` label.replace(' Drive ', ' ') ` |
| 12442 | ` label.replace(' Drive ', ' ').replace('Installed', '').strip() ` |
| 12442 | ` label.replace(' Drive ', ' ').replace('Installed', '') ` |
| 12442 | ` label.replace(' Drive ', ' ') ` |

### `normalize_bp_capability`

Source: [app.py:12467-12473](../app.py#L12467).

Normalize bp capability. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12470 | str | ` 'SAS/SATA' ` |
| 12472 | str | ` 'Tri-model' ` |
| 12473 | dynamic (not annotated) | ` text ` |

### `render_badge`

Source: [app.py:12476-12482](../app.py#L12476).

Render badge. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| label | not annotated | ` (required) ` | Label; operation-specific input consumed by this function. No stricter schema is declared. |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |
| kind | str | ` '' ` | Kind; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12478 | str | ` '' ` |
| 12482 | str | ` f"<span class='{cls}'><b>{esc(label)}</b>{esc(display_value)}</span>" ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `backplane_u3_mode`

Source: [app.py:12485-12495](../app.py#L12485).

Backplane u3 mode. Delegates to `decode_u3_mode`, `parse_rdata_line`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| ctrl | not annotated | ` (required) ` | Ctrl; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12487 | dynamic (not annotated) | ` ctrl['u3_mode'] ` |
| 12490 | str | ` '' ` |
| 12494 | dynamic (not annotated) | ` decode_u3_mode(values[11]) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_backplane_registers`

Source: [app.py:12498-12568](../app.py#L12498).

Render backplane registers. Delegates to `backplane_u3_mode`, `esc`, `normalize_bp_capability`, `parse_slot_status_text`, `render_badge`. Literal result/intermediate fields include `ctrl`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| rows | not annotated | ` (required) ` | Rows; operation-specific input consumed by this function. No stricter schema is declared. |
| platform_format | str | ` 'v1_v3' ` | Platform format; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12501 | str | ` "<section><h2>Backplane Registers</h2><p class='hint'>No SEP register data was decoded for this report.</p></section>" ` |
| 12568 | dynamic (not annotated) | ` "<section><h2>Backplane Registers</h2><div class='bp-grid'>" + ''.join(cards) + '</div></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_network_analysis`

Source: [app.py:12571-12599](../app.py#L12571).

Render network analysis. Delegates to `esc`, `render_table`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| network | not annotated | ` (required) ` | Network; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12578 | str | ` "<section><h2>Network Adapters</h2><p class='hint'>No NIC inventory or network link/driver log was found in this FFDC. This is a collection-data limitation, not a network fault.</p></section>" ` |
| 12599 | dynamic (not annotated) | ` content + '</section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_details`

Source: [app.py:12602-12604](../app.py#L12602).

Render details. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| title | not annotated | ` (required) ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |
| body | not annotated | ` (required) ` | Body; operation-specific input consumed by this function. No stricter schema is declared. |
| open_by_default | bool | ` False ` | Open by default; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12604 | str | ` f"<details class='config-details'{state}><summary>{esc(title)}</summary>{body}</details>" ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_raid_tty`

Source: [app.py:12609-12625](../app.py#L12609).

Render raid tty. Delegates to `esc`, `render_table`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| raid_tty | not annotated | ` (required) ` | Raid tty; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12611 | str | ` '' ` |
| 12625 | dynamic (not annotated) | ` "<section><details class='compact-details'><summary>" + esc(title) + '</summary>' + ''.join(body) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_fpga_on`

Source: [app.py:12627-12639](../app.py#L12627).

Render fpga on. Delegates to `render_table`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| fpga | not annotated | ` (required) ` | Fpga; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12629 | str | ` '' ` |
| 12639 | dynamic (not annotated) | ` "<section><details class='compact-details'><summary>FPGA On Demand</summary>" + ''.join(body) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_uefi_boot`

Source: [app.py:12643-12656](../app.py#L12643).

Render UEFI boot. Delegates to `enrich_uefi_pcie_device_names`, `render_table`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| uefi | not annotated | ` (required) ` | Uefi; operation-specific input consumed by this function. No stricter schema is declared. |
| pci | NoneType | ` None ` | Parsed PCI/controller inventory. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12645 | str | ` '' ` |
| 12656 | dynamic (not annotated) | ` "<section><details class='compact-details'><summary>UEFI / Boot Logs Summary</summary>" + ''.join(body) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `markdown_table_cells`

Source: [app.py:12658-12662](../app.py#L12658).

Markdown table cells. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12661 | list | ` [] ` |
| 12662 | list | ` [cell.strip() for cell in line[1:-1].split('\|')] ` |

### `is_markdown_table_separator`

Source: [app.py:12665-12669](../app.py#L12665).

Test markdown table separator. Delegates to `markdown_table_cells`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| line | not annotated | ` (required) ` | Line; operation-specific input consumed by this function. No stricter schema is declared. |
| column_count | not annotated | ` (required) ` | Column count; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12667 | bool | ` len(cells) == column_count and all((re.fullmatch(':?-{3,}:?', cell.replace(' ', '')) for cell in cells)) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 12668 | ` cell.replace(' ', '') ` |

### `normalize_chat_markdown_tables`

Source: [app.py:12672-12721](../app.py#L12672).

Replace wide Markdown tables with one readable finding per chat section.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12721 | str | ` '\n'.join(normalized).strip() ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_workspace_chat_markdown`

Source: [app.py:12724-12725](../app.py#L12724).

Render workspace chat markdown. Delegates to `normalize_chat_markdown_tables`, `render_chat_markdown`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12725 | dynamic (not annotated) | ` render_chat_markdown(normalize_chat_markdown_tables(text), render_ai_markdown) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_markdown_table_cell`

Source: [app.py:12728-12738](../app.py#L12728).

Render markdown table cell. Delegates to `esc`, `render_inline_markdown`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| cell | not annotated | ` (required) ` | Cell; operation-specific input consumed by this function. No stricter schema is declared. |
| header | not annotated | ` (required) ` | Header; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12730 | dynamic (not annotated) | ` render_inline_markdown(cell) ` |
| 12735 | dynamic (not annotated) | ` "<a href='" + esc(JIRA_BASE_URL) + '/browse/' + esc(key) + "' target='_blank' rel='noopener'>" + esc(key) + '</a>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_ai_markdown`

Source: [app.py:12741-12801](../app.py#L12741).

Render ai markdown. Delegates to `is_markdown_table_separator`, `markdown_table_cells`, `render_inline_markdown`, `render_markdown_table_cell`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12743 | str | ` "<p class='hint'>AI analysis is not available for this report.</p>" ` |
| 12801 | str | ` ''.join(lines) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_inline_markdown`

Source: [app.py:12804-12808](../app.py#L12804).

Render inline markdown. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12808 | dynamic (not annotated) | ` html ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_ai_analysis`

Source: [app.py:12811-12820](../app.py#L12811).

Render ai analysis. Delegates to `esc`, `render_ai_markdown`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12817 | dynamic (not annotated) | ` "<section class='ai-overview'><details><summary>AI Analysis Overview</summary><div class='section-head'>" + meta + actions + "</div><div class='ai-report'>" + render_ai_markdown(ai.get('content', '')) + '</div></details></section>' ` |
| 12819 | dynamic (not annotated) | ` "<section class='ai-overview error'><details><summary>AI Analysis Overview</summary><p>AI analysis failed: " + esc(ai.get('error', 'unknown error')) + '</p></details></section>' ` |
| 12820 | dynamic (not annotated) | ` "<section class='ai-overview'><details><summary>AI Analysis Overview</summary><p class='hint'>AI analysis has not been generated yet.</p><form class='ai-generate-form' method='post' action='/generate-ai-report' data-progress-title='Generating AI Report' data-progress-start='Preparing FFDC context'><input type='hidden' name='id' value='" + esc(report.get('id', '')) + "'><button type='submit'>Genera ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_agent_analysis`

Source: [app.py:12822-12830](../app.py#L12822).

Render agent analysis. Delegates to `esc`, `render_agent_analysis_controls`, `render_ai_markdown`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12827 | dynamic (not annotated) | ` "<section id='ai-agent-analysis' class='ai-overview'><details open><summary>Deep Investigation</summary><div class='section-head'>" + meta + "</div><div class='ai-report'>" + render_ai_markdown(agent.get('content', '')) + '</div></details></section>' ` |
| 12829 | dynamic (not annotated) | ` "<section id='ai-agent-analysis' class='ai-overview error'><details open><summary>Deep Investigation</summary><p>Deep Investigation failed: " + esc(agent.get('error', 'unknown error')) + '</p>' + render_agent_analysis_controls(report) + '</details></section>' ` |
| 12830 | dynamic (not annotated) | ` "<section id='ai-agent-analysis' class='ai-overview'><details><summary>Deep Investigation</summary><p class='hint'>Deep Investigation has not been generated yet. It uses selected FFDC evidence modules and a dedicated reasoning model.</p>" + render_agent_analysis_controls(report) + '</details></section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_agent_analysis_controls`

Source: [app.py:12833-12896](../app.py#L12833).

Render agent analysis controls. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12835 | str | ` f"\n<form id='agent-analysis-form' class='ai-generate-form' method='post' action='/agent-analysis-start'>\n  <input type='hidden' name='id' value='{rid}'>\n  <button id='agent-analysis-button' type='submit'>Run Deep Investigation</button>\n</form>\n<div id='agent-progress' class='jira-progress agent-progress' aria-live='polite'>\n  <div class='jira-progress-top'><span>Deep Investigation</span><spa ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `build_default_jira_comment`

Source: [app.py:12898-12941](../app.py#L12898).

Build default JIRA comment. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12924 | str | ` '\n'.join(lines).strip() ` |

### `render_jira_comment_section`

Source: [app.py:12944-12965](../app.py#L12944).

Render JIRA comment section. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12948 | str | ` '' ` |
| 12953 | dynamic (not annotated) | ` "<section><details><summary>Add comment to JIRA</summary><p class='hint'>Write the customer-facing JIRA comment manually, or generate Deep Investigation first and copy the useful conclusion here. Your JIRA login is required only for this write action and is not stored.</p>" + notice + "<form class='jira-comment-form' method='post' action='/jira-comment'><input type='hidden' name='id' value='" + es ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_case_context`

Source: [app.py:12968-13000](../app.py#L12968).

Render JIRA case context. Delegates to `render_details`, `render_table`. Literal result/intermediate fields include `author`, `comment`, `created`, `item`, `value`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| issue_context | not annotated | ` (required) ` | Issue context; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 12970 | str | ` '' ` |
| 13000 | dynamic (not annotated) | ` body + '</section>' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_jira_attachment_evidence`

Source: [app.py:13003-13049](../app.py#L13003).

Render JIRA attachment evidence. Delegates to `esc`, `render_details`, `render_table`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| evidence | not annotated | ` (required) ` | Evidence; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13006 | str | ` "<section><h2>JIRA Log Attachment Analysis</h2><p class='hint'>No supported log archive evidence was extracted.</p></section>" ` |
| 13049 | str | ` ''.join(parts) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_similar_jira_cases`

Source: [app.py:13052-13104](../app.py#L13052).

Render similar JIRA cases. Delegates to `esc`, `render_ai_markdown`. Literal result/intermediate fields include `id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |
| search_endpoint | str | ` '/similar-jira-cases' ` | Search endpoint; operation-specific input consumed by this function. No stricter schema is declared. |
| search_payload | NoneType | ` None ` | Search payload; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13104 | dynamic (not annotated) | ` "<section id='similar-jira-cases'><div class='section-head'><div><h2>Similar JIRA Bugs</h2></div><button id='similar-jira-search' type='button'>" + label + "</button></div><div id='similar-jira-results'>" + content + "</div><script>(function(){const button=document.getElementById('similar-jira-search');const results=document.getElementById('similar-jira-results');const autoSearch=" + auto_search + ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 13055 | ` json.dumps(search_payload if search_payload is not None else {'id': report.get('id') or ''}, ensure_ascii=False).replace('</', '<\\/') ` |

### `render_report`

Source: [app.py:13107-13383](../app.py#L13107).

Render report. Delegates to `classify_backplane_scope`, `esc`, `parse_raid_tty_logs`, `render_agent_analysis`, `render_automated_checks`. Literal result/intermediate fields include `device`, `failure`, `mctp_evidence`, `slot`, `software_id`, `timestamp`, `version`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| report | not annotated | ` (required) ` | Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13142 | str | ` ''.join(html_parts) ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `defect_review_html_head`

Source: [app.py:13398-13403](../app.py#L13398).

Defect review html head. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| title | str | ` 'Defect Review with FFDC Analyzer Tool' ` | Title; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13399 | dynamic (not annotated) | ` HTML_HEAD.replace('<title>ThinkSystem FFDC Analyzer for RAID team</title>', '<title>' + esc(title) + '</title>', 1) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 13399 | ` HTML_HEAD.replace('<title>ThinkSystem FFDC Analyzer for RAID team</title>', '<title>' + esc(title) + '</title>', 1) ` |

### `index_page`

Source: [app.py:13406-13532](../app.py#L13406).

Index page. Delegates to `esc`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| message | str | ` '' ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13408 | dynamic (not annotated) | ` HTML_HEAD + f"\n<main><div class='topbar'><a class='brand' href='/'><img class='brand-logo' src='/static/lenovo_logo.png' alt='Lenovo'><span>ThinkSystem FFDC Analyzer</span></a><div class='nav-links'><a href='/reports'>Reports</a></div></div>\n<section class='home-hero unified-hero'><div><div class='home-eyebrow'>RAID team analysis workspace</div><h1>Analyze ThinkSystem FFDC packages</h1><p>Upload ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `add_new_version_nav`

Source: [app.py:13535-13538](../app.py#L13535).

Add new version nav. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| body | not annotated | ` (required) ` | Body; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13538 | dynamic (not annotated) | ` str(body).replace(old_nav, new_nav) ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 13538 | ` str(body).replace(old_nav, new_nav) ` |

### `add_workspace_view`

Source: [app.py:13541-13547](../app.py#L13541).

Add workspace view. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| url | not annotated | ` (required) ` | Destination URL; destination validation and credential forwarding policy depend on the caller. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13544 | str | ` str(url or '') ` |
| 13547 | str | ` parsed._replace(query=urlencode(query)).geturl() ` |

### `Handler.send_html`

Source: [app.py:13553-13566](../app.py#L13553).

Send html. Delegates to `add_new_version_nav`, `render_workspace_subpage`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| body | not annotated | ` (required) ` | Body; operation-specific input consumed by this function. No stricter schema is declared. |
| status | int | ` 200 ` | Status; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `Handler.send_json`

Source: [app.py:13568-13578](../app.py#L13568).

Send json. Delegates to `add_workspace_view`, `self.uses_workspace_view`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| data | not annotated | ` (required) ` | Data; operation-specific input consumed by this function. No stricter schema is declared. |
| status | int | ` 200 ` | Status; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `Handler.uses_workspace_view`

Source: [app.py:13580-13585](../app.py#L13580).

Uses workspace view. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13581 | dynamic (not annotated) | ` any((parse_qs(urlparse(value).query).get('view', [''])[0] == 'workspace' for value in (self.path, self.headers.get('Referer', '')) if value)) ` |

### `Handler.view_location`

Source: [app.py:13587-13588](../app.py#L13587).

View location. Delegates to `add_workspace_view`, `self.uses_workspace_view`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| location | not annotated | ` (required) ` | Location; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13588 | dynamic (not annotated) | ` add_workspace_view(location) if self.uses_workspace_view() else location ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `Handler.read_json_body`

Source: [app.py:13590-13595](../app.py#L13590).

Read json body. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13595 | dynamic (not annotated) | ` json.loads(raw.decode('utf-8')) if raw else {} ` |

Raises directly: `ValueError('request body too large')` (line 13593). Delegated exceptions may also propagate.

### `Handler.read_form`

Source: [app.py:13597-13602](../app.py#L13597).

Read form. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13602 | dynamic (not annotated) | ` parse_qs(raw) ` |

Raises directly: `ValueError('request body too large')` (line 13600). Delegated exceptions may also propagate.

### `Handler.get_cookie`

Source: [app.py:13604-13612](../app.py#L13604).

Retrieve cookie. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13611 | dynamic (not annotated) | ` value ` |
| 13612 | str | ` '' ` |

### `Handler.set_jira_session_cookie`

Source: [app.py:13614-13615](../app.py#L13614).

Update JIRA session cookie. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| sid | not annotated | ` (required) ` | Sid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `Handler.set_author_session_cookie`

Source: [app.py:13617-13618](../app.py#L13617).

Update author session cookie. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| sid | not annotated | ` (required) ` | Sid; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `Handler.do_GET`

Source: [app.py:13620-13943](../app.py#L13620).

Dispatch GET routes for pages, reports, evidence, exports, job polling and sample analysis. Several GET routes have local or integration side effects.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13631 | dynamic (not annotated) | ` None ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 13674 | ` render_jira_monitor_page().replace('</main></body></html>', "<p class='hint'>Current Bug Status Summary has not been generated yet. It will be available after the next scheduled Defect Review run.</p></main></body></html>") ` |
| 13701 | ` render_table(['id', 'created_at', 'source', 'system'], items).replace('<td>', '<td>', 1) ` |
| 13703 | ` body.replace(f"<td>{item['id']}</td>", f"<td><a href='/report?id={item['id']}'>{item['id']}</a></td>") ` |

### `Handler.do_POST`

Source: [app.py:13945-14465](../app.py#L13945).

Dispatch chat, upload, analysis, review, comment and deletion requests; validation, credentials and response types differ by route.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 13952 | dynamic (not annotated) | ` None ` |

Raises directly: `ValueError('Username and password are required.')` (line 14072); `ValueError('JIRA username and password are required.')` (line 14094); `ValueError('Jira username and password are required to add a comment.')` (line 14227); `ValueError('Jira comment is required.')` (line 14229); `ValueError('Jira issue is missing. Please reopen the report from JIRA analysis results and try again.')` (line 14236); `ValueError('A valid JIRA Bug ID is required.')` (line 14283). Delegated exceptions may also propagate.

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 14150 | ` path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 14241 | ` path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 14353 | ` path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 14370 | ` path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 14400 | ` (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8') ` |
| 14445 | ` upload_path.open('wb') ` |
| 14446 | ` shutil.copyfileobj(field.file, out) ` |

### `main`

Source: [app.py:14473-14484](../app.py#L14473).

Create runtime directories, start the scheduler thread and serve HTTP on the configured host/port until interrupted.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| None | — | — | No arguments. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 14474 | ` UPLOAD_DIR.mkdir(exist_ok=True) ` |
| 14475 | ` REPORT_DIR.mkdir(exist_ok=True) ` |
| 14476 | ` FFDC_CACHE_DIR.mkdir(exist_ok=True) ` |
| 14477 | ` JIRA_OCR_CACHE_DIR.mkdir(exist_ok=True) ` |
| 14478 | ` JIRA_ATTACHMENT_CACHE_DIR.mkdir(exist_ok=True) ` |
| 14479 | ` JIRA_MONITOR_JOB_DIR.mkdir(exist_ok=True) ` |

## `ffdc_chat.py` Callable Details

### `bounded_context`

Source: [ffdc_chat.py:41-70](../ffdc_chat.py#L41).

Give each report section a budget so large logs cannot crowd out other modules.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| context | not annotated | ` (required) ` | Evidence/context mapping supplied to parsing or model orchestration. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 70 | dict | ` {key: compact(value, [6000]) for key, value in context.items()} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `render_chat_markdown`

Source: [ffdc_chat.py:73-116](../ffdc_chat.py#L73).

Extend the existing escaped block renderer with safe code and links.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| text | not annotated | ` (required) ` | Source text to parse/normalize/render; untrusted content must be escaped before HTML output. |
| render_blocks | not annotated | ` (required) ` | Render blocks; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 116 | dynamic (not annotated) | ` result ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 115 | ` result.replace(token, fragment) ` |

### `redact`

Source: [ffdc_chat.py:119-126](../ffdc_chat.py#L119).

Redact. Delegates to `redact`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| value | not annotated | ` (required) ` | Value; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 121 | dict | ` {k: redact(v) for k, v in value.items() if not SECRET.search(str(k))} ` |
| 123 | list | ` [redact(v) for v in value] ` |
| 125 | str | ` '\n'.join(('[sensitive line omitted]' if SECRET.search(line) else line for line in value.split('\n'))) ` |
| 126 | dynamic (not annotated) | ` value ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `parse_text_tool_calls`

Source: [ffdc_chat.py:129-165](../ffdc_chat.py#L129).

Normalize Davy's XML-like fallback tool syntax to OpenAI tool calls.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| content | not annotated | ` (required) ` | Content; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 165 | dynamic (not annotated) | ` calls ` |

### `function`

Source: [ffdc_chat.py:168-172](../ffdc_chat.py#L168).

Function. Literal result/intermediate fields include `additionalProperties`, `description`, `function`, `name`, `parameters`, `properties`, `required`, `type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| description | not annotated | ` (required) ` | Description; operation-specific input consumed by this function. No stricter schema is declared. |
| properties | not annotated | ` (required) ` | Properties; operation-specific input consumed by this function. No stricter schema is declared. |
| required | not annotated | ` (required) ` | Required; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 169 | dict | ` {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}} ` |

### `EvidenceTools.__init__`

Source: [ffdc_chat.py:176-182](../ffdc_chat.py#L176).

init. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| root | NoneType | ` None ` | Optional raw-evidence root; absence disables raw log tools. |
| jira_request | NoneType | ` None ` | Jira request; operation-specific input consumed by this function. No stricter schema is declared. |
| jira_base | str | ` '' ` | Jira base; operation-specific input consumed by this function. No stricter schema is declared. |
| project_search | NoneType | ` None ` | Project search; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `EvidenceTools.schemas`

Source: [ffdc_chat.py:184-215](../ffdc_chat.py#L184).

Schemas. Delegates to `function`. Literal result/intermediate fields include `contains`, `count`, `enum`, `focus`, `items`, `jql`, `key`, `limit`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 215 | dynamic (not annotated) | ` schemas ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.log_path`

Source: [ffdc_chat.py:217-232](../ffdc_chat.py#L217).

Log path. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 232 | dynamic (not annotated) | ` path ` |

Raises directly: `ValueError('Raw FFDC files are unavailable for this report.')` (line 219); `ValueError('Use a relative path inside this FFDC.')` (line 222); `ValueError('Path is outside this FFDC.')` (line 225); `ValueError('This file is not an available text log.')` (line 227); `ValueError('Log file not found.')` (line 229); `ValueError('This file is not readable.')` (line 231). Delegated exceptions may also propagate.

### `EvidenceTools.paths`

Source: [ffdc_chat.py:234-247](../ffdc_chat.py#L234).

Paths. Delegates to `os.walk`, `self.log_path`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 236 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.lines`

Source: [ffdc_chat.py:249-264](../ffdc_chat.py#L249).

Lines. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 252 | dynamic (not annotated) | ` None ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 250 | ` path.open('rb') ` |

### `EvidenceTools.execute`

Source: [ffdc_chat.py:266-279](../ffdc_chat.py#L266).

Allow only tool schemas enabled for this context, dispatch arguments, record successful lookups and redact results; failures return an error dictionary.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| args | not annotated | ` (required) ` | Args; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 269 | dict | ` {'error': 'Tool unavailable in this analysis.'} ` |
| 273 | dynamic (not annotated) | ` redact(result) ` |
| 277 | dict | ` {'error': redact(str(exc))} ` |
| 279 | dict | ` {'error': 'Evidence lookup failed. Do not infer a result; report the lookup failure.'} ` |

Raises directly: `None` (line 275). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.list_logs`

Source: [ffdc_chat.py:281-296](../ffdc_chat.py#L281).

List logs. Delegates to `self.paths`. Literal result/intermediate fields include `available`, `bytes`, `files`, `next_offset`, `path`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| contains | str | ` '' ` | Contains; operation-specific input consumed by this function. No stricter schema is declared. |
| offset | int | ` 0 ` | Zero-based pagination offset. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 295 | dict | ` {'files': rows[:80], 'next_offset': offset + 80 if len(rows) > 80 else None, 'available': bool(self.root and self.root.is_dir())} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.read_log`

Source: [ffdc_chat.py:298-309](../ffdc_chat.py#L298).

Read log. Delegates to `redact`, `self.lines`, `self.log_path`. Literal result/intermediate fields include `file_exceeds_scan_limit`, `line`, `lines`, `path`, `scan_byte_limit`, `text`, `text_truncated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| start | not annotated | ` (required) ` | Starting source line or range boundary as defined by the function. |
| count | int | ` 60 ` | Requested record/line count; evidence readers clamp it. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 308 | dict | ` {'path': path, 'lines': rows, 'scan_byte_limit': MAX_SCAN_BYTES, 'file_exceeds_scan_limit': source.stat().st_size > MAX_SCAN_BYTES} ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.search_logs`

Source: [ffdc_chat.py:311-333](../ffdc_chat.py#L311).

Search logs. Delegates to `self.lines`, `self.log_path`, `self.paths`. Literal result/intermediate fields include `files_scanned`, `limited`, `line`, `matches`, `path`, `text`, `text_truncated`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| terms | not annotated | ` (required) ` | Terms; operation-specific input consumed by this function. No stricter schema is declared. |
| path | str | ` '' ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 328 | dict | ` {'matches': results, 'limited': True, 'files_scanned': scanned} ` |
| 333 | dict | ` {'matches': results, 'limited': limited, 'files_scanned': scanned} ` |

Raises directly: `ValueError('Raw FFDC files are unavailable for this report.')` (line 313); `ValueError('Supply 1 to 6 nonempty literal search terms, at most 160 characters each.')` (line 315). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.search_evidence`

Source: [ffdc_chat.py:335-361](../ffdc_chat.py#L335).

Search evidence. Delegates to `ensure_index`, `search_index`, `self.paths`, `self.search_logs`. Literal result/intermediate fields include `bytes_indexed`, `files_available`, `files_indexed`, `index_available`, `limited`, `matches`, `note`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| terms | not annotated | ` (required) ` | Terms; operation-specific input consumed by this function. No stricter schema is declared. |
| match_all | bool | ` False ` | Match all; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 351 | dict | ` {**fallback, 'index_available': False, 'limited': True, 'note': 'Full-text index unavailable; bounded literal search was used.'} ` |
| 353 | dict | ` {'matches': matches, 'index_available': True, 'limited': meta['limited'] == '1', 'files_available': int(meta['files_available']), 'files_indexed': int(meta['files_indexed']), 'bytes_indexed': int(meta['bytes_indexed']), 'note': 'Search hits are leads, not diagnoses. Read surrounding lines. No matches in an incomplete index do not prove absence.'} ` |

Raises directly: `ValueError('Raw FFDC files are unavailable for this report.')` (line 337); `ValueError('Supply 1 to 6 nonempty literal terms and an optional boolean match_all.')` (line 341); `None` (line 347). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.triage_ffdc`

Source: [ffdc_chat.py:363-419](../ffdc_chat.py#L363).

Triage FFDC. Delegates to `self.lines`, `self.paths`. Literal result/intermediate fields include `bytes_scanned`, `files_scanned`, `findings`, `focus`, `limited`, `line`, `note`, `path`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| focus | str | ` 'all' ` | Focus; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 410 | dict | ` {'focus': focus, 'findings': findings, 'files_scanned': scanned, 'unreadable_files': unreadable + self.unreadable_paths, 'bytes_scanned': consumed, 'scan_byte_limit': TRIAGE_SCAN_BYTES, 'limited': limited, 'note': 'Triage findings are leads, not confirmed root cause. Read surrounding lines before concluding.'} ` |

Raises directly: `ValueError('Raw FFDC files are unavailable for this report.')` (line 365); `ValueError('Use a supported FFDC triage focus.')` (line 368). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.issue_summary`

Source: [ffdc_chat.py:421-429](../ffdc_chat.py#L421).

Issue summary. Literal result/intermediate fields include `author`, `body`, `comments`, `created`, `description`, `engineer`, `key`, `status`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| issue | not annotated | ` (required) ` | JIRA issue record or key as expected by this function; see caller and body. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 425 | dict | ` {'key': key, 'url': self.jira_base + '/browse/' + quote(key), 'summary': fields.get('summary'), 'status': (fields.get('status') or {}).get('name'), 'engineer': (fields.get('assignee') or {}).get('displayName'), 'updated': fields.get('updated'), 'description': str(fields.get('description') or '')[:16000], 'comments': [{'author': (c.get('author') or {}).get('displayName'), 'created': c.get('created' ` |

### `EvidenceTools.get_jira_issue`

Source: [ffdc_chat.py:431-438](../ffdc_chat.py#L431).

Retrieve JIRA issue. Delegates to `self.issue_summary`. Literal result/intermediate fields include `issue`, `source`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| key | not annotated | ` (required) ` | Key; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 438 | dict | ` {'source': 'live JIRA', 'issue': self.issue_summary(data)} ` |

Raises directly: `ValueError('Invalid JIRA key.')` (line 434). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.search_jira`

Source: [ffdc_chat.py:440-445](../ffdc_chat.py#L440).

Search JIRA. Delegates to `self.issue_summary`. Literal result/intermediate fields include `fields`, `issues`, `jql`, `maxResults`, `source`, `total`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| jql | not annotated | ` (required) ` | Jql; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 445 | dict | ` {'source': 'live JIRA', 'total': data.get('total'), 'issues': [self.issue_summary(i) for i in data.get('issues', [])]} ` |

Raises directly: `ValueError('Supply a JQL query of at most 2000 characters.')` (line 442). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `EvidenceTools.search_project_milestones`

Source: [ffdc_chat.py:447-450](../ffdc_chat.py#L447).

Search project milestones. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| query | str | ` '' ` | Project/issue/name search string or parsed query data as used by this function. |
| within_days | NoneType | ` None ` | Within days; operation-specific input consumed by this function. No stricter schema is declared. |
| limit | int | ` 12 ` | Maximum result/sample count, or operation-specific limit; default shown below. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 450 | dynamic (not annotated) | ` self.project_search(query=query, within_days=within_days, limit=limit) ` |

Raises directly: `ValueError('Project milestone data is unavailable.')` (line 449). Delegated exceptions may also propagate.

### `run_chat`

Source: [ffdc_chat.py:453-568](../ffdc_chat.py#L453).

Build the language/evidence policy and bounded history, execute up to ten model/tool rounds and up to two final no-tool synthesis attempts, and return a cleaned answer or raise.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |
| history | not annotated | ` (required) ` | Prior user/assistant messages; downstream chat bounds role, count and length. |
| context | not annotated | ` (required) ` | Evidence/context mapping supplied to parsing or model orchestration. |
| tools | not annotated | ` (required) ` | Evidence tool provider exposing schemas and controlled execution. |
| complete | not annotated | ` (required) ` | Injected completion callback receiving a model request payload. |
| clean | not annotated | ` (required) ` | Callable used to normalize model-returned text. |
| language | not annotated | ` (required) ` | Answer language selector; chat branches distinguish Chinese from English. |
| instructions | str | ` '' ` | Instructions; operation-specific input consumed by this function. No stricter schema is declared. |
| investigate | bool | ` False ` | Investigate; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 538 | dynamic (not annotated) | ` answer ` |

Raises directly: `RuntimeError('AI API returned no response.')` (line 506); `ValueError()` (line 519); `RuntimeError('AI returned no answer after evidence retrieval. Please retry.')` (line 539); `RuntimeError('AI API returned no response.')` (line 552); `RuntimeError('AI evidence lookup limit reached before a final answer was produced. Please retry.')` (line 568). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

## `workspace_analysis.py` Callable Details

### `focus_for`

Source: [workspace_analysis.py:39-40](../workspace_analysis.py#L39).

Focus for. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 40 | list | ` [name for name, pattern in FOCUS_WORDS.items() if re.search(pattern, str(question), re.I)] ` |

### `WorkspaceEvidenceTools.__init__`

Source: [workspace_analysis.py:44-53](../workspace_analysis.py#L44).

init. Delegates to `super().__init__`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| sections | NoneType | ` None ` | Sections; operation-specific input consumed by this function. No stricter schema is declared. |
| *args | tuple | ` (variadic) ` | *args; operation-specific input consumed by this function. No stricter schema is declared. |
| **kwargs | dict | ` (variadic) ` | **kwargs; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.schemas`

Source: [workspace_analysis.py:55-61](../workspace_analysis.py#L55).

Schemas. Delegates to `function`, `super().schemas`. Literal result/intermediate fields include `enum`, `minimum`, `offset`, `section`, `type`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 61 | dynamic (not annotated) | ` schemas ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.add_source`

Source: [workspace_analysis.py:63-67](../workspace_analysis.py#L63).

Add source. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| source | not annotated | ` (required) ` | Source; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `WorkspaceEvidenceTools.read_report_section`

Source: [workspace_analysis.py:69-79](../workspace_analysis.py#L69).

Read report section. Delegates to `bounded_context`, `self.add_source`. Literal result/intermediate fields include `data`, `description`, `kind`, `label`, `next_offset`, `offset`, `section`, `total`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| section | not annotated | ` (required) ` | Section; operation-specific input consumed by this function. No stricter schema is declared. |
| offset | int | ` 0 ` | Zero-based pagination offset. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 78 | dict | ` {'section': section, 'data': bounded_context({section: page})[section], 'offset': offset, 'total': total, 'next_offset': offset + 20 if total is not None and offset + 20 < total else None} ` |

Raises directly: `ValueError('Unknown parsed report section.')` (line 71). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.read_log`

Source: [workspace_analysis.py:81-85](../workspace_analysis.py#L81).

Read log. Delegates to `self.add_source`, `super().read_log`. Literal result/intermediate fields include `end`, `kind`, `path`, `start`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| start | not annotated | ` (required) ` | Starting source line or range boundary as defined by the function. |
| count | int | ` 60 ` | Requested record/line count; evidence readers clamp it. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 85 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.get_jira_issue`

Source: [workspace_analysis.py:87-91](../workspace_analysis.py#L87).

Retrieve JIRA issue. Delegates to `self.add_source`, `super().get_jira_issue`. Literal result/intermediate fields include `description`, `kind`, `label`, `url`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| key | not annotated | ` (required) ` | Key; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 91 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.search_project_milestones`

Source: [workspace_analysis.py:93-97](../workspace_analysis.py#L93).

Search project milestones. Delegates to `self.add_source`, `super().search_project_milestones`. Literal result/intermediate fields include `description`, `kind`, `label`, `url`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| **kwargs | dict | ` (variadic) ` | **kwargs; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 97 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.execute`

Source: [workspace_analysis.py:99-106](../workspace_analysis.py#L99).

Execute. Delegates to `super().execute`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| args | not annotated | ` (required) ` | Args; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 102 | dynamic (not annotated) | ` self.cached_results[cache_key] ` |
| 106 | dynamic (not annotated) | ` result ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.triage_ffdc`

Source: [workspace_analysis.py:108-160](../workspace_analysis.py#L108).

Distribute a bounded scan across files and keep diverse, contextual leads.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| focus | str | ` 'all' ` | Focus; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 160 | dynamic (not annotated) | ` result ` |

Raises directly: `ValueError('Raw FFDC files are unavailable for this report.')` (line 111); `ValueError('Unknown focus.')` (line 113). Delegated exceptions may also propagate.

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.reopen_sources`

Source: [workspace_analysis.py:162-182](../workspace_analysis.py#L162).

Revalidate a few prior-turn citations against the current report's files.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| sources | not annotated | ` (required) ` | Sources; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 166 | dynamic (not annotated) | ` excerpts ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.prepare`

Source: [workspace_analysis.py:184-230](../workspace_analysis.py#L184).

Choose a component focus from the question, triage raw files, then read up to eight contextual excerpts to seed an evidence-grounded answer.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| question | not annotated | ` (required) ` | Latest natural-language question; keep the original wording for language and scope. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 186 | dict | ` {'available': False, 'note': 'No original FFDC text logs are available; use parsed report/JIRA evidence only.'} ` |
| 196 | dynamic (not annotated) | ` triage ` |
| 225 | dict | ` {'available': True, 'scan': self.scan, 'indexed_search': index_summary, 'log_catalog': {'files': (catalog or {}).get('files', [])[:40], 'next_offset': (catalog or {}).get('next_offset')} if catalog else None, 'excerpts': excerpts, 'domain_pack_evidence': domain_pack_evidence, 'note': 'These surrounding log lines were read before answering. They may show recovery, normal empty slots, or old events. ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `WorkspaceEvidenceTools.unsupported_citations`

Source: [workspace_analysis.py:232-238](../workspace_analysis.py#L232).

Identify backtick path/line citations not wholly contained in previously read log ranges; does not establish claim correctness.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |
| answer | not annotated | ` (required) ` | Answer; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 238 | dynamic (not annotated) | ` unsupported ` |

### `WorkspaceEvidenceTools.metadata`

Source: [workspace_analysis.py:240-243](../workspace_analysis.py#L240).

Metadata. Literal result/intermediate fields include `elapsed_seconds`, `reopened_sources`, `scan`, `sources`, `tool_calls`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| self | not annotated | ` (required) ` | Current class instance; supplied by Python method binding. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 241 | dict | ` {'sources': self.sources, 'scan': self.scan, 'tool_calls': len(self.audit), 'reopened_sources': self.reopened_sources, 'elapsed_seconds': round(time.monotonic() - self.started, 1)} ` |

## `workspace_ui.py` Callable Details

### `workspace_navigation`

Source: [workspace_ui.py:19-24](../workspace_ui.py#L19).

Workspace navigation. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| active | str | ` '' ` | Active; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 24 | str | ` ''.join(links) ` |

### `workspace_page_identity`

Source: [workspace_ui.py:27-43](../workspace_ui.py#L27).

Workspace page identity. Literal result/intermediate fields include `/Defect_review`, `/Defect_review_ffdcs`, `/Defect_review_result`, `/Defect_review_similar`, `/jira-results`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 30 | tuple | ` ('defect', {'/Defect_review': 'Defect Review', '/Defect_review_result': 'Defect Review Result', '/Defect_review_similar': 'Similar JIRA Bugs', '/Defect_review_ffdcs': 'Defect FFDC Files', '/jira-results': 'JIRA FFDC Results'}.get(route, 'Defect Review')) ` |
| 38 | tuple | ` ('milestones', 'IOSS key milestones and defects mapping') ` |
| 40 | tuple | ` ('usage', 'Usage') ` |
| 42 | tuple | ` ('reports', 'FFDC Analyzer Report') ` |
| 43 | tuple | ` ('reports', 'Reports') ` |

### `classic_url`

Source: [workspace_ui.py:46-49](../workspace_ui.py#L46).

Classic url. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 49 | bool | ` parsed._replace(query=urlencode(query)).geturl() or '/' ` |

### `render_workspace_subpage`

Source: [workspace_ui.py:52-101](../workspace_ui.py#L52).

Extract the existing main content and place it in the opt-in shared workspace shell while preserving the classic route.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| legacy_page | not annotated | ` (required) ` | Legacy page; operation-specific input consumed by this function. No stricter schema is declared. |
| request_path | not annotated | ` (required) ` | Request path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 58 | dynamic (not annotated) | ` page ` |
| 84 | dynamic (not annotated) | ` head + '</head><body class="workspace-subpage-body">' + f'\n<header class="workspace-topbar">\n  <div class="brand-group"><button class="icon-button mobile-nav" id="subpage-toggle-sidebar" title="Navigation" aria-label="Navigation" aria-expanded="false"><i data-lucide="panel-left"></i></button>\n  <a class="workspace-brand" href="/new-version"><img src="/static/lenovo_logo.png" alt="Lenovo"><span> ` |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 73 | ` main.start() ` |

### `render_workspace_page`

Source: [workspace_ui.py:104-176](../workspace_ui.py#L104).

Return the new conversation workspace HTML with navigation, chat, file input, evidence dialog and a user-activated report link.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| message | str | ` '' ` | Request message or progress text, depending on this function. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 115 | dynamic (not annotated) | ` '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n  <title>ThinkSystem FFDC Analyzer Workspace</title>\n  <link rel="stylesheet" href="/static/workspace.css?v=__VERSION__">\n  <script defer src="/static/workspace-marked.js?v=__VERSION__"></script>\n  <script defer src="/static/workspace-lucide.js?v=__VERSION__"> ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

## `ffdc_config.py` Callable Details

### `env_int`

Source: [ffdc_config.py:12-28](../ffdc_config.py#L12).

Return an integer environment value, falling back to *default*.

A malformed deployment variable should not prevent the service from
starting. Bounds are applied after parsing so queue and worker settings
cannot become negative or unreasonably large by accident.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| default | not annotated | ` (required) ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |
| minimum | NoneType | ` None ` | Minimum; operation-specific input consumed by this function. No stricter schema is declared. |
| maximum | NoneType | ` None ` | Maximum; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 28 | dynamic (not annotated) | ` value ` |

### `env_float`

Source: [ffdc_config.py:31-42](../ffdc_config.py#L31).

Return a bounded floating-point environment value.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| default | not annotated | ` (required) ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |
| minimum | NoneType | ` None ` | Minimum; operation-specific input consumed by this function. No stricter schema is declared. |
| maximum | NoneType | ` None ` | Maximum; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 42 | dynamic (not annotated) | ` value ` |

### `env_path`

Source: [ffdc_config.py:45-48](../ffdc_config.py#L45).

Return a non-empty environment path or the supplied default.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| default | not annotated | ` (required) ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 48 | dynamic (not annotated) | ` Path(str(raw).strip()) if raw and str(raw).strip() else Path(default) ` |

### `env_url`

Source: [ffdc_config.py:51-54](../ffdc_config.py#L51).

Return a trimmed URL without a trailing slash.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| name | not annotated | ` (required) ` | Name; operation-specific input consumed by this function. No stricter schema is declared. |
| default | not annotated | ` (required) ` | Default; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 54 | dynamic (not annotated) | ` str(raw or default).strip().rstrip('/') ` |

## `ffdc_jobs.py` Callable Details

### `safe_job_id`

Source: [ffdc_jobs.py:16-18](../ffdc_jobs.py#L16).

Keep the historical alphanumeric job-id normalization behavior.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 18 | dynamic (not annotated) | ` re.sub('[^A-Za-z0-9_-]', '', str(job_id or '')) ` |

### `job_path`

Source: [ffdc_jobs.py:21-23](../ffdc_jobs.py#L21).

Job path. Delegates to `safe_job_id`. (Intent inferred from the complete function AST; see return/effect details.)

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| directory | not annotated | ` (required) ` | Directory; operation-specific input consumed by this function. No stricter schema is declared. |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 23 | dynamic (not annotated) | ` Path(directory) / f'{normalized}.json' if normalized else None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `_atomic_write_json`

Source: [ffdc_jobs.py:26-42](../ffdc_jobs.py#L26).

Write JSON next to the target and replace it atomically.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| path | not annotated | ` (required) ` | Filesystem or relative log path; evidence tools require containment in the current report. |
| payload | not annotated | ` (required) ` | Payload; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

| Line | Direct filesystem/network/process/synchronization call |
| --- | --- |
| 29 | ` path.parent.mkdir(parents=True, exist_ok=True) ` |
| 37 | ` os.replace(temporary, path) ` |
| 40 | ` os.unlink(temporary) ` |

### `persist_job`

Source: [ffdc_jobs.py:45-53](../ffdc_jobs.py#L45).

Persist a job and update the latest pointer when appropriate.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job | not annotated | ` (required) ` | Job; operation-specific input consumed by this function. No stricter schema is declared. |
| directory | not annotated | ` (required) ` | Directory; operation-specific input consumed by this function. No stricter schema is declared. |
| latest_path | not annotated | ` (required) ` | Latest path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 49 | dynamic (not annotated) | ` None ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `load_job`

Source: [ffdc_jobs.py:56-79](../ffdc_jobs.py#L56).

Load a job and mark interrupted running work after a restart.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| job_id | not annotated | ` (required) ` | Background job identifier for lookup/progress/persistence. |
| directory | not annotated | ` (required) ` | Directory; operation-specific input consumed by this function. No stricter schema is declared. |
| persist | NoneType | ` None ` | Persist; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 60 | NoneType | ` None ` |
| 79 | dynamic (not annotated) | ` data ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

### `cleanup_jobs`

Source: [ffdc_jobs.py:82-91](../ffdc_jobs.py#L82).

Remove expired in-memory jobs while leaving disk snapshots intact.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| jobs | not annotated | ` (required) ` | Jobs; operation-specific input consumed by this function. No stricter schema is declared. |
| lock | not annotated | ` (required) ` | Lock; operation-specific input consumed by this function. No stricter schema is declared. |
| ttl_seconds | not annotated | ` (required) ` | Ttl seconds; operation-specific input consumed by this function. No stricter schema is declared. |
| now | NoneType | ` None ` | Now; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| — | None or generator | No explicit return; inspect yields and side effects. Constructor methods initialize the instance. |

### `latest_job_id`

Source: [ffdc_jobs.py:94-100](../ffdc_jobs.py#L94).

Read and validate the persisted latest-job pointer.

| Parameter | Type / inference | Default | Meaning |
| --- | --- | --- | --- |
| latest_path | not annotated | ` (required) ` | Latest path; operation-specific input consumed by this function. No stricter schema is declared. |

Returns: not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.

| Line | Observed type | Returned value / expression |
| --- | --- | --- |
| 99 | str | ` '' ` |
| 100 | dynamic (not annotated) | ` safe_job_id(data.get('job_id', '')) if isinstance(data, dict) else '' ` |

Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.

