"""Nom montré pour un membre (Natsu, 13/11/2026 : « plutôt le nom + prénom que le nom d'utilisateur »).

Un membre CONNECTÉ voit le prénom et le nom des autres, partout où un membre est affiché (profil, auteur d'un
contenu ou d'un message, membres, abonnés, notifications). Un visiteur non connecté, et donc Google, ne voit que
le nom d'utilisateur. Le nom d'utilisateur reste l'identifiant des adresses (/profile/<pseudo>) et des @mentions.
Politique de confidentialité modifiée en conséquence (date seule : TERMS_VERSION inchangé, Natsu ne veut pas de réacceptation).
"""
from django.db.models import Q


def nom_complet(user):
    """« Prénom Nom », vide si le compte n'a pas encore rempli son identité."""
    return f'{(user.first_name or "").strip()} {(user.last_name or "").strip()}'.strip()


def voit_les_noms(viewer):
    return bool(viewer is not None and getattr(viewer, 'is_authenticated', False))


def nom_affiche(user, viewer):
    """Nom à afficher pour `user` à la personne `viewer` (None ou anonyme : le nom d'utilisateur)."""
    if user is None:
        return ''
    from .account_deletion import is_deleted_account
    if is_deleted_account(user) or not voit_les_noms(viewer):
        return user.username
    return nom_complet(user) or user.username


def viewer_de(context_ou_request):
    """Le membre qui regarde, depuis un contexte de serializer ou une requête."""
    request = context_ou_request.get('request') if isinstance(context_ou_request, dict) else context_ou_request
    return getattr(request, 'user', None) if request is not None else None


def recherche_nom(q):
    """Filtre « pseudo, prénom, nom ou prénom + nom » pour les recherches de membres connectés."""
    cond = Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
    mots = q.split()
    if len(mots) >= 2:
        prenom, nom = mots[0], ' '.join(mots[1:])
        cond |= (Q(first_name__icontains=prenom) & Q(last_name__icontains=nom)) | \
            (Q(last_name__icontains=prenom) & Q(first_name__icontains=nom))
    return cond
