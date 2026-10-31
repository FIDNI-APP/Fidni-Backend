"""« Ma progression » en tableau de bord (13/10/2026) : des faits datés, sans indicateur abstrait.

GET /api/stats/tableau/?jours=7|30|90|0 (0 = depuis le début) :
- kpis : questions réussies / en partie / ratées, note moyenne aux examens (/20), temps, jours actifs ; chacun avec la
  période précédente de même longueur (`avant`, sauf « depuis le début ») ;
- jours : par jour (par semaine au-delà de 120 jours), questions réussies / en partie / ratées et temps ;
- notes : les examens notés de la période ;
- chapitres : ceux du programme du niveau (ordre d'enseignement) — note aux examens (moyenne, min, max, série dans le
  temps), questions, temps ;
- temps : chapitre › contenu › jours.
GET /api/stats/tableau/jour/?date=AAAA-MM-JJ : ce que l'élève a fait ce jour-là, contenu par contenu.

Règles :
- une question compte une fois par jour, avec son dernier statut du jour (une évaluation retirée ne compte pas) ;
- note d'un examen = barème des questions corrigées × (réussie 1, en partie ½, à revoir 0), ramené sur 20, dès que la
  moitié du barème est corrigée (comme « Ta copie ») ; refait plus de 3 jours après : une nouvelle note ;
- note d'un chapitre dans un examen = ses questions seulement (rattachées par leurs théorèmes, progression.
  _question_chapters), dès que la moitié de leur barème est corrigée ;
- temps d'un contenu partagé à parts égales entre ses chapitres (du niveau d'abord) : rien n'est compté deux fois ;
- points faibles (13/10/2026, à la demande : l'élève voit maintenant ses théorèmes) : par théorème des questions de la
  période, réussies / en partie / à revoir, et les questions encore à revoir aujourd'hui (dernier statut), pour savoir
  quoi refaire ; les moins réussis d'abord.
"""
from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics import theoremes as TH
from apps.caracteristics.hubs import hub_url
from apps.caracteristics.programme import chapitres_du_niveau
from apps.skilliq.models import COURS, SkillQuestion
from apps.users.my_stats import WEIGHT
from apps.users.progression import TYPE_PATH, _collect, _local, _question_chapters, eleve_vise

PERIODES = (7, 30, 90, 0)
POINTS_FAIBLES = 12         # théorèmes renvoyés au plus
A_REFAIRE = 6               # questions à refaire montrées par théorème
SEMAINES_APRES = 120        # au-delà, « jours » est regroupé par semaine
NOUVELLE_COPIE_JOURS = 3    # un examen refait plus tard que ça : une nouvelle note


def _cle(status):
    return 'reussies' if status == 'success' else 'partielles' if status == 'partial' else 'ratees'


def _url(c):
    return f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}'


def _note(rows, state):
    """Note /20 de questions [(chemin, points)] d'après leur statut, si la moitié du barème au moins est corrigée."""
    total = sum(p for _, p in rows)
    corrige = sum(p for path, p in rows if state.get(path))
    if not total or not corrige or corrige < total / 2:
        return None
    got = sum(p * WEIGHT.get(state[path], 0) for path, p in rows if state.get(path))
    return round(got / corrige * 20, 1)


def _donnees(user):
    """Ce que le tableau lit : journal des évaluations, temps, contenus, chapitres du niveau."""
    d = _collect(user, journal=True)
    level = getattr(getattr(user, 'profile', None), 'class_level', None)
    programme = chapitres_du_niveau(level) if level else []
    allowed = {ch.id for ch in programme} if level else None
    # Dernier statut de chaque question, jour par jour.
    du_jour = {}
    for cid, path, status, _aide, _reprise, at in d.events:
        du_jour[(_local(at), cid, path)] = status
    return d, level, programme, allowed, du_jour


def _chapitres_question(d, allowed, cid, path):
    return _question_chapters(d.chapters_of.get(cid, []), d.theoremes_of.get(cid, {}).get(path, []), allowed)


def _notes_examens(d, allowed):
    """Notes des examens dans le temps : [(date, id, note, {chapitre: note})], copies successives d'un même examen
    séparées de plus de 3 jours."""
    par_examen = defaultdict(list)
    for cid, path, status, _aide, _reprise, at in d.events:
        c = d.contents.get(cid)
        if c is not None and c.type == 'exam':
            par_examen[cid].append((_local(at), path, status))
    out = []
    for cid, evts in par_examen.items():
        rows = [(path, pts) for path, pts, _ in d.index.get(cid, [])]
        if not rows:
            continue
        if not any(p for _, p in rows):
            rows = [(path, 1.0) for path, _ in rows]  # examen sans barème : chaque question compte autant
        # Questions de chaque chapitre de l'examen (par leurs théorèmes).
        par_chapitre = defaultdict(list)
        for path, pts in rows:
            for ch in _chapitres_question(d, allowed, cid, path):
                par_chapitre[ch].append((path, pts))
        state, points = {}, []
        evts.sort(key=lambda e: e[0])
        for i, (day, path, status) in enumerate(evts):
            if status:
                state[path] = status
            else:
                state.pop(path, None)
            if i + 1 < len(evts) and evts[i + 1][0] == day:
                continue  # la note du jour : après sa dernière évaluation
            note = _note(rows, state)
            if note is None:
                continue
            chapitres = {ch: n for ch, qs in par_chapitre.items() if (n := _note(qs, state)) is not None}
            point = (day, cid, note, chapitres)
            if points and (day - points[-1][0]).days <= NOUVELLE_COPIE_JOURS:
                points[-1] = point  # même copie, corrigée sur plusieurs jours
            else:
                points.append(point)
        out += points
    out.sort(key=lambda p: (p[0], p[1]))
    return out


def _partage(d, allowed, cid):
    """Chapitres d'un contenu pour le temps : ceux du niveau d'abord, sinon tous (aucun : « Autres »)."""
    chs = [ch for ch, _ in d.chapters_of.get(cid, [])]
    mine = [ch for ch in chs if allowed is None or ch in allowed]
    return mine or chs


def _bornes(jours, d, du_jour, today):
    if jours:
        return today - timedelta(days=jours - 1), today
    dates = [k[0] for k in du_jour] + [r['date'] for r in d.time_rows]
    return (min(dates) if dates else today), today


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tableau(request):
    try:
        jours = int(request.query_params.get('jours', 30))
    except (TypeError, ValueError):
        jours = -1
    if jours not in PERIODES:
        return Response({'error': 'jours : 7, 30, 90 ou 0 (depuis le début).'}, status=400)
    user, erreur = eleve_vise(request)
    if erreur:
        return erreur
    today = timezone.localdate()
    d, level, programme, allowed, du_jour = _donnees(user)
    debut, fin = _bornes(jours, d, du_jour, today)
    avant = (debut - timedelta(days=jours), debut - timedelta(days=1)) if jours else None

    def dans(day, borne=(debut, fin)):
        return borne is not None and borne[0] <= day <= borne[1]

    # ── Questions et temps, jour par jour
    par_jour = defaultdict(lambda: {'reussies': 0, 'partielles': 0, 'ratees': 0, 'secondes': 0})
    q_avant = {'reussies': 0, 'partielles': 0, 'ratees': 0}
    q_chap = defaultdict(lambda: {'reussies': 0, 'partielles': 0, 'ratees': 0})
    q_chap_jour = defaultdict(lambda: defaultdict(lambda: {'reussies': 0, 'partielles': 0, 'ratees': 0}))
    for (day, cid, path), status in du_jour.items():
        if not status:
            continue
        if dans(day):
            par_jour[day][_cle(status)] += 1
            for ch in _chapitres_question(d, allowed, cid, path):
                q_chap[ch][_cle(status)] += 1
                q_chap_jour[ch][day][_cle(status)] += 1
        elif dans(day, avant):
            q_avant[_cle(status)] += 1
    secondes_avant, actifs_avant = 0, set()
    temps_chap = defaultdict(lambda: defaultdict(lambda: {'secondes': 0, 'jours': defaultdict(int), 'partage': 1}))
    for r in d.time_rows:
        day, cid, s = r['date'], r['object_id'], r['seconds']
        if dans(day):
            par_jour[day]['secondes'] += s
            chs = _partage(d, allowed, cid) or [None]
            for ch in chs:
                row = temps_chap[ch][cid]
                row['secondes'] += s / len(chs)
                row['jours'][day] += s
                row['partage'] = len(chs)
        elif dans(day, avant):
            secondes_avant += s
            if s:
                actifs_avant.add(day)
    for (day, _cid, _path), status in du_jour.items():
        if status and dans(day, avant):
            actifs_avant.add(day)

    nb_jours = (fin - debut).days + 1
    jours_out = []
    for i in range(nb_jours):
        day = debut + timedelta(days=i)
        row = par_jour.get(day, {'reussies': 0, 'partielles': 0, 'ratees': 0, 'secondes': 0})
        actif = int(bool(row['secondes'] or row['reussies'] or row['partielles'] or row['ratees']))
        jours_out.append({'date': day.isoformat(), **row, 'actifs': actif})
    actifs = sum(r['actifs'] for r in jours_out)
    pas = 'jour'
    if nb_jours > SEMAINES_APRES:
        pas = 'semaine'
        semaines = {}
        for r in jours_out:
            day = date.fromisoformat(r['date'])
            lundi = (day - timedelta(days=day.weekday())).isoformat()
            s = semaines.setdefault(lundi, {'date': lundi, 'reussies': 0, 'partielles': 0, 'ratees': 0, 'secondes': 0, 'actifs': 0})
            for k in ('reussies', 'partielles', 'ratees', 'secondes', 'actifs'):
                s[k] += r[k]
        jours_out = list(semaines.values())

    # ── Notes d'examens
    notes = _notes_examens(d, allowed)
    notes_periode = [n for n in notes if dans(n[0])]
    notes_avant = [n for n in notes if dans(n[0], avant)]
    serie_chap = defaultdict(list)
    for day, cid, _note_examen, chapitres in notes_periode:
        for ch, n in chapitres.items():
            serie_chap[ch].append({'date': day.isoformat(), 'note': n, 'examen': cid})

    def moyenne(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    # ── Chapitres : ceux du programme du niveau (sinon ceux qu'il a travaillés), dans l'ordre d'enseignement
    if programme:
        chapitres = list(programme)
    else:
        from apps.caracteristics.models import Chapter
        ids = set(q_chap) | set(serie_chap) | {ch for ch in temps_chap if ch}
        chapitres = list(Chapter.objects.filter(id__in=ids).order_by('name'))
    quiz = set(SkillQuestion.objects.filter(is_active=True, a_relire=False, type=COURS,
                                            **({'class_level': level} if level else {}))
               .values_list('chapter_id', flat=True)) if chapitres else set()
    chap_out = []
    for ch in chapitres:
        serie = serie_chap.get(ch.id, [])
        vals = [p['note'] for p in serie]
        q = q_chap.get(ch.id, {'reussies': 0, 'partielles': 0, 'ratees': 0})
        sec = round(sum(r['secondes'] for r in temps_chap.get(ch.id, {}).values()))
        chap_out.append({
            'id': ch.id, 'nom': ch.name,
            'hub_url': hub_url('exercises', level, ch) if level and ch.id in allowed else None,
            'examens_url': hub_url('exams', level, ch) if level and ch.id in allowed else None,
            'quiz': ch.id in quiz,
            'note': {'moyenne': moyenne(vals), 'min': min(vals) if vals else None, 'max': max(vals) if vals else None,
                     'n': len(vals), 'serie': serie},
            **q, 'secondes': sec,
            # Questions de ce chapitre, jour par jour (jours avec activité seulement).
            'jours': [{'date': k.isoformat(), **v} for k, v in sorted(q_chap_jour.get(ch.id, {}).items())],
            'actif': bool(vals or sec or q['reussies'] or q['partielles'] or q['ratees']),
        })

    # ── Temps : chapitre › contenu › jours
    noms = {c['id']: c['nom'] for c in chap_out}
    temps = []
    for ch, contenus in temps_chap.items():
        rows = []
        for cid, r in contenus.items():
            c = d.contents.get(cid)
            if c is None:
                continue
            rows.append({'id': cid, 'titre': c.title, 'type': c.type, 'url': _url(c), 'secondes': round(r['secondes']),
                         'partage': r['partage'],
                         'jours': [{'date': k.isoformat(), 'secondes': v} for k, v in sorted(r['jours'].items())]})
        rows.sort(key=lambda x: -x['secondes'])
        total = sum(x['secondes'] for x in rows)
        if total:
            nom = noms.get(ch) or (next((n for c_, n in d.chapters_of.get(rows[0]['id'], []) if c_ == ch), None) if ch else None)
            temps.append({'id': ch, 'nom': nom or 'Autres', 'secondes': total, 'contenus': rows})
    temps.sort(key=lambda x: -x['secondes'])

    faibles = _points_faibles(d, allowed, level, du_jour, dans, {c['id']: c for c in chap_out})

    q_periode = {k: sum(r[k] for r in jours_out) for k in ('reussies', 'partielles', 'ratees')}
    return Response({
        'level': {'id': level.id, 'name': level.name} if level else None,
        'periode': {'debut': debut.isoformat(), 'fin': fin.isoformat(), 'jours': jours, 'pas': pas, 'nb_jours': nb_jours},
        'kpis': {
            'questions': {**q_periode, 'avant': q_avant if avant else None},
            'note': {'moyenne': moyenne([n[2] for n in notes_periode]), 'n': len(notes_periode),
                     'avant': moyenne([n[2] for n in notes_avant]) if avant else None},
            'secondes': {'total': sum(r['secondes'] for r in jours_out), 'avant': secondes_avant if avant else None},
            'jours_actifs': {'n': actifs, 'sur': nb_jours, 'avant': len(actifs_avant) if avant else None},
        },
        'jours': jours_out,
        'notes': [{'date': day.isoformat(), 'id': cid, 'titre': d.contents[cid].title, 'url': _url(d.contents[cid]),
                   'note': note} for day, cid, note, _ in notes_periode],
        'chapitres': chap_out,
        'temps': temps,
        'points_faibles': faibles,
        # Vue administrateur (?eleve=) : de qui est cette progression (bandeau de la page).
        **({'eleve': {'id': user.id, 'username': user.username,
                      'nom': f'{user.first_name} {user.last_name}'.strip()}} if user != request.user else {}),
    })


def _points_faibles(d, allowed, level, du_jour, dans, chapitres):
    """Théorèmes des questions évaluées sur la période, les moins réussis d'abord (au moins une question ratée ou en
    partie), avec les questions encore à revoir aujourd'hui."""
    from apps.things.models import Content
    from apps.things.views import _walk_questions_meta
    stats = defaultdict(lambda: {'reussies': 0, 'partielles': 0, 'ratees': 0})
    for (day, cid, path), status in du_jour.items():
        if status and dans(day):
            for nom in d.theoremes_of.get(cid, {}).get(path, []):
                stats[nom][_cle(status)] += 1
    # Dernier statut de chaque question, tous jours confondus : ce qui reste à revoir.
    courant, quand = {}, {}
    for cid, path, status, _aide, _reprise, at in d.events:
        courant[(cid, path)] = status
        quand[(cid, path)] = _local(at)
    a_revoir = defaultdict(list)
    for (cid, path), status in courant.items():
        if status in ('review', 'failed', 'partial'):
            for nom in d.theoremes_of.get(cid, {}).get(path, []):
                if nom in stats:
                    a_revoir[nom].append((cid, path, status, quand[(cid, path)]))
    rows = []
    for nom, s in stats.items():
        n = s['reussies'] + s['partielles'] + s['ratees']
        taux = round((s['reussies'] + s['partielles'] / 2) * 100 / n)
        # Un point faible : des questions encore à refaire, ou moins de la moitié réussie sur la période (un théorème
        # raté puis réussi depuis n'y est plus).
        if not (s['ratees'] or s['partielles']) or not (a_revoir.get(nom) or taux < 50):
            continue
        rows.append((taux, -s['ratees'], nom, s, n))
    rows.sort()
    rows = rows[:POINTS_FAIBLES]
    if not rows:
        return []
    besoin = {cid for nom in (r[2] for r in rows) for cid, *_ in a_revoir.get(nom, [])}
    structures = dict(Content.objects.filter(id__in=besoin).values_list('id', 'json_content'))
    libelles = {cid: {p: lab for p, lab, _ in _walk_questions_meta(js or {})} for cid, js in structures.items()}
    idx = TH.index()
    out = []
    for taux, _neg, nom, s, n in rows:
        th = idx.get(TH.cle(nom))
        chs = th['chapters'] if th else []
        ch_id = next((ch for ch in chs if allowed is None or ch in allowed), chs[0] if chs else None)
        ch = chapitres.get(ch_id)
        questions = sorted(a_revoir.get(nom, []), key=lambda x: x[3], reverse=True)
        out.append({
            'nom': th['name'] if th else nom, 'id': th['id'] if th else None, 'taux': taux, 'questions': n, **s,
            'chapitre': {'id': ch_id, 'nom': ch['nom'], 'hub_url': ch['hub_url']} if ch else None,
            'a_revoir_total': len(questions),
            'a_revoir': [{'id': cid, 'titre': d.contents[cid].title, 'url': _url(d.contents[cid]),
                          'question': libelles.get(cid, {}).get(path, path), 'statut': status, 'date': day.isoformat()}
                         for cid, path, status, day in questions[:A_REFAIRE] if cid in d.contents],
        })
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tableau_jour(request):
    """Ce jour-là : par contenu, le temps et les questions réussies / en partie / ratées."""
    try:
        day = date.fromisoformat(request.query_params.get('date', ''))
    except ValueError:
        return Response({'error': 'date : AAAA-MM-JJ.'}, status=400)
    user, erreur = eleve_vise(request)
    if erreur:
        return erreur
    d, _level, _programme, _allowed, du_jour = _donnees(user)
    rows = defaultdict(lambda: {'secondes': 0, 'reussies': 0, 'partielles': 0, 'ratees': 0})
    for (jour, cid, _path), status in du_jour.items():
        if jour == day and status:
            rows[cid][_cle(status)] += 1
    for r in d.time_rows:
        if r['date'] == day:
            rows[r['object_id']]['secondes'] += r['seconds']
    out = []
    for cid, r in rows.items():
        c = d.contents.get(cid)
        if c is None or not (r['secondes'] or r['reussies'] or r['partielles'] or r['ratees']):
            continue
        out.append({'id': cid, 'titre': c.title, 'type': c.type, 'url': _url(c),
                    'chapitre': next((n for _, n in d.chapters_of.get(cid, [])), None), **r})
    out.sort(key=lambda x: (-x['secondes'], -(x['reussies'] + x['partielles'] + x['ratees'])))
    return Response({'date': day.isoformat(), 'contenus': out})
