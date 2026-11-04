# FFDC Analyzer: Environment and Dependencies

## Baseline and Scope

This documentation describes the local source snapshot inspected on **2026-09-30**, not a newly verified production deployment. The executable product consists of `app.py`, `ffdc_chat.py`, `workspace_analysis.py`, `workspace_ui.py`, `ffdc_config.py`, `ffdc_jobs.py`, and `static/`. Historical `app.py.*` copies, one-off diagnostic scripts, test fixtures, presentation/video outputs, and the separate Knowledge Base patch are inventoried separately.

English is the documentation language because comments, prompts, and interface strings in the runtime modules are predominantly English. Chinese user questions and original evidence remain supported by the application.

The inventory reads the complete bytes of every regular workspace file outside generated `docs/` and Git internals. Root Python files and historical application copies receive complete AST traversal, not signature-only inspection. Binary files are hashed rather than interpreted as source. Credentials and diagnostic contents are not reproduced. See [AuditInventory.md](AuditInventory.md) for coverage and [Maintenance.md](Maintenance.md) for limits of static analysis.

## Python Version

**Inferred runtime minimum: Python 3.9.** This is a source/API compatibility inference, not a claim that every version has been integration-tested.

| Evidence | Required version | Source |
| --- | --- | --- |
| `Path.is_relative_to()` in evidence containment and report handling | 3.9+ | `ffdc_chat.py:215`; `app.py:11416` |
| `Path.unlink(missing_ok=True)` in attachment cleanup | 3.8+ | `app.py:6875`, `6945`, `7324` |
| f-strings throughout HTTP/rendering code | 3.6+ | `app.py:249` and subsequent functions |
| Optional `cgi` import catches `ModuleNotFoundError`; streaming multipart fallback is implemented | Supports removal of `cgi` in 3.13+, subject to tests | `app.py:132-135`, `199-263`, `13808-13817` |

The full source also passed syntax parsing with the version grammars recorded in `_audit/validation.json`. Syntax acceptance does not establish dependency or archive-extraction behavior on an older interpreter. In particular, the legacy tar extraction code does not specify an explicit extraction filter, so Python-version-dependent extraction behavior is a maintenance risk.

## Dependency Tables

### Third-Party Python Packages

| Library | Version | Specific purpose |
| --- | --- | --- |
| None imported by the six runtime Python modules | Not applicable | HTTP serving, JIRA/AI requests, JSON/CSV, ZIP/XLSX generation, parsing, threading, configuration parsing, and job persistence use the standard library. |

The root `requirements.txt` documents the deliberate standard-library-only runtime policy. `requirements-optional.txt` contains the optional `pypdf` dependency for PDF text extraction; the service can use `pdftotext` instead. There is no dependency lockfile. Packages bundled under the video deliverable are production-media tooling, not FFDC service dependencies.

### Browser Libraries

| Library | Version | Specific purpose |
| --- | --- | --- |
| Marked | 17.0.5, embedded header | Tokenize Markdown in `static/workspace-marked.js`; `workspace.js` renders tokens into controlled DOM nodes rather than executing model-provided HTML. MIT license is included. |
| Lucide | 1.8.0, embedded header | Navigation and action icons in `static/workspace-lucide.js`; license file included. |

No frontend package installation or bundler is required for the shipped static files.

### Operating-System Tools

| Tool | Version | Specific purpose |
| --- | --- | --- |
| `lzop` | Not pinned | Decompress `.tzz`/LZO inputs to `ffdc.tar`; `unpack_ffdc`. |
| `zstd` | Not pinned | Decompress `.tar.zst`/`.tzst` inputs; `unpack_ffdc`. |
| `tar` | Not pinned | Rebuild a downloadable TAR from gzip/TGZ extraction. |
| `7z` | Not pinned | List, validate, and extract JIRA `.zip`, `.rar`, and `.7z` log attachments; `list_7z_archive_entries`, `analyze_jira_log_archive`. Actual archive codec support depends on the installed binary. |
| `tesseract` with `eng` and `chi_sim` language data | Not pinned; optional fallback | OCR when the configured vision model cannot provide attachment evidence. Page segmentation modes 6 and 11 are attempted. |
| Nginx | Not pinned; optional reverse proxy | The provided FFDC configuration forwards port 80 to `127.0.0.1:8088`. |
| systemd | Deployment convention; non-secret example included | Production service administration uses an externally installed unit, historically `ffdc-analyzer.service`. Review [deploy/ffdc-analyzer.service.example](../deploy/ffdc-analyzer.service.example) and verify the host unit before changing it. |

### System Environment

| Area | Requirement and limitation |
| --- | --- |
| Operating system | Linux is the intended server environment, based on Nginx configuration, Unix command dependencies, and deployment paths. Core modules can be imported on macOS; that does not validate all production workflows there. |
| Browser | A desktop browser supporting `fetch`, `AbortController`, `dialog`, optional chaining, `Array.at`, Web Storage, and CSS used by the shipped workspace. No exact supported browser-version matrix is declared. |
| Network | Reachability to configured JIRA, the configured AI base URL, Project Tool, and any permitted external FFDC download host. Read and write permissions are separate concerns. |
| Filesystem | Writable upload, report, extraction, cache, and job-state directories beneath the application root. Account for raw upload + expanded TAR + extracted logs + retained report/cache copies. No measured minimum disk/RAM capacity is declared. |
| AI service | An API accepting the configured text model and chat/tool-call schema; image analysis additionally needs a compatible vision model. Model names alone do not establish server availability. |
| Secrets | AI configuration file and JIRA PAT remain server-side. Scheduled JIRA/Project Tool credentials are separately configured. Never place actual values in these documents or browser assets. |
| Timezone | Scheduling uses host-local `time.localtime()`. Set and verify the service timezone; there is no explicit timezone field in scheduler configuration. |
| Exposure | Intended internal use is not a substitute for authentication or TLS. The source has important unresolved access-control and TLS risks documented in Maintenance. |

## Installation and Local Start

From a copy of the project root on an Ubuntu/Debian-style server:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv lzop zstd tar p7zip-full tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim
python3 -m venv .venv
. .venv/bin/activate
python -c 'import sys; assert sys.version_info >= (3, 9), sys.version'
command -v lzop zstd tar 7z tesseract
# Optional PDF dependency; omit when pdftotext is installed instead.
python -m pip install -r requirements-optional.txt
FFDC_HOST=127.0.0.1 FFDC_PORT=8088 python app.py
```

Distribution package names and available archive codecs must be checked on the target OS; the executable names above are the actual application contract. No third-party package is necessary for the six runtime modules. Port 8088 must be free, or choose another `FFDC_PORT` and update the proxy accordingly.

Open `http://127.0.0.1:8088/new-version` for the conversation workspace or `/` for classic upload. `main()` creates the primary runtime directories and starts the scheduler thread. With no schedule configuration, scheduled processing is disabled. Parsing an uploaded FFDC is distinct from calling AI and can be exercised without an AI credential file. A deployment template is provided at [config/ffdc-analyzer.env.example](../config/ffdc-analyzer.env.example), and a non-secret systemd example is provided at [deploy/ffdc-analyzer.service.example](../deploy/ffdc-analyzer.service.example).

## Optional Integrations

1. Provision an AI configuration file through your normal secret-management process. Set `FFDC_API_KEY_FILE` to its path. The loader accepts labelled key/model lines and a base URL; see the precedence rules in [Specification.md](Specification.md).
2. Provision the JIRA PAT file and set `FFDC_JIRA_SIMILAR_PAT_FILE`. The default is `.jira_similar_pat` in the project root. Do not paste the token into frontend code.
3. Configure `defect_review_config.json` or `FFDC_JIRA_MONITOR_CONFIG` for scheduled processing. Fields include `enabled`, `username`, `password`, `times`, `project_tool_username`, and `project_tool_password`. An administrator must protect the file; values are loaded by the service.
4. Set `FFDC_SAMPLE` and `FFDC_KEYFILES` if the sample/demo route is needed. The historical `/root/codx_test/...` defaults are not supplied by this repository.
5. Install the Nginx FFDC configuration only after reviewing access controls. The adjacent `nginx-knowledgebase.conf` belongs to a different service on port 8087.

This documentation does not install packages, provision credentials, enable scheduling, change a saved JIRA filter, or deploy the service.

## Validation

```bash
python docs/_tools/audit_project.py
python docs/_tools/validate_project.py
```

The validation helper copies source and static assets into disposable directories before executing the existing tests. It does not copy real credential/configuration files. The current focused runtime suites pass **79 tests**, including configuration and job persistence tests. The historical monitor suite runs four tests with **one failure and one error**; see Maintenance. No live JIRA/AI or hardware acceptance test was performed for this documentation task.

<!-- GENERATED STANDARD LIBRARY -->

## Complete Runtime Standard-Library Import Index

| Module | Purpose | Imported by |
| --- | --- | --- |
| base64 | Encode authorization/image payloads. | app.py |
| cgi | Optional legacy multipart parser; fallback used when absent. | app.py |
| csv | Read JIRA current-field exports and produce CSV. | app.py |
| datetime | Dates, countdowns, status ages and timezones. | app.py, workspace_ui.py |
| email.message | Parse multipart Content-Type/Disposition parameters. | app.py |
| email.parser | Standard-library support; see import sites. | app.py |
| email.policy | Standard-library support; see import sites. | app.py |
| hashlib | Cache/client identifiers and content hashes. | app.py |
| html | Escape text and decode HTML entities. | app.py, ffdc_chat.py, workspace_ui.py |
| html.parser | Extract table rows from generated review HTML. | app.py |
| http | HTTP status constants. | app.py |
| http.cookiejar | Maintain Project Tool authentication cookies. | app.py |
| http.server | ThreadingHTTPServer and request handler base. | app.py |
| io | In-memory binary/text streams for exports. | app.py |
| json | Report, configuration, job state and API serialization. | app.py, ffdc_chat.py, ffdc_jobs.py, workspace_analysis.py |
| os | Environment settings and filesystem traversal/access. | app.py, ffdc_chat.py, ffdc_config.py, ffdc_jobs.py |
| pathlib | Filesystem paths, traversal checks and report directories. | app.py, ffdc_chat.py, ffdc_config.py, ffdc_jobs.py |
| re | Log parsing, Bug recognition, validation and text normalization. | app.py, ffdc_chat.py, ffdc_jobs.py, workspace_analysis.py, workspace_ui.py |
| shutil | Copies, directory cleanup and executable discovery. | app.py |
| sqlite3 | Standard-library support; see import sites. | ffdc_chat.py |
| ssl | TLS contexts for outbound integrations; currently unverified in app.py. | app.py |
| subprocess | Invoke decompression, 7z and OCR executables. | app.py |
| tarfile | Read/extract TAR and compressed log members. | app.py |
| tempfile | Temporary attachment extraction directories. | app.py, ffdc_jobs.py |
| threading | HTTP workers, job threads, locks and capacity limits. | app.py |
| time | Timestamps, retention, polling, throttles and scheduling. | app.py, ffdc_jobs.py, workspace_analysis.py |
| urllib.error | Handle HTTP/network failures. | app.py |
| urllib.parse | URL/query encoding, parsing and quoting. | app.py, ffdc_chat.py, workspace_ui.py |
| urllib.request | Outbound JIRA/Project Tool/AI HTTP requests. | app.py |
| uuid | Job/report/session identifiers and renderer tokens. | app.py, ffdc_chat.py |
| zipfile | Create XLSX ZIP containers and inspect archive content. | app.py |
| zoneinfo | Standard-library support; see import sites. | workspace_ui.py |

