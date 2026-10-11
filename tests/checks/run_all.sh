#!/usr/bin/env bash
# Vérifications de bout en bout du backend, chacune sur une base SQLite jetable
# (jamais la base de production). Depuis backend/ :  bash tests/checks/run_all.sh
#
# Rapide : la base est migrée UNE fois (modèle), puis copiée pour chaque fichier (config/settings/base.py,
# FIDNI_CHECK_MODELE) au lieu de rejouer les migrations ; les fichiers tournent en parallèle (chacun a sa
# propre base). Un seul fichier : python tests/checks/check_x.py (sans modèle, il migre lui-même).
set -u
cd "$(dirname "$0")/../.."
PY=${PYTHON:-venv/bin/python}
TRAVAIL=$(mktemp -d)
trap 'rm -rf "$TRAVAIL"' EXIT

echo "=== base modèle (migrations)"
SQLITE_PATH="$TRAVAIL/modele.sqlite3" DB_ENGINE=sqlite DJANGO_ENV=development AWS_STORAGE_ENABLED=false \
  DJANGO_SETTINGS_MODULE=config.settings PYTHONPATH="src:." \
  "$PY" -c "import django; django.setup(); from django.core.management import call_command; call_command('migrate', verbosity=0)" \
  || { echo "!!! migrations en échec"; echo "ÉCHEC"; exit 1; }
export FIDNI_CHECK_MODELE="$TRAVAIL/modele.sqlite3"

# Tous les fichiers en parallèle, chacun écrit son résultat dans $TRAVAIL/<nom>.out (+ .rc).
ls tests/checks/check_*.py | xargs -P "${JOBS:-$(nproc)}" -I{} sh -c \
  'f="$1"; n=$(basename "$f" .py); "$2" "$f" > "$3/$n.out" 2>&1; echo $? > "$3/$n.rc"' _ {} "$PY" "$TRAVAIL"

fail=0
for f in tests/checks/check_*.py; do
  n=$(basename "$f" .py)
  echo "=== $f"
  grep -v WARNING "$TRAVAIL/$n.out" | tail -3
  rc=$(cat "$TRAVAIL/$n.rc" 2>/dev/null || echo 1)
  [ "$rc" -ne 0 ] && { echo "!!! $f a échoué (code $rc)"; fail=1; }
done
if [ $fail -eq 0 ]; then echo "TOUT EST VERT"; else echo "ÉCHEC"; exit 1; fi
