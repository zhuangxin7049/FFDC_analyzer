"""Run existing tests in disposable project copies and retain the results."""
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / '_audit'


def main():
    results = []
    for names in [('test_ffdc_chat', 'test_workspace_quality', 'test_workspace_ui', 'test_ffdc_jobs', 'test_ffdc_config'), ('test_jira_monitor_workflow',)]:
        with tempfile.TemporaryDirectory(prefix='ffdc-docgen-tests-') as directory:
            target = Path(directory)
            for file in ROOT.iterdir():
                if file.is_file() and (file.suffix == '.py' or file.name.startswith('app.py.')):
                    shutil.copy2(file, target / file.name)
            shutil.copytree(ROOT / 'static', target / 'static')
            run = subprocess.run([sys.executable, '-m', 'unittest', *names], cwd=target, capture_output=True, text=True, timeout=120)
            results.append({'modules': names, 'exit_code': run.returncode, 'output': run.stdout + run.stderr})
    versions = {}
    for name in ('app.py', 'ffdc_chat.py', 'workspace_analysis.py', 'workspace_ui.py'):
        source = (ROOT / name).read_text(encoding='utf-8')
        versions[name] = {}
        for minor in (8, 9, 10, 11, 12, 13, 14):
            try:
                ast.parse(source, feature_version=(3, minor))
                versions[name][f'3.{minor}'] = 'syntax accepted; runtime API compatibility is a separate check'
            except SyntaxError as exc:
                versions[name][f'3.{minor}'] = str(exc)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'validation.json').write_text(json.dumps({'runtime': sys.version, 'isolation': 'Each suite used a disposable directory, no real configuration or credentials copied.', 'tests': results, 'syntax': versions}, indent=2), encoding='utf-8')
    for result in results:
        print(', '.join(result['modules']), 'exit', result['exit_code'])
        print(result['output'][-200:])


if __name__ == '__main__':
    main()
