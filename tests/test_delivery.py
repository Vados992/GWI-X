"""Release regressions which matter when cloning on another OS or folder name."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from gwix.export import json_write, manifest
from gwix.households import Person, Household, summarize

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from check_reproduction import compare


class DeliveryTests(unittest.TestCase):
    def test_national_aggregation_keeps_small_money_terms(self):
        # Independent exact decimal sum: builtin float sum in Python 3.11
        # loses two units here, while the weighted national total must keep them.
        from decimal import Decimal
        hs=[Household(str(i),"single",(Person(str(i),1,1,True),),0,1) for i in range(3)]
        keys=("gross","income_tax","employee_sc","employer_sc","business_sc","clearing","topup","benefits","pension","disability","child","assistance","disposable","real_disposable","employer_cost")
        rows=[{k:0.0 for k in keys} for _ in hs]
        for row,value in zip(rows,(1e16,1.0,1.0)): row["gross"]=value
        exact=Decimal("10000000000000000")+Decimal(1)+Decimal(1)
        self.assertEqual(summarize(hs,rows)["gross"],float(exact))

    def test_residual_comparison_preserves_the_invariant_limit(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/"a",Path(d)/"b"; a.mkdir(); b.mkdir()
            (a/"annual.csv").write_text("year,cash_residual\n2027,0\n")
            (b/"annual.csv").write_text("year,cash_residual\n2027,0.00001\n")
            self.assertEqual(compare(a,b,False)["status"],"NUMERIC_MATCH")
            (b/"annual.csv").write_text("year,cash_residual\n2027,0.001\n")
            with self.assertRaises(AssertionError): compare(a,b,False)

    def test_json_uses_canonical_lf(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json"; json_write(p,{"label":"SYNTHETIC","values":[1,2]})
            self.assertNotIn(b"\r",p.read_bytes())
            self.assertEqual(json.loads(p.read_text()),{"label":"SYNTHETIC","values":[1,2]})

    def test_manifest_excludes_local_state_and_release_recursion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/"source.py").write_text("pass\n")
            for folder in (".git",".venv","results-local","releases"):
                p=root/folder; p.mkdir(); (p/"local.txt").write_text("not part of the source manifest")
            manifest(root)
            files=json.loads((root/"manifest.json").read_text())["files"]
            self.assertEqual(set(files),{"source.py"})

    def test_archive_root_does_not_depend_on_clone_folder(self):
        spec=importlib.util.spec_from_file_location("delivery_package",ROOT/"scripts/package.py")
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"arbitrary-clone-name"; root.mkdir(); (root/"README.md").write_text("SYNTHETIC")
            (root/"releases").mkdir(); (root/"releases/old.zip").write_bytes(b"not recursively embedded")
            target=Path(d)/"delivery.zip"; module.package(root,target)
            with zipfile.ZipFile(target) as z:
                self.assertTrue(all(n.startswith("GWI-X-v1.2/") for n in z.namelist()))
                self.assertFalse(any("releases/" in n for n in z.namelist()))
                self.assertEqual(z.read("GWI-X-v1.2/README.md"),b"SYNTHETIC")

    def test_numeric_comparison_tolerates_only_tiny_float_roundoff(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/"a",Path(d)/"b"; a.mkdir(); b.mkdir()
            (a/"annual.csv").write_text("year,value,emtr_adults\n2027,100000000000,0.1;NA\n")
            (b/"annual.csv").write_text("year,value,emtr_adults\n2027,100000000000.00001,0.10000000000000002;NA\n")
            self.assertEqual(compare(a,b,False)["status"],"NUMERIC_MATCH")
            with self.assertRaises(AssertionError): compare(a,b,True)
            (b/"annual.csv").write_text("year,value,emtr_adults\n2027,110000000000,0.1;NA\n")
            with self.assertRaises(AssertionError): compare(a,b,False)


if __name__=="__main__": unittest.main()
