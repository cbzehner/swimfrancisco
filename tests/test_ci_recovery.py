"""Exercise the workflow's real timeout shell, without source/network calls."""
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_detection_timeout_writes_evidence_and_fails_normally(tmp_path):
    if not shutil.which('timeout') or 'GNU coreutils' not in subprocess.check_output(['timeout', '--version'], text=True):
        pytest.skip('The workflow timeout test requires GNU coreutils (available in the project sandbox).')
    workflow = Path('.github/workflows/schedules-extract.yml').read_text()
    detect = workflow.split('\n  detect:', 1)[1].split('\n  extract:', 1)[0]
    script = textwrap.dedent(detect.split('        run: |\n', 1)[1].split('      - uses:', 1)[0])
    script = script.replace('10m uv', '0.1s uv')
    tools = tmp_path / 'bin'
    tools.mkdir()
    uv = tools / 'uv'
    uv.write_text('#!/bin/sh\nsleep 5\n')
    uv.chmod(0o755)
    result = subprocess.run(['bash', '-e', '-c', script], cwd=tmp_path, timeout=3,
                            env=os.environ | {'PATH': f'{tools}:{os.environ["PATH"]}',
                                              'GITHUB_OUTPUT': str(tmp_path / 'outputs')},
                            text=True, capture_output=True)
    assert result.returncode == 1
    import json
    assert json.loads((tmp_path / 'tmp/source-changes.json').read_text()) == {
        'changed': True, 'failure_code': 'detection_timeout'}
    assert not (tmp_path / 'outputs').exists()
