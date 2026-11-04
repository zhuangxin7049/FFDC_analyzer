# FFDC Analyzer Project Handoff

## Purpose

ThinkSystem FFDC Analyzer is an internal engineering tool for collecting, parsing, reviewing, and explaining Lenovo ThinkSystem FFDC evidence. It combines deterministic parsers and checks with Davy AI so that engineers can locate evidence faster and continue the investigation through a read-only conversation.

The analyzer is evidence-oriented: parsed facts and original log excerpts are the source of truth. AI may correlate evidence and suggest likely causes, but it must distinguish confirmed observations from inference.

## Current Runtime

- Service: `ffdc-analyzer.service`
- Server-side project directory: `/home/zhuangxin2/ffdc_analyzer`
- Application port: `8088`
- Main entry point: `app.py`
- New workspace entry: `/new-version`
- Classic report entry: `/report?id=<report-id>`
- Report retention: 30 days
- Usage statistics retention: 30 days

Do not place passwords, JIRA tokens, AI API keys, or server login credentials in this repository or in this document. They are configured on the server through protected files and environment variables.

## Source Map

| File | Responsibility |
| --- | --- |
| `app.py` | HTTP server, upload jobs, FFDC extraction, deterministic parsers, automated checks, JIRA integration, scheduler, report persistence, AI report calls, and route handling. |
| `ffdc_chat.py` | Read-only evidence tools, bounded report context, conversation loop, tool schemas, citation checking, and chat Markdown cleanup. |
| `workspace_analysis.py` | New-workspace evidence preparation, bounded raw-log triage, source reopening, and investigation instructions. |
| `workspace_ui.py` | Server-rendered new workspace and report UI shell. |
| `evidence_index.py` | Report-local full-text index used by evidence search. |
| `ffdc_config.py` | Bounded, fault-tolerant environment configuration parsing. |
| `ffdc_jobs.py` | Atomic persisted job snapshots and interrupted-job handling. |
| `static/` | Browser JavaScript, CSS, Markdown renderer, icon library, and Lenovo logo. |
| `templates/` | Server-side template assets, when present. |
| `docs/` | Technical specification, requirements, maintenance notes, logic plan, and source inventory. |

## AI Model Routing

The model name shown in the UI is returned by the configured service. Source defaults and overrides are:

| Capability | Default / selection rule |
| --- | --- |
| Standard generated FFDC report | Configured text model; code fallback is `gpt-5.2`. |
| Deep Investigation | `FFDC_DEEP_INVESTIGATION_MODEL`, default `nemotron-3-ultra`. |
| Classic chat and Defect Review chat | `FFDC_CHAT_MODEL`, default `nemotron-3-ultra`. |
| New workspace chat | `FFDC_WORKSPACE_CHAT_MODEL`, otherwise the chat model, otherwise the configured text model. |
| JIRA screenshot interpretation | `FFDC_VISION_MODEL`, default `gemma-4-31b-it`; OCR remains a fallback. |

The configured AI key file can override the base URL and text model. Therefore, a source default is not proof of the model currently serving production traffic. Verify the server configuration before making performance or quality claims.

## Evidence and Investigation Rules

1. Deterministic parsing runs before AI reasoning.
2. Automated checks are observations or leads, not automatic root-cause confirmation.
3. For broad FFDC questions, the assistant should run bounded triage first.
4. A search result must be followed by reading surrounding original log lines before a conclusion.
5. Evidence citations must use an actual relative path and line number returned by a tool.
6. Missing matches in a limited scan do not prove that a fault is absent.
7. JIRA-linked analysis filters FFDC findings against the Bug title, description, reproduction steps, comments, component, symptom, trigger, and time window.
8. `sep_info.txt`, `sep_vpd.txt`, and `backplanes.txt` describe built-in backplanes. An E-suffix adapter such as `940-8e` is external storage and must be analyzed separately.
9. Internal storage such as `9350-8i` and external storage may coexist. Internal backplane registers remain valid for the internal path.
10. JIRA write operations require the user's own JIRA login. Read-only analysis uses server-side integration only where explicitly configured.

## Conversation Limits

- The request endpoint accepts a current message up to 16,000 characters.
- The server sends at most the latest 8 history messages to the model, usually about 4 user/assistant turns.
- Each report section receives an independent approximately 6,000-character compacting budget.
- The conversation loop allows up to 10 model/tool cycles, with at most 4 tool calls in one cycle.
- A single raw-log read returns at most 100 lines.
- The model response budget for interactive chat is 4,096 tokens.

Large FFDC packages are not placed into the prompt in full. The assistant starts from a compact report and reads additional evidence through bounded, read-only tools.

## Safe Change Procedure

1. Read `README.md`, this document, `ARCHITECTURE.md`, and `CURRENT_STATUS.md`.
2. Inspect the existing implementation and current service state.
3. Make the smallest change that preserves evidence boundaries and existing route contracts.
4. Run focused tests before deployment.
5. Back up the complete current project, runtime data and actual service configuration to a separate data disk; verify the copy before replacing files.
6. Run `python3 -m py_compile` on changed Python files.
7. Restart the service only after local validation.
8. Verify `systemctl is-active ffdc-analyzer.service`, `/new-version`, served asset hashes and the changed UI/API path; there is no `/health` endpoint.
9. Record the change and any remaining uncertainty in `CURRENT_STATUS.md`.

## Do Not Do

- Do not commit `api_key.txt`, `.jira_similar_pat`, JIRA passwords, AI keys, cookies, uploaded FFDC, or generated reports.
- Do not treat an AI explanation as evidence without a source path and line reference.
- Do not broaden backplane evidence from internal files to external E-suffix storage.
- Do not use a user's JIRA credentials for background writes or store them in browser local storage.
- Do not expose raw server logs or credentials in an AI response.
