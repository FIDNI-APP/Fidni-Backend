"""Journal d'activité d'un membre (Pilotage › Membres, 14/10/2026) : ce qu'il a fait, jour par jour et contenu par contenu.

Avant, la fiche d'un membre montrait 8 lignes (« A consulté », « A commenté »…) lues dans 6 sources, dont des dates
écrasées. Le journal lit les sources datées qui existent déjà, par élève :
- par contenu travaillé ce jour-là : temps (StudyTimeDay), dernière ouverture (ViewHistory : seule la dernière est
  gardée), questions évaluées une à une avec l'aide utilisée (AssessmentEvent), indices et solutions ouverts
  (QuestionHelp), « Tout réussi », contenu réussi / à revoir (Complete), favori, j'aime, ajout à une liste, ressenti,
  signalement, commentaire, solution proposée, chrono d'examen, correction par IA ;
- hors contenu : quiz (dernier passage seulement, avec son score ; quiz commencé), DS annoncé, DS blanc, liste créée,
  classe rejointe, cahier créé, simulation de concours, inscription, dernière connexion.
Les documents privés du membre (apps/documents) ne sont jamais montrés.

Fenêtre de JOURS jours par page (`avant` : date exclue, la plus récente d'abord) ; une fenêtre vide passe à la
précédente (MAX_FENETRES au plus) ; `suivant` = date à passer pour la page suivante, None au début du compte.
Une requête par source, bornée à la fenêtre ; les contenus sont chargés en lot. Jours en UTC (comme StudyTimeDay).
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

JOURS = 14
MAX_FENETRES = 8      # une page saute au plus 8 × 14 jours sans activité
DETAIL_MAX = 60       # lignes de détail par contenu et par jour
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
STATUT = {'success': 'réussie', 'partial': 'en partie', 'review': 'à revoir', 'failed': 'ratée'}
AIDE = {'indice': 'avec indice', 'solution': 'avec la solution', '': 'sans aide'}


def _bornes(debut, fin):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(debut, time.min), tz),
            timezone.make_aware(datetime.combine(fin, time.min), tz))


def _jour(dt):
    return timezone.localtime(dt).date()


def _ref(c):
    return {'id': c.id, 'type': c.type, 'title': c.title, 'url': f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}'}


def _fenetre(user, debut, fin):
    """Jours de [debut, fin) : [{date, minutes, contenus, evenements}], du plus récent au plus ancien."""
    from apps.classrooms.models import ClassroomMembership
    from apps.concours.models import SimulationSession
    from apps.interactions.models import (AICorrection, AssessmentEvent, Complete, QuestionHelp, RevisionList,
                                          RevisionListItem, Save, StudyTimeDay, TimeSession, UpcomingTest, Vote)
    from apps.notebooks.models import Notebook
    from apps.skilliq.models import QuizEnCours, SkillAssessment
    from apps.things.models import Comment, Content, ContentReport, DifficultyFeedback, ProposedSolution
    from apps.things.views import _walk_questions_meta
    from apps.users.models import ViewHistory

    t0, t1 = _bornes(debut, fin)
    ct = ContentType.objects.get_for_model(Content)
    contenus = defaultdict(dict)    # (jour, content_id) -> entrée
    evenements = defaultdict(list)  # jour -> [événements]
    minutes = defaultdict(int)

    def entree(jour, cid):
        e = contenus[(jour, int(cid))]
        if not e:
            e.update({'id': int(cid), 'secondes': 0, 'ouvert': None, 'questions': defaultdict(int), 'tout_reussi': False,
                      'aides': defaultdict(int), 'statut': None, 'gestes': [], 'detail': [], 'premier': None, 'dernier': None})
        return e

    def vu(e, at):
        e['premier'] = min(at, e['premier']) if e['premier'] else at
        e['dernier'] = max(at, e['dernier']) if e['dernier'] else at

    def geste(e, at, kind, label):
        e['gestes'].append({'at': at, 'kind': kind, 'label': label})
        vu(e, at)

    # ── Par contenu
    for r in StudyTimeDay.objects.filter(user=user, date__gte=debut, date__lt=fin):
        entree(r.date, r.object_id)['secondes'] += r.seconds
        minutes[r.date] += r.seconds
    for v in ViewHistory.objects.filter(user=user, content_type=ct, viewed_at__gte=t0, viewed_at__lt=t1):
        if str(v.object_id).isdigit():
            e = entree(_jour(v.viewed_at), v.object_id)
            e['ouvert'] = v.viewed_at
            vu(e, v.viewed_at)
    for ev in AssessmentEvent.objects.filter(user=user, at__gte=t0, at__lt=t1).order_by('at'):
        e = entree(_jour(ev.at), ev.object_id)
        if ev.status:
            e['questions'][ev.status] += 1
        else:
            e['questions']['retiree'] += 1
        if ev.source == 'tout':
            e['tout_reussi'] = True
        e['detail'].append({'at': ev.at, 'kind': 'evaluation', 'path': ev.question_path, 'status': ev.status,
                            'aide': ev.aide, 'source': ev.source, 'reprise': ev.reprise})
        vu(e, ev.at)
    for h in QuestionHelp.objects.filter(user=user, day__gte=debut, day__lt=fin):
        e = entree(h.day, h.object_id)
        e['aides'][h.kind] += 1
        e['detail'].append({'at': h.first_at, 'kind': 'aide', 'path': h.question_path, 'aide': h.kind, 'fois': h.count})
        vu(e, h.first_at)
    for c in Complete.objects.filter(user=user, content_type=ct, updated_at__gte=t0, updated_at__lt=t1):
        if str(c.object_id).isdigit():
            e = entree(_jour(c.updated_at), c.object_id)
            e['statut'] = c.status
            geste(e, c.updated_at, 'statut', 'Marqué réussi' if c.status == 'success' else 'Marqué à revoir')
    for s in Save.objects.filter(user=user, content_type=ct, saved_at__gte=t0, saved_at__lt=t1):
        if str(s.object_id).isdigit():
            geste(entree(_jour(s.saved_at), s.object_id), s.saved_at, 'favori', 'Mis en favori')
    for v in Vote.objects.filter(user=user, content_type=ct, updated_at__gte=t0, updated_at__lt=t1).exclude(value=0):
        if str(v.object_id).isdigit():
            geste(entree(_jour(v.updated_at), v.object_id), v.updated_at, 'vote', 'J’aime' if v.value > 0 else 'Je n’aime pas')
    for it in (RevisionListItem.objects.filter(revision_list__user=user, content_type=ct, added_at__gte=t0, added_at__lt=t1)
               .select_related('revision_list')):
        geste(entree(_jour(it.added_at), it.object_id), it.added_at, 'liste', f'Ajouté à la liste « {it.revision_list.name} »')
    for f in DifficultyFeedback.objects.filter(user=user, updated_at__gte=t0, updated_at__lt=t1):
        geste(entree(_jour(f.updated_at), f.content_id), f.updated_at, 'ressenti', f'Ressenti : {f.get_felt_display().lower()}')
    for r in ContentReport.objects.filter(user=user, created_at__gte=t0, created_at__lt=t1):
        quoi = f' ({r.item_label})' if r.item_label else ''
        geste(entree(_jour(r.created_at), r.content_id), r.created_at, 'signalement',
              f'Signalement{quoi} : {r.get_reason_display().lower()}')
    for c in Comment.objects.filter(author=user, created_at__gte=t0, created_at__lt=t1):
        texte = ' '.join((c.content or '').split())
        geste(entree(_jour(c.created_at), c.content_item_id), c.created_at, 'commentaire',
              f'Commentaire : « {texte[:120]}{"…" if len(texte) > 120 else ""} »')
    for s in ProposedSolution.objects.filter(author=user, created_at__gte=t0, created_at__lt=t1):
        geste(entree(_jour(s.created_at), s.content_item_id), s.created_at, 'solution', 'Solution proposée')
    for t in TimeSession.objects.filter(user=user, content_type=ct, created_at__gte=t0, created_at__lt=t1):
        if str(t.object_id).isdigit():
            mins = round(t.session_duration.total_seconds() / 60) if t.session_duration else 0
            note = f', {t.score:g}/{t.max_score:g}' if t.score is not None and t.max_score else ''
            geste(entree(_jour(t.created_at), t.object_id), t.created_at, 'chrono', f'Chrono : {mins} min{note}')
    for a in AICorrection.objects.filter(user=user, content_type=ct, submitted_at__gte=t0, submitted_at__lt=t1):
        if str(a.object_id).isdigit():
            note = f' : {a.score_awarded:g}/{a.score_total:g}' if a.score_awarded is not None and a.score_total else ''
            geste(entree(_jour(a.submitted_at), a.object_id), a.submitted_at, 'ia', f'Copie corrigée par l’IA{note}')

    # ── Hors contenu
    def evt(at, kind, label, url=None):
        evenements[_jour(at)].append({'at': at, 'kind': kind, 'label': label, 'url': url})

    for a in (SkillAssessment.objects.filter(user=user, completed_at__gte=t0, completed_at__lt=t1)
              .select_related('chapter', 'class_level')):
        p = round(100 * a.score / a.max_score) if a.max_score else 0
        niveau = f' ({a.class_level.name})' if a.class_level_id else ''
        rang = f', {a.attempts}e passage' if (a.attempts or 1) > 1 else ''
        evt(a.completed_at, 'quiz', f'Quiz « {a.chapter.name} »{niveau} : {p} %{rang}')
    for q in QuizEnCours.objects.filter(user=user, debut__gte=t0, debut__lt=t1).select_related('chapter'):
        evt(q.debut, 'quiz', f'Quiz « {q.chapter.name} » commencé ({len(q.reponses or {})}/{len(q.questions or [])} corrigées)')
    for t in UpcomingTest.objects.filter(user=user).prefetch_related('chapters').select_related('subject'):
        chap = ', '.join(c.name for c in t.chapters.all()[:3])
        if t0 <= t.created_at < t1:
            evt(t.created_at, 'ds', f'{t.get_kind_display()} annoncé pour le {t.date:%d/%m}' + (f' : {chap}' if chap else ''))
        if t.mock_started_at and t0 <= t.mock_started_at < t1:
            evt(t.mock_started_at, 'ds', 'DS blanc commencé')
        if t.mock_done_at and t0 <= t.mock_done_at < t1:
            duree = f' en {round(t.mock_seconds / 60)} min' if t.mock_seconds else ''
            evt(t.mock_done_at, 'ds', f'DS blanc terminé{duree}')
    for r in RevisionList.objects.filter(user=user, created_at__gte=t0, created_at__lt=t1):
        evt(r.created_at, 'liste', f'Liste créée : « {r.name} »')
    for m in ClassroomMembership.objects.filter(student=user, joined_at__gte=t0, joined_at__lt=t1).select_related('classroom'):
        evt(m.joined_at, 'classe', f'A rejoint la classe « {m.classroom.name} »')
    for n in Notebook.objects.filter(user=user, created_at__gte=t0, created_at__lt=t1):
        evt(n.created_at, 'cahier', f'Cahier créé : « {n.title} »')
    for s in SimulationSession.objects.filter(user=user, started_at__gte=t0, started_at__lt=t1):
        score = f' : {s.correct_count}/{s.total_questions}' if s.submitted_at and s.total_questions else ''
        evt(s.started_at, 'concours', f'Simulation de concours{score}')
    if t0 <= user.date_joined < t1:
        evt(user.date_joined, 'inscription', 'Inscription')
    if user.last_login and t0 <= user.last_login < t1:
        evt(user.last_login, 'connexion', 'Dernière connexion')

    # ── Contenus et libellés des questions (en lot)
    ids = {cid for (_, cid) in contenus}
    objets = {c.id: c for c in Content.objects.filter(id__in=ids).only('id', 'type', 'title', 'json_content')}
    libelles = {cid: {p: lab for p, lab, _ in _walk_questions_meta(c.json_content or {})} for cid, c in objets.items()}

    jours = sorted({j for (j, _) in contenus} | set(evenements), reverse=True)
    out = []
    for j in jours:
        lignes = []
        for (jj, cid), e in contenus.items():
            if jj != j or cid not in objets:
                continue
            labs = libelles.get(cid, {})
            detail = []
            for d in sorted(e['detail'], key=lambda x: x['at'])[:DETAIL_MAX]:
                q = labs.get(d['path'], 'Tout le contenu' if d['path'] == '*' else d['path'])
                if d['kind'] == 'aide':
                    texte = f'{"Indice" if d["aide"] == "indice" else "Solution"} ouvert{"e" if d["aide"] == "solution" else ""}' \
                            + (f' ({d["fois"]} fois)' if d.get('fois', 1) > 1 else '')
                else:
                    texte = STATUT.get(d['status'], 'évaluation retirée') if d['status'] else 'évaluation retirée'
                    if d['source'] == 'tout':
                        texte += ' (« Tout réussi »)'
                    elif d['status'] and d['aide'] is not None and not d['reprise']:
                        texte += f' · {AIDE.get(d["aide"], d["aide"])}'
                detail.append({'at': d['at'].isoformat(), 'question': q, 'kind': d['kind'], 'status': d.get('status'), 'texte': texte})
            lignes.append({
                'content': _ref(objets[cid]),
                'minutes': round(e['secondes'] / 60),
                'ouvert': e['ouvert'].isoformat() if e['ouvert'] else None,
                'questions': dict(e['questions']),
                'tout_reussi': e['tout_reussi'],
                'aides': dict(e['aides']),
                'statut': e['statut'],
                'gestes': [{'at': g['at'].isoformat(), 'kind': g['kind'], 'label': g['label']}
                           for g in sorted(e['gestes'], key=lambda g: g['at'])],
                'detail': detail,
                'debut': e['premier'].isoformat() if e['premier'] else None,
                'fin': e['dernier'].isoformat() if e['dernier'] else None,
            })
        lignes.sort(key=lambda x: (x['fin'] or '', x['minutes']), reverse=True)
        evts = sorted(evenements.get(j, []), key=lambda x: x['at'], reverse=True)
        out.append({'date': j.isoformat(), 'minutes': round(minutes.get(j, 0) / 60), 'contenus': lignes,
                    'evenements': [{**x, 'at': x['at'].isoformat()} for x in evts]})
    return out


def journal(user, avant=None):
    """{jours, suivant, plus_ancien} : jusqu'à JOURS jours d'activité avant `avant` (date exclue ; défaut : demain)."""
    fin = avant or (timezone.localdate() + timedelta(days=1))
    plus_ancien = _jour(user.date_joined)
    jours = []
    for _ in range(MAX_FENETRES):
        debut = fin - timedelta(days=JOURS)
        jours = _fenetre(user, debut, fin)
        fin = debut
        if jours or debut <= plus_ancien:
            break
    return {'jours': jours, 'suivant': fin.isoformat() if fin > plus_ancien else None,
            'plus_ancien': plus_ancien.isoformat()}
