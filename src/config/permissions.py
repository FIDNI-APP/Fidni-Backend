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


def is_admin(user) -> bool:
    """Équipe : superutilisateur ou staff."""
    return _is_authenticated(user) and bool(user.is_superuser or user.is_staff)


def is_teacher_or_admin(user) -> bool:
    """Enseignant déclaré (profil « enseignant ») ou membre de l'équipe."""
    if is_admin(user):
        return True
    profile = getattr(user, 'profile', None) if _is_authenticated(user) else None
    return getattr(profile, 'user_type', None) == 'teacher'


class CanCreateContent(BasePermission):
    """Création d'un exercice, d'une leçon ou d'un examen : réservée à l'équipe pour l'instant (12/10/2026).
    Les autres actions (lire, voter, modifier son propre contenu…) passent aux permissions suivantes."""
    message = 'La création de contenu est réservée à l’équipe pour l’instant.'

    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'create':
            return True
        return is_admin(request.user)


class IsTeacherOrAdmin(BasePermission):
    """« Mes documents » : enseignants (déclarés) et équipe seulement, pour l'instant (12/10/2026)."""
    message = 'Réservé aux enseignants pour l’instant.'

    def has_permission(self, request, view):
        return is_teacher_or_admin(request.user)


class IsAdminMember(BasePermission):
    """Équipe seulement (superutilisateur ou staff)."""

    def has_permission(self, request, view):
        return is_admin(request.user)
