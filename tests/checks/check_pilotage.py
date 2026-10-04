"""Tableau de bord d'administration (/api/pilotage/) : droits d'accès et chiffres exacts sur des données connues."""
import os
import sys
import tempfile
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-pilotage.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
import runpy  # noqa: E402
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
from apps.things.models import Comment, Content  # noqa: E402
from apps.users.models import ViewHistory  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


now = timezone.now()
level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
ct = ContentType.objects.get_for_model(Content)

admin = User.objects.create_superuser('admin', 'admin@x.fr', 'Motdepasse-solide-42')
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42', first_name='Alice', last_name='Benali')
bob = User.objects.create_user('bob', 'bob@x.fr', 'Motdepasse-solide-42')
carla = User.objects.create_user('carla', 'carla@x.fr', 'Motdepasse-solide-42')   # inscrite il y a 40 jours, jamais active
prof = User.objects.create_user('prof', 'prof@x.fr', 'Motdepasse-solide-42')
User.objects.filter(pk=carla.pk).update(date_joined=now - timedelta(days=40))
User.objects.filter(pk=bob.pk).update(date_joined=now - timedelta(days=12))
for u, lv in ((alice, level), (bob, level)):
    u.profile.class_level = lv
    u.profile.save()
alice.profile.birth_date = date.today().replace(year=date.today().year - 13)
alice.profile.school_name = 'Lycée Test'
alice.profile.save()
prof.profile.user_type = 'teacher'
prof.profile.save()

ex = Content.objects.create(type='exercise', title='Exercice suivi', author=editorial, subject=subject,
                            json_content={'version': '2.1', 'blocks': []})
ex.class_levels.add(level)
# alice : consulte, termine et évalue aujourd'hui ; bob : consulte il y a 3 jours ; admin : actif (exclu)
ViewHistory.objects.create(user=alice, content_type=ct, object_id=ex.id)
Complete.objects.create(user=alice, content_type=ct, object_id=str(ex.id), status='success')
QuestionProgress.objects.create(user=alice, content_type=ct, object_id=ex.id, question_path='q1', status='success')
v = ViewHistory.objects.create(user=bob, content_type=ct, object_id=ex.id)
ViewHistory.objects.filter(pk=v.pk).update(viewed_at=now - timedelta(days=3))
ViewHistory.objects.create(user=admin, content_type=ct, object_id=ex.id)
Comment.objects.create(content_item=ex, author=alice, content='Merci !')

c = APIClient()
r = c.get('/api/pilotage/')
check('anonyme refusé', r.status_code in (401, 403), r.status_code)
c.force_authenticate(alice)
check('élève refusé', c.get('/api/pilotage/').status_code == 403)
check('élève refusé (liste)', c.get('/api/pilotage/utilisateurs/').status_code == 403)
c.force_authenticate(admin)
r = c.get('/api/pilotage/')
check('administrateur autorisé', r.status_code == 200, r.status_code)
d = r.data
us = d['users']
check('inscrits réels : 4 (admin et compte éditorial exclus)', us['total'] == 4, us)
check('1 enseignant, 3 élèves', us['teachers'] == 1 and us['students'] == 3, us)
check('nouveaux : 3 sur 7 jours, 3 sur 30 jours', us['new_7d'] == 2 and us['new_30d'] == 3, us)
check('actifs : 1 aujourd’hui, 2 sur 7 jours (admin exclu)', us['active_1d'] == 1 and us['active_7d'] == 2, us)
check('jamais actifs : carla et prof', us['never_active'] == 2, us)
check('moins de 15 ans : 1', us['under_15'] == 1, us)
eng = d['engagement_30d']
check('engagement : 2 consultations, 1 terminé, 1 question, 1 commentaire (admin exclu)',
      eng['views'] == 2 and eng['completions'] == 1 and eng['questions_assessed'] == 1 and eng['comments'] == 1, eng)
check('courbes sur 30 jours', len(d['series']) == 30 and d['series'][-1]['active'] == 1, d['series'][-1])
check('inscriptions du jour dans la courbe', d['series'][-1]['signups'] == 2, d['series'][-1])
check('contenu le plus consulté : 2 élèves distincts', d['top_contents'] and d['top_contents'][0]['readers'] == 2
      and d['top_contents'][0]['url'] == f'/exercises/{ex.id}', d['top_contents'])
check('niveaux : 2ème Bac SM compte 2 élèves', any(x['name'] == '2ème Bac SM' and x['count'] == 2 for x in d['levels']), d['levels'])
check('établissements', d['schools'] == [{'name': 'Lycée Test', 'count': 1}], d['schools'])
kinds = [e['kind'] for e in d['recent_activity']]
check('fil d’activité : inscription, consultation, terminé, commentaire',
      {'signup', 'view', 'complete', 'comment'} <= set(kinds), kinds)
check('fil d’activité sans les comptes maison', all(e['username'] not in ('admin', 'Fidni') for e in d['recent_activity']))

r = c.get('/api/pilotage/utilisateurs/')
names = [x['username'] for x in r.data['results']]
check('liste : tous les comptes (maison signalés)', r.data['count'] == 6 and 'admin' in names, names)
check('comptes maison marqués', all(x['is_house'] == (x['username'] in ('admin', 'Fidni')) for x in r.data['results']))
row = next(x for x in r.data['results'] if x['username'] == 'alice')
check('ligne alice : nom, niveau, établissement, activité', row['full_name'] == 'Alice Benali' and row['class_level'] == '2ème Bac SM'
      and row['school'] == 'Lycée Test' and row['stats']['views'] == 1 and row['stats']['completions'] == 1
      and row['stats']['comments'] == 1 and row['last_activity'], row)
check('recherche par nom de famille', [x['username'] for x in c.get('/api/pilotage/utilisateurs/?q=benali').data['results']] == ['alice'])
check('filtre enseignants', [x['username'] for x in c.get('/api/pilotage/utilisateurs/?type=teacher').data['results']] == ['prof'])
act = [x['username'] for x in c.get('/api/pilotage/utilisateurs/?tri=activite').data['results']]
check('tri par dernière activité', act.index('alice') < act.index('bob') < act.index('carla'), act)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
