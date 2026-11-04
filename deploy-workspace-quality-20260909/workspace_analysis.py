"""Focused, inspectable evidence preparation for the conversation workspace."""
import json
import re
import time

from ffdc_chat import (
    EvidenceTools, TRIAGE_COMPONENTS, TRIAGE_FAILURE, bounded_context, function, redact,
)

FOCUS_WORDS = {
    'network': r'网卡|网络|丢包|以太|\b(?:nic|ethernet|network|netdev|mlx\w*|bnxt\w*|link down|carrier)\b',
    'storage': r'背板|磁盘|硬盘|盘符|\b(?:raid|hba|drive|disk|nvme|backplane|psoc|ubm)\b',
    'firmware': r'固件|刷写|升级|\b(?:firmware|flash|pldm|mctp|bmu|in.?band)\b',
    'pcie': r'通道|链路宽|\b(?:pcie|aer|link width|link speed)\b',
    'system': r'内存|电源|温度|\b(?:dimm|memory|cpu|thermal|power|watchdog|panic)\b',
}
BENIGN = re.compile(r'\b(?:no errors?|0 errors?|errors?\s*[:=]\s*0\b|failures?\s*[:=]\s*0\b|error handling|error injection|supported error)\b', re.I)
URGENT = re.compile(r'\b(?:fatal|uncorrectable|panic|critical|failed|timeout|unsupported|not detected)\b', re.I)
INSTRUCTIONS = """You are investigating the currently selected FFDC, not writing a generic report.
Answer the latest question directly. For broad findings: a 1-2 sentence conclusion, at most 5 ranked findings with short evidence/meaning/next-check bullets, then the most useful unresolved question. For focused follow-ups answer only the requested point; do not repeat the entire investigation or unrelated JIRA boilerplate.
Use the user's requested language, including headings. Preserve exact device identifiers and original quoted log text. Never infer a server model from a controller model (for example RAID 940 is not a ThinkSystem server model).
Keep three evidence levels distinct: original log observations (cite `path:line`), parser/automatic-check observations (cite `report:section`), and hypotheses. A keyword match, a missing inventory field, or an automatic warning alone is not proof of a fault or root cause. No match in a limited scan is not proof the machine is healthy.
Check surrounding lines and timestamps, recovery/retry outcomes, slot/device scope, and collection time. Historical errors that recovered are not current failures. Do not conflate empty/unpopulated drive bays with failed disks, or independent controller-local slot numbers with a proven backplane conflict. Never claim an upgrade or version transition from a single firmware snapshot.
Scope health conclusions to the latest supplied record, not the live machine. Say "the latest supplied log shows recovery; it does not establish the current physical state" instead of "the NIC is not faulty" or "the system is healthy". A zero error counter alone does not exclude intermittent faults.
For a Bug investigation use its title, description, recent engineer comments, and available FFDC. Describe explicitly which assertions are from JIRA vs logs. If comments conflict with logs or the root cause is unconfirmed, state the conflict and the concrete next check. If no Bug is linked, simply analyze the FFDC; do not add an empty JIRA section.
Do not fabricate an engineer, timestamp, register interpretation, citation, affected model, or solution. Use original evidence tools for missing details. Prepared excerpts are real source lines already read; search and read more only when needed. Use read_report_section to inspect fields omitted from the compact snapshot. For project questions use the milestone tool and include its snapshot date.
In next checks, use only filenames actually returned by the tools or supplied context. Do not invent likely filenames such as system.log or fw_update.log. If no relevant filename has been identified, name the evidence category needed (for example firmware update history) without pretending a specific file exists.
Use concise paragraphs and numbered findings. No wide tables for narrative diagnostic findings. Avoid repeated severity/category columns and long hardware inventories. Do not expose internal reasoning or tool markup.
"""


def focus_for(question):
    return [name for name, pattern in FOCUS_WORDS.items() if re.search(pattern, str(question), re.I)]


class WorkspaceEvidenceTools(EvidenceTools):
    def __init__(self, *args, sections=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sections = sections or {}
        self.sources = []
        self.source_keys = set()
        self.scan = None
        self.started = time.monotonic()
        self.cached_results = {}

    def schemas(self):
        schemas = super().schemas()
        if self.sections:
            schemas.append(function('read_report_section', 'Read a parsed report section. For lists, use offset to inspect additional records. Parsed checks are not verified root causes.',
                                    {'section': {'type': 'string', 'enum': sorted(self.sections)},
                                     'offset': {'type': 'integer', 'minimum': 0}}, ['section']))
        return schemas

    def add_source(self, source):
        key = json.dumps(source, sort_keys=True)
        if key not in self.source_keys and len(self.sources) < 32:
            self.source_keys.add(key)
            self.sources.append(source)

    def read_report_section(self, section, offset=0):
        if section not in self.sections:
            raise ValueError('Unknown parsed report section.')
        value = self.sections[section]
        offset = max(0, int(offset))
        total = len(value) if isinstance(value, list) else None
        page = value[offset:offset + 20] if total is not None else value
        self.add_source({'kind': 'report', 'section': section, 'label': 'report:' + section,
                         'description': 'Parsed report data; automated findings still require interpretation.'})
        return {'section': section, 'data': bounded_context({section: page})[section],
                'offset': offset, 'total': total, 'next_offset': offset + 20 if total is not None and offset + 20 < total else None}

    def read_log(self, path, start, count=60):
        result = super().read_log(path, start, count)
        if result['lines']:
            self.add_source({'kind': 'log', 'path': path, 'start': result['lines'][0]['line'], 'end': result['lines'][-1]['line']})
        return result

    def get_jira_issue(self, key):
        result = super().get_jira_issue(key)
        issue = result.get('issue') or {}
        self.add_source({'kind': 'jira', 'label': issue.get('key', key), 'url': issue.get('url', ''), 'description': 'Live JIRA title, description, status and recent comments.'})
        return result

    def search_project_milestones(self, **kwargs):
        result = super().search_project_milestones(**kwargs)
        self.add_source({'kind': 'projects', 'label': 'Project milestone snapshot', 'url': '/Current_bug_status_summary',
                         'description': 'Project milestone snapshot queried for this answer.'})
        return result

    def execute(self, name, args):
        cache_key = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if cache_key in self.cached_results:
            return self.cached_results[cache_key]
        result = super().execute(name, args)
        if not result.get('error'):
            self.cached_results[cache_key] = result
        return result

    def triage_ffdc(self, focus='all'):
        """Distribute a bounded scan across files and keep diverse, contextual leads."""
        if not self.root or not self.root.is_dir():
            raise ValueError('Raw FFDC files are unavailable for this report.')
        if focus != 'all' and focus not in TRIAGE_COMPONENTS:
            raise ValueError('Unknown focus.')
        categories = list(TRIAGE_COMPONENTS) if focus == 'all' else [focus]
        matches = {category: [] for category in categories}
        seen = set()
        self.unreadable_paths = 0
        paths = list(self.paths())
        # Small event logs come before large inventories; every file receives its own byte budget.
        paths.sort(key=lambda path: (not any(word in path.name.lower() for word in ('event', 'dmesg', 'pldm', 'mctp', 'network', 'tty')), path.stat().st_size, str(path)))
        consumed, scanned, unreadable = 0, 0, self.unreadable_paths
        limited = len(paths) > 240
        for path in paths[:240]:
            scanned += 1
            file_bytes = 0
            try:
                for number, line, size in self.lines(path):
                    consumed += size; file_bytes += size
                    if consumed > 12 * 1024 * 1024 or file_bytes > 512 * 1024:
                        limited = True
                        break
                    if not TRIAGE_FAILURE.search(line) or (BENIGN.search(line) and not URGENT.search(line)) or redact(line) != line:
                        continue
                    identity = re.sub(r'^.*?\b(\d\d:\d\d:\d\d(?:\.\d+)?)\s*', '', line)
                    for category in categories:
                        duplicate = (category, identity)
                        if duplicate in seen or not TRIAGE_COMPONENTS[category].search(line):
                            continue
                        seen.add(duplicate)
                        matches[category].append({'path': str(path.relative_to(self.root)), 'line': number, 'text': line[:500],
                                                  'text_truncated': len(line) > 500, '_rank': int(bool(URGENT.search(line)))})
                        matches[category] = sorted(matches[category], key=lambda row: -row['_rank'])[:4]
            except OSError:
                unreadable += 1
            if consumed > 12 * 1024 * 1024:
                break
        for rows in matches.values():
            for row in rows:
                row.pop('_rank', None)
        result = {'focus': focus, 'findings': {key: rows for key, rows in matches.items() if rows},
                  'files_scanned': scanned, 'bytes_scanned': consumed, 'limited': limited, 'unreadable_files': unreadable,
                  'note': 'Candidates only. Inspect the surrounding source lines and recovery before concluding.'}
        self.scan = {key: result[key] for key in ('files_scanned', 'bytes_scanned', 'limited', 'unreadable_files')}
        return result

    def prepare(self, question):
        if not self.root or not self.root.is_dir():
            return {'available': False, 'note': 'No original FFDC text logs are available; use parsed report/JIRA evidence only.'}
        focuses = focus_for(question)
        triage = self.execute('triage_ffdc', {'focus': focuses[0] if len(focuses) == 1 else 'all'})
        if triage.get('error'):
            return triage
        candidates = triage.get('findings', {})
        excerpts, seen = [], set()
        for category, rows in candidates.items():
            for row in rows[:2]:
                key = (row['path'], row['line'])
                if key in seen or len(excerpts) >= 8:
                    continue
                seen.add(key)
                excerpt = self.execute('read_log', {'path': row['path'], 'start': max(1, row['line'] - 3), 'count': 11})
                if not excerpt.get('error'):
                    excerpts.append({'category': category, **excerpt})
        return {'available': True, 'scan': self.scan, 'excerpts': excerpts,
                'note': 'These surrounding log lines were read before answering. They may show recovery, normal empty slots, or old events.'}

    def unsupported_citations(self, answer):
        unsupported = []
        for match in re.finditer(r'`([^`\s]+):(\d+)(?:[-–](\d+))?`', answer):
            path, number, end = match.groups()
            if not any(row['kind'] == 'log' and row['path'] == path and row['start'] <= int(number) <= int(end or number) <= row['end'] for row in self.sources):
                unsupported.append(match.group(0)[1:-1])
        return unsupported

    def metadata(self):
        return {'sources': self.sources, 'scan': self.scan, 'tool_calls': len(self.audit),
                'elapsed_seconds': round(time.monotonic() - self.started, 1)}
