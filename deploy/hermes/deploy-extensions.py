"""Install the reviewed project extension archive; restore configuration on failed activation.

Run with the deployment venv on Linux. Never prints config contents or credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

import yaml


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def merge_config(config, extension, root, release):
    """Preserve unrelated services, toolsets and plugin policy."""
    config = json.loads(json.dumps(config))
    servers = config.setdefault("mcp_servers", {})
    for name, entry in extension["mcp_servers"].items():
        entry = json.loads(json.dumps(entry))
        def expand(value):
            return value.replace("{root}", str(root)).replace("{release}", str(release))
        if "command" in entry:
            entry["command"] = expand(entry["command"])
        if "args" in entry:
            entry["args"] = [expand(value) for value in entry["args"]]
        servers[name] = entry
    plugins = config.setdefault("plugins", {})
    plugins["enabled"] = sorted(set(plugins.get("enabled") or []) | set(extension["plugins"]))
    plugins["disabled"] = [n for n in plugins.get("disabled", []) if n not in extension["plugins"]]
    platforms = config.setdefault("platform_toolsets", {})
    saved = platforms.get("api_server")
    platforms["api_server"] = list(dict.fromkeys((saved if isinstance(saved, list) else ["hermes-cli"])
                                                + extension["api_toolsets"]))
    # Installing an MCP explicitly enables it on this platform.
    platforms["api_server"] = [n for n in platforms["api_server"] if n != "no_mcp"]
    return config


def health():
    import httpx
    for _ in range(30):
        try:
            response = httpx.get("http://127.0.0.1:8642/health", timeout=3, trust_env=False)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError("Hermes API did not become healthy")


def rollback(root, backup):
    backup = backup.resolve()
    if backup.parent != (root / "extensions/backups").resolve():
        raise ValueError("Backup must be a direct child of extensions/backups")
    info = json.loads((backup / "restore.json").read_text())
    for rel, existed in info["paths"].items():
        destination = (root / "state" / rel).resolve()
        if not destination.is_relative_to(root / "state"):
            raise ValueError("Invalid rollback destination")
        saved = backup / rel
        if destination.exists():
            # Preserve the failed/current deployment rather than deleting files.
            archived = backup / ("displaced-" + str(time.time_ns()))
            destination.rename(archived)
        if existed:
            shutil.copytree(saved, destination)
    shutil.copy2(backup / "config.yaml", root / "state/config.yaml")
    run("sudo", "systemctl", "restart", "haudi-hermes-api.service")
    health()
    print("Rolled back extension configuration and managed directories:", backup.name)


def deploy(root, archive):
    base = root / "extensions"
    base.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        files = manifest["files"]
        digest = hashlib.sha256()
        for name in sorted(files):
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != files[name]:
                raise ValueError("Archive checksum mismatch")
            digest.update(name.encode() + b"\0" + data)
        release_id = digest.hexdigest()[:16]
        if manifest["release"] != release_id:
            raise ValueError("Invalid release identity")
        release = base / "releases" / release_id
        release.mkdir(parents=True, exist_ok=True)
        for name in files:
            destination = (release / name).resolve()
            if not destination.is_relative_to(release.resolve()):
                raise ValueError("Invalid archive path")
            data = z.read(name)
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError("Immutable release already exists with different contents")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (release / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Pin all existing distributions: installation may only add missing packages.
    constraints = base / "existing-packages.txt"
    constraints.write_text("\n".join(sorted(f"{d.metadata['Name']}=={d.version}"
                           for d in importlib.metadata.distributions() if d.metadata.get("Name"))) + "\n")
    # Install requirements for every MCP service shipped in this release, not
    # just the original paper-search one. Each service directory may carry its
    # own pinned requirements.txt.
    requirements = sorted((release / "mcp").glob("*/requirements.txt"))
    for req_file in requirements:
        run(str(root / "runtime/uv-bin/uv"), "pip", "install", "--python", sys.executable,
            "--constraint", str(constraints), "-r", str(req_file))
    run(str(root / "runtime/uv-bin/uv"), "pip", "check", "--python", sys.executable)
    ext = json.loads((release / "config.json").read_text())
    state = root / "state"
    config = yaml.safe_load((state / "config.yaml").read_text()) or {}
    merged = merge_config(config, ext, root, release)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = base / "backups" / stamp
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(state / "config.yaml", backup / "config.yaml")
    paths = [f"skills/{n}" for n in ext["skills"]] + [f"plugins/{n}" for n in ext["plugins"]]
    info = {"release": release_id, "paths": {p: (state / p).exists() for p in paths}}
    for rel in paths:
        if info["paths"][rel]:
            shutil.copytree(state / rel, backup / rel)
    (backup / "restore.json").write_text(json.dumps(info, indent=2))
    try:
        for rel in paths:
            target = state / rel
            if target.exists():
                target.rename(backup / ("previous-" + target.name))
            target.parent.mkdir(exist_ok=True)
            shutil.copytree(release / rel, target)
        temporary = state / "config.extensions.tmp"
        temporary.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))
        temporary.chmod(0o600)
        os.replace(temporary, state / "config.yaml")
        env = {**os.environ, "HERMES_HOME": str(state), "PYTHONPATH": str(root / "source")}
        run(sys.executable, str(release / "verify-extensions.py"), "--root", str(root),
            cwd=root / "source", env=env)
        run("sudo", "systemctl", "restart", "haudi-hermes-api.service")
        health()
    except Exception:
        rollback(root, backup)
        raise
    record = {"release": release_id, "backup": str(backup), "verified_at": stamp,
              "mcp": list(ext["mcp_servers"]), "skills": ext["skills"], "plugins": ext["plugins"]}
    (base / "deployment.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/ubuntu/haudi-hermes"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.rollback:
        rollback(root, args.rollback)
    elif args.archive:
        deploy(root, args.archive)
    else:
        parser.error("Pass --archive or --rollback")
