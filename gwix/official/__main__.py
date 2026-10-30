"""CLI separating live acquisition, frozen replay and blocked policy execution."""
import argparse
import json
from pathlib import Path
import sys

from .catalog import load_profile
from .microdata import audit_microdata
from .store import fetch_snapshot, read_snapshot, write_json
from .validation import readiness, validate_snapshot

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = ROOT/'data/official/PT/2026-10-30-final'


def main(argv=None):
    parser = argparse.ArgumentParser(description='GWI-X official Portugal observations; no synthetic fallback')
    subs = parser.add_subparsers(dest='command', required=True)
    fetch = subs.add_parser('fetch', help='Live public APIs, new immutable snapshot')
    fetch.add_argument('--profile', type=Path, default=ROOT/'configs/official_portugal.json')
    fetch.add_argument('--out', type=Path, required=True)
    check = subs.add_parser('validate', help='Offline historical diagnostic from a frozen snapshot')
    check.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    check.add_argument('--out', type=Path, required=True)
    policy = subs.add_parser('run-policy', help='Fail closed when a real national policy run lacks prerequisites')
    policy.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    micro = subs.add_parser('micro-audit', help='Local canonical licensed extract audit; no microdata publication')
    micro.add_argument('--input', type=Path, required=True)
    micro.add_argument('--metadata', type=Path, required=True)
    micro.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            receipts = fetch_snapshot(load_profile(args.profile), args.out)
            ok = all(r['status'] == 'OK' for r in receipts)
            print(json.dumps(dict(status='COMPLETE' if ok else 'PARTIAL_SOURCE_FAILURE',
                                  successful=sum(r['status'] == 'OK' for r in receipts), requests=len(receipts)), indent=2))
            return 0 if ok else 2
        if args.command == 'validate':
            summary = validate_snapshot(args.snapshot, args.out)
            print(json.dumps(summary, indent=2))
            return 0 if summary['accounting_status'] == 'PASS' and summary['source_status'] == 'COMPLETE' else 2
        if args.command == 'run-policy':
            profile, receipts, _, _ = read_snapshot(args.snapshot)
            print(json.dumps(readiness(profile, receipts), ensure_ascii=False, indent=2))
            return 2
        if args.command == 'micro-audit':
            if args.out.exists():
                raise FileExistsError('Audit output already exists')
            result = audit_microdata(args.input, args.metadata)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, result)
            print('Canonical accounting audit completed; household identifiers were not exported. Policy run remains blocked.')
            return 0
    except (ValueError, OSError, KeyError, ArithmeticError) as exc:
        print(json.dumps(dict(status='ERROR_NO_FALLBACK', error=type(exc).__name__+': '+str(exc))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
