"""Index des questions d'un contenu, en cache : [(chemin, points, notions)] (08/10/2026).

Les statistiques (Ma progression, plan d'un DS, profil) n'ont besoin que de ça, pas de l'énoncé entier.
Avant, chaque visite rechargeait le json_content de tous les contenus travaillés par l'élève (plusieurs
Mo pour un élève actif, autant de transfert depuis RDS). La clé contient la date de modification du
contenu : un contenu modifié est relu, jamais d'index périmé.
"""
from django.core.cache import cache

TIMEOUT = 24 * 3600


def _key(content_id, updated_at):
    return f'qidx:{content_id}:{updated_at.isoformat() if updated_at else "-"}'


def question_index(contents):
    """{id: [(chemin, points, notions)]} pour des contenus (objets avec id et updated_at)."""
    from apps.things.models import Content
    from apps.users.my_stats import _questions
    keys = {c.id: _key(c.id, c.updated_at) for c in contents}
    found = cache.get_many(list(keys.values())) if keys else {}
    out, fresh = {}, {}
    for cid, key in keys.items():
        if key in found:
            out[cid] = found[key]
    missing = [cid for cid in keys if cid not in out]
    if missing:
        for cid, structure in Content.objects.filter(id__in=missing).values_list('id', 'json_content'):
            out[cid] = [(path, points, list(skills)) for path, points, skills in _questions(structure)]
            fresh[keys[cid]] = out[cid]
        cache.set_many(fresh, TIMEOUT)
    return out
