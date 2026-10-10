"""Tableau de bord d'administration (« Pilotage ») : réservé aux administrateurs (superuser).

GET /api/pilotage/?jours=7|30|90        aperçu : à traiter, 4 chiffres comparés à la période d'avant,
                                        leur courbe jour par jour, contenus les plus vus
GET /api/pilotage/utilisateurs/         membres (recherche, filtres actifs/nouveaux/jamais actifs/enseignants, tri, pages)
GET /api/pilotage/utilisateurs/<id>/    dernières actions d'un membre

Uniquement des faits enregistrés. « Actif » un jour donné = au moins une action datée par un champ qui ne
bouge plus (10/10/2026) : temps d'étude du jour, première auto-évaluation d'une question, contenu terminé,
chrono, commentaire, solution proposée, quiz de chapitre, concours, favoris, listes, cahier, DS annoncé…
Les dates écrasées à chaque passage (dernière consultation, dernière connexion) ne servent plus qu'à la
« dernière activité » de la liste des membres : sinon la période d'avant et la rétention sont sous-comptées.
`funnel` : entonnoir de la cohorte inscrite sur la période ; `auth_doors` : portes d'entrée de la fenêtre de
connexion ; `todo.difficulty_gaps` : contenus dont le ressenti des élèves s'écarte de la difficulté affichée.
Les visiteurs non connectés apparaissent dans les vues des contenus (ContentDailyView, depuis le 05/10/2026),
et à part dans le bloc `anonymes` (depuis le 09/10/2026 :
visiteurs distincts par jour, pages vues, contenus vus, gestes). `filter_values` : valeurs de filtre les plus
utilisées dans les listes (difficulté, chapitre, tri…), depuis le 09/10/2026.
Les comptes « maison » (administrateurs, compte éditorial, compte supprimé, compte de test) sont exclus des chiffres.
"""
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay, StudyTimeTracker, TimeSession
from apps.skilliq.models import SkillAssessment
from apps.things.models import Comment, Content, ContentDailyView, ContentReport, ProposedSolution
from apps.users.account_deletion import DELETED_USERNAME
from apps.users.models import UsageDaily, ViewHistory

PERIODS = (7, 30, 90)
# Vues jour par jour (visiteurs compris) enregistrées à partir de cette date : avant, la courbe est vide.
VIEWS_SINCE = date(2026, 10, 5)
# Pages vues et actions mesurées par le navigateur (UsageDaily) : à partir de cette date.
USAGE_SINCE = date(2026, 10, 6)
# Part des visiteurs non connectés (anon_count, anon_visitors) et valeurs des filtres : à partir de cette date.
ANON_SINCE = date(2026, 10, 9)
TOP_CONTENTS = 8
# Comptes de vérification automatique (captures, tests en production) : pas de vrais membres.
TEST_ACCOUNTS = ['fidni_test_claude']
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
TYPE_LABEL = {'exercise': 'Exercice', 'exam': 'Examen', 'lesson': 'Leçon'}
logger = logging.getLogger('django')


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
# Uniquement des dates qui ne bougent plus (création, jour du temps d'étude) : un jour actif reste actif.
def _activity_sources():
    from apps.concours.models import SimulationSession
    from apps.interactions.models import RevisionListItem, Save, UpcomingTest, Vote
    from apps.notebooks.models import NotebookAnnotation, NotebookLessonEntry
    from apps.things.models import CatchUpSkip, DifficultyFeedback
    return [
        (StudyTimeDay.objects.all(), 'date', 'user_id'),
        (QuestionProgress.objects.all(), 'created_at', 'user_id'),
        (Complete.objects.all(), 'created_at', 'user_id'),
        (TimeSession.objects.all(), 'created_at', 'user_id'),
        (Comment.objects.all(), 'created_at', 'author_id'),
        (ProposedSolution.objects.all(), 'created_at', 'author_id'),
        (SkillAssessment.objects.all(), 'created_at', 'user_id'),
        (SimulationSession.objects.all(), 'started_at', 'user_id'),
        (NotebookAnnotation.objects.all(), 'created_at', 'user_id'),
        (NotebookLessonEntry.objects.all(), 'added_at', 'section__notebook__user_id'),
        (RevisionListItem.objects.all(), 'added_at', 'revision_list__user_id'),
        (Save.objects.all(), 'saved_at', 'user_id'),
        (Vote.objects.all(), 'created_at', 'user_id'),
        (UpcomingTest.objects.all(), 'created_at', 'user_id'),
        (ContentReport.objects.all(), 'created_at', 'user_id'),
        (CatchUpSkip.objects.all(), 'created_at', 'user_id'),
        (DifficultyFeedback.objects.all(), 'created_at', 'user_id'),
    ]


# Dates écrasées à chaque passage : justes pour la DERNIÈRE action (liste des membres), pas pour les jours d'avant.
def _last_only_sources():
    return [
        (ViewHistory.objects.all(), 'viewed_at', 'user_id'),
        (QuestionProgress.objects.all(), 'assessed_at', 'user_id'),
        (Complete.objects.all(), 'updated_at', 'user_id'),
        (SkillAssessment.objects.all(), 'completed_at', 'user_id'),
        (User.objects.all(), 'last_login', 'id'),
    ]


def _since(qs, field, since):
    """`field >= since`, que le champ soit une date-heure ou une date (StudyTimeDay.date)."""
    f = qs.model._meta.get_field(field)
    if isinstance(since, datetime) and not isinstance(f, models.DateTimeField):
        since = timezone.localtime(since).date()
    return qs.filter(**{f'{field}__gte': since})


def _as_datetime(value):
    """Date d'une ligne → date-heure comparable (une date seule = minuit, heure locale)."""
    if isinstance(value, datetime) or value is None:
        return value
    return timezone.make_aware(datetime.combine(value, time.min))


def _active_user_ids(since, real_ids):
    ids = set()
    for qs, field, ufield in _activity_sources():
        # order_by() : sans le tri par défaut du modèle, DISTINCT porte bien sur l'utilisateur seul.
        ids.update(_since(qs, field, since).order_by().values_list(ufield, flat=True).distinct())
    return ids & real_ids


def _active_days(users, since):
    """{utilisateur: {jours actifs}} depuis `since`, pour des ids ou un queryset d'utilisateurs."""
    days = defaultdict(set)
    for qs, field, ufield in _activity_sources():
        rows = _since(qs.filter(**{f'{ufield}__in': users}), field, since).order_by().values_list(ufield, field)
        for uid, when in rows:
            if uid is not None and when:
                days[uid].add(_day(when))
    return days


def _last_activity(user_ids):
    """utilisateur → date de sa dernière action enregistrée."""
    last = {}
    for qs, field, ufield in _activity_sources() + _last_only_sources():
        rows = qs.filter(**{f'{ufield}__in': user_ids}).values(ufield).annotate(m=Max(field))
        for row in rows:
            uid, when = row[ufield], _as_datetime(row['m'])
            if when and (uid not in last or when > last[uid]):
                last[uid] = when
    return last


def _day(dt):
    """Jour local d'une date-heure ; une date est rendue telle quelle."""
    if not isinstance(dt, datetime):
        return dt
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


def _period(request):
    try:
        n = int(request.query_params.get('jours') or 30)
    except ValueError:
        n = 30
    return n if n in PERIODS else 30


def _period_start(n):
    """Minuit du premier des n derniers jours (aujourd'hui compris)."""
    return timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=n - 1), time.min))


@api_view(['GET'])
@permission_classes([IsSuperuser])
def overview(request):
    """Aperçu des n derniers jours (aujourd'hui compris), comparés aux n jours d'avant."""
    n = _period(request)
    first = timezone.localdate() - timedelta(days=n - 1)
    prev_first = first - timedelta(days=n)
    since = timezone.make_aware(datetime.combine(prev_first, time.min))
    days = [prev_first + timedelta(days=i) for i in range(2 * n)]
    current, previous = days[n:], days[:n]
    real = _real_users()
    real_ids = set(real.values_list('id', flat=True))

    def real_only(qs, ufield='user_id'):
        return qs.filter(**{f'{ufield}__in': real_ids})

    # ── Jour par jour, sur les deux périodes
    signups = Counter(_day(d) for d in real.filter(date_joined__gte=since).values_list('date_joined', flat=True))
    active_by_day = defaultdict(set)
    for uid, ds in _active_days(real.values('id'), since).items():
        for d in ds:
            active_by_day[d].add(uid)
    # Travail daté à sa création : une question réévaluée plus tard ne quitte pas son jour d'origine.
    work = Counter()
    for model in (Complete, QuestionProgress):
        work.update(_day(d) for d in real_only(model.objects.filter(created_at__gte=since)).values_list('created_at', flat=True))
    views = dict(ContentDailyView.objects.filter(date__gte=prev_first).values_list('date').annotate(s=Sum('count')))

    def total(per_day, ds):
        return sum(per_day.get(d, 0) for d in ds)

    def distinct_active(ds):
        return len(set().union(*(active_by_day.get(d, set()) for d in ds)))

    metrics = {
        'views': {'value': total(views, current),
                  'previous': total(views, previous) if previous[0] >= VIEWS_SINCE else None},
        'active': {'value': distinct_active(current), 'previous': distinct_active(previous)},
        'signups': {'value': total(signups, current), 'previous': total(signups, previous)},
        'work': {'value': total(work, current), 'previous': total(work, previous)},
    }
    series = [{'date': d.isoformat(), 'views': views.get(d, 0) if d >= VIEWS_SINCE else None,
               'active': len(active_by_day.get(d, ())), 'signups': signups.get(d, 0), 'work': work.get(d, 0)}
              for d in current]

    # ── Contenus les plus vus : vues de la période (visiteurs compris), puis membres distincts
    ct = ContentType.objects.get_for_model(Content)
    start = timezone.make_aware(datetime.combine(first, time.min))
    member_views = real_only(ViewHistory.objects.filter(viewed_at__gte=start, content_type=ct))
    ids = set(ContentDailyView.objects.filter(date__gte=first).values('content_id').annotate(v=Sum('count'))
              .order_by('-v').values_list('content_id', flat=True)[:TOP_CONTENTS])
    ids |= set(member_views.values('object_id').annotate(r=Count('user_id', distinct=True))
               .order_by('-r').values_list('object_id', flat=True)[:TOP_CONTENTS])
    period_views = dict(ContentDailyView.objects.filter(date__gte=first, content_id__in=ids)
                        .values_list('content_id').annotate(v=Sum('count')))
    readers = dict(member_views.filter(object_id__in=ids).values_list('object_id').annotate(r=Count('user_id', distinct=True)))
    contents = {c.id: c for c in Content.objects.filter(id__in=ids).only('id', 'type', 'title')}
    ranked = sorted(contents, key=lambda i: (period_views.get(i, 0), readers.get(i, 0)), reverse=True)[:TOP_CONTENTS]
    top_contents = [{**_content_ref(contents[i]), 'views': period_views.get(i, 0), 'readers': readers.get(i, 0)}
                    for i in ranked]

    features, pages = _usage(first, prev_first, real_ids)
    signups_current = total(signups, current)

    return Response({
        'generated_at': timezone.now().isoformat(),
        'days': n,
        'views_since': VIEWS_SINCE.isoformat(),
        'usage_since': USAGE_SINCE.isoformat(),
        'features': features,
        'pages': pages,
        'filter_values': _filter_values(first),
        'anonymes': _anonymous(first, prev_first, current, previous, signups_current),
        'members_total': len(real_ids),
        'funnel': _funnel(start, real),
        'auth_doors': _auth_doors(first),
        'todo': {
            'reports_open': ContentReport.objects.filter(status=ContentReport.STATUS_OPEN).count(),
            'a_verifier': [_content_ref(c) for c in Content.objects.filter(json_content__a_verifier=True)
                           .only('id', 'type', 'title').order_by('-created_at')],
            'difficulty_gaps': _difficulty_gaps(),
        },
        'metrics': metrics,
        'series': series,
        'top_contents': top_contents,
    })


def _funnel(start, real=None):
    """Entonnoir de la cohorte inscrite depuis `start` (comptes maison exclus).

    signups → verified (e-mail confirmé) → onboarded (profil complété) → first_view (un contenu ouvert) →
    first_work (une question auto-évaluée ou un contenu terminé) ; back_d7 = revenus entre J+7 et J+13
    parmi les d7_eligible (inscrits depuis au moins 7 jours), jours actifs pris dans _activity_sources.
    """
    real = _real_users() if real is None else real
    cohort = real.filter(date_joined__gte=start)
    joined = {uid: _day(d) for uid, d in cohort.values_list('id', 'date_joined')}
    ids = cohort.values('id')
    ct = ContentType.objects.get_for_model(Content)

    def members(qs):
        return set(qs.filter(user_id__in=ids).order_by().values_list('user_id', flat=True).distinct())
    viewed = members(ViewHistory.objects.filter(content_type=ct))
    worked = members(QuestionProgress.objects.all()) | members(Complete.objects.all())
    last_eligible_day = timezone.localdate() - timedelta(days=7)
    eligible = [uid for uid, d in joined.items() if d <= last_eligible_day]
    days = _active_days(eligible, start) if eligible else {}
    back = [uid for uid in eligible
            if any(joined[uid] + timedelta(days=7) <= d <= joined[uid] + timedelta(days=13) for d in days.get(uid, ()))]
    return {
        'signups': len(joined),
        'verified': cohort.filter(is_active=True, profile__email_verified=True).count(),
        'onboarded': cohort.filter(profile__onboarding_completed=True).count(),
        'first_view': len(viewed),
        'first_work': len(worked),
        'back_d7': len(back),
        'd7_eligible': len(eligible),
    }


AUTH_DOOR_PREFIX = 'auth:porte:'


def _auth_doors(first):
    """Portes d'entrée de la fenêtre de connexion / inscription (« vote », « bandeau »…) sur la période."""
    rows = (UsageDaily.objects.filter(kind=UsageDaily.KIND_FILTER, name__startswith=AUTH_DOOR_PREFIX, date__gte=first)
            .values('name').annotate(c=Sum('count'), v=Sum('visitors'), a=Sum('anon_count')))
    out = [{'source': r['name'][len(AUTH_DOOR_PREFIX):], 'count': r['c'] or 0, 'visits': r['v'] or 0,
            'anon': r['a'] or 0} for r in rows]
    out.sort(key=lambda x: (-x['count'], x['source']))
    return out


def _difficulty_gaps():
    """Écarts entre difficulté affichée et ressenti des élèves (things/difficulty.py), à corriger à la main."""
    try:
        from apps.things.difficulty import difficulty_gaps
        gaps = difficulty_gaps()
    except Exception:  # le reste du Pilotage s'affiche quand même ; l'erreur est journalisée
        logger.exception('Pilotage : écarts de difficulté indisponibles')
        return []
    out = []
    for gap in gaps:
        content = gap.get('content')
        if content is None:
            continue
        felt, ref = gap.get('felt'), _content_ref(content)
        out.append({**ref, 'edit_url': f'{ref["url"]}/edit', 'declared': gap.get('declared'),
                    'felt': felt.get('level') if isinstance(felt, dict) else felt,
                    'n': gap.get('n'), 'success_pct': gap.get('success_pct'), 'votes': gap.get('votes'),
                    'basis': gap.get('basis')})
    return out


def _features():
    """(clé, libellé, queryset, champ de date, champ utilisateur) : fonctionnalités dont chaque usage est en base."""
    from apps.classrooms.models import ClassroomMembership
    from apps.concours.models import SimulationSession
    from apps.interactions.models import RevisionList, RevisionListItem, Save, SolutionView, UpcomingTest, Vote
    from apps.notebooks.models import NotebookAnnotation, NotebookLessonEntry
    from apps.things.models import CatchUpSkip, DifficultyFeedback
    return [
        ('auto_evaluation', 'Auto-évaluation des questions', QuestionProgress.objects.all(), 'assessed_at', 'user_id'),
        ('termine', 'Contenu terminé (réussi ou à revoir)', Complete.objects.all(), 'updated_at', 'user_id'),
        ('jaime', 'J’aime / je n’aime pas', Vote.objects.exclude(value=0), 'updated_at', 'user_id'),
        ('chrono', 'Chrono et épreuves', TimeSession.objects.all(), 'created_at', 'user_id'),
        ('favoris', 'Enregistrer (favoris)', Save.objects.all(), 'saved_at', 'user_id'),
        ('liste', 'Listes de révision', RevisionListItem.objects.all(), 'added_at', 'revision_list__user_id'),
        ('ds', 'DS annoncés (« Mon prochain DS »)', UpcomingTest.objects.all(), 'created_at', 'user_id'),
        ('ds_blanc', 'DS blancs terminés', UpcomingTest.objects.exclude(mock_done_at=None), 'mock_done_at', 'user_id'),
        ('cahier', 'Leçons ajoutées au cahier', NotebookLessonEntry.objects.all(), 'added_at', 'section__notebook__user_id'),
        ('skilliq', 'Tests Skill IQ', SkillAssessment.objects.all(), 'completed_at', 'user_id'),
        ('commentaire', 'Commentaires', Comment.objects.all(), 'created_at', 'author_id'),
        ('solution', 'Solutions proposées', ProposedSolution.objects.all(), 'created_at', 'author_id'),
        ('signalement', 'Erreurs signalées', ContentReport.objects.all(), 'created_at', 'user_id'),
        ('classe', 'Classe rejointe', ClassroomMembership.objects.all(), 'joined_at', 'student_id'),
        # Audit du 10/10/2026 : usages en base jusqu'ici absents du Pilotage.
        ('concours', 'Simulations de concours', SimulationSession.objects.all(), 'started_at', 'user_id'),
        ('annotation', 'Annotations dans les cahiers', NotebookAnnotation.objects.all(), 'created_at', 'user_id'),
        ('liste_creee', 'Listes de révision créées', RevisionList.objects.all(), 'created_at', 'user_id'),
        ('pas_encore_fait', '« Pas encore fait » (bandeau de rattrapage)', CatchUpSkip.objects.all(), 'created_at', 'user_id'),
        ('note_ds', 'Notes de DS saisies', UpcomingTest.objects.exclude(grade=None), 'updated_at', 'user_id'),
        ('solution_vue', 'Solutions ouvertes (par contenu)', SolutionView.objects.all(), 'viewed_at', 'user_id'),
        ('ressenti', 'Difficulté ressentie donnée', DifficultyFeedback.objects.all(), 'created_at', 'user_id'),
    ]


# Actions mesurées par le navigateur (apps/users/usage.py) : pas de membres distincts sur la période,
# seulement le nombre de fois et les personnes distinctes jour par jour, additionnées.
TRACKED_ACTIONS = [
    ('voir-solution', 'Voir la solution d’une question'),
    ('toutes-solutions', 'Voir toutes les solutions'),
    ('tout-reussi', '« Tout réussi »'),
    ('trouve-apres-solution', '« Tu avais trouvé ? » (sous une solution)'),
    ('rattrapage-liste', 'Évalué depuis le bandeau « Tu as ouvert… » de la liste'),
    ('onglet-activite', 'Onglet « Activité » ouvert'),
    ('onglet-solutions', 'Onglet « Solutions des élèves » ouvert'),
    ('imprimer', 'Impression / PDF'),
    ('recherche', 'Recherche'),
    ('visite-guidee', 'Visite guidée'),
    # Audit du 10/10/2026
    ('partager', 'Partager un contenu'),
    ('chrono-demarre', 'Chrono lancé'),
    ('epreuve-demarree', 'Épreuve d’examen lancée'),
    ('epreuve-terminee', 'Épreuve d’examen terminée'),
    ('similaire', '« Pour continuer » (contenus semblables)'),
    ('suivant-apres-resultat', '« Exercice suivant » après le résultat'),
    ('ressenti', 'Difficulté ressentie donnée'),
    ('cloche', 'Cloche des notifications ouverte'),
    ('retour-liste', 'Retour d’un contenu vers la liste'),
    ('sommaire-lecon', 'Sommaire d’une leçon'),
    ('affichage-enonces', 'Liste en mode « Énoncés »'),
    ('charger-plus', '« Charger plus » dans une liste'),
    ('recherche-vide', 'Recherche sans résultat'),
    ('accueil-reprendre', 'Accueil : « Reprendre »'),
    ('accueil-pour-toi', 'Accueil : contenu « Pour toi »'),
    ('annoncer-ds', '« Annoncer mon DS »'),
    ('prog-entrainer', 'Ma progression : « S’entraîner »'),
    ('prog-cours', 'Ma progression : « Le cours »'),
    ('prog-quiz', 'Ma progression : « Quiz »'),
    ('quiz-refait', 'Quiz de chapitre repassé'),
    ('mode-revision', 'Liste de révision en mode révision'),
    ('barre-mobile', 'Barre d’onglets (téléphone)'),
    ('visite-auto', 'Visite guidée lancée automatiquement'),
    ('visite-passee', 'Visite guidée passée'),
    ('visite-finie', 'Visite guidée terminée'),
    ('signaler-ouvert', 'Fenêtre « Signaler une erreur » ouverte'),
    ('auth-ouverte', 'Fenêtre de connexion ouverte'),
    ('connexion-google', '« Continuer avec Google »'),
]
# Filtres des listes (07/10/2026) : un filtre compté quand on l'ajoute.
TRACKED_FILTERS = [
    ('filtre-niveau', 'Niveau'),
    ('filtre-chapitre', 'Chapitre'),
    ('filtre-difficulte', 'Difficulté'),
    ('filtre-theoreme', 'Théorème'),
    ('filtre-sous-domaine', 'Sous-domaine'),
    ('filtre-matiere', 'Matière'),
    ('filtre-statut', 'Statut (à faire, réussis, à revoir, vus)'),
    ('filtre-national', 'Examen national'),
    ('filtre-date', 'Date'),
    ('tri', 'Tri de la liste'),
    ('filtre-effacer', '« Tout effacer »'),
]


def _usage(first, prev_first, real_ids):
    """Fonctionnalités (membres, période et période d'avant) et toutes les pages vues (période)."""
    start = timezone.make_aware(datetime.combine(first, time.min))
    prev_start = timezone.make_aware(datetime.combine(prev_first, time.min))
    features = []
    for key, label, qs, field, ufield in _features():
        qs = qs.filter(**{f'{ufield}__in': real_ids})
        cur = qs.filter(**{f'{field}__gte': start})
        features.append({
            'key': key, 'label': label, 'source': 'base',
            'actions': cur.count(),
            'users': cur.values(ufield).distinct().count(),
            'previous': qs.filter(**{f'{field}__gte': prev_start, f'{field}__lt': start}).count(),
        })
    tracked = UsageDaily.objects.filter(kind=UsageDaily.KIND_ACTION, date__gte=prev_first)
    cur_t = dict(tracked.filter(date__gte=first).values_list('name').annotate(c=Sum('count')))
    vis_t = dict(tracked.filter(date__gte=first).values_list('name').annotate(v=Sum('visitors')))
    prev_t = dict(tracked.filter(date__lt=first).values_list('name').annotate(c=Sum('count')))
    for source, tracked in (('navigateur', TRACKED_ACTIONS), ('filtre', TRACKED_FILTERS)):
        for key, label in tracked:
            features.append({
                'key': key, 'label': label, 'source': source,
                'actions': cur_t.get(key, 0), 'users': None, 'visits': vis_t.get(key, 0),
                'previous': prev_t.get(key, 0) if prev_first >= USAGE_SINCE else None,
            })

    page_rows = (UsageDaily.objects.filter(kind=UsageDaily.KIND_PAGE, date__gte=first)
                 .values('name').annotate(views=Sum('count'), visits=Sum('visitors')).order_by('-views', 'name'))
    # Toutes les pages (une cinquantaine de motifs au plus) : avant, seules les 15 premières remontaient
    # et une page peu vue (ex. « Mes statistiques ») semblait jamais visitée. Le Pilotage replie la suite.
    pages = [{'page': r['name'], 'views': r['views'], 'visits': r['visits']} for r in page_rows]
    return features, pages


DIFFICULTY_LABEL = {'easy': 'Facile', 'medium': 'Moyen', 'hard': 'Difficile'}
STATUS_LABEL = {'showViewed': 'Déjà vus', 'hideViewed': 'Masquer les vus', 'showCompleted': 'Réussis',
                'showFailed': 'À revoir', 'todo': 'À faire'}
SORT_LABEL = {'recommended': 'Pour toi', 'most_upvoted': 'Plus aimés', 'newest': 'Plus récents',
              'oldest': 'Plus anciens', 'most_commented': 'Plus commentés',
              'easiest': 'Du plus facile au plus difficile'}
# Filtre envoyé par le navigateur → clé de TRACKED_FILTERS (même ligne du Pilotage).
FILTER_KEY = {'niveau': 'filtre-niveau', 'matiere': 'filtre-matiere', 'sous-domaine': 'filtre-sous-domaine',
              'chapitre': 'filtre-chapitre', 'theoreme': 'filtre-theoreme', 'difficulte': 'filtre-difficulte',
              'statut': 'filtre-statut', 'national': 'filtre-national', 'date': 'filtre-date', 'tri': 'tri'}


def _filter_values(first):
    """Valeurs de filtre ajoutées sur la période (« exercise:difficulte:hard »…), avec leur nom lisible.

    Une ligne par (liste, filtre, valeur) : le Pilotage regroupe par filtre et peut isoler une liste.
    """
    from apps.caracteristics.models import Chapter, ClassLevel, Subfield, Subject, Theorem
    rows = (UsageDaily.objects.filter(kind=UsageDaily.KIND_FILTER, date__gte=first).values('name')
            .annotate(c=Sum('count'), v=Sum('visitors'), a=Sum('anon_count')))
    parsed = []
    ids = defaultdict(set)
    for r in rows:
        parts = r['name'].split(':', 2)
        if len(parts) != 3 or parts[1] not in FILTER_KEY:
            continue
        kind, filt, value = parts
        parsed.append((kind, filt, value, r))
        if value.isdigit():
            ids[filt].add(int(value))
    models_by_filter = {'niveau': ClassLevel, 'matiere': Subject, 'sous-domaine': Subfield, 'chapitre': Chapter,
                        'theoreme': Theorem}
    names = {}
    for filt, model in models_by_filter.items():
        if not ids[filt]:
            continue
        qs = model.objects.filter(id__in=ids[filt])
        if model is Chapter:
            qs = qs.prefetch_related('class_levels')
            for c in qs:
                levels = ', '.join(sorted(l.name for l in c.class_levels.all()))
                names[(filt, str(c.id))] = f'{c.name} ({levels})' if levels else c.name
        else:
            names.update({(filt, str(pk)): name for pk, name in qs.values_list('id', 'name')})
    out = []
    for kind, filt, value, r in parsed:
        if filt == 'difficulte':
            label = DIFFICULTY_LABEL.get(value, value)
        elif filt == 'statut':
            label = STATUS_LABEL.get(value, value)
        elif filt == 'tri':
            label = SORT_LABEL.get(value, value)
        elif filt == 'national':
            label = 'Nationaux' if value == 'oui' else 'Devoirs (non nationaux)'
        elif filt == 'date':
            label = f'À partir de {value}'
        else:
            label = names.get((filt, value), f'#{value} (supprimé)')
        out.append({'filter': FILTER_KEY[filt], 'type': kind, 'value': value, 'label': label,
                    'count': r['c'] or 0, 'visits': r['v'] or 0, 'anon': r['a'] or 0})
    out.sort(key=lambda x: -x['count'])
    return out


def _anonymous(first, prev_first, current, previous, signups_current):
    """Visiteurs non connectés : visiteurs distincts par jour, pages et contenus vus, gestes (depuis ANON_SINCE).

    `visits` = personnes distinctes chaque jour, additionnées sur la période (une personne venue 3 jours = 3).
    """
    site = {r['date']: r for r in UsageDaily.objects.filter(kind=UsageDaily.KIND_SITE, name='visites', date__gte=prev_first)
            .values('date', 'count', 'visitors', 'anon_count', 'anon_visitors')}
    content_anon = dict(ContentDailyView.objects.filter(date__gte=prev_first).values_list('date').annotate(s=Sum('anon_count')))
    content_all = dict(ContentDailyView.objects.filter(date__gte=prev_first).values_list('date').annotate(s=Sum('count')))
    measured = lambda d: d >= ANON_SINCE  # noqa: E731

    def day(d):
        r = site.get(d) or {}
        if not measured(d):
            return {'date': d.isoformat(), 'anon': None, 'members': None, 'anon_pages': None, 'anon_contents': None}
        return {'date': d.isoformat(), 'anon': r.get('anon_visitors', 0),
                'members': r.get('visitors', 0) - r.get('anon_visitors', 0),
                'anon_pages': r.get('anon_count', 0), 'anon_contents': content_anon.get(d, 0)}

    def sums(ds):
        ds = [d for d in ds if measured(d)]
        rows = [site.get(d) or {} for d in ds]
        return {
            'visits': sum(r.get('anon_visitors', 0) for r in rows),
            'member_visits': sum(r.get('visitors', 0) - r.get('anon_visitors', 0) for r in rows),
            'pages': sum(r.get('anon_count', 0) for r in rows),
            'contents': sum(content_anon.get(d, 0) for d in ds),
            'contents_all': sum(content_all.get(d, 0) for d in ds),
        }

    cur = sums(current)
    prev = sums(previous) if previous[0] >= ANON_SINCE else None

    page_rows = (UsageDaily.objects.filter(kind=UsageDaily.KIND_PAGE, date__gte=max(first, ANON_SINCE))
                 .values('name').annotate(views=Sum('anon_count'), visits=Sum('anon_visitors'))
                 .filter(views__gt=0).order_by('-views', 'name'))
    pages = [{'page': r['name'], 'views': r['views'], 'visits': r['visits']} for r in page_rows]

    top = list(ContentDailyView.objects.filter(date__gte=max(first, ANON_SINCE)).values('content_id')
               .annotate(v=Sum('anon_count'), t=Sum('count')).filter(v__gt=0).order_by('-v')[:TOP_CONTENTS])
    contents = {c.id: c for c in Content.objects.filter(id__in=[r['content_id'] for r in top]).only('id', 'type', 'title')}
    top_contents = [{**_content_ref(contents[r['content_id']]), 'views': r['v'], 'total': r['t']}
                    for r in top if r['content_id'] in contents]

    labels = dict(TRACKED_ACTIONS)
    action_rows = (UsageDaily.objects.filter(kind=UsageDaily.KIND_ACTION, name__in=labels, date__gte=max(first, ANON_SINCE))
                   .values('name').annotate(c=Sum('anon_count'), t=Sum('count'), v=Sum('anon_visitors')))
    actions = sorted(({'key': r['name'], 'label': labels[r['name']], 'count': r['c'] or 0, 'total': r['t'] or 0,
                       'visits': r['v'] or 0} for r in action_rows), key=lambda x: -x['count'])

    return {
        'since': ANON_SINCE.isoformat(),
        'current': cur, 'previous': prev, 'signups': signups_current,
        'series': [day(d) for d in current],
        'pages': pages, 'top_contents': top_contents, 'actions': actions,
    }


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
    """Liste paginée des membres (comptes maison inclus mais signalés dans « Tous »), avec leur activité.

    filtre : actifs / nouveaux (sur les `jours` derniers jours) / jamais (aucune action) / enseignants ;
    les trois premiers excluent les comptes maison, comme les chiffres de l'aperçu.
    `counts` donne l'effectif de chaque filtre (recherche comprise) pour les pastilles.
    """
    q = (request.query_params.get('q') or '').strip()
    kind = request.query_params.get('type') or ''
    filtre = request.query_params.get('filtre') or ''
    sort = request.query_params.get('tri') or 'recent'
    since = _period_start(_period(request))
    try:
        page = max(1, int(request.query_params.get('page') or 1))
    except ValueError:
        page = 1
    size = 25

    base = User.objects.select_related('profile', 'profile__class_level').exclude(username=DELETED_USERNAME)
    if q:
        base = base.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q)
                           | Q(last_name__icontains=q) | Q(profile__school_name__icontains=q))
    if kind in ('student', 'teacher'):
        base = base.filter(profile__user_type=kind)
    elif kind == 'admin':
        base = base.filter(Q(is_staff=True) | Q(is_superuser=True))

    all_ids = list(base.values_list('id', flat=True))
    house_all = set(base.filter(_house_filter()).values_list('id', flat=True))
    last_all = _last_activity(all_ids)
    real_all = [i for i in all_ids if i not in house_all]
    groups = {
        'tous': all_ids,
        # Même définition que la tuile « actifs » de l'aperçu (dates stables) ; la dernière activité affichée,
        # elle, tient compte aussi des consultations et connexions.
        'actifs': sorted(_active_user_ids(since, set(real_all))),
        'nouveaux': list(base.filter(date_joined__gte=since).exclude(_house_filter()).values_list('id', flat=True)),
        'jamais': [i for i in real_all if i not in last_all],
        'enseignants': list(base.filter(profile__user_type='teacher').values_list('id', flat=True)),
    }
    qs = base.filter(id__in=groups[filtre]) if filtre in groups and filtre != 'tous' else base

    total = qs.count()
    if sort == 'activite':
        ids_all = list(qs.values_list('id', flat=True))
        ordered = sorted(ids_all, key=lambda i: last_all.get(i) or datetime(1970, 1, 1, tzinfo=dt_timezone.utc), reverse=True)
        page_ids = ordered[(page - 1) * size: page * size]
        rows = {u.id: u for u in qs.filter(id__in=page_ids)}
        page_users = [rows[i] for i in page_ids if i in rows]
    else:
        page_users = list(qs.order_by(SORTS.get(sort, '-date_joined'))[(page - 1) * size: page * size])
    ids = [u.id for u in page_users]

    def counts(qs_, ufield='user_id'):
        return dict(qs_.filter(**{f'{ufield}__in': ids}).values_list(ufield).annotate(n=Count('id')))
    views, completes = counts(ViewHistory.objects), counts(Complete.objects)
    assessed, comments = counts(QuestionProgress.objects), counts(Comment.objects, 'author_id')
    study = dict(StudyTimeTracker.objects.filter(user_id__in=ids).values_list('user_id').annotate(s=Sum('time_spent_seconds')))

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
            'last_activity': last_all[u.id].isoformat() if u.id in last_all else None,
            'onboarding_completed': bool(p and p.onboarding_completed),
            'email_verified': bool(p and getattr(p, 'email_verified_at', None)),
            'is_admin': u.is_staff or u.is_superuser, 'is_house': u.id in house_all,
            'stats': {'views': views.get(u.id, 0), 'completions': completes.get(u.id, 0),
                      'questions': assessed.get(u.id, 0), 'comments': comments.get(u.id, 0),
                      'study_minutes': round((study.get(u.id) or 0) / 60)},
        })
    return Response({'count': total, 'page': page, 'pages': max(1, -(-total // size)), 'results': results,
                     'counts': {k: len(v) for k, v in groups.items()}})


@api_view(['GET'])
@permission_classes([IsSuperuser])
def user_detail(request, pk):
    """Dernières actions d'un membre (fiche dépliée dans Pilotage › Membres)."""
    user = get_object_or_404(User, pk=pk)
    return Response({'id': user.id, 'activity': recent_activity({user.id}, limit=15)})
