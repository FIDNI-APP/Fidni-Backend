# learningpath/serializers.py

from rest_framework import serializers
from .models import (
    LearningPath, PathChapter, Video, VideoResource,
    ChapterQuiz, QuizQuestion,
    UserLearningPathProgress, UserChapterProgress,
    UserVideoProgress, QuizAttempt,
)
from caracteristics.models import Subject, ClassLevel, Chapter
from caracteristics.serializers import SubjectSerializer, ClassLevelSerializer, ChapterSerializer


class VideoResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoResource
        fields = ['id', 'title', 'resource_type', 'url']
        read_only_fields = ['id']


class VideoSerializer(serializers.ModelSerializer):
    resources = VideoResourceSerializer(many=True, read_only=True)
    duration = serializers.CharField(source='duration_display', read_only=True)
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = Video
        fields = [
            'id', 'path_chapter', 'title', 'description', 'url', 'thumbnail_url',
            'video_type', 'duration_seconds', 'duration',
            'resources', 'user_progress', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'duration']
        extra_kwargs = {
            'path_chapter': {'required': True},
            'duration_seconds': {'required': True},
        }
    
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
            'id', 'quiz', 'question_text', 'options', 'correct_answer_index',
            'explanation', 'difficulty', 'points',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'quiz': {'required': False, 'read_only': True}
        }
    
    def validate_options(self, value):
        """Ensure options is a list with at least 2 items"""
        if not isinstance(value, list) or len(value) < 2:
            raise serializers.ValidationError("At least 2 options are required")
        return value
    
    def validate_correct_answer_index(self, value):
        """Ensure correct answer index is valid"""
        if value < 0:
            raise serializers.ValidationError("Correct answer index must be non-negative")
        return value
    
    def validate(self, attrs):
        """Ensure correct answer index is within options range"""
        options = attrs.get('options', [])
        correct_index = attrs.get('correct_answer_index', 0)
        
        if correct_index >= len(options):
            raise serializers.ValidationError({
                'correct_answer_index': 'Index must be less than the number of options'
            })
        
        return attrs


class ChapterQuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    user_attempts = serializers.SerializerMethodField()
    questions_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChapterQuiz
        fields = [
            'id', 'path_chapter', 'title', 'description', 'passing_score',
            'time_limit_minutes', 'shuffle_questions',
            'show_correct_answers', 'questions', 'questions_count', 
            'user_attempts', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'path_chapter': {'required': True}
        }
    
    def get_questions_count(self, obj):
        return obj.questions.count()
    
    def get_user_attempts(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            attempts = QuizAttempt.objects.filter(
                user=request.user,
                quiz=obj
            ).order_by('-started_at')[:5]
            
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
    chapter_id = serializers.PrimaryKeyRelatedField(
        queryset=Chapter.objects.all(),
        source='chapter',
        write_only=True
    )
    videos = VideoSerializer(many=True, read_only=True)
    quiz = ChapterQuizSerializer(read_only=True)
    user_progress = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    estimated_time = serializers.CharField(source='estimated_minutes', read_only=True)
    
    class Meta:
        model = PathChapter
        fields = [
            'id', 'learning_path', 'chapter', 'chapter_id', 'title', 
            'description', 'estimated_time', 'estimated_minutes', 'is_milestone', 
            'videos', 'quiz', 'user_progress', 'is_locked', 'total_videos', 
            'total_quiz_questions',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'estimated_time']
        extra_kwargs = {
            'learning_path': {'required': True},
        }
    
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
    
    
    def create(self, validated_data):
        path_chapter = super().create(validated_data)
        return path_chapter
    
    def update(self, instance, validated_data):
        path_chapter = super().update(instance, validated_data)
        return path_chapter


class LearningPathSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(),
        source='subject',
        write_only=True
    )
    class_level = ClassLevelSerializer(read_only=True)
    class_level_id = serializers.PrimaryKeyRelatedField(
        queryset=ClassLevel.objects.all(),
        source='class_level',
        write_only=True
    )
    path_chapters = PathChapterSerializer(many=True, read_only=True)
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = LearningPath
        fields = [
            'id', 'subject', 'subject_id', 'class_level', 'class_level_id',
            'title', 'description', 'estimated_hours', 'is_active', 
            'path_chapters', 'total_chapters', 'total_videos', 
            'total_quiz_questions', 'user_progress',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
    
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
                }
        return None
    
    def validate(self, attrs):
        """Ensure subject and class level combination is unique"""
        subject = attrs.get('subject')
        class_level = attrs.get('class_level')
        
        if self.instance:
            # Update case - exclude current instance
            existing = LearningPath.objects.filter(
                subject=subject,
                class_level=class_level
            ).exclude(id=self.instance.id)
        else:
            # Create case
            existing = LearningPath.objects.filter(
                subject=subject,
                class_level=class_level
            )
        
        if existing.exists():
            raise serializers.ValidationError(
                "A learning path already exists for this subject and class level combination"
            )
        
        return attrs



class UserLearningPathProgressSerializer(serializers.ModelSerializer):
    learning_path = LearningPathSerializer(read_only=True)
    chapter_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = UserLearningPathProgress
        fields = [
            'id', 'learning_path', 'started_at', 'last_activity',
            'total_time_seconds',
            'experience_points', 'level', 'progress_percentage',
            'completed_chapters_count', 'chapter_progress'
        ]
        read_only_fields = fields
    
    def get_chapter_progress(self, obj):
        """Get progress for all chapters in this path"""
        progress = UserChapterProgress.objects.filter(
            path_progress=obj
        ).select_related('path_chapter')
        
        return [{
            'chapter_id': str(cp.path_chapter.id),
            'is_completed': cp.is_completed,
            'progress_percentage': cp.progress_percentage,
            'quiz_score': cp.quiz_score,
            'started_at': cp.started_at,
            'completed_at': cp.completed_at
        } for cp in progress]


class QuizSubmissionSerializer(serializers.Serializer):
    """Serializer for submitting quiz answers"""
    answers = serializers.ListField(
        child=serializers.DictField(),
        required=True
    )
    
    def validate_answers(self, value):
        # Validate answer format
        for answer in value:
            if 'question_id' not in answer or 'answer_index' not in answer:
                raise serializers.ValidationError(
                    "Each answer must have 'question_id' and 'answer_index'"
                )
            
            if not isinstance(answer['answer_index'], int) or answer['answer_index'] < 0:
                raise serializers.ValidationError(
                    "answer_index must be a non-negative integer"
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
    total_time_spent = serializers.IntegerField()
    completed_chapters = serializers.IntegerField()
    total_chapters = serializers.IntegerField()
    quiz_average = serializers.FloatField()

