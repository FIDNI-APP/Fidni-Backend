"""python manage.py audit_usage [--jours 30] [--format md|json] [--sortie FICHIER] [--top 20] [--min-eleves 5]

Rapport d'audit d'usage, en LECTURE SEULE : ce qui sert et ce qui ne sert pas, entonnoir d'inscription,
rétention, réussite réelle face à la difficulté affichée, solutions ouvertes, signalements, temps passé.
Pour décider des fusions de menu, des contenus à reprendre et des seuils (ressenti, durées).

Garde-fous : tout se lit dans une transaction (SET TRANSACTION READ ONLY sous PostgreSQL), annulée à la fin ;
le cache est lu mais jamais écrit pendant le rapport. Comptes maison (administrateurs, compte éditorial,
tests) exclus partout. Aucun nom ni e-mail d'élève en sortie : des compteurs, des identifiants et titres de contenus.

Les mesures du navigateur sont récentes (pages depuis le 06/10/2026, visiteurs et filtres depuis le 09/10,
nouveaux gestes depuis le 10/10) : chaque chiffre est aussi donné en moyenne par jour mesuré.

Sur le serveur (sans -t : le rapport arrive sur l'hôte, les journaux restent sur la sortie d'erreur) :
    docker exec fidni-backend python manage.py audit_usage --jours 30 --format md > audit.md
    (ou --sortie /tmp/audit.md dans le conteneur, puis docker cp fidni-backend:/tmp/audit.md .)
"""
import inspect
import json
import math
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from apps.users import admin_dashboard as ad

# Débuts des mesures (voir aussi admin_dashboard.VIEWS_SINCE / USAGE_SINCE / ANON_SINCE).
# StudyTimeDay (créé vers le 01/10/2026, migration interactions 0019) : le cumul d'avant a été rattaché en bloc au
# dernier jour d'activité de chaque contenu. Temps « propre » = à partir du lendemain de la migration (_study_clean_since).
STUDY_SINCE = date(2026, 10, 1)
FILTERS_SINCE = date(2026, 10, 7)    # gestes « filtre-* » des listes
AUDIT_SINCE = date(2026, 10, 10)     # nouveaux gestes, portes d'inscription, origine des évaluations, ressenti
FIRST_AUDIT_ACTION = 'partager'      # premier des gestes ajoutés le 10/10/2026 dans admin_dashboard.TRACKED_ACTIONS
TIME_CAP = 2 * 3600                  # temps d'un élève sur un contenu plafonné à 2 h (onglet oublié)
Z80 = 1.2816                         # borne de Wilson à 80 %
BANDS = {'easy': (0.70, 1.01), 'medium': (0.40, 0.70), 'hard': (0.0, 0.40)}
# Mêmes poids que things/difficulty.py : réponse d'une question, ou contenu terminé sans assez de questions évaluées.
SCORE = {'success': 1.0, 'partial': 0.5, 'review': 0.0, 'failed': 0.0}
COMPLETE_SCORE = {'success': 1.0, 'review': 0.25}
BATCH_SECONDS = 2                    # avant le 10/10 : toutes « réussi » à moins de 2 s d'écart = un « Tout réussi »
RETENTION_WEEKS = 8
TYPE_LABEL = ad.TYPE_LABEL
DIFF_LABEL = {**ad.DIFFICULTY_LABEL, None: 'Sans difficulté'}
FELT_LABEL = {'easier': 'Plus facile', 'as_said': 'Comme annoncé', 'harder': 'Plus dur'}
SOURCE_LABEL = {'question': 'Question par question', 'tout': '« Tout réussi »', 'apres_solution': 'Sous la solution',
                'rattrapage': 'Bandeau de rattrapage'}
VALIDATION_LABEL = {'compatible': 'Solution compatible', 'different': 'Solution différente',
                    'not-understood': 'Solution pas comprise'}

# Copie de PAGES (frontend src/lib/usage.ts) : le serveur ne connaît pas les routes, il faut la liste
# pour afficher les pages jamais vues. À tenir à jour avec le front.
PAGE_PATTERNS = [
    ('/', 'Accueil'),
    ('/exercises', 'Liste des exercices'),
    ('/exercises/niveau/:level/:chapter?', 'Exercices d’un niveau'),
    ('/exercises/:id/pdf', 'Exercice : impression'),
    ('/exercises/:id', 'Page d’un exercice'),
    ('/lessons', 'Liste des leçons'),
    ('/lessons/niveau/:level/:chapter?', 'Leçons d’un niveau'),
    ('/lessons/:id/pdf', 'Leçon : impression'),
    ('/lessons/:id', 'Page d’une leçon'),
    ('/exams', 'Liste des examens'),
    ('/exams/nationaux', 'Examens nationaux'),
    ('/exams/nationaux/:annee', 'Bac national : une année'),
    ('/exams/niveau/:level/:chapter?', 'Examens d’un niveau'),
    ('/exams/:id/pdf', 'Examen : impression'),
    ('/exams/:id', 'Page d’un examen'),
    ('/concours', 'Concours'),
    ('/concours/exams/:id', 'Sujet de concours'),
    ('/concours/simulate/:sessionId', 'Simulation de concours'),
    ('/concours/sessions', 'Historique des concours'),
    ('/concours/sessions/:sessionId/recap', 'Bilan d’un concours'),
    ('/concours/tips', 'Conseils concours'),
    ('/concours/tips/:id', 'Conseil concours'),
    ('/skill-iq', 'Skill IQ'),
    ('/progression', 'Ma progression'),
    ('/statistiques', 'Mes statistiques (ancienne page)'),
    ('/notebooks', 'Cahiers'),
    ('/notebooks/:id/pdf', 'Cahier : impression'),
    ('/revision-lists', 'Révisions'),
    ('/revisions/ds/:id', 'Plan de révision d’un DS'),
    ('/revisions/ds/:id/blanc', 'DS blanc'),
    ('/revision-lists/:id/pdf', 'Liste de révision : impression'),
    ('/profile/revision-lists/:id', 'Une liste de révision'),
    ('/saved', 'Favoris'),
    ('/profile/:username/edit', 'Modifier mon profil'),
    ('/profile/:username', 'Profil'),
    ('/complete-profile', 'Compléter son profil'),
    ('/classrooms', 'Classes'),
    ('/classrooms/:id', 'Une classe'),
    ('/learning-path', 'Parcours'),
    ('/learning-path/:id', 'Un parcours'),
    ('/learning-path/:pathId/chapters/:chapterId/videos/:videoId', 'Vidéo d’un parcours'),
    ('/learning-path/:pathId/chapters/:chapterId/quiz', 'Quiz d’un parcours'),
    ('/search', 'Recherche'),
    ('/login', 'Connexion'),
    ('/signup', 'Inscription'),
    ('/verify-email', 'Confirmation de l’e-mail'),
    ('/reset-password', 'Nouveau mot de passe'),
    ('/mentions-legales', 'Mentions légales'),
    ('/privacy-policy', 'Confidentialité'),
    ('/terms-of-service', 'Conditions d’utilisation'),
]
# Motifs ajoutés à PAGES le 10/10/2026 : pas mesurés avant (« jamais vue » n'a de sens qu'à partir de là).
PAGES_SINCE_AUDIT = {'/revisions/ds/:id', '/revisions/ds/:id/blanc', '/verify-email', '/reset-password',
                     '/learning-path/:pathId/chapters/:chapterId/videos/:videoId',
                     '/learning-path/:pathId/chapters/:chapterId/quiz'}


# ─────────────────────────────── outils

@contextmanager
def _cache_lecture_seule():
    """Le rapport peut LIRE le cache (ressenti déjà calculé…) mais n'y écrit jamais rien."""
    from django.core.cache import caches
    backend = caches['default']
    blocked = {
        'set': lambda *a, **k: None, 'set_many': lambda *a, **k: [], 'add': lambda *a, **k: False,
        'delete': lambda *a, **k: False, 'delete_many': lambda *a, **k: None, 'touch': lambda *a, **k: False,
        'incr': lambda *a, **k: 0, 'decr': lambda *a, **k: 0, 'clear': lambda *a, **k: None,
        # Cache fichier (production) ou mémoire : une entrée expirée lue est effacée par `_delete`.
        '_delete': lambda *a, **k: False,
    }
    for name, fn in blocked.items():
        setattr(backend, name, fn)
    try:
        yield
    finally:
        for name in blocked:
            backend.__dict__.pop(name, None)


def _wilson(p, n, z=Z80):
    """Intervalle de Wilson d'une proportion p observée sur n (n peut être pondéré)."""
    if not n:
        return None, None
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _round(x, d=2):
    return None if x is None else round(x, d)


def _pct(part, whole):
    return round(part * 100 / whole) if whole else None


def _band(r):
    return 'easy' if r >= 0.70 else ('medium' if r >= 0.40 else 'hard')


def _ref(content):
    return ad._content_ref(content)


class _Ctx:
    """Bornes de la période et populations, partagées par toutes les sections."""

    def __init__(self, days, top, min_students):
        self.days, self.top, self.min_students = days, top, min_students
        self.today = timezone.localdate()
        self.first = self.today - timedelta(days=days - 1)
        self.prev_first = self.first - timedelta(days=days)
        self.start = timezone.make_aware(datetime.combine(self.first, time.min))
        self.real = ad._real_users()
        self.real_q = self.real.values('id')
        self.real_ids = set(self.real.values_list('id', flat=True))
        from apps.things.models import Content
        self.ct = ContentType.objects.get_for_model(Content)
        self.study_since = _study_clean_since()

    def measured(self, since=None):
        """Nombre de jours de la période couverts par une mesure qui a commencé à `since`."""
        begin = max(self.first, since) if since else self.first
        return max(0, (self.today - begin).days + 1)

    def per_day(self, value, since=None):
        n = self.measured(since)
        return round(value / n, 1) if n else None


def _study_clean_since():
    """Premier jour où StudyTimeDay ne contient que le temps du jour : la migration qui l'a créé (interactions
    0019) y a rattaché tout le cumul d'avant au dernier jour d'activité de chaque contenu, jusqu'au jour même."""
    from django.db.migrations.recorder import MigrationRecorder
    applied = (MigrationRecorder.Migration.objects.filter(app='interactions', name='0019_studytimeday')
               .values_list('applied', flat=True).first())
    day = timezone.localtime(applied).date() if applied else STUDY_SINCE
    return day + timedelta(days=1)


def _felt_for(contents):
    """Ressenti des élèves (things/difficulty.py, lot du ressenti) ; ({}, raison) s'il n'est pas disponible."""
    try:
        from apps.things.difficulty import felt_for
    except ImportError:
        return {}, 'module things/difficulty.py absent'
    if not contents:
        return {}, None
    try:
        # store=False : felt_for n'écrit rien en cache (en plus du blocage de _cache_lecture_seule).
        kwargs = {'store': False} if 'store' in inspect.signature(felt_for).parameters else {}
        # Point de sauvegarde : une erreur SQL n'interrompt pas la transaction (en lecture seule) du rapport.
        with transaction.atomic():
            return felt_for(contents, **kwargs) or {}, None
    except Exception as exc:  # le rapport passe quand même : la colonne reste vide, la raison est donnée
        return {}, f'{type(exc).__name__} : {exc}'


# ─────────────────────────────── 1. Couverture

def _coverage(ctx):
    sources = [
        ('Tables métier (auto-évaluations, contenus terminés, favoris, listes…)', None),
        ("Temps d'étude jour par jour (StudyTimeDay ; avant : cumul rattaché au dernier jour d'activité)",
         ctx.study_since),
        ('Vues par contenu, jour par jour, visiteurs compris (ContentDailyView)', ad.VIEWS_SINCE),
        ('Pages vues et gestes du navigateur (UsageDaily)', ad.USAGE_SINCE),
        ('Visiteurs non connectés à part, valeurs des filtres', ad.ANON_SINCE),
        ('Nouveaux gestes, portes d’inscription, origine des auto-évaluations, ressenti, solutions ouvertes',
         AUDIT_SINCE),
    ]
    real = ctx.real
    students = real.filter(profile__user_type='student')
    by_level = Counter(dict(students.values_list('profile__class_level__name').annotate(n=Count('id'))))
    from apps.users.models import GoogleAccount
    return {
        'sources': [{'source': label, 'since': since.isoformat() if since else None,
                     'measured_days': ctx.measured(since)} for label, since in sources],
        'population': {
            'members': len(ctx.real_ids),
            'students': students.count(),
            'teachers': real.filter(profile__user_type='teacher').count(),
            'students_without_level': students.filter(profile__class_level=None).count(),
            'new': real.filter(date_joined__gte=ctx.start).count(),
            'active': len(ad._active_user_ids(ctx.start, ctx.real_ids)),
            'google_linked': GoogleAccount.objects.filter(user_id__in=ctx.real_q).values('user_id').distinct().count(),
            'by_level': [{'level': name or 'Sans niveau', 'students': n} for name, n in by_level.most_common()],
        },
    }


# ─────────────────────────────── 2. Fonctionnalités et gestes

def _extra_features():
    """Usages en base absents du Pilotage, utiles pour décider des fusions."""
    from apps.concours.models import SimulationSession
    from apps.interactions.models import QuestionProgress, StudyTimeDay, UpcomingTest
    from apps.learningpath.models import QuizAttempt, UserVideoProgress
    from apps.notebooks.models import Notebook
    from apps.notifications.models import Notification
    from apps.things.models import Comment
    from apps.users.models import GoogleAccount
    return [
        ('concours_fini', 'Simulations de concours rendues', SimulationSession.objects.filter(status='submitted'),
         'submitted_at', 'user_id'),
        ('ds_blanc_commence', 'DS blancs commencés', UpcomingTest.objects.exclude(mock_started_at=None),
         'mock_started_at', 'user_id'),
        ('cahier_cree', 'Cahiers créés', Notebook.objects.all(), 'created_at', 'user_id'),
        ('notif_lue', 'Notifications lues', Notification.objects.exclude(read_at=None), 'read_at', 'recipient_id'),
        ('reponse', 'Réponses à un commentaire', Comment.objects.exclude(parent=None), 'created_at', 'author_id'),
        ('avis_solution', 'Avis sur une solution (compatible, différente, pas comprise)',
         QuestionProgress.objects.exclude(solution_validation=None), 'assessed_at', 'user_id'),
        ('video', 'Vidéos de parcours terminées', UserVideoProgress.objects.exclude(completed_at=None),
         'completed_at', 'user_id'),
        ('quiz_parcours', 'Quiz de parcours', QuizAttempt.objects.all(), 'started_at', 'user_id'),
        ('temps_etude', "Temps d'étude enregistré (jours × contenus)", StudyTimeDay.objects.all(), 'date', 'user_id'),
        ('google', 'Comptes liés à Google', GoogleAccount.objects.all(), 'created_at', 'user_id'),
    ]


def _features(ctx):
    from apps.users.models import UsageDaily
    from apps.users.usage import ACTIONS
    features, _pages = ad._usage(ctx.first, ctx.prev_first, ctx.real_ids)
    base = [dict(f, users_share=_pct(f['users'], len(ctx.real_ids))) for f in features if f['source'] == 'base']
    for key, label, qs, field, ufield in _extra_features():
        cur = ad._since(qs.filter(**{f'{ufield}__in': ctx.real_q}), field, ctx.start)
        users = cur.values(ufield).distinct().count()
        base.append({'key': key, 'label': label, 'source': 'base', 'actions': cur.count(), 'users': users,
                     'previous': None, 'users_share': _pct(users, len(ctx.real_ids))})
    base.sort(key=lambda f: (f['users'], f['actions'], f['key']))

    labels = dict(ad.TRACKED_ACTIONS + ad.TRACKED_FILTERS)
    filters = dict(ad.TRACKED_FILTERS)
    rows = {r['name']: r for r in UsageDaily.objects.filter(kind=UsageDaily.KIND_ACTION, date__gte=ctx.first)
            .values('name').annotate(c=Sum('count'), v=Sum('visitors'), a=Sum('anon_count'))}
    keys = [k for k, _ in ad.TRACKED_ACTIONS]
    new = set(keys[keys.index(FIRST_AUDIT_ACTION):])   # gestes ajoutés le 10/10/2026 (fin de TRACKED_ACTIONS)
    gestures = []
    for name in sorted(ACTIONS | set(rows)):
        r = rows.get(name, {})
        since = AUDIT_SINCE if name in new else (FILTERS_SINCE if name in filters else ad.USAGE_SINCE)
        count = r.get('c') or 0
        gestures.append({'key': name, 'label': labels.get(name, name), 'count': count, 'visits': r.get('v') or 0,
                         'anon': r.get('a') or 0, 'measured_since': since.isoformat(), 'per_day': ctx.per_day(count, since),
                         'filter': name in filters})
    gestures.sort(key=lambda g: (g['count'], g['key']))
    doors = ad._auth_doors(ctx.first)
    for d in doors:
        d['per_day'] = ctx.per_day(d['count'], AUDIT_SINCE)
    return {
        'base': base,
        'gestures': gestures,
        'gestures_never_used': [g['key'] for g in gestures if not g['count']],
        'auth_doors': doors,
        'filter_values': ad._filter_values(ctx.first),
    }


# ─────────────────────────────── 3. Pages

def _pages(ctx):
    from apps.users.models import UsageDaily
    rows = {r['name']: r for r in UsageDaily.objects.filter(kind=UsageDaily.KIND_PAGE, date__gte=ctx.first)
            .values('name').annotate(views=Sum('count'), visits=Sum('visitors'), anon=Sum('anon_count'))}
    labels = dict(PAGE_PATTERNS)
    pages = []
    for name in [p for p, _ in PAGE_PATTERNS] + sorted(set(rows) - set(labels)):
        r = rows.get(name, {})
        views = r.get('views') or 0
        since = AUDIT_SINCE if name in PAGES_SINCE_AUDIT else ad.USAGE_SINCE
        pages.append({'page': name, 'label': labels.get(name, '(motif inconnu du front)'), 'views': views,
                      'visits': r.get('visits') or 0, 'anon': r.get('anon') or 0,
                      'measured_since': since.isoformat(), 'per_day': ctx.per_day(views, since)})
    pages.sort(key=lambda p: (p['views'], p['page']))
    site = UsageDaily.objects.filter(kind=UsageDaily.KIND_SITE, name='visites', date__gte=ctx.first).aggregate(
        pages=Sum('count'), visits=Sum('visitors'), anon_visits=Sum('anon_visitors'), anon_pages=Sum('anon_count'))
    site = {k: v or 0 for k, v in site.items()}
    site['visits_per_day'] = ctx.per_day(site['visits'], ad.USAGE_SINCE)
    site['anon_visits_per_day'] = ctx.per_day(site['anon_visits'], ad.ANON_SINCE)
    current = [ctx.first + timedelta(days=i) for i in range(ctx.days)]
    previous = [ctx.prev_first + timedelta(days=i) for i in range(ctx.days)]
    signups = ctx.real.filter(date_joined__gte=ctx.start).count()
    anon = ad._anonymous(ctx.first, ctx.prev_first, current, previous, signups)
    return {
        'pages': pages,
        'never_viewed': [p['page'] for p in pages if not p['views'] and p['page'] in labels],
        'site': site,
        'anonymous': {k: anon[k] for k in ('since', 'current', 'signups', 'pages', 'top_contents', 'actions')},
    }


# ─────────────────────────────── 4. Entonnoir

def _funnel(ctx):
    from apps.interactions.models import Complete, QuestionProgress
    from apps.users.models import GoogleAccount, UsageDaily
    funnel = ad._funnel(ctx.start, ctx.real)
    cohort = ctx.real.filter(date_joined__gte=ctx.start)
    joined = dict(cohort.values_list('id', 'date_joined'))
    ids = cohort.values('id')
    firsts = {}
    for model in (QuestionProgress, Complete):
        for uid, when in model.objects.filter(user_id__in=ids).values_list('user_id').annotate(m=Min('created_at')):
            if when and (uid not in firsts or when < firsts[uid]):
                firsts[uid] = when
    delays = [(firsts[u] - joined[u]).total_seconds() / 86400 for u in firsts if u in joined]
    done_at = cohort.exclude(profile__onboarding_completed_at=None).values_list('date_joined',
                                                                                'profile__onboarding_completed_at')
    onboarding_delays = [(b - a).total_seconds() / 3600 for a, b in done_at if b >= a]
    steps = Counter(dict(cohort.filter(profile__onboarding_completed=False)
                         .values_list('profile__onboarding_step').annotate(n=Count('id'))))
    visitors = UsageDaily.objects.filter(kind=UsageDaily.KIND_SITE, name='visites', date__gte=ctx.first).aggregate(
        s=Sum('anon_visitors'))['s'] or 0
    n = funnel['signups']
    return {
        **funnel,
        'rates': {k: _pct(v, n) for k, v in funnel.items() if k not in ('signups', 'd7_eligible', 'back_d7')},
        'back_d7_rate': _pct(funnel['back_d7'], funnel['d7_eligible']),
        'visitor_days': visitors,
        'visitor_days_since': ad.ANON_SINCE.isoformat(),
        'google_signups': GoogleAccount.objects.filter(user_id__in=ids).values('user_id').distinct().count(),
        'median_days_to_first_work': _round(_quantile(delays, 0.5), 1),
        'median_hours_to_onboarding': _round(_quantile(onboarding_delays, 0.5), 1),
        'onboarding_steps_unfinished': [{'step': s, 'members': c} for s, c in sorted(steps.items())],
    }


# ─────────────────────────────── 5. Rétention

def _retention(ctx):
    monday = ctx.today - timedelta(days=ctx.today.weekday())
    oldest = monday - timedelta(weeks=RETENTION_WEEKS - 1)
    since = timezone.make_aware(datetime.combine(oldest, time.min))
    joined = {uid: ad._day(d) for uid, d in ctx.real.filter(date_joined__gte=since).values_list('id', 'date_joined')}
    active = ad._active_days(list(joined), since) if joined else {}
    cohorts = []
    for i in range(RETENTION_WEEKS):
        week = oldest + timedelta(weeks=i)
        members = [u for u, d in joined.items() if week <= d < week + timedelta(days=7)]
        weeks = []
        for k in range(5):
            # Semaine k entièrement écoulée seulement : une semaine à peine commencée ferait baisser le taux à tort.
            eligible = [u for u in members if joined[u] + timedelta(days=7 * k + 6) <= ctx.today]
            back = [u for u in eligible if any(joined[u] + timedelta(days=7 * k) <= d < joined[u] + timedelta(days=7 * k + 7)
                                               for d in active.get(u, ()))]
            weeks.append({'week': k, 'eligible': len(eligible), 'active': len(back),
                          'rate': _pct(len(back), len(eligible)) if eligible else None})
        cohorts.append({'week_of': week.isoformat(), 'signups': len(members), 'weeks': weeks})
    return {'cohorts': cohorts}


# ─────────────────────────────── 6. Contenus vus

def _contents(ctx):
    from apps.caracteristics.models import Chapter
    from apps.things.models import Content, ContentDailyView
    from apps.users.models import ViewHistory
    views = {r['content_id']: r for r in ContentDailyView.objects.filter(date__gte=ctx.first).values('content_id')
             .annotate(v=Sum('count'), a=Sum('anon_count'))}
    readers = dict(ViewHistory.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q, viewed_at__gte=ctx.start)
                   .values_list('object_id').annotate(r=Count('user_id', distinct=True)))
    contents = {c.id: c for c in Content.objects.only('id', 'type', 'title')}
    rows = [{**_ref(c), 'views': (views.get(cid) or {}).get('v') or 0, 'anon': (views.get(cid) or {}).get('a') or 0,
             'readers': readers.get(cid, 0)} for cid, c in contents.items()]
    seen = sorted((r for r in rows if r['views']), key=lambda r: (-r['views'], -r['readers'], r['id']))
    unseen = [r for r in rows if not r['views']]
    chapter_of = defaultdict(set)
    for cid, ch in Content.chapters.through.objects.values_list('content_id', 'chapter_id'):
        chapter_of[ch].add(cid)
    unseen_ids = {r['id'] for r in unseen}
    chapters = {c.id: c for c in Chapter.objects.filter(id__in=list(chapter_of)).prefetch_related('class_levels')}
    by_chapter = []
    for ch, cids in chapter_of.items():
        if ch in chapters and cids & unseen_ids:
            c = chapters[ch]
            by_chapter.append({'chapter_id': ch, 'chapter': c.name,
                               'levels': ', '.join(sorted(lv.name for lv in c.class_levels.all())),
                               'unviewed': len(cids & unseen_ids), 'total': len(cids)})
    by_chapter.sort(key=lambda x: (-x['unviewed'], x['chapter']))
    return {
        'measured_since': ad.VIEWS_SINCE.isoformat(),
        'viewed': seen,   # du plus vu au moins vu (au moins une vue)
        'unviewed_by_type': dict(Counter(r['type'] for r in unseen)),
        'unviewed_by_chapter': by_chapter,
    }


# ─────────────────────────────── 7. Réussite réelle face à la difficulté affichée

def _difficulty(ctx):
    from apps.interactions.models import Complete, QuestionProgress
    from apps.things.models import Content, DifficultyFeedback
    from apps.things.views import _walk_questions_meta
    from apps.users.my_stats import _questions

    per_pair = defaultdict(list)
    sources = Counter()
    for uid, oid, path, status, source, created in (
            QuestionProgress.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q)
            .values_list('user_id', 'object_id', 'question_path', 'status', 'source', 'created_at')):
        per_pair[(uid, oid)].append((path, status, source, created))
        if created and created >= ctx.start:
            sources[source] += 1
    completes = {}
    for uid, oid, status in Complete.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q).values_list(
            'user_id', 'object_id', 'status'):
        if str(oid).isdigit():
            completes[(uid, int(oid))] = status
    ids = {oid for _, oid in per_pair} | {oid for _, oid in completes}
    contents = {c.id: c for c in Content.objects.filter(id__in=ids, type__in=('exercise', 'exam'))
                .only('id', 'type', 'title', 'difficulty', 'json_content', 'author')}
    # Questions finales (chemins de QuestionProgress), comme things/difficulty.py : une question mère ou un
    # ancien chemin ne compte pas.
    finals = {cid: {path for path, _, _ in _questions(c.json_content)} for cid, c in contents.items()}

    tagged_since = timezone.make_aware(datetime.combine(AUDIT_SINCE, time.min))

    def is_batch(rows):
        """Lot « Tout réussi » : marqué depuis le 10/10/2026 ; avant, deviné (tout réussi à moins de 2 s d'écart)."""
        if all(s == 'tout' for _, _, s, _ in rows):
            return True
        times = [c for _, _, _, c in rows if c]
        if len(rows) < 2 or len(times) < len(rows) or max(times) >= tagged_since:
            return False
        return all(st == 'success' for _, st, _, _ in rows) and (max(times) - min(times)).total_seconds() <= BATCH_SECONDS

    stats = defaultdict(lambda: {'students': 0, 'w': 0.0, 'r': 0.0, 'w_raw': 0.0, 'r_raw': 0.0,
                                 'w_clean': 0.0, 'r_clean': 0.0, 'batch': 0})
    per_question = defaultdict(lambda: {'users': 0, 'score': 0.0})
    for key in set(per_pair) | set(completes):
        uid, cid = key
        c = contents.get(cid)
        if c is None or uid == c.author_id:   # l'auteur ne juge pas son propre contenu (things/difficulty.py)
            continue
        fin = finals.get(cid) or set()
        rows = [x for x in per_pair.get(key, []) if x[1] in SCORE and x[0] in fin]
        batch = bool(rows) and is_batch(rows)
        if not batch:   # questions les moins réussies : chaque réponse hors lot « Tout réussi »
            for path, st, _, _ in rows:
                q = per_question[(cid, path)]
                q['users'] += 1
                q['score'] += SCORE[st]
        if rows and len(rows) >= max(1, math.ceil(len(fin) / 2)):
            r = sum(SCORE[st] for _, st, _, _ in rows) / len(rows)
        elif completes.get(key) in COMPLETE_SCORE:
            r, batch = COMPLETE_SCORE[completes[key]], False
        else:
            continue
        s = stats[cid]
        w = 0.5 if batch else 1.0
        s['students'] += 1
        s['batch'] += batch
        s['w'] += w
        s['r'] += w * r
        s['w_raw'] += 1
        s['r_raw'] += r
        if not batch:
            s['w_clean'] += 1
            s['r_clean'] += r

    rows_out = []
    for cid, s in stats.items():
        c = contents[cid]
        r = s['r'] / s['w']
        lo, hi = _wilson(r, s['w'])
        row = {**_ref(c), 'declared': c.difficulty, 'n': s['students'], 'batch_students': s['batch'],
               'success': _round(r), 'success_raw': _round(s['r_raw'] / s['w_raw']),
               'success_without_batch': _round(s['r_clean'] / s['w_clean']) if s['w_clean'] else None,
               'wilson80': [_round(lo), _round(hi)], 'observed': _band(r), 'gap': None}
        band = BANDS.get(c.difficulty)
        if band and s['students'] >= ctx.min_students:
            if hi < band[0]:
                row['gap'] = {'direction': 'harder', 'distance': _round(band[0] - hi)}
            elif lo >= band[1]:
                row['gap'] = {'direction': 'easier', 'distance': _round(lo - band[1])}
        rows_out.append(row)

    # Par difficulté affichée et par type
    totals = Counter((t, d) for t, d in Content.objects.filter(type__in=('exercise', 'exam')).values_list('type', 'difficulty'))
    review = defaultdict(Counter)
    for (uid, cid), st in completes.items():
        if cid in contents:
            review[(contents[cid].type, contents[cid].difficulty)][st] += 1
    groups = []
    for (t, d), total in sorted(totals.items(), key=lambda x: (x[0][0], list(BANDS).index(x[0][1]) if x[0][1] in BANDS else 9)):
        mine = [r for r in rows_out if r['type'] == t and r['declared'] == d]
        enough = [r for r in mine if r['n'] >= ctx.min_students]
        clean = [r['success_without_batch'] for r in enough if r['success_without_batch'] is not None]
        rv = review[(t, d)]
        groups.append({
            'type': t, 'declared': d, 'contents': total, 'with_data': len(mine),
            'with_min_students': len(enough), 'with_8_students': sum(1 for r in mine if r['n'] >= 8),
            'mean_success': _round(sum(r['success'] for r in enough) / len(enough)) if enough else None,
            'mean_success_without_batch': _round(sum(clean) / len(clean)) if clean else None,
            'review_share': _pct(rv['review'], rv['review'] + rv['success']),
        })

    gaps = sorted((r for r in rows_out if r['gap']), key=lambda r: (-r['gap']['distance'], -r['n'], r['id']))

    # Questions les moins réussies (hors lots « Tout réussi »)
    meta = {}
    for cid, c in contents.items():
        for path, label, m in _walk_questions_meta(c.json_content):
            meta[(cid, path)] = (label, m.get('difficulty'))
    questions = []
    for (cid, path), q in per_question.items():
        if q['users'] < ctx.min_students:
            continue
        label, qdiff = meta.get((cid, path), (path, None))
        r = q['score'] / q['users']
        questions.append({**_ref(contents[cid]), 'question_path': path, 'label': label, 'declared': qdiff,
                          'n': q['users'], 'success': _round(r), 'wilson80': [_round(x) for x in _wilson(r, q['users'])]})
    questions.sort(key=lambda q: (q['success'], -q['n']))

    # Ressenti donné par les élèves (DifficultyFeedback, depuis le 10/10/2026)
    fb = DifficultyFeedback.objects.filter(user_id__in=ctx.real_q)
    matrix = defaultdict(Counter)
    for declared, felt, n in fb.values_list('declared', 'felt').annotate(n=Count('id')):
        matrix[declared][felt] += n
    by_content = defaultdict(Counter)
    for cid, felt, n in fb.values_list('content_id', 'felt').annotate(n=Count('id')):
        by_content[cid][felt] += n
    top_fb = sorted(by_content.items(), key=lambda x: (-sum(x[1].values()), x[0]))
    fb_contents = {c.id: c for c in Content.objects.filter(id__in=[cid for cid, _ in top_fb[:ctx.top]])
                   .only('id', 'type', 'title', 'difficulty')}
    felt_targets = [contents[g['id']] for g in gaps[:ctx.top]] + list(fb_contents.values())
    felt, felt_error = _felt_for(list({c.id: c for c in felt_targets}.values()))

    def felt_level(cid):
        f = felt.get(cid)
        return f.get('level') if isinstance(f, dict) else None

    for g in gaps:
        g['felt'] = felt_level(g['id'])
    feedback_rows = []
    for cid, cnt in top_fb[:ctx.top]:
        if cid in fb_contents:
            c = fb_contents[cid]
            feedback_rows.append({**_ref(c), 'declared': c.difficulty, 'votes': {k: cnt.get(k, 0) for k in FELT_LABEL},
                                  'n': sum(cnt.values()), 'felt': felt_level(cid)})
    period = fb.filter(created_at__gte=ctx.start)
    return {
        'min_students': ctx.min_students,
        'rule': ('R par élève = (réussi + ½ en partie) / questions évaluées s’il en a évalué au moins la moitié '
                 '(questions finales, auteur du contenu exclu), sinon '
                 'contenu terminé (réussi = 1, à revoir = 0,25) ; poids ½ pour un lot « Tout réussi ». '
                 'Bandes : facile ≥ 70 %, moyen 40–70 %, difficile < 40 % ; écart si la borne de Wilson à 80 % '
                 'sort entièrement de la bande affichée.'),
        'assessment_sources': {k: sources.get(k, 0) for k in SOURCE_LABEL},
        'by_difficulty': groups,
        'gaps': gaps,
        'contents': sorted(rows_out, key=lambda r: (-r['n'], r['id'])),
        'hardest_questions': questions,
        'feedback': {
            'total': fb.count(), 'period': period.count(),
            'students_period': period.values('user_id').distinct().count(),
            'by_declared': [{'declared': d, **{k: matrix[d].get(k, 0) for k in FELT_LABEL}}
                            for d in sorted(matrix, key=lambda d: list(BANDS).index(d) if d in BANDS else 9)],
            'top_contents': feedback_rows,
        },
        'felt_error': felt_error,
    }


# ─────────────────────────────── 8. Solutions

def _solutions(ctx):
    from apps.interactions.models import QuestionProgress, SolutionView
    from apps.things.models import Content
    from apps.users.models import UsageDaily, ViewHistory
    usage = dict(UsageDaily.objects.filter(date__gte=ctx.first).filter(
        Q(kind=UsageDaily.KIND_ACTION, name__in=['voir-solution', 'toutes-solutions'])
        | Q(kind=UsageDaily.KIND_PAGE, name__in=['/exercises/:id', '/exams/:id'])).values_list('name').annotate(c=Sum('count')))
    pages = usage.get('/exercises/:id', 0) + usage.get('/exams/:id', 0)
    opened = dict(SolutionView.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q, viewed_at__gte=ctx.start)
                  .values_list('object_id').annotate(n=Count('id')))
    readers = dict(ViewHistory.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q, object_id__in=list(opened))
                   .values_list('object_id').annotate(r=Count('user_id', distinct=True)))
    validations = QuestionProgress.objects.filter(content_type=ctx.ct, user_id__in=ctx.real_q).exclude(solution_validation=None)
    not_understood = list(validations.filter(solution_validation='not-understood').values('object_id', 'question_path')
                          .annotate(n=Count('id')).order_by('-n', 'object_id'))
    contents = {c.id: c for c in Content.objects.filter(id__in=set(opened) | {r['object_id'] for r in not_understood})
                .only('id', 'type', 'title')}
    per_content = sorted(({**_ref(contents[cid]), 'members': n, 'readers': readers.get(cid, 0),
                           'share': _pct(n, readers.get(cid, 0))} for cid, n in opened.items() if cid in contents),
                         key=lambda r: (-r['members'], r['id']))
    return {
        'global': {'show_solution': usage.get('voir-solution', 0), 'show_all': usage.get('toutes-solutions', 0),
                   'content_pages': pages,
                   'per_100_pages': _round((usage.get('voir-solution', 0) + usage.get('toutes-solutions', 0)) * 100 / pages, 1)
                   if pages else None},
        'per_content': per_content,
        'per_content_since': AUDIT_SINCE.isoformat(),
        'validations': dict(validations.values_list('solution_validation').annotate(n=Count('id'))),
        'not_understood': [{**_ref(contents[r['object_id']]), 'question_path': r['question_path'], 'n': r['n']}
                           for r in not_understood if r['object_id'] in contents],
    }


# ─────────────────────────────── 9. Signalements

def _reports(ctx):
    from apps.things.models import Content, ContentDailyView, ContentReport
    period = ContentReport.objects.filter(created_at__gte=ctx.start, user_id__in=ctx.real_q)
    reasons = dict(ContentReport.REASON_CHOICES)
    by_reason = [{'reason': r, 'label': reasons.get(r, r), 'n': n}
                 for r, n in period.values_list('reason').annotate(n=Count('id')).order_by('-n')]
    open_rows = list(ContentReport.objects.filter(status=ContentReport.STATUS_OPEN)
                     .values('content_id', 'item_path', 'item_label').annotate(n=Count('id')).order_by('-n', 'content_id'))
    per_content = dict(period.values_list('content_id').annotate(n=Count('id')))
    views = dict(ContentDailyView.objects.filter(date__gte=ctx.first, content_id__in=list(per_content))
                 .values_list('content_id').annotate(v=Sum('count')))
    contents = {c.id: c for c in Content.objects.filter(id__in=set(per_content) | {r['content_id'] for r in open_rows})
                .only('id', 'type', 'title')}
    rate = sorted(({**_ref(contents[cid]), 'reports': n, 'views': views.get(cid, 0),
                    'per_100_views': _round(n * 100 / views[cid], 1) if views.get(cid) else None}
                   for cid, n in per_content.items() if cid in contents),
                  key=lambda r: (-(r['per_100_views'] or 0), -r['reports'], r['id']))
    return {
        'period_total': sum(per_content.values()),
        'by_reason': by_reason,
        'open': [{**_ref(contents[r['content_id']]), 'item_path': r['item_path'], 'item_label': r['item_label'],
                  'n': r['n']} for r in open_rows if r['content_id'] in contents],
        'per_100_views': rate,
    }


# ─────────────────────────────── 10. Temps passé

def _time(ctx):
    from apps.interactions.models import StudyTimeDay, TimeSession
    from apps.things.models import Content
    from apps.things.views import _walk_questions_meta
    # Temps d'un élève sur un contenu pendant la période (plafonné), sans les jours où le cumul d'avant a été rattaché.
    pairs = (StudyTimeDay.objects.filter(user_id__in=ctx.real_q, date__gte=max(ctx.first, ctx.study_since))
             .values('user_id', 'object_id').annotate(s=Sum('seconds')).values_list('user_id', 'object_id', 's'))
    per_content = defaultdict(list)
    for _uid, cid, s in pairs:
        per_content[cid].append(min(s or 0, TIME_CAP))
    contents = {c.id: c for c in Content.objects.filter(id__in=list(per_content))
                .only('id', 'type', 'difficulty', 'duration_minutes', 'json_content')}
    groups = defaultdict(lambda: {'pairs': [], 'medians': [], 'expected': [], 'durations': []})
    for cid, values in per_content.items():
        c = contents.get(cid)
        if not c:
            continue
        g = groups[(c.type, c.difficulty)]
        g['pairs'].extend(values)
        g['medians'].append(_quantile(values, 0.5))
        expected = sum(m.get('expected_seconds') for _, _, m in _walk_questions_meta(c.json_content)
                       if isinstance(m.get('expected_seconds'), (int, float)) and m.get('expected_seconds') > 0)
        if expected:
            g['expected'].append(expected)
        if c.type == 'exam' and c.duration_minutes:
            g['durations'].append(c.duration_minutes)

    def minutes(x):
        return None if x is None else round(x / 60, 1)

    by_difficulty = []
    for (t, d), g in sorted(groups.items(), key=lambda x: (x[0][0] or '', list(BANDS).index(x[0][1]) if x[0][1] in BANDS else 9)):
        by_difficulty.append({
            'type': t, 'declared': d, 'contents': len(g['medians']), 'pairs': len(g['pairs']),
            'median_minutes': minutes(_quantile(g['pairs'], 0.5)), 'p75_minutes': minutes(_quantile(g['pairs'], 0.75)),
            'median_of_content_medians': minutes(_quantile(g['medians'], 0.5)),
            'expected_minutes': minutes(_quantile(g['expected'], 0.5)),
            'exam_duration_minutes': _quantile(g['durations'], 0.5),
        })
    chrono = defaultdict(list)
    for kind, duration in TimeSession.objects.filter(user_id__in=ctx.real_q, created_at__gte=ctx.start).values_list(
            'session_type', 'session_duration'):
        if duration:
            chrono[kind].append(min(duration.total_seconds(), 4 * 3600))
    return {
        'cap_minutes': TIME_CAP // 60,
        'clean_since': ctx.study_since.isoformat(),
        'by_difficulty': by_difficulty,
        'chrono': [{'session_type': k, 'n': len(v), 'median_minutes': minutes(_quantile(v, 0.5))}
                   for k, v in sorted(chrono.items())],
    }


def build_report(days=30, top=20, min_students=5):
    """Rapport complet (dict sérialisable en JSON). À appeler en lecture seule (voir Command.handle)."""
    ctx = _Ctx(days, top, min_students)
    return {
        'generated_at': timezone.now().isoformat(),
        'days': days, 'from': ctx.first.isoformat(), 'to': ctx.today.isoformat(),
        'top': top, 'min_students': min_students,
        'sections': {
            'couverture': _coverage(ctx),
            'fonctionnalites': _features(ctx),
            'pages': _pages(ctx),
            'entonnoir': _funnel(ctx),
            'retention': _retention(ctx),
            'contenus': _contents(ctx),
            'difficulte': _difficulty(ctx),
            'solutions': _solutions(ctx),
            'signalements': _reports(ctx),
            'temps': _time(ctx),
        },
    }


# ─────────────────────────────── Markdown

def _cell(v):
    if v is None:
        return '—'
    if isinstance(v, float):
        v = f'{v:g}'.replace('.', ',')
    return str(v).replace('|', '\\|').replace('\n', ' ')


def _table(headers, rows):
    if not rows:
        return ['_(rien)_', '']
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    out += ['| ' + ' | '.join(_cell(c) for c in row) + ' |' for row in rows]
    return out + ['']


def _p(x):
    return '—' if x is None else f'{round(x * 100)} %'


def _n(count, word):
    """« 1 signalement », « 3 signalements »."""
    return f'{count} {word}{"s" if count > 1 else ""}'


def _title(r):
    return f"{TYPE_LABEL.get(r['type'], r['type'])} #{r['id']} {r['title']}"


def render_md(rep):
    top = rep['top']
    s = rep['sections']
    out = [f"# Audit d’usage Fidni — {rep['days']} derniers jours (du {rep['from']} au {rep['to']})", '',
           f"Généré le {rep['generated_at'][:16].replace('T', ' ')}. Comptes maison exclus. Lecture seule. "
           f"Listes limitées à {top} lignes (tout est dans --format json).", '']

    c = s['couverture']
    out += ['## 1. Couverture des mesures', '']
    out += _table(['Source', 'Mesurée depuis', 'Jours mesurés sur la période'],
                  [[x['source'], x['since'] or 'toujours', x['measured_days']] for x in c['sources']])
    p = c['population']
    out += [f"Membres réels : **{p['members']}** ({_n(p['students'], 'élève')}, {_n(p['teachers'], 'prof')}) · nouveaux sur la "
            f"période : {p['new']} · actifs sur la période : {p['active']} · élèves sans niveau : "
            f"{p['students_without_level']} · liés à Google : {p['google_linked']}", '']
    out += _table(['Niveau', 'Élèves'], [[x['level'], x['students']] for x in p['by_level']])

    f = s['fonctionnalites']
    out += ['## 2. Fonctionnalités et gestes (les moins utilisés en tête)', '', '### En base (membres distincts)', '']
    out += _table(['Fonctionnalité', 'Membres', '% des membres', 'Usages', 'Période d’avant'],
                  [[x['label'], x['users'], x['users_share'], x['actions'], x['previous']] for x in f['base']])
    out += ['### Gestes du navigateur', '',
            '« Personnes-jours » : une personne venue 3 jours compte 3. « Par jour » : moyenne par jour mesuré.', '']
    out += _table(['Geste', 'Fois', 'Par jour', 'Personnes-jours', 'Non connectés', 'Mesuré depuis'],
                  [[x['label'], x['count'], x['per_day'], x['visits'], x['anon'], x['measured_since']]
                   for x in f['gestures'] if not x['filter']])
    out += [f"Jamais utilisés sur la période : {', '.join(f['gestures_never_used']) or 'aucun'}", '']
    out += ['### Portes d’entrée de la fenêtre de connexion', '']
    out += _table(['Porte', 'Ouvertures', 'Par jour', 'Non connectés'],
                  [[x['source'], x['count'], x['per_day'], x['anon']] for x in f['auth_doors'][:top]])
    out += ['### Filtres des listes', '']
    out += _table(['Filtre', 'Fois', 'Par jour'],
                  [[x['label'], x['count'], x['per_day']] for x in f['gestures'] if x['filter']])
    out += _table(['Liste', 'Filtre', 'Valeur', 'Fois', 'Non connectés'],
                  [[TYPE_LABEL.get(x['type'], x['type']), x['filter'], x['label'], x['count'], x['anon']]
                   for x in f['filter_values'][:top]])

    pg = s['pages']
    out += ['## 3. Pages (les moins vues en tête)', '']
    site = pg['site']
    out += [f"Site : {site['visits']} personnes-jours ({_cell(site['visits_per_day'])} par jour), dont {site['anon_visits']} "
            f"non connectées ({_cell(site['anon_visits_per_day'])} par jour mesuré) ; {site['pages']} pages vues.", '']
    out += _table(['Page', 'Motif', 'Vues', 'Par jour', 'Personnes-jours', 'Non connectés', 'Mesurée depuis'],
                  [[x['label'], x['page'], x['views'], x['per_day'], x['visits'], x['anon'], x['measured_since']]
                   for x in pg['pages']])
    out += [f"Jamais vues : {', '.join(pg['never_viewed']) or 'aucune'}", '']
    an = pg['anonymous']
    out += [f"Visiteurs non connectés (depuis le {an['since']}) : {an['current']['visits']} personnes-jours, "
            f"{an['current']['pages']} pages, {an['current']['contents']} contenus vus ; {an['signups']} inscriptions.", '']
    out += _table(['Contenu le plus vu sans compte', 'Vues sans compte', 'Vues en tout'],
                  [[_title(x), x['views'], x['total']] for x in an['top_contents'][:top]])

    fu = s['entonnoir']
    out += ['## 4. Entonnoir (inscrits sur la période)', '']
    out += _table(['Étape', 'Membres', '% des inscrits'], [
        ['Visiteurs non connectés (personnes-jours, depuis le ' + fu['visitor_days_since'] + ')', fu['visitor_days'], None],
        ['Inscrits', fu['signups'], 100 if fu['signups'] else None],
        ['… dont avec Google', fu['google_signups'], _pct(fu['google_signups'], fu['signups'])],
        ['E-mail confirmé', fu['verified'], fu['rates']['verified']],
        ['Profil complété (onboarding)', fu['onboarded'], fu['rates']['onboarded']],
        ['Un contenu ouvert', fu['first_view'], fu['rates']['first_view']],
        ['Une auto-évaluation ou un contenu terminé', fu['first_work'], fu['rates']['first_work']],
        [f"Revenus entre J+7 et J+13 (sur {_n(fu['d7_eligible'], 'inscrit')} depuis au moins 7 j)", fu['back_d7'],
         fu['back_d7_rate']],
    ])
    out += [f"Délai médian inscription → 1er travail : {_cell(fu['median_days_to_first_work'])} j · "
            f"inscription → profil complété : {_cell(fu['median_hours_to_onboarding'])} h", '']
    out += _table(['Étape d’onboarding atteinte (profil non complété)', 'Membres'],
                  [[x['step'], x['members']] for x in fu['onboarding_steps_unfinished']])

    out += ['## 5. Rétention hebdomadaire (cohortes des 8 dernières semaines)', '',
            'Part des inscrits de la semaine actifs la semaine k après leur inscription (dates stables seulement ; '
            'une semaine pas encore finie reste vide).', '']
    out += _table(['Semaine du', 'Inscrits', 'S0', 'S1', 'S2', 'S3', 'S4'],
                  [[x['week_of'], x['signups']] + [f"{w['rate']} %" if w['rate'] is not None else None for w in x['weeks']]
                   for x in s['retention']['cohorts']])

    co = s['contenus']
    out += ['## 6. Contenus les plus et les moins vus', '', f"Vues mesurées depuis le {co['measured_since']} "
            '(visiteurs compris) ; « membres » = élèves distincts (borne basse).', '']
    out += _table(['Plus vus', 'Vues', 'Sans compte', 'Membres'],
                  [[_title(x), x['views'], x['anon'], x['readers']] for x in co['viewed'][:top]])
    out += _table(['Moins vus (au moins une vue)', 'Vues', 'Membres'],
                  [[_title(x), x['views'], x['readers']] for x in co['viewed'][::-1][:top]])
    unviewed = ', '.join(f'{TYPE_LABEL.get(k, k)} {v}' for k, v in co['unviewed_by_type'].items())
    out += [f"Jamais vus sur la période : {unviewed or 'aucun'}", '']
    out += _table(['Chapitre', 'Niveaux', 'Contenus jamais vus', 'Contenus'],
                  [[x['chapter'], x['levels'], x['unviewed'], x['total']] for x in co['unviewed_by_chapter'][:top]])

    d = s['difficulte']
    out += ['## 7. Réussite réelle face à la difficulté affichée', '', d['rule'], '']
    out += _table(['Type', 'Difficulté affichée', 'Contenus', 'Avec données', f"≥ {d['min_students']} élèves",
                   '≥ 8 élèves', 'R moyen', 'R sans « Tout réussi »', '« À revoir » (contenus terminés)'],
                  [[TYPE_LABEL.get(x['type'], x['type']), DIFF_LABEL.get(x['declared'], x['declared']), x['contents'],
                    x['with_data'], x['with_min_students'], x['with_8_students'], _p(x['mean_success']),
                    _p(x['mean_success_without_batch']), None if x['review_share'] is None else f"{x['review_share']} %"]
                   for x in d['by_difficulty']])
    src = d['assessment_sources']
    out += ['Origine des auto-évaluations de la période (depuis le 10/10/2026) : '
            + ', '.join(f"{SOURCE_LABEL[k]} {v}" for k, v in src.items()), '']
    out += ['### Écarts (la réussite sort de la bande affichée)', '']
    if d['felt_error']:
        out += [f"_Ressenti des élèves indisponible : {d['felt_error']}._", '']
    out += _table(['Contenu', 'Affiché', 'Observé', 'Élèves', 'R', 'Wilson 80 %', 'R sans « Tout réussi »', 'Ressenti'],
                  [[_title(x), DIFF_LABEL.get(x['declared']), DIFF_LABEL.get(x['observed']), x['n'], _p(x['success']),
                    f"{_p(x['wilson80'][0])} – {_p(x['wilson80'][1])}", _p(x['success_without_batch']),
                    DIFF_LABEL.get(x['felt']) if x.get('felt') else None] for x in d['gaps'][:top]])
    out += ['### Questions les moins réussies (hors lots « Tout réussi »)', '']
    out += _table(['Contenu', 'Question', 'Difficulté de la question', 'Élèves', 'R'],
                  [[_title(x), x['label'], DIFF_LABEL.get(x['declared'], x['declared']), x['n'], _p(x['success'])]
                   for x in d['hardest_questions'][:top]])
    fb = d['feedback']
    out += ['### Ressenti donné par les élèves', '',
            f"{fb['total']} avis en tout, {fb['period']} sur la période par {fb['students_period']} élèves.", '']
    out += _table(['Difficulté affichée', 'Plus facile', 'Comme annoncé', 'Plus dur'],
                  [[DIFF_LABEL.get(x['declared'], x['declared'])] + [x[k] for k in FELT_LABEL] for x in fb['by_declared']])
    out += _table(['Contenu', 'Affiché', 'Plus facile', 'Comme annoncé', 'Plus dur', 'Ressenti calculé'],
                  [[_title(x), DIFF_LABEL.get(x['declared'])] + [x['votes'][k] for k in FELT_LABEL]
                   + [DIFF_LABEL.get(x['felt']) if x['felt'] else None] for x in fb['top_contents']])

    so = s['solutions']
    g = so['global']
    out += ['## 8. Solutions ouvertes', '',
            f"« Voir la solution » : {g['show_solution']} · « Voir les solutions » : {g['show_all']} · pages d’exercice "
            f"et d’examen vues : {g['content_pages']} → {_cell(g['per_100_pages'])} ouvertures pour 100 pages.", '',
            f"Par contenu (membres, depuis le {so['per_content_since']} : avant, rien n’était enregistré) :", '']
    out += _table(['Contenu', 'Membres qui ont ouvert une solution', 'Lecteurs membres', '%'],
                  [[_title(x), x['members'], x['readers'], x['share']] for x in so['per_content'][:top]])
    out += ['Avis sur les solutions : ' + (', '.join(f"{VALIDATION_LABEL.get(k, k)} {v}" for k, v in so['validations'].items())
                                           or 'aucun'), '']
    out += _table(['« Solution pas comprise »', 'Question', 'Fois'],
                  [[_title(x), x['question_path'], x['n']] for x in so['not_understood'][:top]])

    r = s['signalements']
    out += ['## 9. Signalements', '', f"{_n(r['period_total'], 'signalement')} sur la période (élèves).", '']
    out += _table(['Motif', 'Signalements'], [[x['label'], x['n']] for x in r['by_reason']])
    out += _table(['Contenu', 'Signalements', 'Vues', 'Pour 100 vues'],
                  [[_title(x), x['reports'], x['views'], x['per_100_views']] for x in r['per_100_views'][:top]])
    out += _table(['Encore à traiter', 'Où', 'Signalements'],
                  [[_title(x), x['item_label'] or x['item_path'] or 'tout le contenu', x['n']] for x in r['open'][:top]])

    t = s['temps']
    out += ['## 10. Temps passé par difficulté', '',
            f"Temps d’étude automatique par élève et par contenu, plafonné à {t['cap_minutes']} min, à partir du "
            f"{t['clean_since']} (avant, le temps cumulé a été rattaché en bloc au dernier jour d’activité).", '']
    out += _table(['Type', 'Difficulté', 'Contenus', 'Élève × contenu', 'Médiane (min)', '75 % (min)',
                   'Durée attendue (min)', 'Durée d’épreuve (min)'],
                  [[TYPE_LABEL.get(x['type'], x['type']), DIFF_LABEL.get(x['declared'], x['declared']), x['contents'],
                    x['pairs'], x['median_minutes'], x['p75_minutes'], x['expected_minutes'], x['exam_duration_minutes']]
                   for x in t['by_difficulty']])
    out += _table(['Chrono (type de session)', 'Sessions', 'Médiane (min)'],
                  [[x['session_type'], x['n'], x['median_minutes']] for x in t['chrono']])
    return '\n'.join(out).rstrip() + '\n'


class Command(BaseCommand):
    help = "Rapport d'audit d'usage (lecture seule) : fonctionnalités, pages, entonnoir, rétention, difficulté…"

    def add_arguments(self, parser):
        parser.add_argument('--jours', type=int, default=30, help='Période : les N derniers jours (défaut 30).')
        parser.add_argument('--format', choices=['md', 'json'], default='md', dest='fmt',
                            help='md (lisible) ou json (complet).')
        parser.add_argument('--sortie', default=None, help='Fichier où écrire le rapport (sinon la sortie standard).')
        parser.add_argument('--top', type=int, default=20, help='Lignes par tableau en md (défaut 20).')
        parser.add_argument('--min-eleves', type=int, default=5, dest='min_eleves',
                            help='Élèves minimum pour juger la réussite d’un contenu (défaut 5).')

    def handle(self, *args, jours=30, fmt='md', sortie=None, top=20, min_eleves=5, **options):
        if jours < 1 or top < 1 or min_eleves < 1:
            raise CommandError('--jours, --top et --min-eleves doivent être positifs.')
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
            with _cache_lecture_seule():
                report = build_report(jours, top, min_eleves)
            transaction.set_rollback(True)   # rien à valider : on ne garde aucune trace
        text = (json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n' if fmt == 'json'
                else render_md(report))
        if sortie:
            with open(sortie, 'w', encoding='utf-8') as fh:
                fh.write(text)
            self.stdout.write(self.style.SUCCESS(f'Rapport écrit dans {sortie}'))
        else:
            self.stdout.write(text, ending='')
