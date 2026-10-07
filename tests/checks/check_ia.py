"""IA des administrateurs (Pilotage › IA) : import d'un document, correction d'un signalement.

L'API Anthropic est simulée (réponses écrites à l'avance) : on vérifie tout ce qui l'entoure —
permissions, contrôle des fiches, reprise automatique, clés jamais écrasées, publication « à
vérifier », proposition de correction avant / après, application et conflits.
"""
import io
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-ia.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false', 'IA_LANCEMENT': 'aucun',
                   'ANTHROPIC_API_KEY': 'cle-de-test', 'ANTHROPIC_WORKSPACE_ID': '',
                   'MEDIA_ROOT': os.path.join(tempfile.gettempdir(), 'fidni-ia-media')})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.ia import client as ia_client, pipeline  # noqa: E402
from apps.ia.client import IAErreur  # noqa: E402
from apps.ia.models import IAFile, IAJob  # noqa: E402
from apps.things.models import Content, ContentReport  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# ---------------------------------------------------------------- IA simulée
REPONSES, APPELS = [], []


def faux_appeler(system, messages, **kw):
    APPELS.append({'system': system, 'messages': messages})
    r = REPONSES.pop(0)
    if isinstance(r, Exception):
        raise r
    return r, {'input_tokens': 1000, 'output_tokens': 500}


ia_client.appeler = faux_appeler


def fiche_json(cle='test-ia-ex1', notion='Dérivée', solution=r'<p>$f(x)=\frac{1}{x}$ donc $f\'(x)=-\dfrac{1}{x^2}$.</p>'):
    # Écrit comme le ferait l'IA, y compris une barre oblique non doublée (« \frac ») à réparer.
    return ('Voici les fiches.\n```json\n{"fiches": [{"cle": "' + cle + '", "type": "exercice", '
            '"titre": "Dérivée de la fonction inverse", "niveaux": ["2ème Bac SM"], '
            '"chapitres": ["Dérivation et étude des fonctions"], "difficulte": "facile", "source": {"document": "x"}, '
            '"a_verifier": false, "blocs": [{"type": "contexte", "html": "<p>Soit $f(x)=\\\\dfrac{1}{x}$.</p>'
            '<p><img src=\\"figures/courbe.png\\" alt=\\"Courbe de f\\"></p>"}, '
            '{"type": "question", "html": "", "sous_questions": ['
            '{"html": "<p>Calculer $f\'(x)$.</p>", "points": 2, "notions": ["' + notion + '"], "solution": "'
            + solution.replace('"', '\\"') + '"}, '
            '{"html": "<p>En déduire les variations de $f$.</p>", "points": 1, "solution": "<p>Méthode : signe de la dérivée.</p>'
            '<p>Donc $f$ est décroissante sur chaque intervalle.</p>"}]}]}], '
            '"figures": [{"nom": "courbe.png", "image": 1, "cadre": [0.1, 0.1, 0.6, 0.7]}], '
            '"doutes": ["Exercice : barème absent du document, 2 + 1 points proposés."], '
            '"solutions_du_document": false}\n```')


def png():
    img = Image.new('RGB', (400, 300), 'white')
    ImageDraw.Draw(img).line((20, 280, 380, 20), fill='black', width=3)
    out = io.BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
eleve = User.objects.create_user('eleve', 'eleve@x.fr', 'Motdepasse-solide-42')
admin = User.objects.create_superuser('patron', 'patron@x.fr', 'Motdepasse-solide-42')
# Contenu déjà publié avec la clé que l'IA va proposer : il ne doit JAMAIS être écrasé.
ancien = Content.objects.create(type='exercise', title='Ancien', author=editorial,
                                json_content={'version': '2.1', 'blocks': [], 'import': {'cle': 'test-ia-ex1'}})

anon, el, ad = APIClient(), APIClient(), APIClient()
el.force_authenticate(eleve)
ad.force_authenticate(admin)

# ---------------------------------------------------------------- permissions
check('visiteur refusé', anon.get('/api/pilotage/ia/').status_code in (401, 403))
check('élève refusé', el.get('/api/pilotage/ia/').status_code == 403)
r = el.post('/api/pilotage/ia/import/', {'origine': 'autorise', 'fichiers': SimpleUploadedFile('a.png', png(), 'image/png')},
            format='multipart')
check('élève : envoi refusé', r.status_code == 403, r.status_code)
r = ad.get('/api/pilotage/ia/')
check('admin : liste + IA configurée', r.status_code == 200 and r.data['configuree'] is True, r.data)

# ---------------------------------------------------------------- envoi d'un document
r = ad.post('/api/pilotage/ia/import/', {'fichiers': SimpleUploadedFile('a.png', png(), 'image/png')}, format='multipart')
check('droits du document obligatoires', r.status_code == 400 and 'origine' in r.data, r.data)
r = ad.post('/api/pilotage/ia/import/', {'origine': 'autorise', 'fichiers': SimpleUploadedFile('a.txt', b'x', 'text/plain')},
            format='multipart')
check('format refusé (texte)', r.status_code == 400 and 'fichiers' in r.data, r.data)
r = ad.post('/api/pilotage/ia/import/', {'origine': 'autorise', 'credit': 'M. Haddar, professeur de mathématiques',
                                         'niveau': '2ème Bac SM', 'consignes': 'Un seul exercice.',
                                         'fichiers': SimpleUploadedFile('serie.png', png(), 'image/png')},
            format='multipart')
check('document accepté, travail en attente', r.status_code == 201 and r.data['status'] == 'en_attente', r.data)
job = IAJob.objects.get(pk=r.data['id'])
check('document gardé en base (privé)', IAFile.objects.filter(job=job).count() == 1)

# Réponses : 1) fiche avec une notion inconnue → 2) reprise corrigée → 3) relecture (un point à vérifier).
REPONSES[:] = [fiche_json(notion='notion-inventee'), fiche_json(),
               '```json\n{"problemes": [{"gravite": "a_verifier", "ou": "Question 1", "description": "Barème à confirmer."}],'
               ' "fiches": null}\n```']
pipeline.traiter(job.pk)
job.refresh_from_db()
check('brouillon prêt', job.status == 'pret', (job.status, job.error))
check('3 appels : rédaction, reprise, relecture', len(APPELS) == 3, len(APPELS))
check('la reprise cite l’erreur du contrôle', 'notion inconnue' in APPELS[1]['messages'][-1]['content'])
check('champs du serveur jamais remontrés à l’IA', all('"credit"' not in m['content'] and '"source"' not in m['content']
      for m in APPELS[2]['messages'] if m['role'] == 'assistant'))
check('consigne : règles + annexes de la base', 'Annexe A' in APPELS[0]['system'] and '2ème Bac SM' in APPELS[0]['system']
      and 'Annexe C' in APPELS[0]['system'])
premier = APPELS[0]['messages'][0]['content']
check('document envoyé en image + options de l’admin', premier[1]['type'] == 'image'
      and 'Un seul exercice.' in premier[-1]['text'] and '2ème Bac SM' in premier[-1]['text'])
f = job.result['fiches'][0]
check('clé déjà publiée : jamais écrasée, suffixée', f['cle'] == 'test-ia-ex1-2', f['cle'])
check('champs du serveur : source, crédit ; a_verifier de l’IA ignoré',
      f['source']['origine'] == 'autorise' and f['credit'].startswith('M. Haddar') and 'a_verifier' not in f)
check('barre oblique réparée (\\frac intact)', r'\frac{1}{x}' in f['blocs'][1]['sous_questions'][0]['solution'],
      f['blocs'][1]['sous_questions'][0]['solution'])
check('figure découpée', 'courbe.png' in job.result['figures'])
check('contrôle au vert', all(not c['erreurs'] for c in job.result['controles']), job.result['controles'])
check('doutes et relecture conservés', len(job.result['doutes']) == 1 and job.result['problemes'][0]['gravite'] == 'a_verifier')

r = ad.get(f'/api/pilotage/ia/{job.pk}/')
ap = r.data['apercus'][0]
html = str(ap['structure'])
check('aperçu : structure du site, figure en data URI', r.status_code == 200 and ap['type'] == 'exercise'
      and 'data:image/png;base64,' in html, r.data.get('apercus'))
check('élève : détail refusé', el.get(f'/api/pilotage/ia/{job.pk}/').status_code == 403)

# ---------------------------------------------------------------- correction demandée par l'admin
r = ad.post(f'/api/pilotage/ia/{job.pk}/corriger/', {'instruction': ''}, format='json')
check('demande vide refusée', r.status_code == 400)
r = ad.post(f'/api/pilotage/ia/{job.pk}/corriger/', {'instruction': 'Mets la difficulté à moyen.'}, format='json')
check('demande enregistrée', r.status_code == 200 and r.data['status'] == 'en_attente', r.data)
REPONSES[:] = [fiche_json().replace('"facile"', '"moyen"')]
pipeline.traiter(job.pk)
job.refresh_from_db()
check('demande appliquée, même clé', job.status == 'pret' and job.result['fiches'][0]['difficulte'] == 'moyen'
      and job.result['fiches'][0]['cle'] == 'test-ia-ex1-2', (job.status, job.error))
check('demande transmise à l’IA', 'Mets la difficulté à moyen.' in APPELS[-1]['messages'][-1]['content'])
check('historique', [h['qui'] for h in job.history][-2:] == ['patron', 'ia'], job.history)

ad.post(f'/api/pilotage/ia/{job.pk}/corriger/', {'instruction': 'Autre chose.'}, format='json')
REPONSES[:] = [IAErreur('Crédit Anthropic épuisé : recharger le compte.')]
pipeline.traiter(job.pk)
job.refresh_from_db()
check('demande échouée : brouillon intact et publiable', job.status == 'pret' and 'Crédit' in job.error
      and job.result['fiches'][0]['difficulte'] == 'moyen', (job.status, job.error))

# ---------------------------------------------------------------- publication
r = ad.post(f'/api/pilotage/ia/{job.pk}/publier/', {'a_verifier': True}, format='json')
check('publié', r.status_code == 200 and r.data['status'] == 'publie', r.data)
c = Content.objects.get(json_content__import__cle='test-ia-ex1-2')
check('auteur éditorial, bandeau « à vérifier », trace IA',
      c.author.username == 'Fidni' and c.json_content.get('a_verifier') is True
      and c.json_content['import']['ia']['travail'] == job.pk and c.json_content.get('credit', '').startswith('M. Haddar'))
check('niveau, chapitre, difficulté', list(c.class_levels.values_list('name', flat=True)) == ['2ème Bac SM']
      and c.chapters.count() == 1 and c.difficulty == 'medium')
check('figure publiée', FileAttachment.objects.filter(object_id=c.pk).count() == 1
      and '/api/files/' in str(c.json_content['blocks'][0]))
ancien.refresh_from_db()
check('contenu existant intact', ancien.title == 'Ancien' and ancien.json_content['import']['cle'] == 'test-ia-ex1')
r = ad.post(f'/api/pilotage/ia/{job.pk}/publier/', {'a_verifier': True}, format='json')
check('double publication refusée', r.status_code == 409, r.status_code)

# Doublon probable (même titre) : publication seulement si l'admin le confirme.
r = ad.post('/api/pilotage/ia/import/', {'origine': 'original', 'fichiers': SimpleUploadedFile('b.png', png(), 'image/png')},
            format='multipart')
job2 = IAJob.objects.get(pk=r.data['id'])
REPONSES[:] = [fiche_json(cle='autre-cle'), '```json\n{"problemes": [], "fiches": null}\n```']
pipeline.traiter(job2.pk)
job2.refresh_from_db()
check('doublon signalé, pas une erreur de l’IA', job2.status == 'pret' and job2.result['controles'][0]['doublons']
      and not job2.result['controles'][0]['erreurs'], job2.result.get('controles'))
r = ad.post(f'/api/pilotage/ia/{job2.pk}/publier/', {'a_verifier': True}, format='json')
check('doublon non confirmé : refusé', r.status_code == 400 and 'doublon' in r.data['detail'], r.data)
r = ad.post(f'/api/pilotage/ia/{job2.pk}/rejeter/', format='json')
check('rejet : document effacé', r.status_code == 200 and not IAFile.objects.filter(job=job2).exists())

# Erreur de l'API : travail en erreur, relançable.
r = ad.post('/api/pilotage/ia/import/', {'origine': 'original', 'fichiers': SimpleUploadedFile('c.png', png(), 'image/png')},
            format='multipart')
job3 = IAJob.objects.get(pk=r.data['id'])
REPONSES[:] = [IAErreur('Crédit Anthropic épuisé : recharger le compte.')]
pipeline.traiter(job3.pk)
job3.refresh_from_db()
check('erreur lisible', job3.status == 'erreur' and 'Crédit' in job3.error)
r = ad.post(f'/api/pilotage/ia/{job3.pk}/relancer/', format='json')
check('relance', r.status_code == 200 and r.data['status'] == 'en_attente', r.data)
REPONSES[:] = ['pas de json', 'toujours pas']
pipeline.traiter(job3.pk)
job3.refresh_from_db()
check('réponse illisible deux fois : erreur claire', job3.status == 'erreur' and 'illisible' in job3.error, job3.error)

# ---------------------------------------------------------------- signalement
bloc = c.json_content['blocks'][1]
sq1 = bloc['subQuestions'][0]
rep = ContentReport.objects.create(content=c, user=eleve, reason='solution', item_path=f"{bloc['id']}.{sq1['id']}",
                                   item_label='Question 1.1', description='Il manque le domaine.')
r = el.post(f'/api/pilotage/signalements/{rep.pk}/ia/', format='json')
check('élève : correction IA refusée', r.status_code == 403)
r = ad.post(f'/api/pilotage/signalements/{rep.pk}/ia/', format='json')
check('travail de correction créé', r.status_code == 201, r.data)
sj = IAJob.objects.get(pk=r.data['id'])
nouvelle = r'<p>Méthode : dériver un quotient.</p><p>$f$ est dérivable sur $\mathbb{R}^*$ et $f\'(x)=-\dfrac{1}{x^2}$ pour $x<0$ ou $x>0$.</p><p>Donc $f\'(x)=-\dfrac{1}{x^2}$.</p>'
mauvais = ('```json\n{"fonde": "oui", "explication": "x", "modifications": [{"bloc": "inconnu", "sous_question": null, '
           '"champ": "solution", "html": "<p>x</p>"}], "doutes": []}\n```')
bon = ('```json\n{"fonde": "oui", "explication": "Le domaine de dérivabilité n’était pas précisé.", "modifications": '
       '[{"bloc": "' + bloc['id'] + '", "sous_question": "' + sq1['id'] + '", "champ": "solution", "html": "'
       + nouvelle.replace('\\', '\\\\').replace('"', '\\"') + '"}], "doutes": []}\n```')
REPONSES[:] = [mauvais, bon]
pipeline.traiter(sj.pk)
sj.refresh_from_db()
check('proposition prête après une reprise', sj.status == 'pret' and len(APPELS[-1]['messages']) == 3, (sj.status, sj.error))
check('extrait balisé, endroit signalé', 'signale="oui"' in APPELS[-2]['messages'][0]['content']
      and 'Il manque le domaine.' in APPELS[-2]['messages'][0]['content'])
m = sj.result['modifications'][0]
check('avant / après, libellé', m['ou'] == 'Question 1.1' and m['avant'] == sq1['solution']['html']
      and '&lt;' in m['apres'] and sj.result['fonde'] == 'oui', m)
check('contenu pas encore modifié', Content.objects.get(pk=c.pk).json_content['blocks'][1]['subQuestions'][0]['solution']['html']
      == sq1['solution']['html'])
r = ad.get(f'/api/pilotage/signalements/{rep.pk}/ia/derniere/')
check('dernière proposition du signalement', r.status_code == 200 and r.data['id'] == sj.pk)

# Conflit : le contenu change entre la proposition et l'application.
js = Content.objects.get(pk=c.pk).json_content
js['blocks'][1]['subQuestions'][0]['solution']['html'] = '<p>modifié à la main</p>'
Content.objects.filter(pk=c.pk).update(json_content=js)
r = ad.post(f'/api/pilotage/ia/{sj.pk}/appliquer/', {'a_verifier': True}, format='json')
check('conflit détecté, rien écrasé', r.status_code == 409 and Content.objects.get(pk=c.pk).json_content['blocks'][1]
      ['subQuestions'][0]['solution']['html'] == '<p>modifié à la main</p>', r.data)
js['blocks'][1]['subQuestions'][0]['solution']['html'] = sq1['solution']['html']
js.pop('a_verifier', None)
Content.objects.filter(pk=c.pk).update(json_content=js)
r = ad.post(f'/api/pilotage/ia/{sj.pk}/appliquer/', {'a_verifier': True}, format='json')
c.refresh_from_db()
rep.refresh_from_db()
check('correction appliquée', r.status_code == 200 and c.json_content['blocks'][1]['subQuestions'][0]['solution']['html']
      == m['apres'], r.data)
check('bandeau « à vérifier » remis, trace, signalement clos', c.json_content.get('a_verifier') is True
      and c.json_content['modifs_ia'][0]['signalement'] == rep.pk and rep.status == 'resolved' and rep.handled_by == admin)
r = ad.post(f'/api/pilotage/ia/{sj.pk}/appliquer/', {'a_verifier': True}, format='json')
check('double application refusée', r.status_code == 409)

# Image : l'IA ne peut pas en ajouter.
norm, err = pipeline._controler_modif(c.json_content, {'bloc': bloc['id'], 'sous_question': sq1['id'], 'champ': 'solution',
                                                       'html': '<p><img src="https://x.fr/a.png" alt="a"></p>'}, 1)
check('image ajoutée refusée', any('image' in e for e in err), err)
norm, err = pipeline._controler_modif(c.json_content, {'bloc': bloc['id'], 'sous_question': None, 'champ': 'solution',
                                                       'html': '<p>x</p>'}, 1)
check('solution sur une question à sous-questions refusée', norm is None and err, err)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
