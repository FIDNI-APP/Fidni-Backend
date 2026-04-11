from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from apps.caracteristics.models import Chapter, ClassLevel, Subject, Theorem, Subfield
from apps.interactions.models import VotableMixin, CompleteableMixin, SaveableMixin
import logging

logger = logging.getLogger('django')


# =====================
# STRUCTURED CONTENT MIXIN
# =====================

class StructuredContentMixin(models.Model):
    """
    Structure JSON (stored in MongoDB, this field is unused but kept for schema compat):
    {
        "version": "2.0",
        "blocks": [ ... ]
    }
    """
    structure = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True

    def get_all_item_paths(self) -> list:
        paths = []
        structure = self.structure or {}
        for block in structure.get('blocks', []):
            if block.get('type') == 'question':
                block_id = block.get('id', '')
                if block_id:
                    paths.append(block_id)
                    for sub in block.get('subQuestions', []):
                        sub_id = sub.get('id', '')
                        if sub_id:
                            sub_path = f"{block_id}.{sub_id}"
                            paths.append(sub_path)
                            for part in sub.get('parts', []):
                                part_id = part.get('id', '')
                                if part_id:
                                    paths.append(f"{sub_path}.{part_id}")
        return paths

    def get_total_points(self) -> int:
        total = 0
        structure = self.structure or {}
        for block in structure.get('blocks', []):
            if block.get('type') == 'question':
                block_points = block.get('points', 0) or 0
                sub_points = sum(
                    (sub.get('points', 0) or 0) + sum(
                        (part.get('points', 0) or 0) for part in sub.get('parts', [])
                    )
                    for sub in block.get('subQuestions', [])
                )
                total += sub_points if sub_points > 0 else block_points
        return total

    def get_item_count(self) -> int:
        return len(self.get_all_item_paths())

    def get_preview(self) -> str:
        structure = self.structure or {}
        for block in structure.get('blocks', []):
            if block.get('type') == 'context':
                html = block.get('content', {}).get('html', '')
                if html:
                    return html[:500]
            elif block.get('type') == 'question':
                html = block.get('content', {}).get('html', '')
                if html:
                    return html[:500]
        return ''


# =====================
# CONTENT
# =====================

class Content(StructuredContentMixin, CompleteableMixin, SaveableMixin, models.Model):
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

    @property
    def total_points(self):
        return self.get_total_points()

    @property
    def item_count(self):
        return self.get_item_count()

    @property
    def section_count(self):
        structure = self.structure or {}
        return len([b for b in structure.get('blocks', []) if b.get('type') == 'section'])

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
