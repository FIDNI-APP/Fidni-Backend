from rest_framework import status,viewsets
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from .serializers import (
    UserSerializer,
    UserSettingsSerializer,
    SubjectGradeSerializer,
)
from .models import SubjectGrade
from .time_stats_views import TimeStatsViewMixin
from things.models import Exercise
from caracteristics.models import Subject, ClassLevel
from interactions.models import Complete, Save
from rest_framework.views import APIView
from .models import ViewHistory
from things.serializers import ViewHistorySerializer,ExerciseSerializer


import logging

logger = logging.getLogger('django')



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
        subject_grades = []
        for grade in profile.subject_grades.all():
            subject_grades.append({
                'id': grade.id,
                'subject': grade.subject.id,
                'min_grade': grade.min_grade,
                'max_grade': grade.max_grade
            })
        
        # Get target subjects
        target_subjects = []
        for subject_id in profile.target_subjects:
            try:
                subject = Subject.objects.get(id=subject_id)
                target_subjects.append({
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
            'target_subjects': target_subjects,
            'subject_grades': subject_grades
        })
    
    @transaction.atomic
    def post(self, request):
        """Complete or update onboarding data"""
        user = request.user
        data = request.data
        
        try:
            # Update UserProfile fields
            profile = user.profile
            
            # Update class level
            if 'class_level' in data and data['class_level']:
                try:
                    class_level = ClassLevel.objects.get(id=data['class_level'])
                    profile.class_level = class_level
                except ClassLevel.DoesNotExist:
                    return Response(
                        {'error': f"Class level with ID {data['class_level']} not found"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Update user type
            if 'user_type' in data:
                profile.user_type = data['user_type']
            
            # Update bio
            if 'bio' in data:
                profile.bio = data['bio']
            
            # Update target subjects
            if 'target_subjects' in data:
                profile.target_subjects = data['target_subjects']
            
            # Mark onboarding as completed
            profile.onboarding_completed = True
            profile.save()
            
            # Process subject grades if provided
            if 'subject_grades' in data and isinstance(data['subject_grades'], list):
                # Clear existing grades and create new ones
                profile.subject_grades.all().delete()
                
                for grade_data in data['subject_grades']:
                    subject_id = grade_data.get('subject')
                    min_grade = grade_data.get('min_grade', 0)
                    max_grade = grade_data.get('max_grade', 20)
                    
                    try:
                        subject = Subject.objects.get(id=subject_id)
                        SubjectGrade.objects.create(
                            user=profile,
                            subject=subject,
                            min_grade=min_grade,
                            max_grade=max_grade
                        )
                    except Subject.DoesNotExist:
                        # Log this but continue processing other grades
                        print(f"Subject with ID {subject_id} not found")
            
            return Response({
                'status': 'success',
                'message': 'Onboarding completed successfully.',
                'onboarding_completed': True
            })
        
        except Exception as e:
            # Roll back transaction on error
            transaction.set_rollback(True)
            return Response(
                {'error': f'Failed to complete onboarding: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


# Ajouter un nouvel endpoint pour les notes par matière
class SubjectGradeViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectGradeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SubjectGrade.objects.filter(user=self.request.user.profile)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user.profile)
    
    def create(self, request, *args, **kwargs):
        # Check if the subject grade already exists
        subject_id = request.data.get('subject')
        existing = SubjectGrade.objects.filter(
            user=request.user.profile,
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
class UserProfileViewSet(TimeStatsViewMixin, viewsets.ModelViewSet):
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
    @action(detail=True, methods=['get'])
    def get_time_spent(self,request,username = None):
        """Get time spent on specific exercise for the user"""
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error' : 'You cannnot view other users \' progress'}
            )
        content_type = ContentType.objects.get_for_model(Exercise)
        



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