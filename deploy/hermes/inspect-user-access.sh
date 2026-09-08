set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
for filename, markers in {
    'models/users.py':['class UserUpdateForm'],
    'routers/models.py':['class ModelAccessGrantsForm',"@router.post('/model/access/update'"],
    'models/access_grants.py':['class AccessGrantForm','class AccessGrantModel'],
}.items():
    lines=(Path('/app/backend/open_webui')/filename).read_text().splitlines()
    for i,line in enumerate(lines):
        if any(marker in line for marker in markers):
            print(filename,'\n'.join(lines[i:i+45]))
PY
