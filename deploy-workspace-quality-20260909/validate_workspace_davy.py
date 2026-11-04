"""Validate the staged workspace against Davy with synthetic evidence only."""
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

# Respect the deployed service's model configuration without printing credentials.
environment = subprocess.check_output(['systemctl', 'show', 'ffdc-analyzer.service', '-p', 'Environment', '--value'], text=True)
allowed = {'FFDC_CHAT_MODEL', 'FFDC_WORKSPACE_CHAT_MODEL', 'FFDC_OPENAI_BASE_URL', 'FFDC_OPENAI_MODEL', 'FFDC_API_KEY_FILE'}
for assignment in shlex.split(environment):
    name, separator, value = assignment.partition('=')
    if separator and name in allowed:
        os.environ[name] = value
import app

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    (root / 'network.log').write_text('2026-09-01 10:00:00 NIC eth0 link down\n2026-09-01 10:00:04 NIC eth0 link up 25Gbps\n2026-09-01 10:02:00 NIC eth0 link up rx_errors=0 tx_errors=0\n')
    (root / 'inventory.log').write_text('RAID controller model: 940-8i\nBay 4: no drive installed\nBackplane firmware version: 3\n')
    context = {'created_at': '2026-09-01 10:03:00', 'source_file': 'synthetic-only',
               'system': {'model': 'not supplied'}, 'storage': {'controller': '940-8i', 'bay4': 'empty', 'psoc': '3'},
               'raw_logs_available': True}
    for question in ('这个FFDC中的网卡当前故障了吗？请核实原始日志并用中文简短回答。',
                     '请读取inventory.log，这能证明是940型号服务器、盘4坏了、背板从v2升级到v3了吗？'):
        trace = {}
        answer, model = app.call_evidence_chat(context, question, root=root, auto_triage=True, workspace=True, trace=trace)
        assert answer.strip()
        assert any(row.get('kind') == 'log' for row in trace['sources']), 'No original logs were read'
        print(json.dumps({'question': question, 'model': model, 'answer': answer,
                          'citation_check': trace.get('citation_check'), 'tool_calls': trace['tool_calls'],
                          'seconds': trace['elapsed_seconds']}, ensure_ascii=False), flush=True)
