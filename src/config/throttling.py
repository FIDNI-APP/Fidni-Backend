"""Limitation du nombre de requêtes sur les routes sensibles (connexion, inscription, e-mails)."""
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class _ClientIPThrottle(SimpleRateThrottle):
    """Compte les requêtes par adresse IP du visiteur.

    La seule entrée publique est le tunnel Cloudflare (le conteneur n'écoute que sur
    127.0.0.1) : l'IP du visiteur arrive dans CF-Connecting-IP. Sans ce header, tout
    le monde partagerait l'IP du tunnel et une seule personne bloquerait tout le site.
    """

    def get_ident(self, request):
        ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
        return ip or super().get_ident(request)

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class ClientErrorThrottle(_ClientIPThrottle):
    """Erreurs d'affichage envoyées par le navigateur (apps/logging/client_errors.py) : ouvert aux visiteurs."""
    scope = 'client_error'


class AuthRateThrottle(_ClientIPThrottle):
    """Connexion, inscription : freine les requêtes en rafale depuis une même adresse.
    Assez large pour une classe entière qui se connecte derrière la même IP de lycée."""
    scope = 'auth'


class LoginAccountThrottle(SimpleRateThrottle):
    """Essais de connexion sur UN compte, d'où qu'ils viennent : c'est ce qui arrête
    vraiment la recherche d'un mot de passe, même répartie sur plusieurs adresses."""
    scope = 'login_account'

    def get_cache_key(self, request, view):
        identifier = str(request.data.get('identifier') or request.data.get('username') or '').strip().lower()
        if not identifier:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': identifier}


class TokenRefreshThrottle(_ClientIPThrottle):
    scope = 'token_refresh'


class EmailRateThrottle(_ClientIPThrottle):
    """Routes qui envoient un e-mail : empêche de s'en servir pour spammer une adresse."""
    scope = 'auth_email'


class PdfParseThrottle(UserRateThrottle):
    """Analyse de PDF : chaque appel lit un fichier jusqu'à 25 Mo côté serveur."""
    scope = 'pdf_parse'


class ClassroomJoinThrottle(UserRateThrottle):
    """Rejoindre une classe : empêche de deviner les codes d'invitation en boucle."""
    scope = 'classroom_join'


class ContentReportThrottle(UserRateThrottle):
    """Signalements d'erreurs : largement assez pour un élève, pas pour inonder la file."""
    scope = 'content_report'


class ProposedSolutionThrottle(UserRateThrottle):
    """Publication de solutions d'élèves (texte + photos) : freine le spam."""
    scope = 'proposed_solution'
