#!/usr/bin/env bash
# Autorise GitHub Actions à mettre le site en ligne. À lancer en root (sudo), avec la clé
# PUBLIQUE de GitHub en argument. Lancé par « bash deployer.sh ci » depuis le PC.
# Idempotent : le relancer remplace la clé et met à jour le script de déploiement.
#
# La clé est enfermée : utilisateur « deploiement » sans mot de passe, commande forcée
# (fidni-deployer-ci), pas de shell, pas de redirection de ports, sudo limité à ce seul script.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "À lancer avec sudo." >&2; exit 1; }
CLE=${1:-}
[[ "$CLE" == ssh-ed25519\ * ]] || { echo "usage : installer-ci.sh 'ssh-ed25519 AAAA… commentaire'" >&2; exit 2; }
UTIL=deploiement
ICI=$(cd "$(dirname "$0")" && pwd)

echo "→ Utilisateur $UTIL"
id "$UTIL" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$UTIL"
passwd -l "$UTIL" >/dev/null

echo "→ Script de déploiement (/usr/local/sbin/fidni-deployer-ci)"
install -m 755 -o root -g root "$ICI/deployer-ci.sh" /usr/local/sbin/fidni-deployer-ci

echo "→ sudo limité à ce script"
cat > /etc/sudoers.d/fidni-deploiement <<EOF
$UTIL ALL=(root) NOPASSWD: /usr/local/sbin/fidni-deployer-ci
EOF
chmod 440 /etc/sudoers.d/fidni-deploiement
visudo -cf /etc/sudoers.d/fidni-deploiement >/dev/null

echo "→ Clé SSH (commande forcée)"
# Dossier et fichier à root : l'utilisateur ne peut pas modifier sa propre clé.
install -d -m 755 -o root -g root "/home/$UTIL/.ssh"
printf 'restrict,command="sudo -n /usr/local/sbin/fidni-deployer-ci \\"$SSH_ORIGINAL_COMMAND\\"" %s\n' "$CLE" \
  > "/home/$UTIL/.ssh/authorized_keys"
chown root:root "/home/$UTIL/.ssh/authorized_keys"
chmod 644 "/home/$UTIL/.ssh/authorized_keys"

echo "✓ GitHub Actions peut déployer (et rien d'autre)."
