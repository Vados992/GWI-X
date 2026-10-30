"""Full offline model check used identically on Windows and Linux runners."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from audit_csv import audit
from check_reproduction import compare


def command(*args):
    subprocess.run([sys.executable,"-S",*map(str,args)],cwd=ROOT,check=True)


def main(out=None):
    out=Path(out) if out else ROOT/"results-local/ci"
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    for name,digest in manifest["files"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest: raise AssertionError("snapshot hash mismatch: "+name)
    command("-m","unittest","discover","-s","tests","-v")
    command("scripts/verify_official.py", "--out", out/"official")
    for name in ("first","second"):
        command("-m","gwix","all","--config",ROOT/"configs/synthetic.json","--out",out/name)
    receipt=dict(status="PASS",runtime=sys.version,first_audit=audit(out/"first"),second_audit=audit(out/"second"),same_runtime=compare(out/"first",out/"second"),published_snapshot=compare(ROOT/"results",out/"first",exact=False))
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--out"); args=parser.parse_args()
    main(args.out)
