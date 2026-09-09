"""Build an immutable, non-secret extension release from repository files."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = {}
    for path in sorted((ROOT / "extensions").rglob("*")):
        # .json 契约文件（tools/*.json、manifest.json 等）随扩展一起归档。
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".yaml", ".txt", ".json"}:
            files[path.relative_to(ROOT / "extensions").as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
    files["config.json"] = (ROOT / "configs/workstation/extensions.json").read_bytes().replace(b"\r\n", b"\n")
    for name in ("deploy-extensions.py", "verify-extensions.py"):
        files[name] = (ROOT / "deploy/hermes" / name).read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b"\0" + data)
    release = digest.hexdigest()[:16]
    manifest = {"release": release, "files": {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}}
    target = ROOT / ".build/extensions.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    print(f"Packaged {len(files)} files; release {release}: {target}")


if __name__ == "__main__":
    main()
