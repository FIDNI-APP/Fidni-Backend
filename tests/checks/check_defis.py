"""Défi du jour (07/11/2026), sur une base SQLite jetable : la réponse et la solution ne partent jamais avant la fin de la
tentative ; un défi non validé ou à venir reste invisible ; trois essais, formats de réponse, série, visiteurs ; le jour
change à minuit au Maroc ; Pilotage réservé aux administrateurs ; import d'un lot en brouillons.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone as tz
from unittest import mock

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-defis.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.cache import cache  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402

call_command('migrate', verbosity=0)

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.defis import reponses, views  # noqa: E402
from apps.defis.models import Defi, TentativeDefi  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAUX ') + name + (f' — {detail}' if detail and not ok else ''))


def creer(jour, cle=None, valide=True, reponse='2'):
    return Defi.objects.create(
        cle=cle or f'defi-{jour.isoformat()}', date=jour, titre='Titre', theme='algebre', difficulte='easy', enonce='Calculer $1+1$.',
        consigne='Donne un nombre entier.', reponse=reponse, solution='SOLUTION-SECRETE',
        indices=[{'titre': 'Outil', 'texte': 'Additionne.'}, {'titre': 'Calcul', 'texte': 'Une unité de plus.'}], valide=valide)


def client(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


print('--- Formats de réponse')
for texte, attendue, ok in [('2', '2', True), (' 2 ', '2', True), ('2,0', '2', True), ('2.0', '2', True), ('4/2', '2', True),
                            ('−3', '-3', True), ('-3', '-3', True), ('0,5', '1/2', True), ('1/2', '1/2', True), ('.5', '1/2', True),
                            ('2 026', '2026', True), ('2 026', '2026', True), ('3', '2', False), ('-2', '2', False)]:
    check(f'{texte!r} contre {attendue!r} : {ok}', reponses.juste(texte, attendue) == ok)
for texte in ['', 'abc', '1/0', '1/2/3', '2+2', '1e5', '²', None, 12, '9' * 41]:
    check(f'{texte!r} n’est pas lu comme un nombre', reponses.lire(texte) is None)

print('--- Jour du Maroc')
minuit_passe = datetime(2026, 7, 1, 23, 30, tzinfo=tz.utc)  # 00 h 30 le 2 au Maroc (UTC+1 cet été-là)
with mock.patch('django.utils.timezone.now', return_value=minuit_passe):
    check('23 h 30 UTC le 1er juillet : déjà le 2 au Maroc', views.aujourdhui().isoformat() == '2026-07-02', str(views.aujourdhui()))

jour = views.aujourdhui()
hier, avant_hier, demain = jour - timedelta(days=1), jour - timedelta(days=2), jour + timedelta(days=1)
J, H, A = jour.isoformat(), hier.isoformat(), avant_hier.isoformat()
eleve = User.objects.create_user('eleve', password='x')
autre = User.objects.create_user('autre', password='x')
admin = User.objects.create_superuser('chef', password='x')
c = client(eleve)

print('--- Visibilité')
check('Aucun défi aujourd’hui : réponse vide, pas d’erreur', client().get('/api/defis/aujourdhui/').json() == {'defi': None})
creer(jour, valide=False)
check('Non validé : invisible', client().get('/api/defis/aujourdhui/').json() == {'defi': None})
check('Non validé : pas de détail', client().get(f'/api/defis/{J}/').status_code == 404)
check('Non validé : on ne peut pas répondre', client().post(f'/api/defis/{J}/repondre/', {'reponse': '2'}, format='json').status_code == 404)
Defi.objects.filter(date=jour).update(valide=True)
creer(demain)
check('Validé mais à venir : invisible', client().get(f'/api/defis/{demain.isoformat()}/').status_code == 404)
check('Date illisible : 404', client().get('/api/defis/n-importe-quoi/').status_code == 404)

print('--- Rien ne fuit avant la fin')
for nom, cl in (('visiteur', client()), ('élève', c)):
    r = cl.get('/api/defis/aujourdhui/')
    texte = r.content.decode()
    defi = r.json()['defi']
    check(f'{nom} : énoncé et indices présents', 'Calculer' in defi['enonce'] and len(defi['indices']) == 2)
    check(f'{nom} : ni réponse ni solution', 'SOLUTION-SECRETE' not in texte and 'reponse' not in defi and 'solution' not in defi, texte[:300])
check('Le visiteur n’a pas de série', client().get('/api/defis/aujourdhui/').json()['defi']['serie'] is None)

print('--- Trois essais')
r = c.post(f'/api/defis/{J}/repondre/', {'reponse': 'abc'}, format='json')
check('Pas un nombre : 400, essai non compté', r.status_code == 400 and not TentativeDefi.objects.filter(user=eleve).exists(), r.content)
r = c.post(f'/api/defis/{J}/repondre/', {'reponse': '5'}, format='json').json()
check('Faux : 2 essais restants, pas de solution', r['juste'] is False and r['essais_restants'] == 2 and 'solution' not in r and 'reponse' not in r, r)
c.post(f'/api/defis/{J}/repondre/', {'reponse': '6'}, format='json')
check('Après 2 essais faux : toujours pas de solution', 'solution' not in c.get('/api/defis/aujourdhui/').json()['defi'])
r = c.post(f'/api/defis/{J}/repondre/', {'reponse': '7'}, format='json').json()
check('3e faux : fin, solution et réponse données', r['statut'] == 'rate' and r['solution'] == 'SOLUTION-SECRETE' and r['reponse'] == '2', r)
r = c.post(f'/api/defis/{J}/repondre/', {'reponse': '2'}, format='json').json()
check('Fini : une bonne réponse après coup ne compte plus', r['juste'] is False and r['statut'] == 'rate' and r['essais'] == 3, r)
check('Raté : la série reste à 0', r['serie'] == 0)

c2 = client(autre)
r = c2.post(f'/api/defis/{J}/repondre/', {'reponse': '4/2'}, format='json').json()
check('Bonne réponse (4/2 pour 2) : trouvé, solution donnée', r['juste'] is True and r['statut'] == 'trouve' and r['solution'] == 'SOLUTION-SECRETE', r)
check('Trouvé le jour même : série à 1', r['serie'] == 1, r)
check('Tentative de l’élève 1 intacte', TentativeDefi.objects.get(user=eleve).statut == 'rate')
r = c2.get('/api/defis/aujourdhui/').json()['defi']
check('On revient : état et solution retrouvés', r['statut'] == 'trouve' and r['essais'] == 1 and r['solution'] == 'SOLUTION-SECRETE')

print('--- Indices et abandon')
creer(hier)
creer(avant_hier)
r = c.post(f'/api/defis/{H}/indice/', format='json').json()
check('Indice noté pour un membre', r['indices_vus'] == 1, r)
c.post(f'/api/defis/{H}/indice/', format='json')
r = c.post(f'/api/defis/{H}/indice/', format='json').json()
check('Pas plus d’indices que le défi n’en a', r['indices_vus'] == 2, r)
check('Un indice ne donne pas la solution', 'solution' not in c.get(f'/api/defis/{H}/').json())
r = c.post(f'/api/defis/{H}/abandonner/', format='json').json()
check('« Voir la solution » : fin de la tentative, solution donnée', r['statut'] == 'rate' and r['solution'] == 'SOLUTION-SECRETE', r)
r = c2.post(f'/api/defis/{J}/abandonner/', format='json').json()
check('Déjà trouvé : voir la solution ne change rien', r['statut'] == 'trouve' and r['serie'] == 1, r)

print('--- Visiteur')
v = client()
r = v.post(f'/api/defis/{J}/repondre/', {'reponse': '9', 'essai': 1}, format='json').json()
check('Faux au 1er essai : rien de donné', r['statut'] == 'en_cours' and r['essais_restants'] == 2 and 'solution' not in r, r)
r = v.post(f'/api/defis/{J}/repondre/', {'reponse': '9', 'essai': 3}, format='json').json()
check('Faux au 3e essai : solution', r['statut'] == 'rate' and r['solution'] == 'SOLUTION-SECRETE', r)
r = v.post(f'/api/defis/{J}/repondre/', {'reponse': '2', 'essai': 1}, format='json').json()
check('Juste : trouvé', r['juste'] is True and r['statut'] == 'trouve', r)
r = v.post(f'/api/defis/{J}/repondre/', {'reponse': '9', 'essai': 'x'}, format='json')
check('Essai illisible : compté comme le premier', r.status_code == 200 and r.json()['statut'] == 'en_cours', r.content)
nb = TentativeDefi.objects.count()
v.post(f'/api/defis/{J}/indice/', format='json')
v.post(f'/api/defis/{J}/abandonner/', format='json')
check('Un visiteur n’écrit rien en base', TentativeDefi.objects.count() == nb)

print('--- Série')
u = User.objects.create_user('regulier', password='x')
cu = client(u)
check('Défi d’avant-hier fait aujourd’hui : ne compte pas dans la série',
      cu.post(f'/api/defis/{A}/repondre/', {'reponse': '2'}, format='json').json()['serie'] == 0)
t = TentativeDefi.objects.get(user=u, defi__date=avant_hier)
check('Rattrapage : trouvé, mais pas le jour même', t.statut == 'trouve' and t.le_jour_meme is False)
TentativeDefi.objects.filter(pk=t.pk).update(le_jour_meme=True)
TentativeDefi.objects.create(user=u, defi=Defi.objects.get(date=hier), statut='trouve', essais=1, le_jour_meme=True)
check('Hier et avant-hier trouvés : série 2, aujourd’hui pas encore fait', views.serie(u) == 2, views.serie(u))
r = cu.post(f'/api/defis/{J}/repondre/', {'reponse': '2'}, format='json').json()
check('Aujourd’hui trouvé : série 3', r['serie'] == 3, r)
Defi.objects.filter(date=hier).update(valide=False)
check('Un jour sans défi publié ne casse pas la série', views.serie(u) == 2, views.serie(u))
Defi.objects.filter(date=hier).update(valide=True)
TentativeDefi.objects.filter(user=u, defi__date=hier).update(statut='rate')
check('Un défi publié manqué casse la série', views.serie(u) == 1, views.serie(u))

print('--- Taux de réussite')
d = Defi.objects.get(date=avant_hier)
TentativeDefi.objects.filter(defi=d).delete()
for i in range(19):
    TentativeDefi.objects.create(user=User.objects.create_user(f's{i}', password='x'), defi=d, statut='trouve' if i < 5 else 'rate')
check('Moins de 20 réponses : pas de chiffre', views._stats(d) is None)
TentativeDefi.objects.create(user=User.objects.create_user('s19', password='x'), defi=d, statut='trouve')
check('20 réponses : le vrai taux', views._stats(d) == {'total': 20, 'trouves': 6}, views._stats(d))

print('--- Archives')
r = c.get('/api/defis/archives/').json()['results']
check('Passés seulement, du plus récent au plus ancien', [x['date'] for x in r] == [H, A], r)
check('Avec l’état du membre', r[0]['statut'] == 'rate' and r[1]['statut'] == 'en_cours', r)
check('Sans réponse ni solution', 'SOLUTION' not in c.get('/api/defis/archives/').content.decode() and 'reponse' not in r[0])

print('--- Pilotage')
check('Visiteur refusé', client().get('/api/pilotage/defis/').status_code in (401, 403))
check('Élève refusé', c.get('/api/pilotage/defis/').status_code == 403)
d_futur = Defi.objects.get(date=demain)
check('Élève ne peut pas modifier', c.patch(f'/api/pilotage/defis/{d_futur.pk}/', {'reponse': '9'}, format='json').status_code == 403)
check('Élève ne peut pas valider', c.post('/api/pilotage/defis/valider/', {'ids': [d_futur.pk]}, format='json').status_code == 403)
a = client(admin)
Defi.objects.filter(pk=d_futur.pk).update(valide=False)
r = a.get('/api/pilotage/defis/').json()
check('Admin voit les réponses et le compte', r['results'][0]['reponse'] == '2' and r['a_valider'] == 1 and r['jours_couverts'] == 1, {k: r[k] for k in ('a_valider', 'jours_couverts')})
check('Pastille « à valider » du Pilotage', a.get('/api/admin/live/').status_code in (200, 404))
check('Réponse illisible refusée', a.patch(f'/api/pilotage/defis/{d_futur.pk}/', {'reponse': 'abc'}, format='json').status_code == 400)
check('Indice sans texte refusé', a.patch(f'/api/pilotage/defis/{d_futur.pk}/', {'indices': [{'titre': 'x', 'texte': ' '}]}, format='json').status_code == 400)
check('Date déjà prise refusée', a.patch(f'/api/pilotage/defis/{d_futur.pk}/', {'date': J}, format='json').status_code == 400)
r = a.patch(f'/api/pilotage/defis/{d_futur.pk}/', {'reponse': '-3', 'titre': 'Nouveau'}, format='json')
check('Correction enregistrée', r.status_code == 200 and r.json()['reponse'] == '-3' and r.json()['titre'] == 'Nouveau', r.content)
r = a.post('/api/pilotage/defis/valider/', {'ids': [d_futur.pk]}, format='json').json()
check('Validation groupée', r == {'valides': 1} and Defi.objects.get(pk=d_futur.pk).valide)
check('Défi déjà joué : suppression refusée', a.delete(f'/api/pilotage/defis/{Defi.objects.get(date=jour).pk}/').status_code == 400)
check('Défi déjà joué : date figée', a.patch(f'/api/pilotage/defis/{Defi.objects.get(date=jour).pk}/', {'date': (jour + timedelta(days=30)).isoformat()}, format='json').status_code == 400)
check('Défi jamais joué : suppression possible', a.delete(f'/api/pilotage/defis/{d_futur.pk}/').status_code == 204)

print('--- Limite de requêtes')
cache.clear()
ok = [client(eleve).post(f'/api/defis/{J}/repondre/', {'reponse': '1'}, format='json').status_code for _ in range(61)]
check('Au-delà de 60 réponses par minute : 429', ok[-1] == 429 and ok[0] == 200, ok[-3:])
cache.clear()

print('--- Import')
LOT = [{'cle': 'lot-a', 'date': (jour + timedelta(days=40)).isoformat(), 'titre': 'A', 'theme': 'logique', 'difficulte': 'hard', 'enonce': 'E',
        'consigne': 'C', 'reponse': '1/4', 'indices': [{'titre': 't', 'texte': 'x'}], 'solution': 'S', 'source': 'Fidni'}]


def importer(lot, **kw):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(lot, f)
    call_command('defis_importer', f.name, verbosity=0, **kw)


importer(LOT, essai=True)
check('--essai : rien d’écrit', not Defi.objects.filter(cle='lot-a').exists())
importer(LOT)
n = Defi.objects.get(cle='lot-a')
check('Importé en brouillon', n.valide is False and n.reponse == '1/4')
Defi.objects.filter(cle='lot-a').update(valide=True)
importer([{**LOT[0], 'titre': 'B'}])
n.refresh_from_db()
check('Réimport : mis à jour et repassé à valider', n.titre == 'B' and n.valide is False)
for nom, lot in (('réponse illisible', [{**LOT[0], 'cle': 'x', 'reponse': 'abc'}]), ('champ manquant', [{**LOT[0], 'cle': 'x', 'solution': ''}]),
                 ('thème inconnu', [{**LOT[0], 'cle': 'x', 'theme': 'zzz'}]), ('date déjà prise', [{**LOT[0], 'cle': 'x'}])):
    try:
        importer(lot)
        check(f'Lot refusé : {nom}', False)
    except CommandError:
        check(f'Lot refusé : {nom}', True)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
