# Description de Projet CV - Fidni Backend

## Version Courte (pour CV)

**Développeur Backend - Plateforme Éducative Fidni**

Conception et développement d'une API REST complète pour une plateforme d'apprentissage en ligne utilisant Django et PostgreSQL. Mise en œuvre d'un système de parcours d'apprentissage structuré avec suivi de progression granulaire, gestion de notebooks numériques avec annotations riches, et système d'interactions sociales (votes, commentaires, listes de révision). Implémentation d'une architecture modulaire avec 7 applications Django, authentification JWT, système de tracking temporel des sessions d'étude, et déploiement conteneurisé sur AWS.

**Technologies :** Python, Django 5.0, Django REST Framework, PostgreSQL, JWT, Docker, Redis, Nginx, AWS ECR, Gunicorn

---

## Version Détaillée (pour présentation portfolio)

**Développeur Backend Full-Stack - Plateforme Éducative Fidni**
*Projet personnel / Startup*

### Vue d'ensemble
Développement complet du backend d'une plateforme éducative interactive destinée aux étudiants et enseignants, permettant la gestion de contenu pédagogique, le suivi de progression, et la collaboration.

### Réalisations principales

**1. Architecture & Infrastructure**
- Conception d'une architecture modulaire basée sur 7 applications Django interconnectées
- Mise en place d'une API RESTful complète avec Django REST Framework
- Configuration d'un système d'authentification JWT avec gestion de sessions
- Déploiement conteneurisé avec Docker, Nginx, et orchestration AWS ECR
- Configuration d'environnements multiples (dev, test, production) avec variables d'environnement

**2. Système de Parcours d'Apprentissage**
- Développement d'un système hiérarchique : Parcours → Chapitres → Vidéos → Quiz
- Implémentation d'un tracking de progression multi-niveaux (parcours, chapitres, vidéos)
- Création d'un système de quiz interactif avec plusieurs types de questions (QCM, vrai/faux, choix multiples)
- Gestion des ressources vidéo avec matériaux supplémentaires (PDF, slides, exercices)
- Calcul automatique de progression avec pourcentages et scores de quiz

**3. Gestion de Contenu Pédagogique**
- Système complet de gestion d'exercices, leçons, et examens avec niveaux de difficulté
- Recherche intelligente avec fuzzy matching utilisant les trigrammes PostgreSQL
- Système de commentaires hiérarchiques avec réponses imbriquées
- Gestion de solutions avec système de vote communautaire
- Intégration d'examens nationaux avec tracking par année

**4. Notebooks Numériques & Annotations**
- Développement d'un système de notebooks personnels par matière et niveau
- Implémentation d'annotations riches (surlignage, notes, dessins SVG)
- Gestion de sections et entrées de leçons avec pagination
- Tracking de position et couleurs pour les annotations
- Liaison bidirectionnelle entre leçons et notebooks

**5. Système d'Interactions Sociales**
- Système de vote générique (upvote/downvote) applicable à plusieurs types de contenu
- Fonctionnalité de sauvegarde/bookmarking de contenu
- Listes de révision personnalisables avec notes
- Système d'évaluation de difficulté (1-5 étoiles)
- Système de signalement de contenu inapproprié

**6. Analytics & Suivi de Performance**
- Tracking détaillé du temps d'étude par session avec types d'activité (study, review, practice, exam)
- Statistiques utilisateur : contributions, contenu complété, sujets étudiés
- Dashboard avec statistiques d'apprentissage et recommandations personnalisées
- Historique de visualisation avec statuts de complétion
- Calcul de temps total et par session sur chaque contenu

**7. Gestion Utilisateurs & Onboarding**
- Système de profils avec types utilisateur (Étudiant/Enseignant)
- Processus d'onboarding avec sélection de niveau de classe et matières cibles
- Gestion de préférences de notification (email, commentaires, solutions)
- Tracking de notes par matière (min/max)
- Localisation et personnalisation de profil (bio, avatar)

**8. Optimisations & Sécurité**
- Utilisation de transactions atomiques pour la cohérence des données
- Système de permissions granulaire pour opérations CRUD
- Hashing de mots de passe avec Argon2
- Configuration CORS pour sécurité cross-origin
- Pagination standardisée pour performance sur grands datasets
- Optimisation de requêtes avec select_related et prefetch_related

### Technologies utilisées

**Backend & API**
- Python 3.x
- Django 5.0.1
- Django REST Framework 3.14.0
- FastAPI (endpoints spécifiques)
- Pydantic pour validation

**Base de données**
- PostgreSQL (production)
- SQLite (développement)
- SQLAlchemy (ORM additionnel)

**Authentification & Sécurité**
- djangorestframework-simplejwt
- JWT tokens
- Argon2-cffi (hashing)
- Django CORS Headers

**Infrastructure & Déploiement**
- Docker (containerisation)
- Nginx (reverse proxy)
- Gunicorn/Uvicorn (WSGI/ASGI)
- WhiteNoise (fichiers statiques)
- AWS ECR (registry)
- Redis (caching)

**Outils & Librairies**
- django-environ (variables d'environnement)
- Pillow (traitement images)
- FPDF (génération PDF)
- python-dotenv
- PostgreSQL extensions (trigrammes)

### Métriques du projet
- 7 applications Django interconnectées
- 50+ modèles de données
- 30+ endpoints API RESTful
- Support de relations génériques pour flexibilité
- Architecture scalable et maintenable

---

## Version LinkedIn / Portfolio Web

Développement complet du backend d'une plateforme éducative moderne permettant aux étudiants de suivre des parcours d'apprentissage structurés, de gérer des notebooks numériques, et de collaborer sur des exercices.

Principales réalisations :
✓ API REST complète avec Django & PostgreSQL servant 30+ endpoints
✓ Système de parcours d'apprentissage avec tracking multi-niveaux de progression
✓ Notebooks numériques avec annotations riches (SVG, surlignage, notes)
✓ Analytics détaillées avec tracking temporel des sessions d'étude
✓ Architecture modulaire avec 7 applications Django et 50+ modèles
✓ Déploiement conteneurisé (Docker, Nginx, AWS ECR)
✓ Authentification JWT sécurisée avec Argon2

Stack technique : Python • Django 5.0 • DRF • PostgreSQL • Redis • Docker • AWS • JWT

---

## Bullet Points pour CV (format court)

**Backend Developer - Fidni Educational Platform**

• Développé une API REST complète avec Django 5.0 et PostgreSQL pour plateforme d'apprentissage en ligne
• Implémenté un système de parcours d'apprentissage avec tracking de progression multi-niveaux (parcours, chapitres, vidéos, quiz)
• Créé un système de notebooks numériques avec annotations riches et gestion de contenu pédagogique (exercices, leçons, examens)
• Développé un système d'interactions sociales (votes, commentaires, listes de révision) avec relations génériques
• Mis en place analytics détaillées avec tracking temporel des sessions d'étude et statistiques d'apprentissage
• Configuré authentification JWT sécurisée et système de permissions granulaire
• Déployé l'application via Docker/Nginx sur AWS avec environnements multiples (dev, test, prod)
• Optimisé performances avec recherche fuzzy (trigrammes PostgreSQL) et pagination

**Technologies :** Python, Django 5.0, Django REST Framework, PostgreSQL, JWT, Docker, Redis, Nginx, AWS ECR
