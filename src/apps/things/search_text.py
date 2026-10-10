"""Texte de recherche d'un contenu (10/10/2026) : ce que l'élève voit, sans accents, sans balises ni LaTeX.

`normalize(« Dérivée d'une fonction »)` → « derivee d'une fonction » : la recherche compare ce texte à la
requête normalisée de la même façon (things/views.py), donc « derivee » trouve « Dérivée ».
"""
import re
import unicodedata

# Clés techniques du JSON de contenu : jamais montrées telles quelles à l'élève. `import` : traçabilité
# d'un contenu importé (importing.py, ia/pipeline.py : cle, source.document/origine, importe_le, ia) ;
# sans elle, « officiel », « pdf » ou « 2026 » trouvaient tous les contenus importés.
SKIP_KEYS = {'id', 'type', 'version', 'meta', 'style', 'class', 'src', 'href', 'url', 'points', 'difficulty',
             'expected_seconds', 'skills', 'a_verifier', 'modifs_ia', 'difficulte_historique', 'credit',
             'import', 'cle', 'origine', 'importe_le'}
_TAG = re.compile(r'<[^>]+>')
_LATEX_CMD = re.compile(r'\\[a-zA-Z]+')
_SPACES = re.compile(r'\s+')


def normalize(text):
    """Minuscules, sans accents, espaces simples."""
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    return _SPACES.sub(' ', text).strip()


def _strings(value, out):
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in SKIP_KEYS:
                _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)


def build_search_text(title, json_content, limit=20000):
    parts = []
    _strings(json_content or {}, parts)
    body = _TAG.sub(' ', ' '.join(parts))
    body = _LATEX_CMD.sub(' ', body).replace('$', ' ').replace('{', ' ').replace('}', ' ')
    return normalize(f'{title or ""} {body}')[:limit]
