"""Barème d'une évaluation : les questions notées du sujet figé, leurs points, et la note d'une copie.

Les chemins des questions sont ceux du reste du site (QuestionProgress, renderer) : l'id du bloc, ou
« <id du bloc>.<id de la sous-question> ». Une partie notée (« Exercice 2 — 5 pts ») dont les questions n'ont pas de
points voit son barème réparti à parts égales, comme sur la page du devoir (ExamView.splitExam). Le professeur peut
remplacer les points de chaque question (Evaluation.maxima).
"""
import copy
import html
import re
import uuid

from apps.caracteristics.theoremes import de_la_question

_BALISE = re.compile(r'<[^>]+>')
_ESPACES = re.compile(r'[ \t]+')


def texte(fragment):
    """HTML d'un énoncé → texte (les formules $…$ restent telles quelles) : pour les consignes de l'IA."""
    if isinstance(fragment, dict):
        fragment = fragment.get('html') or ''
    s = str(fragment or '')
    s = re.sub(r'<\s*(br|/p|/li|/div|/h\d)\s*/?>', '\n', s, flags=re.I)
    s = re.sub(r'<\s*li[^>]*>', '- ', s, flags=re.I)
    s = html.unescape(_BALISE.sub('', s))
    lignes = [_ESPACES.sub(' ', ligne).strip() for ligne in s.split('\n')]
    return '\n'.join(ligne for ligne in lignes if ligne)


def _html(bloc, cle):
    v = (bloc or {}).get(cle)
    return (v.get('html') if isinstance(v, dict) else v) or ''


def completer_ids(structure):
    """Copie du sujet où chaque bloc et sous-question a un identifiant (les chemins des notes en dépendent)."""
    s = copy.deepcopy(structure or {})
    s.setdefault('version', '2.1')
    for b in s.setdefault('blocks', []):
        if not b.get('id'):
            b['id'] = uuid.uuid4().hex[:10]
        for sq in b.get('subQuestions') or []:
            if not sq.get('id'):
                sq['id'] = uuid.uuid4().hex[:10]
    return s


def questions(structure, maxima=None):
    """Questions notées, dans l'ordre : [{chemin, label, partie, max, theoremes, enonce, solution, contexte}].

    `label` : « 1 », « 2.b » (numérotation par partie) précédé de la partie si le sujet en a (« Ex. 2 – 1.a »).
    `contexte` : texte de l'énoncé commun (blocs « context ») qui précède la question dans sa partie.
    """
    blocs = (structure or {}).get('blocks') or []
    avec_parties = any(b.get('type') == 'section' for b in blocs)
    parties, courante, num, contexte = [], None, 0, []
    out = []
    for b in blocs:
        t = b.get('type')
        if t == 'section':
            courante = {'titre': texte(_html(b, 'content')) or f'Partie {len(parties) + 1}',
                        'points': _nombre(b.get('points')), 'questions': []}
            parties.append(courante)
            num, contexte = 0, []
            continue
        if courante is None:
            courante = {'titre': '' if not avec_parties else 'Introduction', 'points': 0, 'questions': []}
            parties.append(courante)
        if t == 'context':
            contexte.append(texte(_html(b, 'content')))
            continue
        if t != 'question':
            continue
        num += 1
        subs = b.get('subQuestions') or []
        enonce_q = texte(_html(b, 'content'))
        items = ([(f"{b.get('id')}.{sq.get('id')}", f'{num}.{chr(ord("a") + i)}', sq, enonce_q)
                  for i, sq in enumerate(subs)] if subs else [(str(b.get('id')), str(num), b, '')])
        for chemin, label, q, parent in items:
            courante['questions'].append({
                'chemin': chemin,
                'label': label,
                'partie': courante['titre'],
                'max': _nombre(q.get('points')),
                'theoremes': de_la_question(q.get('meta')),
                'enonce': texte(_html(q, 'content')),
                'enonce_parent': parent,
                'enonce_html': _html(q, 'content'),
                'solution': texte(_html(q, 'solution')),
                'solution_html': _html(q, 'solution'),
                'contexte': '\n'.join(c for c in contexte if c),
            })
    for p in parties:
        qs = p['questions']
        # Partie notée sans points par question : répartis à parts égales (comme la page du devoir).
        if p['points'] > 0 and qs and all(not q['max'] for q in qs):
            for q in qs:
                q['max'] = p['points'] / len(qs)
        if avec_parties and p['titre']:
            court = _court(p['titre'])
            for q in qs:
                q['label'] = f"{court} – {q['label']}"
        out.extend(qs)
    # Sujet sans aucun barème (exercice de la banque) : 1 point par question, à ajuster par le professeur.
    if out and all(not q['max'] for q in out):
        for q in out:
            q['max'] = 1.0
    for q in out:
        if maxima and q['chemin'] in maxima:
            q['max'] = _nombre(maxima[q['chemin']])
        q['max'] = round(q['max'], 2)
    return out


def _court(titre):
    """« Exercice 2 (5 points) » → « Ex. 2 » ; « Problème » → « Problème »."""
    m = re.match(r'\s*exercice\s*(n°\s*)?(\d+)', titre, re.I)
    if m:
        return f'Ex. {m.group(2)}'
    return titre.split('(')[0].split(':')[0].strip()[:24]


def _nombre(v):
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return 0.0


def arrondir(points, maxi, pas):
    """Points d'une question : bornés à [0, max] et arrondis au pas (0,25, 0,5 ou 1)."""
    try:
        x = float(points)
    except (TypeError, ValueError):
        return None
    x = min(max(x, 0.0), float(maxi))
    pas = pas if pas in (0.25, 0.5, 1) else 0.5
    x = round(x / pas) * pas
    return round(min(x, float(maxi)), 2)


def notes_finales(evaluation, copie, qs=None):
    """{chemin: {points, max, commentaire, source}} : la note du professeur, sinon celle de l'IA."""
    qs = qs if qs is not None else questions(evaluation.sujet, evaluation.maxima)
    out = {}
    for q in qs:
        c = q['chemin']
        prof, ia = (copie.notes or {}).get(c) or {}, (copie.ia or {}).get(c) or {}
        if prof.get('points') is not None:
            pts, src = prof.get('points'), 'prof'
        elif ia.get('points') is not None:
            pts, src = ia.get('points'), 'ia'
        else:
            pts, src = None, None
        com = prof['commentaire'] if 'commentaire' in prof else ia.get('commentaire', '')
        out[c] = {'points': arrondir(pts, q['max'], evaluation.pas) if pts is not None else None,
                  'max': q['max'], 'commentaire': com or '', 'source': src}
    return out


def total(evaluation, copie, qs=None):
    """(points obtenus, total du barème, note sur `note_sur`) ; None si une question n'est pas notée."""
    qs = qs if qs is not None else questions(evaluation.sujet, evaluation.maxima)
    notes = notes_finales(evaluation, copie, qs)
    maxi = round(sum(q['max'] for q in qs), 2)
    if not qs or any(n['points'] is None for n in notes.values()):
        return None, maxi, None
    pts = round(sum(n['points'] for n in notes.values()), 2)
    sur = evaluation.note_sur or 20
    return pts, maxi, (round(pts * sur / maxi, 2) if maxi else None)
