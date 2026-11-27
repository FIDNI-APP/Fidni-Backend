"""Astuces par chapitre (bêta, 27/11/2026) : réservées à l'équipe, chargées depuis apps/astuces/data, liens « Sur Fidni »
vers la bonne question avec le numéro affiché par le site."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-astuces.sqlite3')
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

from apps.astuces.data import astuces_2sm  # noqa: E402
from apps.astuces.models import Astuce  # noqa: E402
from apps.astuces.views import numero_question  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    cache.clear()
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


eleve = User.objects.create_user('eleve_t', 'e@x.fr', 'x')
admin = User.objects.create_superuser('chef_t', 'c@x.fr', 'x')
staff = User.objects.create_user('staff_t', 's@x.fr', 'x', is_staff=True)

# ── Numérotation identique au site (sections : la numérotation repart à 1)
structure = {'blocks': [
    {'id': 'k-b1', 'type': 'section'}, {'id': 'k-b2', 'type': 'context'},
    {'id': 'k-b3', 'type': 'question'},
    {'id': 'k-b4', 'type': 'question', 'subQuestions': [{'id': 'k-b4-1'}, {'id': 'k-b4-2'}]},
    {'id': 'k-b5', 'type': 'section'}, {'id': 'k-b6', 'type': 'question'},
]}
check('question simple', numero_question(structure, 'k-b3') == ('k-b3', '1', 1))
check('sous-question', numero_question(structure, 'k-b4-2') == ('k-b4.k-b4-2', '2.2', 1))
check('nouvelle partie : repart à 1', numero_question(structure, 'k-b6') == ('k-b6', '1', 2))
check('question introuvable', numero_question(structure, 'zzz') is None)

# ── Chargement : chaque astuce a un chapitre du niveau, des étapes, un exemple
call_command('charger_astuces', verbosity=0)
n = Astuce.objects.filter(publie=True).count()
check('toutes les astuces chargées', n == len(astuces_2sm.ASTUCES), n)
incompletes = [a.slug for a in Astuce.objects.all()
               if not (a.methode and a.signaux and a.pourquoi and a.exemple_enonce and a.exemple_solution)]
check('astuces complètes (signaux, pourquoi, méthode, exemple)', not incompletes, incompletes)
check('chapitres des DS 1 et 2 seulement', set(Astuce.objects.values_list('chapitre__name', flat=True)) == {
    'Limites et continuité', 'Dérivation et étude des fonctions', 'Suites numériques'})
call_command('charger_astuces', verbosity=0)
check('rechargement sans doublon', Astuce.objects.count() == n)

# ── Lien vers une vraie question du site
level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
c = Content.objects.create(type='exam', title='DS test', author=admin, subject=subject, json_content={
    'import': {'cle': 'suites-limites-sanaa-2sm-ex08'}, 'blocks': [
        {'id': 'suites-limites-sanaa-2sm-ex08-b1', 'type': 'question'},
        {'id': 'suites-limites-sanaa-2sm-ex08-b2', 'type': 'question'},
        {'id': 'suites-limites-sanaa-2sm-ex08-b4', 'type': 'question'}]})
c.class_levels.add(level)

# ── Accès : équipe seulement
check('visiteur refusé', client().get('/api/astuces/').status_code in (401, 403))
check('élève refusé', client(eleve).get('/api/astuces/').status_code == 403)
check('staff accepté', client(staff).get('/api/astuces/').status_code == 200)
r = client(admin).get('/api/astuces/?niveau=2ème Bac SM')
check('administrateur : liste', r.status_code == 200 and len(r.data['astuces']) == n, r.status_code)
f = r.data['filtres']
check('filtres : chapitres dans l’ordre du programme', [x['nom'] for x in f['chapitres']] == [
    'Limites et continuité', 'Dérivation et étude des fonctions', 'Suites numériques'], f['chapitres'])
check('filtres : techniques et types', f['techniques'] and f['types'])
a = next(x for x in r.data['astuces'] if x['slug'] == 'absurde-divergence')
check('lien vers la question 3 (contenu existant)', any(
    li['contenu'] == c.id and li['question'] == '3' and li['url'] == f'/exams/{c.id}#question-suites-limites-sanaa-2sm-ex08-b4'
    for li in a['sur_le_site']), a['sur_le_site'])
check('référence introuvable ignorée', all(li['contenu'] == c.id for x in r.data['astuces'] for li in x['sur_le_site']))
r = client(admin).get('/api/astuces/absurde-limite-precise/')
check('détail', r.status_code == 200 and r.data['technique'] == 'Raisonnement par l’absurde', r.status_code)
check('détail : élève refusé', client(eleve).get('/api/astuces/absurde-limite-precise/').status_code == 403)

# ── Interrupteur « ouvert à tous » (équipe seulement)
check('état : fermé par défaut', client(eleve).get('/api/astuces/etat/').data == {'ouvert': False, 'peut_modifier': False})
check('état : élève ne peut pas ouvrir', client(eleve).patch('/api/astuces/etat/', {'ouvert': True}, format='json').status_code == 403)
r = client(admin).patch('/api/astuces/etat/', {'ouvert': True}, format='json')
check('état : l’admin ouvre la section', r.status_code == 200 and r.data['ouvert'] is True, r.data)
r = client(eleve).get('/api/astuces/')
check('ouverte : l’élève lit la liste', r.status_code == 200 and len(r.data['astuces']) == n and not r.data['peut_modifier'], r.status_code)
check('ouverte : pas de champs d’édition pour l’élève', 'references' not in r.data['astuces'][0])
check('ouverte : un visiteur lit aussi', client().get('/api/astuces/').status_code == 200)

# ── Modifier (équipe), et le rechargement du fichier ne l'écrase plus
check('élève : modification refusée', client(eleve).patch('/api/astuces/absurde-divergence/', {'titre': 'x'}, format='json').status_code == 403)
r = client(admin).patch('/api/astuces/absurde-divergence/', {
    'titre': 'Montrer qu’une suite diverge (modifié)', 'methode': ['Étape A', '  ', 'Étape B'],
    'sur_le_site': [{'id': str(c.id), 'question': '2'}, {'id': 'abc'}]}, format='json')
check('admin : modification enregistrée', r.status_code == 200 and r.data['titre'].endswith('(modifié)')
      and r.data['methode'] == ['Étape A', 'Étape B'], getattr(r, 'data', None))
check('lien saisi par numéro → bonne question',
      r.data['sur_le_site'] and r.data['sur_le_site'][0]['url'] == f'/exams/{c.id}#question-suites-limites-sanaa-2sm-ex08-b2',
      r.data['sur_le_site'])
call_command('charger_astuces', verbosity=0)
check('rechargement : la modification est gardée',
      Astuce.objects.get(slug='absurde-divergence').titre.endswith('(modifié)'))
check('titre obligatoire', client(admin).patch('/api/astuces/absurde-divergence/', {'titre': ''}, format='json').status_code == 400)

# ── Créer, masquer, supprimer
r = client(admin).post('/api/astuces/', {'chapitre': 'Suites numériques', 'titre': 'Comparer $u_n$ à une suite géométrique',
                                         'type_question': 'Limite d’une suite', 'technique': 'Comparaison',
                                         'methode': ['Majorer'], 'signaux': ['Un quotient']}, format='json')
check('admin : nouvelle astuce', r.status_code == 201 and r.data['slug'].startswith('comparer-u-n') is False
      and r.data['source'] == 'admin', getattr(r, 'data', None))
nouvelle = r.data['slug']
check('élève : création refusée', client(eleve).post('/api/astuces/', {'titre': 'x'}, format='json').status_code == 403)
check('masquer une astuce du fichier', client(admin).delete('/api/astuces/somme-telescopique/').status_code == 204
      and not Astuce.objects.get(slug='somme-telescopique').publie)
call_command('charger_astuces', verbosity=0)
check('rechargement : l’astuce masquée reste masquée', not Astuce.objects.get(slug='somme-telescopique').publie)
check('élève : l’astuce masquée n’apparaît pas', all(x['slug'] != 'somme-telescopique' for x in client(eleve).get('/api/astuces/').data['astuces']))
check('admin : l’astuce masquée apparaît (pour la rouvrir)', any(x['slug'] == 'somme-telescopique' and x['publie'] is False
                                                                for x in client(admin).get('/api/astuces/').data['astuces']))
check('supprimer une astuce créée sur le site', client(admin).delete(f'/api/astuces/{nouvelle}/').status_code == 204
      and not Astuce.objects.filter(slug=nouvelle).exists())
client(admin).patch('/api/astuces/etat/', {'ouvert': False}, format='json')
check('refermée : l’élève est de nouveau refusé', client(eleve).get('/api/astuces/').status_code == 403)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
