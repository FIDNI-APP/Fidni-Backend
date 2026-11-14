"""Enseignants des contenus (things/enseignants.py, 14/11/2026) : lecture des crédits, reprise des contenus en ligne
(migration 0029), champ des cartes (profil caché aux visiteurs), filtre et compteurs, Pilotage › Enseignants ;
type de devoir lu dans le titre (things/devoir.py) ; « 4 réussies, 1 à revoir » (user_progress)."""
import importlib
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-enseignants.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.apps import apps as django_apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import QuestionProgress  # noqa: E402
from apps.things.devoir import type_devoir  # noqa: E402
from apps.things.enseignants import analyser, attacher_depuis_credit  # noqa: E402
from apps.things.models import Content, Enseignant  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# --- Lecture des crédits
a = analyser('M. Haddar, M. Hafidi et M. Naoufel, professeurs de mathématiques')
check('crédit : trois enseignants, suffixe retiré', [x['nom'] for x in a] == ['Haddar', 'Hafidi', 'Naoufel'], a)
a = analyser('Aya Khazraji et M. Abdellah Belkhatir, professeurs de mathématiques')
check('crédit : sans civilité, prénom + nom', a == [{'civilite': '', 'prenom': 'Aya', 'nom': 'Khazraji'},
                                                    {'civilite': 'M.', 'prenom': 'Abdellah', 'nom': 'Belkhatir'}], a)
a = analyser('Driss En-Najjary, professeur de mathématiques')
check('crédit : nom composé', a == [{'civilite': '', 'prenom': 'Driss', 'nom': 'En-Najjary'}], a)
check('crédit : « Mme » et majuscules', analyser('Mme BENNANI') == [{'civilite': 'Mme', 'prenom': '', 'nom': 'Bennani'}])

# --- Contenus
admin = User.objects.create_superuser('natsu', 'n@x.fr', 'Motdepasse-solide-42')
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
prof = User.objects.create_user('khalid', 'k@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
maths = lim.subject


def q(qid):
    return {'id': qid, 'type': 'question', 'content': {'html': '<p>?</p>'}, 'meta': {}}


def contenu(titre, kind='exercise', credit=None, difficulty='medium'):
    st = {'version': '2.1', 'blocks': [q('q1'), q('q2'), q('q3'), q('q4'), q('q5')]}
    if credit:
        st['credit'] = credit
    c = Content.objects.create(type=kind, title=titre, author=admin, subject=maths, json_content=st,
                               difficulty=difficulty)
    c.class_levels.set([sm])
    c.chapters.set([lim])
    return c


c1 = contenu('Ex 1', credit='M. Haddar, professeur de mathématiques')
c2 = contenu('Ex 2', credit='M. Haddar, M. Hafidi et M. Naoufel, professeurs de mathématiques', difficulty='hard')
c3 = contenu('Ex 3', credit='Aya Khazraji et M. Abdellah Belkhatir, professeurs de mathématiques')
c4 = contenu('Ex 4')
ds = contenu('Devoir surveillé n° 2 (rattrapage) — 2ème Bac SM, M. Haddar (octobre 2024)', kind='exam',
             credit='M. Naoufal, professeur de mathématiques')

migration = importlib.import_module('apps.things.migrations.0029_enseignants_depuis_credits')
migration.forwards(django_apps, None)
haddar = Enseignant.objects.filter(nom='Haddar').first()
check('reprise : « M. Haddar » devient « M. Khalid Haddar »', haddar and haddar.nom_affiche == 'M. Khalid Haddar',
      haddar and haddar.nom_affiche)
check('reprise : un seul Haddar pour deux crédits', Enseignant.objects.filter(nom='Haddar').count() == 1)
check('reprise : contenus tagués', set(c2.enseignants.values_list('nom', flat=True)) == {'Haddar', 'Hafidi', 'Naoufel'})
check('reprise : Naoufel et Naoufal restent deux (à fusionner)', Enseignant.objects.filter(nom__startswith='Naouf').count() == 2)
check('reprise : contenu sans crédit sans enseignant', c4.enseignants.count() == 0)
check('reprise : 6 enseignants', Enseignant.objects.count() == 6, Enseignant.objects.count())

# Import : un crédit sans prénom retrouve l'enseignant existant.
attacher_depuis_credit(c4, 'M. Haddar, professeur de mathématiques')
check('import : « M. Haddar » retrouve M. Khalid Haddar', list(c4.enseignants.all()) == [haddar])
attacher_depuis_credit(c4, '')
check('import : crédit vide ne touche à rien', list(c4.enseignants.all()) == [haddar])

# --- Cartes
haddar.user = prof
haddar.save()
visiteur, membre, equipe = APIClient(), APIClient(), APIClient()
membre.force_authenticate(eleve)
equipe.force_authenticate(admin)


def carte(client, cid, kind='exercise'):
    r = client.get(f'/api/contents/?type={kind}&page_size=50')
    rows = r.json().get('results', [])
    return next((x for x in rows if x['id'] == cid), None)


v = carte(visiteur, c1.id)
check('carte : enseignant affiché', v and v['enseignants'] and v['enseignants'][0]['nom'] == 'M. Khalid Haddar', v and v.get('enseignants'))
check('carte : visiteur ne voit pas le compte relié', v and v['enseignants'][0]['profil'] is None)
m = carte(membre, c1.id)
check('carte : membre voit le profil relié', m and m['enseignants'][0]['profil'] == 'khalid', m and m.get('enseignants'))
d = membre.get(f'/api/contents/{c1.id}/').json()
check('page : enseignants dans le détail', d.get('enseignants', [{}])[0].get('nom') == 'M. Khalid Haddar', d.get('enseignants'))

# --- Type de devoir
e = carte(visiteur, ds.id, 'exam')
check('devoir : DS n° 2, rattrapage, 2024-2025', e and e['devoir'] == {'genre': 'ds', 'numero': 2, 'rattrapage': True,
                                                                        'annee_scolaire': '2024-2025'}, e and e.get('devoir'))
check('devoir : exercice sans type', m.get('devoir') is None)
check('devoir : contrôle continu, année écrite', type_devoir('Contrôle continu n° 3 — 2ème Bac SM (2023-2024)')
      == {'genre': 'controle', 'numero': 3, 'rattrapage': False, 'annee_scolaire': '2023-2024'})
check('devoir : mai 2025 = 2024-2025', type_devoir('Devoir maison n° 1 (mai 2025)')['annee_scolaire'] == '2024-2025')
check('devoir : synthèse', type_devoir('Devoir de synthèse n° 1 — 2ème Bac SM')['genre'] == 'synthese')
check('devoir : titre quelconque = rien', type_devoir('Étude de fonction') is None)
check('devoir : Bac national = rien', type_devoir('Examen national 2023', national=True) is None)

# --- Filtre et compteurs
r = visiteur.get(f'/api/contents/?type=exercise&enseignants[]={haddar.id}&page_size=50').json()
check('filtre : contenus de M. Khalid Haddar', {x['id'] for x in r['results']} == {c1.id, c2.id, c4.id},
      [x['id'] for x in r['results']])
r = visiteur.get(f'/api/enseignants/?content_type=exercise&class_levels[]={sm.id}').json()
noms = {x['nom']: x['count'] for x in r}
check('compteurs : par enseignant', noms.get('M. Khalid Haddar') == 3 and noms.get('M. Hafidi') == 1, r)
check('compteurs : seulement ceux qui ont des contenus du type', 'M. Naoufal' not in noms, noms)
r = visiteur.get(f'/api/enseignants/?content_type=exercise&difficulties[]=hard').json()
check('compteurs : avec la difficulté choisie', {x['nom'] for x in r} == {'M. Khalid Haddar', 'M. Hafidi', 'M. Naoufel'}, r)
r = visiteur.get(f'/api/difficulty-counts/?content_type=exercise&enseignants[]={haddar.id}').json()
check('difficultés : filtrées par enseignant', r == {'medium': 2, 'hard': 1}, r)

# --- Résultat de l'élève
ct = ContentType.objects.get_for_model(Content)
for path, st in (('q1', 'success'), ('q2', 'success'), ('q3', 'partial'), ('q4', 'review'), ('q5', 'failed')):
    QuestionProgress.objects.create(user=eleve, content_type=ct, object_id=str(c3.id), question_path=path, status=st)
p = carte(membre, c3.id)['user_progress']
check('résultat : réussies, en partie, à revoir', p == {'assessed': 5, 'success': 2, 'partial': 1, 'review': 2, 'total': 5}, p)

# --- Pilotage › Enseignants
check('pilotage : refusé à un élève', membre.get('/api/pilotage/enseignants/').status_code == 403)
check('pilotage : refusé à un visiteur', visiteur.get('/api/pilotage/enseignants/').status_code in (401, 403))
r = equipe.get('/api/pilotage/enseignants/').json()['results']
h = next(x for x in r if x['id'] == haddar.id)
check('pilotage : liste avec compte et nombre de contenus', h['contenus'] == 3 and h['compte']['username'] == 'khalid', h)
r = equipe.post('/api/pilotage/enseignants/', {'civilite': 'Mme', 'prenom': 'Salma', 'nom': 'Idrissi'}, format='json')
check('pilotage : créer', r.status_code == 201 and r.json()['nom_affiche'] == 'Mme Salma Idrissi', r.content[:200])
salma = r.json()['id']
r = equipe.post('/api/pilotage/enseignants/', {'nom': ''}, format='json')
check('pilotage : nom obligatoire', r.status_code == 400)
r = equipe.patch(f'/api/pilotage/enseignants/{salma}/', {'compte': 'khalid'}, format='json')
check('pilotage : un compte = un enseignant', r.status_code == 400, r.content[:200])
r = equipe.patch(f'/api/pilotage/enseignants/{salma}/', {'compte': 'inconnu'}, format='json')
check('pilotage : compte inconnu refusé', r.status_code == 400)
naoufel = Enseignant.objects.get(nom='Naoufel')
naoufal = Enseignant.objects.get(nom='Naoufal')
r = equipe.post(f'/api/pilotage/enseignants/{naoufal.id}/fusionner/', {'dans': naoufel.id}, format='json')
check('pilotage : fusionner', r.status_code == 200 and not Enseignant.objects.filter(pk=naoufal.id).exists()
      and set(ds.enseignants.all()) == {naoufel}, r.content[:200])
r = equipe.put(f'/api/pilotage/contenus/{c4.id}/enseignants/', {'ids': [salma, haddar.id]}, format='json')
check('pilotage : poser les enseignants d’un contenu', r.status_code == 200
      and [x['nom'] for x in r.json()['enseignants']] == ['Mme Salma Idrissi', 'M. Khalid Haddar'], r.content[:200])
check('pilotage : poser refusé à un élève',
      membre.put(f'/api/pilotage/contenus/{c4.id}/enseignants/', {'ids': []}, format='json').status_code == 403)
r = equipe.put(f'/api/pilotage/contenus/{c4.id}/enseignants/', {'ids': [999999]}, format='json')
check('pilotage : enseignant inconnu refusé', r.status_code == 400)
r = equipe.delete(f'/api/pilotage/enseignants/{salma}/')
check('pilotage : supprimer garde le contenu', r.status_code == 204 and list(c4.enseignants.all()) == [haddar])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
