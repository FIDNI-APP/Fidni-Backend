"""Contenus préparés par Claude (14/10/2026) : déposés en brouillon dans Pilotage › À valider, publiés par l'administrateur.

Natsu : « publier d'abord dans un espace admin, avec les mêmes styles que pour les élèves, et une option valider et
publier ou modifier ». Les fiches préparées à la main (skill importer-contenu, contenus/outils/deposer.sh) ne sont
plus publiées directement : chacune devient un travail de l'IA « prêt à relire » (IAJob kind import, une fiche par
travail), avec ses figures et les commentaires qui allaient au rapport (`doutes`). L'onglet « À valider » (à part de
l'onglet IA, demande de Natsu) les montre en cartes, puis chacun au rendu du site avec les commentaires de Claude :
« Valider et publier », « Modifier » (l'IA du serveur corrige la fiche, document source à l'appui), « Rejeter ».

Même clé qu'un contenu déjà publié : le brouillon le met à jour à la publication (`options.remplacer`), au même
lien, progression des élèves conservée. Re-déposer la même clé remplace le brouillon encore en attente.
"""
import base64
import json
import os
import re

from django.utils import timezone

from . import pipeline
from .models import IAFile, IAJob

DEPOT = 'claude'
FIGURE = re.compile(r'^[A-Za-z0-9._-]+\.(png|jpe?g|webp)$', re.IGNORECASE)
MIME = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.webp': 'image/webp', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class DepotErreur(Exception):
    pass


def travaux():
    """Les brouillons déposés par Claude (exclus de l'onglet IA)."""
    return IAJob.objects.filter(kind=IAJob.IMPORT, options__depot=DEPOT)


def _texte(html, n=200):
    """Début lisible d'un énoncé (sans balises), coupé hors d'une formule."""
    import html as h
    t = re.sub(r'\s+', ' ', h.unescape(re.sub(r'<[^>]+>', ' ', html or ''))).strip()
    if len(t) <= n:
        return t
    t = t[:n].rsplit(' ', 1)[0]
    if t.count('$') % 2:
        t = t[:t.rindex('$')].rstrip()
    return t + ' …'


def carte(job):
    """Résumé d'un brouillon pour sa carte : de quoi juger d'un coup d'œil (questions, solutions, alertes)."""
    r = job.result or {}
    fiches = [f for f in r.get('fiches') or [] if isinstance(f, dict)]
    f = fiches[0] if fiches else {}
    blocs = [b for b in f.get('blocs') or [] if isinstance(b, dict)]
    questions = [b for b in blocs if b.get('type') == 'question']
    feuilles = [s for b in questions for s in ([x for x in b.get('sous_questions') or [] if isinstance(x, dict)] or [b])]
    controles = [c for c in r.get('controles') or [] if isinstance(c, dict)]
    ecole = f.get('ecole')
    if isinstance(ecole, dict):
        ecole = ecole.get('nom', '') + (f" ({ecole['ville']})" if ecole.get('ville') else '')
    premier = next((b.get('html') for b in blocs if b.get('type') in ('contexte', 'question') and b.get('html')), '')
    if not premier and f.get('sections'):
        s0 = f['sections'][0] if isinstance(f['sections'][0], dict) else {}
        premier = s0.get('html') or ''
    from apps.things import importing
    try:
        theoremes = importing.theoremes_des_questions(f)
    except Exception:  # fiche mal formée : la carte le dit par ses erreurs
        theoremes = []
    publies = r.get('publies') or []
    e = (r.get('editions') or {}).get(f.get('cle'))  # modifiée dans l'éditeur
    if e:
        from .pipeline import DIFF_FICHE
        f = {**f, 'titre': e['title'], 'niveaux': e.get('niveaux') or [], 'chapitres': e.get('chapitres') or [],
             'difficulte': DIFF_FICHE.get(e.get('difficulty'))}
    return {
        'id': job.id, 'status': job.status, 'etape': job.etape, 'error': job.error,
        'created_at': job.created_at.isoformat(), 'updated_at': job.updated_at.isoformat(),
        'cle': f.get('cle') or job.options.get('cle'), 'titre': f.get('titre') or job.options.get('document'),
        'type': f.get('type'), 'niveaux': f.get('niveaux') or [], 'chapitres': f.get('chapitres') or [],
        'difficulte': f.get('difficulte'), 'credit': f.get('credit') or '', 'ecole': ecole or '',
        'document': job.options.get('document') or '',
        'extrait': _texte(premier),
        'questions': len(feuilles), 'parties': sum(1 for b in blocs if b.get('type') == 'partie'),
        'sections': len(f.get('sections') or []),
        'solutions': sum(1 for q in feuilles if (q.get('solution') or '').strip()),
        'indications': sum(1 for q in feuilles if (q.get('indice') or '').strip()),
        'figures': len(r.get('figures_spec') or []),
        'theoremes': theoremes[:8], 'nb_theoremes': len(theoremes),
        'commentaires': len(r.get('doutes') or []) + len(r.get('problemes') or []),
        'erreurs': sum(len(c.get('erreurs') or []) for c in controles) + len(r.get('erreurs_figures') or []),
        'doublons': sum(len(c.get('doublons') or []) for c in controles),
        'avertissements': sum(len(c.get('avertissements') or []) for c in controles),
        'a_verifier': f.get('a_verifier', True) is not False,
        'remplace': job.options.get('contenu') if job.options.get('remplacer') else None,
        'publie': publies[0] if publies else None,
        'edite': bool(e),
        'corrections': sum(1 for h in job.history or [] if h.get('qui') not in ('Claude', None)
                           and h.get('texte') not in ('Rejeté',) and not str(h.get('texte', '')).startswith('Publié')),
    }


def _lire(dossier):
    chemin = os.path.join(dossier, 'fiche.json')
    if not os.path.isfile(chemin):
        raise DepotErreur(f'fiche.json introuvable dans {dossier}')
    with open(chemin, encoding='utf-8') as f:
        fiche = json.load(f)
    if not isinstance(fiche, dict) or not fiche.get('cle'):
        raise DepotErreur('fiche.json : objet avec une « cle » attendu')
    commentaires = []
    chemin = os.path.join(dossier, 'commentaires.json')
    if os.path.isfile(chemin):
        with open(chemin, encoding='utf-8') as f:
            commentaires = json.load(f)
        if not isinstance(commentaires, list) or not all(isinstance(c, str) for c in commentaires):
            raise DepotErreur('commentaires.json : liste de textes attendue')
    return fiche, [c.strip() for c in commentaires if c.strip()]


def _figures(dossier):
    """{nom: (signature, png base64)} des figures du dossier ; la signature marque une figure déposée (gardée
    telle quelle par une correction de l'IA, pipeline._figures)."""
    images = {}
    d = os.path.join(dossier, 'figures')
    for nom in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not FIGURE.match(nom):
            continue
        with open(os.path.join(d, nom), 'rb') as f:
            spec = {'nom': nom, 'depot': True}
            images[nom] = (json.dumps(spec, sort_keys=True), base64.b64encode(f.read()).decode())
    return images


def _documents(dossier):
    """Document source (dossier « document/ ») : sert à l'IA du serveur pour « Demander une correction »."""
    d = os.path.join(dossier, 'document')
    out = []
    for nom in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        mime = MIME.get(os.path.splitext(nom)[1].lower())
        if mime:
            with open(os.path.join(d, nom), 'rb') as f:
                out.append((nom, mime, f.read()))
    return out


def deposer(dossier):
    """Crée (ou remplace, même clé encore en attente) le brouillon d'une fiche → (travail, créé ?)."""
    from apps.things.models import Content

    fiche, commentaires = _lire(dossier)
    cle = fiche['cle']
    existant = Content.objects.filter(json_content__import__cle=cle).only('id', 'title', 'type').first()
    if existant is None and isinstance(fiche.get('remplace'), int):  # contenu publié visé par son id
        existant = Content.objects.filter(pk=fiche['remplace']).only('id', 'title', 'type').first()
    src = fiche.get('source') if isinstance(fiche.get('source'), dict) else {}
    options = {
        'depot': DEPOT, 'cle': cle, 'document': src.get('document') or fiche.get('titre') or cle,
        'origine': src.get('origine'), 'credit': fiche.get('credit') or '', 'note': src.get('note') or '',
        'niveaux': fiche.get('niveaux') or [], 'remplacer': existant is not None,
        'contenu': {'id': existant.id, 'titre': existant.title, 'type': existant.type} if existant else None,
    }
    job = (IAJob.objects.filter(kind=IAJob.IMPORT, options__depot=DEPOT, options__cle=cle,
                                status__in=[IAJob.PRET, IAJob.ERREUR, IAJob.EN_ATTENTE]).order_by('-created_at').first())
    cree = job is None
    if cree:
        job = IAJob(kind=IAJob.IMPORT, created_by=None)
    job.options = options
    job.status, job.etape, job.error = IAJob.PRET, '', ''
    images = _figures(dossier)
    fiches = [fiche]
    rapports = pipeline._controler(job, fiches, images)
    avertissements = []
    if existant:
        avertissements.append(f'Mise à jour du contenu déjà publié « {existant.title} » (même clé « {cle} ») : '
                              'même lien, progression des élèves conservée.')
    pipeline._bilan(job, fiches, [json.loads(sig) for sig, _ in images.values()], images, commentaires, [],
                    not fiche.get('a_verifier', True), rapports, [], avertissements)
    job.history = (job.history or []) + [{'date': timezone.now().isoformat(), 'qui': 'Claude',
                                          'texte': 'Déposé pour relecture' if cree else 'Nouvelle version déposée'}]
    job.save()
    documents = _documents(dossier)
    if documents:
        job.files.all().delete()
        IAFile.objects.bulk_create([IAFile(job=job, name=n, mime=m, data=d) for n, m, d in documents])
    return job, cree
