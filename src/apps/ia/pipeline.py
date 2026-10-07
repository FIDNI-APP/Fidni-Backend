"""Travail de l'IA, exécuté hors requête web (commande `ia_traiter`, lancée par les vues).

Import d'un document :
  lecture et rédaction des fiches → découpe des figures → contrôle automatique (le même que
  contenus/outils/verifier.sh) → l'IA corrige ce que le contrôle refuse (2 fois au plus) →
  relecture critique par l'IA, document sous les yeux → brouillon « prêt à relire ».
  L'administrateur relit, demande une correction, publie ou rejette. Rien n'est publié sans lui.

Correction d'un signalement :
  l'IA vérifie le signalement, propose la correction minimale (avant / après) ;
  l'administrateur l'applique ou la rejette.
"""
import base64
import json
import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.things import importing

from . import client, consignes, documents
from .client import IAErreur
from .models import IAJob

MAX_REPRISES = 2  # corrections automatiques après le contrôle
ORIGINES = {
    'autorise': 'Document publié avec l’accord de son auteur.',
    'officiel': 'Sujet officiel (document public).',
    'original': 'Contenu rédigé pour Fidni.',
}
CHAMPS = {'enonce': 'content', 'solution': 'solution', 'contenu': 'content'}
DUREE_MAX = timedelta(minutes=30)  # sans nouvelles du travail au-delà : interrompu


# --------------------------------------------------------------------------- outils

def _etape(job, texte, **champs):
    job.etape = texte
    job.heartbeat = timezone.now()
    for k, v in champs.items():
        setattr(job, k, v)
    job.save()


def _compter(job, usage):
    for k in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
        if usage.get(k):
            job.usage[k] = job.usage.get(k, 0) + usage[k]
    job.usage['appels'] = job.usage.get('appels', 0) + 1


def _appeler(job, messages, system=None):
    texte, usage = client.appeler(system or consignes.systeme(), messages)
    _compter(job, usage)
    return texte


def _reparer_barres(brut):
    """Formules LaTeX dans du JSON : une barre oblique non doublée (« \\frac ») est soit invalide
    (« \\a »), soit pire, lue comme un caractère de contrôle (« \\f », « \\t », « \\n » suivis d'une
    lettre : \\frac, \\times, \\neq). On double ces barres ; un JSON correct n'est pas modifié."""
    def rep(m):
        if m.group(0) == '\\\\':
            return m.group(0)
        c, suite = m.group(1), m.group(2)
        if c in '"/':
            return m.group(0)
        if c == 'u' and re.match(r'[0-9a-fA-F]{4}', suite):
            return m.group(0)
        if c in 'bfnrt' and not suite[:1].isalpha():
            return m.group(0)
        return '\\\\' + c + suite
    return re.sub(r'\\\\|\\(.)(.{0,4})', rep, brut, flags=re.S)


def extraire_json(texte):
    """Le bloc ```json de la réponse (le dernier), sinon le plus grand objet { … }."""
    blocs = re.findall(r'```(?:json)?\s*\n(.*?)\n```', texte, flags=re.S)
    brut = blocs[-1] if blocs else texte[texte.find('{'):texte.rfind('}') + 1]
    if not brut.strip():
        raise ValueError('aucun objet JSON dans la réponse')
    try:
        return json.loads(_reparer_barres(brut))
    except ValueError as exc:
        raise ValueError(f'JSON invalide : {exc}')


def _demander_json(job, messages, cles, system=None):
    """Appelle l'IA et lit sa réponse JSON ; une seconde chance si le JSON est illisible."""
    texte = _appeler(job, messages, system)
    try:
        data = extraire_json(texte)
        if not isinstance(data, dict) or not all(k in data for k in cles):
            raise ValueError(f'objet attendu avec les champs {", ".join(cles)}')
        return texte, data
    except ValueError as exc:
        messages = messages + [
            {'role': 'assistant', 'content': texte},
            {'role': 'user', 'content': f'Ta réponse est illisible ({exc}). Renvoie exactement un bloc ```json '
                                        f'avec les champs {", ".join(cles)}, sans rien changer d’autre.'},
        ]
        texte = _appeler(job, messages, system)
        try:
            data = extraire_json(texte)
        except ValueError:
            data = None
        if not isinstance(data, dict) or not all(k in data for k in cles):
            raise IAErreur('Réponse de l’IA illisible, deux fois de suite : relancer le travail.')
        return texte, data


def _fichiers(job):
    return [(f.name, f.mime, bytes(f.data)) for f in job.files.order_by('id')]


SERVEUR = ('format', 'source', 'credit', 'a_verifier', 'doublon_ok')


def _reponse(data):
    """Réponse de l'IA telle qu'on la lui remontre : sans les champs que le serveur ajoute (sinon la
    relecture les « corrige » et les signale)."""
    out = dict(data)
    out['fiches'] = [{k: v for k, v in f.items() if k not in SERVEUR} if isinstance(f, dict) else f
                     for f in data.get('fiches') or []]
    return '```json\n' + json.dumps(out, ensure_ascii=False) + '\n```'


def _texte_doutes(valeurs):
    return [str(d).strip() for d in (valeurs or []) if str(d).strip()]


# --------------------------------------------------------------------------- import : brouillon

def _premier_message(job, fichiers):
    contenu, description = documents.blocs(fichiers)
    contenu[-1]['cache_control'] = {'type': 'ephemeral'}  # le document resservira à chaque échange
    o = job.options
    lignes = [description]
    if o.get('niveau'):
        lignes.append(f'Niveau indiqué par l’administrateur : {o["niveau"]} (impose-le).')
    if o.get('type'):
        lignes.append(f'Type de contenu attendu : {o["type"]}.')
    if o.get('credit'):
        lignes.append(f'Auteur du document : {o["credit"]}.')
    if (o.get('consignes') or '').strip():
        lignes.append('Consignes de l’administrateur pour ce document (elles priment sur tes choix, '
                      'pas sur les règles de format) :\n' + o['consignes'].strip())
    lignes.append('Produis les fiches de ce document en suivant les consignes à la lettre. '
                  'Réponds par un seul bloc ```json.')
    return {'role': 'user', 'content': contenu + [{'type': 'text', 'text': '\n\n'.join(lignes)}]}


def _figures(job, fichiers, specs, anciennes=None):
    """Découpe les figures déclarées → ({nom: png base64}, erreurs). Garde les découpes inchangées."""
    anciennes = anciennes or {}
    images, erreurs = {}, []
    for spec in specs or []:
        nom = str((spec or {}).get('nom') or '')
        if not re.match(r'^[A-Za-z0-9._-]+\.png$', nom):
            erreurs.append(f'figure « {nom} » : nom invalide (lettres, chiffres, . _ -, extension .png)')
            continue
        signature = json.dumps(spec, sort_keys=True)
        if nom in anciennes and anciennes[nom][0] == signature:
            images[nom] = anciennes[nom]
            continue
        try:
            images[nom] = (signature, base64.b64encode(documents.figure(fichiers, spec)).decode())
        except IAErreur as exc:
            erreurs.append(str(exc))
        except Exception as exc:  # image corrompue, cadre hors page…
            erreurs.append(f'figure « {nom} » : découpe impossible ({exc})')
    return images, erreurs


def _cles_prises(job):
    from apps.things.models import Content
    prises = set(Content.objects.filter(json_content__import__cle__isnull=False)
                 .values_list('json_content__import__cle', flat=True))
    for autre in IAJob.objects.filter(kind=IAJob.IMPORT, status__in=[IAJob.EN_COURS, IAJob.PRET]).exclude(pk=job.pk):
        prises.update(f.get('cle') for f in (autre.result.get('fiches') or []) if isinstance(f, dict))
    return prises


def _completer(job, fiches, avertissements):
    """Champs remplis par le serveur, jamais par l'IA : format, source, crédit, clé unique."""
    o = job.options
    prises = _cles_prises(job)
    vues = set()
    for i, f in enumerate(fiches):
        if not isinstance(f, dict):
            continue
        f['format'] = importing.FORMAT
        for champ in ('source', 'credit', 'a_verifier', 'doublon_ok'):
            f.pop(champ, None)
        f['source'] = {'document': job.options.get('document') or 'document envoyé', 'origine': o.get('origine'),
                       'note': ORIGINES.get(o.get('origine'), '') + ' Fiche préparée par l’IA (Pilotage).'}
        if o.get('credit'):
            f['credit'] = o['credit']
        cle = importing.slugify(str(f.get('cle') or f.get('titre') or f'contenu-{i + 1}'))[:70] or f'contenu-{i + 1}'
        if len(cle) < 3:
            cle = f'contenu-{cle}'
        base, n = cle, 2
        while cle in prises or cle in vues:
            cle = f'{base}-{n}'
            n += 1
        if cle != f.get('cle'):
            if f.get('cle'):
                avertissements.append(f'clé « {f["cle"]} » déjà utilisée : remplacée par « {cle} » '
                                      '(un contenu publié n’est jamais écrasé)')
            f['cle'] = cle
        vues.add(cle)
    return fiches


def _controler(job, fiches, images):
    """Contrôle de chaque fiche, comme verifier.sh. → (erreurs, avertissements, doublons) par fiche."""
    rapports = []
    for i, f in enumerate(fiches):
        if not isinstance(f, dict):
            rapports.append({'erreurs': [f'fiche {i + 1} : objet JSON attendu'], 'avertissements': [], 'doublons': []})
            continue
        erreurs, avert, utilisees = importing.validate(f)
        for rel in sorted(utilisees):
            if rel.split('/', 1)[-1] not in images:
                erreurs.append(f'figure « {rel} » utilisée mais non déclarée dans « figures »')
        # Un doublon probable n'est pas une erreur de l'IA : l'administrateur tranche à la publication.
        db_err, db_avert, _ = importing.check_against_db(f)
        doublons = [e for e in db_err if e.startswith('doublon probable')]
        db_err = [e for e in db_err if e not in doublons]
        rapports.append({'erreurs': erreurs + db_err, 'avertissements': avert + db_avert, 'doublons': doublons})
    return rapports


def _a_corriger(rapports, erreurs_figures):
    lignes = list(erreurs_figures)
    for i, r in enumerate(rapports, 1):
        lignes += [f'fiche {i} — {e}' for e in r['erreurs']]
    return lignes


def _bilan(job, fiches, specs, images, doutes, problemes, solutions_doc, rapports, erreurs_figures, avertissements):
    job.result = {
        'fiches': fiches,
        'figures_spec': specs,
        'figures': {nom: v for nom, v in images.items()},
        'doutes': doutes,
        'problemes': problemes,
        'solutions_du_document': bool(solutions_doc),
        'controles': rapports,
        'erreurs_figures': erreurs_figures,
        'avertissements': avertissements,
    }


def _rediger(job, fichiers, messages, data, anciennes_images=None):
    """Complète, découpe, contrôle ; renvoie l'IA corriger ce que le contrôle refuse."""
    avertissements = []
    for reprise in range(MAX_REPRISES + 1):
        fiches = _completer(job, [dict(f) if isinstance(f, dict) else f for f in data.get('fiches') or []],
                            avertissements)
        specs = data.get('figures') or []
        images, erreurs_figures = _figures(job, fichiers, specs, anciennes_images)
        rapports = _controler(job, fiches, images)
        a_corriger = _a_corriger(rapports, erreurs_figures)
        if not fiches:
            a_corriger.append('aucune fiche produite')
        if not a_corriger or reprise == MAX_REPRISES:
            return data, fiches, specs, images, rapports, erreurs_figures, avertissements
        _etape(job, f'Correction des erreurs de format ({reprise + 1}/{MAX_REPRISES})')
        messages = messages + [
            {'role': 'assistant', 'content': _reponse(data)},
            {'role': 'user', 'content': 'Le contrôle automatique du site refuse ces points :\n- '
             + '\n- '.join(a_corriger)
             + '\n\nCorrige-les (sans rien changer d’autre) et renvoie le bloc ```json complet '
               '(fiches, figures, doutes, solutions_du_document).'},
        ]
        _, nouveau = _demander_json(job, messages, ['fiches'])
        nouveau.setdefault('doutes', data.get('doutes'))
        nouveau.setdefault('figures', data.get('figures'))
        nouveau.setdefault('solutions_du_document', data.get('solutions_du_document'))
        data = nouveau
        anciennes_images = images
    raise AssertionError('inatteignable')


def traiter_import(job):
    fichiers = _fichiers(job)
    _etape(job, 'Lecture du document et rédaction des fiches (quelques minutes)')
    premier = _premier_message(job, fichiers)
    messages = [premier]
    _, data = _demander_json(job, messages, ['fiches'])
    _etape(job, 'Découpe des figures et contrôle automatique')
    data, fiches, specs, images, rapports, erreurs_figures, avert = _rediger(job, fichiers, messages, data)
    doutes = _texte_doutes(data.get('doutes'))

    # Relecture critique : l'IA relit sa fiche, document sous les yeux, et refait les calculs.
    _etape(job, 'Relecture critique (fidélité au document, calculs, rédaction)')
    relu = messages + [
        {'role': 'assistant', 'content': _reponse(
            {'fiches': fiches, 'figures': specs, 'doutes': doutes,
             'solutions_du_document': bool(data.get('solutions_du_document'))})},
        {'role': 'user', 'content': consignes.RELECTURE},
    ]
    _, rel = _demander_json(job, relu, ['problemes'])
    problemes = [p for p in (rel.get('problemes') or []) if isinstance(p, dict) and p.get('description')]
    if isinstance(rel.get('fiches'), list) and rel['fiches']:
        _etape(job, 'Contrôle de la version relue')
        data2 = {'fiches': rel['fiches'], 'figures': specs, 'doutes': doutes,
                 'solutions_du_document': data.get('solutions_du_document')}
        _, fiches2, specs2, images2, rapports2, erreurs2, avert2 = _rediger(job, fichiers, relu, data2, images)
        if not _a_corriger(rapports2, erreurs2) or _a_corriger(rapports, erreurs_figures):
            fiches, specs, images, rapports, erreurs_figures, avert = fiches2, specs2, images2, rapports2, erreurs2, avert2
        else:
            problemes.append({'gravite': 'a_verifier', 'ou': 'Relecture',
                              'description': 'La version corrigée par la relecture ne passait pas le contrôle : '
                                             'version précédente conservée (les corrections ci-dessus n’y sont pas).'})
    _bilan(job, fiches, specs, images, doutes, problemes, data.get('solutions_du_document'),
           rapports, erreurs_figures, avert)
    job.history.append({'date': timezone.now().isoformat(), 'qui': 'ia', 'texte': 'Brouillon prêt.'})


def traiter_correction(job):
    """L'administrateur a demandé une modification du brouillon (job.options['instruction'])."""
    fichiers = _fichiers(job)
    r = job.result
    instruction = job.options.get('instruction', '')
    _etape(job, 'Prise en compte de votre demande')
    messages = [
        _premier_message(job, fichiers),
        {'role': 'assistant', 'content': _reponse(
            {'fiches': r.get('fiches'), 'figures': r.get('figures_spec'), 'doutes': r.get('doutes'),
             'solutions_du_document': r.get('solutions_du_document')})},
        {'role': 'user', 'content': 'Le professeur qui relit ta fiche demande :\n\n' + instruction
         + '\n\nApplique sa demande (si elle contredit le document ou les mathématiques, ne l’applique pas et '
           'explique-le dans « doutes »). Ne change rien d’autre. Renvoie le bloc ```json complet '
           '(fiches, figures, doutes, solutions_du_document).'},
    ]
    _, data = _demander_json(job, messages, ['fiches'])
    anciennes = {n: tuple(v) for n, v in (r.get('figures') or {}).items()}
    _etape(job, 'Contrôle automatique')
    data, fiches, specs, images, rapports, erreurs_figures, avert = _rediger(job, fichiers, messages, data, anciennes)
    _bilan(job, fiches, specs, images, _texte_doutes(data.get('doutes')), r.get('problemes') or [],
           data.get('solutions_du_document'), rapports, erreurs_figures, avert)
    job.history.append({'date': timezone.now().isoformat(), 'qui': 'ia', 'texte': 'Demande prise en compte.'})
    job.options.pop('instruction', None)


# --------------------------------------------------------------------------- import : publication

def apercus(job):
    """Structures converties (rendu du site), figures en data URI, pour la relecture."""
    out = []
    figures = job.result.get('figures') or {}
    src_map = {f'figures/{n}': f'data:image/png;base64,{v[1]}' for n, v in figures.items()}
    for f in job.result.get('fiches') or []:
        try:
            out.append({'cle': f.get('cle'), 'titre': f.get('titre'), 'type': importing.TYPES.get(f.get('type')),
                        'niveaux': f.get('niveaux') or [], 'chapitres': f.get('chapitres') or [],
                        'theoremes': f.get('theoremes') or [], 'difficulte': f.get('difficulte'),
                        'examen': f.get('examen'), 'structure': importing.to_structure(f, src_map)})
        except Exception as exc:  # fiche refusée par le contrôle : pas d'aperçu possible
            out.append({'cle': f.get('cle'), 'titre': f.get('titre'), 'type': None, 'erreur': str(exc)})
    return out


def publier(job, *, a_verifier, doublon_ok, auteur):
    """Publie toutes les fiches du brouillon (tout ou rien). Jamais d'écrasement d'un contenu existant."""
    import os
    import tempfile
    from django.conf import settings
    from django.db import transaction
    from apps.things.models import Content

    r = job.result
    fiches = r.get('fiches') or []
    rapports = _controler(job, fiches, r.get('figures') or {})
    bloquant = _a_corriger(rapports, r.get('erreurs_figures') or [])
    if not doublon_ok:
        bloquant += [d for rp in rapports for d in rp['doublons']]
    if bloquant:
        raise IAErreur('Publication impossible :\n- ' + '\n- '.join(bloquant))
    for f in fiches:
        if Content.objects.filter(json_content__import__cle=f['cle']).exists():
            raise IAErreur(f'La clé « {f["cle"]} » vient d’être utilisée par un autre contenu : demander une correction.')
    publies = []
    with tempfile.TemporaryDirectory() as d, transaction.atomic():
        os.makedirs(os.path.join(d, 'figures'))
        for nom, (_, b64) in (r.get('figures') or {}).items():
            with open(os.path.join(d, 'figures', nom), 'wb') as fh:
                fh.write(base64.b64decode(b64))
        for f in fiches:
            fiche = dict(f, a_verifier=bool(a_verifier), doublon_ok=bool(doublon_ok))
            content, _ = importing.import_fiche(fiche, d, api_base=getattr(settings, 'IA_API_BASE', 'https://api.fidni.fr'))
            js = dict(content.json_content)
            js['import']['ia'] = {'travail': job.pk, 'publie_par': auteur.username}
            Content.objects.filter(pk=content.pk).update(json_content=js)
            publies.append({'id': content.pk, 'type': content.type, 'titre': content.title})
    return publies


# --------------------------------------------------------------------------- signalements

def _parties(structure):
    """[(chemin, libellé, objet)] de chaque endroit modifiable d'un contenu."""
    out = []
    for b in structure.get('blocks') or []:
        out.append((b.get('id'), b))
        for sq in b.get('subQuestions') or []:
            out.append((f"{b.get('id')}.{sq.get('id')}", sq))
    for s in structure.get('sections') or []:
        out.append((s.get('id'), s))
        for ss in s.get('subSections') or []:
            out.append((f"{s.get('id')}.{ss.get('id')}", ss))
    return out


def _html(part):
    return (part or {}).get('html') or ''


def _extrait(content, cible):
    """Le contenu entier, balisé avec les identifiants, la partie signalée repérée."""
    st = content.json_content or {}
    lignes = []
    for b in st.get('blocks') or []:
        marque = ' signale="oui"' if cible and cible.split('.')[0] == b.get('id') else ''
        if b.get('type') == 'section':
            lignes.append(f'<partie id="{b.get("id")}"{marque}>{_html(b.get("content"))}</partie>')
            continue
        lignes.append(f'<bloc id="{b.get("id")}" type="{b.get("type")}"{marque}>')
        if _html(b.get('content')):
            lignes.append(f'  <enonce>{_html(b.get("content"))}</enonce>')
        if b.get('solution'):
            lignes.append(f'  <solution>{_html(b["solution"])}</solution>')
        for sq in b.get('subQuestions') or []:
            m = ' signale="oui"' if cible == f"{b.get('id')}.{sq.get('id')}" else ''
            lignes.append(f'  <sous_question id="{sq.get("id")}"{m}>')
            lignes.append(f'    <enonce>{_html(sq.get("content"))}</enonce>')
            if sq.get('solution'):
                lignes.append(f'    <solution>{_html(sq["solution"])}</solution>')
            lignes.append('  </sous_question>')
        lignes.append('</bloc>')
    for s in st.get('sections') or []:
        marque = ' signale="oui"' if cible and cible.split('.')[0] == s.get('id') else ''
        lignes.append(f'<bloc id="{s.get("id")}" type="section_de_lecon" titre="{s.get("title", "")}"{marque}>')
        lignes.append(f'  <enonce>{_html(s.get("content"))}</enonce>')
        for ss in s.get('subSections') or []:
            m = ' signale="oui"' if cible == f"{s.get('id')}.{ss.get('id')}" else ''
            lignes.append(f'  <sous_question id="{ss.get("id")}" titre="{ss.get("title", "")}"{m}>')
            lignes.append(f'    <enonce>{_html(ss.get("content"))}</enonce>')
            lignes.append('  </sous_question>')
        lignes.append('</bloc>')
    return '\n'.join(lignes)


def _cible(structure, bloc, sous_question):
    for chemin, part in _parties(structure):
        if chemin == (f'{bloc}.{sous_question}' if sous_question else bloc):
            return part
    return None


_IMG = re.compile(r'<img\b[^>]*>')
_SRC = re.compile(r'src="([^"]*)"')


def _controler_modif(structure, m, i):
    """→ (modification normalisée, erreurs)."""
    ou = f'modification {i}'
    if not isinstance(m, dict):
        return None, [f'{ou} : objet attendu']
    bloc, sq, champ = str(m.get('bloc') or ''), m.get('sous_question') or None, m.get('champ')
    part = _cible(structure, bloc, sq)
    if part is None:
        return None, [f'{ou} : bloc « {bloc} »' + (f' / sous-question « {sq} »' if sq else '') + ' introuvable']
    if champ not in CHAMPS:
        return None, [f'{ou} : champ « {champ} » (enonce ou solution)']
    cle = CHAMPS[champ]
    if cle == 'solution' and (part.get('subQuestions') or part.get('type') in ('section', 'context')
                              or 'sections' in structure):
        return None, [f'{ou} : ce bloc n’a pas de solution (elle va dans les sous-questions)']
    if part.get('type') == 'section' and cle == 'content':
        return None, [f'{ou} : le titre d’une partie ne se modifie pas ici']
    html = m.get('html')
    if not isinstance(html, str) or not html.strip():
        return None, [f'{ou} : html vide']
    avant = _html(part.get(cle))
    erreurs = []
    anciennes = {s for t in _IMG.findall(avant) for s in _SRC.findall(t)}
    nouvelles = {s for t in _IMG.findall(html) for s in _SRC.findall(t)}
    if nouvelles - anciennes:
        erreurs.append(f'{ou} : image ajoutée ou modifiée (les figures ne se changent pas ici)')
    # Le contrôle d'import attend « figures/x.png » : on remplace les liens des figures publiées.
    temoin = _SRC.sub(lambda mm: 'src="figures/f.png"' if mm.group(1) in anciennes else mm.group(0), html)
    check = []
    importing.check_html(temoin, ou, check, set())
    erreurs += check
    apres = importing.escape_math_in_html(html)
    if apres == avant:
        return None, []
    return {'bloc': bloc, 'sous_question': sq, 'champ': cle, 'avant': avant, 'apres': apres}, erreurs


def traiter_signalement(job):
    report = job.report
    if report is None:
        raise IAErreur('Signalement supprimé.')
    content = report.content
    _etape(job, 'Vérification du signalement')
    niveaux = ', '.join(content.class_levels.values_list('name', flat=True)) or 'non précisé'
    chapitres = ', '.join(content.chapters.values_list('name', flat=True)) or 'non précisé'
    texte = (
        f'Contenu : « {content.title} » ({content.type}) — niveau : {niveaux} — chapitres : {chapitres}.\n'
        f'Signalement d’un élève : {report.get_reason_display()}'
        + (f' — endroit : {report.item_label} (identifiant {report.item_path})' if report.item_path else ' — tout le contenu')
        + (f'\nMessage de l’élève : « {report.description} »' if report.description else '\nPas de message.')
        + ('\nConsigne de l’administrateur : ' + job.options['instruction'] if job.options.get('instruction') else '')
        + '\n\nDans le HTML ci-dessous, « &lt; » et « &gt; » dans les formules valent < et > (tu peux écrire l’un '
          'ou l’autre) ; garde les balises <img> telles quelles.\n\n<contenu>\n' + _extrait(content, report.item_path)
        + '\n</contenu>'
    )
    system = consignes.systeme() + '\n\n# Tâche : correction d’un signalement\n\n' + consignes.SIGNALEMENT
    messages = [{'role': 'user', 'content': texte}]
    structure = content.json_content or {}
    for reprise in range(MAX_REPRISES + 1):
        _, data = _demander_json(job, messages, ['fonde', 'modifications'], system)
        modifs, erreurs = [], []
        for i, m in enumerate(data.get('modifications') or [], 1):
            norm, err = _controler_modif(structure, m, i)
            erreurs += err
            if norm:
                modifs.append(norm)
        if not erreurs or reprise == MAX_REPRISES:
            break
        _etape(job, f'Correction des erreurs de format ({reprise + 1}/{MAX_REPRISES})')
        messages = messages + [
            {'role': 'assistant', 'content': '```json\n' + json.dumps(data, ensure_ascii=False) + '\n```'},
            {'role': 'user', 'content': 'Le contrôle du site refuse :\n- ' + '\n- '.join(erreurs)
             + '\nCorrige et renvoie le bloc ```json complet.'},
        ]
    labels = {p: _libelle(content, p) for p, _ in _parties(structure)}
    for m in modifs:
        m['ou'] = labels.get(f"{m['bloc']}.{m['sous_question']}" if m['sous_question'] else m['bloc']) or ''
    job.options.pop('instruction', None)
    job.result = {
        'fonde': data.get('fonde') if data.get('fonde') in ('oui', 'non', 'incertain') else 'incertain',
        'explication': str(data.get('explication') or '').strip(),
        'doutes': _texte_doutes(data.get('doutes')),
        'modifications': modifs,
        'erreurs': erreurs,
        'version': (content.updated_at.isoformat() if getattr(content, 'updated_at', None) else ''),
    }


def _libelle(content, chemin):
    """« Exercice 2 · Question 1.3 », comme sur le site (numérotation par partie)."""
    st = content.json_content or {}
    partie, qn = None, 0
    for b in st.get('blocks') or []:
        if b.get('type') == 'section':
            partie = re.sub(r'<[^>]+>', '', _html(b.get('content'))).strip()
            qn = 0
            continue
        if b.get('type') != 'question':
            if chemin == b.get('id'):
                return (partie + ' · ' if partie else '') + 'Énoncé'
            continue
        qn += 1
        base = (partie + ' · ' if partie else '') + f'Question {qn}'
        if chemin == b.get('id'):
            return base
        for j, sq in enumerate(b.get('subQuestions') or [], 1):
            if chemin == f"{b.get('id')}.{sq.get('id')}":
                return f'{base}.{j}'
    for i, s in enumerate(st.get('sections') or [], 1):
        if chemin == s.get('id'):
            return s.get('title') or f'Partie {i}'
        for ss in s.get('subSections') or []:
            if chemin == f"{s.get('id')}.{ss.get('id')}":
                return f"{s.get('title')} · {ss.get('title')}"
    return ''


def appliquer(job, *, a_verifier, auteur):
    """Applique la correction proposée (si le contenu n'a pas changé entre-temps) et clôt le signalement."""
    from django.db import transaction
    from apps.things.models import Content, ContentReport

    modifs = job.result.get('modifications') or []
    if not modifs:
        raise IAErreur('Aucune modification à appliquer.')
    with transaction.atomic():
        content = Content.objects.select_for_update().get(pk=job.report.content_id)
        structure = json.loads(json.dumps(content.json_content or {}))
        for m in modifs:
            part = _cible(structure, m['bloc'], m['sous_question'])
            if part is None or _html(part.get(m['champ'])) != m['avant']:
                raise IAErreur('Le contenu a été modifié depuis la proposition : relancer l’IA sur ce signalement.')
            part[m['champ']] = {'type': 'text', 'html': m['apres']}
        if a_verifier and any(m['champ'] == 'solution' for m in modifs):
            structure['a_verifier'] = True
        structure.setdefault('modifs_ia', []).append({
            'date': timezone.now().isoformat(), 'travail': job.pk, 'signalement': job.report_id,
            'par': auteur.username, 'endroits': [m['ou'] or m['bloc'] for m in modifs],
        })
        content.json_content = structure
        content.save()
        report = job.report
        report.status = ContentReport.STATUS_RESOLVED
        report.handled_at, report.handled_by = timezone.now(), auteur
        report.save(update_fields=['status', 'handled_at', 'handled_by'])
    from django.core.cache import cache
    cache.delete(f'content_stats_{content.pk}_user_None')
    return content


# --------------------------------------------------------------------------- exécution

def traiter(job_id):
    job = IAJob.objects.get(pk=job_id)
    if job.status != IAJob.EN_ATTENTE:
        return
    correction = job.kind == IAJob.IMPORT and bool(job.options.get('instruction'))
    _etape(job, 'Démarrage', status=IAJob.EN_COURS, error='')
    try:
        if job.kind == IAJob.SIGNALEMENT:
            traiter_signalement(job)
        elif correction:
            traiter_correction(job)
        else:
            traiter_import(job)
        _etape(job, '', status=IAJob.PRET)
    except Exception as exc:
        if isinstance(exc, IAErreur):
            message = str(exc)
        else:  # erreur imprévue : visible dans Pilotage et dans les journaux
            import logging
            logging.getLogger('django').exception('IA : travail %s', job_id)
            message = f'Erreur inattendue : {exc.__class__.__name__}: {exc}'[:1000]
        if correction:  # le brouillon précédent reste intact et publiable
            job.options.pop('instruction', None)
            _etape(job, '', status=IAJob.PRET, error='Demande non prise en compte : ' + message)
        else:
            _etape(job, '', status=IAJob.ERREUR, error=message)


def interrompus():
    """Travaux « en cours » sans nouvelles depuis trop longtemps (serveur redémarré…)."""
    limite = timezone.now() - DUREE_MAX
    return IAJob.objects.filter(status=IAJob.EN_COURS).filter(Q(heartbeat__lt=limite) | Q(heartbeat__isnull=True))
