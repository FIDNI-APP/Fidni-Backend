import re
import unicodedata

from rest_framework import status, views
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from apps.authentication.jwt_revocation import blacklist_refresh, revoke_all_sessions
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from django.contrib.auth import logout
from django.contrib.auth.models import User, update_last_login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from config.throttling import AuthRateThrottle, EmailRateThrottle, LoginAccountThrottle, TokenRefreshThrottle
from apps.users.serializers import (
    UserSerializer,
)
from . import google
from .emails import send_password_reset_email, send_verification_email
from .tokens import read_verification_token
from apps.users.identity import clean_person_name
from apps.users.legal import accept_terms
from apps.users.models import GoogleAccount


import logging
logger = logging.getLogger('django')

USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,30}$')


def _find_user(identifier: str):
    """Utilisateur désigné par son e-mail (insensible à la casse) ou son nom d'utilisateur."""
    identifier = identifier.strip()
    qs = User.objects.filter(email__iexact=identifier) if '@' in identifier else User.objects.filter(username=identifier)
    return qs.order_by('id').first()


def _password_errors(password: str, user=None) -> list:
    try:
        validate_password(password, user=user)
        return []
    except ValidationError as e:
        return list(e.messages)


#----------------------------LOGIN-------------------------------
class LoginView(views.APIView):
    """Connexion par e-mail OU nom d'utilisateur ; renvoie les jetons JWT et le profil."""
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip authentication
    throttle_classes = [AuthRateThrottle, LoginAccountThrottle]

    def post(self, request):
        identifier = (request.data.get('identifier') or '').strip()
        password = request.data.get('password') or ''

        if not identifier or not password:
            return Response(
                {'error': 'Indique ton e-mail (ou nom d’utilisateur) et ton mot de passe.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = _find_user(identifier)
        # Le mot de passe est vérifié AVANT de parler de l'état du compte : sinon cette
        # route dirait à n'importe qui quelles adresses sont inscrites.
        if user is None or not user.check_password(password):
            return Response(
                {'error': 'Identifiants incorrects.', 'code': 'invalid_credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            profile = getattr(user, 'profile', None)
            if profile is not None and not profile.email_verified:
                return Response(
                    {'error': 'Confirme ton adresse e-mail pour te connecter.', 'code': 'email_not_verified',
                     'email': user.email},
                    status=status.HTTP_403_FORBIDDEN
                )
            return Response(
                {'error': 'Ce compte est désactivé.', 'code': 'account_disabled'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(_session(user, request))


def _session(user, request):
    """Jetons JWT + profil complet : réponse d'une connexion réussie (mot de passe ou Google)."""
    refresh = RefreshToken.for_user(user)
    update_last_login(None, user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user, context={'request': request, 'is_owner': True}).data,
    }


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Ancienne route /api/token/ (nom d'utilisateur uniquement), gardée pour compatibilité."""
    throttle_classes = [AuthRateThrottle, LoginAccountThrottle]


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [TokenRefreshThrottle]


#----------------------------GOOGLE-------------------------------

def _username_from_email(email: str) -> str:
    """Pseudo libre tiré de l'adresse (« Amine.B+x@gmail.com » → « amine_b », puis « amine_b2 »…),
    conforme à USERNAME_RE. Le point devient « _ » : dans une URL de profil (/profile/amine.b), il
    passe pour une extension de fichier auprès de certains serveurs."""
    local = email.split('@')[0].split('+')[0]
    base = unicodedata.normalize('NFKD', local).encode('ascii', 'ignore').decode().lower().replace('.', '_')
    base = re.sub(r'[^a-z0-9_-]+', '', base)
    base = re.sub(r'_{2,}', '_', base).strip('_-')[:24].strip('_-')  # place pour un suffixe numérique
    if len(base) < 3:
        base = f'{base}_eleve' if base else 'eleve'
    taken = {u.lower() for u in User.objects.filter(username__istartswith=base).values_list('username', flat=True)}
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f'{base}{n}'
    return candidate


def _create_google_user(info):
    """Nouveau compte sans mot de passe, adresse confirmée par Google, conditions acceptées.
    Renvoie (user, lien, créé). Double envoi du même jeton : la seconde requête retrouve le compte
    créé par la première (sub unique) au lieu d'en créer un deuxième."""
    for attempt in range(3):
        try:
            with transaction.atomic():
                first, _ = clean_person_name(info['given_name'], 'Prénom')
                last, _ = clean_person_name(info['family_name'], 'Nom')
                user = User(username=_username_from_email(info['email']), email=info['email'],
                            first_name=first or '', last_name=last or '')
                # Connexion par Google ; « Mot de passe oublié » permet d'en définir un plus tard.
                user.set_unusable_password()
                user.save()
                profile = user.profile
                profile.email_verified = True
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=['email_verified', 'email_verified_at'])
                accept_terms(profile)
                link = GoogleAccount.objects.create(user=user, sub=info['sub'], email=info['email'])
            return user, link, True
        except IntegrityError:
            link = GoogleAccount.objects.select_related('user').filter(sub=info['sub']).first()
            if link is not None:
                return link.user, link, False
            if attempt == 2:  # pseudo pris entre-temps, trois fois de suite
                raise


class GoogleLoginView(views.APIView):
    """Connexion avec Google : POST {credential, accept_terms?, age_ok?}.

    Compte retrouvé par l'identifiant Google (sub), sinon par l'adresse e-mail (le plus ancien, comme
    _find_user) et le lien est créé ; sinon nouveau compte, après acceptation des conditions comme
    l'inscription classique. Google a confirmé l'adresse : pas d'e-mail de confirmation. Un compte
    jamais confirmé est activé après acceptation des conditions, sans son mot de passe d'inscription.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        try:
            info = google.verify_google_credential(data.get('credential'))
        except google.GoogleUnavailable as e:
            logger.warning('Connexion Google : clés publiques de Google injoignables (%s)', e)
            return Response({'error': 'Google ne répond pas pour le moment. Réessaie dans un instant.',
                             'code': 'google_unavailable'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except google.GoogleTokenError as e:
            logger.info('Connexion Google refusée : %s', e)
            return Response({'error': 'La connexion avec Google a échoué. Réessaie.', 'code': 'invalid_token'},
                            status=status.HTTP_400_BAD_REQUEST)

        created = False
        link = GoogleAccount.objects.select_related('user').filter(sub=info['sub']).first()
        user = link.user if link else User.objects.filter(email__iexact=info['email']).order_by('id').first()

        # Compte en attente de confirmation d'e-mail (inscription jamais confirmée) : n'importe qui a pu
        # le créer avec cette adresse. Google prouve maintenant qui la possède : cette personne accepte
        # elle-même les conditions, et le mot de passe choisi à l'inscription ne sert plus (sinon son
        # auteur entrerait dans le compte qu'elle va utiliser).
        profile = getattr(user, 'profile', None) if user is not None else None
        pending = (user is not None and not user.is_active and profile is not None and not profile.email_verified
                   and (user.email or '').lower() == info['email'])
        if user is not None and not user.is_active and not pending:
            return Response({'error': 'Ce compte est désactivé.', 'code': 'account_disabled'},
                            status=status.HTTP_403_FORBIDDEN)

        if user is None or pending:
            # RGPD : mêmes cases que l'inscription (non pré-cochées), exigées ici aussi.
            if data.get('accept_terms') is not True or data.get('age_ok') is not True:
                name = info['name'] or f"{info['given_name']} {info['family_name']}".strip()
                return Response({'error': 'Accepte les conditions d’utilisation pour créer ton compte.',
                                 'code': 'consent_required', 'email': info['email'], 'name': name},
                                status=status.HTTP_400_BAD_REQUEST)

        if user is None:
            user, link, created = _create_google_user(info)
        elif pending:
            with transaction.atomic():
                user.is_active = True
                user.set_unusable_password()  # « Mot de passe oublié » ou les réglages pour en définir un
                user.save(update_fields=['is_active', 'password'])
                profile.email_verified = True
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=['email_verified', 'email_verified_at'])
                accept_terms(profile)

        if link is None:
            link, _ = GoogleAccount.objects.get_or_create(sub=info['sub'],
                                                          defaults={'user': user, 'email': info['email']})
        link.email = info['email']
        link.last_used_at = timezone.now()
        link.save(update_fields=['email', 'last_used_at'])
        return Response({**_session(user, request), 'created': created})


#----------------------------REGISTER-------------------------------

class RegisterView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip authentication
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        if not all([username, email, password]):
            return Response(
                {'error': 'Remplis tous les champs.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not USERNAME_RE.match(username):
            return Response(
                {'error': 'Le nom d’utilisateur doit faire 3 à 30 caractères : lettres, chiffres, « . », « _ » ou « - ».',
                 'field': 'username'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response({'error': 'Adresse e-mail invalide.', 'field': 'email'},
                            status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username__iexact=username).exists():
            return Response(
                {'error': 'Ce nom d’utilisateur est déjà pris.', 'field': 'username'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {'error': 'Un compte existe déjà avec cette adresse e-mail.', 'field': 'email'},
                status=status.HTTP_400_BAD_REQUEST
            )

        errors = _password_errors(password, User(username=username, email=email))
        if errors:
            return Response({'error': ' '.join(errors), 'field': 'password'},
                            status=status.HTTP_400_BAD_REQUEST)

        # RGPD : acceptation explicite (case non pré-cochée) des CGU et de la politique de
        # confidentialité ; moins de 15 ans : accord d'un parent (loi Informatique et
        # Libertés, art. 45). Ces deux cases sont exigées ici, pas seulement dans le front.
        if request.data.get('accept_terms') is not True:
            return Response({'error': 'Tu dois accepter les conditions d’utilisation et la politique de confidentialité.',
                             'field': 'accept_terms'}, status=status.HTTP_400_BAD_REQUEST)
        if request.data.get('age_ok') is not True:
            return Response({'error': 'Si tu as moins de 15 ans, un parent doit donner son accord.',
                             'field': 'age_ok'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        # New accounts are inactive until the email is confirmed. This blocks
        # both /api/token/ (SimpleJWT) and the custom login above.
        user.is_active = False
        user.save(update_fields=['is_active'])

        profile = getattr(user, 'profile', None)
        if profile is not None:
            profile.email_verified = False
            profile.save(update_fields=['email_verified'])
            accept_terms(profile)

        # The account exists either way, so this stays a 201 — telling the
        # client it failed outright would invite a retry that then collides
        # with the username it just took. The detail says which happened, so
        # the UI can point at "renvoyer l'e-mail" instead of promising a
        # message that was never sent.
        try:
            send_verification_email(user)
            detail = 'verification_email_sent'
        except Exception:
            logger.exception("Failed to send verification email to user %s", user.pk)
            detail = 'verification_email_failed'

        return Response(
            {'detail': detail, 'email': email},
            status=status.HTTP_201_CREATED,
        )


#----------------------------VERIFY EMAIL-------------------------------

class VerifyEmailView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token manquant', 'code': 'token_missing'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            data = read_verification_token(token)
        except signing.SignatureExpired:
            return Response({'error': 'Lien expiré', 'code': 'token_expired'},
                            status=status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            return Response({'error': 'Lien invalide', 'code': 'token_invalid'},
                            status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(id=data.get('uid')).first()
        # Le lien confirme UNE adresse : s'il a été émis pour une autre que l'actuelle, il ne vaut plus.
        if user is None or (user.email or '').lower() != (data.get('email') or '').lower():
            return Response({'error': 'Lien invalide', 'code': 'token_invalid'},
                            status=status.HTTP_400_BAD_REQUEST)

        profile = getattr(user, 'profile', None)
        # Première confirmation : l'élève est connecté directement (il vient de créer son compte et
        # enchaîne sur la complétude du profil). Un lien déjà utilisé ne connecte plus personne.
        first_time = not user.is_active or (profile is not None and not profile.email_verified)

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        if profile is not None and not profile.email_verified:
            profile.email_verified = True
            profile.email_verified_at = timezone.now()
            profile.save(update_fields=['email_verified', 'email_verified_at'])

        if not first_time:
            return Response({'detail': 'already_verified'}, status=status.HTTP_200_OK)

        refresh = RefreshToken.for_user(user)
        update_last_login(None, user)
        return Response({
            'detail': 'email_verified',
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user, context={'request': request, 'is_owner': True}).data,
        }, status=status.HTTP_200_OK)


#----------------------------RESEND VERIFICATION-------------------------------

class ResendVerificationView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [EmailRateThrottle]

    def post(self, request):
        email = (request.data.get('email') or '').strip()
        # Always return a generic success — never reveal whether an email exists.
        if email:
            try:
                user = _find_user(email)
                profile = getattr(user, 'profile', None) if user else None
                if user and (profile is None or not profile.email_verified):
                    send_verification_email(user)
            except Exception:
                logger.exception("Failed to resend verification email")

        return Response({'detail': 'verification_email_sent'}, status=status.HTTP_200_OK)


#----------------------------PASSWORD RESET-------------------------------

class PasswordResetRequestView(views.APIView):
    """« Mot de passe oublié » : envoie un lien à usage unique. Réponse identique que
    l'adresse existe ou non, pour ne pas révéler qui est inscrit. Un compte créé avec Google
    (sans mot de passe) s'en sert pour en définir un."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [EmailRateThrottle]

    def post(self, request):
        identifier = (request.data.get('email') or '').strip()
        if identifier:
            try:
                user = _find_user(identifier)
                if user and user.email and (user.has_usable_password() or user.google_accounts.exists()):
                    send_password_reset_email(user)
            except Exception:
                logger.exception("Failed to send password reset email")
        return Response({'detail': 'password_reset_sent'}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        uid = request.data.get('uid') or ''
        token = request.data.get('token') or ''
        password = request.data.get('password') or ''

        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response({'error': 'Ce lien n’est plus valable. Refais une demande.', 'code': 'token_invalid'},
                            status=status.HTTP_400_BAD_REQUEST)

        errors = _password_errors(password, user)
        if errors:
            return Response({'error': ' '.join(errors), 'field': 'password'},
                            status=status.HTTP_400_BAD_REQUEST)

        user.set_password(password)
        # Recevoir le lien prouve l'accès à la boîte mail : le compte est donc confirmé.
        fields = ['password']
        if not user.is_active:
            profile = getattr(user, 'profile', None)
            if profile is not None and not profile.email_verified:
                user.is_active = True
                fields.append('is_active')
                profile.email_verified = True
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=['email_verified', 'email_verified_at'])
        user.save(update_fields=fields)
        # Quelqu'un connaissait peut-être l'ancien mot de passe : on ferme toutes les sessions.
        revoke_all_sessions(user)
        return Response({'detail': 'password_reset_done'}, status=status.HTTP_200_OK)


#----------------------------LOGOUT-------------------------------

class LogoutView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip authentication

    def post(self, request):
        # Le jeton de rafraîchissement volé ou oublié sur un ordinateur partagé ne sert plus.
        blacklist_refresh(request.data.get('refresh'))
        logout(request)
        return Response(status=status.HTTP_200_OK)
