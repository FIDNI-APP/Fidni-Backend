from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import (
    LearningPath, PathChapter, Video, VideoResource,
    ChapterQuiz, QuizQuestion, Achievement,
    UserLearningPathProgress, UserChapterProgress,
    UserVideoProgress, QuizAttempt, QuizAnswer,
    UserAchievement, LearningStreak
)
from caracteristics.serializers import SubjectSerializer, ClassLevelSerializer, ChapterSerializer
from users.serializers import UserSerializer


class VideoResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoResource
        fields = ['id', 'title', 'resource_type', 'url', 'order']


class VideoSerializer(serializers.ModelSerializer):
    resources = VideoResourceSerializer(many=True, read_only=True)
    duration = serializers.CharField(source='duration_display', read_only=True)
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = Video
        fields = [
            'id', 'title', 'description', 'url', 'thumbnail_url',
            'video_type', 'duration_seconds', 'duration', 'order',
            'transcript', 'resources', 'user_progress'
        ]
    
    def get_user_progress(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress = UserVideoProgress.objects.filter(
                user=request.user,
                video=obj
            ).first()
            if progress:
                return {
                    'watched_seconds': progress.watched_seconds,
                    'is_completed': progress.is_completed,
                    'progress_percentage': progress.progress_percentage,
                    'notes': progress.notes
                }
        return None


class QuizQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = [
            'id', 'question_text', 'options', 'correct_answer_index',
            'explanation', 'difficulty', 'points', 'order'
        ]
        extra_kwargs = {
            'correct_answer_index': {'write_only': True},
            'explanation': {'write_only': True}
        }


class ChapterQuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    user_attempts = serializers.SerializerMethodField()
    
    class Meta:
        model = ChapterQuiz
        fields = [
            'id', 'title', 'description', 'passing_score',
            'time_limit_minutes', 'max_attempts', 'shuffle_questions',
            'show_correct_answers', 'questions', 'user_attempts'
        ]
    
    def get_user_attempts(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            attempts = QuizAttempt.objects.filter(
                user=request.user,
                quiz=obj
            ).order_by('-started_at')[:5]  # Last 5 attempts
            
            return [{
                'id': str(attempt.id),
                'started_at': attempt.started_at,
                'score': attempt.percentage_score,
                'passed': attempt.passed,
                'time_spent_seconds': attempt.time_spent_seconds
            } for attempt in attempts]
        return []


class PathChapterSerializer(serializers.ModelSerializer):
    chapter = ChapterSerializer(read_only=True)
    videos = VideoSerializer(many=True, read_only=True)
    quiz = ChapterQuizSerializer(read_only=True)
    user_progress = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    estimated_time = serializers.CharField(source='estimated_minutes', read_only=True)
    
    class Meta:
        model = PathChapter
        fields = [
            'id', 'order', 'title', 'description', 'chapter',
            'estimated_time', 'is_milestone', 'videos', 'quiz',
            'user_progress', 'is_locked', 'total_videos',
            'total_quiz_questions'
        ]
    
    def get_user_progress(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress = UserChapterProgress.objects.filter(
                user=request.user,
                path_chapter=obj
            ).first()
            if progress:
                return {
                    'is_completed': progress.is_completed,
                    'progress_percentage': progress.progress_percentage,
                    'quiz_score': progress.quiz_score,
                    'started_at': progress.started_at
                }
        return None
    
    def get_is_locked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.is_locked_for_user(request.user)
        return True


class LearningPathSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_level = ClassLevelSerializer(read_only=True)
    path_chapters = PathChapterSerializer(many=True, read_only=True)
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = LearningPath
        fields = [
            'id', 'subject', 'class_level', 'title', 'description',
            'estimated_hours', 'is_active', 'path_chapters',
            'total_chapters', 'total_videos', 'total_quiz_questions',
            'user_progress'
        ]
    
    def get_user_progress(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress = UserLearningPathProgress.objects.filter(
                user=request.user,
                learning_path=obj
            ).first()
            if progress:
                return {
                    'started_at': progress.started_at,
                    'progress_percentage': progress.progress_percentage,
                    'completed_chapters': progress.completed_chapters_count,
                    'current_streak': progress.current_streak,
                    'level': progress.level,
                    'experience_points': progress.experience_points
                }
        return None


class AchievementSerializer(serializers.ModelSerializer):
    is_earned = serializers.SerializerMethodField()
    
    class Meta:
        model = Achievement
        fields = [
            'id', 'name', 'description', 'icon',
            'achievement_type', 'points', 'is_earned'
        ]
    
    def get_is_earned(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAchievement.objects.filter(
                user=request.user,
                achievement=obj
            ).exists()
        return False


class UserLearningPathProgressSerializer(serializers.ModelSerializer):
    learning_path = LearningPathSerializer(read_only=True)
    achievements = serializers.SerializerMethodField()
    
    class Meta:
        model = UserLearningPathProgress
        fields = [
            'id', 'learning_path', 'started_at', 'last_activity',
            'current_streak', 'longest_streak', 'total_time_seconds',
            'experience_points', 'level', 'progress_percentage',
            'completed_chapters_count', 'achievements'
        ]
    
    def get_achievements(self, obj):
        achievements = UserAchievement.objects.filter(
            path_progress=obj
        ).select_related('achievement')
        return AchievementSerializer(
            [ua.achievement for ua in achievements],
            many=True,
            context=self.context
        ).data


class QuizSubmissionSerializer(serializers.Serializer):
    """Serializer for submitting quiz answers"""
    answers = serializers.ListField(
        child=serializers.DictField(
            child=serializers.IntegerField()
        )
    )
    
    def validate_answers(self, value):
        # Validate answer format
        for answer in value:
            if 'question_id' not in answer or 'answer_index' not in answer:
                raise serializers.ValidationError(
                    "Each answer must have 'question_id' and 'answer_index'"
                )
        return value


class VideoProgressUpdateSerializer(serializers.Serializer):
    """Serializer for updating video progress"""
    watched_seconds = serializers.IntegerField(min_value=0)
    is_completed = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class LearningPathStatsSerializer(serializers.Serializer):
    """Overall learning statistics for a user"""
    total_progress = serializers.IntegerField()
    current_streak = serializers.IntegerField()
    longest_streak = serializers.IntegerField()
    total_time_spent = serializers.IntegerField()
    completed_chapters = serializers.IntegerField()
    total_chapters = serializers.IntegerField()
    quiz_average = serializers.FloatField()
    level = serializers.IntegerField()
    experience = serializers.IntegerField()
    next_level_experience = serializers.IntegerField()
    recent_achievements = AchievementSerializer(many=True)