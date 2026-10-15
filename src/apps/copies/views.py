"""API des copies (Classes › Évaluations).

Professeur (propriétaire de la classe ; tout autre compte reçoit 404) :
    /api/classrooms/<cid>/evaluations/                         GET liste · POST création
    /api/classrooms/<cid>/evaluations/<eid>/                   GET · PATCH (titre, barème, consignes, sujet) · DELETE
    …/<eid>/sujet/import/                                      POST : sujet privé depuis un PDF (lu par l'IA)
    …/<eid>/copies/                                            GET : un élève par ligne, avec sa copie
                                                               POST {nom} : copie d'un élève sans compte
    …/<eid>/copies/<id>/pages/                                 POST : ajoute des pages à cette copie
    …/<eid>/eleves/<sid>/pages/                                POST : ajoute des pages (photo ou PDF)
    …/<eid>/pages/<pid>/                                       DELETE
    …/<eid>/copies/<id>/                                       GET (correction) · PATCH (notes, valider) · DELETE
    …/<eid>/copies/<id>/ordre/                                 POST {pages: [ids]}
    …/<eid>/copies/<id>/recorriger/                            POST {chemins?}
    …/<eid>/corriger/                                          POST {copies: [ids] | 'toutes'}
    …/<eid>/publier/                                           POST {copies: [ids] | 'validees'}
    …/<eid>/rapport/                                           GET
    …/<eid>/export/?type=csv|xlsx                              GET (« format » est réservé par DRF)
    …/<eid>/lots/                                              POST : PDF de toute la classe
    …/<eid>/lots/<lid>/                                        GET · DELETE ;  …/confirmer/  POST {groupes}
Élève :
    /api/mes-copies/   ·   /api/mes-copies/<id>/                copies publiées de l'élève connecté
Images (balise <img> : pas d'en-tête d'authentification, lien signé 10 min) :
    /api/copies/pages/<pid>/?s=…    ·    /api/copies/lots/<lid>/pages/<n>/?s=…
"""
import csv
import io

from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.classrooms.models import Classroom, ClassroomMembership
from config.throttling import CopiesIAThrottle, CopiesUploadThrottle

from . import analyse, images, traitement
from .bareme import completer_ids, notes_finales, questions, total
from .models import Copie, Evaluation, FichierSujet, Lot, Page

SIGNATURE_AGE = 600
SEL_PAGE, SEL_LOT = 'copies-page', 'copies-lot'
PAS = (0.25, 0.5, 1)


# --------------------------------------------------------------------------- outils

def _actif():
    if not getattr(settings, 'COPIES_ACTIVES', True):
        raise Http404


def _classe(request, cid):
    _actif()
    return get_object_or_404(Classroom, pk=cid, owner=request.user)


def _evaluation(request, cid, eid):
    return get_object_or_404(Evaluation.objects.select_related('classroom', 'content'),
                             pk=eid, classroom=_classe(request, cid))


def _err(message, code=400):
    return Response({'error': message}, status=code)


def _url_page(page, user):
    s = signing.TimestampSigner(salt=SEL_PAGE).sign(f'{page.id}:{user.id}')
    return f'/api/copies/pages/{page.id}/?s={s}'


def _url_lot(lot, n, user):
    s = signing.TimestampSigner(salt=SEL_LOT).sign(f'{lot.id}:{n}:{user.id}')
    return f'/api/copies/lots/{lot.id}/pages/{n}/?s={s}'


def _eleve(u):
    return {'id': u.id, 'username': u.username}


def _qui(c):
    """Élève de la copie : compte Fidni, ou nom tapé par le professeur (élève sans compte)."""
    if c.eleve_id:
        return {'id': c.eleve_id, 'username': c.eleve.username, 'sans_compte': False}
    return {'id': None, 'username': c.nom, 'sans_compte': True}


def _note(evaluation, copie, qs):
    pts, maxi, note = total(evaluation, copie, qs)
    return {'points': pts, 'max': maxi, 'note': note, 'note_sur': evaluation.note_sur}


def _resume_copie(c, evaluation, qs):
    return {
        'id': c.id, 'statut': c.statut, 'etape': c.etape, 'error': c.error,
        'nb_pages': getattr(c, 'nb_pages', None) if hasattr(c, 'nb_pages') else c.pages.count(),
        **_note(evaluation, c, qs),
        'drapeaux': len(c.drapeaux or []),
        'publiee': bool(c.publiee_le and c.statut == Copie.VALIDEE),
    }


def _resume_evaluation(e, compter=True):
    out = {
        'id': e.id, 'titre': e.titre, 'date': e.date.isoformat() if e.date else None, 'note_sur': e.note_sur,
        'pas': e.pas, 'source': e.source, 'sujet_statut': e.sujet_statut,
        'content': {'id': e.content.id, 'type': e.content.type, 'title': e.content.title} if e.content else None,
        'created_at': e.created_at.isoformat(),
    }
    if compter:
        compte = {}
        for s in e.copies.values_list('statut', flat=True):
            compte[s] = compte.get(s, 0) + 1
        out['copies'] = compte
        out['publiees'] = e.copies.filter(publiee_le__isnull=False, statut=Copie.VALIDEE).count()
    return out


def _questions_publiques(qs):
    return [{'chemin': q['chemin'], 'label': q['label'], 'partie': q['partie'], 'max': q['max'],
             'theoremes': q['theoremes'], 'enonce_html': q['enonce_html'], 'solution_html': q['solution_html']}
            for q in qs]


def _chemins(structure):
    return [q['chemin'] for q in questions(structure)]


# --------------------------------------------------------------------------- évaluations

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def evaluations(request, cid):
    classe = _classe(request, cid)
    if request.method == 'GET':
        qs = classe.evaluations.select_related('content').all()
        return Response({'evaluations': [_resume_evaluation(e) for e in qs],
                         'quota_restant': traitement.quota_restant(request.user)})
    d = request.data
    titre = str(d.get('titre') or '').strip()[:200]
    e = Evaluation(classroom=classe, created_by=request.user, titre=titre)
    try:
        e.note_sur = max(1, min(100, int(d.get('note_sur') or 20)))
        e.pas = float(d.get('pas') or 0.5)
    except (TypeError, ValueError):
        return _err('Barème invalide.')
    if e.pas not in PAS:
        return _err('Arrondi : 0,25, 0,5 ou 1 point.')
    if d.get('date'):
        try:
            e.date = timezone.datetime.fromisoformat(str(d['date'])).date()
        except ValueError:
            return _err('Date invalide (AAAA-MM-JJ).')
    if d.get('content_id'):
        from apps.things.models import Content
        content = Content.objects.filter(pk=d['content_id'], type__in=('exam', 'exercise')).first()
        if content is None:
            return _err('Contenu introuvable (un devoir ou un exercice).')
        e.content, e.source = content, Evaluation.FIDNI
        e.sujet = completer_ids(content.json_content)
        e.titre = e.titre or content.title[:200]
        if not questions(e.sujet):
            return _err('Ce contenu n’a pas de questions à noter.')
    else:
        e.source, e.sujet = Evaluation.PRIVE, {'version': '2.1', 'blocks': []}
    if not e.titre:
        return _err('Donne un titre à l’évaluation.')
    e.save()
    return Response(_detail_evaluation(e, request.user), status=201)


def _detail_evaluation(e, user):
    qs = questions(e.sujet, e.maxima)
    # Découpage d'un PDF de classe pas encore confirmé : le panneau revient si le professeur a quitté la page.
    lot_ouvert = e.lots.exclude(statut=Lot.CONFIRME).first()
    return {**_resume_evaluation(e), 'consignes': e.consignes, 'sujet': e.sujet, 'maxima': e.maxima,
            'lot': _detail_lot(lot_ouvert, user) if lot_ouvert else None,
            'questions': _questions_publiques(qs), 'total_max': round(sum(q['max'] for q in qs), 2),
            'etape': e.etape, 'error': e.error, 'quota_restant': traitement.quota_restant(user),
            'modifiable': not e.copies.exclude(ia={}, notes={}).exists()}


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def evaluation(request, cid, eid):
    e = _evaluation(request, cid, eid)
    if request.method == 'GET':
        return Response(_detail_evaluation(e, request.user))
    if request.method == 'DELETE':
        e.delete()
        return Response(status=204)
    d = request.data
    if 'titre' in d:
        titre = str(d['titre'] or '').strip()[:200]
        if not titre:
            return _err('Donne un titre à l’évaluation.')
        e.titre = titre
    if 'date' in d:
        try:
            e.date = timezone.datetime.fromisoformat(str(d['date'])).date() if d['date'] else None
        except ValueError:
            return _err('Date invalide (AAAA-MM-JJ).')
    if 'note_sur' in d:
        try:
            e.note_sur = max(1, min(100, int(d['note_sur'])))
        except (TypeError, ValueError):
            return _err('Note sur : un nombre entier.')
    if 'pas' in d:
        try:
            pas = float(d['pas'])
        except (TypeError, ValueError):
            pas = None
        if pas not in PAS:
            return _err('Arrondi : 0,25, 0,5 ou 1 point.')
        e.pas = pas
    if 'consignes' in d:
        e.consignes = str(d['consignes'] or '')[:2000]
    if 'sujet' in d:
        sujet = d['sujet'] if isinstance(d['sujet'], dict) else None
        if sujet is None or not isinstance(sujet.get('blocks'), list):
            return _err('Sujet invalide.')
        # HTML nettoyé à l'affichage (sanitizeHtml du renderer), comme les contenus du site.
        sujet = completer_ids(sujet)
        notees = e.copies.exclude(ia={}, notes={}).exists()
        if notees and _chemins(sujet) != _chemins(e.sujet):
            return _err('Des copies sont déjà corrigées : on peut changer les textes et les points, pas ajouter, '
                        'retirer ou déplacer des questions.', 409)
        e.sujet = sujet
        if e.sujet_statut == Evaluation.A_VERIFIER and d.get('sujet_verifie'):
            e.sujet_statut = Evaluation.PRET
    if 'maxima' in d:
        m = d['maxima'] if isinstance(d['maxima'], dict) else {}
        valides = set(_chemins(e.sujet))
        try:
            e.maxima = {k: round(max(0.0, min(100.0, float(v))), 2) for k, v in m.items() if k in valides}
        except (TypeError, ValueError):
            return _err('Points invalides.')
    if d.get('sujet_verifie') and e.sujet_statut == Evaluation.A_VERIFIER:
        e.sujet_statut = Evaluation.PRET
    e.save()
    _recalculer(e)
    return Response(_detail_evaluation(e, request.user))


def _recalculer(e):
    """Barème ou arrondi changé : les totaux des copies suivent."""
    qs = questions(e.sujet, e.maxima)
    for c in e.copies.exclude(statut=Copie.VIDE):
        t = total(e, c, qs)[0]
        if t != c.total:
            Copie.objects.filter(pk=c.pk).update(total=t)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesIAThrottle])
def importer_sujet(request, cid, eid):
    e = _evaluation(request, cid, eid)
    if e.source != Evaluation.PRIVE:
        return _err('Le sujet vient d’un contenu Fidni : il est déjà prêt.')
    if e.copies.exclude(ia={}, notes={}).exists():
        return _err('Des copies sont déjà corrigées avec ce sujet.', 409)
    if e.sujet_statut == Evaluation.EN_COURS:
        return _err('Lecture du sujet déjà en cours.', 409)
    fichiers = request.FILES.getlist('fichiers')
    if not 1 <= len(fichiers) <= 4:
        return _err('Envoie le sujet (et son corrigé si tu l’as) : 4 fichiers au plus.')
    if traitement.quota_restant(request.user) == 0:
        return _err('Quota du mois atteint.', 429)
    for f in fichiers:
        donnees = f.read()
        if len(donnees) > images.TAILLE_MAX:
            return _err(f'« {f.name} » : 25 Mo au plus.')
        try:
            images.sorte(f.name, f.content_type, donnees)
        except images.FichierRefuse as exc:
            return _err(f'« {f.name} » : {exc}')
        f.seek(0)
    FichierSujet.objects.filter(evaluation=e).delete()
    for f in fichiers:
        FichierSujet.objects.create(evaluation=e, nom=f.name[:255], fichier=ContentFile(f.read(), name=f.name))
    traitement.compter_copies(request.user, 1)
    e.sujet_statut, e.error, e.etape, e.heartbeat = Evaluation.EN_COURS, '', 'En attente', timezone.now()
    e.save(update_fields=['sujet_statut', 'error', 'etape', 'heartbeat', 'updated_at'])
    traitement.lancer('sujet', e.pk)
    return Response(_detail_evaluation(e, request.user), status=202)


# --------------------------------------------------------------------------- copies (professeur)

def _lignes(e):
    """(élève ou None, nom affiché, membre ?, copie ou None) : membres, anciens membres, puis élèves sans compte."""
    tout = list(e.copies.select_related('eleve'))
    par_eleve = {c.eleve_id: c for c in tout if c.eleve_id}
    membres = [m.student for m in ClassroomMembership.objects.filter(classroom=e.classroom)
               .select_related('student').order_by('student__username')]
    ids = {m.id for m in membres}
    out = [(u, u.username, True, par_eleve.get(u.id)) for u in membres]
    out += [(c.eleve, c.eleve.username, False, c) for c in sorted(par_eleve.values(), key=lambda c: c.eleve.username)
            if c.eleve_id not in ids]
    out += [(None, c.nom, False, c) for c in sorted((c for c in tout if not c.eleve_id), key=lambda c: c.nom.lower())]
    return out


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def copies(request, cid, eid):
    """GET : un élève par ligne. POST {nom} : nouvelle copie d'un élève sans compte Fidni."""
    e = _evaluation(request, cid, eid)
    qs = questions(e.sujet, e.maxima)
    if request.method == 'POST':
        nom = ' '.join(str(request.data.get('nom') or '').split())[:120]
        if not nom:
            return _err('Écris le nom de l’élève.')
        if e.copies.filter(eleve__isnull=True, nom__iexact=nom).exists():
            return _err('Il y a déjà une copie à ce nom.')
        c = Copie.objects.create(evaluation=e, nom=nom)
        return Response({'eleve': _qui(c), 'membre': False, 'sans_compte': True,
                         'copie': _resume_copie(c, e, qs)}, status=201)
    lignes = [{'eleve': _eleve(u) if u else {'id': None, 'username': nom}, 'membre': membre, 'sans_compte': u is None,
               'copie': _resume_copie(c, e, qs) if c else None}
              for u, nom, membre, c in _lignes(e)]
    return Response({'copies': lignes, 'quota_restant': traitement.quota_restant(request.user)})


def _deposer(e, copie, f):
    """Ajoute les pages d'un fichier (photo ou PDF) à une copie → Response."""
    if f is None:
        return _err('Aucun fichier.')
    if copie.statut == Copie.EN_COURS:
        return _err('Correction en cours : attends qu’elle se termine.', 409)
    deja = copie.pages.count()
    try:
        nouvelles = images.pages(f.read(), f.name, f.content_type, limite=settings.COPIES_PAGES_MAX - deja)
    except images.FichierRefuse as exc:
        return _err(str(exc))
    if not nouvelles:
        return _err('Aucune page lisible.')
    with transaction.atomic():
        for i, (jpeg, w, h) in enumerate(nouvelles, deja + 1):
            Page.objects.create(copie=copie, numero=i, largeur=w, hauteur=h,
                                fichier=ContentFile(jpeg, name='page.jpg'))
        if copie.statut == Copie.VIDE:
            copie.statut = Copie.DEPOSEE
            copie.save(update_fields=['statut', 'updated_at'])
    return Response(_resume_copie(copie, e, questions(e.sujet, e.maxima)), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesUploadThrottle])
def ajouter_pages_copie(request, cid, eid, pk):
    e = _evaluation(request, cid, eid)
    return _deposer(e, get_object_or_404(Copie, pk=pk, evaluation=e), request.FILES.get('fichier'))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesUploadThrottle])
def ajouter_pages(request, cid, eid, sid):
    e = _evaluation(request, cid, eid)
    if not ClassroomMembership.objects.filter(classroom=e.classroom, student_id=sid).exists():
        return _err('Cet élève n’est pas dans la classe.', 404)
    f = request.FILES.get('fichier')
    if f is None:
        return _err('Aucun fichier.')
    copie, _ = Copie.objects.get_or_create(evaluation=e, eleve_id=sid)
    return _deposer(e, copie, f)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def supprimer_page(request, cid, eid, pid):
    e = _evaluation(request, cid, eid)
    page = get_object_or_404(Page, pk=pid, copie__evaluation=e)
    copie = page.copie
    if copie.statut == Copie.EN_COURS:
        return _err('Correction en cours.', 409)
    page.delete()
    for i, p in enumerate(copie.pages.all(), 1):
        if p.numero != i:
            Page.objects.filter(pk=p.pk).update(numero=i)
    if not copie.pages.exists() and not copie.notes:
        copie.statut = Copie.VIDE
        copie.save(update_fields=['statut', 'updated_at'])
    return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ordonner_pages(request, cid, eid, pk):
    e = _evaluation(request, cid, eid)
    copie = get_object_or_404(Copie, pk=pk, evaluation=e)
    ids = request.data.get('pages')
    actuelles = list(copie.pages.values_list('id', flat=True))
    if not isinstance(ids, list) or sorted(ids) != sorted(actuelles):
        return _err('Ordre des pages invalide.')
    for i, pid in enumerate(ids, 1):
        Page.objects.filter(pk=pid).update(numero=i)
    return Response({'ok': True})


def _detail_copie(e, c, user, prof=True):
    qs = questions(e.sujet, e.maxima)
    finales = notes_finales(e, c, qs)
    out = {
        'id': c.id, 'statut': c.statut, 'etape': c.etape, 'error': c.error,
        'evaluation': _resume_evaluation(e, compter=False),
        'eleve': _qui(c),
        'questions': _questions_publiques(qs),
        'finales': finales,
        **_note(e, c, qs),
        'commentaire_prof': c.commentaire_prof,
        'commentaire_global': c.ia_global,
        'pages': [{'id': p.id, 'numero': p.numero, 'url': _url_page(p, user), 'largeur': p.largeur,
                   'hauteur': p.hauteur} for p in c.pages.all()],
        'publiee_le': c.publiee_le.isoformat() if c.publiee_le else None,
    }
    if prof:
        ordre = [cp.id for _u, _n, _m, cp in _lignes(e) if cp and cp.statut != Copie.VIDE]
        i = ordre.index(c.id) if c.id in ordre else -1
        out.update({
            'transcription': c.transcription, 'ia': c.ia, 'notes': c.notes, 'drapeaux': c.drapeaux,
            'usage': c.usage, 'validee_le': c.validee_le.isoformat() if c.validee_le else None,
            'precedente': ordre[i - 1] if i > 0 else None,
            'suivante': ordre[i + 1] if 0 <= i < len(ordre) - 1 else None,
        })
    return out


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def copie(request, cid, eid, pk):
    e = _evaluation(request, cid, eid)
    c = get_object_or_404(Copie.objects.select_related('eleve'), pk=pk, evaluation=e)
    if request.method == 'GET':
        return Response(_detail_copie(e, c, request.user))
    if c.statut == Copie.EN_COURS:
        return _err('Correction en cours : attends qu’elle se termine.', 409)
    if request.method == 'DELETE':
        c.delete()  # pages et fichiers avec (signal)
        return Response(status=204)
    d = request.data
    qs = questions(e.sujet, e.maxima)
    maxi = {q['chemin']: q['max'] for q in qs}
    if 'notes' in d:
        if not isinstance(d['notes'], dict):
            return _err('Notes invalides.')
        notes = dict(c.notes or {})
        for chemin, v in d['notes'].items():
            if chemin not in maxi or not isinstance(v, dict):
                continue
            n = dict(notes.get(chemin) or {})
            if 'points' in v:
                if v['points'] is None or v['points'] == '':
                    n.pop('points', None)
                else:
                    try:
                        p = float(v['points'])
                    except (TypeError, ValueError):
                        return _err('Points invalides.')
                    if not 0 <= p <= maxi[chemin]:
                        return _err(f'Points entre 0 et {maxi[chemin]:g}.')
                    n['points'] = p
            if 'commentaire' in v:  # null : on revient au commentaire de l'IA
                if v['commentaire'] is None:
                    n.pop('commentaire', None)
                else:
                    n['commentaire'] = str(v['commentaire'])[:1000]
            if n:
                notes[chemin] = n
            else:
                notes.pop(chemin, None)
        c.notes = notes
    if 'commentaire_prof' in d:
        c.commentaire_prof = str(d['commentaire_prof'] or '')[:2000]
    if 'transcription' in d and isinstance(d['transcription'], dict):
        tr = dict(c.transcription or {})
        for chemin, texte in d['transcription'].items():
            if chemin in maxi:
                ancien = tr.get(chemin) or {}
                tr[chemin] = {**ancien, 'texte': str(texte or '')[:6000], 'modifie': True}
        c.transcription = tr
    if 'valider' in d:
        if d['valider']:
            if total(e, c, qs)[0] is None:
                return _err('Chaque question doit avoir une note avant de valider.')
            c.statut, c.validee_le = Copie.VALIDEE, timezone.now()
        elif c.statut == Copie.VALIDEE:
            c.statut = Copie.CORRIGEE if c.ia else Copie.DEPOSEE
            c.validee_le = None
    elif c.statut == Copie.DEPOSEE and c.notes and total(e, c, qs)[0] is not None:
        c.statut = Copie.CORRIGEE  # notée entièrement à la main
    c.total = total(e, c, qs)[0]
    c.save()
    return Response(_detail_copie(e, c, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesIAThrottle])
def recorriger(request, cid, eid, pk):
    e = _evaluation(request, cid, eid)
    c = get_object_or_404(Copie, pk=pk, evaluation=e)
    if c.statut in (Copie.EN_COURS, Copie.EN_ATTENTE):
        return _err('Correction déjà en cours.', 409)
    if not c.pages.exists():
        return _err('Cette copie n’a pas de page.')
    valides = set(_chemins(e.sujet))
    chemins = [x for x in (request.data.get('chemins') or []) if x in valides]
    if not chemins:  # toute la copie : compte dans le quota
        if traitement.quota_restant(request.user) == 0:
            return _err('Quota du mois atteint.', 429)
        traitement.compter_copies(request.user, 1)
    c.a_renoter, c.statut, c.error, c.essais, c.validee_le = chemins, Copie.EN_ATTENTE, '', 0, None
    c.save()
    traitement.demarrer_corrections(e)
    return Response({'ok': True, 'statut': c.statut}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesIAThrottle])
def corriger(request, cid, eid):
    """Lance la correction par l'IA des copies déposées (toutes, ou celles demandées)."""
    e = _evaluation(request, cid, eid)
    if not questions(e.sujet, e.maxima):
        return _err('Le sujet n’a aucune question.')
    if e.sujet_statut in (Evaluation.EN_COURS, Evaluation.ERREUR):
        return _err('Le sujet n’est pas prêt.')
    voulues = request.data.get('copies', 'toutes')
    qs = e.copies.filter(pages__isnull=False).distinct()
    if voulues == 'toutes':
        qs = qs.filter(statut__in=[Copie.DEPOSEE, Copie.ERREUR])
    elif isinstance(voulues, list):
        qs = qs.filter(pk__in=voulues).exclude(statut__in=[Copie.EN_COURS, Copie.EN_ATTENTE, Copie.VALIDEE])
    else:
        return _err('Copies : liste d’identifiants ou « toutes ».')
    ids = list(qs.values_list('id', flat=True))
    if not ids:
        return _err('Aucune copie à corriger (dépose d’abord des pages).')
    reste = traitement.quota_restant(request.user)
    if reste is not None and len(ids) > reste:
        return _err(f'Quota du mois : encore {reste} copie(s) corrigeable(s) par l’IA ce mois-ci.', 429)
    traitement.compter_copies(request.user, len(ids))
    Copie.objects.filter(pk__in=ids).update(statut=Copie.EN_ATTENTE, error='', essais=0, a_renoter=[],
                                            etape='En attente', validee_le=None)
    traitement.demarrer_corrections(e)
    return Response({'lancees': len(ids), 'quota_restant': traitement.quota_restant(request.user)}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def publier(request, cid, eid):
    """Rend les copies validées visibles à leurs élèves (et les prévient)."""
    from apps.notifications.models import Notification
    e = _evaluation(request, cid, eid)
    voulues = request.data.get('copies', 'validees')
    # Un élève sans compte ne peut rien recevoir : seules les copies d'élèves inscrits sont publiées.
    qs = e.copies.filter(statut=Copie.VALIDEE, publiee_le__isnull=True, eleve__isnull=False).select_related('eleve')
    if isinstance(voulues, list):
        qs = qs.filter(pk__in=voulues)
    elif voulues != 'validees':
        return _err('Copies : liste d’identifiants ou « validees ».')
    maintenant = timezone.now()
    n = 0
    for c in qs:
        c.publiee_le = maintenant
        c.save(update_fields=['publiee_le', 'updated_at'])
        n += 1
        if c.eleve.is_active:
            Notification.objects.update_or_create(
                recipient=c.eleve, kind=Notification.KIND_COPIE, target=f'copie:{c.id}',
                defaults={'title': e.titre[:200], 'link': f'/mes-copies/{c.id}', 'actor': request.user,
                          'excerpt': 'Ta copie corrigée est disponible.', 'count': 1, 'updated_at': maintenant,
                          'read_at': None})
    sans_compte = e.copies.filter(statut=Copie.VALIDEE, eleve__isnull=True).count()
    return Response({'publiees': n, 'sans_compte': sans_compte})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def rapport(request, cid, eid):
    return Response(analyse.rapport(_evaluation(request, cid, eid)))


def _virgule(x):
    return '' if x is None else f'{x:g}'.replace('.', ',')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def exporter(request, cid, eid):
    """Notes de la classe : une ligne par élève, une colonne par question (tableur, cahier de textes, Massar)."""
    e = _evaluation(request, cid, eid)
    fmt = request.query_params.get('type', 'csv')
    qs = questions(e.sujet, e.maxima)
    entete = ['Élève', 'Statut'] + [f"{q['label']} (/{q['max']:g})" for q in qs] + \
        [f'Total (/{sum(q["max"] for q in qs):g})', f'Note (/{e.note_sur})']
    lignes = []
    statuts = dict(Copie.STATUTS)
    for _u, nom_eleve, _membre, c in _lignes(e):
        if c is None:
            lignes.append([nom_eleve, 'Pas de copie'] + [None] * (len(qs) + 2))
            continue
        fin = notes_finales(e, c, qs)
        pts, _m, note = total(e, c, qs)
        lignes.append([nom_eleve, statuts.get(c.statut, c.statut)] + [fin[q['chemin']]['points'] for q in qs]
                      + [pts, note])
    nom = f"notes-{e.titre[:40]}".replace('/', '-').replace('"', '')
    if fmt == 'xlsx':
        try:
            from openpyxl import Workbook
        except ImportError:
            return _err('Export Excel indisponible sur ce serveur : utiliser le CSV.', 501)
        wb = Workbook()
        ws = wb.active
        ws.title = 'Notes'
        ws.append(entete)
        for ligne in lignes:
            ws.append(ligne)
        out = io.BytesIO()
        wb.save(out)
        r = HttpResponse(out.getvalue(),
                         content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r['Content-Disposition'] = f'attachment; filename="{nom}.xlsx"'
        return r
    out = io.StringIO()
    w = csv.writer(out, delimiter=';')
    w.writerow(entete)
    for ligne in lignes:
        w.writerow([_virgule(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else (x or '')
                    for x in ligne])
    r = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    r['Content-Disposition'] = f'attachment; filename="{nom}.csv"'
    return r


# --------------------------------------------------------------------------- PDF de toute la classe

def _detail_lot(lot, user):
    eleves = {m.student_id: m.student.username for m in ClassroomMembership.objects
              .filter(classroom=lot.evaluation.classroom).select_related('student')}
    return {
        'id': lot.id, 'nom': lot.nom, 'statut': lot.statut, 'etape': lot.etape, 'error': lot.error,
        'nb_pages': lot.nb_pages, 'pages_par_copie': lot.pages_par_copie,
        'proposition': lot.proposition,
        'pages': [_url_lot(lot, n, user) for n in range(1, lot.nb_pages + 1)] if lot.statut == Lot.PRET else [],
        'eleves': [{'id': i, 'username': u} for i, u in sorted(eleves.items(), key=lambda x: x[1])],
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesIAThrottle])
def lots(request, cid, eid):
    e = _evaluation(request, cid, eid)
    f = request.FILES.get('fichier')
    if f is None:
        return _err('Aucun fichier.')
    donnees = f.read()
    if len(donnees) > images.TAILLE_MAX:
        return _err('Fichier trop lourd (25 Mo au plus) : envoie la classe en plusieurs PDF.')
    if donnees[:5] != b'%PDF-':
        return _err('Envoie un PDF (toutes les copies scannées à la suite).')
    try:
        n = images.nb_pages_pdf(donnees)
    except images.FichierRefuse as exc:
        return _err(str(exc))
    if not 1 <= n <= settings.COPIES_LOT_PAGES_MAX:
        return _err(f'{settings.COPIES_LOT_PAGES_MAX} pages au plus par PDF.')
    ppc = request.data.get('pages_par_copie')
    try:
        ppc = int(ppc) if ppc not in (None, '', '0') else None
    except (TypeError, ValueError):
        return _err('Pages par copie : un nombre.')
    if ppc is not None and not 1 <= ppc <= settings.COPIES_PAGES_MAX:
        return _err('Pages par copie invalide.')
    lot = Lot.objects.create(evaluation=e, nom=f.name[:255], nb_pages=n, pages_par_copie=ppc,
                             created_by=request.user, fichier=ContentFile(donnees, name='classe.pdf'))
    traitement.lancer('lot', lot.pk)
    return Response(_detail_lot(lot, request.user), status=202)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def lot(request, cid, eid, lid):
    e = _evaluation(request, cid, eid)
    lt = get_object_or_404(Lot, pk=lid, evaluation=e)
    if request.method == 'DELETE':
        lt.delete()
        return Response(status=204)
    return Response(_detail_lot(lt, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirmer_lot(request, cid, eid, lid):
    """Crée les copies d'après le découpage validé par le professeur : [{pages: [1, 2], eleve_id}] ; un groupe
    {pages, nom} sans eleve_id devient la copie d'un élève sans compte."""
    e = _evaluation(request, cid, eid)
    lt = get_object_or_404(Lot, pk=lid, evaluation=e)
    if lt.statut != Lot.PRET:
        return _err('Ce découpage n’est pas prêt.', 409)
    groupes = request.data.get('groupes')
    membres = set(ClassroomMembership.objects.filter(classroom=e.classroom).values_list('student_id', flat=True))
    if not isinstance(groupes, list):
        return _err('Découpage invalide.')
    vus_eleves, vues_pages, propres = set(), set(), []
    noms = set()
    for g in groupes:
        nom = ' '.join(str(g.get('nom') or '').split())[:120] if isinstance(g, dict) else ''
        if not isinstance(g, dict) or not (g.get('eleve_id') or nom):
            continue  # pages laissées de côté (non attribuées)
        try:
            sid = int(g['eleve_id']) if g.get('eleve_id') else None
            pages_g = [int(p) for p in g.get('pages') or []]
        except (TypeError, ValueError):
            return _err('Découpage invalide.')
        if sid is not None and sid not in membres:
            return _err('Un élève choisi n’est pas dans la classe.')
        if (sid is not None and sid in vus_eleves) or (sid is None and nom.lower() in noms):
            return _err('Un élève a reçu deux copies : regroupe ses pages.')
        if sid is None:
            noms.add(nom.lower())
            sid = ('nom', nom)
        if not pages_g or any(not 1 <= p <= lt.nb_pages or p in vues_pages for p in pages_g):
            return _err('Pages invalides ou attribuées deux fois.')
        if len(pages_g) > settings.COPIES_PAGES_MAX:
            return _err(f'{settings.COPIES_PAGES_MAX} pages au plus par copie.')
        if not isinstance(sid, tuple):
            vus_eleves.add(sid)
        vues_pages.update(pages_g)
        propres.append((sid, pages_g))
    if not propres:
        return _err('Attribue au moins une copie à un élève.')
    publiees = set(e.copies.filter(eleve_id__in=vus_eleves, publiee_le__isnull=False)
                   .values_list('eleve_id', flat=True))
    if publiees:
        return _err('Certaines de ces copies sont déjà publiées : retire-les du découpage.', 409)
    with lt.fichier.open('rb') as f:
        pdf = f.read()
    crees = 0
    for sid, pages_g in propres:
        if isinstance(sid, tuple):  # élève sans compte : même nom = même copie
            c = e.copies.filter(eleve__isnull=True, nom__iexact=sid[1]).first() or Copie(evaluation=e, nom=sid[1])
            if c.publiee_le:
                continue
            c.save()
        else:
            c, _ = Copie.objects.get_or_create(evaluation=e, eleve_id=sid)
        if c.statut == Copie.EN_COURS:
            continue
        for p in list(c.pages.all()):
            p.delete()
        for i, n in enumerate(pages_g, 1):
            jpeg, w, h = images.page_pdf(pdf, n)
            Page.objects.create(copie=c, numero=i, largeur=w, hauteur=h, fichier=ContentFile(jpeg, name='page.jpg'))
        c.statut, c.transcription, c.ia, c.ia_global, c.drapeaux, c.total = Copie.DEPOSEE, {}, {}, '', [], None
        c.validee_le, c.error, c.essais = None, '', 0
        c.save()
        crees += 1
    lt.proposition = groupes
    lt.statut = Lot.CONFIRME
    lt.fichier.delete(save=False)
    lt.save()
    return Response({'copies': crees})


# --------------------------------------------------------------------------- élève

def _copie_eleve(request, pk):
    _actif()
    return get_object_or_404(Copie.objects.select_related('evaluation__classroom', 'eleve'), pk=pk,
                             eleve=request.user, statut=Copie.VALIDEE, publiee_le__isnull=False)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mes_copies(request):
    _actif()
    qs = (Copie.objects.filter(eleve=request.user, statut=Copie.VALIDEE, publiee_le__isnull=False)
          .select_related('evaluation__classroom').order_by('-publiee_le'))
    if request.query_params.get('classe'):
        qs = qs.filter(evaluation__classroom_id=request.query_params['classe'])
    out = []
    for c in qs:
        e = c.evaluation
        q = questions(e.sujet, e.maxima)
        out.append({'id': c.id, 'titre': e.titre, 'date': e.date.isoformat() if e.date else None,
                    'classe': {'id': e.classroom_id, 'name': e.classroom.name},
                    'publiee_le': c.publiee_le.isoformat(), **_note(e, c, q)})
    return Response({'copies': out})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ma_copie(request, pk):
    c = _copie_eleve(request, pk)
    e = c.evaluation
    out = _detail_copie(e, c, request.user, prof=False)
    # L'élève ne voit pas d'où vient la note (professeur ou IA) : seulement la note et le commentaire retenus.
    out['finales'] = {k: {kk: vv for kk, vv in v.items() if kk != 'source'} for k, v in out['finales'].items()}
    out['classe'] = {'id': e.classroom_id, 'name': e.classroom.name}
    out['points_faibles'] = analyse.points_faibles(e, c)
    return Response(out)


# --------------------------------------------------------------------------- images signées

def _signe(sel, valeur):
    try:
        return signing.TimestampSigner(salt=sel).unsign(valeur, max_age=SIGNATURE_AGE)
    except signing.BadSignature:
        raise Http404


def _image(octets_ou_fichier):
    r = (FileResponse(octets_ou_fichier, content_type='image/jpeg') if not isinstance(octets_ou_fichier, bytes)
         else HttpResponse(octets_ou_fichier, content_type='image/jpeg'))
    r['Cache-Control'] = 'private, no-store'
    r['X-Content-Type-Options'] = 'nosniff'
    return r


@api_view(['GET'])
@permission_classes([AllowAny])
def image_page(request, pid):
    _actif()
    pid_s, uid_s = _signe(SEL_PAGE, request.query_params.get('s', '')).split(':')
    if int(pid_s) != pid:
        raise Http404
    page = get_object_or_404(Page.objects.select_related('copie__evaluation__classroom'), pk=pid)
    c = page.copie
    uid = int(uid_s)
    # Le lien n'a été donné qu'au professeur de la classe ou à l'élève de la copie publiée : on le revérifie.
    if uid != c.evaluation.classroom.owner_id and not (
            uid == c.eleve_id and c.publiee_le and c.statut == Copie.VALIDEE):
        raise Http404
    return _image(page.fichier.open('rb'))


@api_view(['GET'])
@permission_classes([AllowAny])
def image_lot(request, lid, n):
    _actif()
    lid_s, n_s, uid_s = _signe(SEL_LOT, request.query_params.get('s', '')).split(':')
    if int(lid_s) != lid or int(n_s) != n:
        raise Http404
    lt = get_object_or_404(Lot.objects.select_related('evaluation__classroom'), pk=lid)
    if int(uid_s) != lt.evaluation.classroom.owner_id or not lt.fichier or not 1 <= n <= lt.nb_pages:
        raise Http404
    with lt.fichier.open('rb') as f:
        jpeg, _w, _h = images.page_pdf(f.read(), n, cote=700)
    return _image(jpeg)
