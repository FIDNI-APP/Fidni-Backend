"""Import de contenus rédigés au format « fiche » (fidni-fiche/1) : exercices, examens, leçons.

Une fiche est un fichier JSON rédigé à partir d'un document source (PDF, DOCX), avec ses figures
à côté (dossier `figures/`). Ce module la vérifie, la convertit au format stocké (json_content)
et l'enregistre. Les fonctions de vérification et de conversion n'utilisent pas la base : elles
servent aussi à l'aperçu local ; seules `check_against_db` et `import_fiche` y accèdent.

Documentation du format : contenus/outils/FORMAT.md (hors dépôt) et
backend/src/apps/things/management/commands/importer_contenu.py.
"""
from __future__ import annotations

import difflib
import html as html_lib
import os
import re
import unicodedata
from html.parser import HTMLParser

FORMAT = 'fidni-fiche/1'
EDITORIAL_USERNAME = 'Fidni'  # auteur des contenus importés (compte éditorial, sans mot de passe)
TYPES = {'exercice': 'exercise', 'examen': 'exam', 'lecon': 'lesson'}
DIFFICULTIES = {'facile': 'easy', 'moyen': 'medium', 'difficile': 'hard'}
EXAM_HARD_SHARE, EXAM_EASY_SHARE = 0.35, 0.60  # part des points (examen) : voir exam_difficulty
ORIGINS = {'officiel', 'original', 'autorise'}  # document public officiel / rédigé pour Fidni / avec l'accord de l'auteur
CALLOUTS = {'theorem', 'property', 'definition', 'lemma', 'corollary', 'example', 'remark', 'proof', 'method', 'warning'}

KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{2,80}$')
FIGURE_RE = re.compile(r'^figures/[A-Za-z0-9._-]+\.(png|jpe?g|webp)$')
MAX_FIGURE_BYTES = 5 * 1024 * 1024

# Balises et attributs autorisés dans le HTML d'une fiche (le reste est une erreur, pas un filtrage
# silencieux : on veut savoir qu'un élément du document source a été mal transcrit).
ALLOWED = {
    'p': set(), 'br': set(), 'strong': set(), 'b': set(), 'em': set(), 'i': set(), 'u': set(),
    'sub': set(), 'sup': set(), 'ul': set(), 'ol': {'type', 'start'}, 'li': set(),
    'table': set(), 'thead': set(), 'tbody': set(), 'tr': set(), 'th': {'colspan', 'rowspan'},
    'td': {'colspan', 'rowspan'}, 'img': {'src', 'alt', 'width'}, 'h3': set(), 'h4': set(),
    'blockquote': set(), 'hr': set(), 'code': set(), 'span': set(),
    'div': {'data-callout-type', 'data-callout-title'},
}
VOID = {'br', 'img', 'hr'}

# Mêmes expressions que le rendu du site (frontend/src/components/editor/TipTapRenderer.tsx).
DISPLAY_MATH = re.compile(r'\$\$([\s\S]*?)\$\$')
INLINE_MATH = re.compile(r'\$(?!\$)([^\$\n]+?)\$(?!\$)')
ANY_MATH = re.compile(r'\$\$([\s\S]*?)\$\$|\$(?!\$)([^\$\n]+?)\$(?!\$)')


class FicheError(Exception):
    pass


# --------------------------------------------------------------------------- utilitaires

def slugify(text: str) -> str:
    s = unicodedata.normalize('NFKD', text or '')
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def normalize_text(text: str) -> str:
    """Texte comparable (doublons) : sans balises, accents, espaces ni ponctuation."""
    s = re.sub(r'<[^>]+>', ' ', text or '')
    s = html_lib.unescape(s)
    return slugify(s).replace('-', '')


# Intervalles à la française (« ]-\infty;-3[ ») : KaTeX lit « ] » comme fermant et « - » comme une
# soustraction, d'où « =] − ∞ ». On marque les crochets ouvrants « ] » et fermants « [ ».
# « ] » ouvrant : en début de formule, ou après un espace, =, (, virgule, point-virgule, {, \in, \cup.
_OPEN_BRACKET = re.compile(r'(?:^|(?<=[\s$=(,;{])|(?<=\\in)|(?<=\\cup))\](?=[-\w\\])')
_CLOSE_BRACKET = re.compile(r'(?<!\\right)(?<!\\left)(?<=[\w}])\[(?=[\s$,;.)\\]|$)')


def fix_intervals(tex: str) -> str:
    return _CLOSE_BRACKET.sub(r'\\mathclose{[}', _OPEN_BRACKET.sub(r'\\mathopen{]}', tex))


def _escape_math(tex: str) -> str:
    tex = fix_intervals(tex)
    # Le rendu décode &lt; &gt; &amp; avant KaTeX ; un « < » brut serait lu comme une balise.
    tex = re.sub(r'&(?!(?:lt|gt|amp|quot|#39|nbsp);)', '&amp;', tex)
    return tex.replace('<', '&lt;').replace('>', '&gt;')


def escape_math_in_html(html: str) -> str:
    # Une seule passe : deux passes successives prendraient le « $ » final d'un $$…$$ pour le
    # début d'une formule en ligne et échapperaient le HTML qui suit (« </p><p> » visible).
    return ANY_MATH.sub(lambda m: ('$$' + _escape_math(m.group(1)) + '$$') if m.group(1) is not None
                        else ('$' + _escape_math(m.group(2)) + '$'), html)


def math_segments(html: str) -> list[tuple[str, bool]]:
    """(latex, affichage) de chaque formule, telles que le site les découpe."""
    out = [(m.group(1), True) for m in DISPLAY_MATH.finditer(html)]
    rest = DISPLAY_MATH.sub(' ', html)
    out += [(m.group(1), False) for m in INLINE_MATH.finditer(rest)]
    return out


class _HtmlChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.images: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED:
            self.problems.append(f'balise <{tag}> non autorisée')
            return
        for name, value in attrs:
            if name not in ALLOWED[tag]:
                self.problems.append(f'attribut {name}="{value}" non autorisé sur <{tag}>')
        a = dict(attrs)
        if tag == 'img':
            src = a.get('src') or ''
            if not FIGURE_RE.match(src):
                self.problems.append(f'image « {src} » : attendu figures/nom.png|jpg|webp')
            else:
                self.images.append(src)
            if not (a.get('alt') or '').strip():
                self.problems.append(f'image « {src} » sans texte alternatif (alt)')
        if tag == 'div':
            if a.get('data-callout-type') not in CALLOUTS:
                self.problems.append(f'<div> : data-callout-type doit valoir {sorted(CALLOUTS)}')
            if not (a.get('data-callout-title') or '').strip():
                self.problems.append('encadré sans data-callout-title (ex. « Théorème », « Définition »)')
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID or tag not in ALLOWED:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f'</{tag}> ne ferme pas la bonne balise')
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


def check_html(html: str, where: str, errors: list[str], images: set[str]):
    if not isinstance(html, str) or not html.strip():
        errors.append(f'{where} : texte vide')
        return
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', html):
        errors.append(f'{where} : caractère de contrôle invisible (barre oblique mal échappée, ex. « \\f » ou « \\t » ?)')
    checker = _HtmlChecker()
    checker.feed(html)
    checker.close()
    if checker.stack:
        checker.problems.append(f'balises non fermées : {checker.stack}')
    errors.extend(f'{where} : {p}' for p in checker.problems)
    images.update(checker.images)
    # Formules : tout « $ » doit appartenir à une formule reconnue par le site.
    rest = INLINE_MATH.sub(' ', DISPLAY_MATH.sub(' ', html))
    if '$' in rest:
        i = rest.index('$')
        errors.append(f'{where} : « $ » non apparié près de « {rest[max(0, i - 30):i + 30]} »'
                      ' (une formule en ligne ne peut pas contenir de retour à la ligne)')
    text_only = re.sub(r'<[^>]+>', ' ', rest)
    for bad in (r'\(', r'\)', r'\[', r'\]'):
        if bad in text_only:
            errors.append(f'{where} : délimiteur {bad} non géré par le site, utiliser $…$ ou $$…$$')
            break
    for tex, _ in math_segments(html):
        if not tex.strip():
            errors.append(f'{where} : formule vide')
        elif re.search(r'</?[a-zA-Z][^>]*>', tex):
            errors.append(f'{where} : balise HTML à l’intérieur d’une formule : « {tex[:60]} »')


# --------------------------------------------------------------------------- vérification

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(fiche: dict) -> tuple[list[str], list[str], set[str]]:
    """Vérifications sans base de données. Renvoie (erreurs, avertissements, figures utilisées)."""
    errors: list[str] = []
    warnings: list[str] = []
    images: set[str] = set()
    if not isinstance(fiche, dict):
        return ['la fiche doit être un objet JSON'], [], images
    if fiche.get('format') != FORMAT:
        errors.append(f'format : attendu « {FORMAT} »')
    key = fiche.get('cle', '')
    if not KEY_RE.match(str(key)):
        errors.append('cle : minuscules, chiffres et tirets (3 à 81 caractères), ex. « bac-2023-sm-normale »')
    kind = fiche.get('type')
    if kind not in TYPES:
        errors.append(f'type : {sorted(TYPES)}')
    title = (fiche.get('titre') or '').strip()
    if not title or len(title) > 200:
        errors.append('titre : obligatoire, 200 caractères au plus')
    if not fiche.get('niveaux') or not isinstance(fiche.get('niveaux'), list):
        errors.append('niveaux : liste obligatoire, ex. ["2ème Bac SM"]')
    if not isinstance(fiche.get('chapitres', []), list) or not fiche.get('chapitres'):
        errors.append('chapitres : au moins un chapitre')
    if not isinstance(fiche.get('a_verifier', False), bool):
        errors.append('a_verifier : true ou false')
    credit = fiche.get('credit')
    if credit is not None and not (isinstance(credit, str) and 0 < len(credit.strip()) <= 120):
        errors.append('credit : texte de 120 caractères au plus, ex. « M. Haddar, professeur de mathématiques »')
    src = fiche.get('source') or {}
    if not src.get('document'):
        errors.append('source.document : nom du document d’origine obligatoire (traçabilité)')
    if src.get('origine') not in ORIGINS:
        errors.append(f'source.origine : {sorted(ORIGINS)} (droits de publication)')

    if kind in ('exercice', 'examen'):
        if fiche.get('difficulte') not in DIFFICULTIES:
            errors.append(f'difficulte : {sorted(DIFFICULTIES)}')
        _validate_blocks(fiche.get('blocs'), kind, errors, warnings, images)
        if fiche.get('sections'):
            errors.append('sections : réservé aux leçons (utiliser blocs)')
    elif kind == 'lecon':
        _validate_sections(fiche.get('sections'), errors, images)
        if fiche.get('blocs'):
            errors.append('blocs : réservé aux exercices et examens (utiliser sections)')

    if kind == 'examen':
        ex = fiche.get('examen') or {}
        if not isinstance(ex.get('national'), bool):
            errors.append('examen.national : true ou false')
        if ex.get('national') and not (isinstance(ex.get('annee'), int) and 1990 <= ex['annee'] <= 2100):
            errors.append('examen.annee : année de la session (examen national)')
        if ex.get('duree_minutes') is not None and not (isinstance(ex['duree_minutes'], int) and ex['duree_minutes'] > 0):
            errors.append('examen.duree_minutes : entier positif')
        if isinstance(fiche.get('blocs'), list):
            derived = exam_difficulty(fiche)
            if derived is None:
                warnings.append('difficulte : à donner sur chaque question d’un examen '
                                '(sinon le label de la fiche est gardé)')
            elif derived != DIFFICULTIES.get(fiche.get('difficulte')):
                label = next(k for k, v in DIFFICULTIES.items() if v == derived)
                warnings.append(f'difficulté de l’examen : « {label} » d’après ses questions '
                                f'(fiche : « {fiche.get("difficulte")} »)')
    return errors, warnings, images


def exam_difficulty(fiche: dict) -> str | None:
    """Label d'un examen tiré de ses questions finales, pondérées par les points : au moins 35 % des points en
    « difficile » → hard ; au moins 60 % en « facile » → easy ; sinon medium. Un seul label d'auteur classait
    les sujets de Bac en « moyen ». None si une question n'a pas de difficulté (le label de la fiche reste)."""
    finals = []
    for b in fiche.get('blocs') or []:
        if isinstance(b, dict) and b.get('type') == 'question':
            finals += [q for q in (b.get('sous_questions') or [b]) if isinstance(q, dict)]
    if not finals or any(q.get('difficulte') not in DIFFICULTIES for q in finals):
        return None
    points = [q['points'] if _num(q.get('points')) and q['points'] > 0 else None for q in finals]
    weights = points if all(points) else [1] * len(finals)  # barème incomplet : questions à égalité
    total = sum(weights)

    def share(level):
        return sum(w for q, w in zip(finals, weights) if q['difficulte'] == level) / total

    if share('difficile') >= EXAM_HARD_SHARE:
        return 'hard'
    if share('facile') >= EXAM_EASY_SHARE:
        return 'easy'
    return 'medium'


def _question_points(q: dict) -> float:
    subs = q.get('sous_questions') or []
    sub_total = sum(s.get('points') or 0 for s in subs if _num(s.get('points')))
    return sub_total if sub_total > 0 else (q.get('points') or 0)


def _validate_blocks(blocks, kind, errors, warnings, images):
    if not isinstance(blocks, list) or not blocks:
        errors.append('blocs : liste obligatoire')
        return
    n_questions = 0
    missing_solutions: list[str] = []
    section = None  # (nom, barème annoncé, total calculé)
    sections: list[list] = []
    qn = 0
    for i, b in enumerate(blocks, 1):
        t = b.get('type') if isinstance(b, dict) else None
        where = f'bloc {i}'
        if t == 'partie':
            where = f'bloc {i} (partie)'
            titre = (b.get('titre') or '').strip()
            if not titre:
                errors.append(f'{where} : titre obligatoire, ex. « Exercice 1 »')
            if b.get('points') is not None and not (_num(b['points']) and b['points'] > 0):
                errors.append(f'{where} : points positifs')
            section = [titre, b.get('points'), 0]
            sections.append(section)
            qn = 0
            continue
        if t == 'contexte':
            check_html(b.get('html'), where + ' (contexte)', errors, images)
            continue
        if t != 'question':
            errors.append(f'{where} : type « partie », « contexte » ou « question »')
            continue
        n_questions += 1
        qn += 1
        label = f'{section[0] + " " if section else ""}Q{qn}'
        where = f'bloc {i} ({label})'
        subs = b.get('sous_questions') or []
        # « 1) a- … b- … » : une question peut n'avoir pour texte que ses sous-questions.
        if not (subs and not (b.get('html') or '').strip()):
            check_html(b.get('html'), where, errors, images)
        if b.get('points') is not None and not (_num(b['points']) and b['points'] > 0):
            errors.append(f'{where} : points positifs')
        if subs:
            if b.get('solution'):
                errors.append(f'{where} : avec des sous-questions, les solutions vont dans chaque sous-question')
            sub_total = 0
            for j, s in enumerate(subs, 1):
                sw = f'{where}.{j}'
                check_html(s.get('html'), sw, errors, images)
                if s.get('points') is not None and not (_num(s['points']) and s['points'] > 0):
                    errors.append(f'{sw} : points positifs')
                sub_total += s.get('points') or 0
                if s.get('solution'):
                    check_html(s['solution'], sw + ' (solution)', errors, images)
                else:
                    missing_solutions.append(f'{label}.{j}')
                _validate_meta(s, sw, errors)
            if _num(b.get('points')) and sub_total and abs(b['points'] - sub_total) > 1e-9:
                errors.append(f'{where} : {b["points"]} pts annoncés mais sous-questions = {sub_total}')
        else:
            if b.get('solution'):
                check_html(b['solution'], where + ' (solution)', errors, images)
            else:
                missing_solutions.append(label)
            _validate_meta(b, where, errors)
        if section is not None:
            section[2] += _question_points(b)
    if n_questions == 0:
        errors.append('blocs : aucune question')
    for titre, announced, computed in sections:
        if _num(announced) and abs(announced - computed) > 1e-9:
            errors.append(f'partie « {titre} » : barème {announced} pts mais questions = {computed:g} pts')
    if missing_solutions:
        warnings.append(f'questions sans solution : {", ".join(missing_solutions)}')
    total = sum(_question_points(b) for b in blocks if isinstance(b, dict) and b.get('type') == 'question')
    if kind == 'examen' and total and abs(total - 20) > 1e-9:
        warnings.append(f'total de l’examen : {total:g} pts (20 attendus pour un examen noté sur 20)')


def _validate_meta(q, where, errors):
    notions = q.get('notions', [])
    if not isinstance(notions, list) or any(not isinstance(x, str) or not x.strip() for x in notions):
        errors.append(f'{where} : notions = liste de textes')
    else:
        # Référentiel fermé (apps/caracteristics/notions.py) : même notion = même identifiant partout.
        from apps.caracteristics.notions import NOTION_INDEX, closest_notions
        for n in notions:
            if slugify(n) not in NOTION_INDEX:
                close = closest_notions(n)
                errors.append(f'{where} : notion inconnue « {n} »'
                              + (f' (proche : {", ".join(close)})' if close else
                                 ' — à ajouter dans backend/src/apps/caracteristics/notions.py'))
    if q.get('difficulte') is not None and q['difficulte'] not in DIFFICULTIES:
        errors.append(f'{where} : difficulte {sorted(DIFFICULTIES)}')
    if q.get('duree_secondes') is not None and not (isinstance(q['duree_secondes'], int) and q['duree_secondes'] > 0):
        errors.append(f'{where} : duree_secondes entier positif')
    if q.get('indice') is not None:
        check_html(q['indice'], where + ' (indice)', errors, set())


def _validate_sections(sections, errors, images):
    if not isinstance(sections, list) or not sections:
        errors.append('sections : liste obligatoire')
        return
    for i, s in enumerate(sections, 1):
        where = f'section {i}'
        if not (s.get('titre') or '').strip():
            errors.append(f'{where} : titre obligatoire')
        check_html(s.get('html'), where, errors, images)
        for j, ss in enumerate(s.get('sous_sections') or [], 1):
            if not (ss.get('titre') or '').strip():
                errors.append(f'{where}.{j} : titre obligatoire')
            check_html(ss.get('html'), f'{where}.{j}', errors, images)


def check_figures(base_dir: str, images: set[str]) -> list[str]:
    errors = []
    for rel in sorted(images):
        path = os.path.join(base_dir, rel)
        if not os.path.isfile(path):
            errors.append(f'figure introuvable : {rel}')
        elif os.path.getsize(path) > MAX_FIGURE_BYTES:
            errors.append(f'figure trop lourde (> 5 Mo) : {rel}')
    return errors


# --------------------------------------------------------------------------- conversion

def _block(html: str, src_map: dict) -> dict:
    for rel, url in src_map.items():
        html = html.replace(f'src="{rel}"', f'src="{url}"')
    return {'type': 'text', 'html': escape_math_in_html(html)}


def _meta(q: dict) -> dict:
    meta = {}
    if q.get('notions'):
        meta['skills'] = [slugify(x) for x in q['notions']]
    if q.get('difficulte'):
        meta['difficulty'] = DIFFICULTIES[q['difficulte']]
    if q.get('duree_secondes'):
        meta['expected_seconds'] = q['duree_secondes']
    if q.get('erreurs_frequentes'):
        meta['common_mistakes'] = list(q['erreurs_frequentes'])
    if q.get('indice'):
        meta['hint'] = q['indice']
    return meta


def to_structure(fiche: dict, src_map: dict | None = None) -> dict:
    """json_content à stocker. Identifiants stables (clé + position) : un ré-import d'une fiche
    corrigée garde la progression des élèves tant que l'ordre des questions ne change pas."""
    src_map = src_map or {}
    key = fiche['cle']
    if fiche['type'] == 'lecon':
        sections = []
        for i, s in enumerate(fiche['sections'], 1):
            sections.append({
                'id': f'{key}-s{i}', 'title': s['titre'], 'content': _block(s['html'], src_map),
                'subSections': [
                    {'id': f'{key}-s{i}-{j}', 'title': ss['titre'], 'content': _block(ss['html'], src_map)}
                    for j, ss in enumerate(s.get('sous_sections') or [], 1)
                ],
            })
        return _with_credit({'version': '1.0', 'sections': sections}, fiche)

    blocks = []
    for i, b in enumerate(fiche['blocs'], 1):
        bid = f'{key}-b{i}'
        if b['type'] == 'partie':
            block = {'id': bid, 'type': 'section', 'content': {'type': 'text', 'html': html_lib.escape(b['titre'].strip())}}
            if b.get('points'):
                block['points'] = b['points']
        elif b['type'] == 'contexte':
            block = {'id': bid, 'type': 'context', 'content': _block(b['html'], src_map), 'subQuestions': []}
        else:
            block = {'id': bid, 'type': 'question', 'content': _block(b.get('html') or '', src_map), 'subQuestions': []}
            if b.get('points') or (b.get('sous_questions') and _question_points(b)):
                block['points'] = _question_points(b)
            if b.get('solution'):
                block['solution'] = _block(b['solution'], src_map)
            if _meta(b) and not b.get('sous_questions'):
                block['meta'] = _meta(b)
            for j, s in enumerate(b.get('sous_questions') or [], 1):
                sq = {'id': f'{bid}-{j}', 'content': _block(s['html'], src_map)}
                if s.get('points'):
                    sq['points'] = s['points']
                if s.get('solution'):
                    sq['solution'] = _block(s['solution'], src_map)
                if _meta(s):
                    sq['meta'] = _meta(s)
                block['subQuestions'].append(sq)
        blocks.append(block)
    return _with_credit({'version': '2.1', 'blocks': blocks}, fiche)


def _with_credit(structure: dict, fiche: dict) -> dict:
    # Mention visible de l'auteur du document (« Proposé par … » dans l'en-tête du contenu).
    if (fiche.get('credit') or '').strip():
        structure['credit'] = fiche['credit'].strip()
    # Correction rédigée par Fidni, pas encore relue par M. Haddar : bandeau « en cours de
    # vérification » sur le site (retiré par contenus/outils/valider.sh après son feu vert).
    if fiche.get('a_verifier'):
        structure['a_verifier'] = True
    return structure


def all_html(structure: dict):
    """Tous les textes HTML d'une structure convertie (pour les vérifications de formules)."""
    for b in structure.get('blocks', []):
        for part in (b.get('content'), b.get('solution')):
            if part:
                yield b['id'], part['html']
        if b.get('meta', {}).get('hint'):
            yield b['id'] + ' (indice)', b['meta']['hint']
        for sq in b.get('subQuestions', []):
            for part in (sq.get('content'), sq.get('solution')):
                if part:
                    yield sq['id'], part['html']
    for s in structure.get('sections', []):
        yield s['id'], s['content']['html']
        for ss in s.get('subSections', []):
            yield ss['id'], ss['content']['html']


# --------------------------------------------------------------------------- base de données

def _match(model_qs, names: list[str], what: str, errors: list[str], **filters):
    found = []
    choices = list(model_qs.filter(**filters).values_list('name', flat=True))
    for name in names:
        exact = [c for c in choices if c.lower() == name.strip().lower()]
        if exact:
            found.append(model_qs.filter(name=exact[0], **filters).first())
        else:
            close = difflib.get_close_matches(name, choices, n=3, cutoff=0.5)
            errors.append(f'{what} inconnu : « {name} »' + (f' (proche : {", ".join(close)})' if close else
                                                          ' — à ajouter dans backend/tests/base_tables.py'))
    return found


def check_against_db(fiche: dict) -> tuple[list[str], list[str], dict]:
    """Taxonomie existante, doublons, contenu à mettre à jour. Renvoie (erreurs, avertissements, résolu)."""
    from apps.caracteristics.models import Chapter, ClassLevel, Subject, Subfield, Theorem
    from apps.things.models import Content

    errors, warnings = [], []
    subject_name = fiche.get('matiere', 'Mathématiques')
    subject = Subject.objects.filter(name__iexact=subject_name).first()
    if not subject:
        errors.append(f'matière inconnue : « {subject_name} »')
    levels = _match(ClassLevel.objects.all(), fiche.get('niveaux', []), 'niveau', errors)
    chapters = _match(Chapter.objects.all(), fiche.get('chapitres', []), 'chapitre', errors,
                      **({'subject': subject} if subject else {}))
    theorems = _match(Theorem.objects.all(), fiche.get('theoremes', []), 'théorème', errors)
    subfields = _match(Subfield.objects.all(), fiche.get('sous_domaines', []), 'sous-domaine', errors)
    # Les sous-domaines se déduisent des chapitres (Limites et continuité → Analyse) : on les
    # ajoute toujours, sinon le filtre « Sous-domaine » du site ne trouve pas le contenu.
    for ch in chapters:
        if ch.subfield_id and ch.subfield_id not in {sf.id for sf in subfields}:
            subfields.append(ch.subfield)
    for ch in chapters:
        linked = set(ch.class_levels.values_list('id', flat=True))
        if levels and not linked & {lv.id for lv in levels}:
            warnings.append(f'le chapitre « {ch.name} » n’est rattaché à aucun des niveaux indiqués')
    chapter_ids = {ch.id for ch in chapters}
    for th in theorems:
        if chapter_ids and not set(th.chapters.values_list('id', flat=True)) & chapter_ids:
            warnings.append(f'le théorème « {th.name} » n’est rattaché à aucun des chapitres indiqués')

    kind = TYPES.get(fiche.get('type'))
    existing = Content.objects.filter(json_content__import__cle=fiche.get('cle')).first()
    if existing and existing.type != kind:
        errors.append(f'la clé « {fiche.get("cle")} » est déjà utilisée par un contenu de type {existing.type}')
    if not fiche.get('doublon_ok'):
        title_key = normalize_text(fiche.get('titre', ''))
        for c in Content.objects.filter(type=kind).exclude(pk=getattr(existing, 'pk', None)).only('id', 'title', 'display_id'):
            if normalize_text(c.title) == title_key:
                errors.append(f'doublon probable : même titre que #{c.display_id} « {c.title} »'
                              ' (changer le titre ou mettre "doublon_ok": true)')
    return errors, warnings, {
        'subject': subject, 'levels': levels, 'chapters': chapters, 'theorems': theorems,
        'subfields': subfields, 'existing': existing,
    }


def editorial_author():
    from django.contrib.auth.models import User
    user, created = User.objects.get_or_create(username=EDITORIAL_USERNAME, defaults={'first_name': 'Fidni'})
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def import_fiche(fiche: dict, base_dir: str, *, api_base: str = 'https://api.fidni.fr', author=None):
    """Crée ou met à jour le contenu (clé identique = mise à jour). Tout ou rien."""
    from django.contrib.contenttypes.models import ContentType
    from django.core.files import File
    from django.db import transaction
    from django.utils import timezone
    from apps.things.models import Content
    from apps.uploads.models import FileAttachment

    errors, _, images = validate(fiche)
    errors += check_figures(base_dir, images)
    db_errors, _, res = check_against_db(fiche)
    errors += db_errors
    if errors:
        raise FicheError('\n'.join(errors))

    author = author or editorial_author()
    kind = TYPES[fiche['type']]
    with transaction.atomic():
        content = res['existing'] or Content(type=kind, author=author)
        created = content.pk is None
        content.title = fiche['titre'].strip()
        content.subject = res['subject']
        content.difficulty = DIFFICULTIES.get(fiche.get('difficulte')) if kind != 'lesson' else None
        if kind == 'exam':
            content.difficulty = exam_difficulty(fiche) or content.difficulty
        ex = fiche.get('examen') or {}
        content.is_national_exam = bool(ex.get('national')) if kind == 'exam' else False
        content.national_year = ex.get('annee') if kind == 'exam' else None
        content.duration_minutes = ex.get('duree_minutes') if kind == 'exam' else None
        content.json_content = content.json_content or {}
        content.save()

        ct = ContentType.objects.get_for_model(Content)
        old_files = list(FileAttachment.objects.filter(content_type=ct, object_id=content.pk))
        src_map = {}
        for rel in sorted(images):
            path = os.path.join(base_dir, rel)
            ext = rel.rsplit('.', 1)[-1].lower()
            with open(path, 'rb') as fh:
                att = FileAttachment(
                    content_type=ct, object_id=content.pk, uploaded_by=content.author,
                    file_name=f'{fiche["cle"]}-{os.path.basename(rel)}', file_size=os.path.getsize(path),
                    mime_type={'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}[ext],
                )
                att.file.save(att.file_name, File(fh), save=False)
                att.save()
            src_map[rel] = f'{api_base.rstrip("/")}/api/files/{att.id}/download/'

        structure = to_structure(fiche, src_map)
        structure['import'] = {
            'cle': fiche['cle'], 'source': fiche.get('source'), 'importe_le': timezone.now().isoformat(),
        }
        content.json_content = structure
        content.save()
        content.class_levels.set(res['levels'])
        content.chapters.set(res['chapters'])
        content.theorems.set(res['theorems'])
        content.subfields.set(res['subfields'])
        for att in old_files:  # figures de la version précédente
            att.file.delete(save=False)
            att.delete()
    return content, created
