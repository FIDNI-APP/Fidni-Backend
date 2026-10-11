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
from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay  # noqa: E402
from apps.things.models import Comment, Content, ContentDailyView, ContentReport  # noqa: E402
from apps.users.admin_dashboard import VIEWS_SINCE, _active_days  # noqa: E402
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
# Jour actif = date stable : son temps d'étude ce jour-là (la date de consultation, elle, est écrasée à chaque passage).
StudyTimeDay.objects.create(user=bob, object_id=ex.id, date=timezone.localdate() - timedelta(days=3), seconds=240)
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


# ── Audit du 10/10/2026 : entonnoir, portes d'inscription, nouvelles fonctionnalités, écarts de difficulté
from apps.concours.models import SimulationSession  # noqa: E402
from apps.interactions.models import RevisionList, SolutionView, UpcomingTest  # noqa: E402
from apps.notebooks.models import NotebookAnnotation  # noqa: E402
from apps.things.models import CatchUpSkip, DifficultyFeedback  # noqa: E402
from apps.users.models import UsageDaily  # noqa: E402

f30 = c.get('/api/pilotage/?jours=30').data['funnel']
check('entonnoir : cohorte des 30 j (alice, bob, prof ; carla trop ancienne, admin exclu)',
      f30 == {'signups': 3, 'verified': 3, 'onboarded': 0, 'first_view': 2, 'first_work': 1, 'back_d7': 1,
              'd7_eligible': 1}, f30)
# emma : inscrite il y a 20 jours, e-mail jamais confirmé ; fares : profil complété, a travaillé le lendemain
# de son inscription puis a seulement réévalué la même question aujourd'hui (assessed_at bouge, created_at non).
emma = User.objects.create_user('emma', 'emma@x.fr', 'Motdepasse-solide-42', is_active=False)
emma.profile.email_verified = False
emma.profile.save()
fares = User.objects.create_user('fares', 'fares@x.fr', 'Motdepasse-solide-42')
fares.profile.onboarding_completed = True
fares.profile.save()
User.objects.filter(pk=emma.pk).update(date_joined=now - timedelta(days=20))
User.objects.filter(pk=fares.pk).update(date_joined=now - timedelta(days=15))
qp = QuestionProgress.objects.create(user=fares, content_type=ct, object_id=ex.id, question_path='q1', status='review')
QuestionProgress.objects.filter(pk=qp.pk).update(created_at=now - timedelta(days=14))
d = c.get('/api/pilotage/?jours=30').data
check('entonnoir : confirmés, profil complété, 1er travail, retour J7 (dates stables seulement)',
      d['funnel'] == {'signups': 5, 'verified': 4, 'onboarded': 1, 'first_view': 2, 'first_work': 2, 'back_d7': 1,
                      'd7_eligible': 3}, d['funnel'])
by_day = {x['date']: x['active'] for x in d['series']}
check('courbe : la réévaluation d’aujourd’hui ne déplace pas le jour actif de fares',
      by_day[(today - timedelta(days=14)).isoformat()] == 1 and by_day[today.isoformat()] == 1, by_day)
check('entonnoir 7 j : personne n’a encore 7 jours', c.get('/api/pilotage/?jours=7').data['funnel']['d7_eligible'] == 0)

UsageDaily.objects.create(date=today, kind='filtre', name='auth:porte:vote', count=3, visitors=2, anon_count=3, anon_visitors=2)
UsageDaily.objects.create(date=today - timedelta(days=1), kind='filtre', name='auth:porte:bandeau', count=1, visitors=1,
                          anon_count=1, anon_visitors=1)
UsageDaily.objects.create(date=today - timedelta(days=40), kind='filtre', name='auth:porte:vieux', count=9, visitors=9)
UsageDaily.objects.create(date=today, kind='filtre', name='exercise:difficulte:hard', count=1, visitors=1)
d = c.get('/api/pilotage/?jours=30').data
doors = [(x['source'], x['count']) for x in d['auth_doors']]
check('portes d’inscription de la période, la plus utilisée en tête', doors == [('vote', 3), ('bandeau', 1)], d['auth_doors'])
check('portes : pas mêlées aux valeurs des filtres', all(v['filter'] != 'porte' for v in d['filter_values'])
      and len(d['filter_values']) == 1, d['filter_values'])

lesson = Content.objects.create(type='lesson', title='Leçon', author=editorial, subject=subject,
                                json_content={'version': '2.1', 'blocks': []})
for u in (alice, admin):   # admin : compté nulle part
    SimulationSession.objects.create(user=u, mode='random_mix', concours_type='ensa', duration_minutes=60)
    NotebookAnnotation.objects.create(user=u, lesson=lesson, annotation_id='a1', annotation_type='note',
                                      position_x=1, position_y=1)
    RevisionList.objects.create(user=u, name='Pour le DS')
    CatchUpSkip.objects.create(user=u, content=ex)
    UpcomingTest.objects.create(user=u, date=today, grade=14)
    SolutionView.objects.create(user=u, content_type=ct, object_id=ex.id)
    DifficultyFeedback.objects.create(user=u, content=ex, felt='harder', declared='medium')
UpcomingTest.objects.create(user=bob, date=today)   # DS sans note : pas une « note de DS »
gaby = User.objects.create_user('gaby', 'gaby@x.fr', 'Motdepasse-solide-42')   # ne fait que des concours
User.objects.filter(pk=gaby.pk).update(date_joined=now - timedelta(days=60))
SimulationSession.objects.create(user=gaby, mode='random_mix', concours_type='ensa', duration_minutes=60)
d = c.get('/api/pilotage/?jours=30').data
base = {x['key']: x for x in d['features'] if x['source'] == 'base'}
new_keys = ('concours', 'annotation', 'liste_creee', 'pas_encore_fait', 'note_ds', 'solution_vue', 'ressenti')
check('nouvelles fonctionnalités en base : 1 membre, 1 usage chacune (admin exclu)',
      all(base.get(k, {}).get('users') == 1 and base[k]['actions'] == 1 for k in new_keys if k != 'concours')
      and base['concours']['users'] == 2, {k: base.get(k) for k in new_keys})
check('ressenti : en base ET geste du navigateur, rubriques séparées',
      {x['source'] for x in d['features'] if x['key'] == 'ressenti'} == {'base', 'navigateur'})
check('actif grâce à une source ajoutée (gaby : concours seulement)', d['metrics']['active']['value'] == 4
      and _active_days([gaby.id], now - timedelta(days=1)).get(gaby.id) == {today},
      d['metrics']['active'])
gaps = d['todo'].get('difficulty_gaps')
check('à traiter : écarts de difficulté présents (liste)', isinstance(gaps, list), gaps)
# 5 élèves trouvent « plus dur » un exercice annoncé facile : ressenti décalé d'un niveau (things/difficulty.py).
ex3 = Content.objects.create(type='exercise', title='Annoncé facile', difficulty='easy', author=editorial, subject=subject,
                             json_content={'version': '2.1', 'blocks': []})
for i in range(5):
    u = User.objects.create_user(f'avis{i}', f'avis{i}@x.fr', 'Motdepasse-solide-42')
    DifficultyFeedback.objects.create(user=u, content=ex3, felt='harder', declared='easy')
gaps = c.get('/api/pilotage/?jours=30').data['todo']['difficulty_gaps']
g3 = next((g for g in gaps if g['id'] == ex3.id), None)
check('écart de difficulté remonté dans « À traiter »', g3 is not None and g3['declared'] == 'easy'
      and g3['felt'] == 'medium' and g3['votes'].get('harder') == 5 and g3['url'] == f'/exercises/{ex3.id}'
      and g3['edit_url'] == f'/exercises/{ex3.id}/edit', gaps)
check('écarts de difficulté : forme attendue', all({'id', 'type', 'title', 'url', 'declared', 'felt', 'n', 'success_pct',
                                                    'votes'} <= set(g) for g in gaps), gaps)
# Une simple connexion n'est pas une activité datée (la date est écrasée) : « dernière activité » oui, « actifs » non.
User.objects.filter(pk=carla.pk).update(last_login=now)
rows = {x['username']: x for x in c.get('/api/pilotage/utilisateurs/?q=carla').data['results']}
check('connexion seule : dernière activité affichée, pas comptée active',
      rows['carla']['last_activity'] and 'carla' not in who('filtre=actifs&jours=7'), rows.get('carla'))

# Forme de la réponse (10/10/2026) : les nombres que la page affiche ne sont jamais None (seuls les champs
# « pas encore mesuré » / « période d'avant » peuvent l'être), sur chaque période.
NULLABLE = {'previous', 'success_pct', 'votes', 'basis', 'users', 'edit_url',
            'views', 'active', 'signups', 'work', 'anon', 'members', 'anon_pages', 'anon_contents'}


def nones(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v is None and k not in NULLABLE:
                yield f'{path}.{k}'
            yield from nones(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from nones(v, f'{path}[{i}]')


for n in (7, 30, 90):
    d = c.get(f'/api/pilotage/?jours={n}').data
    bad = sorted(set(nones(d)))
    check(f'{n} j : aucun nombre à None hors champs prévus', not bad, bad[:10])
    check(f'{n} j : blocs attendus présents', {'metrics', 'series', 'top_contents', 'features', 'pages', 'filter_values',
                                               'anonymes', 'todo', 'funnel', 'auth_doors'} <= set(d), sorted(d))
    check(f'{n} j : chiffres des métriques entiers', all(isinstance(d['metrics'][k]['value'], int)
                                                         for k in ('views', 'active', 'signups', 'work')), d['metrics'])

# Erreurs d'affichage envoyées par le navigateur (apps/logging/client_errors.py) : rangées dans ErrorLog,
# regroupées par message, ouvertes aux visiteurs, sans exiger de champ sensible.
from apps.logging.models import ErrorLog  # noqa: E402
anon = APIClient()
msg = "TypeError: Cannot read properties of undefined (reading 'DEV')"
r1 = anon.post('/api/logs/client-errors/', {'message': msg, 'stack': 'at trackPage', 'path': '/pilotage'}, format='json')
r2 = c.post('/api/logs/client-errors/', {'message': msg, 'path': '/exercises/3/edit'}, format='json')
rows = ErrorLog.objects.filter(message=msg)
check('erreur d’affichage : acceptée (visiteur et membre)', r1.status_code == 204 and r2.status_code == 204, (r1.status_code, r2.status_code))
check('erreur d’affichage : une ligne, comptée deux fois, dernière page gardée',
      rows.count() == 1 and rows[0].count == 2 and rows[0].endpoint == '/exercises/3/edit', list(rows.values('count', 'endpoint')))
check('erreur d’affichage : message vide refusé', anon.post('/api/logs/client-errors/', {'message': ' '}, format='json').status_code == 400)
long = anon.post('/api/logs/client-errors/', {'message': 'x' * 5000, 'stack': ['pas', 'une', 'chaîne']}, format='json')
check('erreur d’affichage : message tronqué, pile non texte ignorée', long.status_code == 204
      and ErrorLog.objects.filter(message='x' * 500, traceback__isnull=True).exists(), long.status_code)

nul = anon.post('/api/logs/client-errors/', {'message': 'Erreur\x00 avec NUL', 'path': '/a\x00b'}, format='json')
check('erreur d’affichage : caractère NUL retiré (PostgreSQL le refuse)', nul.status_code == 204
      and ErrorLog.objects.filter(message='Erreur avec NUL', endpoint='/ab').exists(), nul.status_code)
# Au plus NEW_PER_HOUR nouvelles lignes par heure pour tout le site ; les erreurs connues restent comptées.
import apps.logging.client_errors as ce  # noqa: E402
from django.core.cache import cache  # noqa: E402
cache.clear()
ce.NEW_PER_HOUR = 2
before = ErrorLog.objects.count()
for i in range(4):
    APIClient().post('/api/logs/client-errors/', {'message': f'Erreur inventée {i}'}, format='json',
                     HTTP_CF_CONNECTING_IP=f'10.0.0.{i}')
check('erreur d’affichage : plafond de nouvelles lignes par heure', ErrorLog.objects.count() - before == 2,
      ErrorLog.objects.count() - before)
r = anon.post('/api/logs/client-errors/', {'message': msg}, format='json', HTTP_CF_CONNECTING_IP='10.0.1.1')
check('erreur d’affichage : une erreur connue reste comptée au-delà du plafond',
      r.status_code == 204 and ErrorLog.objects.get(message=msg).count == 3, ErrorLog.objects.get(message=msg).count)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
