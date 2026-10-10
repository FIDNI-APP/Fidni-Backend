"""Mesure d'usage (pages, actions, fonctionnalités du Pilotage) et auto-évaluation groupée (« Tout réussi »)."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-usage.sqlite3')
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
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.models import UsageDaily  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


UA = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0) Chrome/130'}
level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
eleves = [User.objects.create_user(f'eleve{i}', f'e{i}@x.fr', 'Motdepasse-solide-42') for i in range(2)]
admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
ex = Content.objects.create(type='exercise', title='Exercice', author=editorial, subject=subject, json_content={
    'version': '2.1', 'blocks': [
        {'id': 'q1', 'type': 'question', 'content': {'html': '<p>a</p>'}},
        {'id': 'q2', 'type': 'question', 'content': {'html': '<p>b</p>'},
         'subQuestions': [{'id': 's1', 'content': {'html': '<p>c</p>'}}, {'id': 's2', 'content': {'html': '<p>d</p>'}}]},
    ]})
ex.class_levels.add(level)


def client(user=None, ip='10.0.0.1'):
    c = APIClient(REMOTE_ADDR=ip, **UA)
    if user:
        c.force_authenticate(user)
    return c


# ── Mesure d'usage
visitor = client(ip='10.0.0.7')
r = visitor.post('/api/usage/', {'kind': 'page', 'name': '/exercises/:id'}, format='json')
check('visiteur : page comptée', r.status_code == 200 and r.data['counted'], r.data)
r = visitor.post('/api/usage/', {'kind': 'page', 'name': '/exercises/:id'}, format='json')
check('double envoi immédiat : compté une fois', not r.data['counted'], r.data)
client(eleves[0]).post('/api/usage/', {'kind': 'page', 'name': '/exercises/:id'}, format='json')
client(eleves[1]).post('/api/usage/', {'kind': 'page', 'name': '/'}, format='json')
row = UsageDaily.objects.get(kind='page', name='/exercises/:id')
check('2 vues, 2 personnes', (row.count, row.visitors) == (2, 2), (row.count, row.visitors))
r = client(admin).post('/api/usage/', {'kind': 'page', 'name': '/'}, format='json')
check('compte maison : pas compté', r.status_code == 200 and not r.data['counted'], r.data)
r = APIClient(REMOTE_ADDR='10.0.0.9', HTTP_USER_AGENT='Googlebot/2.1').post('/api/usage/', {'kind': 'page', 'name': '/'}, format='json')
check('robot : pas compté', not r.data['counted'], r.data)
r = visitor.post('/api/usage/', {'kind': 'page', 'name': '/exercises/42?x=<script>'}, format='json')
check('adresse invalide refusée', r.status_code == 400, r.status_code)
r = visitor.post('/api/usage/', {'kind': 'action', 'name': 'nimporte-quoi'}, format='json')
check('action inconnue refusée', r.status_code == 400, r.status_code)
r = client(eleves[0]).post('/api/usage/', {'kind': 'action', 'name': 'imprimer'}, format='json')
check('action connue comptée', r.data.get('counted') is True, r.data)
r = client(eleves[0]).post('/api/usage/', {'kind': 'action', 'name': 'filtre-chapitre'}, format='json')
check('filtre compté', r.data.get('counted') is True, r.data)

# ── Auto-évaluation groupée
cl = client(eleves[0])
r = cl.get(f'/api/contents/{ex.id}/statistics/')
check('statistiques : pas encore évalué', r.status_code == 200 and r.data['user_assessed'] is False, r.data.get('user_assessed'))
r = cl.post(f'/api/contents/{ex.id}/assess_many/',
            {'assessments': {'q1': 'success', 'q2.s1': 'success', 'q2.s2': 'success'}, 'completion': 'success'}, format='json')
check('« Tout réussi » : 3 questions et le contenu réussis', r.status_code == 200 and len(r.data['item_progress']) == 3
      and r.data['completion'] == 'success', r.data)
r = cl.get(f'/api/contents/{ex.id}/statistics/')
check('statistiques à jour tout de suite (cache vidé)', r.data['user_assessed'] is True and r.data['user_completed'] == 'success'
      and len(r.data['per_question']) == 3, (r.data['user_assessed'], r.data['user_completed']))
r = cl.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q2.s2', 'status': 'review'}, format='json')
r = cl.get(f'/api/contents/{ex.id}/statistics/')
st = {q['path']: q['user_status'] for q in r.data['per_question']}
check('une question décochée : visible tout de suite', st.get('q2.s2') == 'review', st)
r = cl.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': None, 'q2.s1': None, 'q2.s2': None}, 'completion': None}, format='json')
check('tout effacer', r.status_code == 200 and r.data['item_progress'] == {} and r.data['completion'] is None
      and not Complete.objects.filter(user=eleves[0]).exists(), r.data)
r = cl.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': 'parfait'}}, format='json')
check('statut invalide refusé', r.status_code == 400, r.status_code)
r = client().post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': 'success'}}, format='json')
check('visiteur : refusé', r.status_code in (401, 403), r.status_code)
r = cl.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': 'success'}}, format='json')
check('sans « completion » : le résultat du contenu ne change pas', r.data['completion'] is None
      and QuestionProgress.objects.filter(user=eleves[0]).count() == 1, r.data)

# ── Pilotage : fonctionnalités et pages
pc = client(admin)
r = pc.get('/api/pilotage/?jours=7')
check('pilotage : réponse', r.status_code == 200 and 'features' in r.data and 'pages' in r.data, r.status_code)
f = {x['key']: x for x in r.data['features']}
check('auto-évaluation : 1 membre, 1 question', f['auto_evaluation']['users'] == 1 and f['auto_evaluation']['actions'] == 1,
      f.get('auto_evaluation'))
check('impression (navigateur) : 1 fois', f['imprimer']['actions'] == 1 and f['imprimer']['users'] is None, f.get('imprimer'))
check('filtres : rubrique à part', f['filtre-chapitre']['source'] == 'filtre' and f['filtre-chapitre']['actions'] == 1
      and f['tri']['actions'] == 0, f.get('filtre-chapitre'))
pages = {p['page']: p for p in r.data['pages']}
check('pages : fiche exercice en tête', r.data['pages'][0]['page'] == '/exercises/:id' and pages['/exercises/:id']['views'] == 2,
      r.data['pages'])
from django.utils import timezone  # noqa: E402
for i in range(20):
    UsageDaily.objects.create(date=timezone.localdate(), kind='page', name=f'/page-{i}', count=50, visitors=5)
UsageDaily.objects.create(date=timezone.localdate(), kind='page', name='/statistiques', count=1, visitors=1)
pages = {p['page']: p for p in pc.get('/api/pilotage/?jours=7').data['pages']}
check('toutes les pages, même peu vues (« Mes statistiques » au-delà de la 15e)',
      pages.get('/statistiques', {}).get('views') == 1 and len(pages) >= 22, len(pages))
check('date de début de la mesure', r.data['usage_since'] == '2026-10-06', r.data.get('usage_since'))

# ── Visiteurs non connectés (09/10/2026) : comptés à part
row = UsageDaily.objects.get(kind='page', name='/exercises/:id')
check('page : part des visiteurs', (row.anon_count, row.anon_visitors) == (1, 1), (row.anon_count, row.anon_visitors))
site = UsageDaily.objects.get(kind='site', name='visites')
check('site : 3 personnes distinctes dont 1 visiteur', (site.visitors, site.anon_visitors) == (3, 1),
      (site.visitors, site.anon_visitors))
client(ip='10.0.0.7').post('/api/usage/', {'kind': 'page', 'name': '/exams'}, format='json')
site.refresh_from_db()
check('site : le même visiteur sur une autre page reste 1 personne', (site.count, site.anon_count, site.anon_visitors) == (4, 2, 1),
      (site.count, site.anon_count, site.anon_visitors))
r = client(ip='10.0.0.8').post(f'/api/contents/{ex.id}/view/')
r = client(eleves[1]).post(f'/api/contents/{ex.id}/view/')
from apps.things.models import ContentDailyView  # noqa: E402
dv = ContentDailyView.objects.get(content=ex)
check('vues du contenu : 2 dont 1 visiteur', (dv.count, dv.anon_count) == (2, 1), (dv.count, dv.anon_count))
r = client(ip='10.0.0.8').post('/api/usage/', {'kind': 'action', 'name': 'voir-solution'}, format='json')

# ── Valeurs des filtres
for name in ('exercise:difficulte:hard', 'exercise:difficulte:easy', 'exam:niveau:%d' % level.id, 'lesson:tri:newest'):
    r = client(eleves[1]).post('/api/usage/', {'kind': 'filtre', 'name': name}, format='json')
    check(f'valeur de filtre comptée : {name}', r.data.get('counted') is True, r.data)
client(ip='10.0.0.8').post('/api/usage/', {'kind': 'filtre', 'name': 'exercise:difficulte:hard'}, format='json')
for bad in ('exercise:difficulte:<b>', 'autre:difficulte:hard', 'exercise:inconnu:1', 'exercise:difficulte:'):
    r = client(eleves[1]).post('/api/usage/', {'kind': 'filtre', 'name': bad}, format='json')
    check(f'valeur de filtre invalide refusée : {bad}', r.status_code == 400, r.status_code)

r = pc.get('/api/pilotage/?jours=7')
vals = {(v['type'], v['filter'], v['value']): v for v in r.data['filter_values']}
hard = vals.get(('exercise', 'filtre-difficulte', 'hard'), {})
check('filtres : « Difficile » 2 fois dont 1 visiteur, en tête', hard.get('label') == 'Difficile' and hard.get('count') == 2
      and hard.get('anon') == 1 and r.data['filter_values'][0] is hard, r.data['filter_values'])
check('filtres : identifiant traduit en nom', vals.get(('exam', 'filtre-niveau', str(level.id)), {}).get('label') == level.name,
      r.data['filter_values'])
check('filtres : tri traduit', vals.get(('lesson', 'tri', 'newest'), {}).get('label') == 'Plus récents', r.data['filter_values'])
an = r.data['anonymes']
check('anonymes : visites, pages, contenus', an['current']['visits'] == 1 and an['current']['pages'] == 2
      and an['current']['contents'] == 1 and an['current']['contents_all'] == 2, an['current'])
check('anonymes : courbe du jour', an['series'][-1]['anon'] == 1 and an['series'][-1]['members'] == 2, an['series'][-1])
check('anonymes : pages vues', {p['page'] for p in an['pages']} == {'/exercises/:id', '/exams'}, an['pages'])
check('anonymes : contenu le plus vu', an['top_contents'] and an['top_contents'][0]['id'] == ex.id
      and an['top_contents'][0]['views'] == 1, an['top_contents'])
acts = {a['key']: a for a in an['actions']}
check('anonymes : gestes (voir la solution)', acts.get('voir-solution', {}).get('count') == 1, an['actions'])


# ── Audit du 10/10/2026 : nouveaux gestes mesurés, porte d'entrée de l'inscription, origine d'une auto-évaluation
import re  # noqa: E402
from apps.users.admin_dashboard import TRACKED_ACTIONS, TRACKED_FILTERS  # noqa: E402
from apps.users.usage import ACTIONS  # noqa: E402

NEW_ACTIONS = ['partager', 'chrono-demarre', 'epreuve-demarree', 'epreuve-terminee', 'similaire', 'suivant-apres-resultat',
               'ressenti', 'cloche', 'retour-liste', 'sommaire-lecon', 'affichage-enonces', 'charger-plus', 'recherche-vide',
               'accueil-reprendre', 'accueil-pour-toi', 'annoncer-ds', 'prog-entrainer', 'prog-cours', 'prog-quiz',
               'quiz-refait', 'mode-revision', 'barre-mobile', 'visite-auto', 'visite-passee', 'visite-finie',
               'signaler-ouvert', 'auth-ouverte', 'connexion-google']
labelled = {k for k, _ in TRACKED_ACTIONS + TRACKED_FILTERS}
check('nouveaux gestes dans la liste fermée', set(NEW_ACTIONS) <= ACTIONS, set(NEW_ACTIONS) - ACTIONS)
check('chaque geste accepté a son libellé au Pilotage (et inversement)', labelled == ACTIONS, labelled ^ ACTIONS)
FRONT = os.path.join(os.path.dirname(BACKEND), 'Fidni-Frontend', 'src', 'lib', 'usage.ts')
if os.path.exists(FRONT):
    src = open(FRONT, encoding='utf-8').read()
    block = src[src.index('export type UsageAction'):]
    front = set(re.findall(r"'([a-z-]+)'", block[:block.index(';')]))
    check('même liste fermée côté navigateur (lib/usage.ts UsageAction)', front == ACTIONS, front ^ ACTIONS)
el = client(eleves[1], ip='10.0.0.21')
refused = [a for a in NEW_ACTIONS if el.post('/api/usage/', {'kind': 'action', 'name': a}, format='json').data.get('counted') is not True]
check('nouveaux gestes comptés', not refused, refused)
check('nouveaux gestes : une ligne du jour chacun',
      UsageDaily.objects.filter(kind='action', name__in=NEW_ACTIONS, count=1).count() == len(NEW_ACTIONS))
door = client(ip='10.0.0.22')
for name in ('auth:porte:vote', 'auth:porte:barre-haut', 'auth:porte:' + 'a' * 30):
    r = door.post('/api/usage/', {'kind': 'filtre', 'name': name}, format='json')
    check(f'porte d’inscription comptée : {name[:24]}', r.data.get('counted') is True, r.data)
row = UsageDaily.objects.get(kind='filtre', name='auth:porte:vote')
check('porte : visiteur non connecté compté à part', (row.count, row.anon_count, row.anon_visitors) == (1, 1, 1),
      (row.count, row.anon_count, row.anon_visitors))
for bad in ('auth:porte:', 'auth:porte:Vote', 'auth:porte:vote!', 'auth:porte:' + 'a' * 31, 'auth:autre:vote',
            'auth:porte:vote:2', 'exercise:porte:vote', 'auth:porte:vote\n', 'exercise:difficulte:hard\n'):
    r = door.post('/api/usage/', {'kind': 'filtre', 'name': bad}, format='json')
    check(f'porte invalide refusée : {bad[:26]!r}', r.status_code == 400, r.status_code)
r = door.post('/api/usage/', {'kind': 'page', 'name': '/exercises\n'}, format='json')
check('page avec saut de ligne final refusée', r.status_code == 400, r.status_code)
r = door.post('/api/usage/', {'kind': 'page', 'name': '/exercises/niveau/:level/:chapter?'}, format='json')
check('motif à segment facultatif (« :chapter? ») compté', r.status_code == 200 and r.data['counted'], r.status_code)
for bad in ('Partager', 'partager ', 'auth:porte:vote'):
    r = door.post('/api/usage/', {'kind': 'action', 'name': bad}, format='json')
    check(f'geste invalide refusé : {bad!r}', r.status_code == 400, r.status_code)
d = pc.get('/api/pilotage/?jours=7').data
nav = {x['key']: x for x in d['features'] if x['source'] == 'navigateur'}
check('Pilotage : nouveaux gestes affichés', nav.get('partager', {}).get('actions') == 1
      and nav.get('connexion-google', {}).get('actions') == 1, nav.get('partager'))
check('Pilotage : portes d’inscription', {(x['source'], x['count']) for x in d['auth_doors']}
      == {('vote', 1), ('barre-haut', 1), ('a' * 30, 1)}, d['auth_doors'])

# Origine d'une auto-évaluation (QuestionProgress.source) : « Tout réussi », réponse sous la solution, bandeau.
cl = client(eleves[1], ip='10.0.0.23')
cl.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': 'success', 'q2.s1': 'success'}, 'source': 'tout'},
        format='json')
cl.post(f'/api/contents/{ex.id}/assess_question/',
        {'question_path': 'q2.s2', 'status': 'review', 'source': 'apres_solution'}, format='json')
src = dict(QuestionProgress.objects.filter(user=eleves[1]).values_list('question_path', 'source'))
check('source de l’auto-évaluation enregistrée', src == {'q1': 'tout', 'q2.s1': 'tout', 'q2.s2': 'apres_solution'}, src)
cl.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
check('sans source : « question par question »',
      QuestionProgress.objects.get(user=eleves[1], question_path='q1').source == 'question')

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
