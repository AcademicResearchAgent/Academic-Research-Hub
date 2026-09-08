"""Run a reviewed deployment script over the project's dedicated SSH connection."""
import os
from pathlib import Path
import subprocess
import sys

SSH = r"C:\Windows\System32\OpenSSH\ssh.exe"
OPTIONS = [
    "-l", "ubuntu", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=yes", "-o",
    "UserKnownHostsFile=" + str(Path(__file__).resolve().parent / "known_hosts"),
]

if __name__ == "__main__":
    script = Path(sys.argv[1]).read_bytes().replace(b"\r\n", b"\n")
    result = subprocess.run([SSH, *OPTIONS, "haudi-hermes-server", "bash -s"], input=script)
    raise SystemExit(result.returncode)
