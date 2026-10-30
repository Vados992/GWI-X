"""Compare numerical exports exactly on one runtime or by tolerance across OS."""
import argparse
import csv
import json
import math
from pathlib import Path


def value_equal(a,b):
    if a==b: return True
    if ";" in a or ";" in b:
        aa,bb=a.split(";"),b.split(";")
        return len(aa)==len(bb) and all(value_equal(x,y) for x,y in zip(aa,bb))
    try: x,y=float(a),float(b)
    except ValueError: return False
    return math.isfinite(x) and math.isfinite(y) and math.isclose(x,y,rel_tol=1e-12,abs_tol=1e-8)


def compare(reference,candidate,exact=True):
    reference,candidate=Path(reference),Path(candidate)
    selected=lambda root: {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and (p.suffix==".csv" or p.name=="resolved_config.json")}
    files=selected(reference)
    if files!=selected(candidate): raise AssertionError("exported file sets differ")
    for name in sorted(files):
        a,b=reference/name,candidate/name
        if exact:
            if a.read_bytes()!=b.read_bytes(): raise AssertionError("byte mismatch: "+name)
        elif a.suffix==".json":
            if json.loads(a.read_text(encoding="utf-8"))!=json.loads(b.read_text(encoding="utf-8")): raise AssertionError("configuration differs: "+name)
        else:
            with a.open(encoding="utf-8",newline="") as fa,b.open(encoding="utf-8",newline="") as fb:
                aa,bb=list(csv.reader(fa)),list(csv.reader(fb))
            if len(aa)!=len(bb): raise AssertionError("row count differs: "+name)
            for row,(x,y) in enumerate(zip(aa,bb)):
                def equal(col,v,w):
                    if row and aa[0][col].endswith("_residual"):
                        try: return all(math.isfinite(float(z)) and abs(float(z))<=1e-4 for z in (v,w))
                        except ValueError: return False
                    return value_equal(v,w)
                if len(x)!=len(y) or not all(equal(col,v,w) for col,(v,w) in enumerate(zip(x,y))):
                    raise AssertionError(f"value differs: {name}, row {row+1}")
    return dict(status="BYTE_IDENTICAL" if exact else "NUMERIC_MATCH",matched_files=len(files),relative_tolerance=0 if exact else 1e-12,absolute_tolerance=0 if exact else 1e-8,residual_bound=0 if exact else 1e-4)


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("reference"); p.add_argument("candidate"); p.add_argument("--numeric",action="store_true"); p.add_argument("--receipt")
    a=p.parse_args(); result=compare(a.reference,a.candidate,not a.numeric)
    if a.receipt: Path(a.receipt).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(result,indent=2))
