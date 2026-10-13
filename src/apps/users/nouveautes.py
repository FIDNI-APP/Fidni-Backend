"""
Fenêtres « Nouveautés » (14/10/2026) : à la connexion, le front présente une nouveauté du site dans une fenêtre
centrée (animations, étapes). Le serveur décide QUI la voit et retient qu'elle a été vue, une fois par compte
(`UserProfile.nouveautes_vues`, pas le localStorage : elle ne revient pas sur un autre appareil).

La liste `a_voir(user)` voyage avec le compte (champ `nouveautes` de `UserSerializer` pour son titulaire : réponse de
connexion, `GET /api/auth/user/`) ; `POST /api/nouveautes/<id>/vue/` la marque vue. Le contenu des fenêtres est côté
front (`components/nouveautes/registre.ts`, même id).
"""
from datetime import date, datetime, timezone as dt_timezone

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# Pour qui : les comptes inscrits AVANT la nouveauté (pour les autres, ce n'en est pas une), jusqu'à une date.
# Les profs ne voient pas celles des élèves (`profs: False`) ; l'équipe, si.
NOUVEAUTES = {
    # Tableau de bord « Ma progression », en ligne le 13/10/2026 vers 21 h UTC.
    'progression-2026-10': {
        'inscrits_avant': datetime(2026, 10, 13, 21, 0, tzinfo=dt_timezone.utc),
        'jusqu_au': date(2026, 12, 31),
        'profs': False,
    },
}


def a_voir(user, maintenant=None):
    """Ids des nouveautés à montrer à ce compte (pas encore vues, encore d'actualité, pour lui)."""
    if not user or not user.is_authenticated:
        return []
    profile = getattr(user, 'profile', None)
    vues = (profile.nouveautes_vues if profile else None) or {}
    prof = bool(profile and profile.user_type == 'teacher')
    maintenant = maintenant or timezone.now()
    jour = timezone.localdate(maintenant)
    return [
        nid for nid, n in NOUVEAUTES.items()
        if nid not in vues
        and jour <= n['jusqu_au']
        and user.date_joined < n['inscrits_avant']
        and (n['profs'] or not prof)
    ]


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def vue(request, nid):
    """La fenêtre a été montrée : elle ne revient plus pour ce compte (idempotent)."""
    if nid not in NOUVEAUTES:
        return Response({'detail': 'Nouveauté inconnue.'}, status=404)
    profile = request.user.profile
    vues = dict(profile.nouveautes_vues or {})
    if nid not in vues:
        vues[nid] = timezone.now().isoformat()
        profile.nouveautes_vues = vues
        profile.save(update_fields=['nouveautes_vues'])
    return Response({'a_voir': a_voir(request.user)})
