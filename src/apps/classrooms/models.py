"""
Classroom models.

A Classroom is created by one teacher (the owner). It contains:
- Many ClassroomSubject entries (subject + the teacher who teaches it in this classroom)
- Many ClassroomMembership entries (students who joined via the join_code)

Students join a classroom by entering its join_code on their profile.
"""
import secrets
import string

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


def _generate_join_code(length: int = 6) -> str:
    """Generate a random uppercase alphanumeric code (no ambiguous chars)."""
    alphabet = ''.join(c for c in (string.ascii_uppercase + string.digits) if c not in 'O0I1')
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class Classroom(models.Model):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    # The teacher who created the classroom (the admin / owner)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='owned_classrooms',
    )

    # Optional class level (e.g. "2ème Bac SM") for context
    class_level = models.ForeignKey(
        'caracteristics.ClassLevel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='classrooms',
    )

    # Code students enter to join
    join_code = models.CharField(max_length=12, unique=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'classrooms'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.join_code})"

    def save(self, *args, **kwargs):
        if not self.join_code:
            # Retry until unique
            for _ in range(10):
                code = _generate_join_code()
                if not Classroom.objects.filter(join_code=code).exists():
                    self.join_code = code
                    break
            else:
                # Extremely unlikely fallback
                self.join_code = _generate_join_code(8)
        super().save(*args, **kwargs)

    def regenerate_join_code(self):
        """Generate a new unique join code (invalidates the old one)."""
        for _ in range(10):
            code = _generate_join_code()
            if not Classroom.objects.filter(join_code=code).exclude(pk=self.pk).exists():
                self.join_code = code
                self.save(update_fields=['join_code', 'updated_at'])
                return code
        raise RuntimeError("Could not generate unique join code")


class ClassroomSubject(models.Model):
    """A subject taught inside a classroom by a specific teacher."""
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='subjects',
    )
    subject = models.ForeignKey(
        'caracteristics.Subject',
        on_delete=models.CASCADE,
        related_name='classroom_subjects',
    )
    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='taught_classroom_subjects',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'classrooms'
        unique_together = ('classroom', 'subject')
        ordering = ['subject__name']

    def __str__(self):
        return f"{self.subject} in {self.classroom} (taught by {self.teacher.username})"


class ClassroomMembership(models.Model):
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='classroom_memberships',
    )
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = 'classrooms'
        unique_together = ('classroom', 'student')
        ordering = ['-joined_at']
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['classroom']),
        ]

    def __str__(self):
        return f"{self.student.username} in {self.classroom}"


class TDList(models.Model):
    """A list of exercises a teacher assigns to a whole classroom (TD = Travaux Dirigés)."""
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='td_lists',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Optional: scope to a specific subject inside the classroom
    subject = models.ForeignKey(
        'caracteristics.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='td_lists',
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_td_lists',
    )

    due_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'classrooms'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['classroom']),
            models.Index(fields=['due_date']),
        ]

    def __str__(self):
        return f"TD: {self.title} ({self.classroom.name})"


class TDListItem(models.Model):
    """An exercise belonging to a TDList."""
    td_list = models.ForeignKey(
        TDList,
        on_delete=models.CASCADE,
        related_name='items',
    )
    # Generic FK is overkill — TDs are exercises only. Reference Content directly.
    content = models.ForeignKey(
        'things.Content',
        on_delete=models.CASCADE,
        related_name='td_items',
    )
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'classrooms'
        ordering = ['position', 'added_at']
        unique_together = ('td_list', 'content')

