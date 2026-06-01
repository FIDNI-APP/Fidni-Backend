from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import update_session_auth_hash
from django.db import transaction

from .serializers import UserSerializer, UserSettingsSerializer, SubjectGradeSerializer
from .models import SubjectGrade, ViewHistory, UserProfile, get_random_avatar
from .time_stats_views import TimeStatsViewMixin
from apps.things.models import Content
from apps.caracteristics.models import Subject, ClassLevel
from apps.interactions.models import Complete, Save
from apps.things.serializers import ContentListSerializer
from apps.interactions.serializers import ViewHistorySerializer

import logging

logger = logging.getLogger('django')


# ============ CURRENT USER ============

@api_view(['GET'])
def get_current_user(request):
    if request.user.is_authenticated:
        serializer = UserSerializer(request.user, context={'request': request, 'is_owner': True})
        return Response(serializer.data)
    return Response(status=status.HTTP_401_UNAUTHORIZED)


# ============ AVATAR UPLOAD ============

class AvatarUploadView(APIView):
    """Handle avatar upload, update and deletion"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """Upload or update user avatar"""
        if 'avatar' not in request.FILES:
            return Response(
                {'error': 'No image file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        avatar_file = request.FILES['avatar']
        
        # Validate file size (max 5MB)
        if avatar_file.size > 5 * 1024 * 1024:
            return Response(
                {'error': 'File size must be less than 5MB'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        content_type = getattr(avatar_file, 'content_type', None)
        if content_type not in allowed_types:
            return Response(
                {'error': 'Invalid file type. Allowed: JPEG, PNG, GIF, WebP'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from PIL import Image
            import io
            from django.core.files.base import ContentFile
            
            # Process and resize image
            img = Image.open(avatar_file)
            
            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Resize to max 500x500 while maintaining aspect ratio
            max_size = (500, 500)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save to buffer
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            profile = request.user.profile
            
            # Delete old avatar file if exists
            if hasattr(profile, 'avatar_file') and profile.avatar_file:
                profile.avatar_file.delete(save=False)
            
            # Clear URL avatar when uploading file
            if hasattr(profile, 'avatar_url'):
                profile.avatar_url = None
            
            # Save new avatar
            filename = f'avatar_{request.user.id}.jpg'
            
            if hasattr(profile, 'avatar_file'):
                profile.avatar_file.save(filename, ContentFile(buffer.read()), save=True)
                avatar_url = profile.avatar_file.url if profile.avatar_file else None
            else:
                # Fallback: store as URL if avatar_file field doesn't exist
                # You might want to upload to a cloud storage here
                avatar_url = None
            
            return Response({
                'message': 'Avatar uploaded successfully',
                'avatar_url': avatar_url or profile.avatar
            })
            
        except ImportError:
            return Response(
                {'error': 'Image processing not available. Install Pillow.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"Avatar upload error: {str(e)}")
            return Response(
                {'error': f'Failed to process image: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def delete(self, request):
        """Remove user avatar and set default"""
        profile = request.user.profile
        
        # Delete file if exists
        if hasattr(profile, 'avatar_file') and profile.avatar_file:
            profile.avatar_file.delete(save=False)
            profile.avatar_file = None
        
        # Set a default avatar URL
        from .models import get_random_avatar
        if hasattr(profile, 'avatar_url'):
            profile.avatar_url = get_random_avatar()
        profile.save()
        
        return Response({
            'message': 'Avatar removed successfully',
            'avatar_url': profile.avatar
        })


# ============ ONBOARDING ============

class OnboardingView(APIView):
    """Handle onboarding flow"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current onboarding state and data"""
        profile = request.user.profile
        
        # Get subject grades
        subject_grades = []
        for grade in profile.subject_grades.all():
            subject_grades.append({
                'subject': str(grade.subject.id),
                'subject_name': grade.subject.name,
                'current': float(grade.current_grade) if hasattr(grade, 'current_grade') else float(grade.min_grade),
                'target': float(grade.target_grade) if hasattr(grade, 'target_grade') else float(grade.max_grade),
            })
        
        # Get favorite subjects
        favorite_subjects = []
        if hasattr(profile, 'target_subjects'):
            favorite_subjects = [str(s) for s in profile.target_subjects.values_list('id', flat=True)]
        
        return Response({
            'completed': profile.onboarding_completed,
            'current_step': getattr(profile, 'onboarding_step', 0),
            'data': {
                'user_type': profile.user_type,
                'class_level': str(profile.class_level.id) if profile.class_level else None,
                'class_level_name': profile.class_level.name if profile.class_level else None,
                'learning_style': getattr(profile, 'learning_style', 'mixed'),
                'study_frequency': getattr(profile, 'study_frequency', 'weekly'),
                'daily_goal_minutes': getattr(profile, 'daily_goal_minutes', 30),
                'learning_goals': getattr(profile, 'learning_goals', []),
                'favorite_subjects': favorite_subjects,
                'subject_grades': subject_grades,
                'bio': profile.bio,
                'avatar_url': profile.avatar if hasattr(profile, 'avatar') else profile.avatar_url,
            }
        })
    
    def patch(self, request):
        """Update onboarding step data (partial save)"""
        profile = request.user.profile
        data = request.data
        
        # Update step tracker
        if 'current_step' in data and hasattr(profile, 'onboarding_step'):
            profile.onboarding_step = data['current_step']
        
        # Update basic fields
        if 'user_type' in data:
            profile.user_type = data['user_type']
        
        if 'class_level' in data and data['class_level']:
            try:
                profile.class_level = ClassLevel.objects.get(id=data['class_level'])
            except ClassLevel.DoesNotExist:
                pass
        
        if 'learning_style' in data and hasattr(profile, 'learning_style'):
            profile.learning_style = data['learning_style']
        
        if 'study_frequency' in data and hasattr(profile, 'study_frequency'):
            profile.study_frequency = data['study_frequency']
        
        if 'daily_goal_minutes' in data and hasattr(profile, 'daily_goal_minutes'):
            profile.daily_goal_minutes = data['daily_goal_minutes']
        
        if 'learning_goals' in data and hasattr(profile, 'learning_goals'):
            profile.learning_goals = data['learning_goals']
        
        if 'bio' in data:
            profile.bio = data['bio']
        
        profile.save()
        
        return Response({
            'message': 'Onboarding data updated',
            'current_step': getattr(profile, 'onboarding_step', 0)
        })
    
    @transaction.atomic
    def post(self, request):
        """Complete onboarding with all data"""
        profile = request.user.profile
        data = request.data

        try:
            user_type = data.get('user_type', profile.user_type)
            profile.user_type = user_type

            if 'bio' in data:
                profile.bio = data['bio']

            if user_type == 'teacher':
                # ---- Teacher-specific onboarding ----
                # Teaching class levels
                if 'teaching_class_levels' in data:
                    levels = ClassLevel.objects.filter(id__in=data['teaching_class_levels'])
                    profile.teaching_class_levels.set(levels)

                # Teaching subjects
                if 'teaching_subjects' in data:
                    subjects = Subject.objects.filter(id__in=data['teaching_subjects'])
                    profile.teaching_subjects.set(subjects)

                # Generate teacher code if missing
                profile.save()
                profile.ensure_teacher_code()

            else:
                # ---- Student-specific onboarding ----
                if 'class_level' in data and data['class_level']:
                    try:
                        profile.class_level = ClassLevel.objects.get(id=data['class_level'])
                    except ClassLevel.DoesNotExist:
                        return Response(
                            {'error': f"Class level {data['class_level']} not found"},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                if 'study_frequency' in data:
                    profile.study_frequency = data['study_frequency']

                if 'daily_goal_minutes' in data:
                    profile.daily_goal_minutes = data['daily_goal_minutes']

                if 'learning_goals' in data:
                    profile.learning_goals = data['learning_goals']

                # Favorite subjects
                if 'favorite_subjects' in data:
                    profile.target_subjects.clear()
                    if data['favorite_subjects']:
                        subjects = Subject.objects.filter(id__in=data['favorite_subjects'])
                        profile.target_subjects.add(*subjects)

                # Subject grades
                if 'subject_grades' in data:
                    SubjectGrade.objects.filter(user=profile).delete()
                    for grade_data in data['subject_grades']:
                        try:
                            subject = Subject.objects.get(id=grade_data['subject'])
                            current = grade_data.get('current', grade_data.get('min_grade', 10))
                            target = grade_data.get('target', grade_data.get('max_grade', 15))
                            SubjectGrade.objects.create(
                                user=profile,
                                subject=subject,
                                min_grade=current,
                                max_grade=target,
                            )
                        except Subject.DoesNotExist:
                            continue

                profile.save()

            # Mark onboarding as completed
            profile.onboarding_completed = True
            profile.onboarding_step = 5
            profile.save(update_fields=['onboarding_completed', 'onboarding_step'])

            return Response({
                'message': 'Onboarding completed successfully',
                'completed': True,
                'teacher_code': profile.teacher_code if user_type == 'teacher' else None,
            })

        except Exception as e:
            logger.error(f"Onboarding error: {str(e)}")
            return Response(
                {'error': f'Failed to complete onboarding: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============ USER PROFILE VIEWSET ============

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
        try:
            user = self.get_object() if self.action != 'list' else None
            if user and self.request.user.is_authenticated:
                context['is_owner'] = user.id == self.request.user.id
        except Exception:
            # If object doesn't exist, don't set is_owner
            pass
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
        
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot check other users\' onboarding status'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return Response({
            'onboarding_completed': user.profile.onboarding_completed,
            'needs_profile_completion': not user.profile.onboarding_completed
        })
    
    @action(detail=True, methods=['get'])
    def stats(self, request, username=None):
        user = self.get_object()
        
        is_owner = request.user.is_authenticated and request.user.id == user.id
        
        if not is_owner and not user.profile.display_stats and not request.user.is_superuser:
            return Response(
                {'error': 'This user\'s statistics are private'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        contribution_stats = user.profile.get_contribution_stats()
        
        response_data = {
            'contribution_stats': contribution_stats,
            'learning_stats': {}
        }
        
        if is_owner or request.user.is_superuser:
            response_data['learning_stats'] = user.profile.get_learning_stats()
        
        return Response(response_data)
    
    @action(detail=True, methods=['get'])
    def contributions(self, request, username=None):
        user = self.get_object()
        items = Content.objects.filter(author=user).order_by('-created_at')
        page = self.paginate_queryset(items)
        if page is not None:
            return self.get_paginated_response(ContentListSerializer(page, many=True, context={'request': request}).data)
        return Response(ContentListSerializer(items, many=True, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def saved_exercises(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' saved exercises"}, status=status.HTTP_403_FORBIDDEN)
        return self._saved_by_type(user, 'exercise', request)

    @action(detail=True, methods=['get'])
    def saved_lessons(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' saved lessons"}, status=status.HTTP_403_FORBIDDEN)
        return self._saved_by_type(user, 'lesson', request)

    @action(detail=True, methods=['get'])
    def saved_exams(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' saved exams"}, status=status.HTTP_403_FORBIDDEN)
        return self._saved_by_type(user, 'exam', request)

    def _saved_by_type(self, user, content_type_str, request):
        ct = ContentType.objects.get_for_model(Content)
        type_ids = Content.objects.filter(type=content_type_str).values_list('id', flat=True)
        saved_ids = Save.objects.filter(
            user=user, content_type=ct, object_id__in=type_ids
        ).order_by('-saved_at').values_list('object_id', flat=True)
        items = Content.objects.filter(id__in=saved_ids)
        return Response(ContentListSerializer(items, many=True, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def history(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' history"}, status=status.HTTP_403_FORBIDDEN)
        history = ViewHistory.objects.filter(user=user).order_by('-viewed_at')
        return Response(ViewHistorySerializer(history, many=True, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def success_thing(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' progress"})
        return self._completed_by_status(user, 'success', request)

    @action(detail=True, methods=['get'])
    def review_thing(self, request, username=None):
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response({'error': "You cannot view other users' progress"})
        return self._completed_by_status(user, 'review', request)

    def _completed_by_status(self, user, status_val, request):
        ct = ContentType.objects.get_for_model(Content)
        exercise_ids = Content.objects.filter(type='exercise').values_list('id', flat=True)
        complete_ids = Complete.objects.filter(
            user=user, status=status_val, content_type=ct, object_id__in=exercise_ids
        ).order_by('-updated_at').values_list('object_id', flat=True)
        items = Content.objects.filter(id__in=complete_ids)
        return Response(ContentListSerializer(items, many=True, context={'request': request}).data)


# ============ SUBJECT GRADE VIEWSET ============

class SubjectGradeViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectGradeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SubjectGrade.objects.filter(user=self.request.user.profile)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user.profile)


# ============ USER SETTINGS ============

class UserSettingsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSettingsSerializer(request.user.profile)
        return Response(serializer.data)
    
    def patch(self, request):
        serializer = UserSettingsSerializer(
            request.user.profile, 
            data=request.data, 
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_content_viewed(request, content_id):
    """Mark content as viewed and update view count"""
    try:
        content = Content.objects.get(id=content_id)
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
    except Content.DoesNotExist:
        return Response(
            {'error': 'Content not found'},
            status=status.HTTP_404_NOT_FOUND
        )


# ============ TEACHER INVITATIONS ============

from .models import TeacherInvitation


class TeacherInvitationView(APIView):
    """
    POST   — prof envoie une invitation à un élève (by username ou teacher_code)
    GET    — prof liste ses invitations en attente + ses élèves actuels
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        if profile.user_type != 'teacher':
            return Response({'error': 'Réservé aux enseignants'}, status=status.HTTP_403_FORBIDDEN)

        # Élèves déjà liés
        students = profile.students.select_related('user').all()
        students_data = [
            {
                'id': s.user.id,
                'username': s.user.username,
                'avatar': s.avatar,
                'class_level': s.class_level.name if s.class_level else None,
            }
            for s in students
        ]

        # Invitations envoyées
        invitations = TeacherInvitation.objects.filter(teacher=profile).select_related('student__user', 'student__class_level')
        invitations_data = [
            {
                'id': inv.id,
                'student_username': inv.student.user.username,
                'student_avatar': inv.student.avatar,
                'student_class_level': inv.student.class_level.name if inv.student.class_level else None,
                'status': inv.status,
                'created_at': inv.created_at,
            }
            for inv in invitations
        ]

        return Response({'students': students_data, 'invitations': invitations_data})

    def post(self, request):
        profile = request.user.profile
        if profile.user_type != 'teacher':
            return Response({'error': 'Réservé aux enseignants'}, status=status.HTTP_403_FORBIDDEN)

        identifier = request.data.get('identifier', '').strip()
        if not identifier:
            return Response({'error': 'Fournissez un nom d\'utilisateur ou un code élève'}, status=status.HTTP_400_BAD_REQUEST)

        # Recherche par username
        try:
            target_user = User.objects.get(username=identifier)
            student_profile = target_user.profile
        except User.DoesNotExist:
            return Response({'error': f'Utilisateur "{identifier}" introuvable'}, status=status.HTTP_404_NOT_FOUND)

        if student_profile.user_type != 'student':
            return Response({'error': 'Cet utilisateur n\'est pas un élève'}, status=status.HTTP_400_BAD_REQUEST)

        if student_profile == profile:
            return Response({'error': 'Vous ne pouvez pas vous inviter vous-même'}, status=status.HTTP_400_BAD_REQUEST)

        # Déjà lié
        if student_profile.teacher == profile:
            return Response({'error': 'Cet élève est déjà dans votre classe'}, status=status.HTTP_400_BAD_REQUEST)

        inv, created = TeacherInvitation.objects.get_or_create(
            teacher=profile,
            student=student_profile,
            defaults={'status': 'pending'},
        )

        if not created:
            if inv.status == 'pending':
                return Response({'error': 'Une invitation est déjà en attente pour cet élève'}, status=status.HTTP_400_BAD_REQUEST)
            # Renvoi d'invitation refusée/expirée
            inv.status = 'pending'
            inv.save(update_fields=['status', 'updated_at'])

        return Response({
            'message': f'Invitation envoyée à {student_profile.user.username}',
            'invitation_id': inv.id,
        }, status=status.HTTP_201_CREATED)


class TeacherInvitationRespondView(APIView):
    """
    PATCH /teacher-invitations/<id>/respond/
    body: { "action": "accept" | "decline" }
    — appelé par l'élève
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, invitation_id):
        try:
            inv = TeacherInvitation.objects.select_related('teacher', 'student__user').get(pk=invitation_id)
        except TeacherInvitation.DoesNotExist:
            return Response({'error': 'Invitation introuvable'}, status=status.HTTP_404_NOT_FOUND)

        if inv.student.user != request.user:
            return Response({'error': 'Non autorisé'}, status=status.HTTP_403_FORBIDDEN)

        if inv.status != 'pending':
            return Response({'error': 'Cette invitation a déjà été traitée'}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get('action')
        if action == 'accept':
            inv.status = 'accepted'
            inv.save(update_fields=['status', 'updated_at'])
            # Lier l'élève au prof
            inv.student.teacher = inv.teacher
            inv.student.save(update_fields=['teacher'])
            return Response({'message': 'Invitation acceptée'})
        elif action == 'decline':
            inv.status = 'declined'
            inv.save(update_fields=['status', 'updated_at'])
            return Response({'message': 'Invitation refusée'})
        else:
            return Response({'error': 'action invalide, utilisez "accept" ou "decline"'}, status=status.HTTP_400_BAD_REQUEST)


class TeacherInvitationDeleteView(APIView):
    """
    DELETE /teacher-invitations/<id>/  — prof annule une invitation ou retire un élève
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, invitation_id):
        profile = request.user.profile
        try:
            inv = TeacherInvitation.objects.get(pk=invitation_id, teacher=profile)
        except TeacherInvitation.DoesNotExist:
            return Response({'error': 'Invitation introuvable'}, status=status.HTTP_404_NOT_FOUND)

        # Si déjà acceptée, délier l'élève
        if inv.status == 'accepted':
            inv.student.teacher = None
            inv.student.save(update_fields=['teacher'])

        inv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentInvitationsView(APIView):
    """
    GET — élève liste ses invitations reçues en attente
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        invitations = TeacherInvitation.objects.filter(
            student=profile, status='pending'
        ).select_related('teacher__user', 'teacher__class_level')

        data = [
            {
                'id': inv.id,
                'teacher_username': inv.teacher.user.username,
                'teacher_avatar': inv.teacher.avatar,
                'teacher_code': inv.teacher.teacher_code,
                'teaching_subjects': [s.name for s in inv.teacher.teaching_subjects.all()],
                'created_at': inv.created_at,
            }
            for inv in invitations
        ]
        return Response(data)


# ---------------------------------------------------------------------------
# Password & account info
# ---------------------------------------------------------------------------

class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        if not current_password or not new_password:
            return Response({'error': 'Mot de passe actuel et nouveau mot de passe requis'}, status=status.HTTP_400_BAD_REQUEST)
        if not request.user.check_password(current_password):
            return Response({'error': 'Mot de passe actuel incorrect'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 8:
            return Response({'error': 'Le nouveau mot de passe doit contenir au moins 8 caractères'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        return Response({'message': 'Mot de passe changé avec succès'})


class UpdateUserInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        user = request.user
        updated_fields = []

        for field in ('first_name', 'last_name'):
            if (val := request.data.get(field)) is not None:
                setattr(user, field, val)
                updated_fields.append(field)

        if (email := request.data.get('email')) is not None:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                return Response({'error': 'Cet email est déjà utilisé'}, status=status.HTTP_400_BAD_REQUEST)
            user.email = email
            updated_fields.append('email')

        if updated_fields:
            user.save(update_fields=updated_fields)

        return Response({'message': 'Informations mises à jour', 'user': {
            'id': user.id, 'username': user.username,
            'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name,
        }})


class UpdateMeView(APIView):
    """PATCH /api/users/me/ — update own profile without username in URL"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        user = request.user
        user_updated_fields = []

        # Username change
        if (new_username := request.data.get('username')) is not None:
            new_username = new_username.strip()
            if not new_username:
                return Response({'error': "Le nom d'utilisateur ne peut pas être vide"}, status=status.HTTP_400_BAD_REQUEST)
            if new_username != user.username:
                if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                    return Response({'error': "Ce nom d'utilisateur est déjà pris"}, status=status.HTTP_400_BAD_REQUEST)
                user.username = new_username
                user_updated_fields.append('username')

        # Profile data
        profile_data = request.data.get('profile', None)

        if user_updated_fields:
            user.save(update_fields=user_updated_fields)

        if profile_data:
            serializer = UserSerializer(user, data={'profile': profile_data}, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user, context={'request': request, 'is_owner': True}).data)