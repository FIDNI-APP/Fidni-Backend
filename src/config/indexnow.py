"""IndexNow : prévient Bing (et donc DuckDuckGo, Yahoo, la recherche de ChatGPT…) dès qu'un contenu
est publié ou modifié, pour qu'il soit exploré en quelques heures au lieu de quelques semaines.
Google n'utilise pas IndexNow : pour lui, le plan du site (sitemap.xml) et Search Console.

Protocole : https://www.indexnow.org — la clé est publique par conception ; le fichier
https://fidni.fr/<clé>.txt (frontend/public/) prouve que le site nous appartient.

Envoi groupé et en arrière-plan : les adresses modifiées pendant quelques secondes (import de 25
exercices…) partent en une seule requête, et une panne d'IndexNow n'affecte jamais le site.
Désactivé hors production (INDEXNOW_ENABLED).
"""
import json
import logging
import threading
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)
ENDPOINT = 'https://api.indexnow.org/indexnow'
DELAY = 10  # secondes d'attente pour regrouper les adresses
SECTIONS = {'exercise': 'exercises', 'lesson': 'lessons', 'exam': 'exams'}

_pending = set()
_lock = threading.Lock()
_timer = None


def enabled():
    return bool(getattr(settings, 'INDEXNOW_ENABLED', False) and getattr(settings, 'INDEXNOW_KEY', ''))


def content_url(content):
    section = SECTIONS.get(content.type)
    return f"{settings.FRONTEND_URL.rstrip('/')}/{section}/{content.pk}" if section else None


def payload(urls):
    site = settings.FRONTEND_URL.rstrip('/')
    key = settings.INDEXNOW_KEY
    return {'host': site.split('://', 1)[-1], 'key': key, 'keyLocation': f'{site}/{key}.txt',
            'urlList': sorted(urls)[:10000]}


def submit(urls):
    """Envoi immédiat (utilisé par le regroupement et par la commande indexnow_tout)."""
    urls = [u for u in urls if u]
    if not urls or not enabled():
        return None
    body = json.dumps(payload(urls)).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, method='POST',
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (adresse fixe)
            logger.info('IndexNow : %d adresse(s) envoyée(s), réponse %s', len(urls), resp.status)
            return resp.status
    except Exception as exc:  # une panne d'IndexNow ne doit jamais gêner le site
        logger.warning('IndexNow indisponible (%s) pour %d adresse(s)', exc, len(urls))
        return None


def flush():
    """Envoie tout de suite les adresses en attente (fin d'une commande d'import, par exemple)."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        urls, _timer = set(_pending), None
        _pending.clear()
    if urls:
        submit(urls)


_flush = flush


def queue(url):
    """Ajoute une adresse ; l'envoi part DELAY secondes après la dernière ajoutée."""
    global _timer
    if not url or not enabled():
        return
    with _lock:
        _pending.add(url)
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DELAY, _flush)
        _timer.daemon = True
        _timer.start()
