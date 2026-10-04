"""Correction « à vérifier » : un administrateur (M. Haddar, Natsu) la marque vérifiée depuis le site
après relecture, ou remet le bandeau. Le marquage vit dans json_content['a_verifier'] (posé à l'import)."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.things.models import Content


class IsModerator(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or u.is_staff))


@api_view(['POST'])
@permission_classes([IsModerator])
def set_verification(request, content_id):
    """POST {"verifie": true} retire le bandeau ; {"verifie": false} le remet."""
    content = get_object_or_404(Content, pk=content_id)
    verifie = request.data.get('verifie')
    if not isinstance(verifie, bool):
        return Response({'verifie': 'true ou false'}, status=status.HTTP_400_BAD_REQUEST)
    js = dict(content.json_content or {})
    if verifie:
        js.pop('a_verifier', None)
    else:
        js['a_verifier'] = True
    # update() : ni updated_at ni signaux (pas de ré-indexation pour un simple bandeau).
    Content.objects.filter(pk=content.pk).update(json_content=js)
    return Response({'id': content.pk, 'a_verifier': not verifie})
