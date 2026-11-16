"""Inspect the final distribution archives for unsafe members and runtime imports."""
import ast
from pathlib import Path, PurePosixPath
import stat
import sys
from zipfile import ZipFile

NETWORK_MODULES = {"socket", "ssl", "urllib", "http", "httpx", "requests", "aiohttp",
                   "websocket", "websockets", "ftplib"}
PROCESS_MODULES = {"subprocess", "dotenv"}


def inspect_code(source: str, name: str):
    for node in ast.walk(ast.parse(source, filename=name)):
        if isinstance(node, ast.Import):
            modules = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = {node.module.split(".")[0]}
        else:
            modules = set()
        if modules & (NETWORK_MODULES | PROCESS_MODULES):
            raise ValueError(f"network/process/config import in {name}")
        if isinstance(node, ast.Call):
            callable_name = ast.unparse(node.func)
            if callable_name in {"eval", "exec", "os.system", "subprocess.Popen"}:
                raise ValueError(f"arbitrary code or process execution in {name}")
            if callable_name == "__import__" and (
                len(node.args) != 1 or node.keywords or
                not isinstance(node.args[0], ast.Constant) or node.args[0].value != "asyncio"
            ):
                raise ValueError(f"unvalidated dynamic import in {name}")


def inspect(path: Path):
    allowed_names = {"LICENSE", "METADATA", "WHEEL", "top_level.txt", "RECORD"}
    allowed_suffixes = {".md", ".py", ".csv", ".json", ".sha256"}
    with ZipFile(path) as archive:
        names = archive.namelist()
        if archive.testzip() or len(names) != len(set(names)):
            raise ValueError("archive CRC failure or duplicate paths")
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            unsafe_path = name.is_absolute() or ".." in name.parts or "\\" in entry.filename
            if unsafe_path or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"unsafe archive entry {name}")
            if name.name not in allowed_names and name.suffix not in allowed_suffixes:
                raise ValueError(f"unexpected file type {name}")
            source = archive.read(entry).decode("utf-8")
            if name.name == "METADATA" and "\nRequires-Dist:" in source:
                raise ValueError("wheel unexpectedly requires runtime dependencies")
            if name.suffix == ".py":
                inspect_code(source, entry.filename)

    print(f"{path.name}: {len(names)} unique text members, {path.stat().st_size} bytes")
    print("CRC, file types, Python imports and dependency boundary: PASS")


if __name__ == "__main__":
    for value in sys.argv[1:]:
        inspect(Path(value))
