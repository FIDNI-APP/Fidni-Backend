"""
Concours app — entrance exams (ENSA / ENSAM / Médecine) and tips/techniques.

Architecture mirrors `things`: relational metadata in PostgreSQL, the QCM
question structure stored as a JSON document in MongoDB (one document per
exam) for flexibility and parity with how exercises are stored.

Three top-level models:

    ConcoursExam        — one specific exam (concours_type + year + duration).
                          Saveable + commentable. NOT votable per spec.

    ConcoursTip         — a re-usable trick/technique attached to one or more
                          subjects/chapters. Has an explanatory video.
                          Votable + saveable + commentable per spec.

    SimulationSession   — one student's run of an exam (real exam, random
                          year, or random questions). Persisted with answers.

    SimulationAnswer    — per-question record inside a session.

QCM question structure (Mongo, one document per ConcoursExam):
{
    "version": "1.0",
    "questions": [
        {
            "id": "q1",
            "statement": "<rich HTML>",
            "options": [
                {"key": "A", "text": "<rich HTML>"},
                {"key": "B", "text": "<rich HTML>"},
                ...
            ],
            "correct_key": "B",
            "explanation": "<rich HTML — why B is correct>",
            "subject_id": <int|null>,
            "subfield_id": <int|null>,
            "chapter_id": <int|null>,
            "tip_id": <int|null>,
            "points": <int, default 1>
        }
    ]
}
"""

import uuid

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from apps.interactions.models import SaveableMixin, VotableMixin


# --------------------------------------------------------------------------
# Concours type
# --------------------------------------------------------------------------

CONCOURS_TYPE_CHOICES = [
    ('ensa', 'ENSA'),
    ('ensam', 'ENSAM'),
    ('medecine', 'Médecine'),
]


# --------------------------------------------------------------------------
# ConcoursExam
# --------------------------------------------------------------------------

class ConcoursExam(SaveableMixin, models.Model):
    """A specific concours exam (e.g. ENSA 2023). Question content lives in Mongo."""

    concours_type = models.CharField(max_length=10, choices=CONCOURS_TYPE_CHOICES, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    title = models.CharField(max_length=200, blank=True,
                             help_text="Optional title — auto-generated if empty (e.g. 'ENSA 2023').")
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=180)

    # Auto-incremented per-type display id (1, 2, 3, ...) — used as the public
    # URL slug and the Mongo lookup key. Same idea as Content.display_id.
    display_id = models.PositiveIntegerField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='concours_exams')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Comments (re-uses the things.Comment model via a generic relation? No —
    # things.Comment has a hard FK to Content. We define our own Comment below.)

    class Meta:
        app_label = 'concours'
        ordering = ['-year', 'concours_type']
        constraints = [
            models.UniqueConstraint(fields=['concours_type', 'year'],
                                    name='unique_concours_exam_year'),
        ]
        indexes = [
            models.Index(fields=['concours_type', 'year']),
        ]

    def __str__(self):
        return self.display_title

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        return f"{self.get_concours_type_display()} {self.year}"

    def save(self, *args, **kwargs):
        if self.display_id is None:
            max_id = ConcoursExam.objects.filter(
                concours_type=self.concours_type
            ).aggregate(m=models.Max('display_id'))['m']
            self.display_id = (max_id or 0) + 1
        super().save(*args, **kwargs)

    # JSON structure helpers ------------------------------------------------

    def get_structure(self) -> dict:
        from .content_store import get_concours_structure
        return get_concours_structure(self.concours_type, self.display_id)

    def set_structure(self, structure: dict) -> None:
        from .content_store import set_concours_structure
        set_concours_structure(self.concours_type, self.display_id, structure)

    @property
    def question_count(self) -> int:
        s = self.get_structure()
        return len(s.get('questions', []))


# --------------------------------------------------------------------------
# ConcoursTip — admin-managed tips/techniques (with video).
# --------------------------------------------------------------------------

class ConcoursTip(SaveableMixin, VotableMixin, models.Model):
    """A re-usable technique (e.g. 'Théorème de l'Hôpital') with a video lesson."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text="Markdown / rich text")

    # Filtering metadata
    concours_types = models.JSONField(default=list, blank=True,
                                      help_text="List of concours type keys this tip applies to")
    subject = models.ForeignKey(
        'caracteristics.Subject', on_delete=models.PROTECT,
        related_name='concours_tips', null=True, blank=True,
    )
    subfield = models.ForeignKey(
        'caracteristics.Subfield', on_delete=models.SET_NULL,
        related_name='concours_tips', null=True, blank=True,
    )
    chapters = models.ManyToManyField(
        'caracteristics.Chapter', related_name='concours_tips', blank=True,
    )

    # Video — either an external URL OR an uploaded file (or both).
    video_url = models.URLField(blank=True, help_text="External video URL (YouTube, Vimeo, ...)")
    video_file = models.ForeignKey(
        'uploads.FileAttachment', on_delete=models.SET_NULL,
        related_name='concours_tip_videos', null=True, blank=True,
    )

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='concours_tips')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = 'concours'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['subject']),
            models.Index(fields=['subfield']),
        ]

    def __str__(self):
        return self.title


# --------------------------------------------------------------------------
# ConcoursExamStats — admin-curated statistics for one exam.
# --------------------------------------------------------------------------

class ConcoursExamStats(models.Model):
    """
    Manually-curated stats panel for one ConcoursExam.

    The per-chapter/domain *distribution* is computed automatically from the
    exam's tagged questions (not stored here). This model only holds the
    admin-authored comparison content:

        comparison_html  — free rich-text block (CompactTipTapEditor output).
        insight_cards    — list of {title, text} cards shown as a grid.
    """

    exam = models.OneToOneField(
        ConcoursExam, on_delete=models.CASCADE, related_name='stats',
    )
    comparison_html = models.TextField(blank=True)
    # [{"title": str, "text": str}, ...]
    insight_cards = models.JSONField(default=list, blank=True)

    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='concours_exam_stats_edits',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'concours'

    def __str__(self):
        return f"Stats for {self.exam_id}"


# --------------------------------------------------------------------------
# Comments — separate model per spec (concours-only, with reply threading).
# --------------------------------------------------------------------------

class ConcoursComment(VotableMixin, models.Model):
    """Comment on a ConcoursExam or a ConcoursTip."""

    TARGET_EXAM = 'exam'
    TARGET_TIP = 'tip'
    TARGET_CHOICES = [
        (TARGET_EXAM, 'Exam'),
        (TARGET_TIP, 'Tip'),
    ]

    target_type = models.CharField(max_length=4, choices=TARGET_CHOICES, db_index=True)
    target_id = models.PositiveIntegerField(db_index=True)

    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='concours_comments')
    content = models.TextField()
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'concours'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on {self.target_type}#{self.target_id}"


# --------------------------------------------------------------------------
# SimulationSession + SimulationAnswer
# --------------------------------------------------------------------------

class SimulationSession(models.Model):
    """A timed run by a student. Three modes: real exam / random year / random mix."""

    MODE_EXAM = 'exam'
    MODE_RANDOM_YEAR = 'random_year'
    MODE_RANDOM_MIX = 'random_mix'
    MODE_CHOICES = [
        (MODE_EXAM, 'Specific exam'),
        (MODE_RANDOM_YEAR, 'Random year'),
        (MODE_RANDOM_MIX, 'Random questions'),
    ]

    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SUBMITTED = 'submitted'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='concours_sessions')

    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    concours_type = models.CharField(max_length=10, choices=CONCOURS_TYPE_CHOICES, db_index=True)
    exam = models.ForeignKey(
        ConcoursExam, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessions',
        help_text="Set for MODE_EXAM and MODE_RANDOM_YEAR (the picked year).",
    )

    duration_minutes = models.PositiveIntegerField(
        help_text="Total time allotted for this session"
    )

    # Frozen snapshot of the questions a student is being asked. Stored at
    # session creation so re-shuffling later doesn't change what they saw.
    # Shape: list of {exam_id, exam_display_id, question, position}
    # `question` is the raw question dict (statement/options/correct_key/...).
    questions_snapshot = models.JSONField(default=list)

    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS,
                              db_index=True)

    # Cached aggregate score (filled at submit). Per-domain breakdown is
    # computed from SimulationAnswer rows on demand.
    total_questions = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = 'concours'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['user', '-started_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.mode} ({self.status})"

    @property
    def score_percentage(self) -> float:
        if not self.total_questions:
            return 0.0
        return round(self.correct_count * 100 / self.total_questions, 1)


class SimulationAnswer(models.Model):
    """One question's answer inside a session."""

    session = models.ForeignKey(SimulationSession, on_delete=models.CASCADE,
                                related_name='answers')
    # Position in the session (0-based) — also indexes into questions_snapshot.
    position = models.PositiveIntegerField()

    chosen_key = models.CharField(max_length=8, blank=True,
                                  help_text="Empty string = unanswered")
    is_correct = models.BooleanField(default=False)

    # Denormalised metadata captured at submit so reports work even if a
    # question is later deleted/edited.
    subject_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    subfield_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    chapter_id = models.PositiveIntegerField(null=True, blank=True)
    tip_id = models.PositiveIntegerField(null=True, blank=True)

    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'concours'
        ordering = ['session', 'position']
        unique_together = ('session', 'position')
        indexes = [
            models.Index(fields=['session', 'position']),
            models.Index(fields=['session', 'is_correct']),
        ]

    def __str__(self):
        return f"{self.session_id}#{self.position} -> {self.chosen_key} ({'✓' if self.is_correct else '✗'})"
