"""Autorisation accordée dans le navigateur à l'atelier présent sur le même PC."""
import hashlib
import re
import zipfile

from django.contrib.auth import get_user_model
from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.users.admin_dashboard import IsSuperuser
from .atelier_archive import LIMIT, traiter_archive

SALT = 'fidni.atelier.brouillons.v1'
DUREE = 30 * 86400


def version_compte(user):
    return salted_hmac(SALT, user.get_session_auth_hash(), algorithm='sha256').hexdigest()


@api_view(['POST'])
@permission_classes([IsSuperuser])
def autoriser(request):
    empreinte = request.data.get('empreinte')
    if not isinstance(empreinte, str) or not re.fullmatch('[a-f0-9]{64}', empreinte):
        return Response({'detail': 'Relancez la connexion depuis l’atelier.'}, status=400)
    jeton = signing.dumps([request.user.pk, empreinte, version_compte(request.user)], salt=SALT)
    return Response({'autorisation': jeton}, headers={'Cache-Control': 'no-store'})


class SessionAtelier(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Atelier'

    def authenticate(self, request):
        header = get_authorization_header(request)
        if len(header) > 2048 or not header.startswith(b'Atelier '):
            raise AuthenticationFailed('Connectez ce PC à Fidni.')
        try:
            jeton, secret = header[8:].decode('ascii').split('.')
            if not re.fullmatch('[a-f0-9]{64}', secret):
                raise ValueError()
            uid, empreinte, version = signing.loads(jeton, salt=SALT, max_age=DUREE)
            if not constant_time_compare(hashlib.sha256(secret.encode()).hexdigest(), empreinte):
                raise ValueError()
            user = get_user_model().objects.get(pk=uid, is_active=True, is_superuser=True)
            if not constant_time_compare(version, version_compte(user)):
                raise ValueError()
        except (ValueError, signing.BadSignature, get_user_model().DoesNotExist):
            raise AuthenticationFailed('Reconnectez ce PC à Fidni.')
        return user, None


@api_view(['GET'])
@authentication_classes([SessionAtelier])
@permission_classes([IsSuperuser])
def etat(request):
    return Response({'compte': request.user.get_username()}, headers={'Cache-Control': 'no-store'})


@api_view(['POST'])
@authentication_classes([SessionAtelier])
@permission_classes([IsSuperuser])
@parser_classes([MultiPartParser])
def fiche(request, action):
    if action not in ('verifier', 'deposer'):
        return Response(status=404)
    archive = request.FILES.get('fiche')
    if not archive or archive.size > LIMIT:
        return Response({'detail': 'Archive manquante ou supérieure à 64 Mio.'}, status=400)
    try:
        result = traiter_archive(action, archive.read(), request.user)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        return Response({'detail': str(exc)[:3500]}, status=400)
    return Response(result, headers={'Cache-Control': 'no-store'})
