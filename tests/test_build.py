import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_windows", ROOT / "scripts" / "build_windows.py")
build_windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_windows)


class BuildScriptTests(unittest.TestCase):
    def test_unittest_counts_parse_actual_result_line(self):
        counts = build_windows.unittest_counts("ok\n\nRan 17 tests in 0.123s\n\nOK\n")
        self.assertEqual(counts, {"ran": 17, "failures": 0, "errors": 0})

    def test_zip_exact_root_contract(self):
        with tempfile.TemporaryDirectory(prefix="hshw-zip-test-") as tmp:
            path = Path(tmp) / "artifact.zip"
            with zipfile.ZipFile(path, "w") as zf:
                for name in ["Start.exe", "Stop.exe", "README-KO.txt", "VERSION"]:
                    zf.writestr(name, "")
            with zipfile.ZipFile(path) as zf:
                self.assertEqual(sorted(zf.namelist()), ["README-KO.txt", "Start.exe", "Stop.exe", "VERSION"])

    def test_pyinstaller_command_includes_src_path_and_static_assets(self):
        text = (ROOT / "scripts" / "build_windows.py").read_text(encoding="utf-8")
        self.assertIn('"--paths"', text)
        self.assertIn("session_hub/static", text)
        self.assertIn("INSTALL-KO.md", text)
        start_wrapper = (ROOT / "packaging" / "start.py").read_text(encoding="utf-8")
        self.assertIn("sys.exit(main())", start_wrapper)


if __name__ == "__main__":
    unittest.main()
