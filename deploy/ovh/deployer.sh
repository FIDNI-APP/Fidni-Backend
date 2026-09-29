#!/usr/bin/env bash
# Tout le déploiement OVH depuis le PC (WSL). Voir README.md pour l'ordre des étapes.
#
#   bash deployer.sh installer    1re fois : prépare le VPS (Docker, pare-feu, sauvegardes…)
#   bash deployer.sh migrer       copie la base et les fichiers d'AWS vers le VPS (répétition,
#                                 le site reste servi par le PC)
#   bash deployer.sh basculer     coupe le PC, recopie les données fraîches, met le VPS en ligne
#   bash deployer.sh              mise à jour du code (tests, envoi, reconstruction)
#   bash deployer.sh sauvegardes  rapatrie les sauvegardes du VPS sur le PC
#   bash deployer.sh retour       secours : remet le site sur le PC (après une bascule ratée)
#
# Hôte SSH : « fidni-ovh » (alias de ~/.ssh/config), ou FIDNI_SSH=autre-alias.
set -euo pipefail
ROOT=/mnt/c/Users/Natsu/Desktop/FIDNI
HOTE=${FIDNI_SSH:-fidni-ovh}
DISTANT=/opt/fidni/backend/deploy/ovh
ENV_PC="$ROOT/backend/.env"

# Valeur d'une clé du .env du PC (vide si absente, sans arrêter le script).
env_get() { { grep -E "^$1=" "$ENV_PC" || true; } | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }

envoyer_code() {
  echo "→ Envoi du code vers $HOTE"
  local exclus=(--exclude .git --exclude venv --exclude node_modules --exclude dist --exclude .env
                --exclude media --exclude static --exclude fidni_media_data --exclude fidni_sqlite_data
                --exclude __pycache__ --exclude '*.pyc')
  rsync -az --delete "${exclus[@]}" "$ROOT/backend/" "$HOTE:/opt/fidni/backend/"
  rsync -az --delete "${exclus[@]}" "$ROOT/frontend/" "$HOTE:/opt/fidni/frontend/"
}

controler_vps() {
  ssh "$HOTE" 'H=(-H "Host: api.fidni.fr" -H "X-Forwarded-Proto: https");
    echo "  API : HTTP $(curl -s -o /dev/null -w %{http_code} "${H[@]}" http://127.0.0.1:8080/api/contents/?type=exercise)";
    echo "  site : HTTP $(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:3001/)"'
}

installer() {
  ssh "$HOTE" 'sudo mkdir -p /opt/fidni && sudo chown "$USER:$USER" /opt/fidni'
  envoyer_code
  ssh -t "$HOTE" "sudo bash $DISTANT/installer-serveur.sh"
}

migrer() {
  command -v aws >/dev/null || { echo "✗ aws introuvable (lancer dans WSL)"; exit 1; }
  local jour out tunnel_id
  jour=$(date +%F-%H%M)
  out="$HOME/fidni-exports/$jour"
  mkdir -p "$out/secrets/cloudflared" "$out/media"
  chmod 700 "$HOME/fidni-exports"

  echo "→ Export de la base AWS (RDS)"
  PGPASSWORD=$(env_get DB_PASSWORD)
  if [ -z "$PGPASSWORD" ]; then
    PGPASSWORD=$(aws secretsmanager get-secret-value --secret-id "$(env_get AWS_DB_SECRET_ARN)" \
      --region "$(env_get AWS_REGION)" --query SecretString --output text \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')
  fi
  export PGPASSWORD
  docker run --rm -e PGPASSWORD -e PGSSLMODE=require postgres:18 \
    pg_dump -h "$(env_get DB_HOST)" -U "$(env_get DB_USER)" -d "$(env_get DB_NAME)" -Fc --no-owner --no-privileges \
    > "$out/base.dump"
  unset PGPASSWORD
  echo "  base : $(du -h "$out/base.dump" | cut -f1)"

  echo "→ Export des fichiers (S3)"
  aws s3 sync --only-show-errors "s3://$(env_get AWS_STORAGE_BUCKET_NAME)/media/" "$out/media/"
  echo "  fichiers : $(find "$out/media" -type f | wc -l)"

  echo "→ Secrets (réglages du backend sans les lignes AWS, tunnel Cloudflare)"
  grep -vE '^(DB_HOST|DB_PASSWORD|DB_SSLMODE|DB_SSLROOTCERT|AWS_[A-Z0-9_]+|GUNICORN_WORKERS)=' "$ENV_PC" > "$out/secrets/backend.env"
  echo "GUNICORN_WORKERS=3" >> "$out/secrets/backend.env"
  tunnel_id=$(grep -E '^tunnel:' "$ROOT/cloudflared/config.yml" | awk '{print $2}')
  cp "$HOME/.cloudflared/$tunnel_id.json" "$out/secrets/cloudflared/tunnel.json"
  cat > "$out/secrets/cloudflared/config.yml" <<EOF
tunnel: $tunnel_id
credentials-file: /etc/cloudflared/tunnel.json
ingress:
  - hostname: api.fidni.fr
    service: http://127.0.0.1:8080
  - hostname: fidni.fr
    service: http://127.0.0.1:3001
  - service: http_status:404
EOF
  chmod -R go-rwx "$out"

  envoyer_code
  echo "→ Envoi de l'export et restauration sur le VPS"
  ssh "$HOTE" 'rm -rf /tmp/fidni-migration && mkdir -m 700 /tmp/fidni-migration'
  rsync -az "$out/" "$HOTE:/tmp/fidni-migration/"
  ssh -t "$HOTE" "sudo bash $DISTANT/restaurer.sh /tmp/fidni-migration; rm -rf /tmp/fidni-migration"
  echo "  (copie de l'export gardée sur le PC : $out — elle contient des secrets)"
}

basculer() {
  echo "La bascule coupe le site ~10 minutes : le PC arrête de le servir, les données fraîches"
  read -r -p "sont copiées sur le VPS, puis le VPS prend le relais. Continuer ? [o/N] " rep
  [ "$rep" = o ] || { echo "Annulé."; exit 0; }

  echo "→ Arrêt du tunnel du PC (plus aucune écriture sur AWS)"
  pkill -f 'cloudflared.*tunnel' || true
  sleep 3

  migrer

  echo "→ Mise en ligne du VPS"
  ssh "$HOTE" "cd $DISTANT && sudo docker compose --profile enligne up -d tunnel"
  sleep 15
  echo "→ Vérification de bout en bout (depuis le VPS, via Cloudflare)"
  ssh "$HOTE" 'echo "  https://api.fidni.fr : HTTP $(curl -s -o /dev/null -w %{http_code} https://api.fidni.fr/api/contents/?type=exercise)";
               echo "  https://fidni.fr     : HTTP $(curl -s -o /dev/null -w %{http_code} https://fidni.fr/)"'

  # Les outils d'import (contenus/outils) visent désormais le VPS.
  echo "FIDNI_SSH=$HOTE" > "$ROOT/contenus/outils/serveur.conf"
  echo "✓ Le site tourne sur OVH. Ne relance plus cloudflared/start.sh sur le PC."
}

retour() {
  read -r -p "Remettre le site sur le PC (base AWS, sans les écritures faites sur le VPS) ? [o/N] " rep
  [ "$rep" = o ] || { echo "Annulé."; exit 0; }
  ssh "$HOTE" "cd $DISTANT && sudo docker compose --profile enligne stop tunnel"
  rm -f "$ROOT/contenus/outils/serveur.conf"
  bash "$ROOT/cloudflared/start.sh"
  echo "✓ Le PC sert de nouveau le site."
}

mettre_a_jour() {
  echo "→ Tests du backend"
  (cd "$ROOT/backend" && bash tests/checks/run_all.sh >/dev/null) || { echo "✗ Tests en échec : rien n'est envoyé."; exit 1; }
  echo "→ Vérification TypeScript"
  (cd "$ROOT/frontend" && node_modules/.bin/tsc -p tsconfig.app.json --noEmit)
  envoyer_code
  echo "→ Reconstruction sur le VPS"
  ssh "$HOTE" "cd $DISTANT && sudo docker compose up -d --build backend frontend"
  sleep 10
  controler_vps
}

sauvegardes() {
  mkdir -p "$HOME/fidni-sauvegardes" && chmod 700 "$HOME/fidni-sauvegardes"
  rsync -az "$HOTE:/var/backups/fidni/" "$HOME/fidni-sauvegardes/"
  echo "✓ Sauvegardes copiées dans ~/fidni-sauvegardes :"; ls -t "$HOME/fidni-sauvegardes" | head -4
}

case "${1:-maj}" in
  installer) installer ;;
  migrer) migrer ;;
  basculer) basculer ;;
  retour) retour ;;
  sauvegardes) sauvegardes ;;
  maj) mettre_a_jour ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
