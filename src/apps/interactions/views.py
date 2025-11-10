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
@permission_classes([])  # Allow without authentication for sendBeacon
def track_study_time(request):
    """
    Track study time spent on a content page.
    Automatically called by frontend when user views exercise/lesson/exam pages.

    Expected request data (JSON or FormData):
    {
        "content_type": "exercise" | "lesson" | "exam",
        "content_id": "uuid",
        "time_spent_seconds": 123,
        "token": "jwt_token"  (for sendBeacon requests)
    }
    """
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        # Support both JSON (normal requests) and FormData (sendBeacon)
        # Try request.data first (works for both JSON and DRF parsed data)
        content_type_name = request.data.get('content_type') if hasattr(request.data, 'get') else None
        content_id = request.data.get('content_id') if hasattr(request.data, 'get') else None
        time_spent = request.data.get('time_spent_seconds', 0) if hasattr(request.data, 'get') else 0
        token = request.data.get('token') if hasattr(request.data, 'get') else None

        # Fallback to request.POST for FormData from sendBeacon
        if not content_type_name:
            content_type_name = request.POST.get('content_type')
            content_id = request.POST.get('content_id')
            time_spent = request.POST.get('time_spent_seconds', 0)
            token = request.POST.get('token')

        # Check if user is authenticated (safely handle None)
        user_authenticated = request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated
        logger.info(f"Study time track request - content_type: {content_type_name}, content_id: {content_id}, time: {time_spent}, has_token: {bool(token)}, user_authenticated: {user_authenticated}")

        # Authenticate using token from body (for sendBeacon compatibility)
        user = None
        if token:
            try:
                access_token = AccessToken(token)
                user_id = access_token['user_id']
                user = User.objects.get(id=user_id)
                logger.info(f"Authenticated via token: user_id={user_id}")
            except (InvalidToken, TokenError, User.DoesNotExist) as e:
                logger.error(f"Invalid token in study time tracking: {e}")
                # Don't fail - just skip tracking for invalid tokens
                return Response({'message': 'Skipped - invalid token'}, status=status.HTTP_200_OK)
        elif request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            user = request.user
            logger.info(f"Authenticated via session: user={user.username}")

        # If no user found, skip tracking silently (don't error out)
        if not user:
            logger.warning(f"Study time tracking called without authentication")
            return Response({'message': 'Skipped - not authenticated'}, status=status.HTTP_200_OK)

        # Convert time_spent to number if it's a string
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

        # Get the content type
        content_type = ContentType.objects.get(model=content_type_name.lower())

        # Double-check user exists before creating (safety check)
        if not user or not user.id:
            logger.error(f"Attempted to track study time without valid user: user={user}")
            return Response({'message': 'Skipped - invalid user'}, status=status.HTTP_200_OK)

        # Get or create study time entry and increment time
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
                # Update existing entry: increment time and update timestamp
                tracker.time_spent_seconds = F('time_spent_seconds') + int(time_spent)
                tracker.recorded_at = timezone.now()
                tracker.save(update_fields=['time_spent_seconds', 'recorded_at'])
                tracker.refresh_from_db()  # Get actual value after F() expression

            logger.info(f"Tracked {time_spent}s of study time for {user.username} on {content_type_name} {content_id} (total: {tracker.time_spent_seconds}s, {'created' if created else 'updated'})")

            return Response({
                'message': 'Study time tracked successfully',
                'time_spent_seconds': int(time_spent),
                'total_time_seconds': tracker.time_spent_seconds
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        except Exception as db_error:
            # If database insert fails, log it but don't fail the request
            logger.error(f"Database error tracking study time: {str(db_error)}, user={user}, content_type={content_type_name}, content_id={content_id}")
            return Response({'message': 'Skipped - database error'}, status=status.HTTP_200_OK)

    except ContentType.DoesNotExist:
        logger.warning(f"Invalid content_type requested: {content_type_name}")
        return Response({'message': f'Skipped - invalid content_type'}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error tracking study time: {str(e)}", exc_info=True)
        # Return 200 instead of 500 to prevent frontend errors
        return Response({'message': 'Skipped - error occurred'}, status=status.HTTP_200_OK)


#----------------------------TAXONOMY TIME STATISTICS-------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_taxonomy_time_stats(request):
    """
    Get time spent statistics aggregated by taxonomy with content type breakdown

    Query parameters:
        - taxonomy_type: Optional filter by type (subject, subfield, chapter, theorem)
        - search: Optional search by name
        - limit: Optional limit results (default: all)
    """
    try:
        from datetime import timedelta
        from django.core.cache import cache

        user = request.user
        taxonomy_type = request.query_params.get('taxonomy_type', None)
        search = request.query_params.get('search', None)
        limit = request.query_params.get('limit', None)

        # Build cache key
        cache_key = f'taxonomy_time_stats_{user.id}_{taxonomy_type or "all"}_{search or ""}_{limit or ""}'

        # Try to get from cache first (cache for 60 seconds)
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)

        # Get base queryset with optimized query
        queryset = TaxonomyTimeSpent.objects.filter(
            user=user,
            total_time__gt=timedelta(0)
        ).select_related('content_type').only(
            'id', 'taxonomy_type', 'object_id', 'total_time',
            'exercise_time', 'lesson_time', 'exam_time', 'content_type'
        )

        # Filter by taxonomy type if provided
        if taxonomy_type:
            queryset = queryset.filter(taxonomy_type=taxonomy_type)

        # Convert to list to avoid multiple DB hits
        taxonomy_times = list(queryset)

        # Bulk fetch all taxonomy objects by type to avoid N+1 queries
        from apps.things.models import Subject, Subfield, Chapter, Theorem

        taxonomy_models = {
            'subject': Subject,
            'subfield': Subfield,
            'chapter': Chapter,
            'theorem': Theorem
        }

        # Group IDs by taxonomy type
        ids_by_type = {}
        for tax_time in taxonomy_times:
            if tax_time.taxonomy_type not in ids_by_type:
                ids_by_type[tax_time.taxonomy_type] = []
            ids_by_type[tax_time.taxonomy_type].append(tax_time.object_id)

        # Bulk fetch all objects at once
        taxonomy_objects = {}
        for tax_type, ids in ids_by_type.items():
            if tax_type in taxonomy_models:
                model = taxonomy_models[tax_type]
                objects = model.objects.filter(id__in=ids).only('id', 'name')
                for obj in objects:
                    taxonomy_objects[(tax_type, obj.id)] = obj

        # Build results
        results = []
        for taxonomy_time in taxonomy_times:
            # Get the taxonomy object from bulk fetch
            taxonomy_obj = taxonomy_objects.get((taxonomy_time.taxonomy_type, taxonomy_time.object_id))
            if not taxonomy_obj:
                continue

            name = getattr(taxonomy_obj, 'name', str(taxonomy_obj))

            # Apply search filter if provided
            if search and search.lower() not in name.lower():
                continue

            # Helper to convert timedelta to seconds
            def td_to_seconds(td):
                return int(td.total_seconds()) if td else 0

            results.append({
                'id': taxonomy_time.id,
                'taxonomy_type': taxonomy_time.taxonomy_type,
                'taxonomy_id': taxonomy_time.object_id,
                'name': name,
                'total_time_seconds': td_to_seconds(taxonomy_time.total_time),
                'total_time_formatted': str(taxonomy_time.total_time),
                # Content type breakdown
                'exercise_time_seconds': td_to_seconds(taxonomy_time.exercise_time),
                'lesson_time_seconds': td_to_seconds(taxonomy_time.lesson_time),
                'exam_time_seconds': td_to_seconds(taxonomy_time.exam_time),
            })

        # Sort by time spent (descending)
        results.sort(key=lambda x: x['total_time_seconds'], reverse=True)

        # Apply limit if provided
        if limit:
            try:
                limit = int(limit)
                results = results[:limit]
            except ValueError:
                pass

        response_data = {
            'count': len(results),
            'results': results
        }

        # Cache the results for 60 seconds
        cache.set(cache_key, response_data, 60)

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error fetching taxonomy time stats: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch taxonomy time statistics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

