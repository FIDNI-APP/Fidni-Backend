"""Appel à l'API Anthropic (Claude), sans dépendance : requête HTTP en flux (SSE) avec urllib.

Configuration (fichier d'environnement du serveur, jamais dans le dépôt) :
  ANTHROPIC_API_KEY, ANTHROPIC_WORKSPACE_ID (la clé du compte l'exige), ANTHROPIC_MODEL (claude-opus-5-5).
"""
import json
import logging
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger('django')
URL = 'https://api.anthropic.com/v1/messages'


class IAErreur(Exception):
    """Erreur lisible par l'administrateur (affichée telle quelle dans Pilotage)."""


def configuree():
    return bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))


def _requete(payload):
    headers = {
        'x-api-key': settings.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'accept': 'text/event-stream',
    }
    if getattr(settings, 'ANTHROPIC_WORKSPACE_ID', ''):
        headers['anthropic-workspace-id'] = settings.ANTHROPIC_WORKSPACE_ID
    return urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers, method='POST')


def _lire_flux(resp):
    """Assemble le texte de la réponse (les blocs de réflexion sont ignorés) et l'usage."""
    texte, usage, arret = [], {}, None
    for brut in resp:
        ligne = brut.decode('utf-8', 'replace').strip()
        if not ligne.startswith('data:'):
            continue
        try:
            ev = json.loads(ligne[5:].strip())
        except ValueError:
            continue
        t = ev.get('type')
        if t == 'message_start':
            usage.update(ev.get('message', {}).get('usage') or {})
        elif t == 'content_block_delta' and ev.get('delta', {}).get('type') == 'text_delta':
            texte.append(ev['delta'].get('text', ''))
        elif t == 'message_delta':
            usage.update(ev.get('usage') or {})
            arret = (ev.get('delta') or {}).get('stop_reason') or arret
        elif t == 'error':
            raise IAErreur(f"Erreur de l’IA : {(ev.get('error') or {}).get('message', 'inconnue')}")
    return ''.join(texte), usage, arret


def appeler(system, messages, *, max_tokens=None, reflexion=None):
    """Envoie la conversation et renvoie (texte, usage). Réessaie sur surcharge ; sans réflexion si refusée."""
    if not configuree():
        raise IAErreur('Clé de l’API Anthropic absente : ajouter ANTHROPIC_API_KEY sur le serveur.')
    max_tokens = max_tokens or settings.ANTHROPIC_MAX_TOKENS
    reflexion = settings.ANTHROPIC_THINKING if reflexion is None else reflexion
    # Consigne mise en cache (la même à chaque appel : moins cher, plus rapide).
    payload = {'model': settings.ANTHROPIC_MODEL, 'max_tokens': max_tokens,
               'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
               'messages': messages, 'stream': True}
    if reflexion:
        payload['thinking'] = {'type': 'enabled', 'budget_tokens': min(reflexion, max_tokens - 4000)}
    for essai in range(6):
        try:
            with urllib.request.urlopen(_requete(payload), timeout=900) as resp:
                texte, usage, arret = _lire_flux(resp)
            if arret == 'max_tokens':
                raise IAErreur('Réponse de l’IA tronquée (document trop long) : découper le document et recommencer.')
            return texte, usage
        except urllib.error.HTTPError as exc:
            corps = exc.read().decode('utf-8', 'replace')
            try:
                message = json.loads(corps).get('error', {}).get('message', corps)
            except ValueError:
                message = corps
            if exc.code == 400 and 'thinking' in payload and 'thinking' in message.lower():
                payload.pop('thinking')  # modèle sans réflexion étendue : on continue sans
                continue
            if exc.code == 400 and 'max_tokens' in message and payload['max_tokens'] > 32000:
                payload['max_tokens'] = 32000  # plafond du modèle plus bas que prévu
                if 'thinking' in payload:
                    payload['thinking']['budget_tokens'] = min(payload['thinking']['budget_tokens'], 16000)
                continue
            if exc.code in (429, 500, 502, 503, 529) and essai < 3:
                time.sleep(15 * (essai + 1))
                continue
            if 'credit balance' in message.lower():
                raise IAErreur('Crédit Anthropic épuisé : recharger le compte (console.anthropic.com › Plans & Billing).')
            raise IAErreur(f'Erreur de l’API Anthropic ({exc.code}) : {message[:300]}')
        except urllib.error.URLError as exc:
            if essai < 3:
                time.sleep(10)
                continue
            raise IAErreur(f'API Anthropic injoignable : {exc.reason}')
    raise IAErreur('API Anthropic indisponible, réessayer plus tard.')
