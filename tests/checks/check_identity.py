"""Identité obligatoire + établissements : vérification sur SQLite jetable."""
import os
import tempfile
import sys
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-identity.sqlite3')
os.environ.update({
    'DJANGO_SETTINGS_MODULE': 'config.settings',
    'DJANGO_ENV': 'development',
    'DB_ENGINE': 'sqlite',
    'SQLITE_PATH': DB,
    'AWS_STORAGE_ENABLED': 'false',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
})
if os.path.exists(DB):
    os.remove(DB)

import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
t = time.time()
call_command('migrate', verbosity=0)
print(f'migrations : {time.time() - t:.1f} s')

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import School  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    c = APIClient(HTTP_CF_CONNECTING_IP='1.1.1.1')
    if user:
        c.force_authenticate(user)
    return c


check('établissements chargés', School.objects.count() > 10000, School.objects.count())
anon = client()
r = anon.get('/api/schools/', {'q': 'moutanabi agadir'})
check('recherche « moutanabi agadir »', r.status_code == 200 and r.data and 'Moutanabi' in r.data[0]['name']
      and r.data[0]['city'] == 'Agadir', r.data[:2] if r.status_code == 200 else r.status_code)
r = anon.get('/api/schools/', {'q': 'lycee ibn sina'})
check('recherche sans accents (« lycee »)', r.status_code == 200 and len(r.data) > 0, r.data[:1])
check('… lycées en premier', r.data and r.data[0]['kind'] in ('lycee', 'cpge'), [x['kind'] for x in r.data[:3]])
r = anon.get('/api/schools/', {'q': 'المتنبي'})
check('recherche en arabe', r.status_code == 200 and len(r.data) > 0, r.status_code)
r = anon.get('/api/schools/', {'q': 'a'})
check('requête trop courte → vide', r.status_code == 200 and r.data == [])
check('12 résultats au plus', len(anon.get('/api/schools/', {'q': 'college'}).data) == 12)

u = User.objects.create_user('sami', 'sami@exemple.fr', 'Motdepasse-solide-42')
c = client(u)
r = c.post('/api/onboarding/', {'user_type': 'student'}, format='json')
check('onboarding sans identité refusé', r.status_code == 400 and r.data.get('code') == 'identity', r.data)
u.profile.refresh_from_db()
check('… onboarding non validé', not u.profile.onboarding_completed)
r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Sami', 'last_name': '12345',
                                'school_name': 'Lycée X'}, format='json')
check('nom avec chiffres refusé', r.status_code == 400, r.data)
school = School.objects.filter(kind='lycee').first()
r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Sami', 'last_name': 'El Idrissi',
                                'school_id': school.id}, format='json')
check('onboarding sans civilité refusé', r.status_code == 400 and 'civilité' in r.data.get('error', ''), r.data)
r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Sami', 'last_name': 'El Idrissi',
                                'school_id': school.id, 'gender': 'X'}, format='json')
check('sexe invalide refusé', r.status_code == 400, r.data)
r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Sami', 'last_name': 'El Idrissi',
                                'school_id': school.id, 'gender': 'm'}, format='json')
check('onboarding sans date de naissance refusé', r.status_code == 400 and 'naissance' in r.data.get('error', ''), r.data)
for bad in ('2099-01-01', '1900-05-05', '31/12/2008', '2024-02-30'):
    r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Sami', 'last_name': 'El Idrissi',
                                    'school_id': school.id, 'gender': 'm', 'birth_date': bad}, format='json')
    check(f'date de naissance invalide refusée ({bad})', r.status_code == 400 and 'naissance' in r.data.get('error', ''), r.data)
r = c.post('/api/onboarding/', {'user_type': 'student', 'first_name': '  Sami ', 'last_name': 'El Idrissi',
                                'school_id': school.id, 'gender': 'm', 'birth_date': '2009-03-14'}, format='json')
check('onboarding complet accepté', r.status_code == 200, r.data)
u.refresh_from_db()
u.profile.refresh_from_db()
check('… prénom nettoyé', u.first_name == 'Sami', repr(u.first_name))
check('… établissement lié', u.profile.school_id == school.id and u.profile.school_name == school.name)
check('… civilité enregistrée (normalisée en M)', u.profile.gender == 'M', u.profile.gender)
check('… date de naissance enregistrée', str(u.profile.birth_date) == '2009-03-14', u.profile.birth_date)

r = c.get('/api/auth/user/')
check('le compte voit ses nom/prénom/établissement',
      r.data.get('first_name') == 'Sami' and r.data['profile']['school']['id'] == school.id, r.data.get('first_name'))
other = client(User.objects.create_user('curieux', 'c@exemple.fr', 'Motdepasse-solide-42'))
r = other.get('/api/users/sami/')
check('un autre compte ne voit ni le nom ni l’établissement',
      r.status_code == 200 and 'first_name' not in r.data and 'school_name' not in r.data.get('profile', {})
      and 'gender' not in r.data.get('profile', {}) and 'birth_date' not in r.data.get('profile', {}),
      (r.status_code, list(r.data.get('profile', {}).keys())[:5] if r.status_code == 200 else ''))

r = c.patch('/api/auth/user/update/', {'birth_date': '2008-11-02'}, format='json')
u.profile.refresh_from_db()
check('date de naissance modifiable', r.status_code == 200 and str(u.profile.birth_date) == '2008-11-02', r.data)
r = c.patch('/api/auth/user/update/', {'birth_date': ''}, format='json')
u.profile.refresh_from_db()
check('date de naissance non effaçable', r.status_code == 400 and str(u.profile.birth_date) == '2008-11-02', r.data)
r = c.get('/api/auth/user/')
check('le compte voit sa date de naissance', r.data['profile'].get('birth_date') == '2008-11-02', r.data['profile'].get('birth_date'))
r = c.patch('/api/auth/user/update/', {'gender': 'F'}, format='json')
u.profile.refresh_from_db()
check('sexe modifiable', r.status_code == 200 and u.profile.gender == 'F', r.data)
r = c.patch('/api/auth/user/update/', {'gender': ''}, format='json')
check('sexe impossible à vider', r.status_code == 400, r.status_code)
r = c.patch('/api/auth/user/update/', {'last_name': ''}, format='json')
check('nom impossible à vider', r.status_code == 400, r.data)
r = c.patch('/api/auth/user/update/', {'school_name': 'Groupe scolaire Les Orangers', 'school_id': ''}, format='json')
u.profile.refresh_from_db()
check('établissement hors liste (texte libre)', r.status_code == 200 and u.profile.school is None
      and u.profile.school_name == 'Groupe scolaire Les Orangers', r.data)
r = c.patch('/api/auth/user/update/', {'school_id': 999999}, format='json')
check('établissement inexistant refusé', r.status_code == 400)
r = c.patch('/api/users/me/', {'profile': {'school_name': 'Pirate'}}, format='json')
u.profile.refresh_from_db()
check('école non modifiable par /users/me/ (contournement)', u.profile.school_name == 'Groupe scolaire Les Orangers',
      (r.status_code, u.profile.school_name))
r = c.patch('/api/auth/user/update/', {'first_name': 'Aïcha-Zineb', 'last_name': "O'Neil"}, format='json')
check('accents, tirets et apostrophes acceptés', r.status_code == 200, r.data)
r = c.patch('/api/auth/user/update/', {'first_name': 'سامي'}, format='json')
check('prénom en arabe accepté', r.status_code == 200, r.data)

# Page « Modifier mon profil » : présentation publique et objectifs de notes privés.
from apps.caracteristics.models import Subject  # noqa: E402
maths = Subject.objects.create(name='Mathématiques (test)')
r = c.patch('/api/users/me/', {'profile': {'bio': 'Je vise une mention.', 'location': 'Fès',
                                           'subject_grades': [{'subject': maths.id, 'min_grade': 11.5, 'max_grade': 16}]}},
            format='json')
u.profile.refresh_from_db()
check('présentation et objectif enregistrés', r.status_code == 200 and u.profile.bio == 'Je vise une mention.'
      and u.profile.subject_grades.count() == 1 and float(u.profile.subject_grades.get().max_grade) == 16, r.data)
r = c.patch('/api/users/me/', {'profile': {'subject_grades': [{'subject': maths.id, 'min_grade': 12, 'max_grade': 25}]}},
            format='json')
check('objectif au-delà de 20 refusé', r.status_code == 400 and float(u.profile.subject_grades.get().max_grade) == 16,
      (r.status_code, r.data))
r = c.patch('/api/users/me/', {'profile': {'subject_grades': []}}, format='json')
check('retirer tous ses objectifs les supprime', r.status_code == 200 and u.profile.subject_grades.count() == 0, r.data)
r = APIClient().get(f'/api/users/{u.username}/')
check('objectifs de notes invisibles des visiteurs', 'subject_grades' not in (r.data.get('profile') or {}), r.data)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
