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

from .structure_utils import move_methods_to_hints

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
    # Établissement d'origine (14/10/2026, champ « école » du site) : facultatif, nom ou {"nom", "ville"}.
    ecole = fiche.get('ecole')
    if ecole is not None and not _ecole_valide(ecole):
        errors.append('ecole : nom de l’établissement (texte) ou {"nom": "…", "ville": "…"}, '
                      'ex. {"nom": "Lycée Ibn Sina", "ville": "Rabat"}')
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
    # Théorèmes de la question (13/10/2026, à la place des « notions ») : noms exacts du programme officiel
    # (programme.py, annexe C de l'IA), anciens noms acceptés ; aucun pour une question purement calculatoire.
    if 'notions' in q:
        errors.append(f'{where} : « notions » n’existe plus, mets les théorèmes utilisés dans « theoremes »')
    theoremes = q.get('theoremes', [])
    if not isinstance(theoremes, list) or any(not isinstance(x, str) or not x.strip() for x in theoremes):
        errors.append(f'{where} : theoremes = liste de noms de théorèmes')
    else:
        for nom in _theoremes_inconnus(theoremes):
            close = difflib.get_close_matches(nom, list(theoremes_programme().values()), n=3, cutoff=0.5)
            errors.append(f'{where} : théorème inconnu « {nom} »'
                          + (f' (proche : {", ".join(close)})' if close else ' — liste : programme officiel (annexe C)'))
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


def theoremes_programme():
    """{nom en minuscules: nom exact} des théorèmes du programme officiel (sans la base)."""
    from apps.caracteristics.theoremes import noms_programme
    return noms_programme()


def _theoremes_exacts(noms):
    """Noms exacts du programme (casse ignorée, anciens noms traduits, retirés ôtés), sans doublon."""
    from apps.caracteristics.programme import ALIAS_THEOREMES
    from apps.caracteristics.theoremes import cle
    prog = theoremes_programme()
    alias = {cle(a): v for a, v in ALIAS_THEOREMES.items()}
    out = []
    for nom in noms or []:
        for n in ([nom] if cle(nom) in prog else list(alias.get(cle(nom), ()))):
            exact = prog.get(cle(n))
            if exact and exact not in out:
                out.append(exact)
    return out


def _theoremes_inconnus(noms):
    from apps.caracteristics.programme import ALIAS_THEOREMES
    from apps.caracteristics.theoremes import cle
    prog, alias = theoremes_programme(), {cle(a) for a in ALIAS_THEOREMES}
    return [n for n in noms if cle(n) not in prog and cle(n) not in alias]


def theoremes_des_questions(fiche: dict) -> list:
    """Tous les théorèmes des questions d'une fiche (noms exacts), dans l'ordre."""
    out = []
    for b in fiche.get('blocs') or []:
        if not isinstance(b, dict):
            continue
        for q in [b] + list(b.get('sous_questions') or []):
            for nom in _theoremes_exacts(q.get('theoremes') if isinstance(q, dict) else None):
                if nom not in out:
                    out.append(nom)
    return out


def _meta(q: dict) -> dict:
    meta = {}
    theoremes = _theoremes_exacts(q.get('theoremes'))
    if theoremes:
        meta['theorems'] = theoremes
    if q.get('difficulte'):
        meta['difficulty'] = DIFFICULTIES[q['difficulte']]
    if q.get('duree_secondes'):
        meta['expected_seconds'] = q['duree_secondes']
    if q.get('erreurs_frequentes'):
        meta['common_mistakes'] = list(q['erreurs_frequentes'])
    # `indice` n'est plus une métadonnée : c'est l'indication affichée (champ `hint`, voir to_structure).
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
            if b.get('indice') and not b.get('sous_questions'):
                block['hint'] = _block(b['indice'], src_map)
            if _meta(b) and not b.get('sous_questions'):
                block['meta'] = _meta(b)
            for j, s in enumerate(b.get('sous_questions') or [], 1):
                sq = {'id': f'{bid}-{j}', 'content': _block(s['html'], src_map)}
                if s.get('points'):
                    sq['points'] = s['points']
                if s.get('solution'):
                    sq['solution'] = _block(s['solution'], src_map)
                if s.get('indice'):
                    sq['hint'] = _block(s['indice'], src_map)
                if _meta(s):
                    sq['meta'] = _meta(s)
                block['subQuestions'].append(sq)
        blocks.append(block)
    structure = {'version': '2.1', 'blocks': blocks}
    # « Méthode : » en tête d'une solution → indication de la question (bouton « Indication » du site).
    move_methods_to_hints(structure)
    return _with_credit(structure, fiche)


def _with_credit(structure: dict, fiche: dict) -> dict:
    # Mention visible de l'auteur du document (« Proposé par … » dans l'en-tête du contenu).
    if (fiche.get('credit') or '').strip():
        structure['credit'] = fiche['credit'].strip()
    # `a_verifier` de la fiche : ignoré depuis le 17/10/2026 (bandeau « en cours de vérification » retiré).
    return structure


def _appliquer_edition(content, edition: dict):
    """Titre et classement choisis dans l'éditeur (ids déjà vérifiés à l'enregistrement du brouillon)."""
    from apps.caracteristics.models import Chapter, ClassLevel, School, Subfield, Theorem
    content.title = edition['title']
    if content.type != 'lesson':
        content.difficulty = edition.get('difficulty') or content.difficulty
    if content.type == 'exam':
        content.duration_minutes = edition.get('duration_minutes')
        content.is_national_exam = bool(edition.get('is_national_exam'))
        content.national_year = edition.get('national_year') if content.is_national_exam else None
    content.school = School.objects.filter(pk=edition.get('school')).first() if edition.get('school') else None
    content.save()
    chapters = list(Chapter.objects.filter(pk__in=edition.get('chapters') or []))
    content.class_levels.set(ClassLevel.objects.filter(pk__in=edition.get('class_levels') or []))
    content.chapters.set(chapters)
    content.theorems.set(Theorem.objects.filter(pk__in=edition.get('theorems') or []))
    subfields = {c.subfield_id for c in chapters if c.subfield_id} | set(edition.get('subfields') or [])
    content.subfields.set(Subfield.objects.filter(pk__in=subfields))


def all_html(structure: dict):
    """Tous les textes HTML d'une structure convertie (pour les vérifications de formules)."""
    for b in structure.get('blocks', []):
        for part in (b.get('content'), b.get('hint'), b.get('solution')):
            if part:
                yield b['id'], part['html']
        for sq in b.get('subQuestions', []):
            for part in (sq.get('content'), sq.get('hint'), sq.get('solution')):
                if part:
                    yield sq['id'], part['html']
    for s in structure.get('sections', []):
        yield s['id'], s['content']['html']
        for ss in s.get('subSections', []):
            yield ss['id'], ss['content']['html']


# --------------------------------------------------------------------------- doublons d'énoncé
# Natsu, 16/10/2026 : aucun doublon sur le site. Le titre ne suffisait pas (un même exercice déposé deux fois sous
# deux titres, ou une série importée deux fois) : on compare aussi l'ÉNONCÉ (questions, sans solutions ni
# indications) aux contenus publiés et aux brouillons en attente du même type. Un même exercice repris dans un devoir
# n'est pas un doublon (types différents).
SEUIL_DOUBLON = 0.85


def _texte_comparable(htmls) -> str:
    """Énoncé réduit à ses lettres et chiffres (balises, espaces, ponctuation et habillage LaTeX retirés)."""
    s = ' '.join(h for h in htmls if isinstance(h, str))
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\\(left|right|displaystyle|limits|quad|qquad|[,;:!])', '', s).replace('dfrac', 'frac').replace('tfrac', 'frac')
    return re.sub(r'[^0-9a-zà-ÿ\\]+', '', unicodedata.normalize('NFC', s.lower()))


_FORMULE = re.compile(r'\$\$?(.+?)\$\$?', re.S)


def _formules(htmls) -> str:
    """Formules de l'énoncé seules ($…$), réduites comme le texte. Deux énoncés d'un même modèle (« Résoudre dans ℝ
    les équations suivantes : … ») se ressemblent par leur texte, pas par leurs formules (17/10/2026 : faux doublons
    |x − 1| = 2 contre |x + 1| = x + 1, encadrements de x − y contre xy = 9)."""
    return _texte_comparable(m for h in htmls if isinstance(h, str) for m in _FORMULE.findall(h))


def _htmls_fiche(fiche: dict) -> list:
    htmls = []

    def walk(blocs):
        for b in blocs or []:
            if isinstance(b, dict):
                htmls.append(b.get('html'))
                for sq in b.get('sous_questions') or []:
                    if isinstance(sq, dict):
                        htmls.append(sq.get('html'))
                walk(b.get('blocs'))
    walk(fiche.get('blocs'))
    return htmls


def _htmls_structure(structure) -> list:
    htmls = []
    if isinstance(structure, dict):
        for b in structure.get('blocks') or []:
            htmls.append((b.get('content') or {}).get('html'))
            for sq in b.get('subQuestions') or []:
                htmls.append((sq.get('content') or {}).get('html'))
    return htmls


def _enonce_fiche(fiche: dict) -> tuple[str, str]:
    """(texte comparable, formules) de l'énoncé d'une fiche."""
    htmls = _htmls_fiche(fiche)
    return _texte_comparable(htmls), _formules(htmls)


def _enonce_structure(structure) -> tuple[str, str]:
    htmls = _htmls_structure(structure)
    return _texte_comparable(htmls), _formules(htmls)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if m.real_quick_ratio() < SEUIL_DOUBLON or m.quick_ratio() < SEUIL_DOUBLON:
        return 0.0
    return m.ratio()


def _ressemblance(a: tuple[str, str], b: tuple[str, str]) -> float:
    """Ressemblance des énoncés ; 0 si leurs formules diffèrent (même texte, autres équations = autre exercice)."""
    r = _ratio(a[0], b[0])
    if r >= SEUIL_DOUBLON and (a[1] or b[1]) and _ratio(a[1], b[1]) < SEUIL_DOUBLON:
        return 0.0
    return r


def doublons_d_enonce(fiche: dict, kind: str, exclure_pk=None) -> list[str]:
    """Erreurs « doublon probable » : même énoncé (≥ 85 % de ressemblance) qu'un contenu publié ou qu'un brouillon en
    attente du même type (autre clé). Rien si la fiche a "doublon_ok": true (vérifié à la main)."""
    from apps.things.models import Content

    moi = _enonce_fiche(fiche)
    if len(moi[0]) < 40:  # énoncé trop court pour juger
        return []
    erreurs = []
    for c in Content.objects.filter(type=kind).exclude(pk=exclure_pk).only('id', 'title', 'display_id', 'json_content'):
        if ((c.json_content or {}).get('import') or {}).get('cle') == fiche.get('cle'):
            continue
        r = _ressemblance(moi, _enonce_structure(c.json_content))
        if r >= SEUIL_DOUBLON:
            erreurs.append(f'doublon probable : même énoncé ({r:.0%}) que le contenu publié #{c.display_id} « {c.title} »'
                           ' (ne pas déposer ; "doublon_ok": true seulement si vérifié à la main)')
    try:
        from apps.ia.models import IAJob
        brouillons = IAJob.objects.filter(status__in=(IAJob.PRET, IAJob.ERREUR)).only('id', 'result')
    except Exception:  # application IA absente (tests isolés)
        brouillons = []
    type_fiche = fiche.get('type')
    for job in brouillons:
        for f in ((job.result or {}).get('fiches') or []):
            if not isinstance(f, dict) or f.get('cle') == fiche.get('cle') or f.get('type') != type_fiche:
                continue
            r = _ressemblance(moi, _enonce_fiche(f))
            if r >= SEUIL_DOUBLON:
                erreurs.append(f'doublon probable : même énoncé ({r:.0%}) que le brouillon {job.id} « {f.get("titre", "")} »'
                               ' (ne pas déposer ; "doublon_ok": true seulement si vérifié à la main)')
    return erreurs


# --------------------------------------------------------------------------- base de données

def _ecole_valide(ecole) -> bool:
    if isinstance(ecole, str):
        return 0 < len(ecole.strip()) <= 255
    return (isinstance(ecole, dict) and isinstance(ecole.get('nom'), str) and 0 < len(ecole['nom'].strip()) <= 255
            and (ecole.get('ville') is None or isinstance(ecole.get('ville'), str)))


# Noms d'en-tête qui ne sont pas ceux de la liste officielle → (nom, ville) de la liste. « Groupe scolaire Sanaa »
# (M. Haddar) : plusieurs « Sanaa » dans la liste, Natsu a choisi Sanaa 5, Hay-Hassani (16/10/2026).
ALIAS_ECOLES = {
    'groupe scolaire sanaa': ('Sanaa 5', 'Hay-Hassani'),
    'gs sanaa': ('Sanaa 5', 'Hay-Hassani'),
    'sanaa': ('Sanaa 5', 'Hay-Hassani'),
}


def trouver_ecole(ecole):
    """Établissement de la liste officielle (caracteristics.School) → (école ou None, avertissement ou None).
    Recherche par mots normalisés (comme le formulaire du site), nom exact d'abord ; introuvable ou ambigu : vide,
    avec un avertissement (l'import continue). Les noms d'ALIAS_ECOLES (sans ville) sont d'abord traduits."""
    from apps.caracteristics.models import School, school_search_key

    if not ecole or not _ecole_valide(ecole):
        return None, None
    nom = (ecole if isinstance(ecole, str) else ecole['nom']).strip()
    ville = '' if isinstance(ecole, str) else (ecole.get('ville') or '').strip()
    if not ville and school_search_key(nom) in ALIAS_ECOLES:
        nom, ville = ALIAS_ECOLES[school_search_key(nom)]
    qs = School.objects.all()
    for mot in school_search_key(nom, ville).split():
        qs = qs.filter(search__contains=mot)
    trouves = list(qs[:20])
    exacts = [e for e in trouves if school_search_key(e.name) == school_search_key(nom)
              and (not ville or school_search_key(e.city) == school_search_key(ville))]
    choix = exacts if len(exacts) == 1 else trouves
    libelle = f'« {nom} »' + (f' ({ville})' if ville else '')
    if len(choix) == 1:
        return choix[0], None
    if not choix:
        return None, f'établissement {libelle} introuvable dans la liste officielle : laissé vide'
    villes = sorted({e.city for e in choix if e.city})[:5]
    return None, (f'{len(choix)} établissements correspondent à {libelle}'
                  + (f' ({", ".join(villes)}…)' if villes else '') + ' : précise la ville ; laissé vide')


# Chapitre décidé à la main (audit du 16/10/2026) : la fiche listait un chapitre de trop, dont la question ne demande
# qu'un outil d'une classe précédente (ex. calculer f′ pour des variations = 1ère Bac, pas « Dérivation » de 2ème Bac).
# Prioritaire sur la règle « dernier chapitre » ; migration things 0019 pour les contenus déjà publiés.
CHAPITRES_FORCES = {
    'ds1-2sm-2020': ['Limites et continuité'],
    'ds1-2sm-2022': ['Limites et continuité'],
    'serie2-continuite-arctan-ex02': ['Limites et continuité'],
    'serie2-continuite-arctan-ex10': ['Limites et continuité'],
    'serie-continuite-reciproque-ex11': ['Limites et continuité'],
    'serie-continuite-reciproque-ex12': ['Limites et continuité'],
    'serie-continuite-reciproque-ex16': ['Limites et continuité'],
    'haddar-lc-ex16': ['Limites et continuité'],
    # + Calcul vectoriel : un exercice entier de ces devoirs (17/10/2026, chapitre de chaque exercice).
    'ds2-tcs-2022': ['Calcul vectoriel dans le plan', 'Ordre dans ℝ'],
    'ds2-tcs-2023': ['Calcul vectoriel dans le plan', 'Ordre dans ℝ'],
    'ordre-tcs-ex15': ['Ordre dans ℝ'],
    'ordre-tcs-ex16': ['Ordre dans ℝ'],
    'ordre-tcs-ex17': ['Ordre dans ℝ'],
    'ordre-tcs-ex18': ['Ordre dans ℝ'],
    'ordre-tcs-ex19': ['Ordre dans ℝ'],
    'logique-1sm-ex5': ['Logique mathématique'],
    # Validés par Natsu (16/10/2026, second lot) : les bonus ne comptent pas pour le classement d'un devoir.
    'ds-synthese1-2sm-2026-belkhatir': ['Limites et continuité'],
    'etude-fonctions-2pc-serie-ex4': ['Limites et continuité'],
    'etude-fonctions-2pc-serie-ex5': ['Limites et continuité'],
    'logique-ens-app-1sm-ex10': ['Logique mathématique'],
}


# Exercice ou devoir tiré d'un document de 2ème Bac PC/SVT : en PC/SVT seulement, jamais aussi en 2ème Bac SM (Natsu,
# 18/10/2026 : « les exercices que je t'ai envoyés de 2ème PC sont aussi sur 2ème SM, enlève ça »). Le contraire
# (document SM aussi au programme PC, `aussi_2pc`) reste possible, et une leçon garde ses deux niveaux (0024 annulée par 0025). Migration things 0023.
NIVEAU_SM = '2ème Bac SM'
_DOC_PC = re.compile(r'2\s*-?\s*pc', re.I)
_DOC_SM = re.compile(r'2\s*-?\s*sm', re.I)


def est_document_pc(nom) -> bool:
    """Nom de document de 2ème Bac PC/SVT (« suites exrcices (2) -2PC.pdf », « ds 2-2pc … ») et pas aussi SM."""
    return isinstance(nom, str) and bool(_DOC_PC.search(nom)) and not _DOC_SM.search(nom)


def document_pc(fiche) -> bool:
    src = fiche.get('source') if isinstance(fiche.get('source'), dict) else {}
    return est_document_pc(src.get('document'))


def chapitres_forces(cle, levels, subject=None):
    """Chapitres imposés pour cette clé (CHAPITRES_FORCES), à chacun des niveaux du contenu ; None si aucun."""
    from apps.caracteristics.models import Chapter

    noms = CHAPITRES_FORCES.get(cle)
    if not noms:
        return None
    qs = Chapter.objects.filter(subject=subject) if subject else Chapter.objects.all()
    out = []
    for lvl in levels:
        for nom in noms:
            ch = qs.filter(name=nom, class_levels=lvl).first()
            if ch and ch not in out:
                out.append(ch)
    return out or None


def chapitres_principaux(chapters, levels):
    """Chapitres d'un exercice ou d'un examen (16/10/2026) : à chaque niveau, seulement le dernier dans l'ordre du
    programme (un élève qui ouvre « Limites et continuité » n'a pas encore vu la dérivation). Un chapitre absent du
    programme compte comme le premier ; un chapitre d'aucun des niveaux est gardé. Ordre d'origine conservé."""
    from apps.caracteristics.programme import RANG_ABSENT, rang

    garder = set()
    for lvl in levels:
        du_niveau = [c for c in chapters if c.class_levels.filter(pk=lvl.pk).exists()]
        if du_niveau:
            r = rang(lvl.name)
            garder.add(max(du_niveau, key=lambda c: (-1 if r[c.name] == RANG_ABSENT else r[c.name], c.id)).pk)
    level_ids = [lvl.pk for lvl in levels]
    garder |= {c.pk for c in chapters if not c.class_levels.filter(pk__in=level_ids).exists()}
    return [c for c in chapters if c.pk in garder] or list(chapters)


def chapitres_par_exercice(chapters, levels, parties):
    """Devoir (17/10/2026, Natsu : « les DS n° 1 contiennent aussi les ensembles de nombres ») : un devoir est fait
    d'exercices indépendants ; chacun compte pour le DERNIER des chapitres du devoir dont ses questions utilisent un
    théorème. `parties` = noms des théorèmes de chaque exercice. → chapitres à garder en plus du dernier du devoir.
    Un théorème rattaché à plusieurs chapitres compte pour le PREMIER, celui où il s'apprend (19/10/2026 : « Limite et
    continuité d'une fonction composée », aussi dans « Suites numériques », rangeait une étude de fonction en Suites)."""
    from apps.caracteristics.programme import RANG_ABSENT, rang

    garder = []
    for lvl in levels:
        r = rang(lvl.name)
        cle = lambda c: (-1 if r[c.name] == RANG_ABSENT else r[c.name], c.id)  # noqa: E731
        du_niveau = sorted((c for c in chapters if c.class_levels.filter(pk=lvl.pk).exists()), key=cle)
        for noms in parties:
            premiers = []  # pour chaque théorème de l'exercice, le premier chapitre du devoir qui le contient
            for nom in noms:
                ch = next((c for c in du_niveau if c.theorems.filter(name=nom).exists()), None)
                if ch is not None:
                    premiers.append(ch)
            if premiers:
                dernier = max(premiers, key=cle)
                if dernier not in garder:
                    garder.append(dernier)
    return garder


def theoremes_par_partie(fiche):
    """Théorèmes de chaque exercice (bloc « partie ») d'une fiche de devoir : liste d'ensembles de noms."""
    parties, cur = [], None
    for b in fiche.get('blocs') or []:
        if not isinstance(b, dict):
            continue
        if b.get('type') == 'partie':
            cur = set()
            parties.append(cur)
        elif b.get('type') == 'question':
            if cur is None:
                cur = set()
                parties.append(cur)
            for q in [b] + [s for s in b.get('sous_questions') or [] if isinstance(s, dict)]:
                cur |= {t for t in q.get('theoremes') or [] if isinstance(t, str)}
    return parties


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
                                                          ' — programme : src/apps/caracteristics/programme.py'))
    return found


def check_against_db(fiche: dict) -> tuple[list[str], list[str], dict]:
    """Taxonomie existante, doublons, contenu à mettre à jour. Renvoie (erreurs, avertissements, résolu).
    Anciens noms de chapitres et de théorèmes (avant le programme officiel du 11/10/2026) acceptés : traduits par
    programme.traduire_noms() selon les niveaux de la fiche, avec un avertissement chacun."""
    from apps.caracteristics.models import Chapter, ClassLevel, Subject, Subfield, Theorem
    from apps.caracteristics.programme import nom_niveau_actuel, traduire_noms
    from apps.things.models import Content

    errors, warnings = [], []
    subject_name = fiche.get('matiere', 'Mathématiques')
    subject = Subject.objects.filter(name__iexact=subject_name).first()
    if not subject:
        errors.append(f'matière inconnue : « {subject_name} »')
    # Ancien nom d'un niveau renommé (« 2ème Bac PC » → « 2ème Bac PC/SVT », 12/10/2026) : accepté tel quel.
    niveaux = [nom_niveau_actuel(n) if isinstance(n, str) else n for n in fiche.get('niveaux') or []] \
        if isinstance(fiche.get('niveaux'), list) else []
    if TYPES.get(fiche.get('type')) in ('exercise', 'exam') and document_pc(fiche) and NIVEAU_SM in niveaux:
        niveaux = [n for n in niveaux if n != NIVEAU_SM]
        warnings.append(f'niveaux : document de 2ème Bac PC/SVT, rangé en PC/SVT seulement (« {NIVEAU_SM} » retiré)')
    levels = _match(ClassLevel.objects.all(), niveaux, 'niveau', errors)
    # Théorèmes du contenu = ceux de la fiche ∪ ceux de ses questions (13/10/2026 : le filtre « Théorème » des listes
    # trouve un exercice par les théorèmes de ses questions).
    th_fiche = fiche.get('theoremes', []) if isinstance(fiche.get('theoremes'), list) else []
    th_fiche = th_fiche + [n for n in theoremes_des_questions(fiche) if n not in th_fiche]
    noms_chapitres, noms_theoremes, traductions = traduire_noms(
        fiche.get('chapitres', []), th_fiche, [str(n) for n in niveaux])
    warnings += traductions
    chapters = _match(Chapter.objects.all(), noms_chapitres, 'chapitre', errors,
                      **({'subject': subject} if subject else {}))
    theorems = _match(Theorem.objects.all(), noms_theoremes, 'théorème', errors)
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
    # Exercice, examen : rangé seulement dans le DERNIER chapitre du programme dont il a besoin (Natsu, 16/10/2026) ;
    # les chapitres d'avant sont des prérequis (un DS de dérivabilité n'est pas un devoir de « Limites et continuité »).
    # Un devoir garde en plus le dernier chapitre de CHACUN de ses exercices (17/10/2026, chapitres_par_exercice).
    forces = chapitres_forces(fiche.get('cle'), levels, subject) if kind in ('exercise', 'exam') else None
    if forces:
        if {c.pk for c in forces} != {c.pk for c in chapters}:
            warnings.append(f'chapitres : « {" », « ".join(c.name for c in forces)} » (décidé à la main, CHAPITRES_FORCES)')
        chapters = forces
    elif kind in ('exercise', 'exam') and len(chapters) > 1:
        gardes = chapitres_principaux(chapters, levels)
        if kind == 'exam':  # un devoir va aussi dans le chapitre de chacun de ses exercices
            gardes += [c for c in chapitres_par_exercice(chapters, levels, theoremes_par_partie(fiche))
                       if c not in gardes]
            gardes = [c for c in chapters if c in gardes]
        retires = [c.name for c in chapters if c not in gardes]
        if retires:
            warnings.append(f'chapitres : rangé dans « {" », « ".join(c.name for c in gardes)} » seulement '
                            f'(dernier chapitre du programme utilisé) ; prérequis retirés : {", ".join(retires)}')
            chapters = gardes
    existing = Content.objects.filter(json_content__import__cle=fiche.get('cle')).first()
    # « remplace » : id d'un contenu publié sans clé d'import (modifié dans l'éditeur avant le 15/10/2026, ou
    # créé sur le site) que cette fiche met à jour, au même lien.
    if existing is None and fiche.get('remplace') is not None:
        existing = Content.objects.filter(pk=fiche['remplace']).first() if isinstance(fiche['remplace'], int) else None
        if existing is None:
            errors.append(f'« remplace » : contenu #{fiche["remplace"]} introuvable')
    if existing and existing.type != kind:
        errors.append(f'la clé « {fiche.get("cle")} » est déjà utilisée par un contenu de type {existing.type}')
    if not fiche.get('doublon_ok'):
        title_key = normalize_text(fiche.get('titre', ''))
        for c in Content.objects.filter(type=kind).exclude(pk=getattr(existing, 'pk', None)).only('id', 'title', 'display_id'):
            if normalize_text(c.title) == title_key:
                # Exercice, devoir : l'énoncé tranche (17/10/2026, « Intersection et réunion d'intervalles » de deux
                # séries) ; le même titre seul n'est qu'un avertissement. Leçon : pas d'énoncé à comparer.
                (warnings if kind in ('exercise', 'exam') else errors).append(
                    f'doublon probable : même titre que #{c.display_id} « {c.title} »'
                    + (' (énoncé différent : changer le titre conseillé)' if kind in ('exercise', 'exam')
                       else ' (changer le titre ou mettre "doublon_ok": true)'))
        if kind in ('exercise', 'exam'):
            errors += doublons_d_enonce(fiche, kind, getattr(existing, 'pk', None))
    school, avert_ecole = trouver_ecole(fiche.get('ecole'))
    if avert_ecole:
        warnings.append(avert_ecole)
    return errors, warnings, {
        'subject': subject, 'levels': levels, 'chapters': chapters, 'theorems': theorems,
        'subfields': subfields, 'existing': existing, 'school': school,
    }


def editorial_author():
    from django.contrib.auth.models import User
    user, created = User.objects.get_or_create(username=EDITORIAL_USERNAME, defaults={'first_name': 'Fidni'})
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def remplacer_sources(obj, src_map: dict):
    """Remplace les liens d'images (« figures/x.png ») dans tous les textes d'une structure."""
    if isinstance(obj, str):
        for rel, url in src_map.items():
            obj = obj.replace(f'"{rel}"', f'"{url}"')
        return obj
    if isinstance(obj, list):
        return [remplacer_sources(x, src_map) for x in obj]
    if isinstance(obj, dict):
        return {k: remplacer_sources(v, src_map) for k, v in obj.items()}
    return obj


def import_fiche(fiche: dict, base_dir: str, *, api_base: str = 'https://api.fidni.fr', author=None, edition=None):
    """Crée ou met à jour le contenu (clé identique = mise à jour). Tout ou rien.
    `edition` : la version modifiée à la main dans l'éditeur (Pilotage › À valider, apps/ia/views.job_editeur) :
    sa structure et son classement remplacent ceux de la fiche ; figures, crédit et clé viennent de la fiche."""
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
        # Établissement : seulement s'il est trouvé (sinon celui choisi à la main sur le site est gardé).
        if res.get('school') is not None:
            content.school = res['school']
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

        if edition:
            import copy
            st = {k: v for k, v in copy.deepcopy(edition['json_content']).items() if k not in ('credit', 'a_verifier', 'import')}
            structure = _with_credit(remplacer_sources(st, src_map), fiche)
        else:
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
        if edition:
            _appliquer_edition(content, edition)
        for att in old_files:  # figures de la version précédente
            att.file.delete(save=False)
            att.delete()
    return content, created
