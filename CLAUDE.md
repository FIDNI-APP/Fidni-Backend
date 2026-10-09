# Fidni backend — carte du projet

Django 5 + DRF · PostgreSQL (AWS RDS, JSONB pour les structures de contenu) · S3 (médias) · JWT (simplejwt).
Une seule stack, un seul fichier d'env, un seul compose.

## Démarrer

```bash
docker compose up --build -d      # stack prod complète (RDS + S3), port 127.0.0.1:8080
docker compose logs -f fidni-backend
# manage.py local (WSL, venv) : lit le même .env → même RDS
python manage.py migrate / createsuperuser / shell
```

## Configuration — UN seul endroit

- **`.env`** (racine backend, git-ignoré) : TOUTES les variables — Django, RDS, Secrets Manager, S3, SMTP Brevo, CORS. Template : `.env.example`.
- Lu par : `docker-compose.yml` (`env_file`) ET `src/config/settings/base.py` (`load_dotenv`).
- Secrets AWS : jamais dans `.env` — le mot de passe RDS vient de Secrets Manager, les credentials AWS du `~/.aws` monté en RO dans le conteneur.
- Settings : `src/config/settings/` — `base.py` (tout), `dev.py`/`prod.py` (petits overrides). `DJANGO_ENV=production` dans `.env` sélectionne prod.

## Arborescence

```
backend/
├── .env / .env.example      ← config (voir ci-dessus)
├── docker-compose.yml       ← LA stack (un seul service + ~/.aws monté)
├── Dockerfile               ← image (python:3.12-slim + nginx + gunicorn)
├── entrypoint.sh            ← migrate → seed → collectstatic → nginx → gunicorn
├── requirements.txt         ← dépendances DIRECTES uniquement (~15)
├── certs/global-bundle.pem  ← CA RDS (sslmode=verify-full)
├── nginx/                   ← reverse proxy interne au conteneur (port 80 → gunicorn 8000)
├── tests/base_tables.py     ← seeder de taxonomie (pas des tests), lancé par entrypoint
└── src/
    ├── config/              ← urls.py racine, wsgi.py, settings/
    └── apps/                ← 13 apps Django (voir ci-dessous)
```

## Les 13 apps — qui fait quoi

| App | Rôle | Modèles clés |
|---|---|---|
| `things` | Contenus (exercices/leçons/examens) — cœur de l'app | `Content` (avec `json_content` JSONB), `Solution`, `Comment` |
| `caracteristics` | Taxonomie | `ClassLevel`, `Subject`, `Subfield`, `Chapter`, `Theorem` |
| `users` | Profils, stats, dashboard | `UserProfile`, `ViewHistory` |
| `authentication` | Register/login JWT, vérification email (Brevo) | — |
| `interactions` | Votes, favoris, progression, temps d'étude | `Vote`, `Save`, `Complete` (⚠ `object_id` **CharField** → ids en `str`), `StudyTimeTracker` (int) |
| `uploads` | Fichiers → S3 | `FileAttachment` — URL stable : `/api/files/<uuid>/download/` |
| `notebooks` | Cahiers de cours | `Notebook`, chapitres/sections |
| `skilliq` | Quiz d'évaluation par chapitre | `SkillAssessment` |
| `classrooms` | Classes prof/élèves | `Classroom`, TD lists |
| `concours` | Examens concours (QCM) | `ConcoursExam` (avec `json_content` JSONB) |
| `learningpath` | Parcours vidéo | — |
| `logging` | Logs API/erreurs en base | — |
| `notifications` | Cloche : nouveau commentaire sur un contenu avec lequel on a interagi, réponse à son commentaire (regroupées par contenu) | `Notification` |

## Conventions & pièges connus

- **Structures de contenu** : vivent dans `Content.json_content` (JSONB). Accès via `apps/things/content_store.py` (même API que l'ancien store MongoDB, supprimé). Idem concours.
- **Generic relations** (`Vote`/`Save`/`Complete`…) : `object_id` est un **CharField** — toujours passer des ids **string** (`[str(i) for i in ...]`), PostgreSQL refuse les comparaisons varchar/bigint (bug classique hérité de SQLite).
- **Tri « Pour toi »** (`sort=recommended`, défaut des listes côté front) : `apps/things/for_you.py` — score par élève (chapitres travaillés, nouveautés, à retravailler, réussis en dernier, variété), calculé en Python puis paginé dans `ContentViewSet.list`. Vérifié par `tests/checks/check_for_you.py`.
- **Ma progression** (`GET /api/stats/progression/`, page `/progression` du front) : `apps/users/progression.py` — carte du programme (maîtrise par chapitre = auto-évaluations 60 % + Skill IQ 40 %), points forts/faibles, évolution, temps d'étude. L'ancien `/api/stats/me/` (`my_stats.py`) sert encore au résumé du profil.
- **Pilotage** (admins, `apps/users/admin_dashboard.py`) : visiteurs non connectés comptés à part (`anon_count`/`anon_visitors` de `UsageDaily` et `ContentDailyView`, ligne `site/visites` = personnes distinctes par jour) et valeurs des filtres des listes (`UsageDaily` kind `filtre`, « exercise:difficulte:hard »), depuis le 09/10/2026. « Un membre n'arrive pas à se connecter » : `GET /api/pilotage/connexion/?q=` (`apps/users/login_diagnostic.py`, lit `APILog`/`ErrorLog` + blocage du `LoginAccountThrottle`).
- **Bandeau « à évaluer »** de la liste « Pour toi » : `GET /api/contents/a-evaluer/` (`apps/things/catch_up.py`).
- **Images dans les contenus** : uploadées via `POST /api/files/upload/` (S3 : `media/uploads/content/YYYY/MM/uuid_nom`), et le HTML embarque l'URL **stable** `download_url` (les URLs S3 présignées expirent en 1 h).
- **S3** : bucket privé `fidni-media-512768499268` (eu-west-3), endpoint régional forcé (le global 307-redirect casse les signatures).
- Le front (fidni.fr) appelle `https://api.fidni.fr` = tunnel Cloudflare → ce conteneur (port local 8080).

## Infra

- **RDS** : `database-1...eu-west-3.rds.amazonaws.com` / db `fidni` — mot de passe via Secrets Manager (ARN dans `.env`).
- **Tunnel** : cloudflared sur l'hôte → `localhost:8080`. Le conteneur n'expose rien publiquement.
- ⚠️ TODO sécurité : security group RDS encore ouvert (0.0.0.0/0) — à restreindre au port 5432 + IP.
