"""Verify documentation completeness, source fingerprints and local references."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'


def main():
    data = json.loads((DOCS / '_audit/structure.json').read_text(encoding='utf-8'))
    failures = []
    names = ('app.py', 'ffdc_chat.py', 'workspace_analysis.py', 'workspace_ui.py', 'ffdc_config.py', 'ffdc_jobs.py')
    core_unchanged = {}
    for name in names:
        old = next(r['sha256'] for r in data['inventory'] if r['path'] == name)
        core_unchanged[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == old
        if not core_unchanged[name]: failures.append('Source changed: ' + name)
    spec = (DOCS / 'Specification.md').read_text(encoding='utf-8')
    for name in names:
        for fn in data['modules'][name]['functions']:
            marker = f"### `{fn['name']}`\n\nSource: [{name}:{fn['line']}"
            if marker not in spec: failures.append('Missing callable: ' + name + ':' + fn['name'])
    diagrams = 0
    for path in [ROOT / 'README.md', *sorted(DOCS.glob('*.md'))]:
        text = path.read_text(encoding='utf-8')
        if len(re.findall(r'^```', text, re.M)) % 2:
            failures.append('Unbalanced fence: ' + path.name)
        diagrams += len(re.findall(r'^```mermaid$', text, re.M))
        prose = re.sub(r'(`+).*?\1', '', text, flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)', prose):
            if target.startswith(('http:', 'https:', '#')): continue
            file, _, anchor = target.partition('#')
            candidate = path.parent / file
            if not candidate.exists(): failures.append('Missing target: ' + str(path.name) + ' -> ' + target)
            if candidate.is_file() and re.fullmatch(r'L\d+', anchor):
                lines = len(candidate.read_text(encoding='utf-8').splitlines())
                if int(anchor[1:]) > lines: failures.append('Invalid source line: ' + target)
        table_width = None
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.startswith('|'):
                table_width = None
                continue
            width = len(re.split(r'(?<!\\)\|', line))
            if table_width is None: table_width = width
            if width != table_width: failures.append(f'Table column mismatch: {path.name}:{line_no}')
        if re.search(r'sk-[A-Za-z0-9_-]{20,}', text): failures.append('Possible unredacted API key: ' + path.name)
    if diagrams < 3: failures.append('Fewer than three Mermaid diagrams')
    report = {'runtime_sources_unchanged': core_unchanged, 'callables_checked': sum(len(data['modules'][n]['functions']) for n in names), 'mermaid_blocks': diagrams, 'checks': 'Markdown fence balance, table column counts, local file links, source line ranges, function coverage, runtime source hashes, API-key pattern check. Mermaid blocks are source-checked, not renderer-certified.', 'failures': sorted(set(failures))}
    (DOCS / '_audit/documentation_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
