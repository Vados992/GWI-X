"""Record tests, independent CSV audit and full-run numeric reproducibility."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from audit_csv import audit


def verify(reproduced,output=None):
    reproduced=Path(reproduced).resolve()
    out=Path(output) if output else ROOT/"verification"
    out.mkdir(parents=True,exist_ok=True)
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (out/"tests.txt").write_text(stream.getvalue(),encoding="utf-8",newline="\n")
    if not result.wasSuccessful(): raise AssertionError(stream.getvalue())
    csv_audit=audit(ROOT/"results")
    numeric=[]
    for p in sorted((ROOT/"results").rglob("*")):
        if not p.is_file() or not (p.suffix==".csv" or p.name=="resolved_config.json"): continue
        relative=p.relative_to(ROOT/"results")
        other=reproduced/relative
        if not other.is_file() or p.read_bytes()!=other.read_bytes(): raise AssertionError(f"Reproduction mismatch: {relative}")
        numeric.append(dict(path=relative.as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    receipt=dict(status="PASS",python=platform.python_version(),data_status="SYNTHETIC",tests=dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)),csv_audit=csv_audit,reproducibility=dict(status="BYTE_IDENTICAL",matched_files=len(numeric),command="python -S -m gwix all --config configs/synthetic.json --out <empty-folder>",scope="Every exported CSV and every resolved scenario configuration; optional PNG and environment manifests excluded",files=numeric))
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8",newline="\n")
    (out/"csv_audit.json").write_text(json.dumps(csv_audit,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:v for k,v in receipt.items() if k!="reproducibility"},indent=2))
    print(f"Reproduction: {len(numeric)} files byte-identical")


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("reproduced_results"); parser.add_argument("--out")
    args=parser.parse_args(); verify(args.reproduced_results,args.out)
