"""Build traceable Markdown appendices from full-source AST audit evidence."""
import ast
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
DATA = json.loads((DOCS / '_audit/structure.json').read_text(encoding='utf-8'))
CORE = ['app.py', 'ffdc_chat.py', 'workspace_analysis.py', 'workspace_ui.py', 'ffdc_config.py', 'ffdc_jobs.py']
TREES = {name: ast.parse((ROOT / name).read_text(encoding='utf-8')) for name in DATA['modules']}


def cell(value):
    if str(value).startswith('`') and str(value).endswith('`'):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', '')
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', '<br>').replace('\r', '').replace('&lt;br&gt;', '<br>')


def code(value):
    text = str(value).replace('\n', ' ')
    runs = re.findall(r'`+', text)
    fence = '`' * (max((len(run) for run in runs), default=0) + 1)
    return fence + ' ' + text + ' ' + fence


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'] + ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]) + '\n\n'


def ref(name, line, end=None):
    label = f'{name}:{line}' + (f'-{end}' if end and end != line else '')
    return f'[{label}](../{name}#L{line})'


def append_at(name, marker, content):
    path = DOCS / name
    current = path.read_text(encoding='utf-8').split(marker)[0].rstrip()
    path.write_text(current + '\n\n' + marker + '\n\n' + content, encoding='utf-8')


STD = {
    'base64': 'Encode authorization/image payloads.', 'csv': 'Read JIRA current-field exports and produce CSV.',
    'html': 'Escape text and decode HTML entities.', 'hashlib': 'Cache/client identifiers and content hashes.',
    'http.cookiejar': 'Maintain Project Tool authentication cookies.', 'io': 'In-memory binary/text streams for exports.',
    'json': 'Report, configuration, job state and API serialization.', 'os': 'Environment settings and filesystem traversal/access.',
    're': 'Log parsing, Bug recognition, validation and text normalization.', 'shutil': 'Copies, directory cleanup and executable discovery.',
    'ssl': 'TLS contexts for outbound integrations; currently unverified in app.py.',
    'subprocess': 'Invoke decompression, 7z and OCR executables.', 'tarfile': 'Read/extract TAR and compressed log members.',
    'urllib.error': 'Handle HTTP/network failures.', 'urllib.request': 'Outbound JIRA/Project Tool/AI HTTP requests.',
    'tempfile': 'Temporary attachment extraction directories.', 'threading': 'HTTP workers, job threads, locks and capacity limits.',
    'time': 'Timestamps, retention, polling, throttles and scheduling.', 'uuid': 'Job/report/session identifiers and renderer tokens.',
    'zipfile': 'Create XLSX ZIP containers and inspect archive content.', 'datetime': 'Dates, countdowns, status ages and timezones.',
    'http': 'HTTP status constants.', 'http.server': 'ThreadingHTTPServer and request handler base.',
    'email.message': 'Parse multipart Content-Type/Disposition parameters.', 'html.parser': 'Extract table rows from generated review HTML.',
    'pathlib': 'Filesystem paths, traversal checks and report directories.', 'urllib.parse': 'URL/query encoding, parsing and quoting.',
    'cgi': 'Optional legacy multipart parser; fallback used when absent.',
}

ENV_HELP = {
    'FFDC_SAMPLE': 'Optional archive used by the /sample route; not required for user uploads.',
    'FFDC_KEYFILES': 'Historical key-file resource path; inspect references before relying on it.',
    'FFDC_API_KEY_FILE': 'Server-only text file containing AI credential/provider/model configuration.',
    'FFDC_OPENAI_MODEL': 'Base text model; key-file model and per-feature overrides can take precedence.',
    'FFDC_OPENAI_BASE_URL': 'Base AI API URL; a URL in the key file takes precedence.',
    'FFDC_DEEP_INVESTIGATION_MODEL': 'Model used by the deep investigation stages.',
    'FFDC_CHAT_MODEL': 'Default evidence conversation model.',
    'FFDC_WORKSPACE_CHAT_MODEL': 'Optional new-workspace-specific override; empty falls back to CHAT_MODEL.',
    'FFDC_VISION_MODEL': 'Model used for supported screenshot images before OCR fallback.',
    'FFDC_JIRA_BASE_URL': 'Base JIRA URL for REST, attachment and issue links.',
    'FFDC_JIRA_SIMILAR_PAT_FILE': 'Server PAT file used by read-only Bug lookup and similar-case retrieval.',
    'FFDC_JIRA_MONITOR_FILTER_ID': 'Saved defect filter used by reviews and current status export.',
    'FFDC_JIRA_MONITOR_CONFIG': 'JSON schedule and JIRA/Project Tool credential configuration file.',
    'FFDC_JIRA_MONITOR_USERNAME': 'Scheduled JIRA username fallback; JSON can override it.',
    'FFDC_JIRA_MONITOR_PASSWORD': 'Scheduled JIRA password fallback; JSON can override it; never log.',
    'FFDC_DEFECT_REVIEW_EMAIL_TO': 'Recipient shown in the review email drafting workflow; not an SMTP account.',
    'FFDC_PROJECT_TOOL_BASE_URL': 'Project Tool base URL for login, tracker and milestone queries.',
    'FFDC_UPCOMING_MILESTONE_REPORT_ID': 'Project Tool custom report ID used to identify tracker projects.',
    'FFDC_JIRA_REQUEST_MIN_INTERVAL_SECONDS': 'Minimum inter-request spacing, converted to float seconds.',
    'FFDC_MAX_CONCURRENT_ANALYSES': 'Parser semaphore size, converted to integer and clamped to at least one.',
    'FFDC_HOST': 'HTTP bind address read in main.',
    'FFDC_PORT': 'HTTP listening port converted to integer in main.',
}

DESCRIPTIONS = {
    'analyze': 'Unpack an FFDC, select classic or V4 parsing, enrich component evidence, apply external-storage scope, run automatic checks, persist report.json and return the report.',
    'analyze_with_capacity': 'Acquire the nonblocking analysis semaphore, track active work, call analyze, and release capacity in a finally block; raises AnalysisBusyError if busy.',
    'run_automated_checks': 'Evaluate parsed inventories and logs for structured severity/category findings, applying component and backplane scope rules. Findings are parser observations, not proven root causes.',
    'parse_network_info': 'Combine PCI inventory and selected log excerpts into network adapters, interface observations, events and source paths; does not actively probe the machine.',
    'parse_bmc_inband_firmware_updates': 'Assemble BMC/BMU inband firmware attempts and events from selected update/PLDM/MCTP logs, preserving terminal-state uncertainty.',
    'parse_pldm_firmware_updates': 'Track PLDM firmware attempts, compatibility responses, component versions and terminal outcomes, enriched with controller identity.',
    'safe_extract_tar': 'Check resolved member names against the destination then extract the TAR. No explicit extraction filter or expansion quota is supplied in this implementation.',
    'unpack_ffdc': 'Select the decompressor using magic bytes and suffix, produce ffdc.tar/extract, and reject unexpected login/error payloads or unsupported inputs.',
    'search_similar_jira_cases': 'Search narrow title/signature JQL using the server PAT, score candidates, optionally widen PSoC context for Davy, and retain separate deterministic/model results.',
    'davy_rank_similar_jira_cases': 'Request a complete three-candidate Markdown assessment with engineer and differences, retry an incomplete result once, and fail rather than accept a placeholder.',
    'run_jira_monitor_job': 'Fetch the current filter and each defect context/evidence, reuse or analyze FFDC, generate AI review, refresh/reuse related cases and milestones, persist the snapshot and start the scheduled summary follow-up.',
    'run_current_status_summary_job': 'Read Project Tool tracker projects, conditionally update the saved JIRA filter, export current JIRA fields, normalize rows and persist summary state.',
    'workspace_chat_response': 'Validate message/report scope, discard conflicting Bug context, create an answer envelope, or start a PAT-backed JIRA FFDC job if no report is available.',
    'call_evidence_chat': 'Select the configured chat model and evidence-tool class, prepare raw context, execute the bounded tool loop, verify supported citation ranges and return answer/model.',
    'run_chat': 'Build the language/evidence policy and bounded history, execute up to ten model/tool rounds and up to two final no-tool synthesis attempts, and return a cleaned answer or raise.',
    'load_ai_config': 'Read the server AI configuration file, combine file/environment defaults and return base URL, secret key and model; callers must not expose the key.',
    'jira_image_comment': 'Reuse cached attachment interpretation or download an image, try vision then OCR, remove the temporary image and cache the resulting attributed evidence.',
    'jira_post_comment': 'Submit an actual JIRA comment using explicit user credentials; this is a write operation, not an evidence tool.',
    'jira_save_filter_jql': 'Update a saved JIRA filter using authenticated REST; summary generation can call this when tracker project IDs change.',
    'classify_backplane_scope': 'Classify the entire report as external storage when any adapter model matches the E-suffix regex; return excluded built-in evidence names.',
    'stream_multipart_upload': 'Stream the single FFDC multipart field to a sanitized timestamped upload path, maintaining boundary lookbehind and rejecting incomplete payloads.',
    'render_workspace_subpage': 'Extract the existing main content and place it in the opt-in shared workspace shell while preserving the classic route.',
    'render_workspace_page': 'Return the new conversation workspace HTML with navigation, chat, file input, evidence dialog and a user-activated report link.',
    'EvidenceTools.execute': 'Allow only tool schemas enabled for this context, dispatch arguments, record successful lookups and redact results; failures return an error dictionary.',
    'WorkspaceEvidenceTools.prepare': 'Choose a component focus from the question, triage raw files, then read up to eight contextual excerpts to seed an evidence-grounded answer.',
    'WorkspaceEvidenceTools.unsupported_citations': 'Identify backtick path/line citations not wholly contained in previously read log ranges; does not establish claim correctness.',
    'Handler.do_GET': 'Dispatch GET routes for pages, reports, evidence, exports, job polling and sample analysis. Several GET routes have local or integration side effects.',
    'Handler.do_POST': 'Dispatch chat, upload, analysis, review, comment and deletion requests; validation, credentials and response types differ by route.',
    'main': 'Create runtime directories, start the scheduler thread and serve HTTP on the configured host/port until interrupted.',
}
PARAMS = {
    'self': 'Current class instance; supplied by Python method binding.', 'report': 'Parsed FFDC/report mapping; optional JIRA/AI sections depend on origin.',
    'question': 'Latest natural-language question; keep the original wording for language and scope.',
    'message': 'Request message or progress text, depending on this function.', 'history': 'Prior user/assistant messages; downstream chat bounds role, count and length.',
    'upload_path': 'Path to an uploaded or downloaded FFDC archive.', 'extract_dir': 'Directory containing extracted FFDC source files.',
    'root': 'Optional raw-evidence root; absence disables raw log tools.', 'rid': 'Report identifier; validation depends on the calling path.',
    'report_id': 'Report identifier used for filesystem/metadata lookup.', 'job_id': 'Background job identifier for lookup/progress/persistence.',
    'issue_key': 'JIRA Bug key; validate/normalize before constructing requests.', 'issue': 'JIRA issue record or key as expected by this function; see caller and body.',
    'username': 'Authentication username, normally from explicit login or server configuration; never log credentials.',
    'password': 'Authentication secret; never include in browser responses or persisted documentation.',
    'api_key': 'Server API secret used for Authorization; never return it to the browser.',
    'url': 'Destination URL; destination validation and credential forwarding policy depend on the caller.',
    'path': 'Filesystem or relative log path; evidence tools require containment in the current report.',
    'text': 'Source text to parse/normalize/render; untrusted content must be escaped before HTML output.',
    'context': 'Evidence/context mapping supplied to parsing or model orchestration.', 'files': 'Evidence category-to-path mapping assembled from KEY_PATHS.',
    'pci': 'Parsed PCI/controller inventory.', 'fields': 'JIRA fields mapping or search-field selection according to the call site.',
    'progress': 'Optional callback for status/progress updates.', 'on_rate_limit': 'Optional callback invoked before rate-limit retry waits.',
    'cleanup': 'Whether report retention cleanup is run after successful analysis.', 'model_override': 'Optional per-call model selection; otherwise use the configured text model.',
    'complete': 'Injected completion callback receiving a model request payload.', 'clean': 'Callable used to normalize model-returned text.',
    'tools': 'Evidence tool provider exposing schemas and controlled execution.', 'language': 'Answer language selector; chat branches distinguish Chinese from English.',
    'attachment': 'JIRA attachment metadata, including filename/content or cached-source attributes.',
    'auth_headers': 'Optional prebuilt server-side authorization headers; must respect destination-origin policy.',
    'limit': 'Maximum result/sample count, or operation-specific limit; default shown below.', 'offset': 'Zero-based pagination offset.',
    'start': 'Starting source line or range boundary as defined by the function.', 'count': 'Requested record/line count; evidence readers clamp it.',
    'query': 'Project/issue/name search string or parsed query data as used by this function.',
    'today_key': 'Optional host-local date key used to select the same-day morning snapshot.',
    'include_similar_bug_analysis': 'True to search/analyze related defects; false to reuse a valid morning snapshot.',
    'include_milestone_refresh': 'True to refresh review milestone mapping; false to reuse morning mapping. Separate summary job currently has additional refresh behavior.',
}


def words(name):
    return name.replace('_', ' ').replace('jira', 'JIRA').replace('ffdc', 'FFDC').replace('pcie', 'PCIe').replace('uefi', 'UEFI').replace('pldm', 'PLDM')


def description(fn):
    if fn['name'] in DESCRIPTIONS:
        return DESCRIPTIONS[fn['name']]
    if fn['doc']:
        return fn['doc']
    name = fn['name'].split('.')[-1]
    verbs = {'parse': 'Parse', 'render': 'Render', 'build': 'Build', 'collect': 'Collect', 'extract': 'Extract', 'normalize': 'Normalize', 'load': 'Load', 'save': 'Save', 'get': 'Retrieve', 'set': 'Update', 'start': 'Start', 'run': 'Run', 'clean': 'Normalize', 'cleanup': 'Clean up', 'is': 'Test', 'has': 'Test whether there is', 'find': 'Locate', 'read': 'Read', 'write': 'Write', 'fetch': 'Fetch', 'generate': 'Generate', 'filter': 'Filter', 'select': 'Select', 'format': 'Format', 'sort': 'Sort', 'check': 'Check', 'decode': 'Decode', 'interpret': 'Interpret', 'compact': 'Compact', 'enrich': 'Enrich', 'classify': 'Classify', 'validate': 'Validate', 'merge': 'Merge', 'reuse': 'Reuse'}
    first, _, rest = name.partition('_')
    sentence = (verbs.get(first, words(first).capitalize()) + ' ' + words(rest)).strip() + '.'
    local = [call for call in fn['calls'] if call.split('.')[-1] in KNOWN]
    if local:
        sentence += ' Delegates to ' + ', '.join('`' + c + '`' for c in local[:5]) + '.'
    keys = fn['dict_keys'][:8]
    if keys:
        sentence += ' Literal result/intermediate fields include ' + ', '.join('`' + k + '`' for k in keys) + '.'
    return sentence + ' (Intent inferred from the complete function AST; see return/effect details.)'


KNOWN = {f['name'].split('.')[-1] for module in DATA['modules'].values() for f in module['functions']}


def api_entries(module_name, functions):
    out = []
    for fn in functions:
        out.append(f"### `{fn['name']}`\n\nSource: {ref(module_name, fn['line'], fn['end'])}.\n\n{description(fn)}\n\n")
        out.append(table(['Parameter', 'Type / inference', 'Default', 'Meaning'], [(a['name'], a['type'], code(a['default']), PARAMS.get(a['name'], f"{words(a['name']).capitalize()}; operation-specific input consumed by this function. No stricter schema is declared.")) for a in fn['args']] or [('None', '—', '—', 'No arguments.')]))
        out.append('Returns: ' + (f"declared `{fn['return_annotation']}`.\n\n" if fn['return_annotation'] else 'not annotated; the following return paths are statically observed. Variable/delegated-call types are intentionally not guessed.\n\n'))
        seen = set()
        rows = []
        for ret in fn['returns']:
            signature = (ret['type'], ret['expression'])
            if signature in seen:
                continue
            seen.add(signature)
            rows.append((ret['line'], ret['type'], code(ret['expression'])))
        out.append(table(['Line', 'Observed type', 'Returned value / expression'], rows or [('—', 'None or generator', 'No explicit return; inspect yields and side effects. Constructor methods initialize the instance.')]))
        if fn['raises']:
            out.append('Raises directly: ' + '; '.join('`' + r['expression'].replace('`', '') + '` (line ' + str(r['line']) + ')' for r in fn['raises']) + '. Delegated exceptions may also propagate.\n\n')
        if fn['globals']:
            out.append('Global declarations: ' + ', '.join('`' + v + '`' for v in fn['globals']) + '.\n\n')
        if fn['effects']:
            out.append(table(['Line', 'Direct filesystem/network/process/synchronization call'], [(e['line'], code(e['expression'])) for e in fn['effects']]))
        elif any(call.split('.')[-1] in KNOWN for call in fn['calls']):
            out.append('Side effects: no indexed direct effect call; delegated functions may still read/write state or perform I/O.\n\n')
    return ''.join(out)


def route_rows():
    rows, seen = [], set()
    handler = next(n for n in TREES['app.py'].body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
    for method in handler.body:
        if not isinstance(method, ast.FunctionDef) or method.name not in {'do_GET', 'do_POST'}:
            continue
        for node in ast.walk(method):
            if not isinstance(node, ast.If):
                continue
            condition = ast.unparse(node.test)
            if '.path' not in condition:
                continue
            paths = sorted({n.value for n in ast.walk(node.test) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/')})
            nodes = [n for body in node.body for n in ast.walk(body)]
            calls = sorted({ast.unparse(n.func) for n in nodes if isinstance(n, ast.Call) and (isinstance(n.func, ast.Name) and n.func.id in KNOWN or isinstance(n.func, ast.Attribute) and n.func.attr in {'send_json', 'send_html', 'send_response', 'read_form', 'read_json_body'})})
            inputs = sorted({n.args[0].value for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'get' and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and (isinstance(n.func.value, ast.Name) and n.func.value.id in {'query', 'payload', 'fields', 'form'} or 'parse_qs(' in ast.unparse(n.func.value))})
            for route in paths:
                key = (method.name, route)
                if key in seen:
                    continue
                seen.add(key)
                behavior = ', '.join(calls)
                if route == '/upload':
                    behavior = 'Legacy multipart upload; analyze_with_capacity; redirect 303 to report. The router rejects all other unmatched POST paths.'
                route_inputs = ', '.join(inputs) or 'None observed in query/form/JSON; inspect route body'
                if route == '/api/workspace-report': route_inputs = 'id'
                if route in {'/upload', '/workspace-upload-start'}: route_inputs = 'multipart field ffdc; Content-Length'
                if route == '/static/': route_inputs = 'path prefix /static/<filename>'
                rows.append((method.name[3:], route, route_inputs, behavior, ref('app.py', node.lineno)))
    return rows


def main():
    imports = collections.defaultdict(set)
    for name in CORE:
        for item in DATA['modules'][name]['imports']:
            if item['module'].split('.')[0] in sys.stdlib_module_names or item['module'] == 'cgi':
                imports[item['module']].add(name)
    append_at('Requirements.md', '<!-- GENERATED STANDARD LIBRARY -->', '## Complete Runtime Standard-Library Import Index\n\n' + table(['Module', 'Purpose', 'Imported by'], [(m, STD.get(m, 'Standard-library support; see import sites.'), ', '.join(sorted(files))) for m, files in sorted(imports.items())]))

    entry_rows = []
    for name, tree in TREES.items():
        role = 'current service' if name == 'app.py' else 'test suite' if name.startswith('test_') else 'historical copy; do not deploy' if name.startswith('app.py.') else 'support/diagnostic script'
        guards = [n.lineno for n in tree.body if isinstance(n, ast.If) and '__name__' in ast.unparse(n.test)]
        effects = [n for n in tree.body if isinstance(n, (ast.Expr, ast.Try, ast.For, ast.With)) and not isinstance(getattr(n, 'value', None), ast.Constant)]
        if guards or effects and name not in CORE:
            entry_rows.append((name, role, 'main guard at ' + ', '.join(map(str, guards)) if guards else 'Top-level statements execute on import/run', ref(name, guards[0] if guards else effects[0].lineno)))
    append_at('LogicPlan.md', '<!-- GENERATED ENTRY POINTS -->', '## Complete Root Python Entrypoint Index\n\n' + table(['File', 'Role', 'Entry mechanism', 'Source'], entry_rows) + 'No `.bat` or shell launch script exists at the project root in this snapshot. The deployment unit is external, not a checked-in executable entrypoint.\n\nSee Specification for persistence destinations and AuditInventory for every root file and ancillary artifact.\n')

    spec = ['## Complete HTTP Route Index\n\nThis index is derived from all path-condition branches in `Handler`. Method and path matching are case-sensitive. Most POST branches compare the full `self.path`, so appending query parameters is not generally equivalent to the same path without a query; `/clear-reports` is handled differently.\n\n']
    spec.append(table(['Method', 'Path', 'Input keys observed', 'Delegated handlers / response operations', 'Source'], route_rows()))
    spec.append('## Complete Environment Variable Index\n\nDefaults are code expressions, not values read from an administrator\'s deployed secret files. Most variables are read on module import; file loader variables are read at call time.\n\n')
    env = DATA['modules']['app.py']['environment']
    spec.append(table(['Configuration key', 'Type', 'Code default / precedence', 'Purpose', 'Source'], [(v['name'].strip("'\""), 'environment string; parsed by caller', code(v['default']), ENV_HELP.get(v['name'].strip("'\""), 'See source.'), ref('app.py', v['line'])) for v in sorted(env, key=lambda v: (v['name'], v['line']))]))
    spec.append('## Module Constants and Shared State\n\nThe full assignment index includes configuration, regular expressions, protocol tables and mutable job state. Long default expressions are summarized instead of reproducing HTML/prompts verbatim. These constants have no stable external configuration schema unless exposed through an environment variable or file loader.\n\n')
    for name in CORE:
        rows = []
        for node in TREES[name].body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = ast.unparse(node.value)
            if len(value) > 300:
                value = value[:200] + f' ... [expression length {len(value)}; full definition at source]'
            names = ', '.join(ast.unparse(n) for n in targets)
            rows.append((names, type(node.value).__name__ + ' expression', code(value), words(names.lower()) + '; module-level state/definition, not necessarily user-configurable.', ref(name, node.lineno)))
        spec.append(f'### `{name}` assignments\n\n' + table(['Name', 'Type representation', 'Default / initializer', 'Purpose', 'Source'], rows))
    spec.append('## Class Instance Attributes\n\nOnly directly assigned `self` attributes are enumerated. Inherited HTTP handler fields (`path`, `headers`, `rfile`, `wfile`, `client_address`, `server`) originate in `BaseHTTPRequestHandler`. Inherited `EvidenceTools` attributes remain available to `WorkspaceEvidenceTools`.\n\n')
    for name in CORE:
        for cls in DATA['modules'][name]['classes']:
            spec.append(f"### `{cls['name']}`\n\nSource: {ref(name, cls['line'], cls['end'])}; bases: " + ', '.join(cls['bases']) + '.\n\n')
            spec.append(table(['Attribute', 'Inferred type', 'Assignment / meaning', 'Source'], [(key, val['type'], code(val['value']), ref(name, val['line'])) for key, val in cls['attributes'].items()] or [('None directly assigned', '—', 'Uses inherited state or is a marker exception.', ref(name, cls['line']))]))
    spec.append('## Full Runtime Python Callable Reference\n\nThe current runtime modules include the HTTP entrypoint, evidence/UI modules, bounded configuration helpers, and job persistence primitives. This catalogue includes private helpers/constructors as well as public functions. Signatures have no inferred enforcement; descriptions marked inferred use full-body structure and observed delegates. Return expressions are abbreviated for readability, with complete implementations linked by line.\n\n')
    spec.append(table(['Module', 'Functions and methods', 'Source SHA-256'], [(name, len(DATA['modules'][name]['functions']), next(r['sha256'] for r in DATA['inventory'] if r['path'] == name)) for name in CORE]))
    for name in CORE:
        spec.append(f'## `{name}` Callable Details\n\n')
        spec.append(api_entries(name, DATA['modules'][name]['functions']))
    append_at('Specification.md', '<!-- GENERATED REFERENCE -->', ''.join(spec))

    audit = ['## Detailed Static Findings\n\nThe following lists are exhaustive for the stated metric over the six current runtime modules, not proof that every entry is a defect.\n\n']
    audit.append('### Deep Nesting\n\n' + table(['Source', 'Depth', 'AST control'], [(ref(name, n['line']), n['depth'], n['kind']) for name in CORE for n in DATA['modules'][name]['nesting']]))
    audit.append('### Top-Level Blank-Line Candidates\n\n' + table(['Source', 'Observed blank lines before definition'], [(ref(name, row['line']), row['blank_lines']) for name in CORE for row in DATA['modules'][name]['top_level_definition_spacing']]))
    audit.append('### Numeric Literal Index\n\nEvery nontrivial numeric literal (excluding -1, 0, 1 and 2) is listed with all line occurrences. Protocol encodings/register masks, HTML dimensions and legitimate budgets are included. No placeholder status is inferred from numeric presence alone.\n\n')
    for name in CORE:
        audit.append(f'#### `{name}`\n\n' + table(['Literal', 'Source lines'], [(v, ', '.join(map(str, lines))) for v, lines in sorted(DATA['modules'][name]['numeric_literals'].items())]))
    names_used = set()
    for name in CORE:
        for n in ast.walk(TREES[name]):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load): names_used.add(n.id)
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load): names_used.add(n.attr)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r'[A-Za-z_]\w*', n.value): names_used.add(n.value)
    candidates = [(ref(name, fn['line']), fn['name'], 'No direct load/attribute/schema-name reference in six current runtime modules; external calls/HTTP dispatch may still use it.') for name in CORE for fn in DATA['modules'][name]['functions'] if fn['name'].split('.')[-1] not in names_used and not fn['name'].split('.')[-1].startswith('__')]
    audit.append('### Potential Uncalled Functions\n\nHTTP `do_GET`/`do_POST` and parser callbacks are framework dispatch, not dead code. This list is a review queue only.\n\n' + table(['Source', 'Callable', 'Qualification'], candidates))
    audit.append('### Import-Time State\n\n' + table(['Source', 'Statement type', 'Initializer / action'], [(ref(name, e['line']), e['kind'], code(e['expression'])) for name in CORE for e in DATA['modules'][name]['module_effects'] if e['kind'] != 'Expr']))
    audit.append('### All Root Python print Calls\n\nCurrent service startup prints are logging. Test/debug/probe scripts print their diagnostic output by design. Historical backup prints are not current production logging.\n\n' + table(['Source', 'Role', 'Expression'], [(ref(name, e['line']), 'startup log' if name == 'app.py' else 'test / historical / diagnostic output', code(e['expression'])) for name in sorted(DATA['modules']) for e in DATA['modules'][name]['print_calls']]))
    audit.append('### Exact Normalized Function-Body Duplicates\n\n' + table(['File', 'Function names and lines'], [(name, ', '.join(f"{f['name']}:{f['line']}" for f in group)) for name in DATA['modules'] for group in DATA['modules'][name]['identical_function_bodies']] or [('No exact AST-body duplicate found', 'Similarity across non-identical implementations still exists.')]))
    append_at('Maintenance.md', '<!-- GENERATED AUDIT FINDINGS -->', ''.join(audit))

    inventory = ['# FFDC Analyzer: Source and Artifact Inventory\n\nBaseline generated by `docs/_tools/audit_project.py`. Full bytes were read for every regular file in the stated scope; no error was reported. Binary contents are not treated as source and are not reproduced. `docs/` is an explicitly excluded generated output, and Git internals are not part of application semantics.\n\n']
    records = [r for r in DATA['inventory'] if 'sha256' in r]
    inventory.append(table(['Metric', 'Value'], [('Regular files read', len(records)), ('Bytes read', sum(r['bytes'] for r in records)), ('Root Python/current/historical modules fully parsed', len(DATA['modules'])), ('Current runtime callables', sum(len(DATA['modules'][n]['functions']) for n in CORE)), ('Read/parse errors', len(DATA['errors'])), ('Machine-readable manifest', '_audit/structure.json'), ('Test evidence', '_audit/validation.json')]))
    inventory.append('## Root Entries\n\nDirectory entries include hidden files. `docs/` existed as the new generator workspace before the baseline scan; README was added after the initial inventory.\n\n' + table(['Entry', 'Classification'], [(p, next((r.get('kind', '') for r in DATA['inventory'] if r['path'] == p), 'generated audit workspace')) for p in DATA['root_entries']]))
    inventory.append('## File Responsibilities and Relationships\n\n' + table(['Group', 'Responsibility / relationship'], [('app.py', 'Product entrypoint; imports companion Python modules and emits classic HTML; references static assets.'), ('ffdc_chat.py', 'Shared evidence tools and model orchestration; inherited by workspace_analysis.'), ('workspace_analysis.py', 'Focused evidence and verification; calls base EvidenceTools.'), ('workspace_ui.py', 'HTML shell; references workspace JavaScript/CSS, Marked, Lucide and logo.'), ('ffdc_config.py', 'Bounded environment parsing and path/URL normalization.'), ('ffdc_jobs.py', 'Atomic background-job snapshots, restart recovery and in-memory expiry cleanup.'), ('static/', 'First-party workspace assets plus separately licensed Marked/Lucide bundles.'), ('test_*.py', 'Runtime mocked unit tests; legacy monitor tests import app.py.jira_monitor.'), ('app.py.*', 'Historical copies; not active imports except the explicit legacy test loader.'), ('compare_*, inspect_*, extract_*, summarize_*, map_*, deep_compare_*, focused_*', 'One-off case investigation scripts; often hardcoded external log paths; not called by app main.'), ('patch_*', 'Historical source-rewrite utilities; importing/executing can modify external app files.'), ('v4_batch_validate.py / vision_capability_test.py', 'Manual validation/probe scripts; may call filesystem/network services.'), ('nginx-ffdc-analyzer.conf', 'FFDC proxy template for port 8088.'), ('00-installer-config.yaml', 'Host installation/network configuration, not read by the analyzer.'), ('knowledgebase_patch/ and nginx-knowledgebase.conf', 'Separate Knowledge Base service artifacts; not FFDC runtime.'), ('reports/, uploads/, ffdc_cache/, jira_monitor_jobs/', 'Runtime/generated data; do not treat case contents as code or embed them in documentation.'), ('work/, outputs/, ppt_work/, ppt_repair/, deliverables/', 'Development, diagnostic, presentation/video artifacts; not required for server startup.'), ('__pycache__/', 'Generated Python bytecode, not source.')]))
    inventory.append('## Complete Root Python Import Edges\n\n' + table(['File', 'Imported module', 'Line', 'Unused-name candidate'], [(name, imp['module'], imp['line'], ', '.join(imp['unused_candidates']) or 'none') for name in sorted(DATA['modules']) for imp in DATA['modules'][name]['imports']]))
    inventory.append('## Exact Duplicate Files\n\n' + table(['Group', 'Paths'], [(i, '<br>'.join(g)) for i, g in enumerate(DATA['duplicate_files'], 1)]))
    inventory.append('## Supporting Python Function Index\n\nThe current public API is in Specification. These auxiliary/test callables are not product HTTP APIs. Historical application copies are represented by their full AST audit, hashes and import edges rather than duplicated as competing current API specifications.\n\n')
    for name in DATA['modules']:
        if name in CORE or name.startswith('app.py.'):
            continue
        fns = DATA['modules'][name]['functions']
        inventory.append(f'### `{name}`\n\n' + table(['Function / method', 'Parameters', 'Role inferred / docstring', 'Source'], [(f['name'], ', '.join(a['name'] for a in f['args']), description(f), ref(name, f['line'], f['end'])) for f in fns] or [('No declared function', '—', 'Top-level diagnostic/patch script; do not import to discover its behavior.', ref(name, 1))]))
    inventory.append('## Complete File Manifest\n\nSHA-256 fingerprints are recorded for reproducibility, not to authenticate a release. Runtime raw data names are inventoried but contents are not published.\n\n' + table(['Path', 'Role', 'Bytes', 'Encoding', 'Lines', 'SHA-256'], [(r['path'], r['kind'], r['bytes'], r['encoding'], r['lines'] if r['lines'] is not None else 'binary', r['sha256']) for r in records]))
    (DOCS / 'AuditInventory.md').write_text(''.join(inventory), encoding='utf-8')
    print(json.dumps({'routes': len(route_rows()), 'functions': sum(len(DATA['modules'][n]['functions']) for n in CORE), 'markdown_files': [p.name for p in DOCS.glob('*.md')]}, indent=2))


if __name__ == '__main__':
    main()
