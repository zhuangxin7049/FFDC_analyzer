"""Guarded deployment for workspace-themed child pages."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

stage = Path(__file__).resolve().parent
base = Path('/home/zhuangxin2/ffdc_analyzer')
assert stage == base / 'deploy-workspace-subpages-20260909'

expected = {
    'app.py': 'fbd848786504a5cf19051595711198dc2ed0c69f9d07eb79a1721976358e3b4e',
    'workspace_ui.py': '2c1fb6ba6e1f8c5e6768b189750f01d1406925b7bc37208149a2385dcae4bf62',
    'static/workspace.js': '9dc50672cc294d05a71e54d1228f3c289bc5068dbee93250bb4abe08fead677f',
}
runtime_files = [
    'app.py', 'workspace_ui.py', 'static/workspace.js',
    'static/workspace-subpage.css', 'static/workspace-subpage.js',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(route):
    with urllib.request.urlopen('http://127.0.0.1:8088' + route, timeout=30) as response:
        return response.status, response.headers.get_content_type(), response.read()


def guard():
    for name, sha in expected.items():
        assert digest(base / name) == sha, 'Production changed: ' + name
    for folder in ('jira_monitor_jobs', 'current_status_summary'):
        for path in (base / folder).glob('*.json'):
            if path.stat().st_mtime < time.time() - 86400:
                continue
            job = json.loads(path.read_text())
            assert job.get('status') not in {'running', 'queued'}, 'Active background job: ' + path.name
    usage = fetch('/usage-stats')[2].decode('utf-8', errors='replace')
    match = re.search(r'Active analyses</span><strong>(\d+)/', usage)
    assert match and int(match.group(1)) == 0, 'Active FFDC analysis, or capacity unavailable'


guard()
subprocess.run([sys.executable, '-m', 'py_compile', str(stage / 'app.py'), str(stage / 'workspace_ui.py')], check=True)
backup = base / 'backups' / ('workspace-subpages-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, exist_ok=False)
manifest = {}
for name in runtime_files:
    target = base / name
    manifest[name] = digest(target) if target.exists() else None
    if target.exists():
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
(backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('BACKUP ' + str(backup), flush=True)

try:
    guard()
    for name in runtime_files:
        target = base / name
        temporary = target.with_name(target.name + '.subpage-next')
        shutil.copy2(stage / name, temporary)
        os.replace(temporary, target)
    subprocess.run(['systemctl', 'restart', 'ffdc-analyzer.service'], check=True)
    for attempt in range(15):
        try:
            fetch('/new-version')
            break
        except Exception:
            time.sleep(1)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'ffdc-analyzer.service'], check=True)

    for route, marker in (
        ('/Defect_review', b'Scheduled Defect Review'),
        ('/reports', b'<h2>Reports</h2>'),
    ):
        status, _, body = fetch(route)
        assert status == 200 and marker in body
        assert b'workspace-subpage-shell' not in body, 'Classic page was themed: ' + route
    for route, active in (
        ('/Defect_review?view=workspace', b'Defect Review'),
        ('/reports?view=workspace', b'Reports'),
        ('/usage-stats?view=workspace', b'Usage'),
        ('/Current_bug_status_summary?view=workspace', b'Milestones'),
    ):
        status, _, body = fetch(route)
        assert status == 200 and b'workspace-subpage-shell' in body and active in body
        print('HTTP 200 themed ' + route, flush=True)
    report_paths = sorted((base / 'reports').glob('*/report.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    if report_paths:
        report_id = report_paths[0].parent.name
        status, _, body = fetch('/report?id=' + report_id + '&view=workspace')
        assert status == 200 and b'workspace-subpage-shell' in body and b'FFDC Analysis Report' in body
        print('HTTP 200 themed /report', flush=True)
    for name in runtime_files:
        assert digest(base / name) == digest(stage / name), 'Installed file mismatch: ' + name
    for name, expected_type in (
        ('workspace-subpage.css', 'text/css'), ('workspace-subpage.js', 'text/javascript'),
    ):
        status, content_type, body = fetch('/static/' + name)
        assert status == 200 and content_type == expected_type
        assert body == (stage / 'static' / name).read_bytes()
    print('DEPLOYED workspace themed subpages; classic pages unchanged', flush=True)
except Exception:
    for name, sha in manifest.items():
        target = base / name
        if sha is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copy2(backup / name, target)
    subprocess.run(['systemctl', 'restart', 'ffdc-analyzer.service'], check=True)
    print('ROLLED BACK to ' + str(backup), flush=True)
    raise
