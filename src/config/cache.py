"""Cache fichier partagé par les processus gunicorn, sans le coût du tri à chaque écriture (30/10/2026).

Le FileBasedCache de Django liste TOUT le dossier à chaque `set` (`_cull`) pour savoir s'il dépasse MAX_ENTRIES.
Depuis les limites anti-abus (une écriture par requête d'API), le dossier contenait ~11 000 fichiers, rarement
supprimés (seulement à la relecture d'une clé expirée) : chaque écriture coûtait ~40 ms, sur toutes les requêtes.

Ici le tri n'a lieu qu'une fois toutes les TRI_SECONDES par processus, et il supprime d'abord les fichiers
expirés (ce que Django ne fait jamais de lui-même), puis applique la règle de Django si le dossier reste trop plein.
"""
import time

from django.core.cache.backends.filebased import FileBasedCache

TRI_SECONDES = 300


class CacheFichier(FileBasedCache):
    _prochain_tri = 0.0  # par processus

    def _cull(self):
        maintenant = time.monotonic()
        if maintenant < CacheFichier._prochain_tri:
            return
        CacheFichier._prochain_tri = maintenant + TRI_SECONDES
        self.purger_expires()
        super()._cull()

    def purger_expires(self):
        """Supprime les fichiers expirés ; renvoie leur nombre."""
        n = 0
        for fname in self._list_cache_files():
            try:
                with open(fname, 'rb') as f:
                    n += bool(self._is_expired(f))  # _is_expired supprime le fichier s'il est expiré
            except (FileNotFoundError, OSError):
                continue  # supprimé ou réécrit entre-temps par un autre processus
        return n
