"""Guarded deployment of the new workspace; does not touch report data or config."""
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
assert stage == base / 'deploy-workspace-quality-20260909'
expected = {
    'app.py': '82d6bf11e0751b17fee85939803bae17c8607c707e88f6b336ffe0fbc9b9351b',
    'ffdc_chat.py': '5e96c3baa1bc093de0cf27c645c47c945740942742868852bf2fb88a22029bef',
    'workspace_ui.py': '3554d8b3913ae90b39825cda9dc71795eb99055a543fb87a7e20246179d00ba8',
}
names = ['ffdc_chat.py', 'workspace_analysis.py', 'workspace_ui.py',
         'static/workspace.css', 'static/workspace.js', 'static/workspace-marked.js',
         'static/workspace-lucide.js', 'static/workspace-marked-LICENSE.txt',
         'static/workspace-lucide-LICENSE.txt', 'app.py']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fetch(route):
    with urllib.request.urlopen('http://127.0.0.1:8088' + route, timeout=30) as response:
        assert response.status == 200, route
        return response.headers.get_content_type(), response.read()

def guard():
    for name, sha in expected.items():
        assert digest(base / name) == sha, 'Production changed: ' + name
    for folder in ('jira_monitor_jobs', 'current_status_summary'):
        for path in (base / folder).glob('*.json'):
            if path.stat().st_mtime < time.time() - 86400:
                continue
            job = json.loads(path.read_text())
            assert job.get('status') not in {'running', 'queued'}, 'Active background job: ' + path.name
    usage = fetch('/usage-stats')[1].decode()
    match = re.search(r'Active analyses</span><strong>(\d+)/', usage)
    assert match and int(match.group(1)) == 0, 'Active FFDC parsing, or capacity unavailable'
    sockets = subprocess.check_output(['ss', '-Htn', 'state', 'established', '( sport = :8088 )'], text=True)
    assert not sockets.strip(), 'Active HTTP request; wait for it to finish before deployment'

guard()
subprocess.run([sys.executable, '-m', 'unittest', 'test_workspace_ui.py', 'test_ffdc_chat.py', 'test_workspace_quality.py'], cwd=stage, check=True)
subprocess.run([sys.executable, '-m', 'py_compile', *[str(stage / name) for name in names if name.endswith('.py')]], check=True)
classic_before = fetch('/')[1]
backup = base / 'backups' / ('workspace-quality-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, exist_ok=False)
manifest = {}
for name in names:
    target = base / name
    manifest[name] = digest(target) if target.exists() else None
    if target.exists():
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
(backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('BACKUP ' + str(backup), flush=True)
guard()
try:
    for name in names:
        target = base / name
        temporary = target.with_name(target.name + '.quality-next')
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
    assert fetch('/')[1] == classic_before, 'Classic homepage changed unexpectedly'
    for route in ('/', '/new-version', '/Defect_review', '/reports', '/Current_bug_status_summary'):
        fetch(route)
        print('HTTP 200 ' + route, flush=True)
    for name in names:
        assert digest(base / name) == digest(stage / name), 'Installed file mismatch: ' + name
        if name.startswith('static/'):
            content_type, body = fetch('/' + name)
            assert body == (stage / name).read_bytes(), 'HTTP asset mismatch: ' + name
            if name.endswith('.css'):
                assert content_type == 'text/css'
            if name.endswith('.js'):
                assert content_type in {'text/javascript', 'application/javascript'}
    print('DEPLOYED workspace-quality-20260909; classic homepage unchanged', flush=True)
except Exception:
    for name, sha in manifest.items():
        if sha is None:
            (base / name).unlink(missing_ok=True)
        else:
            shutil.copy2(backup / name, base / name)
    subprocess.run(['systemctl', 'restart', 'ffdc-analyzer.service'], check=True)
    print('ROLLED BACK to ' + str(backup), flush=True)
    raise
