# FFDC Analyzer Architecture

## Request Flow

```text
Browser
  |
  v
app.py HTTP routes
  |
  +--> Upload / JIRA attachment job
  |       |
  |       +--> archive extraction
  |       +--> deterministic parsers
  |       +--> automated checks
  |       +--> report.json
  |
  +--> Report and workspace chat
          |
          +--> compact report context
          +--> read-only evidence tools
          +--> Davy AI model
          +--> citation and source validation
          +--> answer / analysis trace
```

## Module Boundaries

### 1. Web and Request Control: `app.py`

Owns HTTP routing, request validation, upload jobs, report jobs, JIRA sessions, background work, and response formatting. It decides which workflow is active but should not silently turn an AI inference into a parser fact.

The server is being split by ownership boundary. `app.py` remains the
compatibility entrypoint while extracted modules provide independently tested
services for configuration parsing and job persistence.

### 1a. Configuration: `ffdc_config.py`

Provides bounded parsing for integer and floating-point environment values and
normalizes paths and URLs. Keeping defaults and validation helpers outside the
HTTP module makes deployment configuration testable without starting the
server.

### 1b. Background Job Persistence: `ffdc_jobs.py`

Owns safe job-id normalization, atomic JSON snapshots, latest-job pointers,
restart recovery for interrupted jobs, and in-memory expiry cleanup. The JIRA
monitor keeps its existing application-level dictionaries and workflow policy,
but delegates filesystem mechanics to this module. A future SQLite or queue
adapter can replace this boundary without changing the routes.

### 2. File Intake and Discovery: `app.py`

Receives an FFDC archive, validates supported formats, extracts it into an isolated report directory, and discovers candidate files. Supported archive paths include `.tzz`, `.tar.zst`, `.tzst`, `.tgz`, `.tar.gz`, `.tar`, and `.gz`, subject to installed archive tools.

### 3. Domain Parsers: `app.py`

Converts raw files into structured facts for storage, PCIe, drives, backplanes, UEFI, network, FPGA, PLDM, MCTP, BMC/BMU in-band firmware, and system health. Parsers should report missing data explicitly instead of fabricating defaults.

### 4. Rule and Health Checks: `app.py`

Runs deterministic checks over parsed facts. It assigns severity and records evidence. A warning or critical check is a confirmed parser/check observation, but it is not automatically the root cause of the user's JIRA Bug.

### 5. Evidence Investigation: `ffdc_chat.py` and `workspace_analysis.py`

Provides bounded tools to list files, search logs, search the evidence index, read line ranges, run triage, reopen earlier sources, and query the report sections. This layer controls what evidence is available to the model.

### 6. AI Reasoning and Report Generation: `app.py` and `ffdc_chat.py`

Builds prompts from parsed evidence, JIRA context, and verified tool results. Davy can correlate evidence and explain possible causes, but the prompts require it to label uncertainty and avoid invented paths, commands, errors, versions, and test results.

### 7. Presentation Layer: `workspace_ui.py` and `static/`

Renders the new workspace, report view, chat messages, evidence trace, source links, and status states. Browser state is not the system of record; the server report and extracted evidence remain authoritative.

### 8. Persistence and Cache: `app.py`, `ffdc_jobs.py`, and `evidence_index.py`

Stores extracted FFDC, `report.json`, report-local indexes, JIRA attachment caches, background job state, milestone snapshots, and usage statistics. Runtime data is separate from source code and must not be copied into a source handoff package. Job snapshots use an atomic temporary-file replacement so a service restart cannot leave a partially written JSON file.

### 9. External Integrations

- JIRA REST API: issue details, comments, attachments, search, filters, and explicit comment writes.
- Project Tool: project milestone and node data through authenticated cookie/CSRF requests.
- Davy AI endpoint: text chat, evidence reasoning, report generation, and image interpretation.
- Local archive/OCR tools: `lzop`, `zstd`, `tar`, `7z`, and `tesseract` where installed.

## Data Ownership

```text
FFDC / JIRA / Project Tool
          |
          v
File intake and report storage
          |
          v
Parsed facts + deterministic checks + evidence index
          |
          +--> Report page
          |
          +--> Read-only evidence tools --> Davy AI --> grounded answer
```

The model is not the source of truth. It is a reasoning layer over evidence returned by the parser and tools.

## Extension Pattern

To add a new domain such as FPGA, thermal, NIC, UEFI, or PSU:

1. Add file discovery or candidate selection.
2. Add a focused parser returning a stable report section.
3. Add deterministic checks with explicit evidence and severity.
4. Add the section to the compact AI context.
5. Add tool/search terms only when raw-log follow-up is needed.
6. Add prompt rules that define scope and uncertainty.
7. Add report rendering and tests.

Do not add domain logic directly into the chat prompt. Domain facts belong in parsers and checks; the AI layer should consume them through an explicit contract.
