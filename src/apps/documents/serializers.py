import html as html_lib
import re

from rest_framework import serializers

from .models import Document

ENTETE_TEXTES = ('type', 'etablissement', 'professeur', 'classe', 'annee', 'duree', 'consignes')
# Un document fait au plus ~2 Mo de HTML (les images sont des liens, jamais du base64).
MAX_HTML = 2_000_000
_TAGS = re.compile(r'<[^>]+>')
_SPACES = re.compile(r'\s+')


def excerpt(html, size=160):
    text = _SPACES.sub(' ', html_lib.unescape(_TAGS.sub(' ', html or ''))).strip()
    return text[:size] + ('…' if len(text) > size else '')


class DocumentListSerializer(serializers.ModelSerializer):
    """Liste « Mes documents » : sans le HTML (un aperçu du texte suffit)."""
    excerpt = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ['id', 'title', 'excerpt', 'orientation', 'created_at', 'updated_at']

    def get_excerpt(self, obj):
        return excerpt(obj.html)


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ['id', 'title', 'html', 'orientation', 'marges', 'entete', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {'title': {'allow_blank': True, 'required': False}, 'html': {'required': False}, 'entete': {'required': False}}

    def validate_title(self, value):
        return (value or '').strip()[:200] or 'Document sans titre'

    def validate_entete(self, value):
        """Champs connus seulement, textes courts (l'en-tête est imprimé tel quel)."""
        if not isinstance(value, dict):
            raise serializers.ValidationError('En-tête invalide.')
        out = {}
        for key in ENTETE_TEXTES:
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                out[key] = v.strip()[:300 if key == 'consignes' else 120]
        for key in ('actif', 'nom_prenom'):
            if key in value:
                out[key] = bool(value[key])
        return out

    def validate_html(self, value):
        if len(value or '') > MAX_HTML:
            raise serializers.ValidationError('Document trop volumineux (2 Mo de texte au plus). Les images doivent être envoyées, pas collées.')
        if re.search(r'src="data:', value or ''):
            raise serializers.ValidationError('Image collée en base64 : elle doit être envoyée avec le bouton Image.')
        return value or ''
