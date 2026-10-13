"""« Ma progression », la maîtrise d'abord (13/10/2026) : indicateurs par chapitre, aperçu, régularité.

Trois questions pour l'élève : où en suis-je, est-ce que je progresse, que dois-je faire maintenant (objectif.py).
Règle : ne jamais afficher une précision qu'on n'a pas. Chaque état vient avec sa raison et la liste des critères
observés (`criteres`) ; une estimation fragile est dite fragile ; l'absence de données n'est jamais un jugement.

Données :
- état courant : QuestionProgress (dernier statut de chaque question) → réussite, par difficulté ;
- journal : AssessmentEvent (apps/interactions/journal.py) → résultats récents, tendance, maîtrise durable,
  autonomie. Une évaluation que le journal ne reflète pas (écrite avant lui, ou par un autre chemin) y est ajoutée
  comme « reprise » (aide inconnue).
Ce qui sert à quoi : toutes les évaluations comptent dans les résultats ; seules celles dont l'aide est connue comptent
pour l'autonomie ; seule une réussite SANS aide enregistrée, sur une question différente, au moins 3 jours après une
réussite, confirme une maîtrise durable (une aide inconnue n'est pas une absence d'aide).

États (etat_du_chapitre, dans cet ordre) : pas encore évalué → n'a pas tenu à la vérification (à consolider) →
durablement faible (à renforcer ; en bonne voie « en progrès » si les résultats récents sont bons) → tous les critères
de couverture (maîtrisé) → au moins 60 % ou en hausse (en bonne voie) → sinon à consolider (réussite partielle).
Seuils : maitrise_seuils.py. Cache : 10 min par élève (evaluer, forget).
"""
from collections import Counter, defaultdict
from datetime import timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone

from apps.caracteristics.models import Chapter
from apps.caracteristics.notions import notion_label
from apps.caracteristics.programme import chapitres_du_niveau
from apps.interactions.models import QuestionHelp
from apps.things.models import Content
from apps.things.question_index import question_full
from apps.users import maitrise_seuils as S
from apps.users.my_stats import WEIGHT
from apps.users.overview_views import _streaks
from apps.users.progression import (NOTION_CHAPTER, _chapter_entries, _collect, _local, _pct, _per_chapter,
                                    _question_chapters, _same_chapter)

CACHE_TTL = 600
VERSION = 'v1'
RANG = {'easy': 0, 'medium': 1, 'hard': 2}
NIVEAU_LABEL = {'easy': 'facile', 'medium': 'moyen', 'hard': 'difficile'}
ETATS = ('maitrise', 'bonne_voie', 'a_consolider', 'a_renforcer', 'non_evalue')


def _cle(user_id):
    return f'maitrise:{VERSION}:{user_id}'


def forget(user_id):
    """Après une évaluation, un « Réussi », un quiz, un DS annoncé… : recalcul à la prochaine visite."""
    cache.delete(_cle(user_id))


def _jm(d):
    return f'{d.day:02d}/{d.month:02d}' if d else ''


def _plural(n, one, many=None):
    return f'{n} {one if n == 1 else (many or one + "s")}'


# ── État d'un chapitre (fonction pure, testée sur une table de cas) ─────────────────────────────────────────────

def criteres_maitrise(s):
    """Critères de « Maîtrisé », observés : [{cle, etat: ok | a_faire | en_attente, texte}]."""
    out = []

    def add(cle, etat, texte):
        out.append({'cle': cle, 'etat': etat, 'texte': texte})

    if s.n >= S.MIN_QUESTIONS_MAITRISE and s.self_pct is not None and s.self_pct >= S.SEUIL_MAITRISE:
        add('resultats', 'ok', f'{s.self_pct} % de réussite sur {_plural(s.n, "question")}')
    elif s.n < S.MIN_QUESTIONS_MAITRISE:
        add('resultats', 'a_faire', f'Au moins {S.MIN_QUESTIONS_MAITRISE} questions évaluées et {S.SEUIL_MAITRISE} % '
                                    f'de réussite (tu en as {s.n})')
    else:
        add('resultats', 'a_faire', f'Au moins {S.SEUIL_MAITRISE} % de réussite ({s.self_pct} % sur '
                                    f'{_plural(s.n, "question")} pour l’instant)')

    if s.exercices_reussis >= S.MIN_EXERCICES_MAITRISE:
        add('exercices', 'ok', f'{s.exercices_reussis} exercices différents réussis')
    else:
        add('exercices', 'a_faire', f'Réussis au moins {S.MIN_EXERCICES_MAITRISE} exercices différents '
                                    f'({s.exercices_reussis} pour l’instant)')

    niveaux = [n for n in ('easy', 'medium', 'hard') if n in s.niveaux_reussis]
    if len(niveaux) >= 2 and ('medium' in niveaux or 'hard' in niveaux):
        add('difficultes', 'ok', 'Réussi en ' + ' et en '.join(NIVEAU_LABEL[n] for n in niveaux))
    elif not niveaux:
        add('difficultes', 'a_faire', 'Réussis des questions à deux niveaux de difficulté, dont un moyen ou difficile')
    elif 'medium' not in niveaux and 'hard' not in niveaux:
        add('difficultes', 'a_faire', 'Réussis aussi un exercice moyen ou difficile (seulement facile pour l’instant)')
    else:
        add('difficultes', 'a_faire', f'Réussis à un deuxième niveau de difficulté (seulement '
                                      f'{NIVEAU_LABEL[niveaux[0]]} pour l’instant)')

    if s.synthese:
        add('synthese', 'ok', 'Un exercice de synthèse réussi (question difficile, ou exercice de DS ou du Bac)')
    else:
        add('synthese', 'a_faire', 'Réussis un exercice de synthèse, où tu choisis toi-même la méthode : '
                                   'une question difficile, ou un exercice de DS ou du Bac')

    exigees = min(S.MAX_NOTIONS_EXIGEES, s.notions_dispo)
    if exigees == 0 or s.notions_reussies >= exigees:
        add('notions', 'ok', f'{_plural(s.notions_reussies, "notion")} du chapitre réussie{"s" if s.notions_reussies > 1 else ""}'
            if s.notions_reussies else 'Notions du chapitre : rien de plus à couvrir')
    else:
        reste = (' : ' + ', '.join(s.notions_manquantes[:3])) if s.notions_manquantes else ''
        add('notions', 'a_faire', f'Réussis des questions sur {exigees} notions différentes '
                                  f'({s.notions_reussies} pour l’instant){reste}')

    d = s.durable
    if d['etat'] == 'confirmee':
        add('durable', 'ok', f'Revérifié sans aide le {_jm(d["le"])}, sur d’autres questions')
    elif d['etat'] == 'n_a_pas_tenu':
        add('durable', 'a_faire', f'Lors de la vérification du {_jm(d["le"])}, ça n’a pas tenu : à retravailler')
    elif d['etat'] == 'a_verifier':
        if d['due']:
            add('durable', 'en_attente', 'À revérifier maintenant, sans aide, sur d’autres questions')
        else:
            add('durable', 'en_attente', f'À revérifier sans aide sur d’autres questions à partir du {_jm(d["a_partir_du"])}')
    else:
        add('durable', 'a_faire', 'Réussis d’abord quelques questions, puis revérifie quelques jours plus tard')

    a = s.autonomie
    if a['pct'] is not None:
        if a['pct'] >= S.AUTONOMIE_SUFFISANTE:
            add('autonomie', 'ok', f'{a["pct"]} % de tes réussites sans indice ni solution')
        else:
            add('autonomie', 'a_faire', f'Réussis plus souvent sans indice ni solution ({a["pct"]} % pour l’instant)')
    elif d['etat'] == 'confirmee':
        add('autonomie', 'ok', 'Réussi sans aide lors de la vérification')
    else:
        add('autonomie', 'en_attente', f'Pas encore assez de recul sur l’autonomie ({a["suivies"]}/{S.MIN_AUTONOMIE} '
                                       'réussites suivies)')
    return out


def etat_du_chapitre(s):
    """(etat, raison, criteres, en_progres, a_confirmer). `s` : SimpleNamespace (voir _stats_chapitre)."""
    criteres = criteres_maitrise(s)
    manque = next((c for c in criteres if c['etat'] != 'ok'), None)
    pct, n = s.pct, s.n
    if n < S.MIN_QUESTIONS and s.quiz_pct is None:
        raison = ('Pas encore commencé.' if n == 0 else
                  f'Pas encore assez de questions évaluées ({n}/{S.MIN_QUESTIONS}) pour établir ton point de départ.')
        return 'non_evalue', raison, criteres, False, False
    if s.durable['etat'] == 'n_a_pas_tenu':
        return ('a_consolider', f'Tu l’avais réussi, mais pas lors de la vérification du {_jm(s.durable["le"])} : '
                'les acquis ne sont pas encore stables.', criteres, False, False)
    recents_bons = s.recents_pct is not None and s.recents_pct >= S.SEUIL_BONNE_VOIE
    if pct is not None and pct < S.SEUIL_RENFORCER:
        if recents_bons:
            return ('bonne_voie', f'En progrès : {pct} % en tout, {s.recents_pct} % sur tes '
                    f'{s.recents_n} dernières questions.', criteres, True, False)
        return ('a_renforcer', f'{pct} % de réussite sur {_plural(n, "question")} : reprends les bases avant de '
                'continuer.', criteres, False, False)
    if manque is None:
        return ('maitrise', f'Tous les critères sont remplis, maîtrise confirmée le {_jm(s.durable["le"])}.',
                criteres, False, False)
    hausse = s.tendance is not None and s.tendance >= S.HAUSSE_MIN
    if (pct is not None and pct >= S.SEUIL_BONNE_VOIE) or hausse or recents_bons:
        en_progres = hausse or (recents_bons and (pct is None or pct < S.SEUIL_BONNE_VOIE))
        prefixe = f'En hausse (+{s.tendance} pts en 30 jours). ' if hausse else ''
        return ('bonne_voie', f'{prefixe}Pour passer « Maîtrisé » : {manque["texte"][0].lower()}{manque["texte"][1:]}.',
                criteres, en_progres, pct is not None and pct >= S.SEUIL_MAITRISE)
    return ('a_consolider', f'Réussite partielle ({pct} % sur {_plural(n, "question")}) : revois la méthode et refais '
            'des exercices ciblés.', criteres, False, False)


# ── Données ────────────────────────────────────────────────────────────────────────────────────────────────────

def _notions_dispo(level):
    """{chapter_id: {notion: [content ids]}} des exercices et examens (du niveau), en cache 6 h. Sert au critère
    « notions couvertes » et aux exercices ciblés sur une notion pas encore réussie (objectif.py)."""
    qs = Content.objects.filter(type__in=('exercise', 'exam'))
    if level:
        qs = qs.filter(class_levels=level)
    # Un contenu publié ou modifié change la clé : jamais de liste périmée.
    stamp = qs.aggregate(n=Count('id'), m=Max('updated_at'))
    key = f'maitrise:notions:{level.id if level else "tous"}:{stamp["n"]}:{stamp["m"].isoformat() if stamp["m"] else "-"}'
    hit = cache.get(key)
    if hit is not None:
        return hit
    contents = list(qs.only('id', 'updated_at').prefetch_related('chapters').distinct())
    full = question_full(contents)
    out = defaultdict(lambda: defaultdict(set))
    for c in contents:
        chapters = [(ch.id, ch.name) for ch in c.chapters.all()]
        for _path, _pts, skills, _lvl in full.get(c.id, []):
            for sk in skills:
                home = NOTION_CHAPTER.get(sk)
                if not home:
                    continue
                for ch_id, name in chapters:
                    if _same_chapter(name, home):
                        out[ch_id][sk].add(c.id)
    data = {ch: {sk: sorted(ids) for sk, ids in notions.items()} for ch, notions in out.items()}
    cache.set(key, data, 6 * 3600)
    return data


def _evenements(d):
    """Journal effectif, trié : (at, cid, path, statut | None, aide, reprise). Les évaluations courantes que le
    journal ne reflète pas y sont ajoutées comme « reprises » (aide inconnue), à leur date."""
    events = [(at, cid, path, st, aide, reprise) for cid, path, st, aide, reprise, at in d.events]
    last = {}
    for at, cid, path, st, _a, _r in events:
        last[(cid, path)] = st
    for r in d.qp:
        key = (r['object_id'], r['question_path'])
        if last.get(key, '∅') != r['status']:
            events.append((r['assessed_at'], key[0], key[1], r['status'], None, True))
    events.sort(key=lambda e: e[0])
    return events


def _etats_aux_dates(events, dates):
    """{date: {(cid, path): statut}} : état des questions à la fin de chaque date (un seul passage)."""
    out, state, i = {}, {}, 0
    for day in sorted(dates):
        while i < len(events) and _local(events[i][0]) <= day:
            _at, cid, path, st, _a, _r = events[i]
            if st is None:
                state.pop((cid, path), None)
            else:
                state[(cid, path)] = st
            i += 1
        out[day] = dict(state)
    return out


def calculer(user, level, d, today):
    """Tous les indicateurs (sans cache). `d` : progression._collect(user, journal=True)."""
    programme = chapitres_du_niveau(level, Chapter.objects.select_related('subfield')) if level else None
    allowed = {ch.id for ch in programme} if programme is not None else None
    chap, _ = _per_chapter(d, allowed)
    chapter_list = programme if programme is not None else list(
        Chapter.objects.filter(id__in=set(chap) | set(d.quizzes)).select_related('subfield').order_by('subfield__name', 'name'))
    entries = _chapter_entries(chapter_list, chap, d.quizzes, level)
    ids = {c['id'] for c in entries}
    ordre = {c['id']: i for i, c in enumerate(entries)}

    routes = {}

    def route(cid, path):
        key = (cid, path)
        if key not in routes:
            skills = d.skills_of.get(cid, {}).get(path, [])
            routes[key] = [ch for ch in _question_chapters(d.chapters_of.get(cid, []), skills, allowed) if ch in ids]
        return routes[key]

    def niveau(cid, path):
        lvl = d.levels_of.get(cid, {}).get(path)
        if lvl in RANG:
            return lvl
        c = d.contents.get(cid)
        return c.difficulty if c is not None and c.difficulty in RANG else None

    def est_examen(cid):
        c = d.contents.get(cid)
        return c is not None and c.type == 'exam'

    # État courant, par chapitre.
    cur = defaultdict(list)
    for r in d.qp:
        for ch in route(r['object_id'], r['question_path']):
            cur[ch].append((r['object_id'], r['question_path'], r['status'], niveau(r['object_id'], r['question_path'])))

    # Journal effectif, par chapitre.
    events = _evenements(d)
    par_chap = defaultdict(list)
    for e in events:
        for ch in route(e[1], e[2]):
            par_chap[ch].append(e)

    j30 = today - timedelta(days=S.EVOLUTION_JOURS)
    checkpoints = [today - timedelta(days=7 * k) for k in range(S.SERIE_SEMAINES - 1, -1, -1)]
    snaps = _etats_aux_dates(events, set(checkpoints) | {j30})

    def pcts_a(state):
        acc = defaultdict(lambda: [0, 0.0])
        for (cid, path), st in state.items():
            for ch in route(cid, path):
                acc[ch][0] += 1
                acc[ch][1] += WEIGHT.get(st, 0)
        return {ch: _pct(sc, n) for ch, (n, sc) in acc.items() if n >= S.MIN_QUESTIONS}

    avant = pcts_a(snaps[j30])
    dispo = _notions_dispo(level)
    chapters = []
    for e in entries:
        st = _stats_chapitre(e, cur.get(e['id'], []), par_chap.get(e['id'], []), d, today, avant, dispo, niveau,
                             est_examen, chap.get(e['id'], {}).get('done', ()))
        etat, raison, criteres, en_progres, a_confirmer = etat_du_chapitre(st)
        chapters.append({
            **e,
            'etat': etat, 'raison': raison, 'criteres': criteres, 'en_progres': en_progres, 'a_confirmer': a_confirmer,
            'pct': st.pct,
            'reussite': {'pct': st.self_pct, 'questions': st.n, 'par_difficulte': st.par_difficulte},
            'recents': {'pct': st.recents_pct, 'questions': st.recents_n} if st.recents_pct is not None else None,
            'tendance': st.tendance,
            'durable': {**st.durable, 'le': _iso(st.durable['le']), 'a_partir_du': _iso(st.durable['a_partir_du'])},
            'autonomie': {'seul': st.autonomie, 'transfert': st.transfert},
            'exercices_evalues': st.exercices_evalues,
            'exercices_reussis': st.exercices_reussis,
            'travailles': st.travailles,
            'derniere_evaluation': _iso(st.derniere),
            'notions_couvertes': {'reussies': st.notions_reussies, 'dispo': st.notions_dispo,
                                  'manquantes': st.notions_manquantes_slugs},
            'commence': st.commence,
            'ordre': ordre[e['id']],
        })

    apercu = _apercu(chapters, events, snaps, checkpoints, j30, today, pcts_a, niveau, route)
    return {
        'level': {'id': level.id, 'name': level.name} if level else None,
        'chapters': chapters,
        'apercu': apercu,
        'regularite': _regularite(user, d, events, today),
    }


def _iso(d):
    return d.isoformat() if d else None


def _stats_chapitre(entry, rows, evs, d, today, avant, dispo, niveau, est_examen, done_ids=()):
    ch_id, name = entry['id'], entry['name']
    n = len(rows)
    score = sum(WEIGHT.get(st, 0) for _c, _p, st, _l in rows)
    self_pct = _pct(score, n) if n >= S.MIN_QUESTIONS else None
    quiz = d.quizzes.get(ch_id)
    quiz_pct = _pct(quiz.score, quiz.max_score) if quiz and quiz.max_score else None
    if self_pct is not None and quiz_pct is not None:
        pct = round(S.SELF_WEIGHT * self_pct + (1 - S.SELF_WEIGHT) * quiz_pct)
    else:
        pct = self_pct if self_pct is not None else quiz_pct

    par_lvl = defaultdict(lambda: [0, 0.0])
    par_cid = defaultdict(lambda: [0, 0.0, False])
    niveaux_reussis, synthese, notions_ok = set(), False, set()
    for cid, path, st, lvl in rows:
        if lvl:
            par_lvl[lvl][0] += 1
            par_lvl[lvl][1] += WEIGHT.get(st, 0)
        pc = par_cid[cid]
        pc[0] += 1
        pc[1] += WEIGHT.get(st, 0)
        if st == 'success':
            pc[2] = True
            if lvl:
                niveaux_reussis.add(lvl)
            if lvl == 'hard' or est_examen(cid):
                synthese = True
            for sk in d.skills_of.get(cid, {}).get(path, []):
                home = NOTION_CHAPTER.get(sk)
                if home and _same_chapter(name, home):
                    notions_ok.add(sk)
    par_difficulte = {lvl: {'questions': par_lvl[lvl][0], 'pct': _pct(par_lvl[lvl][1], par_lvl[lvl][0])}
                      for lvl in ('easy', 'medium', 'hard') if par_lvl[lvl][0]}
    exercices_reussis = sum(1 for nq, sc, ok in par_cid.values() if ok and sc * 100 >= S.EXERCICE_REUSSI * nq)

    # Notions présentes dans les exercices du chapitre, et celles pas encore réussies.
    chap_notions = dispo.get(ch_id, {})
    manquantes = sorted((sk for sk in chap_notions if sk not in notions_ok), key=lambda sk: -len(chap_notions[sk]))

    # Résultats récents : les 10 dernières questions évaluées des 30 derniers jours.
    depuis = today - timedelta(days=S.RECENTS_JOURS)
    recents = [e for e in evs if e[3] is not None and _local(e[0]) > depuis][-S.RECENTS_N:]
    recents_pct = (_pct(sum(WEIGHT.get(e[3], 0) for e in recents), len(recents))
                   if len(recents) >= S.RECENTS_MIN else None)

    tendance = self_pct - avant[ch_id] if self_pct is not None and ch_id in avant else None

    return SimpleNamespace(
        n=n, self_pct=self_pct, quiz_pct=quiz_pct, pct=pct, par_difficulte=par_difficulte,
        exercices_evalues=len(par_cid), exercices_reussis=exercices_reussis,
        travailles=len(set(par_cid) | set(done_ids)),  # parcours : contenus évalués ou réussis
        niveaux_reussis=niveaux_reussis, synthese=synthese,
        notions_reussies=len(notions_ok), notions_dispo=len(chap_notions),
        notions_manquantes=[notion_label(sk) for sk in manquantes], notions_manquantes_slugs=manquantes[:5],
        recents_pct=recents_pct, recents_n=len(recents), tendance=tendance,
        durable=_durable(evs, niveau, today), autonomie=_autonomie(evs), transfert=_transfert(evs),
        derniere=max((_local(e[0]) for e in evs if e[3] is not None), default=None),
        commence=bool(n or entry.get('seconds') or entry.get('done') or entry.get('skilliq')),
    )


def _durable(evs, niveau, today):
    """Maîtrise durable : confirmée (réussite sans aide enregistrée, sur une question différente, au moins 3 jours
    après une réussite), n'a pas tenu (échec au moins 3 jours après une réussite, même question ou difficulté égale
    ou plus facile), à vérifier, ou inconnue."""
    delai = timedelta(days=S.DELAI_DURABLE_JOURS)
    succes, reussies, check, premier = [], set(), None, None
    for at, cid, path, st, aide, _reprise in evs:
        day, key = _local(at), (cid, path)
        lvl = niveau(cid, path)
        if st == 'success':
            if aide == '' and key not in reussies and any(day - d0 >= delai for d0, _k, _l in succes):
                check = ('confirmee', day)
            succes.append((day, key, lvl))
            reussies.add(key)
            premier = premier or day
        elif st in ('review', 'failed'):
            r = RANG.get(lvl, 1)
            if any(day - d0 >= delai and (k == key or r <= RANG.get(l0, 1)) for d0, k, l0 in succes):
                check = ('n_a_pas_tenu', day)
    if check:
        return {'etat': check[0], 'le': check[1], 'a_partir_du': None, 'due': False}
    if premier:
        a_partir = premier + delai
        return {'etat': 'a_verifier', 'le': None, 'a_partir_du': a_partir, 'due': a_partir <= today}
    return {'etat': 'inconnue', 'le': None, 'a_partir_du': None, 'due': False}


def _autonomie(evs):
    """« Je sais résoudre seul » : part des réussites sans aide parmi celles dont l'aide est connue."""
    suivies = [aide for _at, _c, _p, st, aide, _r in evs if st in ('success', 'partial') and aide is not None]
    sans = sum(1 for a in suivies if a == '')
    return {'pct': _pct(sans, len(suivies)) if len(suivies) >= S.MIN_AUTONOMIE else None,
            'suivies': len(suivies), 'sans_aide': sans, 'min': S.MIN_AUTONOMIE}


def _transfert(evs):
    """« Je m'en passe de plus en plus » : après une question faite avec une aide, la question suivante (différente,
    même chapitre, dans les 14 jours, aide connue) est-elle réussie sans aide ?"""
    essais = reussis = 0
    fenetre = timedelta(days=S.TRANSFERT_JOURS)
    for i, (at, cid, path, st, aide, _r) in enumerate(evs):
        if st is None or aide not in ('indice', 'solution'):
            continue
        suivante = next((e for e in evs[i + 1:] if e[3] is not None and (e[1], e[2]) != (cid, path)), None)
        if suivante is None or suivante[0] - at > fenetre or suivante[4] is None:
            continue
        essais += 1
        reussis += suivante[3] == 'success' and suivante[4] == ''
    return {'reussis': reussis, 'essais': essais, 'min': S.MIN_TRANSFERT, 'visible': essais >= S.MIN_TRANSFERT}


def _apercu(chapters, events, snaps, checkpoints, j30, today, pcts_a, niveau, route):
    evalues = [c for c in chapters if c['etat'] != 'non_evalue']
    known = [c['pct'] for c in evalues if c['pct'] is not None]
    etats = Counter(c['etat'] for c in chapters)
    ids = {c['id'] for c in chapters}
    names = {c['id']: c['name'] for c in chapters}

    # Évolution sur 30 jours : seulement les chapitres évalués aux deux dates (auto-évaluation, comparable).
    maintenant = {c['id']: c['reussite']['pct'] for c in chapters if c['reussite']['pct'] is not None}
    avant = {ch: p for ch, p in pcts_a(snaps[j30]).items() if ch in ids}
    communs = sorted(set(maintenant) & set(avant), key=lambda ch: names[ch])
    periode = [e for e in events if e[3] is not None and _local(e[0]) > j30]
    jours = [_local(e[0]) for e in events if e[3] is not None]
    premier = min(jours) if jours else None
    journal_debut = min((_local(e[0]) for e in events if not e[5]), default=None)
    mesurable = len(communs) >= S.MIN_CHAPITRES_COMPARES and len(periode) >= S.MIN_QUESTIONS_PERIODE
    evolution = {
        'delta': round(sum(maintenant[c] for c in communs) / len(communs) - sum(avant[c] for c in communs) / len(communs))
        if mesurable else None,
        'mesurable': mesurable,
        'chapitres_compares': len(communs),
        'chapitres_exclus': sorted(names[c] for c in maintenant if c not in avant),
        'questions_periode': len(periode),
        'disponible_le': _iso(premier + timedelta(days=S.EVOLUTION_JOURS))
        if premier and (today - premier).days < S.EVOLUTION_JOURS else None,
        'detail': [{'id': c, 'name': names[c], 'avant': avant[c], 'maintenant': maintenant[c]} for c in communs],
        'mises_en_garde': [],
    }
    if mesurable:
        gains = {c: maintenant[c] - avant[c] for c in communs}
        positifs = {c: g for c, g in gains.items() if g > 0}
        if evolution['delta'] > 0 and positifs and len(communs) >= 2:
            top = max(positifs, key=positifs.get)
            if positifs[top] * 100 >= S.CONCENTRE * sum(positifs.values()):
                evolution['mises_en_garde'].append({'cle': 'concentre', 'texte': f'Surtout grâce à « {names[top]} ».'})
        lvls = [niveau(e[1], e[2]) for e in periode if e[3] == 'success']
        lvls = [lv for lv in lvls if lv]
        if len(lvls) >= 5 and sum(1 for lv in lvls if lv == 'easy') * 100 >= S.SURTOUT_FACILE * len(lvls):
            evolution['mises_en_garde'].append({'cle': 'surtout_facile', 'texte': 'Progrès surtout sur des exercices '
                                                'faciles : essaie des exercices moyens pour le confirmer.'})
        if any(e[5] and _local(e[0]) <= j30 for e in events) and (journal_debut is None or journal_debut > j30):
            evolution['mises_en_garde'].append({'cle': 'estimee', 'texte': 'Estimation : avant le 13/10/2026, Fidni ne '
                                                'gardait que la dernière évaluation de chaque question.'})

    serie = []
    for day in checkpoints:
        vals = [p for ch, p in pcts_a(snaps[day]).items() if ch in ids]
        serie.append({'date': day.isoformat(), 'pct': round(sum(vals) / len(vals)) if vals else None})

    return {
        'chapitres': {'evalues': len(evalues), 'total': len(chapters)},
        'maitrise': round(sum(known) / len(known)) if known else None,
        'etats': {e: etats.get(e, 0) for e in ETATS},
        'evolution': evolution,
        'serie': serie,
        'commence': bool(events),
    }


def _regularite(user, d, events, today):
    """Activité des 28 derniers jours (au second plan : le temps montre l'activité, pas l'apprentissage)."""
    debut = today - timedelta(days=S.REGULARITE_JOURS - 1)
    secondes = Counter()
    for r in d.time_rows:
        secondes[r['date']] += r['seconds']
    evals = Counter(_local(e[0]) for e in events if e[3] is not None)
    aides = set(QuestionHelp.objects.filter(user=user, day__gte=debut).values_list('day', flat=True))
    actifs_tous = ({day for day, s in secondes.items() if s >= S.ACTIF_MIN_SECONDES} | set(evals) | aides
                   | {_local(q.completed_at) for q in d.quizzes.values()})
    jours = []
    for i in range(S.REGULARITE_JOURS - 1, -1, -1):
        day = today - timedelta(days=i)
        jours.append({'date': day.isoformat(), 'secondes': secondes[day], 'evaluations': evals[day],
                      'actif': day in actifs_tous})
    semaine = sum(secondes[today - timedelta(days=i)] for i in range(7))
    precedente = sum(secondes[today - timedelta(days=i)] for i in range(7, 14))
    finis = sum(1 for r in d.completes if r['status'] == 'success' and _local(r['updated_at']) > today - timedelta(days=7)
                and d.contents.get(r['object_id']) is not None and d.contents[r['object_id']].type in ('exercise', 'exam'))
    current, best = _streaks(actifs_tous, today)
    return {
        'jours': jours, 'jours_actifs': sum(1 for j in jours if j['actif']), 'sur': S.REGULARITE_JOURS,
        'semaine_secondes': semaine, 'semaine_precedente': precedente,
        'exercices_finis_semaine': finis, 'serie': {'actuelle': current, 'meilleure': best},
    }


def evaluer(user, level=None, d=None):
    """Indicateurs de l'élève, en cache 10 min (recalculés si le jour ou le niveau change, ou après forget)."""
    today = timezone.localdate()
    lid = level.id if level else None
    hit = cache.get(_cle(user.id))
    if hit and hit.get('day') == today.isoformat() and hit.get('level') == lid:
        return hit['data']
    from apps.users import objectif
    data = calculer(user, level, d or _collect(user, journal=True), today)
    data['objectif'] = objectif.choisir(user, data['chapters'], level, today)
    cache.set(_cle(user.id), {'day': today.isoformat(), 'level': lid, 'data': data}, CACHE_TTL)
    return data
