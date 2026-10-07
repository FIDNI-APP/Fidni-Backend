"""Listes de contenus (cartes) : tout ce qu'il faut précharger pour ContentListSerializer.

La base est sur AWS et l'API sur une autre machine : chaque requête SQL coûte un aller-retour.
Sans ces préchargements, chaque carte déclenchait ~14 requêtes (auteur, votes, commentaires,
enregistrement, statut…) : ~420 requêtes pour les 30 favoris d'un élève.
"""
from django.db.models import Count, Prefetch, Q

from apps.interactions.models import Complete, Save, Vote

from .serializers import ContentListSerializer


def with_list_relations(queryset, user=None):
    """Ajoute à un queryset de Content tout ce que lit ContentListSerializer."""
    queryset = queryset.select_related(
        'author', 'author__profile', 'solution', 'subject'
    ).prefetch_related(
        'chapters', 'class_levels', 'comments', 'votes', 'theorems', 'subfields', 'completed',
        'subject__class_levels',
    )
    if user is not None and getattr(user, 'is_authenticated', False):
        # Enregistrement / statut de l'élève connecté : une requête pour toute la liste.
        queryset = queryset.prefetch_related(
            Prefetch('saved', queryset=Save.objects.filter(user=user), to_attr='my_saves'),
            Prefetch('completed', queryset=Complete.objects.filter(user=user), to_attr='my_completes'),
        )
    likes = Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)
    dislikes = Count('votes', filter=Q(votes__value=Vote.DOWN), distinct=True)
    return queryset.annotate(
        vote_count_annotation=likes - dislikes,
        like_count_annotation=likes,
        dislike_count_annotation=dislikes,
    )


def in_order(queryset, ids):
    """Objets du queryset, dans l'ordre de `ids` (ex. : du plus récemment enregistré au plus ancien)."""
    by_id = {obj.id: obj for obj in queryset.filter(id__in=ids)}
    return [by_id[i] for i in ids if i in by_id]


def serialize_content_list(items, request):
    """Sérialise des cartes de contenus ; la structure JSON est lue sur chaque objet (déjà chargé)."""
    return ContentListSerializer(list(items), many=True, context={'request': request}).data
