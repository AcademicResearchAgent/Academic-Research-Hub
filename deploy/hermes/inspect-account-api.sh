set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
for name,markers in {
    'routers/auths.py':["@router.post('/add'"],
    'models/auths.py':['class AddUserForm'],
    'routers/users.py':["@router.get('/'",'class UserUpdateForm',"@router.post('/{user_id}/update'"],
}.items():
    lines=(Path('/app/backend/open_webui')/name).read_text().splitlines()
    for i,line in enumerate(lines):
        if any(m in line for m in markers):
            print(name,'\n'.join(lines[i:i+55]))
PY
