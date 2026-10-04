"""Permissions partagées entre les apps."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


def _is_authenticated(user) -> bool:
    # UNAUTHENTICATED_USER = None : un visiteur anonyme a request.user = None.
    return bool(user and getattr(user, 'is_authenticated', False))


class IsAuthorOrStaffOrReadOnly(BasePermission):
    """Lecture pour tous, création pour tout utilisateur connecté ;
    modification et suppression réservées à l'auteur de l'objet (ou au staff).

    Seules les actions listées dans `view.author_only_actions` sont protégées :
    les autres actions d'un objet (voter, commenter, enregistrer…) restent ouvertes
    à tout utilisateur connecté.
    """
    default_author_only_actions = ('update', 'partial_update', 'destroy')

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or _is_authenticated(request.user)

    def has_object_permission(self, request, view, obj):
        guarded = getattr(view, 'author_only_actions', self.default_author_only_actions)
        if getattr(view, 'action', None) not in guarded:
            return True
        user = request.user
        return _is_authenticated(user) and (user.is_staff or getattr(obj, 'author_id', None) == user.id)
