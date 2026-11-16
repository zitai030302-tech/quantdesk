"""Install the uploaded Skill's companion wheel offline and test in a fresh venv."""
import argparse
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import venv
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_zip", type=Path)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("tests", type=Path)
    args = parser.parse_args()
    skill_zip, wheel, tests = (p.resolve(strict=True) for p in (args.skill_zip, args.wheel, args.tests))
    with tempfile.TemporaryDirectory(prefix="quantdesk accept ") as temporary:
        root = Path(temporary)
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(root)
        python = root / "Scripts" / "python.exe" if sys.platform == "win32" else root / "bin" / "python"
        detached = root / "detached script.py"
        with zipfile.ZipFile(skill_zip) as package:
            detached.write_bytes(package.read("scripts/quantdesk.py"))
        failure = subprocess.run([str(python), "-I", str(detached), "doctor"], cwd=root, capture_output=True)
        if failure.returncode != 2 or b'"installed_version": null' not in failure.stderr:
            raise RuntimeError("doctor did not detect missing wheel in the fresh environment")
        print("Uninstalled doctor check: PASS", flush=True)
        subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "install",
                        "--no-index", "--no-deps", str(wheel)], cwd=root, check=True)
        subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "check"], cwd=root, check=True)
        subprocess.run([str(python), "-I", str(detached), "doctor"], cwd=root, check=True)
        print(platform.platform(), flush=True)
        subprocess.run([str(python), "-I", str(tests), str(skill_zip)], cwd=root, check=True)


if __name__ == "__main__":
    main()
