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
        fields = ['id', 'title', 'resource_type', 'url', 'description']


class VideoCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating videos within PathChapter creation"""
    resources = VideoResourceSerializer(many=True, required=False)
    
    class Meta:
        model = Video
        fields = [
            'title', 'url', 'thumbnail_url', 'video_type', 
            'duration_seconds', 'order', 'resources'
        ]
        extra_kwargs = {
            'duration_seconds': {'required': True},
            'order': {'required': True}
        }
    
    def validate_order(self, value):
        if value < 0:
            raise serializers.ValidationError("Order must be non-negative")
        return value


class VideoSerializer(serializers.ModelSerializer):
    resources = VideoResourceSerializer(many=True, read_only=True)
    duration = serializers.CharField(source='duration_display', read_only=True)
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = Video
        fields = [
            'id', 'path_chapter', 'title', 'url', 'thumbnail_url',
            'video_type', 'duration_seconds', 'duration', 'order',
             'resources', 'user_progress', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'duration']
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


class QuizQuestionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating quiz questions within ChapterQuiz creation"""
    class Meta:
        model = QuizQuestion
        fields = [
            'question_text', 'question_type', 'options', 
            'correct_answer_index', 'correct_answer_indices',
            'explanation', 'difficulty', 'points', 'order'
        ]
        extra_kwargs = {
            'order': {'required': True}
        }
    
    def validate_options(self, value):
        if not isinstance(value, list) or len(value) < 2:
            raise serializers.ValidationError("At least 2 options are required")
        return value
    
    def validate_correct_answer_index(self, value):
        if value < 0:
            raise serializers.ValidationError("Correct answer index must be non-negative")
        return value
    
    def validate(self, attrs):
        options = attrs.get('options', [])
        correct_index = attrs.get('correct_answer_index', 0)
        question_type = attrs.get('question_type', 'multiple_choice')
        
        # Validate single choice questions
        if question_type in ['multiple_choice', 'true_false']:
            if correct_index >= len(options):
                raise serializers.ValidationError({
                    'correct_answer_index': 'Index must be less than the number of options'
                })
        
        # Validate multiple choice questions
        elif question_type == 'multiple_select':
            correct_indices = attrs.get('correct_answer_indices', [])
            if not correct_indices or not isinstance(correct_indices, list):
                raise serializers.ValidationError({
                    'correct_answer_indices': 'Multiple select questions require correct_answer_indices'
                })
            for idx in correct_indices:
                if idx >= len(options):
                    raise serializers.ValidationError({
                        'correct_answer_indices': 'All indices must be less than the number of options'
                    })
        
        return attrs


class QuizQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = [
            'id', 'quiz', 'question_text', 'question_type', 'options', 
            'correct_answer_index', 'correct_answer_indices',
            'explanation', 'difficulty', 'points', 'order'
        ]
        read_only_fields = ['id']


class ChapterQuizCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating quiz within PathChapter creation"""
    questions = QuizQuestionCreateSerializer(many=True, required=False)
    
    class Meta:
        model = ChapterQuiz
        fields = [
            'title', 'description', 'estimated_minutes', 'passing_score',
            'time_limit_minutes', 'shuffle_questions', 'questions'
        ]
    
    def validate_questions(self, value):
        """Ensure questions have unique orders"""
        orders = [q.get('order', 0) for q in value]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError("Question orders must be unique")
        return value


class ChapterQuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    user_attempts = serializers.SerializerMethodField()
    estimated_duration = serializers.CharField(source='estimated_duration_display', read_only=True)
    
    class Meta:
        model = ChapterQuiz
        fields = [
            'id', 'path_chapter', 'title', 'description', 'estimated_minutes',
            'estimated_duration', 'passing_score', 'time_limit_minutes', 
            'shuffle_questions', 'show_correct_answers', 'is_required',
            'questions', 'user_attempts', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'estimated_duration']
    
    def get_user_attempts(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            attempts = QuizAttempt.objects.filter(
                user=request.user,
                quiz=obj
            ).order_by('-started_at')[:5]
            
            return [{
                'id': attempt.id,
                'started_at': attempt.started_at,
                'score': attempt.percentage_score,
                'passed': attempt.passed,
                'time_spent_seconds': attempt.time_spent_seconds
            } for attempt in attempts]
        return []


class PathChapterCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating PathChapter with videos and quiz"""
    learning_path = serializers.PrimaryKeyRelatedField(
        queryset=LearningPath.objects.all(),
        required=True
    )
    chapter = serializers.PrimaryKeyRelatedField(
        queryset=Chapter.objects.all(),
        required=True
    )
    videos = VideoCreateSerializer(many=True, required=False)
    quiz = ChapterQuizCreateSerializer(required=False)
    
    class Meta:
        model = PathChapter
        fields = [
            'learning_path', 'chapter', 'title', 'description', 
            'order', 'videos', 'quiz'
        ]
        extra_kwargs = {
            'order': {'required': True}
        }
    
    def validate_videos(self, value):
        """Ensure videos have unique orders"""
        if value:
            orders = [v.get('order', 0) for v in value]
            if len(orders) != len(set(orders)):
                raise serializers.ValidationError("Video orders must be unique within the chapter")
        return value
    
    def validate(self, attrs):
        """Validate learning_path and chapter combination"""
        learning_path = attrs.get('learning_path')
        chapter = attrs.get('chapter')
        order = attrs.get('order', 0)
        
        # Check if this learning_path + chapter combination already exists
        if PathChapter.objects.filter(
            learning_path=learning_path, 
            chapter=chapter
        ).exists():
            raise serializers.ValidationError({
                'chapter': 'This chapter is already added to this learning path'
            })
        
        # Check if order is unique within the learning path
        if PathChapter.objects.filter(
            learning_path=learning_path,
            order=order
        ).exists():
            raise serializers.ValidationError({
                'order': 'This order is already taken in this learning path'
            })
        
        return attrs
    
    def create(self, validated_data):
        videos_data = validated_data.pop('videos', [])
        quiz_data = validated_data.pop('quiz', None)
        
        # Create the PathChapter
        path_chapter = PathChapter.objects.create(**validated_data)
        
        # Create videos
        for video_data in videos_data:
            resources_data = video_data.pop('resources', [])
            video = Video.objects.create(path_chapter=path_chapter, **video_data)
            
            # Create video resources
            for resource_data in resources_data:
                VideoResource.objects.create(video=video, **resource_data)
        
        # Create quiz if provided
        if quiz_data:
            questions_data = quiz_data.pop('questions', [])
            quiz = ChapterQuiz.objects.create(path_chapter=path_chapter, **quiz_data)
            
            # Create quiz questions
            for question_data in questions_data:
                QuizQuestion.objects.create(quiz=quiz, **question_data)
        
        return path_chapter


class PathChapterSerializer(serializers.ModelSerializer):
    learning_path = serializers.PrimaryKeyRelatedField(read_only=True)
    chapter = ChapterSerializer(read_only=True)
    videos = VideoSerializer(many=True, read_only=True)
    quiz = ChapterQuizSerializer(read_only=True)
    user_progress = serializers.SerializerMethodField()
    total_duration = serializers.CharField(source='total_duration_display', read_only=True)
    
    class Meta:
        model = PathChapter
        fields = [
            'id', 'learning_path', 'chapter', 'title', 'description', 
            'order', 'total_duration', 'videos', 'quiz', 'user_progress',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'total_duration']
    
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
                    'quiz_passed': progress.quiz_passed,
                    'started_at': progress.started_at
                }
        return None


class LearningPathSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_level = ClassLevelSerializer(many=True, read_only=True)
    path_chapters = PathChapterSerializer(many=True, read_only=True)
    user_progress = serializers.SerializerMethodField()

    class Meta:
        model = LearningPath
        fields = [
            'id', 'subject', 'class_level', 'title', 'description', 
            'estimated_hours', 'is_active', 'path_chapters', 'user_progress',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
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
                }
        return None


class LearningPathCreateSerializer(serializers.ModelSerializer):
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(),
        required=True
    )
    class_level = serializers.PrimaryKeyRelatedField(
        many=True, 
        queryset=ClassLevel.objects.all(), 
        required=True
    )

    class Meta:
        model = LearningPath
        fields = [
            'subject', 'class_level', 'title', 'description', 
            'estimated_hours', 'is_active'
        ]

    def create(self, validated_data):
        class_levels = validated_data.pop('class_level', [])
        learning_path = LearningPath.objects.create(**validated_data)
        if class_levels:
            learning_path.class_level.set(class_levels)
        return learning_path
    
    def update(self, instance, validated_data):
        class_levels = validated_data.pop('class_level', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if class_levels is not None:
            instance.class_level.set(class_levels)
        
        return instance


# Keep your existing progress and utility serializers
class UserLearningPathProgressSerializer(serializers.ModelSerializer):
    learning_path = LearningPathSerializer(read_only=True)
    chapter_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = UserLearningPathProgress
        fields = [
            'learning_path', 'started_at', 'last_activity', 'chapter_progress'
        ]
    
    def get_chapter_progress(self, obj):
        progress = UserChapterProgress.objects.filter(
            path_progress=obj
        ).select_related('path_chapter')
        
        return [{
            'chapter_id': cp.path_chapter.id,
            'is_completed': cp.is_completed,
            'progress_percentage': cp.progress_percentage,
            'quiz_score': cp.quiz_score,
            'started_at': cp.started_at,
            'completed_at': cp.completed_at
        } for cp in progress]


class QuizSubmissionSerializer(serializers.Serializer):
    answers = serializers.ListField(
        child=serializers.DictField(),
        required=True
    )
    
    def validate_answers(self, value):
        for answer in value:
            if 'question_id' not in answer:
                raise serializers.ValidationError(
                    "Each answer must have 'question_id'"
                )
            
            # Handle both single and multiple choice answers
            if 'answer_index' not in answer and 'answer_indices' not in answer:
                raise serializers.ValidationError(
                    "Each answer must have either 'answer_index' or 'answer_indices'"
                )
        
        return value


class VideoProgressUpdateSerializer(serializers.Serializer):
    watched_seconds = serializers.IntegerField(min_value=0)
    is_completed = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class LearningPathStatsSerializer(serializers.Serializer):
    total_progress = serializers.IntegerField()
    total_time_spent = serializers.IntegerField()
    completed_chapters = serializers.IntegerField()
    total_chapters = serializers.IntegerField()
    quiz_average = serializers.FloatField()