"""Tableau de bord d'administration (« Pilotage ») : réservé aux administrateurs (superuser).

GET /api/pilotage/                 vue d'ensemble : chiffres clés, courbes sur 30 jours, fil d'activité…
GET /api/pilotage/utilisateurs/    liste des inscrits (recherche, tri, pages) avec leur activité

Uniquement des faits enregistrés. « Actif » = au moins une action enregistrée sur la période :
connexion, consultation d'un contenu, contenu terminé, question auto-évaluée, session de chrono, temps
d'étude, commentaire, solution proposée, test Skill IQ. Les visiteurs non connectés ne laissent aucune
trace côté serveur (voir Search Console pour eux).
Les comptes « maison » (administrateurs, compte éditorial, compte supprimé) sont exclus des statistiques.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.interactions.models import AICorrection, Complete, QuestionProgress, RevisionList, StudyTimeTracker, TimeSession
from apps.notebooks.models import Notebook
from apps.skilliq.models import SkillAssessment
from apps.things.models import Comment, Content, ProposedSolution
from apps.users.account_deletion import DELETED_USERNAME
from apps.users.legal import TERMS_VERSION
from apps.users.models import ViewHistory

SERIES_DAYS = 30
# Comptes de vérification automatique (captures, tests en production) : pas de vrais membres.
TEST_ACCOUNTS = ['fidni_test_claude']
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
TYPE_LABEL = {'exercise': 'Exercice', 'exam': 'Examen', 'lesson': 'Leçon'}


class IsSuperuser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def _house_filter():
    """Comptes à écarter des statistiques : administrateurs, compte éditorial, compte supprimé, comptes de test."""
    from apps.things.importing import EDITORIAL_USERNAME
    return Q(is_staff=True) | Q(is_superuser=True) | Q(username__in=[EDITORIAL_USERNAME, DELETED_USERNAME, *TEST_ACCOUNTS])


def _real_users():
    return User.objects.exclude(_house_filter())


# (queryset, champ de date, champ utilisateur) des actions qui comptent comme « activité ».
def _activity_sources():
    return [
        (ViewHistory.objects.all(), 'viewed_at', 'user_id'),
        (Complete.objects.all(), 'updated_at', 'user_id'),
        (QuestionProgress.objects.all(), 'assessed_at', 'user_id'),
        (TimeSession.objects.all(), 'created_at', 'user_id'),
        (StudyTimeTracker.objects.all(), 'recorded_at', 'user_id'),
        (Comment.objects.all(), 'created_at', 'author_id'),
        (ProposedSolution.objects.all(), 'created_at', 'author_id'),
        (SkillAssessment.objects.all(), 'completed_at', 'user_id'),
        (User.objects.all(), 'last_login', 'id'),
    ]


def _active_user_ids(since, real_ids):
    ids = set()
    for qs, field, ufield in _activity_sources():
        ids.update(qs.filter(**{f'{field}__gte': since}).values_list(ufield, flat=True))
    return ids & real_ids


def _last_activity(user_ids):
    """utilisateur → date de sa dernière action enregistrée."""
    last = {}
    for qs, field, ufield in _activity_sources():
        rows = qs.filter(**{f'{ufield}__in': user_ids}).values(ufield).annotate(m=Max(field))
        for row in rows:
            uid, when = row[ufield], row['m']
            if when and (uid not in last or when > last[uid]):
                last[uid] = when
    return last


def _day(dt):
    return timezone.localtime(dt).date()


def _content_index(content_type_ids_and_objects):
    """{(ct_id, object_id): Content} pour les éléments génériques pointant vers un contenu."""
    ct = ContentType.objects.get_for_model(Content)
    ids = {int(oid) for ct_id, oid in content_type_ids_and_objects if ct_id == ct.id and str(oid).isdigit()}
    return ct.id, {c.id: c for c in Content.objects.filter(id__in=ids).only('id', 'type', 'title')}


def _content_ref(content):
    if not content:
        return None
    return {'id': content.id, 'type': content.type, 'title': content.title,
            'url': f'/{TYPE_PATH.get(content.type, "exercises")}/{content.id}'}


def _age(birth, today):
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


@api_view(['GET'])
@permission_classes([IsSuperuser])
def overview(request):
    now = timezone.now()
    today = timezone.localdate()
    real = _real_users().select_related('profile', 'profile__class_level')
    real_ids = set(real.values_list('id', flat=True))
    since = {d: now - timedelta(days=d) for d in (1, 7, 30)}

    # ── Inscrits
    profiles = [u.profile for u in real if hasattr(u, 'profile')]
    users = {
        'total': len(real_ids),
        'students': sum(1 for p in profiles if p.user_type != 'teacher'),
        'teachers': sum(1 for p in profiles if p.user_type == 'teacher'),
        'new_7d': real.filter(date_joined__gte=since[7]).count(),
        'new_30d': real.filter(date_joined__gte=since[30]).count(),
        'active_1d': len(_active_user_ids(since[1], real_ids)),
        'active_7d': len(_active_user_ids(since[7], real_ids)),
        'active_30d': len(_active_user_ids(since[30], real_ids)),
        'onboarding_done': sum(1 for p in profiles if p.onboarding_completed),
        'email_verified': sum(1 for p in profiles if getattr(p, 'email_verified_at', None)),
        'terms_outdated': sum(1 for p in profiles if p.terms_version != TERMS_VERSION),
        'under_15': sum(1 for p in profiles if p.birth_date and _age(p.birth_date, today) < 15),
        'birth_date_missing': sum(1 for p in profiles if not p.birth_date),
        'never_active': 0,
    }
    last = _last_activity(real_ids)
    users['never_active'] = sum(1 for uid in real_ids if uid not in last)

    # ── Répartitions
    levels = Counter(p.class_level.name if p.class_level_id else 'Non renseigné'
                     for p in real_profiles(real))
    schools = Counter((p.school_name or '').strip() for p in profiles if (p.school_name or '').strip())
    genders = Counter({'M': 'Monsieur', 'F': 'Madame', 'N': 'Non précisé'}.get(p.gender, 'Non renseigné') for p in profiles)

    # ── Contenus
    content_counts = dict(Content.objects.values_list('type').annotate(n=Count('id')))
    content = {
        'exercises': content_counts.get('exercise', 0), 'lessons': content_counts.get('lesson', 0),
        'exams': content_counts.get('exam', 0),
        'new_30d': Content.objects.filter(created_at__gte=since[30]).count(),
        'total_views': Content.objects.aggregate(v=Sum('view_count'))['v'] or 0,
        'by_level': [{'name': n, 'count': c} for n, c in Content.objects.values_list('class_levels__name')
                     .annotate(c=Count('id', distinct=True)).order_by('-c') if n],
    }

    # ── Engagement sur 30 jours (comptes réels)
    def real_only(qs, ufield='user_id'):
        return qs.filter(**{f'{ufield}__in': real_ids})
    study = real_only(StudyTimeTracker.objects.filter(recorded_at__gte=since[30])).aggregate(s=Sum('time_spent_seconds'))['s'] or 0
    engagement = {
        'views': real_only(ViewHistory.objects.filter(viewed_at__gte=since[30])).count(),
        'completions': real_only(Complete.objects.filter(updated_at__gte=since[30])).count(),
        'completions_success': real_only(Complete.objects.filter(updated_at__gte=since[30], status='success')).count(),
        'questions_assessed': real_only(QuestionProgress.objects.filter(assessed_at__gte=since[30])).count(),
        'study_minutes': round(study / 60),
        'comments': real_only(Comment.objects.filter(created_at__gte=since[30]), 'author_id').count(),
        'proposed_solutions': real_only(ProposedSolution.objects.filter(created_at__gte=since[30]), 'author_id').count(),
        'skill_assessments': real_only(SkillAssessment.objects.filter(completed_at__gte=since[30])).count(),
        'revision_lists': real_only(RevisionList.objects.filter(created_at__gte=since[30])).count(),
        'notebooks': real_only(Notebook.objects.filter(created_at__gte=since[30])).count(),
        'ai_corrections': real_only(AICorrection.objects.filter(submitted_at__gte=since[30])).count(),
    }

    # ── Courbes jour par jour (30 jours)
    days = [today - timedelta(days=i) for i in range(SERIES_DAYS - 1, -1, -1)]
    start = since[30]
    signups = Counter(_day(d) for d in real.filter(date_joined__gte=start).values_list('date_joined', flat=True))
    active_by_day = defaultdict(set)
    for qs, field, ufield in _activity_sources():
        for uid, when in qs.filter(**{f'{field}__gte': start}).values_list(ufield, field):
            if uid in real_ids and when:
                active_by_day[_day(when)].add(uid)
    work = Counter(_day(d) for d in real_only(Complete.objects.filter(updated_at__gte=start)).values_list('updated_at', flat=True))
    work.update(_day(d) for d in real_only(QuestionProgress.objects.filter(assessed_at__gte=start)).values_list('assessed_at', flat=True))
    series = [{'date': d.isoformat(), 'signups': signups.get(d, 0), 'active': len(active_by_day.get(d, ())),
               'work': work.get(d, 0)} for d in days]

    # ── Contenus les plus consultés (30 jours, élèves distincts)
    ct_content = ContentType.objects.get_for_model(Content)
    top_rows = (real_only(ViewHistory.objects.filter(viewed_at__gte=since[30], content_type=ct_content))
                .values('object_id').annotate(readers=Count('user_id', distinct=True)).order_by('-readers')[:8])
    by_id = {c.id: c for c in Content.objects.filter(id__in=[r['object_id'] for r in top_rows]).only('id', 'type', 'title')}
    done = dict(real_only(Complete.objects.filter(content_type=ct_content, object_id__in=[str(r['object_id']) for r in top_rows]))
                .values_list('object_id').annotate(n=Count('id')))
    top_contents = [{**_content_ref(by_id[r['object_id']]), 'readers': r['readers'], 'completions': done.get(str(r['object_id']), 0)}
                    for r in top_rows if r['object_id'] in by_id]

    return Response({
        'generated_at': now.isoformat(),
        'users': users,
        'content': content,
        'engagement_30d': engagement,
        'series': series,
        'top_contents': top_contents,
        'levels': [{'name': n, 'count': c} for n, c in levels.most_common()],
        'schools': [{'name': n, 'count': c} for n, c in schools.most_common(8)],
        'genders': [{'name': n, 'count': c} for n, c in genders.most_common()],
        'recent_activity': recent_activity(real_ids, limit=40),
    })


def real_profiles(real):
    for u in real:
        p = getattr(u, 'profile', None)
        if p:
            yield p


def recent_activity(real_ids, limit=40):
    """Dernières actions des membres, toutes sources confondues, de la plus récente à la plus ancienne."""
    events = []
    names = {}

    def who(uid):
        return names.get(uid)

    for u in User.objects.filter(id__in=real_ids).order_by('-date_joined')[:limit]:
        events.append({'at': u.date_joined, 'kind': 'signup', 'user_id': u.id, 'label': 'Inscription'})
    generic = []
    for v in ViewHistory.objects.filter(user_id__in=real_ids).order_by('-viewed_at')[:limit]:
        generic.append(('view', v.viewed_at, v.user_id, v.content_type_id, v.object_id, None))
    for c in Complete.objects.filter(user_id__in=real_ids).order_by('-updated_at')[:limit]:
        generic.append(('complete', c.updated_at, c.user_id, c.content_type_id, c.object_id, c.status))
    ct_id, contents = _content_index([(g[3], g[4]) for g in generic])
    for kind, at, uid, ctid, oid, status in generic:
        content = contents.get(int(oid)) if ctid == ct_id and str(oid).isdigit() else None
        if not content:
            continue
        label = 'A consulté' if kind == 'view' else ('A réussi' if status == 'success' else 'À revoir :')
        events.append({'at': at, 'kind': kind, 'user_id': uid, 'label': label, 'content': _content_ref(content)})
    for c in Comment.objects.filter(author_id__in=real_ids).select_related('content_item').order_by('-created_at')[:limit]:
        events.append({'at': c.created_at, 'kind': 'comment', 'user_id': c.author_id, 'label': 'A commenté',
                       'content': _content_ref(c.content_item)})
    for s in ProposedSolution.objects.filter(author_id__in=real_ids).select_related('content_item').order_by('-created_at')[:limit]:
        events.append({'at': s.created_at, 'kind': 'solution', 'user_id': s.author_id, 'label': 'A proposé une solution',
                       'content': _content_ref(s.content_item)})
    for a in SkillAssessment.objects.filter(user_id__in=real_ids).select_related('chapter').order_by('-completed_at')[:limit]:
        events.append({'at': a.completed_at, 'kind': 'skilliq', 'user_id': a.user_id,
                       'label': f'Test Skill IQ : {a.chapter.name}' if a.chapter_id else 'Test Skill IQ'})
    events = sorted((e for e in events if e['at']), key=lambda e: e['at'], reverse=True)[:limit]
    names.update(User.objects.filter(id__in={e['user_id'] for e in events}).values_list('id', 'username'))
    for e in events:
        e['username'] = who(e.pop('user_id'))
        e['at'] = e['at'].isoformat()
    return events


SORTS = {'recent': '-date_joined', 'ancien': 'date_joined', 'nom': 'username'}


@api_view(['GET'])
@permission_classes([IsSuperuser])
def users_list(request):
    """Liste paginée des inscrits (comptes maison inclus mais signalés), avec leur activité."""
    q = (request.query_params.get('q') or '').strip()
    kind = request.query_params.get('type') or ''
    sort = request.query_params.get('tri') or 'recent'
    try:
        page = max(1, int(request.query_params.get('page') or 1))
    except ValueError:
        page = 1
    size = 25

    qs = User.objects.select_related('profile', 'profile__class_level').exclude(username=DELETED_USERNAME)
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q)
                       | Q(last_name__icontains=q) | Q(profile__school_name__icontains=q))
    if kind in ('student', 'teacher'):
        qs = qs.filter(profile__user_type=kind)
    elif kind == 'admin':
        qs = qs.filter(Q(is_staff=True) | Q(is_superuser=True))

    total = qs.count()
    ids_all = list(qs.values_list('id', flat=True))
    if sort == 'activite':
        last_all = _last_activity(ids_all)
        ordered = sorted(ids_all, key=lambda i: last_all.get(i) or datetime(1970, 1, 1, tzinfo=dt_timezone.utc), reverse=True)
        page_ids = ordered[(page - 1) * size: page * size]
        rows = {u.id: u for u in qs.filter(id__in=page_ids)}
        page_users = [rows[i] for i in page_ids if i in rows]
    else:
        page_users = list(qs.order_by(SORTS.get(sort, '-date_joined'))[(page - 1) * size: page * size])
    ids = [u.id for u in page_users]
    last = _last_activity(ids)

    def counts(qs_, ufield='user_id'):
        return dict(qs_.filter(**{f'{ufield}__in': ids}).values_list(ufield).annotate(n=Count('id')))
    views, completes = counts(ViewHistory.objects), counts(Complete.objects)
    assessed, comments = counts(QuestionProgress.objects), counts(Comment.objects, 'author_id')
    study = dict(StudyTimeTracker.objects.filter(user_id__in=ids).values_list('user_id').annotate(s=Sum('time_spent_seconds')))
    house = set(User.objects.filter(id__in=ids).filter(_house_filter()).values_list('id', flat=True))

    results = []
    for u in page_users:
        p = getattr(u, 'profile', None)
        results.append({
            'id': u.id, 'username': u.username, 'email': u.email,
            'full_name': f'{u.first_name} {u.last_name}'.strip(),
            'user_type': p.user_type if p else None,
            'class_level': p.class_level.name if p and p.class_level_id else None,
            'school': (p.school_name or None) if p else None,
            'date_joined': u.date_joined.isoformat(),
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'last_activity': last[u.id].isoformat() if u.id in last else None,
            'onboarding_completed': bool(p and p.onboarding_completed),
            'email_verified': bool(p and getattr(p, 'email_verified_at', None)),
            'is_admin': u.is_staff or u.is_superuser, 'is_house': u.id in house,
            'stats': {'views': views.get(u.id, 0), 'completions': completes.get(u.id, 0),
                      'questions': assessed.get(u.id, 0), 'comments': comments.get(u.id, 0),
                      'study_minutes': round((study.get(u.id) or 0) / 60)},
        })
    return Response({'count': total, 'page': page, 'pages': max(1, -(-total // size)), 'results': results})
