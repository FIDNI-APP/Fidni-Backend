#!/usr/bin/env bash
# Version de test sur le PC (WSL), branchée sur une COPIE de la base de production (jamais la vraie).
#
#   bash copie-locale.sh charger    recharge la base de test depuis la dernière sauvegarde locale
#                                   (C:\Users\Natsu\FIDNI-sauvegardes, voir ../ovh/sauvegarde-locale.sh)
#   bash copie-locale.sh backend    API de test sur http://localhost:8010 (migrations jouées d'abord)
#   bash copie-locale.sh            les deux
#
# Puis, dans frontend/ : VITE_API_URL=http://localhost:8010/api npm run dev  → http://localhost:3000
# Les e-mails ne partent pas (console), la clé Brevo et l'IA sont coupées : rien ne sort du PC.
set -euo pipefail
ROOT=/mnt/c/Users/Natsu/Desktop/FIDNI
SAUV=${FIDNI_SAUVEGARDES:-/mnt/c/Users/Natsu/FIDNI-sauvegardes}
PY=$ROOT/backend/venv/bin/python
PORT_DB=5433
PORT_API=8010

export DB_ENGINE=postgresql DB_HOST=127.0.0.1 DB_PORT=$PORT_DB DB_NAME=fidni DB_USER=fidni DB_PASSWORD=dev
export DB_SSLMODE=disable DB_SSLROOTCERT= AWS_DB_SECRET_ARN= AWS_STORAGE_ENABLED=false
export DJANGO_ENV=dev DEBUG=True SECURE_SSL_REDIRECT=False
export EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend BREVO_API_KEY= EMAIL_HOST_PASSWORD=
export ANTHROPIC_API_KEY= REDIS_URL= FIDNI_ANTI_TROLL=0
export ALLOWED_HOSTS=localhost,127.0.0.1 FRONTEND_URL=http://localhost:3000
export CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
export CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://localhost:5173

charger() {
  local dump fichiers
  dump=$(ls -t "$SAUV"/quotidiennes/base-*.dump | head -1)
  fichiers=${dump/base-/fichiers-}; fichiers=${fichiers%.dump}.tar.gz
  echo "→ Base de test depuis $(basename "$dump")"
  if ! docker ps -a --format '{{.Names}}' | grep -qx fidni-dev-db; then
    docker run -d --name fidni-dev-db -e POSTGRES_USER=fidni -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=postgres \
      -p 127.0.0.1:$PORT_DB:5432 -v fidni_dev_pg:/var/lib/postgresql postgres:18 >/dev/null
  fi
  docker start fidni-dev-db >/dev/null
  for _ in $(seq 1 30); do docker exec fidni-dev-db pg_isready -U fidni -q && break; sleep 2; done
  docker exec fidni-dev-db psql -U fidni -d postgres -qc "DROP DATABASE IF EXISTS fidni WITH (FORCE)"
  docker exec fidni-dev-db psql -U fidni -d postgres -qc "CREATE DATABASE fidni OWNER fidni"
  docker cp "$dump" fidni-dev-db:/tmp/base.dump
  docker exec fidni-dev-db pg_restore -U fidni -d fidni --no-owner --no-privileges -j 4 /tmp/base.dump
  docker exec fidni-dev-db rm /tmp/base.dump
  echo "→ Fichiers envoyés (images des contenus) dans backend/media"
  mkdir -p "$ROOT/backend/media" && tar xzf "$fichiers" -C "$ROOT/backend/media"
}

backend() {
  docker start fidni-dev-db >/dev/null
  cd "$ROOT/backend"
  $PY manage.py migrate --noinput
  echo "→ API de test : http://localhost:$PORT_API/api  (Ctrl+C pour arrêter)"
  exec $PY manage.py runserver 127.0.0.1:$PORT_API
}

case "${1:-tout}" in
  charger) charger ;;
  backend) backend ;;
  manage) shift; docker start fidni-dev-db >/dev/null; cd "$ROOT/backend"; exec $PY manage.py "$@" ;;
  tout) charger; backend ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
