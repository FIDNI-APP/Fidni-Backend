"""Révocation des jetons JWT de rafraîchissement (liste noire simplejwt)."""
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken


def blacklist_refresh(raw_token):
    """Révoque un jeton de rafraîchissement ; ignore un jeton absent, invalide ou déjà révoqué."""
    if not raw_token:
        return
    try:
        RefreshToken(str(raw_token)).blacklist()
    except TokenError:
        pass


def revoke_all_sessions(user):
    """Déconnecte l'utilisateur de tous ses appareils (après un changement de mot de passe).

    Les jetons d'accès déjà émis restent valables jusqu'à leur expiration (60 min au plus).
    """
    outstanding = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=t) for t in outstanding], ignore_conflicts=True,
    )


def fresh_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}
