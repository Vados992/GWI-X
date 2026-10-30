"""Regenerate static charts from already exported, audited CSV files."""
import csv
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gwix.charts import charts
from gwix.config import NAMES


def read(path):
    with Path(path).open(encoding="utf-8",newline="") as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        for k,v in r.items():
            try: r[k]=int(v) if k=="year" else float(v)
            except ValueError: pass
    return rows


if __name__=="__main__":
    root=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/"results")
    results={n:SimpleNamespace(annual=read(root/n/"annual.csv")) for n in NAMES}
    charts(root/"charts",results,read(root/"comparisons.csv"))
