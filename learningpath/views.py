from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Avg, Sum, Count, Q, F
from django.db import transaction
from datetime import timedelta, date
import random

from .models import (
    LearningPath, PathChapter, Video, ChapterQuiz,
    UserLearningPathProgress, UserChapterProgress,
    UserVideoProgress, QuizAttempt, QuizAnswer,
    Achievement, UserAchievement, LearningStreak,
    QuizQuestion
)
from .serializers import (
    LearningPathSerializer, PathChapterSerializer,
    VideoSerializer, ChapterQuizSerializer,
    UserLearningPathProgressSerializer,
    QuizSubmissionSerializer, VideoProgressUpdateSerializer,
    LearningPathStatsSerializer, AchievementSerializer
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
    def start(self, request, pk=None):
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
            
            # Track daily streak
            self._update_streak(request.user, learning_path)
        
        serializer = UserLearningPathProgressSerializer(progress)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_paths(self, request):
        """Get user's active learning paths"""
        progress_records = UserLearningPathProgress.objects.filter(
            user=request.user
        ).select_related('learning_path__subject', 'learning_path__class_level')
        
        serializer = UserLearningPathProgressSerializer(progress_records, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def stats(self, request, pk=None):
        """Get detailed statistics for a learning path"""
        learning_path = self.get_object()
        progress = get_object_or_404(
            UserLearningPathProgress,
            user=request.user,
            learning_path=learning_path
        )
        
        # Calculate statistics
        total_chapters = learning_path.path_chapters.count()
        completed_chapters = progress.chapter_progress.filter(is_completed=True).count()
        
        # Calculate average quiz score
        quiz_attempts = QuizAttempt.objects.filter(
            user=request.user,
            quiz__path_chapter__learning_path=learning_path,
            completed_at__isnull=False
        )
        avg_quiz_score = quiz_attempts.aggregate(avg=Avg('score'))['avg'] or 0
        
        # Get recent achievements
        recent_achievements = UserAchievement.objects.filter(
            user=request.user,
            path_progress=progress
        ).select_related('achievement').order_by('-earned_at')[:5]
        
        stats_data = {
            'total_progress': progress.progress_percentage,
            'current_streak': progress.current_streak,
            'longest_streak': progress.longest_streak,
            'total_time_spent': progress.total_time_seconds,
            'completed_chapters': completed_chapters,
            'total_chapters': total_chapters,
            'quiz_average': avg_quiz_score,
            'level': progress.level,
            'experience': progress.experience_points,
            'next_level_experience': progress.level * 100,
            'recent_achievements': AchievementSerializer(
                [ua.achievement for ua in recent_achievements],
                many=True,
                context={'request': request}
            ).data
        }
        
        return Response(stats_data)
    
    def _update_streak(self, user, learning_path):
        """Update user's learning streak"""
        today = date.today()
        
        # Check if already studied today
        streak_today = LearningStreak.objects.filter(
            user=user,
            date=today,
            learning_path=learning_path
        ).first()
        
        if not streak_today:
            LearningStreak.objects.create(
                user=user,
                date=today,
                learning_path=learning_path
            )
            
            # Update streak in progress
            progress = UserLearningPathProgress.objects.get(
                user=user,
                learning_path=learning_path
            )
            
            # Check if studied yesterday
            yesterday = today - timedelta(days=1)
            studied_yesterday = LearningStreak.objects.filter(
                user=user,
                date=yesterday,
                learning_path=learning_path
            ).exists()
            
            if studied_yesterday:
                progress.current_streak += 1
            else:
                progress.current_streak = 1
            
            # Update longest streak
            if progress.current_streak > progress.longest_streak:
                progress.longest_streak = progress.current_streak
            
            progress.save()
            
            # Check for streak achievements
            self._check_streak_achievements(user, progress)
    
    def _check_streak_achievements(self, user, progress):
        """Check and award streak achievements"""
        streak_achievements = Achievement.objects.filter(
            achievement_type='streak',
            related_path=progress.learning_path
        )
        
        for achievement in streak_achievements:
            if progress.current_streak >= achievement.required_value:
                UserAchievement.objects.get_or_create(
                    user=user,
                    achievement=achievement,
                    path_progress=progress
                )


class PathChapterViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for path chapters"""
    queryset = PathChapter.objects.all()
    serializer_class = PathChapterSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start(self, request, pk=None):
        """Start a chapter"""
        chapter = self.get_object()
        
        # Check if chapter is locked
        if chapter.is_locked_for_user(request.user):
            return Response(
                {'error': 'Chapter is locked. Complete prerequisites first.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get or create progress
        path_progress = get_object_or_404(
            UserLearningPathProgress,
            user=request.user,
            learning_path=chapter.learning_path
        )
        
        chapter_progress, created = UserChapterProgress.objects.get_or_create(
            user=request.user,
            path_chapter=chapter,
            path_progress=path_progress
        )
        
        return Response({
            'started': True,
            'chapter_id': str(chapter.id),
            'progress': chapter_progress.progress_percentage
        })
    
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def content(self, request, pk=None):
        """Get chapter content with user progress"""
        chapter = self.get_object()
        serializer = self.get_serializer(chapter)
        return Response(serializer.data)


class VideoViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for videos"""
    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_progress(self, request, pk=None):
        """Update video watch progress"""
        video = self.get_object()
        serializer = VideoProgressUpdateSerializer(data=request.data)
        
        if serializer.is_valid():
            chapter_progress = get_object_or_404(
                UserChapterProgress,
                user=request.user,
                path_chapter=video.path_chapter
            )
            
            video_progress, created = UserVideoProgress.objects.get_or_create(
                user=request.user,
                video=video,
                chapter_progress=chapter_progress
            )
            
            # Update progress
            video_progress.watched_seconds = serializer.validated_data['watched_seconds']
            
            # Check if video is completed (watched 90% or more)
            if video_progress.watched_seconds >= video.duration_seconds * 0.9:
                if not video_progress.is_completed:
                    video_progress.is_completed = True
                    video_progress.completed_at = timezone.now()
                    
                    # Award experience points
                    chapter_progress.path_progress.add_experience(10)
                    
                    # Check if chapter is completed
                    self._check_chapter_completion(chapter_progress)
            
            # Update notes if provided
            if 'notes' in serializer.validated_data:
                video_progress.notes = serializer.validated_data['notes']
            
            video_progress.save()
            
            # Update time tracking
            self._update_time_tracking(request.user, video, serializer.validated_data['watched_seconds'])
            
            return Response({
                'progress_percentage': video_progress.progress_percentage,
                'is_completed': video_progress.is_completed
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _check_chapter_completion(self, chapter_progress):
        """Check if all videos in chapter are completed"""
        total_videos = chapter_progress.path_chapter.videos.count()
        completed_videos = chapter_progress.video_progress.filter(is_completed=True).count()
        
        # If all videos completed and quiz passed (if exists)
        if completed_videos == total_videos:
            has_quiz = hasattr(chapter_progress.path_chapter, 'quiz')
            
            if not has_quiz or (chapter_progress.quiz_score and 
                                chapter_progress.quiz_score >= chapter_progress.path_chapter.quiz.passing_score):
                chapter_progress.is_completed = True
                chapter_progress.completed_at = timezone.now()
                chapter_progress.save()
                
                # Award experience for chapter completion
                chapter_progress.path_progress.add_experience(50)
                
                # Check for chapter completion achievement
                self._check_chapter_achievements(chapter_progress)
                
                # Unlock next chapters
                self._unlock_next_chapters(chapter_progress)
    
    def _check_chapter_achievements(self, chapter_progress):
        """Check and award chapter-related achievements"""
        achievements = Achievement.objects.filter(
            Q(achievement_type='chapter_complete') | Q(achievement_type='milestone'),
            related_chapter=chapter_progress.path_chapter
        )
        
        for achievement in achievements:
            UserAchievement.objects.get_or_create(
                user=chapter_progress.user,
                achievement=achievement,
                path_progress=chapter_progress.path_progress
            )
    
    def _unlock_next_chapters(self, chapter_progress):
        """Unlock chapters that have this chapter as prerequisite"""
        next_chapters = PathChapter.objects.filter(
            prerequisites=chapter_progress.path_chapter,
            learning_path=chapter_progress.path_chapter.learning_path
        )
        
        for chapter in next_chapters:
            # Check if all prerequisites are met
            if not chapter.is_locked_for_user(chapter_progress.user):
                # Create progress entry for unlocked chapter
                UserChapterProgress.objects.get_or_create(
                    user=chapter_progress.user,
                    path_chapter=chapter,
                    path_progress=chapter_progress.path_progress
                )
    
    def _update_time_tracking(self, user, video, watched_seconds):
        """Update time tracking statistics"""
        today = date.today()
        
        streak = LearningStreak.objects.filter(
            user=user,
            date=today,
            learning_path=video.path_chapter.learning_path
        ).first()
        
        if streak:
            streak.minutes_studied += watched_seconds // 60
            streak.videos_watched += 1
            streak.save()
        
        # Update total time in path progress
        path_progress = UserLearningPathProgress.objects.get(
            user=user,
            learning_path=video.path_chapter.learning_path
        )
        path_progress.total_time_seconds += watched_seconds
        path_progress.save()


class ChapterQuizViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for chapter quizzes"""
    queryset = ChapterQuiz.objects.all()
    serializer_class = ChapterQuizSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start_attempt(self, request, pk=None):
        """Start a new quiz attempt"""
        quiz = self.get_object()
        
        # Check if user has attempts left
        attempts_count = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz
        ).count()
        
        if quiz.max_attempts and attempts_count >= quiz.max_attempts:
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
                'question_text': q.question_text,
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
            attempt = get_object_or_404(
                QuizAttempt,
                id=attempt_id,
                user=request.user,
                quiz=quiz,
                completed_at__isnull=True
            )
            
            total_score = 0
            total_points = 0
            results = []
            
            with transaction.atomic():
                for answer_data in serializer.validated_data['answers']:
                    question = get_object_or_404(
                        QuizQuestion,
                        id=answer_data['question_id'],
                        quiz=quiz
                    )
                    
                    is_correct = answer_data['answer_index'] == question.correct_answer_index
                    
                    QuizAnswer.objects.create(
                        attempt=attempt,
                        question=question,
                        selected_answer_index=answer_data['answer_index'],
                        is_correct=is_correct
                    )
                    
                    if is_correct:
                        total_score += question.points
                    
                    total_points += question.points
                    
                    result = {
                        'question_id': str(question.id),
                        'is_correct': is_correct,
                        'correct_answer_index': question.correct_answer_index,
                        'explanation': question.explanation
                    }
                    
                    results.append(result)
                
                # Complete attempt
                attempt.completed_at = timezone.now()
                attempt.score = total_score
                attempt.passed = (total_score / total_points * 100) >= quiz.passing_score
                attempt.time_spent_seconds = int(
                    (attempt.completed_at - attempt.started_at).total_seconds()
                )
                attempt.save()
                
                # Update chapter progress
                chapter_progress = get_object_or_404(
                    UserChapterProgress,
                    user=request.user,
                    path_chapter=quiz.path_chapter
                )
                
                chapter_progress.quiz_score = int(total_score / total_points * 100)
                chapter_progress.quiz_attempts += 1
                chapter_progress.save()
                
                # Award experience
                if attempt.passed:
                    chapter_progress.path_progress.add_experience(30)
                    
                    # Check for perfect score achievement
                    if total_score == total_points:
                        self._check_quiz_achievements(request.user, quiz, chapter_progress.path_progress)
                    
                    # Check chapter completion
                    self._check_chapter_completion_quiz(chapter_progress)
            
            return Response({
                'score': attempt.percentage_score,
                'passed': attempt.passed,
                'total_points': total_points,
                'earned_points': total_score,
                'results': results if quiz.show_correct_answers else None
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _check_quiz_achievements(self, user, quiz, path_progress):
        """Check for quiz-related achievements"""
        achievements = Achievement.objects.filter(
            achievement_type='quiz_perfect',
            related_chapter=quiz.path_chapter
        )
        
        for achievement in achievements:
            UserAchievement.objects.get_or_create(
                user=user,
                achievement=achievement,
                path_progress=path_progress
            )
    
    def _check_chapter_completion_quiz(self, chapter_progress):
        """Check if chapter is completed after quiz"""
        # This is called from video completion check
        video_progress = UserVideoProgress.objects.filter(
            chapter_progress=chapter_progress
        )
        
        all_videos_completed = all(vp.is_completed for vp in video_progress)
        
        if all_videos_completed and chapter_progress.quiz_score >= chapter_progress.path_chapter.quiz.passing_score:
            chapter_progress.is_completed = True
            chapter_progress.completed_at = timezone.now()
            chapter_progress.save()


class LearningPathStatsViewSet(viewsets.ViewSet):
    """ViewSet for overall learning statistics"""
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get user's overall learning statistics"""
        user = request.user
        
        # Get all user's learning paths
        all_progress = UserLearningPathProgress.objects.filter(user=user)
        
        # Calculate overall stats
        total_time = all_progress.aggregate(total=Sum('total_time_seconds'))['total'] or 0
        total_chapters_completed = UserChapterProgress.objects.filter(
            user=user,
            is_completed=True
        ).count()
        
        # Current streak (across all paths)
        today = date.today()
        current_streak = 0
        check_date = today
        
        while LearningStreak.objects.filter(user=user, date=check_date).exists():
            current_streak += 1
            check_date -= timedelta(days=1)
        
        # Recent activity
        recent_videos = UserVideoProgress.objects.filter(
            user=user
        ).select_related('video').order_by('-completed_at')[:10]
        
        # All achievements
        all_achievements = UserAchievement.objects.filter(
            user=user
        ).select_related('achievement').order_by('-earned_at')
        
        return Response({
            'total_paths_started': all_progress.count(),
            'total_time_spent_hours': total_time // 3600,
            'total_chapters_completed': total_chapters_completed,
            'current_streak_days': current_streak,
            'total_achievements': all_achievements.count(),
            'recent_activity': VideoSerializer(
                [vp.video for vp in recent_videos],
                many=True,
                context={'request': request}
            ).data,
            'achievements': AchievementSerializer(
                [ua.achievement for ua in all_achievements],
                many=True,
                context={'request': request}
            ).data
        })