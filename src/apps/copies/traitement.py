"""Travaux de l'IA sur les copies, exécutés en arrière-plan (commande copies_traiter, lancée comme ia_traiter).

- correction d'une copie : transcription des pages (effort faible) puis note par question (texte seul, consignes et
  barème en cache commun à toutes les copies de l'évaluation) ;
- découpage du PDF de toute la classe : lecture du nom en tête de chaque page, regroupement, rapprochement avec la
  liste de la classe (sur le serveur : la liste n'est jamais envoyée à l'IA) ;
- import d'un sujet privé : PDF du sujet (et du corrigé) → structure de questions, solutions rédigées « à vérifier ».

Un processus par évaluation vide sa file de copies, puis prend la suivante ; au plus COPIES_MAX_PROCESSUS à la fois.
Une copie bloquée (serveur redémarré) est reprise par `copies_traiter --reprendre` (tâche planifiée).
"""
import base64
import difflib
import json
import logging
import os
import subprocess
import sys
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.html import strip_tags

from apps.ia import client as ia_client
from apps.ia.client import IAErreur
from apps.ia.pipeline import extraire_json

from . import consignes as C
from .bareme import arrondir, completer_ids, questions, total
from .models import Copie, Evaluation, FichierSujet, Lot, UsageCopies

logger = logging.getLogger('django')
DUREE_MAX = timedelta(minutes=20)
ESSAIS_MAX = 2
CONFIANCE_MIN = 0.6
COMMENTAIRE_MAX = 600
LOT_PAR_APPEL = 30


# --------------------------------------------------------------------------- lancement

def lancer(sorte, ident):
    """Démarre `copies_traiter <sorte> <id>` dans un processus détaché (double fork : pas de zombie)."""
    if getattr(settings, 'IA_LANCEMENT', 'processus') != 'processus':
        return  # tests : traitement appelé directement
    manage = os.path.join(str(settings.BASE_DIR), 'manage.py')
    subprocess.Popen(['sh', '-c', f'"{sys.executable}" "{manage}" copies_traiter {sorte} {int(ident)} &'],
                     start_new_session=True).wait()


def _vivants():
    return timezone.now() - DUREE_MAX


def processus_actifs():
    """Évaluations, lots et sujets en cours de traitement (nouvelles depuis moins de DUREE_MAX)."""
    v = _vivants()
    evals = set(Copie.objects.filter(statut=Copie.EN_COURS, heartbeat__gte=v).values_list('evaluation_id', flat=True))
    lots = Lot.objects.filter(statut=Lot.EN_COURS, heartbeat__gte=v).count()
    sujets = Evaluation.objects.filter(sujet_statut=Evaluation.EN_COURS, heartbeat__gte=v).count()
    return len(evals) + lots + sujets


def demarrer_corrections(evaluation):
    """Lance un processus pour l'évaluation s'il n'y en a pas déjà un (sinon il prendra les nouvelles copies)."""
    v = _vivants()
    if Copie.objects.filter(evaluation=evaluation, statut=Copie.EN_COURS, heartbeat__gte=v).exists():
        return
    if processus_actifs() >= settings.COPIES_MAX_PROCESSUS:
        return  # file d'attente : repris quand un processus se libère (ou par --reprendre)
    lancer('evaluation', evaluation.pk)


def reprendre():
    """Remet en file les travaux interrompus et relance ce qui attend (tâche planifiée toutes les 10 min)."""
    v = _vivants()
    bloquees = Copie.objects.filter(statut=Copie.EN_COURS).filter(Q(heartbeat__lt=v) | Q(heartbeat__isnull=True))
    bloquees.update(statut=Copie.EN_ATTENTE, etape='')
    Lot.objects.filter(statut=Lot.EN_COURS).filter(Q(heartbeat__lt=v) | Q(heartbeat__isnull=True)).update(
        statut=Lot.ERREUR, etape='', error='Lecture interrompue (serveur redémarré ?) : relancer.')
    Evaluation.objects.filter(sujet_statut=Evaluation.EN_COURS).filter(
        Q(heartbeat__lt=v) | Q(heartbeat__isnull=True)).update(
        sujet_statut=Evaluation.ERREUR, etape='', error='Import interrompu (serveur redémarré ?) : relancer.')
    for eid in Copie.objects.filter(statut=Copie.EN_ATTENTE).values_list('evaluation_id', flat=True).distinct():
        demarrer_corrections(Evaluation(pk=eid))


# --------------------------------------------------------------------------- coût

def _compter(obj, usage):
    for k in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
        if usage.get(k):
            obj.usage[k] = obj.usage.get(k, 0) + usage[k]
    obj.usage['appels'] = obj.usage.get('appels', 0) + 1


def cout(usage):
    p = settings.COPIES_PRIX
    return round((usage.get('input_tokens', 0) * p['input'] + usage.get('output_tokens', 0) * p['output']
                  + usage.get('cache_read_input_tokens', 0) * p['cache_read']
                  + usage.get('cache_creation_input_tokens', 0) * p['cache_write']) / 1e6, 5)


def _mois():
    return timezone.localdate().strftime('%Y-%m')


def quota_restant(user):
    """Copies que ce professeur peut encore faire corriger ce mois-ci (None : sans limite)."""
    if user.is_superuser:
        return None
    u = UsageCopies.objects.filter(user=user, mois=_mois()).first()
    return max(0, settings.COPIES_QUOTA_MOIS - (u.copies if u else 0))


def _facturer(evaluation, usage_appel):
    """Ajoute le coût d'un appel au professeur (mois en cours)."""
    owner_id = evaluation.classroom.owner_id
    u, _ = UsageCopies.objects.get_or_create(user_id=owner_id, mois=_mois())
    UsageCopies.objects.filter(pk=u.pk).update(cout_usd=F('cout_usd') + cout(usage_appel))


def _appel(obj, evaluation, system, messages, schema, effort, max_tokens=16000):
    """Appel au modèle des copies, réponse JSON (sortie structurée, ou extraite du texte en secours)."""
    texte, usage = ia_client.appeler(system, messages, max_tokens=max_tokens, model=settings.COPIES_MODEL,
                                     effort=effort, format=schema)
    _compter(obj, usage)
    if evaluation is not None and evaluation is not obj:
        _compter(evaluation, usage)
    if evaluation is not None:
        _facturer(evaluation, usage)
    try:
        return json.loads(texte)
    except ValueError:
        data = extraire_json(texte)
        if data is None:
            raise IAErreur('Réponse de l’IA illisible.')
        return data


def _image(jpeg):
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                        'data': base64.b64encode(jpeg).decode()}}


def _etape(obj, texte, **champs):
    obj.etape = texte
    obj.heartbeat = timezone.now()
    for k, v in champs.items():
        setattr(obj, k, v)
    obj.save()


# --------------------------------------------------------------------------- correction d'une copie

def _propre(s, n=COMMENTAIRE_MAX):
    return ' '.join(strip_tags(str(s or '')).split())[:n]


def transcrire(copie, evaluation, qs):
    pages = list(copie.pages.all())
    if not pages:
        raise IAErreur('Aucune page dans cette copie.')
    contenu = []
    for i, p in enumerate(pages, 1):
        with p.fichier.open('rb') as f:
            contenu += [{'type': 'text', 'text': f'Page {i} :'}, _image(f.read())]
    contenu.append({'type': 'text', 'text': 'Transcris cette copie selon les règles.'})
    system = C.TRANSCRIPTION.replace('{questions}', C.liste_questions(qs))
    data = _appel(copie, evaluation, system, [{'role': 'user', 'content': contenu}],
                  C.schema_transcription([q['chemin'] for q in qs]), settings.COPIES_EFFORT_TRANSCRIPTION)
    chemins = {q['chemin'] for q in qs}
    out = {}
    for r in data.get('reponses') or []:
        c = r.get('chemin')
        if c not in chemins:
            continue
        t = str(r.get('texte') or '')[:6000]
        if c in out:  # même question en deux endroits (suite sur une autre page) : on ajoute
            out[c]['texte'] += '\n' + t
            out[c]['illisible'] = out[c]['illisible'] or bool(r.get('illisible'))
        else:
            out[c] = {'texte': t, 'illisible': bool(r.get('illisible')), 'page': r.get('page') or None}
    out['_hors_question'] = str(data.get('hors_question') or '')[:4000]
    out['_injection'] = bool(data.get('injection_suspecte'))
    return out


def _systeme_correction(evaluation, qs):
    prof = ''
    if evaluation.consignes.strip():
        prof = ('- Consignes du professeur pour cette évaluation (à appliquer) : '
                + ' '.join(evaluation.consignes.split())[:2000] + '\n')
    pas = {0.25: '0,25', 0.5: '0,5', 1: '1'}.get(evaluation.pas, '0,5')
    return (C.CORRECTION.replace('{pas}', pas).replace('{consignes_prof}', prof)
            .replace('{bareme}', C.bareme_texte(qs)))


def noter(copie, evaluation, qs, chemins=None):
    """Note proposée par l'IA à partir de la transcription (toutes les questions, ou seulement `chemins`)."""
    tr = copie.transcription or {}
    lignes = []
    for q in qs:
        r = tr.get(q['chemin'])
        rep = (r or {}).get('texte') or '(pas de réponse)'
        lignes.append(f"### Question {q['label']} (chemin {q['chemin']})\n{rep}")
    if tr.get('_hors_question'):
        lignes.append(f"### Hors des questions\n{tr['_hors_question']}")
    copie_txt = '\n\n'.join(lignes).replace('</copie_eleve>', '')
    message = f"<copie_eleve>\n{copie_txt}\n</copie_eleve>\n\nPropose une note pour chaque question."
    data = _appel(copie, evaluation, _systeme_correction(evaluation, qs), [{'role': 'user', 'content': message}],
                  C.schema_correction([q['chemin'] for q in qs]), settings.COPIES_EFFORT_CORRECTION)
    maxi = {q['chemin']: q['max'] for q in qs}
    ia = dict(copie.ia or {}) if chemins else {}
    for r in data.get('questions') or []:
        c = r.get('chemin')
        if c not in maxi or (chemins and c not in chemins):
            continue
        try:
            conf = min(1.0, max(0.0, float(r.get('confiance'))))
        except (TypeError, ValueError):
            conf = 0.0
        ia[c] = {'points': arrondir(r.get('points'), maxi[c], evaluation.pas), 'commentaire': _propre(r.get('commentaire')),
                 'confiance': round(conf, 2), 'illisible': bool(r.get('illisible'))}
    return ia, _propre(data.get('commentaire_global'), 1200)


def drapeaux(copie, qs):
    out = []
    tr = copie.transcription or {}
    if tr.get('_injection'):
        out.append({'chemin': None, 'raison': 'injection'})
    for q in qs:
        c = q['chemin']
        p = (copie.ia or {}).get(c)
        if p is None or p.get('points') is None:
            out.append({'chemin': c, 'raison': 'non_notee'})
        elif p.get('illisible') or (tr.get(c) or {}).get('illisible'):
            out.append({'chemin': c, 'raison': 'illisible'})
        elif p.get('confiance', 1) < CONFIANCE_MIN:
            out.append({'chemin': c, 'raison': 'confiance'})
    return out


def corriger_copie(copie, chemins=None):
    """Transcrit (si besoin) et note une copie. `chemins` : ne renoter que ces questions (transcription gardée)."""
    evaluation = copie.evaluation
    qs = questions(evaluation.sujet, evaluation.maxima)
    if not qs:
        raise IAErreur('Le sujet n’a aucune question.')
    if not chemins or not copie.transcription:
        _etape(copie, 'Lecture de la copie')
        copie.transcription = transcrire(copie, evaluation, qs)
        chemins = None
    _etape(copie, 'Correction')
    copie.ia, glob = noter(copie, evaluation, qs, chemins)
    if glob or not chemins:
        copie.ia_global = glob
    copie.drapeaux = drapeaux(copie, qs)
    copie.total = total(evaluation, copie, qs)[0]
    _etape(copie, '', statut=Copie.CORRIGEE, error='')
    evaluation.save(update_fields=['usage', 'updated_at'])


def _prendre(evaluation_id):
    """Réserve la prochaine copie en attente de cette évaluation (atomique : un seul processus la traite)."""
    for cid in Copie.objects.filter(evaluation_id=evaluation_id, statut=Copie.EN_ATTENTE).order_by('id') \
            .values_list('id', flat=True)[:5]:
        if Copie.objects.filter(pk=cid, statut=Copie.EN_ATTENTE).update(
                statut=Copie.EN_COURS, heartbeat=timezone.now(), etape='En attente'):
            return Copie.objects.select_related('evaluation__classroom').get(pk=cid)
    return None


def traiter_copie(copie):
    chemins = list(copie.a_renoter or [])
    copie.a_renoter = []
    try:
        corriger_copie(copie, chemins=chemins)
    except IAErreur as exc:
        _echec(copie, str(exc))
    except Exception as exc:  # noqa: BLE001 — la file continue
        logger.exception('Copies : copie %s', copie.pk)
        _echec(copie, f'Erreur inattendue : {exc.__class__.__name__}')


def _echec(copie, message):
    copie.essais += 1
    if copie.essais < ESSAIS_MAX and 'refusé' not in message:
        _etape(copie, '', statut=Copie.EN_ATTENTE, error=message[:1000])
    else:
        _etape(copie, '', statut=Copie.ERREUR, error=message[:1000])


def traiter_evaluation(evaluation_id):
    """Vide la file de l'évaluation, puis celle des autres évaluations qui attendent sans processus."""
    vues = set()
    while evaluation_id is not None:
        vues.add(evaluation_id)
        while True:
            copie = _prendre(evaluation_id)
            if copie is None:
                break
            traiter_copie(copie)
        v = _vivants()
        actives = set(Copie.objects.filter(statut=Copie.EN_COURS, heartbeat__gte=v)
                      .values_list('evaluation_id', flat=True))
        evaluation_id = (Copie.objects.filter(statut=Copie.EN_ATTENTE).exclude(evaluation_id__in=actives | vues)
                         .values_list('evaluation_id', flat=True).first())


# --------------------------------------------------------------------------- PDF de toute la classe

def _sans_accents(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in s).split())


def _noms_eleve(u):
    """Formes du nom d'un élève à comparer au nom lu : « prénom nom », « nom prénom », pseudo. Les noms restent sur
    le serveur (identité privée) : ni envoyés à l'IA, ni montrés au professeur."""
    prenom, nom = (u.first_name or '').strip(), (u.last_name or '').strip()
    formes = {_sans_accents(f'{prenom} {nom}'), _sans_accents(f'{nom} {prenom}'), _sans_accents(u.username)}
    return [f for f in formes if f]


def rapprocher(nom_lu, eleves):
    """(id de l'élève, score 0-1) le plus proche du nom lu ; (None, 0) si rien de convaincant."""
    lu = _sans_accents(nom_lu)
    if not lu:
        return None, 0.0
    meilleur, score = None, 0.0
    for u in eleves:
        for forme in _noms_eleve(u):
            s = difflib.SequenceMatcher(None, lu, forme).ratio()
            if s > score:
                meilleur, score = u.id, s
    return (meilleur, round(score, 2)) if score >= 0.6 else (None, round(score, 2))


def _meme_nom(a, b):
    """« Sara Elkhatib » et « EL KHATIB Sara » : même élève (accents, espaces, ordre et casse ignorés)."""
    a, b = sorted(_sans_accents(a).split()), sorted(_sans_accents(b).split())
    return difflib.SequenceMatcher(None, ''.join(a), ''.join(b)).ratio() >= 0.8 or         difflib.SequenceMatcher(None, ' '.join(a), ' '.join(b)).ratio() >= 0.8


def grouper(lecture, nb_pages):
    """Pages lues [{page, nom_lu, debut_copie}] → groupes [{pages, nom_lu}] : une nouvelle copie à chaque début, ou
    quand un autre nom apparaît en tête de page."""
    par_page = {r.get('page'): r for r in lecture if isinstance(r, dict)}
    groupes = []
    for n in range(1, nb_pages + 1):
        r = par_page.get(n) or {}
        nom = str(r.get('nom_lu') or '').strip()
        precedent = groupes[-1]['nom_lu'] if groupes else ''
        nouveau_nom = nom and precedent and not _meme_nom(nom, precedent)
        if not groupes or nouveau_nom or (r.get('debut_copie') and not (nom and precedent and _meme_nom(nom, precedent))):
            groupes.append({'pages': [n], 'nom_lu': nom})
        else:
            groupes[-1]['pages'].append(n)
            if nom and not groupes[-1]['nom_lu']:
                groupes[-1]['nom_lu'] = nom
    return groupes


def _eleves(evaluation):
    from django.contrib.auth.models import User
    return list(User.objects.filter(classroom_memberships__classroom=evaluation.classroom))


def traiter_lot(lot_id):
    from .images import entete, page_pdf
    lot = Lot.objects.select_related('evaluation__classroom').get(pk=lot_id)
    if not Lot.objects.filter(pk=lot_id, statut=Lot.EN_ATTENTE).update(statut=Lot.EN_COURS, heartbeat=timezone.now()):
        return
    lot.refresh_from_db()
    evaluation = lot.evaluation
    try:
        with lot.fichier.open('rb') as f:
            pdf = f.read()
        if lot.pages_par_copie:
            k = lot.pages_par_copie
            groupes = [{'pages': list(range(i, min(i + k, lot.nb_pages + 1))), 'nom_lu': ''}
                       for i in range(1, lot.nb_pages + 1, k)]
        else:
            lecture = []
            for debut in range(1, lot.nb_pages + 1, LOT_PAR_APPEL):
                fin = min(debut + LOT_PAR_APPEL - 1, lot.nb_pages)
                _etape(lot, f'Lecture des noms (pages {debut} à {fin})')
                contenu = []
                for n in range(debut, fin + 1):
                    contenu += [{'type': 'text', 'text': f'Page {n} :'}, _image(entete(page_pdf(pdf, n)[0]))]
                contenu.append({'type': 'text', 'text': 'Pour chaque page : nom_lu et debut_copie.'})
                data = _appel(lot, evaluation, C.NOMS, [{'role': 'user', 'content': contenu}], C.SCHEMA_NOMS,
                              settings.COPIES_EFFORT_TRANSCRIPTION, max_tokens=8000)
                lecture += data.get('pages') or []
            groupes = grouper(lecture, lot.nb_pages)
        eleves = _eleves(evaluation)
        pris = set()
        for g in groupes:
            eid, score = rapprocher(g['nom_lu'], eleves)
            if eid in pris:  # deux copies pour le même élève : le professeur choisira
                eid = None
            if eid:
                pris.add(eid)
            g['eleve_id'], g['score'] = eid, score
        _etape(lot, '', statut=Lot.PRET, proposition=groupes, error='')
    except IAErreur as exc:
        _etape(lot, '', statut=Lot.ERREUR, error=str(exc)[:1000])
    except Exception as exc:  # noqa: BLE001
        logger.exception('Copies : lot %s', lot_id)
        _etape(lot, '', statut=Lot.ERREUR, error=f'Erreur inattendue : {exc.__class__.__name__}')


# --------------------------------------------------------------------------- sujet privé depuis un PDF

def _p(texte_):
    """Texte (formules $…$) → HTML de l'éditeur (paragraphes)."""
    from html import escape
    lignes = [ligne.strip() for ligne in str(texte_ or '').split('\n') if ligne.strip()]
    return ''.join(f'<p>{escape(ligne, quote=False)}</p>' for ligne in lignes)


def structure_depuis(data):
    """Réponse de l'IA (SCHEMA_SUJET) → json_content v2.1, et nombre de solutions rédigées par l'IA."""
    import uuid
    blocs, redigees = [], 0
    for b in data.get('blocs') or []:
        t = b.get('type')
        if t not in ('section', 'context', 'question'):
            continue
        bloc = {'id': uuid.uuid4().hex[:10], 'type': t, 'content': {'html': _p(b.get('texte'))}}
        if t == 'section':
            bloc['points'] = float(b.get('points') or 0)
        if t == 'question':
            subs = b.get('sous_questions') or []
            if subs:
                bloc['subQuestions'] = []
                for sq in subs:
                    bloc['subQuestions'].append({
                        'id': uuid.uuid4().hex[:10], 'content': {'html': _p(sq.get('enonce'))},
                        'points': float(sq.get('points') or 0), 'solution': {'html': _p(sq.get('solution'))},
                        'meta': {'solution_ia': bool(sq.get('solution_redigee'))}})
                    redigees += bool(sq.get('solution_redigee'))
            else:
                bloc['points'] = float(b.get('points') or 0)
                bloc['solution'] = {'html': _p(b.get('solution'))}
                bloc['meta'] = {'solution_ia': bool(b.get('solution_redigee'))}
                redigees += bool(b.get('solution_redigee'))
        blocs.append(bloc)
    return completer_ids({'version': '2.1', 'blocks': blocs}), redigees


def traiter_sujet(evaluation_id):
    """Lit le sujet (et le corrigé éventuel) envoyés (FichierSujet, PDF ou photos), puis les efface."""
    from .images import pages as en_pages
    evaluation = Evaluation.objects.select_related('classroom').get(pk=evaluation_id)
    if evaluation.sujet_statut != Evaluation.EN_COURS:
        return
    try:
        fichiers = []
        for fs in FichierSujet.objects.filter(evaluation=evaluation):
            with fs.fichier.open('rb') as f:
                fichiers.append((fs.nom, f.read()))
        if not fichiers:
            raise IAErreur('Aucun document envoyé.')
        contenu = []
        for nom, donnees in fichiers:
            if donnees[:5] == b'%PDF-':
                contenu += [{'type': 'text', 'text': f'Document « {nom} » :'},
                            {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf',
                                                            'data': base64.b64encode(donnees).decode()}}]
            else:
                contenu += [{'type': 'text', 'text': f'Document « {nom} » :'}] + [
                    _image(j) for j, _w, _h in en_pages(donnees, nom)]
        contenu.append({'type': 'text', 'text': 'Transcris ce sujet (et son corrigé s’il est fourni).'})
        _etape(evaluation, 'Lecture du sujet')
        data = _appel(evaluation, evaluation, C.SUJET, [{'role': 'user', 'content': contenu}], C.SCHEMA_SUJET,
                      'medium', max_tokens=32000)
        structure, redigees = structure_depuis(data)
        if not questions(structure):
            raise IAErreur('Aucune question trouvée dans ce document.')
        champs = {'sujet': structure, 'maxima': {}, 'sujet_statut': Evaluation.A_VERIFIER, 'error': ''}
        if data.get('titre') and not evaluation.titre:
            champs['titre'] = str(data['titre'])[:200]
        _etape(evaluation, '', **champs)
        for fs in FichierSujet.objects.filter(evaluation=evaluation):
            fs.delete()  # le fichier part avec (signal)
    except IAErreur as exc:
        _etape(evaluation, '', sujet_statut=Evaluation.ERREUR, error=str(exc)[:1000])
    except Exception as exc:  # noqa: BLE001
        logger.exception('Copies : sujet %s', evaluation_id)
        _etape(evaluation, '', sujet_statut=Evaluation.ERREUR, error=f'Erreur inattendue : {exc.__class__.__name__}')


@transaction.atomic
def compter_copies(user, n):
    u, _ = UsageCopies.objects.select_for_update().get_or_create(user=user, mois=_mois())
    u.copies += n
    u.save(update_fields=['copies'])
