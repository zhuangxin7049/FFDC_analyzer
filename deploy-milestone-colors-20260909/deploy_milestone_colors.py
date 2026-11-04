"""Guarded deployment for the workspace Milestones risk colours."""
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
assert stage == base / 'deploy-milestone-colors-20260909'

expected = {
    'workspace_ui.py': '22d45463eaad3a08177483b039bc22deb073cf058262ce6d4096fef722b3d43f',
    'static/workspace-subpage.css': '8d61268580844c2760b4e06ab3944caa0ba94b8cc78a31c54f2d5f9bae1fcd1a',
}
runtime_files = tuple(expected)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(route):
    with urllib.request.urlopen('http://127.0.0.1:8088' + route, timeout=20) as response:
        return response.status, response.headers.get_content_type(), response.read()


def guard():
    for name, sha in expected.items():
        assert digest(base / name) == sha, 'Production changed: ' + name
    usage = fetch('/usage-stats')[2].decode('utf-8', errors='replace')
    match = re.search(r'Active analyses</span><strong>(\d+)/', usage)
    assert match and int(match.group(1)) == 0, 'Active FFDC analysis, or capacity unavailable'


guard()
subprocess.run([sys.executable, '-m', 'py_compile', str(stage / 'workspace_ui.py')], check=True)
backup = base / 'backups' / ('milestone-colors-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, exist_ok=False)
manifest = {}
for name in runtime_files:
    target = base / name
    manifest[name] = digest(target)
    saved = backup / name
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, saved)
(backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('BACKUP ' + str(backup), flush=True)

try:
    guard()
    for name in runtime_files:
        target = base / name
        temporary = target.with_name(target.name + '.milestone-colours-next')
        shutil.copy2(stage / name, temporary)
        os.replace(temporary, target)
    subprocess.run(['systemctl', 'restart', 'ffdc-analyzer.service'], check=True)
    for _ in range(15):
        try:
            fetch('/new-version')
            break
        except Exception:
            time.sleep(1)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'ffdc-analyzer.service'], check=True)
    status, _, page = fetch('/Current_bug_status_summary?view=workspace')
    assert status == 200 and b'workspace-subpage-shell' in page
    assert b'workspace-subpage.css?v=20260909-quality3' in page
    assert b'milestone-countdown' in page
    status, content_type, css = fetch('/static/workspace-subpage.css')
    assert status == 200 and content_type == 'text/css'
    assert b'.milestone-countdown.critical{background:#f00;color:#fff}' in css
    assert b'.milestone-countdown.warning{background:#ff0;color:#1b2430}' in css
    print('DEPLOYED Milestones critical/warning colours', flush=True)
except Exception:
    for name in runtime_files:
        shutil.copy2(backup / name, base / name)
    subprocess.run(['systemctl', 'restart', 'ffdc-analyzer.service'], check=True)
    print('ROLLED BACK to ' + str(backup), flush=True)
    raise
