from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, MaxValueValidator
from caracteristics.models import Subject, ClassLevel, Chapter
from interactions.models import CompleteableMixin, TimeSpentMixin
import json
import uuid

class LearningPath(models.Model):
    """Main learning path for a subject and class level"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learning_paths')
    class_level = models.ForeignKey(ClassLevel, on_delete=models.CASCADE, related_name='learning_paths')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    estimated_hours = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_paths')
    
    class Meta:
        unique_together = ['subject', 'class_level']
        ordering = ['subject__name', 'class_level__order']
    
    def __str__(self):
        return f"{self.subject.name} - {self.class_level.name}"
    
    @property
    def total_chapters(self):
        return self.path_chapters.count()
    
    @property
    def total_videos(self):
        return Video.objects.filter(path_chapter__learning_path=self).count()
    
    @property
    def total_quiz_questions(self):
        return QuizQuestion.objects.filter(quiz__path_chapter__learning_path=self).count()


class PathChapter(models.Model):
    """Chapter within a learning path with order and prerequisites"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name='path_chapters')
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='path_chapters')
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)  # Override chapter title if needed
    description = models.TextField(blank=True)
    estimated_minutes = models.PositiveIntegerField(default=120)
    prerequisites = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='unlocks')
    is_milestone = models.BooleanField(default=False)  # For special badges/achievements
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['learning_path', 'chapter']
        ordering = ['order']
    
    def __str__(self):
        return f"{self.learning_path.subject.name} - Chapter {self.order}: {self.title}"
    
    @property
    def is_locked_for_user(self, user):
        """Check if chapter is locked based on prerequisites"""
        if not self.prerequisites.exists():
            return False
        
        for prereq in self.prerequisites.all():
            progress = UserChapterProgress.objects.filter(
                user=user,
                path_chapter=prereq
            ).first()
            if not progress or not progress.is_completed:
                return True
        return False
    
    @property
    def total_videos(self):
        return self.videos.count()
    
    @property
    def total_quiz_questions(self):
        return self.quiz.questions.count() if hasattr(self, 'quiz') else 0


class Video(TimeSpentMixin, models.Model):
    """Video content within a chapter"""
    VIDEO_TYPES = [
        ('lesson', 'Lesson'),
        ('summary', 'Summary'),
        ('exercise', 'Exercise Walkthrough'),
        ('bonus', 'Bonus Content')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path_chapter = models.ForeignKey(PathChapter, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    url = models.URLField(help_text="Video URL (YouTube, Vimeo, or direct link)")
    thumbnail_url = models.URLField(blank=True)
    video_type = models.CharField(max_length=20, choices=VIDEO_TYPES, default='lesson')
    duration_seconds = models.PositiveIntegerField(help_text="Duration in seconds")
    order = models.PositiveIntegerField(default=0)
    transcript = models.TextField(blank=True, help_text="Video transcript for accessibility")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'created_at']
    
    def __str__(self):
        return f"{self.path_chapter.title} - {self.title}"
    
    @property
    def duration_display(self):
        """Return duration in format like '15m' or '1h 30m'"""
        minutes = self.duration_seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"


class VideoResource(models.Model):
    """Additional resources attached to videos"""
    RESOURCE_TYPES = [
        ('pdf', 'PDF Document'),
        ('link', 'External Link'),
        ('exercise', 'Practice Exercise'),
        ('code', 'Code Sample')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=200)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    url = models.URLField()
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
    
    def __str__(self):
        return f"{self.video.title} - {self.title}"


class ChapterQuiz(models.Model):
    """Quiz for a chapter"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path_chapter = models.OneToOneField(PathChapter, on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=200, default="Quiz du chapitre")
    description = models.TextField(blank=True)
    passing_score = models.PositiveIntegerField(default=70, validators=[MinValueValidator(0), MaxValueValidator(100)])
    time_limit_minutes = models.PositiveIntegerField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(default=3)
    shuffle_questions = models.BooleanField(default=True)
    show_correct_answers = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Quiz - {self.path_chapter.title}"


class QuizQuestion(models.Model):
    """Individual quiz question"""
    DIFFICULTY_LEVELS = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(ChapterQuiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    options = models.JSONField(help_text="List of answer options")  # Store as ["Option 1", "Option 2", ...]
    correct_answer_index = models.PositiveIntegerField()
    explanation = models.TextField(help_text="Explanation shown after answering")
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_LEVELS, default='medium')
    points = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
    
    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}..."
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.options and self.correct_answer_index >= len(self.options):
            raise ValidationError("Correct answer index is out of range")


class Achievement(models.Model):
    """Achievements/Badges that can be earned"""
    ACHIEVEMENT_TYPES = [
        ('chapter_complete', 'Chapter Completion'),
        ('quiz_perfect', 'Perfect Quiz Score'),
        ('streak', 'Study Streak'),
        ('milestone', 'Milestone'),
        ('speed', 'Speed Achievement'),
        ('dedication', 'Dedication')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, default='trophy')  # Icon name for frontend
    achievement_type = models.CharField(max_length=20, choices=ACHIEVEMENT_TYPES)
    points = models.PositiveIntegerField(default=10)
    
    # Criteria
    required_value = models.PositiveIntegerField(default=1)  # e.g., 7 for 7-day streak
    related_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, null=True, blank=True)
    related_chapter = models.ForeignKey(PathChapter, on_delete=models.CASCADE, null=True, blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


# User Progress Models
class UserLearningPathProgress(models.Model):
    """Track user's overall progress in a learning path"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_path_progress')
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name='user_progress')
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    total_time_seconds = models.PositiveIntegerField(default=0)
    experience_points = models.PositiveIntegerField(default=0)
    level = models.PositiveIntegerField(default=1)
    
    class Meta:
        unique_together = ['user', 'learning_path']
    
    @property
    def progress_percentage(self):
        total_chapters = self.learning_path.path_chapters.count()
        if total_chapters == 0:
            return 0
        completed_chapters = self.chapter_progress.filter(is_completed=True).count()
        return int((completed_chapters / total_chapters) * 100)
    
    @property
    def completed_chapters_count(self):
        return self.chapter_progress.filter(is_completed=True).count()
    
    def add_experience(self, points):
        """Add experience points and check for level up"""
        self.experience_points += points
        # Simple leveling: 100 XP per level with increasing requirement
        required_xp = self.level * 100
        if self.experience_points >= required_xp:
            self.level += 1
            self.experience_points -= required_xp
        self.save()


class UserChapterProgress(models.Model):
    """Track user's progress in a specific chapter"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chapter_progress')
    path_chapter = models.ForeignKey(PathChapter, on_delete=models.CASCADE, related_name='user_progress')
    path_progress = models.ForeignKey(UserLearningPathProgress, on_delete=models.CASCADE, related_name='chapter_progress')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    quiz_score = models.PositiveIntegerField(null=True, blank=True)
    quiz_attempts = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['user', 'path_chapter']
    
    @property
    def progress_percentage(self):
        total_videos = self.path_chapter.videos.count()
        if total_videos == 0:
            return 100 if self.is_completed else 0
        completed_videos = self.video_progress.filter(is_completed=True).count()
        
        # Include quiz in progress calculation
        has_quiz = hasattr(self.path_chapter, 'quiz')
        if has_quiz:
            quiz_weight = 20  # Quiz is worth 20% of chapter
            video_weight = 80
            video_progress = (completed_videos / total_videos) * video_weight
            quiz_progress = quiz_weight if self.quiz_score and self.quiz_score >= self.path_chapter.quiz.passing_score else 0
            return int(video_progress + quiz_progress)
        else:
            return int((completed_videos / total_videos) * 100)


class UserVideoProgress(models.Model):
    """Track user's progress on individual videos"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_progress')
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='user_progress')
    chapter_progress = models.ForeignKey(UserChapterProgress, on_delete=models.CASCADE, related_name='video_progress')
    watched_seconds = models.PositiveIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['user', 'video']
    
    @property
    def progress_percentage(self):
        if self.video.duration_seconds == 0:
            return 100 if self.is_completed else 0
        return min(100, int((self.watched_seconds / self.video.duration_seconds) * 100))


class QuizAttempt(models.Model):
    """Record of a quiz attempt"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_attempts')
    quiz = models.ForeignKey(ChapterQuiz, on_delete=models.CASCADE, related_name='attempts')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-started_at']
    
    @property
    def percentage_score(self):
        total_points = self.quiz.questions.aggregate(total=models.Sum('points'))['total'] or 0
        if total_points == 0:
            return 0
        return int((self.score / total_points) * 100)


class QuizAnswer(models.Model):
    """Individual answer in a quiz attempt"""
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='user_answers')
    selected_answer_index = models.PositiveIntegerField()
    is_correct = models.BooleanField()
    answered_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['attempt', 'question']


class UserAchievement(models.Model):
    """Track which achievements users have earned"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earned_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='user_achievements')
    path_progress = models.ForeignKey(UserLearningPathProgress, on_delete=models.CASCADE, related_name='achievements')
    earned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'achievement']
        ordering = ['-earned_at']


class LearningStreak(models.Model):
    """Track daily learning streaks"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_streaks')
    date = models.DateField()
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    minutes_studied = models.PositiveIntegerField(default=0)
    videos_watched = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['user', 'date', 'learning_path']
        ordering = ['-date']