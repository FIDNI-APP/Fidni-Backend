#!/usr/bin/env bash
# Charge sur le VPS un export produit par « deployer.sh migrer » (base + fichiers + secrets), puis
# démarre le site SANS le tunnel (il ne sert donc encore personne). Relançable : la base est
# entièrement remplacée à chaque fois (répétition, puis bascule finale).
# Usage (sur le VPS) : sudo bash restaurer.sh /tmp/fidni-migration
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "À lancer avec sudo."; exit 1; }
SRC=$(realpath "${1:?dossier d export manquant}")
S=/opt/fidni/secrets
cd "$(dirname "$0")"
[ -f "$SRC/base.dump" ] || { echo "✗ $SRC/base.dump introuvable"; exit 1; }

echo "→ Secrets"
if [ -f "$SRC/secrets/backend.env" ]; then
  grep -v '^DB_PASSWORD=' "$SRC/secrets/backend.env" > "$S/backend.env"
  echo "DB_PASSWORD=$(cat "$S/db_password")" >> "$S/backend.env"
  chmod 600 "$S/backend.env"
fi
if [ -f "$SRC/secrets/cloudflared/tunnel.json" ]; then
  cp "$SRC/secrets/cloudflared/"* "$S/cloudflared/"
  chmod 755 "$S/cloudflared" && chmod 644 "$S/cloudflared/"*   # lus par l'utilisateur du conteneur
fi
[ -f "$S/backend.env" ] || { echo "✗ $S/backend.env manquant"; exit 1; }

echo "→ Base de données (remplacée entièrement)"
docker compose stop backend 2>/dev/null || true
docker compose up -d db
for _ in $(seq 1 30); do docker exec fidni-db pg_isready -U fidni -d postgres -q && break; sleep 2; done
docker exec fidni-db psql -U fidni -d postgres -qc "DROP DATABASE IF EXISTS fidni WITH (FORCE)"
docker exec fidni-db psql -U fidni -d postgres -qc "CREATE DATABASE fidni OWNER fidni"
docker exec -i fidni-db pg_restore -U fidni -d fidni --no-owner --no-privileges --exit-on-error < "$SRC/base.dump"

echo "→ Fichiers envoyés (volume media)"
# Étiquettes Compose : le volume est alors reconnu comme le sien (pas d'avertissement).
docker volume inspect fidni_media >/dev/null 2>&1 || docker volume create \
  --label com.docker.compose.project=fidni --label com.docker.compose.volume=media fidni_media >/dev/null
# L'export est verrouillé (il contient des secrets) : on rend les fichiers lisibles par le nginx
# du backend, sinon les images des contenus répondent 403.
docker run --rm -v fidni_media:/m -v "$SRC/media":/src:ro alpine \
  sh -c 'rm -rf /m/* && cp -a /src/. /m/ && chown -R root:root /m && chmod -R u=rwX,go=rX /m'

echo "→ Démarrage (sans le tunnel)"
docker compose up -d --build backend frontend

echo "→ Contrôles"
H=(-H 'Host: api.fidni.fr' -H 'X-Forwarded-Proto: https')
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" http://127.0.0.1:8080/api/contents/?type=exercise)" = 200 ] && break
  sleep 3
done
curl -s "${H[@]}" "http://127.0.0.1:8080/api/contents/?type=exercise" | python3 -c \
  'import json,sys; print("  exercices en ligne :", json.load(sys.stdin).get("count"))'
echo "  site : HTTP $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/)"
echo "✓ Restauré. Le tunnel n'est PAS démarré (voir « deployer.sh basculer »)."
