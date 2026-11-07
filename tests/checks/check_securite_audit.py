"""Audit de sécurité du 07/11/2026 : ce que l'API donne aux visiteurs, le blocage de connexion, la rotation des jetons.

On vérifie : notes internes (`import`) jamais envoyées aux lecteurs ; solutions et indices absents des listes
(présents dans le contenu ouvert) ; l'auteur et l'équipe reçoivent tout ; pages plafonnées à 30 contenus pour un
visiteur ; statut d'administrateur caché aux autres ; routes de suivi anonymes retirées ; 15 faux mots de passe
depuis une IP ne bloquent pas le titulaire ailleurs ; jeton de rafraîchissement utilisable une seule fois ;
rapports CSP rangés dans les erreurs.
"""
import json
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-securite-audit.sqlite3')
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
from apps.caracteristics.models import Subject  # noqa: E402
from apps.logging.models import ErrorLog  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


maths = Subject.objects.get(name='Mathématiques')
admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
auteur = User.objects.create_user('auteur', 'a@x.fr', 'Motdepasse-solide-42')
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
STRUCTURE = {
    'credit': 'M. Prof', 'import': {'source': {'note': 'note interne', 'document': 'cours.pdf'}, 'ia': {'publie_par': 'chef'}},
    'blocks': [{'id': 'q1', 'type': 'question', 'content': {'html': '<p>Énoncé</p>'}, 'hint': {'html': 'indice'},
                'solution': {'html': '<p>Solution</p>'}, 'meta': {'theorems': []},
                'subQuestions': [{'id': 'a', 'content': {'html': 'a)'}, 'solution': {'html': 'sol a'}}]}],
}
ex = Content.objects.create(type='exercise', title='Exercice test', author=auteur, subject=maths, json_content=STRUCTURE,
                            difficulty='medium')
for i in range(40):
    Content.objects.create(type='exercise', title=f'Ex {i}', author=auteur, subject=maths, json_content={'blocks': []},
                           difficulty='easy')


def client(user=None, ip='203.0.113.1'):
    c = APIClient(HTTP_CF_CONNECTING_IP=ip)
    if user:
        c.force_authenticate(user)
    return c


def item(liste, pk):
    return next((x for x in liste if x['id'] == pk), None)


anon = client()
rows = anon.get('/api/contents/?type=exercise&page_size=100').data
lu = item(rows['results'], ex.id) or item(anon.get('/api/contents/?type=exercise&page_size=30&page=2').data['results'], ex.id)
s = json.dumps(lu or {}, ensure_ascii=False)
check('liste (visiteur) : ni notes internes ni solutions ni indices', lu and 'import' not in lu['json_content']
      and 'note interne' not in s and 'Solution' not in s and 'sol a' not in s and 'indice' not in s, s[:300])
check('liste (visiteur) : énoncé et crédit gardés', lu and 'Énoncé' in s and lu['json_content'].get('credit') == 'M. Prof')
check('liste (visiteur) : 30 contenus par page au plus', len(rows['results']) == 30, len(rows['results']))
check('liste (élève connecté) : jusqu’à 100 par page, solutions comprises', len(client(eleve).get('/api/contents/?type=exercise&page_size=100')
                                                         .data['results']) == 41)

detail = anon.get(f'/api/contents/{ex.id}/').data
s = json.dumps(detail, ensure_ascii=False)
check('contenu ouvert (visiteur) : solutions présentes, notes internes absentes', 'Solution' in s and 'sol a' in s
      and 'import' not in detail['json_content'] and 'note interne' not in s, s[:300])
check('contenu ouvert (élève) : pas de notes internes', 'import' not in client(eleve).get(f'/api/contents/{ex.id}/')
      .data['json_content'])
check('contenu ouvert (auteur) : tout, pour l’édition', client(auteur).get(f'/api/contents/{ex.id}/')
      .data['json_content'].get('import', {}).get('source', {}).get('note') == 'note interne')
check('contenu ouvert (équipe) : tout', 'import' in client(admin).get(f'/api/contents/{ex.id}/').data['json_content'])

profil = client(eleve).get('/api/users/chef/').data
check('profil d’un autre : statut d’administrateur caché', 'is_superuser' not in profil, list(profil))
check('son propre profil : statut gardé', 'is_superuser' in client(admin).get('/api/users/chef/').data)

for route in ('pageview/', 'pageview/update-time/', 'interaction/', 'abtest/impression/', 'abtest/conversion/'):
    code = anon.post(f'/api/logs/analytics/{route}', {'session_id': 'x', 'path': '/'}, format='json').status_code
    check(f'suivi anonyme retiré : {route}', code == 404, code)

# Connexion : 15 faux mots de passe depuis une IP bloquent cette IP, pas le titulaire depuis la sienne.
cache.clear()
pirate = client(ip='198.51.100.9')
codes = [pirate.post('/api/auth/login/', {'identifier': 'eleve', 'password': 'faux'}, format='json').status_code
         for _ in range(16)]
check('15 essais depuis une IP, puis bloquée', codes[:15] == [401] * 15 and codes[15] == 429, codes[-3:])
titulaire = client(ip='203.0.113.50').post('/api/auth/login/', {'identifier': 'eleve', 'password': 'Motdepasse-solide-42'},
                                          format='json')
check('le titulaire se connecte depuis son adresse', titulaire.status_code == 200, titulaire.status_code)

refresh = titulaire.data['refresh']
r1 = client(ip='203.0.113.50').post('/api/token/refresh/', {'refresh': refresh}, format='json')
check('renouvellement : nouveau jeton de rafraîchissement', r1.status_code == 200 and r1.data.get('refresh')
      and r1.data['refresh'] != refresh, r1.status_code)
r2 = client(ip='203.0.113.50').post('/api/token/refresh/', {'refresh': refresh}, format='json')
check('ancien jeton de rafraîchissement refusé (volé, il ne sert qu’une fois)', r2.status_code == 401, r2.status_code)

rapport = {'csp-report': {'document-uri': 'https://fidni.fr/exercises', 'effective-directive': 'script-src-elem',
                          'blocked-uri': 'https://evil.example/x.js'}}
code = APIClient().post('/api/logs/csp/', json.dumps(rapport), content_type='application/csp-report').status_code
check('rapport CSP rangé dans les erreurs', code == 204 and ErrorLog.objects.filter(
    exception_type='Politique CSP (navigateur)', message__contains='evil.example').exists(), code)
check('rapport CSP trop gros refusé', APIClient().post('/api/logs/csp/', 'x' * 30000, content_type='application/json')
      .status_code == 413)

# Pages pré-remplies (/exercises/<id>) : 30 par minute et par IP, sauf robots vérifiés par Cloudflare.
from config import seo  # noqa: E402
seo._index_cache.update(html='<html><head><title>x</title></head><body><div id="root"></div></body></html>', at=10 ** 12)
cache.clear()
web = client(ip='192.0.2.77')
codes = [web.get(f'/seo/exercises/{ex.id}/').status_code for _ in range(31)]
check('pages pré-remplies : 30 par minute, puis 429', codes[:30] == [200] * 30 and codes[30] == 429, codes[-3:])
robot = APIClient(HTTP_CF_CONNECTING_IP='192.0.2.77', HTTP_X_FIDNI_ROBOT='true')
check('robot vérifié par Cloudflare : pas limité', robot.get(f'/seo/exercises/{ex.id}/').status_code == 200)

ok = sum(results)
print(f'\n{ok}/{len(results)} vérifications OK')
sys.exit(0 if ok == len(results) else 1)
