from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, IsAdminUser
from django.utils import timezone
from django.db.models import Avg, Sum, Count
from django.db import transaction
import random

from .models import (
    LearningPath, PathChapter, Video, ChapterQuiz,
    UserLearningPathProgress, UserChapterProgress,
    UserVideoProgress, QuizAttempt, QuizAnswer,
    QuizQuestion
)
from .serializers import (
    LearningPathSerializer, LearningPathCreateSerializer,
    PathChapterSerializer, PathChapterCreateSerializer,
    VideoSerializer, ChapterQuizSerializer,
    QuizSubmissionSerializer, VideoProgressUpdateSerializer,
    UserLearningPathProgressSerializer
)


class LearningPathViewSet(viewsets.ModelViewSet):
    """ViewSet for learning paths"""
    queryset = LearningPath.objects.filter(is_active=True)
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LearningPathCreateSerializer
        return LearningPathSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by class level
        class_level = self.request.query_params.get('class_level')
        if class_level:
            queryset = queryset.filter(class_level__id=class_level)
        
        # Filter by subject
        subject = self.request.query_params.get('subject')
        if subject:
            queryset = queryset.filter(subject_id=subject)
        
        return queryset.select_related('subject').prefetch_related(
            'class_level', 'path_chapters__videos', 'path_chapters__quiz'
        )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_path(self, request, pk=None):
        """Start or resume a learning path"""
        learning_path = self.get_object()
        
        progress, created = UserLearningPathProgress.objects.get_or_create(
            user=request.user,
            learning_path=learning_path
        )
        
        if created:
            # Create chapter progress for the first chapter
            first_chapter = learning_path.path_chapters.order_by('order').first()
            if first_chapter:
                UserChapterProgress.objects.create(
                    user=request.user,
                    path_chapter=first_chapter,
                    path_progress=progress
                )
        
        return Response({
            'message': 'Learning path started' if created else 'Learning path resumed',
            'progress_id': progress.id,
            'started_at': progress.started_at,
            'progress_percentage': progress.progress_percentage
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_paths(self, request):
        """Get user's active learning paths"""
        progress_records = UserLearningPathProgress.objects.filter(
            user=request.user
        ).select_related('learning_path__subject').prefetch_related('learning_path__class_level')
        
        serializer = UserLearningPathProgressSerializer(
            progress_records, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def stats(self, request, pk=None):
        """Get detailed statistics for a learning path"""
        learning_path = self.get_object()
        
        try:
            progress = UserLearningPathProgress.objects.get(
                user=request.user,
                learning_path=learning_path
            )
        except UserLearningPathProgress.DoesNotExist:
            return Response(
                {'error': 'You have not started this learning path yet'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Calculate statistics
        total_videos = Video.objects.filter(path_chapter__learning_path=learning_path).count()
        watched_videos = UserVideoProgress.objects.filter(
            user=request.user,
            video__path_chapter__learning_path=learning_path,
            is_completed=True
        ).count()
        
        quiz_stats = QuizAttempt.objects.filter(
            user=request.user,
            quiz__path_chapter__learning_path=learning_path
        ).aggregate(
            avg_score=Avg('score'),
            total_attempts=Count('id')
        )
        
        return Response({
            'total_progress': progress.progress_percentage,
            'total_time_spent': progress.total_time_seconds,
            'completed_chapters': progress.completed_chapters_count,
            'total_chapters': learning_path.total_chapters,
            'quiz_average': quiz_stats['avg_score'] or 0,
            'videos_watched': watched_videos,
            'total_videos': total_videos
        })


class PathChapterViewSet(viewsets.ModelViewSet):
    """ViewSet for path chapters"""
    queryset = PathChapter.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PathChapterCreateSerializer
        return PathChapterSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by learning path
        learning_path = self.request.query_params.get('learning_path')
        if learning_path:
            queryset = queryset.filter(learning_path_id=learning_path)
        
        return queryset.select_related('learning_path', 'chapter').prefetch_related(
            'videos__resources', 'quiz__questions'
        ).order_by('learning_path', 'order')
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_chapter(self, request, pk=None):
        """Start a chapter"""
        chapter = self.get_object()
        
        # Get or create learning path progress
        path_progress, created = UserLearningPathProgress.objects.get_or_create(
            user=request.user,
            learning_path=chapter.learning_path
        )
        
        # Create chapter progress
        chapter_progress, created = UserChapterProgress.objects.get_or_create(
            user=request.user,
            path_chapter=chapter,
            path_progress=path_progress
        )
        
        return Response({
            'message': 'Chapter started' if created else 'Chapter resumed',
            'progress_percentage': chapter_progress.progress_percentage,
            'is_completed': chapter_progress.is_completed
        })
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        """Mark chapter as complete (auto-check requirements)"""
        chapter = self.get_object()
        
        try:
            chapter_progress = UserChapterProgress.objects.get(
                user=request.user,
                path_chapter=chapter
            )
        except UserChapterProgress.DoesNotExist:
            return Response(
                {'error': 'Chapter not started yet'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if all required videos are watched
        required_videos = chapter.videos.filter(is_required=True)
        videos_complete = not required_videos.exclude(
            user_progress__user=request.user,
            user_progress__is_completed=True
        ).exists()
        
        # Check if quiz is passed (if exists and required)
        quiz_passed = True
        if hasattr(chapter, 'quiz') and chapter.quiz.is_required:
            quiz_attempt = QuizAttempt.objects.filter(
                user=request.user,
                quiz=chapter.quiz,
                passed=True
            ).exists()
            quiz_passed = quiz_attempt
        
        if videos_complete and quiz_passed:
            chapter_progress.is_completed = True
            chapter_progress.completed_at = timezone.now()
            chapter_progress.save()
            
            # Update path progress last activity
            chapter_progress.path_progress.last_activity = timezone.now()
            chapter_progress.path_progress.save()
            
            return Response({
                'message': 'Chapter completed!',
                'progress_percentage': chapter_progress.progress_percentage
            })
        else:
            missing_requirements = []
            if not videos_complete:
                missing_requirements.append('Complete all required videos')
            if not quiz_passed:
                missing_requirements.append('Pass the chapter quiz')
                
            return Response({
                'error': 'Chapter requirements not met',
                'missing_requirements': missing_requirements
            }, status=status.HTTP_400_BAD_REQUEST)


class VideoViewSet(viewsets.ModelViewSet):
    """ViewSet for videos"""
    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by chapter
        chapter = self.request.query_params.get('chapter')
        if chapter:
            queryset = queryset.filter(path_chapter_id=chapter)
        
        return queryset.select_related('path_chapter').prefetch_related('resources').order_by('order')
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_progress(self, request, pk=None):
        """Update video watching progress"""
        video = self.get_object()
        serializer = VideoProgressUpdateSerializer(data=request.data)
        
        if serializer.is_valid():
            # Get or create chapter progress
            path_progress, _ = UserLearningPathProgress.objects.get_or_create(
                user=request.user,
                learning_path=video.path_chapter.learning_path
            )
            
            chapter_progress, _ = UserChapterProgress.objects.get_or_create(
                user=request.user,
                path_chapter=video.path_chapter,
                path_progress=path_progress
            )
            
            # Update video progress
            video_progress, created = UserVideoProgress.objects.update_or_create(
                user=request.user,
                video=video,
                chapter_progress=chapter_progress,
                defaults={
                    'watched_seconds': serializer.validated_data['watched_seconds'],
                    'notes': serializer.validated_data.get('notes', '')
                }
            )
            
            # Check if video is completed (90% watched or user marked as complete)
            completion_threshold = int(video.duration_seconds * 0.9)
            is_manually_completed = serializer.validated_data.get('is_completed', False)
            
            if (video_progress.watched_seconds >= completion_threshold or is_manually_completed) and not video_progress.is_completed:
                video_progress.is_completed = True
                video_progress.completed_at = timezone.now()
                video_progress.save()
                
                # Update path progress time
                time_to_add = min(video_progress.watched_seconds, video.duration_seconds)
                path_progress.total_time_seconds += time_to_add
                path_progress.last_activity = timezone.now()
                path_progress.save()
            
            return Response({
                'progress_percentage': video_progress.progress_percentage,
                'is_completed': video_progress.is_completed,
                'watched_seconds': video_progress.watched_seconds
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def toggle_completion(self, request, pk=None):
        """Toggle video completion status"""
        video = self.get_object()
        
        # Get or create progress
        path_progress, _ = UserLearningPathProgress.objects.get_or_create(
            user=request.user,
            learning_path=video.path_chapter.learning_path
        )
        
        chapter_progress, _ = UserChapterProgress.objects.get_or_create(
            user=request.user,
            path_chapter=video.path_chapter,
            path_progress=path_progress
        )
        
        video_progress, _ = UserVideoProgress.objects.get_or_create(
            user=request.user,
            video=video,
            chapter_progress=chapter_progress
        )
        
        # Toggle completion
        video_progress.is_completed = not video_progress.is_completed
        if video_progress.is_completed:
            video_progress.completed_at = timezone.now()
            video_progress.watched_seconds = video.duration_seconds
        else:
            video_progress.completed_at = None
        
        video_progress.save()
        
        return Response({
            'is_completed': video_progress.is_completed,
            'progress_percentage': video_progress.progress_percentage
        })


class ChapterQuizViewSet(viewsets.ModelViewSet):
    """ViewSet for chapter quizzes"""
    queryset = ChapterQuiz.objects.all()
    serializer_class = ChapterQuizSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by chapter
        chapter = self.request.query_params.get('chapter')
        if chapter:
            queryset = queryset.filter(path_chapter_id=chapter)
        
        return queryset.select_related('path_chapter').prefetch_related('questions')
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_attempt(self, request, pk=None):
        """Start a new quiz attempt"""
        quiz = self.get_object()
        
        # Check if user has started the chapter
        try:
            chapter_progress = UserChapterProgress.objects.get(
                user=request.user,
                path_chapter=quiz.path_chapter
            )
        except UserChapterProgress.DoesNotExist:
            return Response(
                {'error': 'Please start the chapter first'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if there's an incomplete attempt
        incomplete_attempt = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            completed_at__isnull=True
        ).first()
        
        if incomplete_attempt:
            return Response(
                {'error': 'You have an incomplete attempt. Please complete or abandon it first.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create new attempt
        attempt = QuizAttempt.objects.create(
            user=request.user,
            quiz=quiz
        )
        
        # Get questions (shuffle if needed)
        questions = list(quiz.questions.order_by('order'))
        if quiz.shuffle_questions:
            random.shuffle(questions)
        
        # Return questions without correct answers
        questions_data = []
        for q in questions:
            question_data = {
                'id': q.id,
                'question_text': q.question_text,
                'question_type': q.question_type,
                'options': q.options,
                'difficulty': q.difficulty,
                'points': q.points
            }
            questions_data.append(question_data)
        
        return Response({
            'attempt_id': attempt.id,
            'questions': questions_data,
            'time_limit_minutes': quiz.time_limit_minutes,
            'total_questions': len(questions_data)
        })
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def submit_attempt(self, request, pk=None):
        """Submit quiz answers"""
        quiz = self.get_object()
        serializer = QuizSubmissionSerializer(data=request.data)
        
        if serializer.is_valid():
            attempt_id = request.data.get('attempt_id')
            
            try:
                attempt = QuizAttempt.objects.get(
                    id=attempt_id,
                    user=request.user,
                    quiz=quiz,
                    completed_at__isnull=True
                )
            except QuizAttempt.DoesNotExist:
                return Response(
                    {'error': 'Invalid attempt or attempt already completed'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Process answers
            total_score = 0
            results = []
            
            with transaction.atomic():
                for answer_data in serializer.validated_data['answers']:
                    try:
                        question = QuizQuestion.objects.get(
                            id=answer_data['question_id'],
                            quiz=quiz
                        )
                    except QuizQuestion.DoesNotExist:
                        continue
                    
                    # Handle different question types
                    is_correct = False
                    selected_index = answer_data.get('answer_index')
                    selected_indices = answer_data.get('answer_indices', [])
                    
                    if question.question_type in ['multiple_choice', 'true_false']:
                        is_correct = selected_index == question.correct_answer_index
                    elif question.question_type == 'multiple_select':
                        is_correct = set(selected_indices) == set(question.correct_answer_indices or [])
                    
                    if is_correct:
                        total_score += question.points
                    
                    # Save answer
                    QuizAnswer.objects.create(
                        attempt=attempt,
                        question=question,
                        selected_answer_index=selected_index,
                        selected_answer_indices=selected_indices,
                        is_correct=is_correct
                    )
                    
                    result_data = {
                        'question_id': question.id,
                        'is_correct': is_correct,
                        'your_answer': selected_index if selected_index is not None else selected_indices
                    }
                    
                    if quiz.show_correct_answers:
                        if question.question_type in ['multiple_choice', 'true_false']:
                            result_data['correct_answer'] = question.correct_answer_index
                        else:
                            result_data['correct_answer'] = question.correct_answer_indices
                        result_data['explanation'] = question.explanation
                    
                    results.append(result_data)
                
                # Complete attempt
                attempt.completed_at = timezone.now()
                attempt.score = total_score
                attempt.time_spent_seconds = int((attempt.completed_at - attempt.started_at).total_seconds())
                
                # Calculate percentage
                total_possible = quiz.questions.aggregate(total=Sum('points'))['total'] or 0
                percentage = (total_score / total_possible * 100) if total_possible > 0 else 0
                attempt.passed = percentage >= quiz.passing_score
                attempt.save()
                
                # Update chapter progress
                try:
                    chapter_progress = UserChapterProgress.objects.get(
                        user=request.user,
                        path_chapter=quiz.path_chapter
                    )
                    
                    chapter_progress.quiz_attempts += 1
                    
                    if attempt.passed:
                        chapter_progress.quiz_score = int(percentage)
                        chapter_progress.quiz_passed = True
                    
                    chapter_progress.save()
                    
                    # Update path progress
                    chapter_progress.path_progress.last_activity = timezone.now()
                    chapter_progress.path_progress.save()
                    
                except UserChapterProgress.DoesNotExist:
                    pass
            
            return Response({
                'score': int(percentage),
                'passed': attempt.passed,
                'correct_answers': len([r for r in results if r['is_correct']]),
                'total_questions': len(results),
                'time_spent_seconds': attempt.time_spent_seconds,
                'results': results if quiz.show_correct_answers else None,
                'passing_score': quiz.passing_score
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def abandon_attempt(self, request, pk=None):
        """Abandon current quiz attempt"""
        quiz = self.get_object()
        
        try:
            attempt = QuizAttempt.objects.get(
                user=request.user,
                quiz=quiz,
                completed_at__isnull=True
            )
            attempt.delete()
            return Response({'message': 'Attempt abandoned successfully'})
        except QuizAttempt.DoesNotExist:
            return Response(
                {'error': 'No active attempt found'},
                status=status.HTTP_404_NOT_FOUND
            )