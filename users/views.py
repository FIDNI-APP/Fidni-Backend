from rest_framework import status, views, generics,viewsets
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Count
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.contrib.auth import get_user_model
from .serializers import (
    UserSerializer,
    UserSettingsSerializer,
    OnboardingSerializer,
    SubjectGradeSerializer,
)
from .models import UserProfile, SubjectGrade
from things.models import ClassLevel, Subject, Exercise, Vote, Complete, Save

# users/views.py
from rest_framework.views import APIView


from .serializers import (
    UserSerializer, 
    UserSettingsSerializer
)

from .models import ViewHistory
from .serializers import (
    UserSerializer, 
)
from things.serializers import ViewHistorySerializer,ExerciseSerializer
from things.models import Exercise,Vote,Complete,Save

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
    queryset = User.objects.all()
    serializer_class = UserSerializer

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
    if request.user.is_authenticated:
        serializer = UserSerializer(request.user, context={'request': request, 'is_owner': True})
        return Response(serializer.data)
    return Response(status=status.HTTP_401_UNAUTHORIZED)


# Ajouter cette nouvelle vue pour l'onboarding
class OnboardingView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get onboarding status and current data"""
        user = request.user
        profile = user.profile
        
        # Get subject grades
        subject_grades = SubjectGradeSerializer(profile.subject_grades.all(), many=True).data
        
        # Get favorite subjects
        favorite_subjects = []
        for subject_id in profile.favorite_subjects:
            try:
                subject = Subject.objects.get(id=subject_id)
                favorite_subjects.append({
                    'id': subject.id,
                    'name': subject.name
                })
            except Subject.DoesNotExist:
                pass
        
        return Response({
            'onboarding_completed': profile.onboarding_completed,
            'user_type': profile.user_type,
            'class_level': profile.class_level.id if profile.class_level else None,
            'class_level_name': profile.class_level.name if profile.class_level else None,
            'bio': profile.bio,
            'favorite_subjects': favorite_subjects,
            'subject_grades': subject_grades
        })
    
    def post(self, request):
        """Complete or update onboarding data"""
        user = request.user
        serializer = OnboardingSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.update(user, serializer.validated_data)
            return Response({
                'status': 'success',
                'message': 'Onboarding completed successfully.',
                'onboarding_completed': True
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Ajouter un nouvel endpoint pour les notes par matière
class SubjectGradeViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectGradeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SubjectGrade.objects.filter(user_profile=self.request.user.profile)
    
    def perform_create(self, serializer):
        serializer.save(user_profile=self.request.user.profile)
    
    def create(self, request, *args, **kwargs):
        # Check if the subject grade already exists
        subject_id = request.data.get('subject')
        existing = SubjectGrade.objects.filter(
            user_profile=request.user.profile,
            subject_id=subject_id
        ).first()
        
        if existing:
            # Update existing
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)
        
        # Create new
        return super().create(request, *args, **kwargs)


# Mettre à jour UserProfileViewSet pour vérifier l'état de l'onboarding
class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    lookup_field = 'username'
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update']:
            return [IsAuthenticated()]
        return [AllowAny()]
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.get_object() if self.action != 'list' else None
        if user and self.request.user.is_authenticated:
            context['is_owner'] = user.id == self.request.user.id
        return context
    
    def update(self, request, *args, **kwargs):
        user = self.get_object()
        
        # Only allow users to update their own profile
        if user.id != request.user.id:
            return Response(
                {'error': 'You cannot update other users\' profiles'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().update(request, *args, **kwargs)
    
    @action(detail=True, methods=['get'])
    def onboarding_status(self, request, username=None):
        """Get the user's onboarding status"""
        user = self.get_object()
        
        # Only allow users to check their own onboarding status
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot check other users\' onboarding status'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return Response({
            'onboarding_completed': user.profile.onboarding_completed,
            'needs_profile_completion': not user.profile.onboarding_completed
        })
    
    def update(self, request, *args, **kwargs):
        user = self.get_object()
        
        # Only allow users to update their own profile
        if user.id != request.user.id:
            return Response(
                {'error': 'You cannot update other users\' profiles'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().update(request, *args, **kwargs)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, username=None):
        user = self.get_object()
        
        # Determine if requester is the profile owner
        is_owner = request.user.is_authenticated and request.user.id == user.id
        
        # If not owner and stats are private, restrict access
        if not is_owner and not user.profile.display_stats and not request.user.is_superuser:
            return Response(
                {'error': 'This user\'s statistics are private'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get comprehensive stats
        contribution_stats = user.profile.get_contribution_stats()
        
        # Only include learning stats for the owner
        response_data = {
            'contribution_stats': contribution_stats,
            'learning_stats' : {}
        }
        print(request.user.is_superuser)
        if is_owner or request.user.is_superuser:
            response_data['learning_stats'] = user.profile.get_learning_stats()
        
        return Response(response_data)
    
    @action(detail=True, methods=['get'])
    def contributions(self, request, username=None):
        user = self.get_object()
        exercises = Exercise.objects.filter(author=user).order_by('-created_at')
        
        page = self.paginate_queryset(exercises)
        if page is not None:
            serializer = ExerciseSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = ExerciseSerializer(exercises, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def saved_exercises(self, request, username=None):
        user = self.get_object()
        
        # Only allow users to view their own saved exercises
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' saved exercises'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        content_type = ContentType.objects.get_for_model(Exercise)
        saved_ids = Save.objects.filter(
            user=user,
            content_type=content_type
        ).order_by('-saved_at').values_list('object_id', flat=True)
        print(saved_ids)
        
        exercises = Exercise.objects.filter(id__in=saved_ids)
        
        page = self.paginate_queryset(exercises)
        if page is not None:
            serializer = ExerciseSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = ExerciseSerializer(exercises, many=True, context={'request': request})
        return Response(serializer.data)
    

    @action(detail=True, methods=['get'])
    def history(self, request, username=None):
        """Get view history for the user"""
        user = self.get_object()
        
        # Only allow users to view their own history
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' history'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        history_ids = ViewHistory.objects.filter(user=user).order_by('-viewed_at')
        serializer = ViewHistorySerializer(history_ids, many=True, context={'request': request})

        return Response(serializer.data)
    

    @action(detail=True, methods=['get'])
    def success_thing(self,request,username=None):
        """Get exercises completed successfully for the user"""
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error' : 'You cannnot view other users \' progress'}
            )
        content_type = ContentType.objects.get_for_model(Exercise)
        complete_ids = Complete.objects.filter(user=user, status ='success',content_type=content_type).order_by('-updated_at').values_list('object_id', flat=True)
        success_exercises = Exercise.objects.filter(id__in=complete_ids)
        serializer = ExerciseSerializer(success_exercises,many=True,context ={'request' : request})
        return Response(serializer.data)
    

    @action(detail=True, methods=['get'])
    def review_thing(self,request,username=None):
        """Get exercises in review for the user"""
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error' : 'You cannnot view other users \' progress'}
            )
        content_type = ContentType.objects.get_for_model(Exercise)
        complete_ids = Complete.objects.filter(user=user, status ='review',content_type=content_type).order_by('-updated_at').values_list('object_id')
        review_exercises = Exercise.objects.filter(id__in=complete_ids)
        serializer = ExerciseSerializer(review_exercises,many=True,context ={'request' : request})
        return Response(serializer.data)



class UserSettingsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current user settings"""
        serializer = UserSettingsSerializer(request.user.profile)
        return Response(serializer.data)
    
    def patch(self, request):
        """Update user settings"""
        serializer = UserSettingsSerializer(request.user.profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_content_viewed(request, content_id):
    """Mark content as viewed and update view count"""
    try:
        content = Exercise.objects.get(id=content_id)
        time_spent = request.data.get('time_spent', 0)
        
        # Get or create view history entry
        view_history, created = ViewHistory.objects.get_or_create(
            user=request.user,
            content=content,
            defaults={'time_spent': time_spent}
        )
        
        # If existing record, update time spent
        if not created and time_spent:
            view_history.time_spent += int(time_spent)
            view_history.save()
        
        # Increment view count only on first view
        if created:
            content.view_count += 1
            content.save()
        
        return Response(status=status.HTTP_200_OK)
    except Exercise.DoesNotExist:
        return Response(
            {'error': 'Content not found'},
            status=status.HTTP_404_NOT_FOUND
        )