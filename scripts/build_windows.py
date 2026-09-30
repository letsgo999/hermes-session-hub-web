import argparse
import hashlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
import re

PRODUCT_VERSION = "0.1.0-preview.2"
ZIP_NAME = f"Hermes-Session-Hub-Web-v{PRODUCT_VERSION}-win-x64.zip"


def run(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def unittest_counts(output):
    match = re.search(r"Ran (\d+) tests? in", output)
    failures = len(re.findall(r"\nFAIL:", output))
    errors = len(re.findall(r"\nERROR:", output))
    return {
        "ran": int(match.group(1)) if match else 0,
        "failures": failures,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    build_root = Path(args.build_root).resolve()
    output_root = Path(args.output_root).resolve()
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    output_root.mkdir(parents=True, exist_ok=True)

    test_output = "skipped"
    if not args.skip_tests:
        test = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo)
        test_output = test.stderr + test.stdout
    counts = unittest_counts(test_output)

    pyinstaller = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--paths", str(repo / "src"),
        "--distpath", str(build_root / "dist"),
        "--workpath", str(build_root / "work"),
        "--specpath", str(build_root / "spec"),
        "--add-data", f"{repo / 'src' / 'session_hub' / 'static'};session_hub/static",
    ]
    run(pyinstaller + ["--name", "Start", str(repo / "packaging" / "start.py")], repo)
    run(pyinstaller + ["--name", "Stop", str(repo / "packaging" / "stop.py")], repo)

    stage = build_root / "stage"
    stage.mkdir()
    shutil.copy2(build_root / "dist" / "Start.exe", stage / "Start.exe")
    shutil.copy2(build_root / "dist" / "Stop.exe", stage / "Stop.exe")
    shutil.copy2(repo / "INSTALL-KO.md", stage / "README-KO.txt")
    (stage / "VERSION").write_text(PRODUCT_VERSION + "\n", encoding="utf-8")

    zip_path = output_root / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(stage.iterdir()):
            zf.write(item, item.name)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (output_root / f"{ZIP_NAME}.sha256").write_text(f"{digest}  {ZIP_NAME}\n", encoding="ascii")
    (output_root / "INSTALL-KO.md").write_text((repo / "INSTALL-KO.md").read_text(encoding="utf-8"), encoding="utf-8")
    (output_root / "BUILD-TEST-RECEIPT.md").write_text(
        "# Build Test Receipt\n\n"
        f"- product: Hermes Session Hub Web\n"
        f"- version: {PRODUCT_VERSION}\n"
        f"- created_at_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"- unittest: {'skipped' if args.skip_tests else 'executed'}\n"
        f"- unittest_ran: {counts['ran']}\n"
        f"- unittest_failures: {counts['failures']}\n"
        f"- unittest_errors: {counts['errors']}\n"
        f"- zip: {ZIP_NAME}\n"
        f"- zip_root: exact files Start.exe, Stop.exe, README-KO.txt, VERSION\n"
        f"- sha256: {digest}\n\n"
        "No PII, source database rows, credentials, cookies, or local profile paths are recorded here.\n\n"
        "```text\n" + test_output[-4000:] + "\n```\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
