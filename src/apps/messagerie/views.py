"""API de la messagerie : /api/messagerie/… (membres connectés seulement).

Le temps réel (nouveaux messages, « en train d'écrire », appels) passe par le WebSocket /ws/ (consumers.py), ouvert
avec un ticket court obtenu ici. L'envoi d'un message passe par POST (fiable, limité en débit), puis est diffusé.
"""
import base64
import hashlib
import hmac
import time

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.discussions.presenters import author, content_tag
from apps.things.models import Content

from . import regles, services
from .models import Conversation, Message, Participant, SignalementMessage
from .services import Refus, message_dict

PAGE = 40
TICKET_SALT = 'messagerie-ws'


class MessageThrottle(UserRateThrottle):
    scope = 'messagerie'


class SignalementThrottle(UserRateThrottle):
    scope = 'content_report'


def _refus(e):
    return Response({'detail': e.message, 'code': e.code}, status=e.status)


def _conversation(request, pk):
    p = regles.participation(request.user, pk)
    if p is None:
        return None, Response({'detail': 'Conversation introuvable.'}, status=404)
    return p.conversation, None


def _contenu(c, request):
    return None if c is None else content_tag(c, {})


def conversation_dict(conv, viewer, request, non_lus=None, dernier=None):
    membres = [p for p in conv.participants.all() if p.parti_le is None]
    autres = [p.user for p in membres if p.user_id != viewer.id]
    titre = conv.titre or ', '.join(u.username for u in autres[:4]) or 'Conversation'
    return {
        'id': conv.id, 'type': conv.type, 'titre': titre, 'titre_libre': conv.titre,
        'membres': [{**author(p.user, request), 'lu_jusqu_a': p.lu_jusqu_a.isoformat() if p.lu_jusqu_a else None,
                     'question': p.question} for p in membres],
        'contenu': _contenu(conv.contenu, request),
        'dernier_message': message_dict(dernier) if dernier else None,
        'dernier_message_at': conv.dernier_message_at.isoformat(),
        'non_lus': non_lus or 0,
        'lecture_seule': regles.raison_lecture_seule(viewer, conv),
        'createur': conv.createur_id,
        'appel': services.etat_appel(conv),
    }


def _avec_membres(qs):
    return qs.select_related('contenu').prefetch_related(
        Prefetch('participants', queryset=Participant.objects.select_related('user__profile', 'user__profile__class_level')),
        'contenu__class_levels', 'contenu__chapters')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def conversations(request):
    if request.method == 'POST':
        return _creer(request)
    ids = list(services.participations(request.user).order_by('-conversation__dernier_message_at')
               .values_list('conversation_id', flat=True)[:100])
    convs = {c.id: c for c in _avec_membres(Conversation.objects.filter(id__in=ids))}
    nl = services.compte_non_lus(request.user)
    derniers = {}
    for cid in ids:
        derniers[cid] = Message.objects.filter(conversation_id=cid).order_by('-created_at').first()
    return Response({'results': [conversation_dict(convs[i], request.user, request, nl.get(i), derniers.get(i))
                                 for i in ids if i in convs]})


def _creer(request):
    try:
        membres = services.membres_par_noms(request.data.get('membres'))
        contenu = None
        cid = request.data.get('contenu')
        if cid:
            contenu = get_object_or_404(Content, pk=int(cid))
        if len(membres) == 1 and contenu is None and not request.data.get('groupe'):
            conv = services.directe(request.user, membres[0])
        else:
            conv = services.creer_groupe(request.user, membres, request.data.get('titre', ''), contenu)
            if contenu is not None:
                services.ecrire(conv, request.user, '', type=Message.INVITATION,
                                donnees={'contenu': _contenu(contenu, request)})
    except Refus as e:
        return _refus(e)
    except (TypeError, ValueError):
        return Response({'detail': 'Requête invalide.'}, status=400)
    conv = _avec_membres(Conversation.objects.filter(pk=conv.pk)).first()
    return Response(conversation_dict(conv, request.user, request), status=201)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def conversation(request, pk):
    conv, err = _conversation(request, pk)
    if err:
        return err
    if request.method == 'PATCH':
        if conv.type != Conversation.GROUPE:
            return Response({'detail': 'Seul un groupe a un nom.'}, status=400)
        conv.titre = str(request.data.get('titre') or '').strip()[:80]
        conv.save(update_fields=['titre'])
        services.envoyer_maj(conv)
    conv = _avec_membres(Conversation.objects.filter(pk=conv.pk)).first()
    return Response(conversation_dict(conv, request.user, request, services.compte_non_lus(request.user).get(conv.id)))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def messages(request, pk):
    conv, err = _conversation(request, pk)
    if err:
        return err
    if request.method == 'POST':
        return _ecrire(request, conv)
    qs = Message.objects.filter(conversation=conv).order_by('-id')
    avant = request.query_params.get('avant')
    if avant and avant.isdigit():
        qs = qs.filter(id__lt=int(avant))
    lot = list(qs[:PAGE + 1])
    return Response({'results': [message_dict(m) for m in reversed(lot[:PAGE])], 'suite': len(lot) > PAGE})


def _ecrire(request, conv):
    t = MessageThrottle()
    if not t.allow_request(request, None):
        return Response({'detail': 'Trop de messages d’un coup. Attends un peu.'}, status=429)
    try:
        m = services.ecrire(conv, request.user, request.data.get('texte', ''))
    except Refus as e:
        return _refus(e)
    return Response({**message_dict(m), 'client_id': request.data.get('client_id')}, status=201)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def message(request, pk):
    m = get_object_or_404(Message.objects.select_related('conversation'), pk=pk)
    if regles.participation(request.user, m.conversation_id) is None:
        return Response({'detail': 'Message introuvable.'}, status=404)
    try:
        services.supprimer(m, request.user)
    except Refus as e:
        return _refus(e)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SignalementThrottle])
def signaler(request, pk):
    m = get_object_or_404(Message.objects.select_related('conversation'), pk=pk)
    if regles.participation(request.user, m.conversation_id) is None or m.auteur_id == request.user.id:
        return Response({'detail': 'Message introuvable.'}, status=404)
    SignalementMessage.objects.get_or_create(
        message=m, auteur=request.user,
        defaults={'motif': str(request.data.get('motif') or '')[:300], 'texte': m.texte})
    return Response({'ok': True}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def lu(request, pk):
    conv, err = _conversation(request, pk)
    if err:
        return err
    services.marquer_lu(conv, request.user)
    return Response({'ok': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def membres(request, pk):
    conv, err = _conversation(request, pk)
    if err:
        return err
    try:
        services.ajouter(conv, request.user, services.membres_par_noms(request.data.get('membres')))
    except Refus as e:
        return _refus(e)
    conv = _avec_membres(Conversation.objects.filter(pk=conv.pk)).first()
    return Response(conversation_dict(conv, request.user, request))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quitter(request, pk):
    conv, err = _conversation(request, pk)
    if err:
        return err
    try:
        services.quitter(conv, request.user)
    except Refus as e:
        return _refus(e)
    return Response({'ok': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def inviter(request, pk):
    """Propose un sujet à travailler ensemble dans une conversation existante."""
    conv, err = _conversation(request, pk)
    if err:
        return err
    try:
        contenu = get_object_or_404(Content, pk=int(request.data.get('contenu')))
        m = services.ecrire(conv, request.user, '', type=Message.INVITATION,
                            donnees={'contenu': _contenu(contenu, request)})
    except Refus as e:
        return _refus(e)
    except (TypeError, ValueError):
        return Response({'detail': 'Requête invalide.'}, status=400)
    return Response(message_dict(m), status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def non_lus(request):
    return Response({'count': services.non_lus(request.user)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def contacts(request):
    """Abonnés mutuels : les seules personnes à qui on peut écrire (sélecteur « Nouveau message »)."""
    qs = regles.mutuels(request.user).select_related('profile', 'profile__class_level')
    q = (request.query_params.get('q') or '').strip()[:60]
    if q:
        qs = qs.filter(username__icontains=q)
    return Response({'results': [author(u, request) for u in qs.order_by('username')[:50]]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def avec(request, username):
    """Conversation directe avec ce membre (sans la créer) : {id} ou {id: null, peut_ecrire}."""
    other = get_object_or_404(User, username=username)
    cle = f'{min(request.user.id, other.id)}:{max(request.user.id, other.id)}'
    conv = Conversation.objects.filter(cle_directe=cle).first()
    return Response({'id': conv.id if conv else None, 'peut_ecrire': regles.peut_ecrire(request.user, other)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ticket(request):
    """Ticket d'ouverture du WebSocket (60 s) : le jeton de connexion ne passe jamais dans une adresse."""
    return Response({'ticket': signing.dumps({'u': request.user.id}, salt=TICKET_SALT)})


def lire_ticket(valeur):
    try:
        return int(signing.loads(valeur or '', salt=TICKET_SALT, max_age=60)['u'])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ice(request):
    """Serveurs STUN/TURN pour les appels : coturn de Fidni, identifiants temporaires (mécanisme « REST API » de
    coturn, use-auth-secret). Aucun serveur de Google ni d'un tiers."""
    hote = getattr(settings, 'TURN_HOST', '')
    secret = getattr(settings, 'TURN_SECRET', '')
    if not hote:
        return Response({'iceServers': []})
    serveurs = [{'urls': [f'stun:{hote}:3478']}]
    if secret:
        expire = int(time.time()) + getattr(settings, 'TURN_TTL', 6 * 3600)
        nom = f'{expire}:{request.user.id}'
        mdp = base64.b64encode(hmac.new(secret.encode(), nom.encode(), hashlib.sha1).digest()).decode()
        serveurs.append({'urls': [f'turn:{hote}:3478?transport=udp', f'turn:{hote}:3478?transport=tcp'],
                         'username': nom, 'credential': mdp})
    return Response({'iceServers': serveurs})


# ── Équipe : messages signalés ──────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def signalements(request):
    qs = (SignalementMessage.objects.select_related('message__conversation', 'message__auteur__profile', 'auteur__profile')
          .order_by('traite_le', '-created_at'))
    if request.query_params.get('tous') != '1':
        qs = qs.filter(traite_le__isnull=True)
    res = []
    for s in qs[:100]:
        m = s.message
        contexte = Message.objects.filter(conversation_id=m.conversation_id, id__lte=m.id).order_by('-id')[:6]
        res.append({
            'id': s.id, 'motif': s.motif, 'texte': s.texte, 'created_at': s.created_at.isoformat(),
            'traite_le': s.traite_le.isoformat() if s.traite_le else None,
            'par': author(s.auteur, request), 'auteur': author(m.auteur, request) if m.auteur else None,
            'message': message_dict(m),
            'contexte': [{**message_dict(x), 'auteur_nom': x.auteur.username if x.auteur else ''}
                         for x in reversed(list(contexte))],
        })
    return Response({'results': res, 'count': SignalementMessage.objects.filter(traite_le__isnull=True).count()})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def traiter_signalement(request, pk):
    s = get_object_or_404(SignalementMessage, pk=pk)
    s.traite_le = timezone.now()
    s.save(update_fields=['traite_le'])
    if request.data.get('supprimer'):
        m = s.message
        if m.supprime_le is None:
            m.supprime_le = timezone.now()
            m.save(update_fields=['supprime_le'])
    return Response({'ok': True})
