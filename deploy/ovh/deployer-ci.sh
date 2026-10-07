#!/usr/bin/env bash
# Mise en ligne lancée par GitHub Actions, à chaque push sur master (une fois les tests verts).
#
# C'est la « commande forcée » de la clé SSH de GitHub (utilisateur « deploiement ») : cette clé
# ne peut rien faire d'autre que lancer ce script. Installé par installer-ci.sh dans
# /usr/local/sbin/fidni-deployer-ci (copie appartenant à root : modifier ce fichier dans le dépôt
# ne change rien tant qu'on n'a pas relancé « bash deployer.sh ci » depuis le PC).
#
#   git archive --format=tar.gz HEAD | ssh deploiement@serveur backend     (ou frontend)
#
# Reçoit le code sur l'entrée standard, le copie dans /opt/fidni/<dépôt>, reconstruit le
# conteneur, vérifie qu'il répond, et remet l'image précédente sinon.
# Les journaux des Actions sont PUBLICS (dépôts publics) : ne rien afficher de secret ici.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "À lancer avec sudo." >&2; exit 1; }

case "${1:-}" in
  backend)  ADRESSE='http://127.0.0.1:8080/api/contents/?type=exercise'
            ENTETES=(-H 'Host: api.fidni.fr' -H 'X-Forwarded-Proto: https') ;;
  frontend) ADRESSE='http://127.0.0.1:3001/'
            ENTETES=() ;;
  *) echo "usage : fidni-deployer-ci backend|frontend" >&2; exit 2 ;;
esac
DEPOT=$1
CIBLE=/opt/fidni/$DEPOT
COMPOSE=/opt/fidni/backend/deploy/ovh
IMAGE=fidni-$DEPOT
PROPRIO=$(stat -c %U /opt/fidni)

# Un seul déploiement à la fois : un push sur chaque dépôt peut arriver en même temps.
exec 9>/var/lock/fidni-deploiement.lock
flock 9

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "→ Réception du code ($DEPOT)"
tar -xzf - -C "$TMP"
[ -f "$TMP/Dockerfile" ] || { echo "✗ Archive vide ou incomplète : rien n'est changé." >&2; exit 1; }

echo "→ Copie dans $CIBLE"
# Mêmes exclusions que deployer.sh : les fichiers propres au serveur ne sont jamais touchés.
rsync -rlt --delete --chown="$PROPRIO:$PROPRIO" \
  --exclude .git --exclude venv --exclude node_modules --exclude dist --exclude .env \
  --exclude media --exclude static --exclude fidni_media_data --exclude fidni_sqlite_data \
  --exclude __pycache__ --exclude '*.pyc' \
  "$TMP/" "$CIBLE/"

echo "→ Reconstruction du conteneur"
docker image tag "$IMAGE:latest" "$IMAGE:precedent" 2>/dev/null || true
cd "$COMPOSE"
docker compose up -d --build "$DEPOT"

echo "→ Vérification"
code=000
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "${ENTETES[@]}" "$ADRESSE" || true)
  [ "$code" = 200 ] && break
  sleep 3
done

if [ "$code" != 200 ]; then
  echo "✗ $DEPOT ne répond pas (HTTP $code) : retour à la version précédente."
  echo "  Journaux sur le serveur : cd $COMPOSE && sudo docker compose logs --tail 100 $DEPOT"
  if docker image inspect "$IMAGE:precedent" >/dev/null 2>&1; then
    docker image tag "$IMAGE:precedent" "$IMAGE:latest"
    docker compose up -d --no-build "$DEPOT"
  fi
  exit 1
fi

docker image prune -f >/dev/null   # images intermédiaires des constructions précédentes
echo "✓ $DEPOT en ligne (HTTP $code)"
