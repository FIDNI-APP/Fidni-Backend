from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
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
    LearningPathSerializer, PathChapterSerializer,
    VideoSerializer, ChapterQuizSerializer,
    UserLearningPathProgressSerializer,
    QuizSubmissionSerializer, VideoProgressUpdateSerializer,
)


class LearningPathViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for learning paths"""
    queryset = LearningPath.objects.filter(is_active=True)
    serializer_class = LearningPathSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by class level
        class_level = self.request.query_params.get('class_level')
        if class_level:
            queryset = queryset.filter(class_level_id=class_level)
        
        # Filter by subject
        subject = self.request.query_params.get('subject')
        if subject:
            queryset = queryset.filter(subject_id=subject)
        
        return queryset.select_related('subject', 'class_level').prefetch_related('path_chapters')
    
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
            first_chapter = learning_path.path_chapters.first()
            if first_chapter:
                UserChapterProgress.objects.create(
                    user=request.user,
                    path_chapter=first_chapter,
                    path_progress=progress
                )
            
        serializer = UserLearningPathProgressSerializer(progress, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    # @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    # def my_paths(self, request):
    #     """Get user's active learning paths"""
    #     progress_records = UserLearningPathProgress.objects.filter(
    #         user=request.user
    #     ).select_related('learning_path__subject', 'learning_path__class_level')
        
    #     serializer = UserLearningPathProgressSerializer(progress_records, many=True, context={'request': request})
    #     return Response(serializer.data)
    
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
    


class PathChapterViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for path chapters"""
    queryset = PathChapter.objects.all()
    serializer_class = PathChapterSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_path(self, request, pk=None):
        """Start a chapter"""
        chapter = self.get_object()
        
        # Check if chapter is locked
        if chapter.is_locked_for_user(request.user):
            return Response(
                {'error': 'Chapter is locked. Complete prerequisites first.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get or create progress
        try:
            path_progress = UserLearningPathProgress.objects.get(
                user=request.user,
                learning_path=chapter.learning_path
            )
        except UserLearningPathProgress.DoesNotExist:
            return Response(
                {'error': 'Please start the learning path first'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        chapter_progress, created = UserChapterProgress.objects.get_or_create(
            user=request.user,
            path_chapter=chapter,
            path_progress=path_progress
        )
        
        return Response({
            'message': 'Chapter started' if created else 'Chapter resumed',
            'progress': chapter_progress.progress_percentage
        })
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        """Mark chapter as complete"""
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
        
        # Check if all videos are watched and quiz is passed
        videos_complete = not chapter.videos.exclude(
            user_progress__user=request.user,
            user_progress__is_completed=True
        ).exists()
        
        quiz_passed = True
        if hasattr(chapter, 'quiz'):
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
            
            # Award XP
            chapter_progress.path_progress.add_experience(50)
            
            return Response({'message': 'Chapter completed!', 'xp_earned': 50})
        else:
            return Response(
                {'error': 'Complete all videos and pass the quiz first'},
                status=status.HTTP_400_BAD_REQUEST
            )
    


class VideoViewSet(viewsets.ModelViewSet):
    """ViewSet for videos"""
    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_progress(self, request, pk=None):
        """Update video watching progress"""
        video = self.get_object()
        serializer = VideoProgressUpdateSerializer(data=request.data)
        
        if serializer.is_valid():
            # Get chapter progress
            try:
                chapter_progress = UserChapterProgress.objects.get(
                    user=request.user,
                    path_chapter=video.path_chapter
                )
            except UserChapterProgress.DoesNotExist:
                return Response(
                    {'error': 'Please start the chapter first'},
                    status=status.HTTP_400_BAD_REQUEST
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
            
            # Check if video is completed (90% watched)
            if video_progress.progress_percentage >= 90:
                video_progress.is_completed = True
                video_progress.completed_at = timezone.now()
                video_progress.save()
                
                # Update time spent
                chapter_progress.path_progress.total_time_seconds += serializer.validated_data['watched_seconds']
                chapter_progress.path_progress.save()
                
            return Response({
                'progress_percentage': video_progress.progress_percentage,
                'is_completed': video_progress.is_completed
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChapterQuizViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for chapter quizzes"""
    queryset = ChapterQuiz.objects.all()
    serializer_class = ChapterQuizSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_attempt(self, request, pk=None):
        """Start a new quiz attempt"""
        quiz = self.get_object()
        
        # Check attempts limit
        attempts_count = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz
        ).count()
        
        if attempts_count >= quiz.max_attempts:
            return Response(
                {'error': f'Maximum attempts ({quiz.max_attempts}) reached'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Create new attempt
        attempt = QuizAttempt.objects.create(
            user=request.user,
            quiz=quiz
        )
        
        # Get questions (shuffle if needed)
        questions = list(quiz.questions.all())
        if quiz.shuffle_questions:
            random.shuffle(questions)
        
        # Return questions without correct answers
        questions_data = []
        for q in questions:
            questions_data.append({
                'id': str(q.id),
                'question': q.question_text,
                'options': q.options,
                'difficulty': q.difficulty,
                'points': q.points
            })
        
        return Response({
            'attempt_id': str(attempt.id),
            'questions': questions_data,
            'time_limit_minutes': quiz.time_limit_minutes
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
                    
                    is_correct = answer_data['answer_index'] == question.correct_answer_index
                    if is_correct:
                        total_score += question.points
                    
                    # Save answer
                    QuizAnswer.objects.create(
                        attempt=attempt,
                        question=question,
                        selected_answer_index=answer_data['answer_index'],
                        is_correct=is_correct
                    )
                    
                    results.append({
                        'question_id': str(question.id),
                        'is_correct': is_correct,
                        'correct_answer': question.correct_answer_index if quiz.show_correct_answers else None,
                        'explanation': question.explanation if quiz.show_correct_answers else None
                    })
                
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
                    
                    if attempt.passed:
                        chapter_progress.quiz_score = int(percentage)
                        chapter_progress.save()
                        
                        # Award XP
                        chapter_progress.path_progress.add_experience(30)
                        
                    chapter_progress.quiz_attempts += 1
                    chapter_progress.save()
                except UserChapterProgress.DoesNotExist:
                    pass
            
            return Response({
                'score': int(percentage),
                'passed': attempt.passed,
                'correct_answers': len([r for r in results if r['is_correct']]),
                'total_questions': len(results),
                'results': results if quiz.show_correct_answers else None,
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)