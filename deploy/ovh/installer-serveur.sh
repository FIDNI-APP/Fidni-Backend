#!/usr/bin/env bash
# Prépare un VPS OVHcloud neuf (Ubuntu 24.04) pour Fidni. À lancer UNE fois, en root (sudo).
# Idempotent : le relancer ne casse rien. Lancé automatiquement par « deployer.sh installer ».
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "À lancer avec sudo."; exit 1; }
UTILISATEUR=${SUDO_USER:-ubuntu}

echo "→ Mises à jour du système"
export DEBIAN_FRONTEND=noninteractive
# Serveur tout neuf : cloud-init et les mises à jour automatiques tiennent encore apt quelques
# minutes. On attend qu'ils aient fini au lieu d'échouer sur « Could not get lock ».
command -v cloud-init >/dev/null && cloud-init status --wait >/dev/null || true
APT=(apt-get -o DPkg::Lock::Timeout=600)
"${APT[@]}" update -q
"${APT[@]}" upgrade -yq
"${APT[@]}" install -yq ca-certificates curl rsync ufw fail2ban unattended-upgrades
# Correctifs de sécurité installés automatiquement chaque nuit.
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "→ Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$UTILISATEUR"   # docker sans sudo pour « $UTILISATEUR » (nouvelle session SSH)
systemctl enable --now docker

echo "→ Pare-feu : seul SSH est ouvert (le site passe par le tunnel Cloudflare, sortant)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "→ SSH : connexion par clé uniquement"
if grep -q '^ssh-' "/home/$UTILISATEUR/.ssh/authorized_keys" 2>/dev/null; then
  cat > /etc/ssh/sshd_config.d/10-fidni.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
EOF
  systemctl reload ssh
else
  echo "  (aucune clé SSH trouvée pour $UTILISATEUR : mot de passe laissé actif, à corriger)"
fi

echo "→ Mémoire d'appoint (swap 2 Go) pour les constructions d'images"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "→ Dossiers"
mkdir -p /opt/fidni/secrets/cloudflared /var/backups/fidni
chown "$UTILISATEUR:$UTILISATEUR" /opt/fidni
chmod 700 /opt/fidni/secrets
if [ ! -s /opt/fidni/secrets/db_password ]; then
  openssl rand -hex 24 > /opt/fidni/secrets/db_password
  echo "  mot de passe de la base généré (/opt/fidni/secrets/db_password)"
fi
# Lisible par l'utilisateur « postgres » du conteneur ; le dossier parent (700) protège le reste.
chmod 644 /opt/fidni/secrets/db_password

echo "→ Tâches planifiées (sauvegarde chaque nuit, purges RGPD)"
cat > /etc/cron.d/fidni <<'EOF'
# Fidni — installé par installer-serveur.sh
30 3 * * *  root  /opt/fidni/backend/deploy/ovh/sauvegarde.sh >> /var/log/fidni-sauvegarde.log 2>&1
15 4 * * *  root  docker exec fidni-backend python manage.py purger_journaux >> /var/log/fidni-purges.log 2>&1
0 5 * * 1   root  docker exec fidni-backend python manage.py purger_comptes_inactifs --appliquer >> /var/log/fidni-purges.log 2>&1
EOF

echo "✓ Serveur prêt. Déconnecte-toi puis reconnecte-toi pour utiliser docker sans sudo."
