from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from django.contrib.contenttypes.models import ContentType


from .models import Vote, RevisionList, RevisionListItem, StudyTimeTracker, Complete
from .serializers import RevisionListSerializer, RevisionListCreateSerializer, RevisionListItemSerializer

import logging


logger = logging.getLogger('django')



class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
#----------------------------VOTEMIXIN-------------------------------

class VoteMixin:
    """
    Mixin that provides vote functionality with toggle behavior
    """
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        obj = self.get_object()
        vote_value = request.data.get('value')
        
        logger.debug(f"Vote request for {obj.__class__.__name__} ID {obj.id} with vote value: {vote_value}")
        
        try:
            vote_value = int(vote_value)
        except (TypeError, ValueError):
            logger.error(f"Invalid vote value type: {vote_value} for {obj.__class__.__name__} ID {obj.id}")
            return Response({'error': 'Invalid vote value'}, status=status.HTTP_400_BAD_REQUEST)

        if vote_value not in [Vote.UP, Vote.DOWN]:
            logger.error(f"Invalid vote value: {vote_value} for {obj.__class__.__name__} ID {obj.id}")
            return Response({'error': 'Invalid vote value'}, status=status.HTTP_400_BAD_REQUEST)

        existing_vote = obj.votes.filter(user=request.user).first()
        
        if existing_vote:
            # If clicking the same vote type, delete the vote
            if existing_vote.value == vote_value:
                existing_vote.delete()
                current_vote = None
            else:
                # If changing vote type (up to down or down to up)
                existing_vote.value = vote_value
                existing_vote.save()
                current_vote = existing_vote
        else:
            # Create new vote
            current_vote = obj.votes.create(user=request.user, value=vote_value)
            
        # Refresh the object to get updated vote count
        obj.refresh_from_db()
        
        return Response({
            'vote_count': obj.vote_count,
            'like_count': obj.like_count,
            'dislike_count': obj.dislike_count,
            'user_vote': current_vote.value if current_vote else 0,  # Return 0 if vote was deleted
            'item': self.get_serializer(obj).data
        })


#----------------------------REVISION LISTS-------------------------------

class RevisionListViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing revision lists.
    Users can create, read, update, and delete their own revision lists.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """Only return revision lists belonging to the current user"""
        return (RevisionList.objects.filter(user=self.request.user)
                .prefetch_related('items', 'class_levels', 'subjects', 'chapters'))

    def list(self, request, *args, **kwargs):
        """
        Page Révisions et fenêtre « Ajouter à une liste » : un résumé par liste, en 5 requêtes.

        Avant (08/10/2026), chaque exercice de chaque liste était sérialisé en carte complète, énoncé
        compris : ~500 requêtes et ~900 Ko pour 3 listes de 10 exercices, plusieurs secondes sur RDS.
        Les éléments ne donnent plus que de quoi savoir si un contenu y est déjà (type réel :
        exercise / exam) ; la progression (réussis, à revoir, à faire) est calculée ici.
        """
        from apps.things.models import Content
        lists = list(self.get_queryset())
        ids = {item.object_id for rl in lists for item in rl.items.all()}
        types = dict(Content.objects.filter(id__in=ids).values_list('id', 'type'))
        ct = ContentType.objects.get_for_model(Content)
        status_of = {int(o): st for o, st in Complete.objects.filter(
            user=request.user, content_type=ct, object_id__in=[str(i) for i in ids]).values_list('object_id', 'status')
            if str(o).isdigit()}
        chapters_of = {}
        for cid, name in Content.chapters.through.objects.filter(content_id__in=ids).values_list('content_id', 'chapter__name'):
            chapters_of.setdefault(cid, []).append(name)
        named = lambda qs: [{'id': x.id, 'name': x.name} for x in qs]  # noqa: E731
        data = []
        for rl in lists:
            items = [i for i in rl.items.all() if i.object_id in types]  # contenu supprimé : ignoré
            success = sum(status_of.get(i.object_id) == 'success' for i in items)
            review = sum(status_of.get(i.object_id) == 'review' for i in items)
            seen = []
            for i in items:
                for name in chapters_of.get(i.object_id, []):
                    if name not in seen:
                        seen.append(name)
            data.append({
                'id': rl.id, 'name': rl.name, 'description': rl.description, 'item_count': len(items),
                'class_levels': named(rl.class_levels.all()), 'subjects': named(rl.subjects.all()),
                'chapters': named(rl.chapters.all()), 'item_chapters': seen,
                'progress': {'success': success, 'review': review, 'todo': len(items) - success - review},
                'items': [{'id': i.id, 'object_id': i.object_id, 'content_type_name': types[i.object_id],
                           'added_at': i.added_at} for i in items],
                'created_at': rl.created_at, 'updated_at': rl.updated_at,
            })
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        """
        Une liste ouverte (feuille de TD, PDF) : ses exercices en cartes complètes, préchargées d'un coup
        (things/listing.py) au lieu d'une quinzaine de requêtes par exercice.
        """
        from apps.things.listing import serialize_content_list, with_list_relations
        from apps.things.models import Content
        rl = self.get_object()
        items = list(rl.items.all())
        contents = list(with_list_relations(Content.objects.filter(id__in=[i.object_id for i in items]), request.user))
        cards = {card['id']: card for card in serialize_content_list(contents, request)}
        types = {c.id: c.type for c in contents}
        named = lambda qs: [{'id': x.id, 'name': x.name} for x in qs]  # noqa: E731
        kept = [i for i in items if i.object_id in cards]
        return Response({
            'id': rl.id, 'name': rl.name, 'description': rl.description, 'item_count': len(kept),
            'class_levels': named(rl.class_levels.all()), 'subjects': named(rl.subjects.all()),
            'chapters': named(rl.chapters.all()),
            'items': [{'id': i.id, 'content_object': cards[i.object_id], 'content_type': i.content_type_id,
                       'object_id': i.object_id, 'content_type_name': types[i.object_id],
                       'added_at': i.added_at, 'notes': i.notes} for i in kept],
            'created_at': rl.created_at, 'updated_at': rl.updated_at,
        })

    # Liste proposée en un clic depuis un exercice raté (« Ajouter à À revoir »).
    QUICK_LIST_NAME = 'À revoir'
    QUICK_LIST_DESCRIPTION = 'Les exercices que tu as ratés ou marqués à revoir, pour les retravailler.'
    QUICK_ADD_MAX = 50  # contenus par ajout en lot

    @staticmethod
    def _label_from_contents(revision_list, contents):
        """Étiquette la liste avec les niveaux, matières et chapitres des contenus ajoutés."""
        levels = {lv.id for c in contents for lv in c.class_levels.all()}
        subjects = {c.subject_id for c in contents if c.subject_id}
        chapters = {ch.id for c in contents for ch in c.chapters.all()}
        if levels:
            revision_list.class_levels.add(*levels)
        if subjects:
            revision_list.subjects.add(*subjects)
        if chapters:
            revision_list.chapters.add(*chapters)

    @action(detail=False, methods=['post'])
    def quick_add(self, request):
        """
        Ajoute à la liste « À revoir » (créée au besoin, étiquetée d'après les contenus) un exercice ou
        un examen (object_id), ou plusieurs d'un coup (object_ids : plus de boucle de requêtes côté
        navigateur). Renvoie la liste et si un élément était nouveau ; en lot, aussi added_ids.
        """
        from apps.things.models import Content
        many = 'object_ids' in request.data
        if many:
            raw = request.data.getlist('object_ids') if hasattr(request.data, 'getlist') else request.data.get('object_ids')
            if not isinstance(raw, list):
                return Response({'error': 'object_ids : une liste d’identifiants.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            raw = [request.data.get('object_id')]
        ids = []
        for value in raw[:self.QUICK_ADD_MAX]:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        contents = sorted(Content.objects.filter(pk__in=ids, type__in=('exercise', 'exam'))
                          .prefetch_related('class_levels', 'chapters'), key=lambda c: ids.index(c.id))
        if not contents:
            return Response({'error': 'Contenu introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        revision_list, created_list = RevisionList.objects.get_or_create(
            user=request.user, name=self.QUICK_LIST_NAME,
            defaults={'description': self.QUICK_LIST_DESCRIPTION})
        ct = ContentType.objects.get_for_model(Content)
        already = set(revision_list.items.filter(content_type=ct, object_id__in=[c.pk for c in contents])
                      .values_list('object_id', flat=True))
        new = [c for c in contents if c.pk not in already]
        RevisionListItem.objects.bulk_create(
            [RevisionListItem(revision_list=revision_list, content_type=ct, object_id=c.pk) for c in new],
            ignore_conflicts=True)
        self._label_from_contents(revision_list, contents)
        revision_list.save(update_fields=['updated_at'])
        payload = {'list_id': revision_list.id, 'list_name': revision_list.name,
                   'created_list': created_list, 'added': bool(new)}
        if many:
            payload.update({'added_ids': [c.pk for c in new], 'added_count': len(new)})
        return Response(payload, status=status.HTTP_201_CREATED if new else status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def suggestions(self, request):
        """
        Exercices et examens à retravailler : marqués « Échoué », ou avec des questions
        auto-évaluées ratées / à revoir / partielles, et qui ne sont encore dans aucune liste.
        """
        from apps.things.models import Content
        from .models import QuestionProgress
        user = request.user
        ct = ContentType.objects.get_for_model(Content)
        in_lists = set(RevisionListItem.objects.filter(revision_list__user=user, content_type=ct)
                       .values_list('object_id', flat=True))
        validated = set()
        found = {}  # id -> {'failed': bool, 'weak': int, 'at': datetime}
        for c in Complete.objects.filter(user=user, content_type=ct):
            try:
                oid = int(c.object_id)
            except (TypeError, ValueError):
                continue
            if c.status == 'review':
                found[oid] = {'failed': True, 'weak': 0, 'at': c.updated_at}
            elif c.status == 'success':
                validated.add(oid)
        for qp in QuestionProgress.objects.filter(user=user, content_type=ct,
                                                  status__in=('failed', 'review', 'partial')):
            entry = found.setdefault(qp.object_id, {'failed': False, 'weak': 0, 'at': qp.assessed_at})
            entry['weak'] += 1
            if qp.assessed_at and qp.assessed_at > entry['at']:
                entry['at'] = qp.assessed_at
        ids = [oid for oid, e in found.items() if oid not in in_lists and (e['failed'] or oid not in validated)]
        contents = {c.id: c for c in Content.objects.filter(id__in=ids, type__in=('exercise', 'exam'))
                    .prefetch_related('chapters', 'class_levels')}
        rows = []
        for oid in sorted(contents, key=lambda i: found[i]['at'], reverse=True)[:12]:
            c, e = contents[oid], found[oid]
            rows.append({
                'id': c.id, 'type': c.type, 'title': c.title,
                'failed': e['failed'], 'weak_questions': e['weak'],
                'chapters': [ch.name for ch in c.chapters.all()],
                'class_level': next((lv.name for lv in c.class_levels.all()), None),
                'at': e['at'],
            })
        return Response({'count': len(ids), 'results': rows})

    def get_serializer_class(self):
        """Use different serializers for different actions"""
        if self.action in ['create', 'update', 'partial_update']:
            return RevisionListCreateSerializer
        return RevisionListSerializer

    def perform_create(self, serializer):
        """Set the user when creating a revision list"""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def add_item(self, request, pk=None):
        """
        Add an exercise or exam to a revision list.
        Expects: content_type (exercise or exam), object_id, notes (optional)
        """
        revision_list = self.get_object()
        content_type_name = request.data.get('content_type')
        object_id = request.data.get('object_id')
        notes = request.data.get('notes', '')

        if not content_type_name or not object_id:
            return Response(
                {'error': 'content_type and object_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # exercise/exam/lesson are all stored in the Content model
            model_name = 'content' if content_type_name.lower() in ('exercise', 'exam', 'lesson') else content_type_name.lower()
            content_type = ContentType.objects.get(model=model_name)

            # Create or update the item
            item, created = RevisionListItem.objects.get_or_create(
                revision_list=revision_list,
                content_type=content_type,
                object_id=object_id,
                defaults={'notes': notes}
            )

            if not created and notes:
                # Update notes if item already exists
                item.notes = notes
                item.save()
            revision_list.save(update_fields=['updated_at'])

            serializer = RevisionListItemSerializer(item, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        except ContentType.DoesNotExist:
            return Response(
                {'error': f'Invalid content_type: {content_type_name}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error adding item to revision list: {str(e)}")
            return Response(
                {'error': 'Failed to add item to revision list'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['delete'])
    def remove_item(self, request, pk=None):
        """
        Remove an item from a revision list.
        Expects: item_id
        """
        revision_list = self.get_object()
        item_id = request.data.get('item_id')

        if not item_id:
            return Response(
                {'error': 'item_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            item = RevisionListItem.objects.get(
                id=item_id,
                revision_list=revision_list
            )
            item.delete()
            return Response({'message': 'Item removed successfully'}, status=status.HTTP_200_OK)

        except RevisionListItem.DoesNotExist:
            return Response(
                {'error': 'Item not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error removing item from revision list: {str(e)}")
            return Response(
                {'error': 'Failed to remove item'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Réussis / à revoir / à faire d'une liste, en une requête (avant : une par exercice), et le
        statut de chaque élément (`statuses` : {object_id: 'success' | 'review' | None}) pour sa pastille."""
        from apps.things.models import Content
        revision_list = self.get_object()
        ids = [str(i) for i in revision_list.items.values_list('object_id', flat=True)]
        statuses = dict(Complete.objects.filter(
            user=request.user, content_type=ContentType.objects.get_for_model(Content), object_id__in=ids)
            .values_list('object_id', 'status'))
        success = sum(1 for i in ids if statuses.get(i) == 'success')
        completed = sum(1 for i in ids if i in statuses)
        return Response({
            'total_items': len(ids),
            'completed': completed,
            'pending': len(ids) - completed,
            'success': success,
            'review': completed - success,
            'progress_percentage': round(completed / len(ids) * 100, 1) if ids else 0,
            'total_time_seconds': 0,
            'statuses': {i: statuses[i] if statuses.get(i) in ('success', 'review') else None for i in ids},
        }, status=status.HTTP_200_OK)


#----------------------------STUDY TIME TRACKING-------------------------------

@api_view(['POST'])
@permission_classes([])
def track_study_time(request):
    """
    Track study time spent on a content page.
    """
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from django.contrib.auth import get_user_model
    from datetime import timedelta
    from .models import update_taxonomy_time  # Ajouter cet import

    User = get_user_model()

    try:
        # Support both JSON (normal requests) and FormData (sendBeacon)
        # Try request.data first (works for both JSON and DRF parsed data)
        content_type_name = request.data.get('content_type') if hasattr(request.data, 'get') else None
        content_id = request.data.get('content_id') if hasattr(request.data, 'get') else None
        time_spent = request.data.get('time_spent_seconds', 0) if hasattr(request.data, 'get') else 0
        token = request.data.get('token') if hasattr(request.data, 'get') else None

        if not content_type_name:
            content_type_name = request.POST.get('content_type')
            content_id = request.POST.get('content_id')
            time_spent = request.POST.get('time_spent_seconds', 0)
            token = request.POST.get('token')

        user_authenticated = request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated
        logger.info(f"Study time track request - content_type: {content_type_name}, content_id: {content_id}, time: {time_spent}, has_token: {bool(token)}, user_authenticated: {user_authenticated}")

        user = None
        if token:
            try:
                access_token = AccessToken(token)
                user_id = access_token['user_id']
                user = User.objects.get(id=user_id)
                logger.info(f"Authenticated via token: user_id={user_id}")
            except (InvalidToken, TokenError, User.DoesNotExist) as e:
                logger.error(f"Invalid token in study time tracking: {e}")
                return Response({'message': 'Skipped - invalid token'}, status=status.HTTP_200_OK)
        elif request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            user = request.user
            logger.info(f"Authenticated via session: user={user.username}")

        if not user:
            logger.warning("Study time tracking called without authentication")
            return Response({'message': 'Skipped - not authenticated'}, status=status.HTTP_200_OK)

        if isinstance(time_spent, str):
            time_spent = float(time_spent)

        if not content_type_name or not content_id:
            return Response(
                {'error': 'content_type and content_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(time_spent, (int, float)) or time_spent < 0:
            return Response(
                {'error': 'time_spent_seconds must be a positive number'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Minimum threshold to avoid spam
        if time_spent < 5:
            return Response({'message': 'Skipped - time too short'}, status=status.HTTP_200_OK)

        # Frontend sends 'exercise' | 'lesson' | 'exam' but they all share the
        # unified Content model, registered as ContentType(model='content').
        normalized = content_type_name.lower()
        if normalized in ('exercise', 'lesson', 'exam'):
            normalized = 'content'
        content_type = ContentType.objects.get(model=normalized)

        if not user or not user.id:
            logger.error(f"Attempted to track study time without valid user: user={user}")
            return Response({'message': 'Skipped - invalid user'}, status=status.HTTP_200_OK)

        try:
            from django.db.models import F
            from django.utils import timezone

            tracker, created = StudyTimeTracker.objects.get_or_create(
                user=user,
                content_type=content_type,
                object_id=content_id,
                defaults={'time_spent_seconds': int(time_spent)}
            )

            if not created:
                tracker.time_spent_seconds = F('time_spent_seconds') + int(time_spent)
                tracker.recorded_at = timezone.now()
                tracker.save(update_fields=['time_spent_seconds', 'recorded_at'])
                tracker.refresh_from_db()

            # Journal jour par jour (statistiques par période).
            if normalized == 'content':
                from .models import StudyTimeDay
                day, day_created = StudyTimeDay.objects.get_or_create(
                    user=user, object_id=int(content_id), date=timezone.localdate(),
                    defaults={'seconds': int(time_spent)})
                if not day_created:
                    StudyTimeDay.objects.filter(pk=day.pk).update(seconds=F('seconds') + int(time_spent))

            # ========== NOUVEAU CODE : Mettre à jour les taxonomies ==========
            # Récupérer l'objet content pour accéder aux taxonomies
            try:
                content_object = tracker.content_object
                if content_object:
                    time_delta = timedelta(seconds=int(time_spent))
                    update_taxonomy_time(user, content_object, time_delta)
                    logger.info(f"Updated taxonomy time for {user.username}: +{time_spent}s on {content_type_name}")
            except Exception as tax_error:
                # Ne pas faire échouer la requête si la mise à jour taxonomy échoue
                logger.error(f"Failed to update taxonomy time: {str(tax_error)}")
            # ==================================================================

            logger.info(f"Tracked {time_spent}s of study time for {user.username} on {content_type_name} {content_id} (total: {tracker.time_spent_seconds}s, {'created' if created else 'updated'})")

            return Response({
                'message': 'Study time tracked successfully',
                'time_spent_seconds': int(time_spent),
                'total_time_seconds': tracker.time_spent_seconds
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        except Exception as db_error:
            logger.error(f"Database error tracking study time: {str(db_error)}, user={user}, content_type={content_type_name}, content_id={content_id}")
            return Response({'message': 'Skipped - database error'}, status=status.HTTP_200_OK)

    except ContentType.DoesNotExist:
        logger.warning(f"Invalid content_type requested: {content_type_name}")
        return Response({'message': 'Skipped - invalid content_type'}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error tracking study time: {str(e)}", exc_info=True)
        return Response({'message': 'Skipped - error occurred'}, status=status.HTTP_200_OK)


#----------------------------TAXONOMY TIME STATISTICS-------------------------------
# views.py

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_taxonomy_time_stats(request):
    """
    Get time spent statistics aggregated by taxonomy - REAL-TIME with SQL aggregation
    """
    from apps.things.models import Content

    user = request.user
    taxonomy_type_filter = request.query_params.get('taxonomy_type', None)
    search = request.query_params.get('search', None)
    limit = request.query_params.get('limit', None)

    try:
        content_ct = ContentType.objects.get_for_model(Content)

        results = {}

        def format_time(seconds):
            if not seconds or seconds == 0:
                return "0s"
            if seconds < 60:
                return f"{seconds}s"
            elif seconds < 3600:
                return f"{seconds // 60}m {seconds % 60}s"
            else:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                return f"{hours}h {minutes}m"

        def add_to_results(tax_type, tax_id, tax_name, content_type, seconds):
            if not seconds or seconds <= 0:
                return
            key = (tax_type, tax_id)
            if key not in results:
                results[key] = {
                    'id': f"{tax_type}_{tax_id}",
                    'taxonomy_type': tax_type,
                    'taxonomy_id': tax_id,
                    'name': tax_name,
                    'total_time_seconds': 0,
                    'exercise_time_seconds': 0,
                    'lesson_time_seconds': 0,
                    'exam_time_seconds': 0,
                }
            results[key]['total_time_seconds'] += seconds
            results[key][f'{content_type}_time_seconds'] += seconds

        # Fetch time per content object in one query
        content_times = dict(
            StudyTimeTracker.objects
            .filter(user=user, content_type=content_ct, time_spent_seconds__gt=0)
            .values_list('object_id', 'time_spent_seconds')
        )

        if content_times:
            contents = (
                Content.objects
                .filter(id__in=content_times.keys())
                .select_related('subject')
                .prefetch_related('subfields', 'chapters', 'theorems')
                .only('id', 'type', 'subject__id', 'subject__name')
            )

            for obj in contents:
                time_spent = content_times.get(obj.id, 0)
                ctype = obj.type  # 'exercise', 'lesson', or 'exam'
                if obj.subject:
                    add_to_results('subject', obj.subject.id, obj.subject.name, ctype, time_spent)
                for sf in obj.subfields.all():
                    add_to_results('subfield', sf.id, sf.name, ctype, time_spent)
                for ch in obj.chapters.all():
                    add_to_results('chapter', ch.id, ch.name, ctype, time_spent)
                for th in obj.theorems.all():
                    add_to_results('theorem', th.id, th.name, ctype, time_spent)

        # Convertir en liste
        result_list = list(results.values())

        # Filtrer par type de taxonomie
        if taxonomy_type_filter:
            result_list = [r for r in result_list if r['taxonomy_type'] == taxonomy_type_filter]

        # Filtrer par recherche
        if search:
            search_lower = search.lower()
            result_list = [r for r in result_list if search_lower in r['name'].lower()]

        # Trier par temps total décroissant
        result_list.sort(key=lambda x: x['total_time_seconds'], reverse=True)

        # Ajouter le temps formaté
        for r in result_list:
            r['total_time_formatted'] = format_time(r['total_time_seconds'])

        # Appliquer la limite
        if limit:
            try:
                result_list = result_list[:int(limit)]
            except ValueError:
                pass

        return Response({
            'count': len(result_list),
            'results': result_list
        })

    except Exception as e:
        logger.error(f"Error calculating taxonomy time stats: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to calculate taxonomy time statistics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )