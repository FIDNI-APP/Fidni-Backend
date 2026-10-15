"""
Pure functions that operate on a structure dict.
No model imports — fully testable in isolation.

Structure shape:
{
    "version": "2.0",
    "blocks": [
        {"type": "context"|"question"|"section", "id": "...", "content": {"html": "..."}, "points": N,
         "subQuestions": [
             {"id": "...", "points": N, "parts": [{"id": "...", "points": N}]}
         ]}
    ]
}
"""


def get_all_item_paths(structure: dict) -> list[str]:
    paths = []
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        block_id = block.get('id', '')
        if block_id:
            paths.append(block_id)
            for sub in block.get('subQuestions', []):
                sub_id = sub.get('id', '')
                if sub_id:
                    sub_path = f"{block_id}.{sub_id}"
                    paths.append(sub_path)
                    for part in sub.get('parts', []):
                        part_id = part.get('id', '')
                        if part_id:
                            paths.append(f"{sub_path}.{part_id}")
    return paths


def get_total_points(structure: dict) -> int:
    total = 0
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        block_points = block.get('points', 0) or 0
        sub_points = sum(
            (sub.get('points', 0) or 0) + sum(
                (part.get('points', 0) or 0) for part in sub.get('parts', [])
            )
            for sub in block.get('subQuestions', [])
        )
        total += sub_points if sub_points > 0 else block_points
    return total


def get_item_count(structure: dict) -> int:
    return len(get_all_item_paths(structure))


def get_section_count(structure: dict) -> int:
    return sum(
        1 for b in (structure or {}).get('blocks', [])
        if b.get('type') == 'section'
    )



# --------------------------------------------------------------------------- indication (« Méthode »)
# Une solution commence par « <p><strong>Méthode :</strong> l'idée</p> » (règle de rédaction de l'import et de
# l'IA). Ce paragraphe devient l'indication de la question (bouton « Indication » du site, avant la solution) :
# champ `hint` ({'type': 'text', 'html': '<p>l'idée</p>'}) à côté de `solution`. La rédaction ne change pas.
import re as _re

_METHOD = _re.compile(
    r'^\s*<p>\s*<strong>\s*M[ée]thode\s*(?:&nbsp;| |\s)*:?\s*</strong>\s*(?::\s*)?(?P<idee>.*?)</p>\s*',
    _re.IGNORECASE | _re.DOTALL,
)


def split_method(html: str):
    """(« <p>idée</p> », reste) si la solution commence par un paragraphe « Méthode : », sinon (None, html).
    Rien n'est séparé si la méthode est vide ou constitue toute la solution."""
    m = _METHOD.match(html or '')
    if not m or not m.group('idee').strip():
        return None, html
    rest = html[m.end():].strip()
    if not rest:
        return None, html
    # « Méthode : on factorise… » → indication seule : « On factorise… » (majuscule d'une phrase).
    idee = m.group('idee').strip()
    if idee[:1].islower():
        idee = idee[0].upper() + idee[1:]
    return f'<p>{idee}</p>', rest


def _after_label(idee: str) -> str:
    """Après « Méthode : », la phrase reprend en minuscule (« On factorise » → « on factorise »)."""
    return idee[0].lower() + idee[1:] if idee[:1].isupper() and idee[1:2].islower() else idee


def _items(structure):
    for block in (structure or {}).get('blocks', []) or []:
        if isinstance(block, dict):
            yield block
            for sq in block.get('subQuestions') or []:
                if isinstance(sq, dict):
                    yield sq


def move_methods_to_hints(structure: dict) -> int:
    """Sépare la « Méthode » de chaque solution en indication (sur place). Une indication déjà présente est
    gardée telle quelle et la méthode est alors retirée de la solution : jamais d'« Indication » ET de « Méthode »
    à la suite (Natsu, 15/10/2026 : « il faut juste "Indication", le reste c'est la solution »). Renvoie le nombre
    de questions modifiées."""
    n = 0
    for item in _items(structure):
        sol = item.get('solution')
        if not isinstance(sol, dict):
            continue
        hint, rest = split_method(sol.get('html') or '')
        if hint:
            if not item.get('hint'):
                item['hint'] = {'type': 'text', 'html': hint}
            item['solution'] = {**sol, 'html': rest}
            n += 1
    return n


def merge_hints_into_solutions(structure: dict) -> int:
    """Inverse de move_methods_to_hints : remet l'indication en tête de la solution (« Méthode : »)."""
    n = 0
    for item in _items(structure):
        hint, sol = item.get('hint'), item.get('solution')
        if not isinstance(hint, dict) or not isinstance(sol, dict):
            continue
        idee = _re.sub(r'^\s*<p>(.*)</p>\s*$', r'\1', hint.get('html') or '', flags=_re.DOTALL).strip()
        if idee:
            item['solution'] = {**sol, 'html': f'<p><strong>Méthode :</strong> {_after_label(idee)}</p>{sol.get("html") or ""}'}
        item.pop('hint', None)
        n += 1
    return n
