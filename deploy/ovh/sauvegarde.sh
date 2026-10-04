#!/usr/bin/env bash
# Sauvegarde de Fidni sur le VPS : base (pg_dump) + fichiers envoyés (volume « media »).
# Lancée chaque nuit par cron (/etc/cron.d/fidni) ; garde 14 jours dans /var/backups/fidni.
# Une copie HORS du serveur reste indispensable : « deployer.sh sauvegardes » la rapatrie sur le PC.
set -euo pipefail
DEST=/var/backups/fidni
JOUR=$(date +%F)
mkdir -p "$DEST"

docker exec fidni-db pg_dump -U fidni -d fidni -Fc > "$DEST/base-$JOUR.dump.tmp"
mv "$DEST/base-$JOUR.dump.tmp" "$DEST/base-$JOUR.dump"

docker run --rm -v fidni_media:/media:ro -v "$DEST":/out alpine \
  tar czf "/out/fichiers-$JOUR.tar.gz" -C /media .

find "$DEST" -name 'base-*.dump' -mtime +14 -delete
find "$DEST" -name 'fichiers-*.tar.gz' -mtime +14 -delete
chown "$(stat -c %U /opt/fidni)" "$DEST"/*   # rapatriables par « deployer.sh sauvegardes »
chmod 600 "$DEST"/*
echo "$(date '+%F %T') sauvegarde OK : $(du -sh "$DEST/base-$JOUR.dump" | cut -f1) de base"
