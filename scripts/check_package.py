"""Verify ZIP paths/hashes, extract to a fresh folder and run the real tests."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import re


def check(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError("fresh extraction folder required")
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise AssertionError("ZIP CRC failure")
        names=z.namelist()
        for name in names:
            if not (destination/name).resolve().is_relative_to(destination): raise ValueError("unsafe archive path")
        z.extractall(destination)
    root=destination/"GWI-X-v1.2"
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    for name,digest in manifest["files"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest: raise AssertionError("Hash mismatch: "+name)
    test=subprocess.run([sys.executable,"-S","-m","unittest","discover","-s","tests","-v"],cwd=root,capture_output=True,text=True,encoding="utf-8")
    (destination/"tests.txt").write_text(test.stdout+test.stderr,encoding="utf-8")
    if test.returncode: raise AssertionError(test.stderr)
    # Real CLI call from an extracted project, no packages or preinstalled code.
    cfg=json.loads((root/"configs/synthetic.json").read_text(encoding="utf-8"))
    cfg["households"]=120
    small=destination/"smoke-config.json"; small.write_text(json.dumps(cfg),encoding="utf-8")
    for name,expected in (("reform",0),("zero_funding",2)):
        output=destination/name
        p=subprocess.run([sys.executable,"-S","-m","gwix","run","--config",str(small),"--scenario",name,"--out",str(output)],cwd=root,capture_output=True,text=True)
        if p.returncode!=expected: raise AssertionError((name,p.returncode,p.stdout,p.stderr))
    match=re.search(r"Ran (\d+) tests",test.stderr+test.stdout)
    receipt=dict(status="PASS",archive_entries=len(names),manifest_files_checked=len(manifest["files"]),tests=f"{match.group(1) if match else 'all'} passed with python -S from clean extraction",cli_exit_codes=dict(reform=0,zero_funding=2),pdf_byte_reproduction="Not checked by this script; see the authoring verification receipt",no_network_or_install_for_model=True)
    (destination/"package_check.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("archive"); p.add_argument("destination"); a=p.parse_args(); check(a.archive,a.destination)
