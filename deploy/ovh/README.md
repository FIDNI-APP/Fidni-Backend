# Déployer Fidni sur OVHcloud

Tout le site sur **un seul VPS OVH** : base PostgreSQL, backend, frontend et tunnel Cloudflare, dans
Docker. On quitte AWS entièrement (la base fait ~20 Mo, les fichiers ~3 Mo).

Le tunnel Cloudflare est gardé : **aucun port à ouvrir, aucun certificat à gérer, aucun DNS à
changer**. Le connecteur du tunnel passe simplement du PC au VPS.

Toutes les commandes `bash deployer.sh …` se lancent **dans WSL**, depuis ce dossier :

```bash
cd /mnt/c/Users/Natsu/Desktop/FIDNI/backend/deploy/ovh
```

---

## Étape 1 — Commander le VPS (sur ovhcloud.com, ~10 min)

1. Créer un compte OVHcloud (particulier). Tes nom et adresse y sont enregistrés : c'est ce que la
   loi demande pour un éditeur non professionnel (« coordonnées communiquées à l'hébergeur »).
2. **Bare Metal & VPS › VPS** ; choisir :
   - le plus petit modèle avec **au moins 4 Go de RAM** et **40 Go de disque** (8 Go de RAM, si
     l'écart de prix est faible, laisse de la marge pour la suite) ;
   - **localisation : France** (Gravelines, Roubaix ou Strasbourg) — la politique de
     confidentialité promet des données stockées dans l'UE ;
   - **système : Ubuntu 24.04** ;
   - option « sauvegarde automatique » : facultative (le script de sauvegarde ci-dessous suffit
     pour démarrer).
3. À la commande, OVH demande une **clé SSH** : voir l'étape 2, puis coller la clé publique.
4. Tu reçois un e-mail avec l'**adresse IP** du VPS et l'utilisateur (`ubuntu`).

## Étape 2 — Clé SSH et accès (dans WSL, ~5 min)

```bash
# 1. Créer une clé (s'il n'y en a pas déjà une) — laisse une phrase de passe
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519 -C fidni-ovh
cat ~/.ssh/id_ed25519.pub          # ← à coller dans OVH (commande ou « Clés SSH » de l'espace client)

# 2. Un raccourci « fidni-ovh » (remplacer 1.2.3.4 par l'IP reçue)
cat >> ~/.ssh/config <<'EOF'
Host fidni-ovh
  HostName 1.2.3.4
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519
EOF
chmod 600 ~/.ssh/config

# 3. Tester
ssh fidni-ovh 'hostname && uptime'
```

## Étape 3 — Préparer le serveur (~10 min)

```bash
bash deployer.sh installer
```

Ce que ça fait (`installer-serveur.sh`) : mises à jour + correctifs de sécurité automatiques,
Docker, pare-feu (seul SSH ouvert), connexion SSH par clé uniquement, 2 Go de swap, mot de passe
de la base généré, **sauvegarde chaque nuit** et **purges RGPD planifiées** (journaux, comptes
inactifs depuis 3 ans — promis par la politique de confidentialité et jamais lancés jusqu'ici).

## Étape 4 — Répétition de la migration (le site reste sur le PC)

```bash
bash deployer.sh migrer
```

Exporte la base RDS et les fichiers S3, les copie sur le VPS, démarre base + backend + frontend
**sans le tunnel** : le VPS ne sert encore personne. À la fin, le script affiche le nombre
d'exercices en ligne sur le VPS : il doit être le même que sur fidni.fr.

S'il y a une erreur, rien n'est cassé : le site tourne toujours sur le PC. On corrige et on relance.

## Étape 5 — Bascule (~10 min de coupure, choisir un moment creux)

```bash
bash deployer.sh basculer
```

1. arrête le tunnel du PC (le site devient injoignable : plus aucune écriture sur AWS) ;
2. refait l'export avec les données fraîches et le charge sur le VPS ;
3. démarre le tunnel sur le VPS : le site revient, servi par OVH ;
4. vérifie https://fidni.fr et https://api.fidni.fr de bout en bout ;
5. règle les outils d'import (`contenus/outils`) pour qu'ils visent le VPS.

Ensuite : **ne plus lancer `cloudflared/start.sh` sur le PC** (deux connecteurs sur le même
tunnel partageraient les visiteurs entre deux bases). Arrêter aussi les conteneurs locaux :
`docker compose down` dans `backend/` et dans `frontend/`.

En cas de gros problème : `bash deployer.sh retour` remet le site sur le PC et AWS (les écritures
faites entre-temps sur le VPS ne sont pas reprises).

## Étape 6 — Juste après la bascule

- **Mentions légales et politique de confidentialité** : l'hébergeur devient OVH SAS (2 rue
  Kellermann, 59100 Roubaix, France) à la place d'AWS. Me le dire : je mets à jour les deux pages
  et la version des conditions (les membres les réaccepteront).
- Tester à la main : connexion, un exercice, une auto-évaluation, l'envoi d'une photo dans une
  solution, un import de contenu.
- Première sauvegarde rapatriée sur le PC : `bash deployer.sh sauvegardes`.

## Étape 7 — Fermer AWS (fait le 29/09/2026)

> Fait : base RDS, buckets S3, cluster ECS, réseau, secrets, rôles, journaux supprimés. Reste
> seulement l'utilisateur IAM `admin-user` (gratuit). Texte d'origine gardé ci-dessous.

Si tout va bien, supprimer ce qui coûte : la base RDS (avec un dernier instantané), le bucket S3,
le secret Secrets Manager, les clés d'accès IAM. On le fait ensemble : ce sont des suppressions
définitives. L'export gardé dans `~/fidni-exports/` reste une copie complète de l'état d'avant.

Le développement local utilise encore la base RDS (`backend/.env`) : à repasser sur une base
locale avant de supprimer RDS.

---

## Au quotidien

| Besoin | Commande (WSL, dans ce dossier) |
|---|---|
| Mettre en ligne une modification | `bash deployer.sh` (tests, envoi du code, reconstruction) |
| Rapatrier les sauvegardes sur le PC | `bash deployer.sh sauvegardes` (à faire au moins chaque semaine) |
| Voir les journaux du backend | `ssh fidni-ovh docker logs -f --tail 100 fidni-backend` |
| État des conteneurs | `ssh fidni-ovh docker ps` |
| Restaurer une sauvegarde | sur le VPS : dossier avec `base.dump` (= `base-AAAA-MM-JJ.dump`) et `media/` (= `fichiers-AAAA-MM-JJ.tar.gz` décompressé), puis `sudo bash restaurer.sh <dossier>` et `sudo docker compose --profile enligne up -d tunnel` |

Les imports de contenus (`importer.sh`, `verifier.sh`) marchent comme avant : après la bascule ils
passent par SSH (`contenus/outils/serveur.conf`).

## Manipuler le serveur à la main

Se connecter : `ssh fidni-ovh` (depuis WSL). On arrive dans `/home/ubuntu` ; tout Fidni est dans
`/opt/fidni`. Les commandes `docker compose` se lancent depuis `/opt/fidni/backend/deploy/ovh`
et **avec `sudo`** (elles lisent les secrets). `docker ps`, `docker logs`, `docker exec` marchent
sans `sudo`.

Ce qui tourne (4 conteneurs) :

| Conteneur | Rôle |
|---|---|
| `fidni-db` | PostgreSQL 18, données dans le volume `fidni_pgdata` |
| `fidni-backend` | Django (API), fichiers envoyés dans le volume `fidni_media` |
| `fidni-frontend` | le site (nginx) |
| `fidni-tunnel` | tunnel Cloudflare : sans lui, le site est injoignable |

| Besoin | Commande (sur le serveur) |
|---|---|
| État | `docker ps` (4 lignes « Up ») ; `df -h /` (disque) ; `free -h` (mémoire) |
| Journaux | `docker logs --tail 100 fidni-backend` (ou `fidni-tunnel`, `fidni-db`…) ; `-f` pour suivre en direct |
| Redémarrer un conteneur | `docker restart fidni-backend` |
| Tout redémarrer | `cd /opt/fidni/backend/deploy/ovh && sudo docker compose --profile enligne restart` |
| Base de données (SQL) | `docker exec -it fidni-db psql -U fidni fidni` (`\dt` liste les tables, `\q` pour sortir) |
| Commande Django | `docker exec -it fidni-backend python manage.py shell` (ou `createsuperuser`, `importer_contenu`…) |
| Sauvegarde immédiate | `sudo /opt/fidni/backend/deploy/ovh/sauvegarde.sh` |
| Journaux des sauvegardes / purges | `cat /var/log/fidni-sauvegarde.log /var/log/fidni-purges.log` |
| Redémarrer la machine | `sudo reboot` : tout repart seul (conteneurs en `restart: unless-stopped`) |

Le serveur ne répond plus en SSH : espace client OVH › Public Cloud › Instances › `fidni-front`
› « Console VNC » (accès direct à l'écran), ou « Redémarrer ». En dernier recours : nouvelle
instance, `deployer.sh installer`, puis restauration de la dernière sauvegarde du PC.

À éviter : `docker compose down -v` (le `-v` efface la base et les fichiers), et relancer
`cloudflared/start.sh` ou les anciens `deploy-prod.sh` sur le PC.

## Fichiers

| Fichier | Rôle | Où il tourne |
|---|---|---|
| `docker-compose.yml` | base, backend, frontend, tunnel | VPS |
| `backend.env.exemple` | modèle du fichier de réglages (secrets) | — |
| `installer-serveur.sh` | préparation du VPS | VPS (via `deployer.sh installer`) |
| `restaurer.sh` | charge un export (base + fichiers + secrets) | VPS (via `deployer.sh migrer`) |
| `sauvegarde.sh` | sauvegarde nocturne, 14 jours gardés | VPS (cron) |
| `deployer.sh` | toutes les étapes ci-dessus | PC (WSL) |

Les secrets (réglages, mot de passe de la base, identifiants du tunnel) sont dans
`/opt/fidni/secrets` sur le VPS, jamais dans le dépôt : il est public.
