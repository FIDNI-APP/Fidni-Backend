#!/usr/bin/env bash
# Met en ligne l'API : tests sur base jetable, construction, plan de migration, redémarrage, santé.
# Les migrations s'appliquent au démarrage du conteneur (entrypoint.sh).
# Usage (dans WSL) : bash backend/scripts/deploy-prod.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ Tests (SQLite jetable, jamais la base de production)"
bash tests/checks/run_all.sh

echo "→ Construction de l'image"
docker compose build -q

echo "→ Migrations qui seront appliquées :"
docker compose run --rm --no-deps --entrypoint sh fidni-backend -c 'cd /app && python manage.py migrate --plan' 2>/dev/null \
  | sed -n '/Planned operations/,$p'

echo "→ Redémarrage"
docker compose up -d

for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8080/api/schools/?q=lyc' || true)
  [ "$code" = 200 ] && { echo "✓ API en ligne (port 8080)"; exit 0; }
  sleep 3
done
echo "✗ L'API ne répond pas : docker compose logs fidni-backend" >&2
exit 1
