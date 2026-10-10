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
  Depuis le 10/10/2026 : « actif » = dates stables seulement (`_activity_sources` : `StudyTimeDay.date`, `created_at`… ; `viewed_at`/`last_login` ne servent qu'à la « dernière activité » des membres), entonnoir `funnel` de la cohorte inscrite, portes d'inscription `auth_doors` (`UsageDaily` kind `filtre`, « auth:porte:vote »), `todo.difficulty_gaps`.
- **Audit d'usage** (lecture seule : transaction `READ ONLY`, aucune écriture de cache) : `docker exec fidni-backend python manage.py audit_usage --jours 30 --format md > audit.md` sur l'hôte (sans `-t` ; ou `--sortie` dans le conteneur ; `--format json` = tout, `--top`, `--min-eleves`) — fonctionnalités et gestes les moins utilisés, pages jamais vues, entonnoir, rétention, réussite réelle vs difficulté affichée, solutions, signalements, temps. Copie de `PAGES` (front `lib/usage.ts`) dans `PAGE_PATTERNS` : à tenir à jour.
- **Ressenti des élèves** (difficulté) : la difficulté éditoriale ne change pas ; `apps/things/difficulty.py` (`felt_for` en lot, cache 6 h ; `difficulty_gaps` pour Pilotage › À traiter) combine réussite réelle (comptes maison exclus, « Tout réussi » pesant ½ via `QuestionProgress.source`) et avis `DifficultyFeedback` (`POST/DELETE /api/contents/<id>/ressenti/`) ; champ `felt` des listes et du détail.
- **Connexion Google** (10/10/2026) : `POST /api/auth/google/` (`apps/authentication/google.py` vérifie le jeton d'identité avec le Client ID public `GOOGLE_CLIENT_ID` — le code secret OAuth n'est PAS utilisé ; clés JWKS de googleapis.com, d'où `cryptography`). Liaison `GoogleAccount` par `sub`, sinon par e-mail **confirmé** ; une adresse non confirmée (inscription en attente ou adresse changée) est reprise par le titulaire Google : mot de passe retiré, sessions révoquées. Premier mot de passe d'un compte Google : seulement par le lien « Mot de passe oublié » (`use_password_reset`). Changer d'adresse dans les réglages ⇒ `email_verified=False` + e-mail « Confirme ta nouvelle adresse » (`new_email_verified`, sans jetons). `credential` est masqué dans `APILog`.
- **Espace élève refondu** (11/10/2026) : menu « Mon suivi » = Ma progression · **Réviser** (`/reviser` du front : prochain DS, « À refaire » via `GET /api/revision-lists/suggestions/?tout=1` — y compris les contenus déjà rangés (`in_list`), plus anciens d'abord, `days_ago`, 30 au plus — et mes listes) · Quiz par chapitre · **Mes enregistrements** (`/enregistrements` = favoris + cahiers). Anciennes adresses (`/revision-lists`, `/saved`, `/notebooks`) redirigées par le front ; `PAGES`/`PAGE_PATTERNS` les gardent.
- **Bandeau « à évaluer »** de la liste « Pour toi » : `GET /api/contents/a-evaluer/` (`apps/things/catch_up.py`).
- **Listes en dossiers** (10/10/2026) : Maths › niveau › chapitre, les contenus sont les « fichiers » (`apps/caracteristics/hubs.py`). `GET /api/hubs/niveaux/?section=` = dossiers de niveaux ; `GET /api/hubs/` renvoie `folders` = TOUS les chapitres du niveau (`count: 0` = dossier vide, non cliquable côté front ; `mine {done, success}` pour un élève connecté) ; `GET /api/hubs/nationaux/` = Bac national par année (`national_year=aucune` dans `/api/contents/` et `/api/difficulty-counts/` pour les sujets sans année). Rubrique `exams` = devoirs seulement : les comptes excluent `is_national_exam` (comme la liste). Front : `pages/content/ContentFolders.tsx`, `ContentHub.tsx`.
- **Erreurs d'affichage du navigateur** : `POST /api/logs/client-errors/` (`apps/logging/client_errors.py`, 30/h par IP) ← `ErrorBoundary` du front ; rangées dans `ErrorLog` (console `/logs`), regroupées par message. Le front refuse au build tout `import.meta` restant (l'obfuscation le casse en production : page blanche du 10/10/2026, `scripts/check-build.mjs`).
- **Images dans les contenus** : uploadées via `POST /api/files/upload/` (S3 : `media/uploads/content/YYYY/MM/uuid_nom`), et le HTML embarque l'URL **stable** `download_url` (les URLs S3 présignées expirent en 1 h).
- **S3** : bucket privé `fidni-media-512768499268` (eu-west-3), endpoint régional forcé (le global 307-redirect casse les signatures).
- Le front (fidni.fr) appelle `https://api.fidni.fr` = tunnel Cloudflare → ce conteneur (port local 8080).

## Infra

- **RDS** : `database-1...eu-west-3.rds.amazonaws.com` / db `fidni` — mot de passe via Secrets Manager (ARN dans `.env`).
- **Tunnel** : cloudflared sur l'hôte → `localhost:8080`. Le conteneur n'expose rien publiquement.
- ⚠️ TODO sécurité : security group RDS encore ouvert (0.0.0.0/0) — à restreindre au port 5432 + IP.
