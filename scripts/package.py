"""Build a deterministic archive, excluding Python caches and local reruns."""
import argparse
import hashlib
from pathlib import Path
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1]
PACKAGE_ROOT="GWI-X-v1.2"
sys.path.insert(0,str(ROOT))
from gwix.export import manifest


def package(root,destination):
    root=Path(root).resolve(); destination=Path(destination).resolve()
    if destination.is_relative_to(root): raise ValueError("archive must be outside project")
    manifest(root)
    with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or {"__pycache__","results-local",".venv",".git","releases","private-data"}.intersection(p.relative_to(root).parts) or p.suffix==".pyc": continue
            info=zipfile.ZipInfo(PACKAGE_ROOT+"/"+p.relative_to(root).as_posix(),(2026,10,29,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes(),compresslevel=9)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix+".sha256").write_text(digest+"  "+destination.name+"\n",encoding="ascii",newline="\n")
    print(f"{destination.name}: {destination.stat().st_size} bytes; SHA256 {digest}")


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("destination"); args=p.parse_args()
    package(ROOT,args.destination)
