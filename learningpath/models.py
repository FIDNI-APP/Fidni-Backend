from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from caracteristics.models import Subject, ClassLevel, Chapter
from interactions.models import TimeSpentMixin

class LearningPath(models.Model):
    """Main learning path for a subject and class level"""
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learning_paths')
    class_level = models.ManyToManyField(ClassLevel, related_name='learning_paths')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    estimated_hours = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['subject__name', 'title']
    
    def __str__(self):
        return f"{self.title} - {self.subject.name}"
    
    @property
    def total_chapters(self):
        return self.path_chapters.count()
    
    @property
    def total_videos(self):
        return Video.objects.filter(path_chapter__learning_path=self).count()


class PathChapter(models.Model):
    """Chapter within a learning path containing videos and a quiz"""
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name='path_chapters')
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='path_chapters')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)  # Order within learning path
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['learning_path', 'chapter']
        ordering = ['learning_path', 'order']
    
    def __str__(self):
        return f"Chapter {self.order}: {self.title}"
    
    @property
    def total_videos(self):
        return self.videos.count()
    
    @property
    def total_duration_seconds(self):
        """Total duration of all videos in this chapter"""
        return self.videos.aggregate(
            total=models.Sum('duration_seconds')
        )['total'] or 0
    
    @property
    def total_duration_display(self):
        """Return total duration in format like '43m 16s' or '2h 19m 56s'"""
        total_seconds = self.total_duration_seconds
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        else:
            return f"{minutes}m {seconds}s"
    
    @property
    def has_quiz(self):
        return hasattr(self, 'quiz')


class Video(TimeSpentMixin, models.Model):
    """Video/lesson content within a chapter"""
    VIDEO_TYPES = [
        ('lesson', 'Lesson'),
        ('introduction', 'Introduction'),
        ('explanation', 'Explanation'),
        ('demo', 'Demo'),
        ('tips', 'Tips'),
        ('summary', 'Summary')
    ]
    
    path_chapter = models.ForeignKey(PathChapter, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=200)
    url = models.URLField(help_text="Video URL (YouTube, Vimeo, or direct link)")
    thumbnail_url = models.URLField(blank=True)
    video_type = models.CharField(max_length=20, choices=VIDEO_TYPES, default='lesson')
    duration_seconds = models.PositiveIntegerField(help_text="Duration in seconds")
    order = models.PositiveIntegerField(default=0)  # Order within chapter
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['path_chapter', 'order']
        ordering = ['path_chapter', 'order']
    
    def __str__(self):
        return f"{self.path_chapter.title} - {self.title}"
    
    @property
    def duration_display(self):
        """Return duration in format like '3m 12s'"""
        minutes = self.duration_seconds // 60
        seconds = self.duration_seconds % 60
        return f"{minutes}m {seconds}s"


class VideoResource(models.Model):
    """Additional resources attached to videos"""
    RESOURCE_TYPES = [
        ('pdf', 'PDF Document'),
        ('link', 'External Link'),
        ('exercise', 'Practice Exercise'),
        ('summary', 'Summary Document'),
        ('code', 'Code Sample'),
        ('slides', 'Presentation Slides')
    ]
    
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=200)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    url = models.URLField()
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.video.title} - {self.title}"


class ChapterQuiz(models.Model):
    """Quiz at the end of each chapter"""
    path_chapter = models.OneToOneField(PathChapter, on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=200)  # e.g., "Check Your Readiness for the CSA-A"
    description = models.TextField(blank=True)
    estimated_minutes = models.PositiveIntegerField(default=15)  # Estimated time to complete
    passing_score = models.PositiveIntegerField(default=70, validators=[MinValueValidator(0), MaxValueValidator(100)])
    time_limit_minutes = models.PositiveIntegerField(null=True, blank=True)
    shuffle_questions = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Quiz: {self.title}"
    
    @property
    def estimated_duration_display(self):
        """Return estimated duration like '30m' or '15m'"""
        return f"{self.estimated_minutes}m"


class QuizQuestion(models.Model):
    """Individual quiz question"""
    DIFFICULTY_LEVELS = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard')
    ]
    
    QUESTION_TYPES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True/False'),
        ('multiple_select', 'Multiple Select')
    ]
    
    quiz = models.ForeignKey(ChapterQuiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='multiple_choice')
    options = models.JSONField(help_text="List of answer options")
    correct_answer_index = models.PositiveIntegerField()  # For single correct answer
    correct_answer_indices = models.JSONField(null=True, blank=True, help_text="For multiple correct answers")
    explanation = models.TextField(help_text="Explanation shown after answering")
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_LEVELS, default='medium')
    points = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['quiz', 'order']
        ordering = ['quiz', 'order']
    
    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}..."


# User Progress Models
class UserLearningPathProgress(models.Model):
    """Track user's overall progress in a learning path"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_path_progress')
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name='user_progress')
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    total_time_seconds = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['user', 'learning_path']
    
    @property
    def progress_percentage(self):
        total_chapters = self.learning_path.path_chapters.count()
        if total_chapters == 0:
            return 0
        completed_chapters = self.chapter_progress.filter(is_completed=True).count()
        return int((completed_chapters / total_chapters) * 100)


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
    quiz_passed = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['user', 'path_chapter']
    
    @property
    def progress_percentage(self):
        total_videos = self.path_chapter.videos.filter(is_required=True).count()
        if total_videos == 0:
            return 100 if self.is_completed else 0
        
        completed_videos = self.video_progress.filter(
            video__is_required=True, 
            is_completed=True
        ).count()
        
        # Videos make up 80% of progress, quiz makes up 20%
        video_progress = (completed_videos / total_videos) * 80
        
        quiz_progress = 0
        if hasattr(self.path_chapter, 'quiz'):
            if self.quiz_passed:
                quiz_progress = 20
        else:
            quiz_progress = 20  # No quiz means full quiz points
        
        return int(video_progress + quiz_progress)


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
    selected_answer_index = models.PositiveIntegerField(null=True, blank=True)  # For single choice
    selected_answer_indices = models.JSONField(null=True, blank=True)  # For multiple choice
    is_correct = models.BooleanField()
    answered_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['attempt', 'question']