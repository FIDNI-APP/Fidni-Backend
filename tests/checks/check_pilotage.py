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
from apps.things.models import Comment, Content, ContentDailyView, ContentReport  # noqa: E402
from apps.users.admin_dashboard import VIEWS_SINCE  # noqa: E402
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
ex2 = Content.objects.create(type='exercise', title='Corrigé à relire', author=editorial, subject=subject,
                             json_content={'version': '2.1', 'blocks': [], 'a_verifier': True})
ex2.class_levels.add(level)
today = timezone.localdate()
ContentDailyView.objects.create(content=ex, date=today, count=5)
ContentDailyView.objects.create(content=ex2, date=today, count=2)
ContentReport.objects.create(content=ex, user=alice, reason='typo')

c = APIClient()
r = c.get('/api/pilotage/')
check('anonyme refusé', r.status_code in (401, 403), r.status_code)
c.force_authenticate(alice)
check('élève refusé', c.get('/api/pilotage/').status_code == 403)
check('élève refusé (liste)', c.get('/api/pilotage/utilisateurs/').status_code == 403)
check('élève refusé (fiche)', c.get(f'/api/pilotage/utilisateurs/{bob.id}/').status_code == 403)
c.force_authenticate(admin)
r = c.get('/api/pilotage/?jours=30')
check('administrateur autorisé', r.status_code == 200, r.status_code)
d = r.data
check('période inconnue → 30 jours', c.get('/api/pilotage/?jours=12').data['days'] == 30)
check('membres réels : 4 (admin et compte éditorial exclus)', d['members_total'] == 4, d['members_total'])
m = d['metrics']
check('actifs sur 30 j : alice et bob (admin exclu)', m['active']['value'] == 2, m['active'])
check('inscriptions : 3 sur 30 j, carla dans les 30 j d’avant', m['signups'] == {'value': 3, 'previous': 1}, m['signups'])
check('travail : 1 contenu terminé + 1 question', m['work']['value'] == 2, m['work'])
check('vues du jour, visiteurs compris : 7', m['views']['value'] == 7, m['views'])
s = d['series']
check('courbe : 30 jours, aujourd’hui en dernier', len(s) == 30 and s[-1]['date'] == today.isoformat()
      and s[-1]['active'] == 1 and s[-1]['signups'] == 2 and s[-1]['views'] == 7, s[-1])
check('jours d’avant la mesure des vues : vides', all(x['views'] is None for x in s if x['date'] < VIEWS_SINCE.isoformat()))
d7 = c.get('/api/pilotage/?jours=7').data
check('7 jours : 2 actifs, 2 inscriptions (bob la semaine d’avant)', d7['metrics']['active']['value'] == 2
      and d7['metrics']['signups'] == {'value': 2, 'previous': 1} and len(d7['series']) == 7, d7['metrics'])
top = d['top_contents']
check('contenus les plus vus : vues puis membres distincts', top and top[0]['id'] == ex.id and top[0]['views'] == 5
      and top[0]['readers'] == 2 and top[0]['url'] == f'/exercises/{ex.id}' and top[1]['id'] == ex2.id, top)
check('à traiter : 1 signalement, 1 correction à vérifier', d['todo']['reports_open'] == 1
      and [x['id'] for x in d['todo']['a_verifier']] == [ex2.id], d['todo'])
r = c.post(f'/api/contents/{ex2.id}/verification/', {'verifie': True}, format='json')
check('correction validée : sort de la liste', r.status_code == 200 and c.get('/api/pilotage/').data['todo']['a_verifier'] == [])

r = c.get('/api/pilotage/utilisateurs/')
names = [x['username'] for x in r.data['results']]
check('liste : tous les comptes (maison signalés)', r.data['count'] == 6 and 'admin' in names, names)
check('comptes maison marqués', all(x['is_house'] == (x['username'] in ('admin', 'Fidni')) for x in r.data['results']))
row = next(x for x in r.data['results'] if x['username'] == 'alice')
check('ligne alice : nom, niveau, établissement, activité', row['full_name'] == 'Alice Benali' and row['class_level'] == '2ème Bac SM'
      and row['school'] == 'Lycée Test' and row['stats']['views'] == 1 and row['stats']['completions'] == 1
      and row['stats']['comments'] == 1 and row['last_activity'], row)
check('recherche par nom de famille', [x['username'] for x in c.get('/api/pilotage/utilisateurs/?q=benali').data['results']] == ['alice'])
act = [x['username'] for x in c.get('/api/pilotage/utilisateurs/?tri=activite').data['results']]
check('tri par dernière activité', act.index('alice') < act.index('bob') < act.index('carla'), act)
cnt = c.get('/api/pilotage/utilisateurs/?jours=7').data['counts']
check('pastilles : effectifs par filtre', cnt == {'tous': 6, 'actifs': 2, 'nouveaux': 2, 'jamais': 2, 'enseignants': 1}, cnt)


def who(params):
    return sorted(x['username'] for x in c.get(f'/api/pilotage/utilisateurs/?{params}').data['results'])


check('filtre actifs (7 j)', who('filtre=actifs&jours=7') == ['alice', 'bob'], who('filtre=actifs&jours=7'))
check('filtre nouveaux (7 j)', who('filtre=nouveaux&jours=7') == ['alice', 'prof'], who('filtre=nouveaux&jours=7'))
check('filtre jamais actifs', who('filtre=jamais') == ['carla', 'prof'], who('filtre=jamais'))
check('filtre enseignants', who('filtre=enseignants') == ['prof'])
check('filtre + recherche', who('filtre=actifs&q=bob') == ['bob'])
r = c.get(f'/api/pilotage/utilisateurs/{alice.id}/')
kinds = {e['kind'] for e in r.data['activity']}
check('fiche membre : dernières actions', r.status_code == 200 and {'signup', 'view', 'complete', 'comment'} <= kinds, kinds)
check('fiche membre : compte inconnu → 404', c.get('/api/pilotage/utilisateurs/999999/').status_code == 404)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
