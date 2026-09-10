"""Build an immutable, non-secret extension release from repository files."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = {}
    for path in sorted((ROOT / "extensions").rglob("*")):
        # .json 契约文件（tools/*.json、manifest.json 等）随扩展一起归档。
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".yaml", ".txt", ".json"}:
            files[path.relative_to(ROOT / "extensions").as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
    files["config.json"] = (ROOT / "configs/workstation/extensions.json").read_bytes().replace(b"\r\n", b"\n")
    config = json.loads(files["config.json"])
    cfd_tools = config["mcp_servers"]["cfd_npy3d"]["tools"]["include"]
    for name, source in config.get("skill_sources", {}).items():
        source_root = (ROOT / "extensions" / source).resolve()
        assert source_root.is_relative_to((ROOT / "extensions").resolve())
        assert name in config["skills"] and (source_root / "SKILL.md").is_file()
        for path in source_root.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            if source.startswith("mcp/cfd-npy3d/"):
                for tool in cfd_tools:
                    content = re.sub(r"(?<![\w])" + tool + r"(?![\w])", "mcp__cfd_npy3d__" + tool, content)
                content = content.replace('data_dir="g:/mcp-/cfd_npy3d_mcp/sample_data"', '')
                content += '\n部署环境不传 data_dir 时读取已准备的合成 CFD 示例；这是演示数据，不是实际实验结果。不要照抄开发机器路径。\n'
            files["skills/" + name + "/" + path.relative_to(source_root).as_posix()] = content.encode("utf-8")
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
