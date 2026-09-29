#!/usr/bin/env bash
# Vérifications de bout en bout du backend, chacune sur une base SQLite jetable
# (jamais la base de production). Depuis backend/ :  bash tests/checks/run_all.sh
set -u
cd "$(dirname "$0")/../.."
PY=${PYTHON:-venv/bin/python}
fail=0
for f in tests/checks/check_*.py; do
  echo "=== $f"
  out=$("$PY" "$f" 2>&1); rc=$?
  echo "$out" | grep -v WARNING | tail -3
  [ $rc -ne 0 ] && { echo "!!! $f a échoué (code $rc)"; fail=1; }
done
if [ $fail -eq 0 ]; then echo "TOUT EST VERT"; else echo "ÉCHEC"; exit 1; fi
