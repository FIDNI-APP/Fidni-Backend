#!/usr/bin/env bash
# Copie quotidienne de la sauvegarde du VPS sur le PC (côté Windows, hors du disque WSL).
# Lancée chaque jour par le Planificateur de tâches Windows (tâche « FIDNI sauvegarde locale »,
# rattrapée au démarrage si le PC était éteint) : voir README.md.
#
#   bash sauvegarde-locale.sh            copie la sauvegarde de la nuit (base + fichiers)
#   bash sauvegarde-locale.sh --etat     dernières copies et journal
#
# Garde les 14 dernières copies quotidiennes, plus celle du 1er de chaque mois pendant 12 mois.
# Chaque base copiée est contrôlée (taille identique au serveur, pg_restore --list lisible).
set -euo pipefail
HOTE=${FIDNI_SSH:-fidni-ovh}
DEST=${FIDNI_SAUVEGARDES:-/mnt/c/Users/Natsu/FIDNI-sauvegardes}
JOURNAL="$DEST/journal.log"
mkdir -p "$DEST/quotidiennes" "$DEST/mensuelles"

if [ "${1:-}" = "--etat" ]; then
  ls -lh "$DEST/quotidiennes" | tail -6; ls -lh "$DEST/mensuelles" | tail -3; tail -5 "$JOURNAL"; exit 0
fi

log() { echo "$(date '+%F %T') $*" | tee -a "$JOURNAL"; }
trap 'log "ÉCHEC (ligne $LINENO) : voir ci-dessus"; echo "ÉCHEC $(date "+%F %T")" > "$DEST/ETAT.txt"' ERR

# Dernière sauvegarde de la nuit sur le serveur
BASE=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOTE" 'ls -t /var/backups/fidni/base-*.dump | head -1')
JOUR=$(basename "$BASE" .dump); JOUR=${JOUR#base-}
FICHIERS="/var/backups/fidni/fichiers-$JOUR.tar.gz"

if [ -s "$DEST/quotidiennes/base-$JOUR.dump" ]; then
  log "déjà copiée : $JOUR"; exit 0
fi

# rsync --partial : une coupure reprend où elle s'était arrêtée au lancement suivant
rsync -a --partial --timeout=120 "$HOTE:$BASE" "$HOTE:$FICHIERS" "$DEST/quotidiennes/.en-cours/" 2>&1 \
  || { mkdir -p "$DEST/quotidiennes/.en-cours"; rsync -a --partial --timeout=120 "$HOTE:$BASE" "$HOTE:$FICHIERS" "$DEST/quotidiennes/.en-cours/"; }

# Contrôles : même taille que sur le serveur, archive PostgreSQL lisible
T_DIST=$(ssh -o BatchMode=yes "$HOTE" "stat -c %s $BASE")
T_LOC=$(stat -c %s "$DEST/quotidiennes/.en-cours/base-$JOUR.dump")
[ "$T_DIST" = "$T_LOC" ] || { log "taille différente ($T_LOC ≠ $T_DIST)"; false; }
TABLES=$(pg_restore --list "$DEST/quotidiennes/.en-cours/base-$JOUR.dump" | grep -c ' TABLE DATA ')
[ "$TABLES" -gt 50 ] || { log "archive suspecte : $TABLES tables"; false; }
gzip -t "$DEST/quotidiennes/.en-cours/fichiers-$JOUR.tar.gz"

mv "$DEST/quotidiennes/.en-cours/base-$JOUR.dump" "$DEST/quotidiennes/.en-cours/fichiers-$JOUR.tar.gz" \
   "$DEST/quotidiennes/"
# Une copie par mois gardée un an
MOIS=${JOUR%-*}
if ! ls "$DEST/mensuelles/base-$MOIS-"*.dump >/dev/null 2>&1; then
  cp "$DEST/quotidiennes/base-$JOUR.dump" "$DEST/quotidiennes/fichiers-$JOUR.tar.gz" "$DEST/mensuelles/"
fi

# Rotation
ls -t "$DEST/quotidiennes"/base-*.dump | tail -n +15 | xargs -r rm -f
ls -t "$DEST/quotidiennes"/fichiers-*.tar.gz | tail -n +15 | xargs -r rm -f
ls -t "$DEST/mensuelles"/base-*.dump | tail -n +13 | xargs -r rm -f
ls -t "$DEST/mensuelles"/fichiers-*.tar.gz | tail -n +13 | xargs -r rm -f

log "OK $JOUR : base $(du -h "$DEST/quotidiennes/base-$JOUR.dump" | cut -f1) ($TABLES tables), fichiers $(du -h "$DEST/quotidiennes/fichiers-$JOUR.tar.gz" | cut -f1)"
echo "OK $JOUR ($(date '+%F %T'))" > "$DEST/ETAT.txt"
