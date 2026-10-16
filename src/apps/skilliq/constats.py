"""Quiz de chapitre écrits d'après les résultats des élèves (13/10/2026) : constats exportés, questions importées.

1. `manage.py quiz_constats` (constats_niveau) : pour chaque chapitre ayant un contenu en ligne, une fiche
   Markdown, sans aucune donnée personnelle (des taux, jamais d'élèves ; comptes maison et auteur du contenu
   exclus, comme things/difficulty.py) :
   - questions d'exercices et d'examens du chapitre les moins réussies (QuestionProgress), avec leur énoncé ;
   - théorèmes les moins réussis (`meta.theorems` des questions) ; solutions « pas comprises » ;
   - questions du quiz actuel les plus ratées et la mauvaise réponse la plus choisie (SkillAssessment.answers) ;
   - programme officiel du niveau, cours en ligne (leçons), questions déjà écrites.
2. Claude rédige d'après ces fiches des QCM « façon certification » (quatre réponses très proches, une seule
   juste ; ou, depuis le 16/10/2026, plusieurs justes : « bonnes » + « distracteurs », 3 à 6 réponses, typiquement
   2 bonnes sur 5) dans un fichier JSON (contenus/quiz/).
3. `manage.py quiz_importer <fichier>` (importer) : contrôle (réponses distinctes et non vides, formules `$`
   appariées), doublons écartés, réponses mélangées, enregistrement en brouillon « à relire »
   (SkillQuestion.a_relire, is_active=False) : invisible des élèves tant que l'administrateur ne l'a pas validée
   dans Pilotage › Quiz.
"""
import html as html_lib
import random
import re
from collections import Counter, defaultdict

from .models import SkillAssessment, SkillQuestion, choix_de

MIN_ELEVES = 2          # en dessous, une question n'est pas « peu réussie » : elle est peu faite
FAIBLE_SOUS = 0.7       # taux de réussite en dessous duquel une question ou un théorème est un constat
CONSTATS_MAX = 12
COURS_MAX = 24000       # caractères de cours envoyés
LONGUEURS = {'question': 350, 'reponse': 200, 'explication': 600}
SCORE = {'success': 1.0, 'partial': 0.5, 'review': 0.0, 'failed': 0.0}
DIFFICULTES = ('easy', 'medium', 'hard')
_TAG = re.compile(r'<[^>]+>')
_ESPACES = re.compile(r'\s+')


def texte(html, limite=None):
    """HTML d'un contenu → texte lisible (formules `$…$` gardées telles quelles)."""
    t = _ESPACES.sub(' ', html_lib.unescape(_TAG.sub(' ', str(html or '')))).strip()
    return t if limite is None or len(t) <= limite else t[:limite].rsplit(' ', 1)[0] + '…'


def _htmls(value, out):
    """Tous les champs `html` d'une structure (leçon : sections et sous-sections ; exercice : blocs)."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'html' and isinstance(v, str):
                out.append(v)
            else:
                _htmls(v, out)
    elif isinstance(value, list):
        for v in value:
            _htmls(v, out)
    return out


def _enonces(structure):
    """{chemin: (énoncé, théorèmes)} des questions finales, chemins alignés sur QuestionProgress.question_path."""
    out = {}
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        tete = texte((block.get('content') or {}).get('html'), 300)
        subs = block.get('subQuestions') or []
        if subs:
            for sub in subs:
                out[f"{block.get('id')}.{sub.get('id')}"] = (
                    (tete + ' … ' if tete else '') + texte((sub.get('content') or {}).get('html'), 400),
                    (sub.get('meta') or {}).get('theorems') or [])
        else:
            out[str(block.get('id'))] = (tete, (block.get('meta') or {}).get('theorems') or [])
    return out


def _maison():
    from django.contrib.auth.models import User
    from apps.users.admin_dashboard import _house_filter
    return set(User.objects.filter(_house_filter()).values_list('id', flat=True))


def _contenus(chapitre, niveau, types):
    from apps.things.models import Content
    qs = Content.objects.filter(chapters=chapitre, type__in=types)
    if niveau is not None:
        qs = qs.filter(class_levels=niveau)
    return qs.distinct()


def constats(chapitre, niveau=None):
    """Résultats des élèves sur ce chapitre : {'eleves', 'questions', 'theoremes', 'quiz'} (listes triées, des moins
    réussies aux mieux réussies, celles sous FAIBLE_SOUS seulement)."""
    from django.contrib.contenttypes.models import ContentType
    from apps.interactions.models import QuestionProgress
    from apps.things.models import Content

    maison = _maison()
    contenus = {c.id: c for c in _contenus(chapitre, niveau, ('exercise', 'exam')).only(
        'id', 'title', 'type', 'display_id', 'author_id', 'json_content')}
    enonces = {cid: _enonces(c.json_content) for cid, c in contenus.items()}
    ct = ContentType.objects.get_for_model(Content)
    par_question = defaultdict(lambda: {'n': 0.0, 'score': 0.0, 'eleves': set(), 'incompris': 0})
    eleves = set()
    for cid, uid, chemin, st, src, valid in (
            QuestionProgress.objects.filter(content_type=ct, object_id__in=list(contenus))
            .values_list('object_id', 'user_id', 'question_path', 'status', 'source', 'solution_validation')):
        if uid in maison or uid == contenus[cid].author_id or st not in SCORE or chemin not in enonces[cid]:
            continue
        poids = 0.5 if src == 'tout' else 1.0  # « Tout réussi » en un clic pèse moins (difficulty.py)
        q = par_question[(cid, chemin)]
        q['n'] += poids
        q['score'] += poids * SCORE[st]
        q['eleves'].add(uid)
        q['incompris'] += valid == 'not-understood'
        eleves.add(uid)

    questions, theoremes = [], defaultdict(lambda: [0.0, 0.0, set()])
    for (cid, chemin), q in par_question.items():
        taux = q['score'] / q['n']
        for th in enonces[cid][chemin][1]:
            theoremes[th][0] += q['score']
            theoremes[th][1] += q['n']
            theoremes[th][2] |= q['eleves']
        if len(q['eleves']) >= MIN_ELEVES and (taux < FAIBLE_SOUS or q['incompris']):
            c = contenus[cid]
            questions.append({
                'contenu': f"{'Examen' if c.type == 'exam' else 'Exercice'} {c.display_id} « {c.title} »",
                'question': chemin.replace('.', ' · '), 'enonce': enonces[cid][chemin][0],
                'theoremes': list(enonces[cid][chemin][1]),
                'reussite': round(taux * 100), 'eleves': len(q['eleves']), 'incompris': q['incompris'],
            })
    questions.sort(key=lambda q: (q['reussite'], -q['eleves']))
    faibles = sorted(
        ({'theoreme': k, 'reussite': round(s / n * 100), 'eleves': len(e)}
         for k, (s, n, e) in theoremes.items() if n and len(e) >= MIN_ELEVES and s / n < FAIBLE_SOUS),
        key=lambda x: x['reussite'])
    return {'eleves': len(eleves), 'questions': questions[:CONSTATS_MAX], 'theoremes': faibles[:CONSTATS_MAX],
            'quiz': constats_quiz(chapitre, maison)}


def _bonnes_texte(q):
    """Texte des bonnes réponses : « A » ou, pour plusieurs bonnes réponses, « A » et « B » (sans les guillemets
    extérieurs, ajoutés par l'appelant)."""
    return ' » et « '.join(q.options[i] for i in q.bonnes() if 0 <= i < len(q.options))


def constats_quiz(chapitre, maison=None):
    """Questions du quiz actuel les plus ratées (dernier passage de chaque élève) et la mauvaise réponse préférée."""
    maison = _maison() if maison is None else maison
    qs = {q.id: q for q in SkillQuestion.objects.filter(chapter=chapitre)}
    stats = defaultdict(lambda: [0, 0, Counter()])
    for uid, reponses in SkillAssessment.objects.filter(chapter=chapitre).values_list('user_id', 'answers'):
        if uid in maison or not isinstance(reponses, dict):
            continue
        for qid, rep in reponses.items():
            q = qs.get(int(qid)) if str(qid).isdigit() else None
            if q is None or not isinstance(rep, (int, list)) or isinstance(rep, bool):
                continue
            s = stats[q.id]
            s[0] += 1
            if q.est_juste(rep):
                s[1] += 1
            else:  # mauvaises réponses cochées (plusieurs bonnes réponses : celles cochées à tort)
                for i in choix_de(rep):
                    if i < len(q.options) and i not in q.bonnes():
                        s[2][i] += 1
    out = []
    for qid, (n, ok, fausses) in stats.items():
        if n >= MIN_ELEVES and ok / n < FAIBLE_SOUS:
            q = qs[qid]
            choix = fausses.most_common(1)
            out.append({'question': q.question, 'bonne': _bonnes_texte(q), 'reussite': round(ok / n * 100),
                        'eleves': n, 'piege': q.options[choix[0][0]] if choix else None})
    return sorted(out, key=lambda x: x['reussite'])[:CONSTATS_MAX]


def cours(chapitre, niveau=None, limite=COURS_MAX):
    """Texte des leçons en ligne du chapitre (au niveau donné d'abord), tronqué à `limite` caractères."""
    morceaux = []
    for lecon in _contenus(chapitre, niveau, ('lesson',)).order_by('id') or _contenus(chapitre, None, ('lesson',)):
        morceaux.append(f'### {lecon.title}\n' + '\n'.join(texte(h) for h in _htmls(lecon.json_content, []) if texte(h)))
    tout = '\n\n'.join(morceaux)
    return tout if len(tout) <= limite else tout[:limite] + '\n[… cours tronqué]'


def _programme(chapitre, niveau):
    from apps.caracteristics.programme import chapitre as entree
    from apps.caracteristics.models import Theorem
    lignes = []
    e = entree(niveau.name, chapitre.name) if niveau is not None else None
    if e:
        for champ, titre in (('capacites', 'Capacités exigibles'), ('contenus', 'Contenus'),
                             ('theoremes', 'Théorèmes et propriétés du programme'),
                             ('hors_programme', 'Hors programme (à ne pas évaluer)'),
                             ('vu_plus_tard', 'Vu plus tard (à ne pas évaluer)'),
                             ('perimetre', 'Périmètre habituel'), ('reperes', 'Repères')):
            if e.get(champ):
                lignes.append(f'- {titre} : ' + ' ; '.join(str(x).rstrip(' ;.') for x in e[champ]) + '.')
    thms = Theorem.objects.filter(chapters=chapitre)
    if niveau is not None:
        thms = thms.filter(class_levels=niveau)
    noms = sorted(set(thms.values_list('name', flat=True)))
    if noms:
        lignes.append('- Théorèmes rattachés au chapitre sur Fidni : ' + ' ; '.join(noms) + '.')
    return '\n'.join(lignes) or '(programme détaillé non disponible : reste dans le cours fourni)'


def _bloc_constats(c):
    if not (c['questions'] or c['theoremes'] or c['quiz']):
        if c['eleves']:
            return (f"{c['eleves']} élève(s) ont travaillé ce chapitre, sans faiblesse nette pour l’instant : "
                    'suis le programme et les erreurs classiques.')
        return 'Pas encore de résultats d’élèves sur ce chapitre : suis le programme et les erreurs classiques.'
    lignes = [f"{c['eleves']} élève(s) ont évalué des questions de ce chapitre."]
    if c['questions']:
        lignes += ['', '### Questions d’exercices les moins réussies']
        for q in c['questions']:
            extra = f", solution « pas comprise » {q['incompris']} fois" if q['incompris'] else ''
            ths = f" — théorèmes : {', '.join(q['theoremes'])}" if q['theoremes'] else ''
            lignes.append(f"- {q['contenu']}, question {q['question']} : {q['reussite']} % de réussite "
                          f"({q['eleves']} élèves{extra}){ths}\n  Énoncé : {q['enonce']}")
    if c['theoremes']:
        lignes += ['', '### Théorèmes les moins réussis']
        lignes += [f"- {t['theoreme']} : {t['reussite']} % ({t['eleves']} élèves)" for t in c['theoremes']]
    if c['quiz']:
        lignes += ['', '### Questions du quiz actuel les plus ratées']
        for q in c['quiz']:
            piege = f" ; mauvaise réponse la plus choisie : « {q['piege']} »" if q['piege'] else ''
            lignes.append(f"- « {q['question']} » (bonne réponse « {q['bonne']} ») : {q['reussite']} % de réussite "
                          f"sur {q['eleves']} passages{piege}")
    return '\n'.join(lignes)


def fiche(chapitre, niveau, c=None):
    """Fiche Markdown d'un chapitre : constats, programme, cours, questions déjà écrites (quiz_constats)."""
    c = constats(chapitre, niveau) if c is None else c
    existantes = SkillQuestion.objects.filter(chapter=chapitre).order_by('id')
    parties = [
        f'# {chapitre.name} — {niveau.name if niveau else "niveau non précisé"} (chapitre {chapitre.id})',
        '## Constats tirés des résultats des élèves\n' + _bloc_constats(c),
        '## Programme officiel du chapitre\n' + _programme(chapitre, niveau),
        '## Cours en ligne sur Fidni\n' + (cours(chapitre, niveau) or '(pas de leçon en ligne)'),
    ]
    if existantes:
        parties.append('## Questions déjà écrites pour ce chapitre\n' + '\n'.join(
            f"- {q.question} → « {_bonnes_texte(q)} »"
            f"{' (à relire)' if q.a_relire else ' (en ligne)' if q.is_active else ' (brouillon)'}"
            for q in existantes[:80]))
    return '\n\n'.join(parties)


def chapitres_en_ligne(niveau):
    """Chapitres de ce niveau qui ont au moins un contenu (exercice, leçon, examen) en ligne à ce niveau."""
    from apps.caracteristics.programme import chapitres_du_niveau
    from apps.caracteristics.models import Chapter
    return chapitres_du_niveau(niveau, Chapter.objects.filter(content_items__class_levels=niveau))


def constats_niveau(niveau):
    """Fiches de tous les chapitres en ligne d'un niveau, dans l'ordre du programme."""
    return '\n\n---\n\n'.join(fiche(ch, niveau) for ch in chapitres_en_ligne(niveau))


def _propre(s):
    return _ESPACES.sub(' ', str(s or '')).strip()


def controler(q):
    """Question du fichier → (champs SkillQuestion, None) ou (None, raison du refus).
    Une bonne réponse : {"question", "bonne", "distracteurs": [3], "explication", "difficulte", "cible",
    "theoremes": [noms exacts]}.
    Plusieurs bonnes réponses (16/10/2026) : "bonnes": [2 ou plus] au lieu de "bonne", et des "distracteurs" ;
    3 à 6 réponses en tout (typiquement 2 bonnes + 3 distracteurs). L'élève doit cocher toutes les bonnes."""
    if not isinstance(q, dict):
        return None, 'question illisible'
    question, explication = _propre(q.get('question')), _propre(q.get('explication'))
    distracteurs = [_propre(d) for d in q.get('distracteurs') or []] if isinstance(q.get('distracteurs'), list) else []
    if 'bonnes' in q:
        if 'bonne' in q:
            return None, '« bonne » ou « bonnes », pas les deux'
        bonnes = [_propre(b) for b in q['bonnes']] if isinstance(q['bonnes'], list) else []
        if not question or len(bonnes) < 2 or any(not b for b in bonnes):
            return None, 'question vide, ou « bonnes » : au moins 2 réponses non vides'
        if not distracteurs or any(not d for d in distracteurs):
            return None, 'il faut au moins 1 mauvaise réponse, non vide'
        if not 3 <= len(bonnes) + len(distracteurs) <= 6:
            return None, 'il faut de 3 à 6 réponses en tout'
    else:
        bonne = _propre(q.get('bonne'))
        bonnes = [bonne]
        if not question or not bonne:
            return None, 'question ou bonne réponse vide'
        if len(distracteurs) != 3 or any(not d for d in distracteurs):
            return None, 'il faut exactement 3 mauvaises réponses non vides'
    reponses = [*bonnes, *distracteurs]
    if len({r.casefold() for r in reponses}) != len(reponses):
        return None, 'deux réponses identiques'
    if len(question) > LONGUEURS['question'] * 2 or any(len(r) > LONGUEURS['reponse'] * 2 for r in reponses):
        return None, 'texte trop long'
    for t in (question, explication, *reponses):
        if t.replace('\\$', '').count('$') % 2:
            return None, 'formule mal fermée ($ impair)'
    if any(m in t for t in (question, *reponses) for m in ('$$', '\\(', '\\[')):
        return None, 'format de formule non accepté'
    random.shuffle(reponses)
    difficulte = q.get('difficulte') if q.get('difficulte') in DIFFICULTES else 'medium'
    justes = sorted(reponses.index(b) for b in bonnes)
    return {'question': question, 'options': reponses, 'correct_answer': justes[0],
            'correct_answers': justes if len(justes) > 1 else [],
            'difficulty': difficulte, 'explanation': explication[:2000], 'motif': _propre(q.get('cible'))[:1000]}, None


def _cle(s):
    return re.sub(r'[^0-9a-z$\\]+', '', s.casefold())


def pour_niveau(q, niveau):
    """La question telle que la voit ce niveau : `par_niveau` remplace des champs (texte, réponses, théorèmes) pour
    un niveau précis — ex. 2ème Bac PC/SVT, où « bijection » est hors programme (on dit « fonction réciproque »)."""
    if not isinstance(q, dict) or not isinstance(q.get('par_niveau'), dict):
        return q
    autre = q['par_niveau'].get(niveau)
    q = {k: v for k, v in q.items() if k != 'par_niveau'}
    if not isinstance(autre, dict):
        return q
    # Une variante peut passer d'une bonne réponse à plusieurs (ou l'inverse) : elle remplace l'autre forme.
    for forme, autre_forme in (('bonne', 'bonnes'), ('bonnes', 'bonne')):
        if forme in autre:
            q.pop(autre_forme, None)
    return {**q, **autre}


def importer(data, simulation=False):
    """{"niveau": nom | "niveaux": [noms], "chapitres": [{"chapitre": nom exact, "questions": [...]}]} → bilan par
    (chapitre, niveau).

    Un quiz = (chapitre, niveau), jamais partagé : chaque niveau listé reçoit sa propre copie des questions, sauf
    celles dont un théorème n'est pas au programme de ce niveau (Theorem.class_levels : arc tangente, Rolle, TAF
    écartés du quiz 2ème Bac PC/SVT ; `par_niveau` d'une question : sa variante pour un niveau). Questions rattachées à leurs théorèmes (au moins un, noms exacts du chapitre),
    en brouillon « à relire » — sauf si la même question (même texte) est déjà validée dans le quiz d'un autre niveau
    du chapitre : elle arrive validée, hors ligne. Une question déjà présente dans le quiz est ignorée : l'import
    peut être rejoué. `simulation` : rien n'est écrit."""
    from django.db import transaction
    from apps.caracteristics.models import Chapter, ClassLevel, Theorem
    from apps.caracteristics.programme import nom_niveau_actuel

    niveaux = []
    for nom in data.get('niveaux') or [data.get('niveau')]:
        lv = ClassLevel.objects.filter(name=nom_niveau_actuel(str(nom or ''))).first()
        if lv is None:
            raise ValueError(f'niveau inconnu : {nom!r}')
        niveaux.append(lv)
    bilan = []
    with transaction.atomic():
        for niveau in niveaux:
            for bloc in data.get('chapitres') or []:
                nom = str(bloc.get('chapitre') or '')
                ch = Chapter.objects.filter(name=nom, class_levels=niveau).first()
                ligne = {'chapitre': nom, 'niveau': niveau.name, 'creees': 0, 'ecartees': []}
                bilan.append(ligne)
                if ch is None:
                    ligne['ecartees'].append({'question': '', 'raison': 'chapitre inconnu à ce niveau'})
                    continue
                vues = {_cle(t) for t in SkillQuestion.objects.filter(chapter=ch, class_level=niveau)
                        .values_list('question', flat=True)}
                validees = {_cle(t) for t in SkillQuestion.objects.filter(chapter=ch, a_relire=False)
                            .exclude(class_level=niveau).values_list('question', flat=True)}
                du_chapitre = {th.name: th for th in
                               Theorem.objects.filter(chapters=ch).prefetch_related('class_levels').distinct()}
                for q in bloc.get('questions') or []:
                    q = pour_niveau(q, niveau.name)
                    champs, raison = controler(q)
                    noms = q.get('theoremes') if isinstance(q, dict) else None
                    if champs and _cle(champs['question']) in vues:
                        champs, raison = None, 'déjà présente'
                    elif champs and (not isinstance(noms, list) or not noms):
                        champs, raison = None, 'aucun théorème indiqué'
                    elif champs and any(n not in du_chapitre for n in noms):
                        champs, raison = None, 'théorème inconnu pour ce chapitre : ' + ', '.join(
                            str(n) for n in noms if n not in du_chapitre)
                    elif champs and any(du_chapitre[n].class_levels.all()
                                        and niveau.id not in {lv.id for lv in du_chapitre[n].class_levels.all()}
                                        for n in noms):
                        champs, raison = None, f'hors programme en {niveau.name} : ' + ', '.join(
                            n for n in noms if du_chapitre[n].class_levels.all()
                            and niveau.id not in {lv.id for lv in du_chapitre[n].class_levels.all()})
                    if not champs:
                        ligne['ecartees'].append({'question': _propre((q or {}).get('question') if isinstance(q, dict)
                                                                      else '')[:120], 'raison': raison})
                        continue
                    cle = _cle(champs['question'])
                    vues.add(cle)
                    if not simulation:
                        nouvelle = SkillQuestion.objects.create(chapter=ch, class_level=niveau, is_active=False,
                                                                a_relire=cle not in validees, source='claude', **champs)
                        nouvelle.theorems.set([du_chapitre[n] for n in noms])
                    ligne['creees'] += 1
    return bilan
