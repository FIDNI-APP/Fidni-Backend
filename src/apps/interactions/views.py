from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from django.contrib.contenttypes.models import ContentType


from .models import Vote, RevisionList, RevisionListItem, StudyTimeTracker, Complete, TaxonomyTimeSpent
from .serializers import RevisionListSerializer, RevisionListCreateSerializer, RevisionListItemSerializer

import logging


logger = logging.getLogger('django')



#----------------------------PAGINATION-------------------------------
class LargeResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200

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
        return RevisionList.objects.filter(user=self.request.user).prefetch_related('items')

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
            # Get the content type
            content_type = ContentType.objects.get(model=content_type_name.lower())

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
        """
        Get statistics for a revision list.
        Returns: completion counts, success/review breakdown, time spent
        """
        revision_list = self.get_object()
        items = revision_list.items.all()

        total_items = items.count()

        # Track completion status
        completed_count = 0
        success_count = 0
        review_count = 0
        pending_count = 0
        total_time = 0

        for item in items:
            if item.content_object:
                # Check completion status using GenericForeignKey
                complete_record = Complete.objects.filter(
                    user=request.user,
                    content_type=item.content_type,
                    object_id=item.object_id
                ).first()

                if complete_record:
                    completed_count += 1
                    if complete_record.status == 'success':
                        success_count += 1
                    else:
                        review_count += 1
                else:
                    pending_count += 1

                # Get time spent using GenericForeignKey

        progress_percentage = (completed_count / total_items * 100) if total_items > 0 else 0

        return Response({
            'total_items': total_items,
            'completed': completed_count,
            'pending': pending_count,
            'success': success_count,
            'review': review_count,
            'progress_percentage': round(progress_percentage, 1),
            'total_time_seconds': total_time
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
            logger.warning(f"Study time tracking called without authentication")
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

        content_type = ContentType.objects.get(model=content_type_name.lower())

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
        return Response({'message': f'Skipped - invalid content_type'}, status=status.HTTP_200_OK)
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
    from django.db.models import Sum, F, Value, CharField
    from django.db.models.functions import Coalesce
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