from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from apps.interactions.models import VotableMixin, CompleteableMixin, SaveableMixin
import logging
from apps.caracteristics.models import Chapter, ClassLevel, Subject, Theorem, Subfield

logger = logging.getLogger('django')


# =====================
# CONTENT
# =====================

class Content(CompleteableMixin, SaveableMixin, models.Model):
    TYPE_EXERCISE = 'exercise'
    TYPE_LESSON = 'lesson'
    TYPE_EXAM = 'exam'
    TYPE_CHOICES = [
        (TYPE_EXERCISE, 'Exercise'),
        (TYPE_LESSON, 'Lesson'),
        (TYPE_EXAM, 'Exam'),
    ]
    DIFFICULTY_CHOICES = [
        ('easy', 'easy'),
        ('medium', 'medium'),
        ('hard', 'hard'),
    ]

    type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    display_id = models.PositiveIntegerField(null=True, blank=True)

    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, default='')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='content_items')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='content_items', null=True)
    chapters = models.ManyToManyField(Chapter, related_name='content_items', blank=True)
    class_levels = models.ManyToManyField(ClassLevel, related_name='content_items')
    theorems = models.ManyToManyField(Theorem, related_name='content_items', blank=True)
    subfields = models.ManyToManyField(Subfield, related_name='content_items', blank=True)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # exercise / exam only
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, null=True, blank=True)

    # exam only
    is_national_exam = models.BooleanField(default=False)
    national_year = models.PositiveIntegerField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'things_content'
        constraints = [
            models.UniqueConstraint(fields=['type', 'display_id'], name='unique_display_id_per_type')
        ]

    def __str__(self):
        return f"[{self.type}] {self.title}"

    def save(self, *args, **kwargs):
        if self.display_id is None:
            max_id = Content.objects.filter(type=self.type).aggregate(
                models.Max('display_id')
            )['display_id__max']
            self.display_id = (max_id or 0) + 1
        super().save(*args, **kwargs)

    def _get_structure(self) -> dict:
        from apps.things.content_store import get_structure
        return get_structure(self.type, self.display_id)

    @property
    def total_points(self) -> int:
        from apps.things.structure_utils import get_total_points
        return get_total_points(self._get_structure())

    @property
    def item_count(self) -> int:
        from apps.things.structure_utils import get_item_count
        return get_item_count(self._get_structure())

    @property
    def section_count(self) -> int:
        from apps.things.structure_utils import get_section_count
        return get_section_count(self._get_structure())

    @property
    def success_count(self):
        return self.progress.filter(status='success').count()

    @property
    def review_count(self):
        return self.progress.filter(status='review').count()

    @property
    def average_time_spent(self):
        if not self.time_spent.exists():
            return 0
        total_time = sum(t.time_spent for t in self.time_spent.all())
        count = self.time_spent.count()
        return total_time / count if count else 0

    @property
    def average_perceived_difficulty(self):
        ratings = self.difficulty_ratings.all()
        if not ratings:
            return None
        return sum(r.rating for r in ratings) / ratings.count()


# =====================
# SOLUTION
# =====================

class Solution(VotableMixin, models.Model):
    content_item = models.OneToOneField(Content, on_delete=models.CASCADE, related_name='solution')
    solution_text = models.TextField()
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='solutions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'things_solution'

    def __str__(self):
        return f"Solution for {self.content_item.title}"


# =====================
# COMMENT
# =====================

class Comment(VotableMixin, models.Model):
    content_item = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    attachments = GenericRelation('uploads.FileAttachment')

    class Meta:
        db_table = 'things_comment'

    def __str__(self):
        return f"Comment by {self.author.username} on {self.content_item}"
