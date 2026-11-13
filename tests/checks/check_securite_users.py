"""Sécurité des APIs utilisateurs (09/11/2026), sur une base SQLite jetable.

Trois garanties vérifiées :
1. Minimisation : la fiche /api/users/<username>/ reste lisible (profils publics), mais un tiers
   (visiteur anonyme ou autre membre) ne récupère QUE le minimum public (pseudo, avatar). Jamais
   l'e-mail, le nom, le prénom, le niveau de classe, les matières, l'activité, les statistiques
   d'apprentissage ni les objectifs. Le propriétaire et un superuser, eux, voient tout.
2. Ressources privées : les sous-ressources personnelles (exercices enregistrés, historique,
   progression, study-stats, statistiques non partagées) restent refusées aux tiers (403).
3. Écritures (IDOR) : personne ne peut modifier ni supprimer la ressource d'un autre.
"""
import os
import runpy
import sys
import tempfile
from datetime import date

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-securite-users.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.things.models import Comment, Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(u=None):
    c = APIClient(HTTP_CF_CONNECTING_IP='9.9.9.9')
    if u:
        c.force_authenticate(u)
    return c


pw = 'Motdepasse-solide-42'
niveau = ClassLevel.objects.create(name='2ème Bac SM S', order=970)
matiere = Subject.objects.create(name='Maths S')

# Le propriétaire : des données personnelles bien réelles à protéger.
cible = User.objects.create_user('cible', 'cible@secret.fr', pw, first_name='Yassine', last_name='Alaoui')
cible.profile.class_level = niveau
cible.profile.birth_date = date(2008, 5, 1)
cible.profile.location = 'Casablanca'
cible.profile.display_email = False
cible.profile.display_stats = False   # ne partage pas ses statistiques publiquement
cible.profile.save()
cible.profile.target_subjects.set([matiere])

autre = User.objects.create_user('autre', 'autre@x.fr', pw)      # un membre quelconque
root = User.objects.create_user('root', 'root@x.fr', pw, is_superuser=True, is_staff=True)

exo = Content.objects.create(type='exercise', title='Exercice de cible', author=cible, subject=matiere, json_content={})

# Ce qu'un tiers ne doit JAMAIS obtenir par /api/users/
SENSIBLES_RACINE = ('email', 'first_name', 'last_name', 'is_superuser')
SENSIBLES_PROFIL = ('class_level', 'class_level_name', 'learning_stats', 'contribution_stats',
                    'last_activity_date', 'target_subjects', 'target_subject_names',
                    'subject_grades', 'school', 'school_name', 'gender', 'birth_date', 'teacher_code')

print('--- 1. La fiche reste lisible (profils publics), mais minimisée pour les tiers')
for nom, cli in [('visiteur anonyme', client()), ('autre membre', client(autre))]:
    r = cli.get('/api/users/cible/')
    check(f'{nom} : fiche accessible (200)', r.status_code == 200, r.status_code)
    d = r.json()
    prof = d.get('profile') or {}
    fuite_racine = [k for k in SENSIBLES_RACINE if k in d]
    fuite_profil = [k for k in SENSIBLES_PROFIL if k in prof]
    check(f'{nom} : aucune donnée sensible à la racine', not fuite_racine, fuite_racine)
    check(f'{nom} : aucune donnée sensible dans le profil (niveau, stats, activité, objectifs)',
          not fuite_profil, fuite_profil)
    check(f'{nom} : garde le minimum public (pseudo + avatar)',
          d.get('username') == 'cible' and 'avatar' in prof, list(prof))

print('--- 2. Le propriétaire et le superuser voient tout')
mes = client(cible).get('/api/users/cible/').json()
mes_prof = mes.get('profile') or {}
check('propriétaire : son e-mail lui est renvoyé', mes.get('email') == 'cible@secret.fr', mes.get('email'))
check('propriétaire : niveau et statistiques présents',
      mes_prof.get('class_level') is not None and 'learning_stats' in mes_prof, list(mes_prof.keys()))
adm = client(root).get('/api/users/cible/').json()
check('superuser : voit l’e-mail du membre (modération)', adm.get('email') == 'cible@secret.fr', adm.get('email'))
check('superuser : voit le niveau de classe', (adm.get('profile') or {}).get('class_level') is not None)

print('--- 3. Les sous-ressources personnelles restent fermées aux tiers')
for sous in ('saved_exercises', 'saved_lessons', 'saved_exams', 'history', 'success_thing', 'review_thing'):
    check(f'{sous} : autre membre refusé (403)', client(autre).get(f'/api/users/cible/{sous}/').status_code == 403,
          client(autre).get(f'/api/users/cible/{sous}/').status_code)
check('study-stats : autre membre refusé (403)', client(autre).get('/api/users/cible/study-stats/').status_code == 403)
check('statistiques : fermées à un tiers quand le membre ne les partage pas (403)',
      client(autre).get('/api/users/cible/stats/').status_code == 403,
      client(autre).get('/api/users/cible/stats/').status_code)
check('exercices enregistrés : propriétaire autorisé', client(cible).get('/api/users/cible/saved_exercises/').status_code == 200)

print('--- 4. Surface publique : l’auteur d’un contenu ne divulgue aucune donnée personnelle')
detail = client().get(f'/api/contents/{exo.id}/')
check('contenu lisible publiquement', detail.status_code == 200, detail.status_code)
auteur = detail.json().get('author', {})
check('auteur : le pseudo est présent', auteur.get('username') == 'cible', auteur)
FUITES = ('email', 'first_name', 'last_name', 'birth_date', 'location', 'school', 'school_name',
          'gender', 'class_level', 'is_superuser', 'is_staff', 'password')
check('auteur : aucune donnée personnelle', not [k for k in FUITES if k in auteur], [k for k in FUITES if k in auteur])
check('auteur : uniquement id/username/display_name/avatar/is_deleted',
      set(auteur.keys()) <= {'id', 'username', 'display_name', 'avatar', 'is_deleted'}, list(auteur.keys()))

print('--- 5. Écritures : pas d’action sur la ressource d’un autre (IDOR)')
check('autre membre ne peut PAS supprimer le contenu de cible (403)',
      client(autre).delete(f'/api/contents/{exo.id}/').status_code == 403,
      client(autre).delete(f'/api/contents/{exo.id}/').status_code)
check('autre membre ne peut PAS modifier le contenu de cible (403)',
      client(autre).patch(f'/api/contents/{exo.id}/', {'title': 'piraté'}, format='json').status_code == 403)
check('visiteur anonyme ne peut PAS supprimer le contenu (401/403)',
      client().delete(f'/api/contents/{exo.id}/').status_code in (401, 403))

com = Comment.objects.create(content_item=exo, author=cible, content='Mon commentaire')
check('autre membre ne peut PAS supprimer le commentaire de cible (403)',
      client(autre).delete(f'/api/comments/{com.id}/').status_code == 403,
      client(autre).delete(f'/api/comments/{com.id}/').status_code)
check('autre membre ne peut PAS modifier la fiche d’un autre (403)',
      client(autre).patch('/api/users/cible/', {'first_name': 'Pirate'}, format='json').status_code == 403,
      client(autre).patch('/api/users/cible/', {'first_name': 'Pirate'}, format='json').status_code)
check('la ressource visée est intacte',
      Content.objects.filter(id=exo.id).exists() and Comment.objects.filter(id=com.id).exists()
      and User.objects.get(id=cible.id).first_name == 'Yassine')

total = len(results)
reussis = sum(results)
print(f'\n{reussis}/{total} vérifications réussies')
sys.exit(0 if reussis == total else 1)
