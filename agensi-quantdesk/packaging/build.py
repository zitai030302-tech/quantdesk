"""Build the portable offline runtime wheel and a deterministic Agensi upload ZIP."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import yaml

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
PACKAGE = "quantdesk_agensi_runtime"
VERSION = "0.1.0"
CORE = (
    "app/types.py",
    "backtest/broker.py", "backtest/engine.py", "backtest/metrics.py", "backtest/report.py",
    "data/csv_loader.py", "data/models.py", "data/repositories.py", "data/sqlite.py",
    "execution/adapter_base.py", "execution/paper_broker.py", "execution/validators.py",
    "risk/manager.py", "risk/protect_mode.py", "risk/rules.py", "risk/sizing.py",
    "strategies/base.py", "strategies/ema_trend.py", "strategies/indicators.py",
    "strategies/registry.py", "strategies/rsi_bbands_mean_reversion.py",
)
SKILL = (
    "SKILL.md", "README.md", "scripts/quantdesk.py", "references/contract.md",
    "references/methodology.md", "templates/research-request.json", "templates/paper-request.json",
    "examples/btc_synthetic_1h.csv",
)
FROZEN_TIME = (1980, 1, 1, 0, 0, 0)


def wheel(dest: Path):
    with tempfile.TemporaryDirectory(prefix="quantdesk-wheel-") as temporary:
        root = Path(temporary)
        target = root / PACKAGE
        source = [(path.relative_to(HERE).as_posix(), path.read_bytes()) for path in sorted((HERE / "runtime").glob("*.py"))]
        source.extend((path, (ROOT / path).read_bytes()) for path in CORE)
        source.append(("examples/btc_synthetic_1h.csv", (HERE / "examples/btc_synthetic_1h.csv").read_bytes()))
        identity = hashlib.sha256()
        for relative, data in source:
            identity.update(relative.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
            if relative.startswith("runtime/"):
                module = target / Path(relative).name
            elif relative.startswith("examples/"):
                module = target / Path(relative).name
            else:
                module = target / "core" / relative
                code = data.decode()
                code = re.sub(r"^(\s*from )(app|backtest|data|execution|risk|strategies)(?=[. ])",
                              rf"\g<1>{PACKAGE}.core.\g<2>", code, flags=re.MULTILINE)
                data = code.encode()
                module.parent.mkdir(parents=True, exist_ok=True)
                module.parent.joinpath("__init__.py").touch()
            module.parent.mkdir(parents=True, exist_ok=True)
            module.write_bytes(data)
        target.joinpath("core", "__init__.py").touch()
        target.joinpath("source.sha256").write_text(identity.hexdigest() + "\n", encoding="ascii")
        shutil.copyfile(ROOT / "LICENSE", root / "LICENSE")
        root.joinpath("pyproject.toml").write_text(f"""
[build-system]
requires = ["setuptools==80.9.0", "wheel==0.45.1"]
build-backend = "setuptools.build_meta"

[project]
name = "quantdesk-agensi-runtime"
version = "{VERSION}"
description = "Offline QuantDesk backtesting and paper risk checks"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICENSE"]

[tool.setuptools.package-data]
{PACKAGE} = ["*.csv", "*.sha256"]
""", encoding="utf-8")
        command = [sys.executable, "-c", "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])", str(dest)]
        subprocess.run(command, cwd=root, env={**os.environ, "SOURCE_DATE_EPOCH": "315532800"}, check=True)


def archive(dest: Path):
    entries = {name: (HERE / name).read_bytes() for name in SKILL}
    entries["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    opening, delimiter, front, ending, _ = entries["SKILL.md"].decode().split("\n", 4)
    if (opening, ending) != ("---", "---"):
        raise ValueError("SKILL.md must begin with two-field YAML frontmatter")
    manifest = yaml.safe_load(delimiter + "\n" + front)
    if set(manifest) != {"name", "description"} or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["name"]):
        raise ValueError("invalid Skill frontmatter")
    if len(manifest["name"]) > 60 or not isinstance(manifest["description"], str) or not manifest["description"].strip():
        raise ValueError("invalid Skill name or description")
    if len(entries) > 201 or sum(len(data.decode()) for data in entries.values()) > 6_000_000:
        raise ValueError("Skill text delivery limit exceeded")
    path = dest / f"quantdesk-agensi-skill-v{VERSION}.zip"
    with zipfile.ZipFile(path, "w") as package:
        for name, data in sorted(entries.items()):
            if name.endswith(".py") and len(data) >= 20_000:
                raise ValueError(f"Script exceeds 20 KB: {name}")
            info = zipfile.ZipInfo(name, FROZEN_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            package.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    if path.stat().st_size >= 50_000_000:
        raise ValueError("Agensi website upload limit exceeded")
    with zipfile.ZipFile(path) as package:
        if package.testzip() or set(package.namelist()) != set(entries):
            raise ValueError("ZIP integrity or file list mismatch")
    print(f"{path.name}: {len(entries)} files, {path.stat().st_size} bytes")


def main():
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    wheel(destination)
    archive(destination)


if __name__ == "__main__":
    main()
