from rest_framework import status, views, generics
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Count
from django.contrib.contenttypes.models import ContentType



from .models import ViewHistory
from .serializers import (
    UserSerializer, 
    UserStatsSerializer, 
)

from things.serializers import UserHistorySerializer,ExerciseSerializer
from things.models import Exercise,Vote

import logging

logger = logging.getLogger('django')


#----------------------------LOGIN-------------------------------

class LoginView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = request.data.get('identifier')
        password = request.data.get('password')

        if not all([identifier, password]):
            return Response(
                {'error': 'Please provide email/username and password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Try to find user by email or username
        try:
            if '@' in identifier:
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(username=identifier)
        except User.DoesNotExist:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Authenticate with username
        user = authenticate(username=user.username, password=password)
        if user is None:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        login(request, user)
        return Response(UserSerializer(user).data)


#----------------------------REGISTER-------------------------------

class RegisterView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')

        if not all([username, email, password]):
            return Response(
                {'error': 'Please provide all required fields'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'Username already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(email=email).exists():
            return Response(
                {'error': 'Email already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        login(request, user)
        return Response(UserSerializer(user).data)
    
   


#----------------------------LOGOUT-------------------------------

class LogoutView(views.APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_200_OK)

#----------------------------API FUNCTIONS-------------------------------


@api_view(['GET'])
def get_current_user(request):
    print(request)
    if request.user.is_authenticated:
        return Response(UserSerializer(request.user).data)
    return Response(status=status.HTTP_401_UNAUTHORIZED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_stats(request):
    user = request.user
    stats = {
        'exercisesCompleted': ViewHistory.objects.filter(
            user=user, 
            completed=True, 
            content__type='exercise'
        ).count(),
        'lessonsCompleted': ViewHistory.objects.filter(
            user=user, 
            completed=True, 
            content__type='course'
        ).count(),
        'totalUpvotes': Exercise.objects.filter(author=user).aggregate(
            total=Count('votes')
        )['total'] or 0,
    }
    return Response(UserStatsSerializer(user, context={'stats': stats}).data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_history(request):
    user = request.user
    exercise_content_type = ContentType.objects.get_for_model(Exercise)

    history = {
        'recentlyViewed': Exercise.objects.filter(
            viewhistory__user=user
        ).order_by('-viewhistory__viewed_at')[:5],
        'upvoted': Exercise.objects.filter(
            votes__user=user,
            votes__value=Vote.UP,
            votes__content_type=exercise_content_type
        ).order_by('-votes__created_at')[:5],
    }
    return Response(UserHistorySerializer(history).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_content_viewed(request, content_id):
    try:
        content = Exercise.objects.get(id=content_id)
        ViewHistory.objects.get_or_create(
            user=request.user,
            content=content
        )
        content.view_count += 1
        content.save()
        return Response(status=status.HTTP_200_OK)
    except Exercise.DoesNotExist:
        return Response(
            {'error': 'Content not found'},
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_content_completed(request, content_id):
    try:
        content = Exercise.objects.get(id=content_id)
        history, _ = ViewHistory.objects.get_or_create(
            user=request.user,
            content=content
        )
        history.completed = True
        history.save()
        return Response(status=status.HTTP_200_OK)
    except Exercise.DoesNotExist:
        return Response(
            {'error': 'Content not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    


@api_view(['GET'])
@permission_classes([AllowAny])  # Allow anyone to view public profiles
def get_user_profile(request, username):
    """
    Get public profile for any user by username
    """
    try:
        user = User.objects.get(username=username)
        logger.info(f"GET request to view profile for user: {user.username}")
        logger.info(f"User data: {request.data}")
        
        # Get basic user data
        user_data = UserSerializer(user).data
        
        # Get contribution counts
        contributions_count = Exercise.objects.filter(author=user).count()
        
        # Get reputation (total upvotes on their content)
        exercise_content_type = ContentType.objects.get_for_model(Exercise)
        reputation = Vote.objects.filter(
            content_type=exercise_content_type,
            object_id__in=Exercise.objects.filter(author=user).values_list('id', flat=True),
            value=Vote.UP
        ).count()
        
        # Add these to user data
        user_data['contributionsCount'] = contributions_count
        user_data['reputation'] = reputation
        
        return Response(user_data)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)

@api_view(['GET'])
def get_user_exercises(request, username):
    """
    Get exercises created by a specific user
    """
    try:
        user = User.objects.get(username=username)
        exercises = Exercise.objects.filter(author=user).order_by('-created_at')
        
        # Apply pagination if needed
        page = request.query_params.get('page', 1)
        per_page = request.query_params.get('per_page', 10)
        
        # You can add pagination code here
        
        data = ExerciseSerializer(exercises, many=True).data
        return Response({
            'results': data,
            'count': exercises.count()
        })
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_saved_content(request):
    """
    Get content saved by the current user
    This uses the upvoted content until you implement a separate save feature
    """
    user = request.user
    exercise_content_type = ContentType.objects.get_for_model(Exercise)
    
    upvoted_exercises = Exercise.objects.filter(
        votes__user=user,
        votes__value=Vote.UP,
        votes__content_type=exercise_content_type
    ).order_by('-votes__created_at')
    
    data = ExerciseSerializer(upvoted_exercises, many=True).data
    return Response({
        'results': data,
        'count': upvoted_exercises.count()
    })

