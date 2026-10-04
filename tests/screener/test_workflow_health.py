"""Execute the workflow's health check with controlled collector outcomes."""
import os
from pathlib import Path
import subprocess
import textwrap

import pytest


def health_script():
    workflow=Path(__file__).parents[2]/'.github/workflows/dashboard.yml'
    lines=workflow.read_text().splitlines()
    start=next((i for i,line in enumerate(lines) if line.strip()=='- name: Report collection health'),None)
    assert start is not None, 'Workflow must report collector failures after publishing usable output'
    run=next(i for i in range(start,len(lines)) if lines[i].strip()=='run: |')
    end=next((i for i in range(run+1,len(lines)) if lines[i] and not lines[i].startswith('          ')),len(lines))
    return textwrap.dedent('\n'.join(lines[run+1:end]))


@pytest.mark.parametrize('failed',['','SNAPSHOT_OUTCOME','BREAKOUT_OUTCOME','RESEARCH_OUTCOME','ENTRY_OUTCOME'])
def test_workflow_health_exit_reflects_each_collector_outcome(tmp_path,failed):
    outcomes={name:'success' for name in ('SNAPSHOT_OUTCOME','BREAKOUT_OUTCOME','RESEARCH_OUTCOME','ENTRY_OUTCOME')}
    if failed:
        outcomes[failed]='failure'
    summary=tmp_path/'summary.md'
    result=subprocess.run(['bash','-e','-c',health_script()],env=dict(os.environ,**outcomes,GITHUB_STEP_SUMMARY=str(summary)),
        text=True,capture_output=True)
    assert result.returncode==(1 if failed else 0)
    assert 'Research' in summary.read_text()
    if failed:
        assert 'failure' in summary.read_text()
