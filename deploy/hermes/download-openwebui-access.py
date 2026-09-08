"""Save the newly generated UI login details locally without printing secrets."""
from pathlib import Path
import subprocess
from remote import SSH, OPTIONS

target=Path(__file__).resolve().parent/'openwebui-access.json'
result=subprocess.run(
    [SSH,*OPTIONS,'haudi-hermes-server','cat /home/ubuntu/haudi-hermes/openwebui/access.json'],
    check=True,capture_output=True,
)
target.write_bytes(result.stdout)
print('Open WebUI login details saved to '+str(target))
