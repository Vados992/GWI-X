"""Portable offline official-snapshot replay, independent audit, blocked-run proof."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gwix.official.validation import validate_snapshot
from gwix.official.store import write_json
from audit_official import audit
from check_reproduction import compare


def verify(out):
    snapshot = ROOT/'data/official/PT/2026-10-30-final'
    out = Path(out)
    summary = validate_snapshot(snapshot, out)
    assert summary['accounting_status'] == 'PASS' and summary['source_status'] == 'COMPLETE'
    independent = audit(snapshot, out)
    match = compare(ROOT/'real-data/PT/2026-10-30-final', out, exact=False)
    blocked = subprocess.run([sys.executable, '-S', '-m', 'gwix.official', 'run-policy'], cwd=ROOT,
                             capture_output=True, text=True, check=False)
    if blocked.returncode != 2 or json.loads(blocked.stdout)['full_real_data_policy_run'] != 'BLOCKED':
        raise AssertionError('Unfunded/unvalidated national policy run was not blocked')
    result = dict(status='OFFICIAL_PIPELINE_PASS_POLICY_RUN_BLOCKED', audit=independent,
                  saved_csv_replay=match, blocked_policy_exit_code=blocked.returncode)
    write_json(out/'verification.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); a = p.parse_args()
    print(json.dumps(verify(a.out), indent=2))
