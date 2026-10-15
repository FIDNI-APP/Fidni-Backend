"""Contenus préparés par Claude, déposés en brouillon dans Pilotage › IA (ia/depot.py, commande ia_deposer).

Rien n'est publié au dépôt : l'administrateur voit le brouillon (aperçu, commentaires), le publie, demande une
correction à l'IA du serveur (figures déposées gardées) ou le rejette. Même clé qu'un contenu publié : mise à jour au
même lien à la publication. L'API Anthropic est simulée.
"""
import io
import json
import os
import runpy
import shutil
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-ia-depot.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false', 'IA_LANCEMENT': 'aucun',
                   'ANTHROPIC_API_KEY': 'cle-de-test', 'ANTHROPIC_WORKSPACE_ID': '',
                   'MEDIA_ROOT': os.path.join(tempfile.gettempdir(), 'fidni-ia-depot-media')})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.ia import client as ia_client, pipeline  # noqa: E402
from apps.ia.depot import deposer  # noqa: E402
from apps.ia.models import IAFile, IAJob  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


REPONSES, APPELS = [], []


def faux_appeler(system, messages, **kw):
    APPELS.append({'system': system, 'messages': messages})
    return REPONSES.pop(0), {'input_tokens': 1000, 'output_tokens': 500}


ia_client.appeler = faux_appeler


def image(fmt='PNG'):
    img = Image.new('RGB', (400, 300), 'white')
    ImageDraw.Draw(img).line((20, 280, 380, 20), fill='black', width=3)
    out = io.BytesIO()
    img.save(out, format=fmt)
    return out.getvalue()


FICHE = {
    'format': 'fidni-fiche/1', 'cle': 'depot-derivee-ex1', 'type': 'exercice',
    'titre': 'Dérivée de la fonction inverse et variations', 'niveaux': ['2ème Bac SM'],
    'chapitres': ['Dérivation et étude des fonctions'], 'difficulte': 'facile',
    'credit': 'M. Haddar, professeur de mathématiques', 'a_verifier': True,
    'source': {'document': 'serie-derivation.pdf', 'pages': '1', 'origine': 'autorise',
               'note': 'Document de M. Haddar, professeur de mathématiques, publié avec son accord.'},
    'blocs': [
        {'type': 'contexte', 'html': '<p>Soit $f(x) = \\dfrac{1}{x}$.</p><p><img src="figures/courbe.png" alt="Courbe de f"></p>'},
        {'type': 'question', 'html': '<p>Calculer $f\'(x)$.</p>', 'points': 2,
         'theoremes': ["Dérivée d'une fonction composée"], 'indice': '<p>Pense à la dérivée de $x^n$.</p>',
         'solution': '<p>$f\'(x) = -\\dfrac{1}{x^2}$.</p><p>Donc $f\'(x) &lt; 0$.</p>'},
        {'type': 'question', 'html': '<p>En déduire les variations de $f$.</p>', 'points': 1,
         'solution': '<p><strong>Méthode :</strong> signe de la dérivée.</p><p>Donc $f$ est décroissante sur chaque intervalle.</p>'},
    ],
}
COMMENTAIRES = ['Barème absent du document : 2 + 1 points proposés.', 'Question 2 : « Monter » corrigé en « Montrer ».']


def dossier(fiche=FICHE, commentaires=COMMENTAIRES, document=True):
    d = tempfile.mkdtemp(prefix='depot-')
    os.makedirs(os.path.join(d, 'figures'))
    with open(os.path.join(d, 'fiche.json'), 'w', encoding='utf-8') as f:
        json.dump(fiche, f, ensure_ascii=False)
    with open(os.path.join(d, 'commentaires.json'), 'w', encoding='utf-8') as f:
        json.dump(commentaires, f, ensure_ascii=False)
    with open(os.path.join(d, 'figures', 'courbe.png'), 'wb') as f:
        f.write(image())
    if document:
        os.makedirs(os.path.join(d, 'document'))
        with open(os.path.join(d, 'document', 'serie-derivation.png'), 'wb') as f:
            f.write(image())
    return d


admin = User.objects.create_superuser('patron', 'patron@x.fr', 'Motdepasse-solide-42')
eleve = User.objects.create_user('eleve', 'eleve@x.fr', 'Motdepasse-solide-42')
User.objects.create_user('Fidni', 'fidni@x.fr', None)
ad, el = APIClient(), APIClient()
ad.force_authenticate(admin)
el.force_authenticate(eleve)

# ---------------------------------------------------------------- dépôt : un brouillon, rien de publié
d1 = dossier()
sortie = io.StringIO()
call_command('ia_deposer', d1, stdout=sortie)
job = IAJob.objects.get(options__depot='claude', options__cle='depot-derivee-ex1')
check('commande : brouillon déposé, lien vers Pilotage › À valider',
      f'onglet=validation&brouillon={job.id}' in sortie.getvalue(), sortie.getvalue())
check('rien n’est publié au dépôt', not Content.objects.filter(json_content__import__cle='depot-derivee-ex1').exists())
check('brouillon prêt à relire, préparé par Claude', job.status == IAJob.PRET and job.kind == IAJob.IMPORT
      and job.options['remplacer'] is False, (job.status, job.options))
check('commentaires de Claude = points à vérifier', job.result['doutes'] == COMMENTAIRES)
check('figure déposée gardée', 'courbe.png' in job.result['figures'])
check('contrôle de la fiche : aucune erreur', all(not c['erreurs'] for c in job.result['controles']), job.result['controles'])
check('document source gardé (correction par l’IA possible)', IAFile.objects.filter(job=job).count() == 1)
check('solutions rédigées (a_verifier) : pas « solutions du document »', job.result['solutions_du_document'] is False)

r = ad.get('/api/pilotage/ia/')
check('onglet IA : sans les brouillons de Claude', r.status_code == 200
      and all(j['id'] != job.id for j in r.data['results']), r.data)
r = ad.get('/api/pilotage/brouillons/')
carte = next((j for j in r.data['results'] if j['id'] == job.id), None) if r.status_code == 200 else None
check('onglet À valider : la carte du brouillon', carte is not None and r.data['compte']['a_valider'] >= 1, r.data)
carte = carte or {}
check('carte : titre, type, niveau, chapitre', carte.get('titre') == FICHE['titre'] and carte.get('type') == FICHE['type']
      and carte.get('niveaux') == FICHE['niveaux'] and carte.get('chapitres') == FICHE['chapitres'], carte)
nb_feuilles = sum(len(b.get('sous_questions') or []) or 1 for b in FICHE['blocs'] if b.get('type') == 'question')
check('carte : questions, solutions, commentaires comptés', carte.get('questions') == nb_feuilles
      and carte.get('solutions') == nb_feuilles and carte.get('commentaires') == 2 and carte.get('erreurs') == 0, carte)
check('carte : début de l’énoncé sans balises', carte.get('extrait') and '<' not in carte['extrait'], carte.get('extrait'))
check('carte : pas encore publiée, pas une mise à jour', carte.get('publie') is None and carte.get('remplace') is None)
check('détail du brouillon : avec le résumé de sa carte', (ad.get(f'/api/pilotage/ia/{job.id}/').data.get('carte') or {}).get('questions') == nb_feuilles)
check('liste des brouillons : réservée à l’administrateur', el.get('/api/pilotage/brouillons/').status_code == 403)
check('statut inconnu refusé', ad.get('/api/pilotage/brouillons/?statut=nimporte').status_code == 400)
r = ad.get('/api/pilotage/direct/')
todo = r.data.get('todo', {}) if r.status_code == 200 else {}
check('Pilotage en direct : brouillons comptés à part de l’IA', todo.get('brouillons') == 1 and todo.get('ia_a_relire') == 0, todo)
r = ad.get(f'/api/pilotage/ia/{job.id}/')
ap = (r.data.get('apercus') or [{}])[0]
check('détail : aperçu au rendu du site (structure convertie, figure intégrée)', r.status_code == 200
      and ap.get('structure') and 'data:image/png;base64' in json.dumps(ap['structure']), r.status_code)
q2 = (ap.get('structure') or {}).get('blocks', [{}, {}, {}])[2]
check('indication : « Méthode » de la solution → bouton Indication', (q2.get('hint') or {}).get('html') == '<p>Signe de la dérivée.</p>', q2)
q1 = (ap.get('structure') or {}).get('blocks', [{}, {}])[1]
check('indication : champ « indice » → bouton Indication', 'dérivée de $x^n$' in (q1.get('hint') or {}).get('html', ''), q1)
check('réservé aux administrateurs', el.get(f'/api/pilotage/ia/{job.id}/').status_code == 403)

# Re-déposer la même clé tant que le brouillon attend : il est remplacé (pas de doublon de brouillon).
call_command('ia_deposer', dossier(dict(FICHE, difficulte='moyen'), ['Nouvelle version.']), stdout=io.StringIO())
check('re-dépôt en attente : même brouillon, nouvelle version',
      IAJob.objects.filter(options__depot='claude', options__cle='depot-derivee-ex1').count() == 1
      and IAJob.objects.get(pk=job.pk).result['fiches'][0]['difficulte'] == 'moyen'
      and IAJob.objects.get(pk=job.pk).result['doutes'] == ['Nouvelle version.'])

# ---------------------------------------------------------------- « Modifier » : correction par l'IA du serveur
REPONSES[:] = ['```json\n' + json.dumps({
    'fiches': [dict({k: v for k, v in FICHE.items() if k not in ('source', 'credit', 'a_verifier')}, difficulte='difficile')],
    'figures': [], 'doutes': ['Difficulté passée à « difficile » à ta demande.'], 'solutions_du_document': False},
    ensure_ascii=False) + '\n```']
r = ad.post(f'/api/pilotage/ia/{job.id}/corriger/', {'instruction': 'Mets la difficulté à difficile.'}, format='json')
pipeline.traiter(job.id)
job.refresh_from_db()
f = job.result['fiches'][0]
check('correction appliquée par l’IA du serveur', job.status == IAJob.PRET and f['difficulte'] == 'difficile', (job.status, job.error))
check('figure déposée gardée après la correction (l’IA ne l’a pas redéclarée)', 'courbe.png' in job.result['figures']
      and all(not c['erreurs'] for c in job.result['controles']), job.result.get('controles'))
check('source et crédit de la fiche gardés', f['source']['origine'] == 'autorise'
      and f['source']['note'].startswith('Document de M. Haddar') and f['credit'].startswith('M. Haddar'), f.get('source'))
check('document source envoyé à l’IA', APPELS and APPELS[-1]['messages'][0]['content'][1]['type'] == 'image')

# ---------------------------------------------------------------- « Valider et publier »
r = ad.post(f'/api/pilotage/ia/{job.id}/publier/', {'a_verifier': True}, format='json')
job.refresh_from_db()
c = Content.objects.filter(json_content__import__cle='depot-derivee-ex1').first()
check('publié : contenu créé, bandeau « à vérifier »', r.status_code == 200 and job.status == IAJob.PUBLIE and c
      and c.json_content.get('a_verifier') is True and c.difficulty == 'hard', (r.status_code, r.data if r.status_code != 200 else ''))

# ---------------------------------------------------------------- mise à jour d'un contenu publié
call_command('ia_deposer', dossier(dict(FICHE, titre='Dérivée de la fonction inverse (corrigé revu)'), []),
             stdout=(s2 := io.StringIO()))
maj = IAJob.objects.filter(options__depot='claude', options__cle='depot-derivee-ex1', status=IAJob.PRET).first()
check('nouveau dépôt après publication : brouillon de mise à jour', maj and maj.pk != job.pk and maj.options['remplacer']
      and maj.options['contenu']['id'] == c.id and f'#{c.id}' in s2.getvalue(), s2.getvalue())
check('mise à jour : la clé est gardée', maj.result['fiches'][0]['cle'] == 'depot-derivee-ex1')
r = ad.get('/api/pilotage/brouillons/?statut=publies')
check('onglet À valider › Publiés : le contenu publié', any((j.get('publie') or {}).get('id') == c.id for j in r.data['results']),
      r.data)
r = ad.get('/api/pilotage/brouillons/')
ligne = next((j for j in r.data['results'] if j['id'] == maj.id), {})
check('carte : « met à jour » le contenu publié', (ligne.get('remplace') or {}).get('id') == c.id, ligne)
check('rien ne change en ligne avant la validation', Content.objects.get(pk=c.pk).title == 'Dérivée de la fonction inverse et variations')
r = ad.post(f'/api/pilotage/ia/{maj.id}/publier/', {'a_verifier': False}, format='json')
c.refresh_from_db()
check('publié : même contenu mis à jour, même lien, pas de doublon', r.status_code == 200
      and c.title == 'Dérivée de la fonction inverse (corrigé revu)'
      and Content.objects.filter(json_content__import__cle='depot-derivee-ex1').count() == 1
      and not c.json_content.get('a_verifier'), (r.status_code, c.title, c.json_content.get('a_verifier')))

# ---------------------------------------------------------------- établissement d'origine (champ « école »)
from apps.caracteristics.models import School  # noqa: E402
from apps.things import importing  # noqa: E402

ibn = School.objects.create(name='Lycée Ibn Sina', city='Rabat', kind='lycee')
School.objects.create(name='Lycée Al Khawarizmi', city='Casablanca', kind='lycee')
School.objects.create(name='Lycée Al Khawarizmi', city='Safi', kind='lycee')
check('établissement trouvé par son nom (accents, casse)', importing.trouver_ecole('lycee ibn sina') == (ibn, None))
ecole, avert = importing.trouver_ecole('Lycée Al Khawarizmi')
check('nom ambigu : laissé vide, la ville est demandée', ecole is None and 'précise la ville' in avert, avert)
check('ambigu levé par la ville', importing.trouver_ecole({'nom': 'Lycée Al Khawarizmi', 'ville': 'Safi'})[0].city == 'Safi')
ecole, avert = importing.trouver_ecole('Lycée Imaginaire')
check('introuvable : laissé vide avec un avertissement (pas d’erreur)', ecole is None and 'introuvable' in avert, avert)
check('format refusé', any('ecole' in e for e in importing.validate(dict(FICHE, ecole={'ville': 'Rabat'}))[0]))
call_command('ia_deposer', dossier(dict(FICHE, cle='depot-ecole', titre='Avec établissement', ecole='Lycée Ibn Sina'), []),
             stdout=io.StringIO())
je = IAJob.objects.get(options__cle='depot-ecole')
r = ad.post(f'/api/pilotage/ia/{je.id}/publier/', {'a_verifier': True}, format='json')
ce = Content.objects.filter(json_content__import__cle='depot-ecole').first()
check('publié avec son établissement (« Donné au Lycée Ibn Sina »)', r.status_code == 200 and ce and ce.school_id == ibn.id,
      r.status_code)
call_command('ia_deposer', dossier(dict(FICHE, cle='depot-ecole', titre='Avec établissement', ecole='Lycée Imaginaire'), []),
             stdout=io.StringIO())
je2 = IAJob.objects.get(options__cle='depot-ecole', status=IAJob.PRET)
check('brouillon : avertissement visible si l’établissement est introuvable',
      any('introuvable' in a for c in je2.result['controles'] for a in c['avertissements']))
ad.post(f'/api/pilotage/ia/{je2.id}/publier/', {'a_verifier': True}, format='json')
ce.refresh_from_db()
check('mise à jour sans établissement trouvé : celui du contenu est gardé', ce.school_id == ibn.id)

# ---------------------------------------------------------------- modifier à la main dans l'éditeur (15/10/2026)
call_command('ia_deposer', dossier(dict(FICHE, cle='depot-editeur', titre='Fiche à retoucher')), stdout=io.StringIO())
je = IAJob.objects.get(options__cle='depot-editeur')
r = ad.get(f'/api/pilotage/ia/{je.id}/editeur/')
ed = r.data if r.status_code == 200 else {}
check('éditeur : le brouillon au format d’un contenu (niveaux, chapitres résolus, figure en data URI)',
      ed.get('type') == 'exercise' and ed.get('title') == 'Fiche à retoucher' and ed.get('difficulty') == 'easy'
      and len(ed.get('class_levels') or []) == 1 and len(ed.get('chapters') or []) == 1
      and 'data:image/png;base64,' in json.dumps(ed.get('json_content')) and ed.get('edite') is False, r.status_code)
check('éditeur réservé à l’administrateur', el.get(f'/api/pilotage/ia/{je.id}/editeur/').status_code == 403)
st = ed['json_content']
st['blocks'][1]['content']['html'] = '<p>Calculer la dérivée $f\'(x)$ (modifié à la main).</p>'
corps = {'type': 'exercise', 'title': 'Fiche retouchée à la main', 'json_content': st, 'difficulty': 'medium',
         'class_levels': [x['id'] for x in ed['class_levels']], 'chapters': [x['id'] for x in ed['chapters']],
         'theorems': [], 'school': None, 'subject': (ed.get('subject') or {}).get('id')}
r = ad.post(f'/api/pilotage/ia/{je.id}/editeur/', corps, format='json')
je.refresh_from_db()
e = (je.result.get('editions') or {}).get('depot-editeur') or {}
check('enregistré dans le brouillon, figure ramenée à « figures/courbe.png »', r.status_code == 200
      and e.get('title') == 'Fiche retouchée à la main' and 'figures/courbe.png' in json.dumps(e.get('json_content'))
      and 'data:image' not in json.dumps(e.get('json_content')), (r.status_code, getattr(r, 'data', None)))
carte = next((j for j in ad.get('/api/pilotage/brouillons/').data['results'] if j['id'] == je.id), {})
check('carte : version modifiée (titre, difficulté), marquée « modifiée »', carte.get('titre') == 'Fiche retouchée à la main'
      and carte.get('difficulte') == 'moyen' and carte.get('edite') is True, carte)
ap = (ad.get(f'/api/pilotage/ia/{je.id}/').data.get('apercus') or [{}])[0]
check('aperçu : version modifiée', 'modifié à la main' in json.dumps(ap.get('structure'), ensure_ascii=False)
      and ap.get('edite') is True, ap.get('titre'))
check('rouvert dans l’éditeur : la version modifiée', ad.get(f'/api/pilotage/ia/{je.id}/editeur/').data.get('title')
      == 'Fiche retouchée à la main')
r = ad.post(f'/api/pilotage/ia/{je.id}/corriger/', {'instruction': 'Change tout.'}, format='json')
check('correction par l’IA refusée après une modification à la main (repartirait de l’origine)', r.status_code == 409, r.status_code)
mauvais = dict(corps, json_content={'version': '2.1', 'blocks': [{'id': 'b', 'type': 'question', 'content': {
    'html': '<p><img src="data:image/png;base64,AAAA"></p>'}}]})
check('image collée en data URI refusée', ad.post(f'/api/pilotage/ia/{je.id}/editeur/', mauvais, format='json').status_code == 400)
check('niveau inconnu refusé', ad.post(f'/api/pilotage/ia/{je.id}/editeur/', dict(corps, class_levels=[99999]),
                                       format='json').status_code == 400)
r = ad.post(f'/api/pilotage/ia/{je.id}/publier/', {'a_verifier': True}, format='json')
cp = Content.objects.filter(json_content__import__cle='depot-editeur').first()
txt = json.dumps(cp.json_content, ensure_ascii=False) if cp else ''
check('publié : version modifiée (titre, difficulté, texte), figure publiée, crédit et bandeau gardés',
      r.status_code == 200 and cp.title == 'Fiche retouchée à la main' and cp.difficulty == 'medium'
      and 'modifié à la main' in txt and '/api/files/' in txt and 'figures/courbe.png' not in txt
      and cp.json_content.get('credit') and cp.json_content.get('a_verifier') is True
      and cp.chapters.count() == 1 and cp.class_levels.count() == 1, (r.status_code, cp and cp.title))

# ---------------------------------------------------------------- l'éditeur du site garde crédit, bandeau et clé
st_sans = {k: v for k, v in cp.json_content.items() if k not in ('credit', 'a_verifier', 'import')}
r = ad.patch(f'/api/contents/{cp.id}/', {'json_content': st_sans}, format='json')
cp.refresh_from_db()
check('modifier sur le site garde « Proposé par », le bandeau « à vérifier » et la clé d’import', r.status_code == 200
      and cp.json_content.get('credit') and cp.json_content.get('a_verifier') is True
      and (cp.json_content.get('import') or {}).get('cle') == 'depot-editeur', (r.status_code, list(cp.json_content)))

# « remplace » : un contenu publié qui a perdu sa clé (ancienne modification sur le site) est mis à jour au même lien.
Content.objects.filter(pk=cp.pk).update(json_content=st_sans)
call_command('ia_deposer', dossier(dict(FICHE, cle='depot-editeur', titre='Fiche retouchée à la main', remplace=cp.id)),
             stdout=(s3 := io.StringIO()))
jr = IAJob.objects.filter(options__cle='depot-editeur', status=IAJob.PRET).first()
check('« remplace » : brouillon de mise à jour du contenu visé', jr and jr.options.get('remplacer')
      and (jr.options.get('contenu') or {}).get('id') == cp.id and f'#{cp.id}' in s3.getvalue(), s3.getvalue())
r = ad.post(f'/api/pilotage/ia/{jr.id}/publier/', {'a_verifier': True}, format='json')
cp.refresh_from_db()
check('publié : même contenu, clé et crédit retrouvés, pas de doublon', r.status_code == 200
      and Content.objects.filter(title='Fiche retouchée à la main').count() == 1
      and (cp.json_content.get('import') or {}).get('cle') == 'depot-editeur' and cp.json_content.get('credit'),
      (r.status_code, getattr(r, 'data', None)))

# ---------------------------------------------------------------- refus clairs
bad = dict(FICHE, cle='depot-faux', titre='Fiche fausse', blocs=[{'type': 'question', 'html': '<p>?</p>', 'notions': ['tvi']}])
call_command('ia_deposer', dossier(bad), stdout=io.StringIO())
fx = IAJob.objects.get(options__cle='depot-faux')
check('fiche refusée par le contrôle : brouillon déposé avec ses erreurs (publication bloquée)',
      any('notions' in e for ctl in fx.result['controles'] for e in ctl['erreurs']))
r = ad.post(f'/api/pilotage/ia/{fx.id}/publier/', {'a_verifier': True}, format='json')
carte = next((j for j in ad.get('/api/pilotage/brouillons/').data['results'] if j['id'] == fx.id), {})
check('carte : erreurs comptées', carte.get('erreurs', 0) >= 1, carte)
check('publication refusée tant que la fiche a des erreurs', r.status_code == 400
      and not Content.objects.filter(json_content__import__cle='depot-faux').exists(), r.status_code)
vide = tempfile.mkdtemp()
try:
    call_command('ia_deposer', vide, stdout=io.StringIO())
    check('dossier sans fiche.json refusé', False)
except Exception as exc:
    check('dossier sans fiche.json refusé', 'fiche.json' in str(exc), exc)
shutil.rmtree(vide)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
