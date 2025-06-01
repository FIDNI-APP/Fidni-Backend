import os
import sys
import django
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from unittest.mock import patch

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
django.setup()

from interactions.models import (
    Vote, VotableMixin, Save, SaveableMixin, Complete, CompleteableMixin,
    Report, Evaluate, TimeSession, TimeSpent, TimeSpentMixin
)
from things.models import Exercise


class VoteModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_vote_creation(self):
        """Test creating a vote"""
        vote = Vote.objects.create(
            user=self.user,
            value=Vote.UP,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        self.assertEqual(vote.user, self.user)
        self.assertEqual(vote.value, Vote.UP)
        self.assertEqual(vote.content_object, self.exercise)

    def test_vote_choices(self):
        """Test vote choice values"""
        self.assertEqual(Vote.UP, 1)
        self.assertEqual(Vote.DOWN, -1)
        self.assertEqual(Vote.UNVOTE, 0)

    def test_unique_vote_constraint(self):
        """Test that a user can only vote once per object"""
        Vote.objects.create(
            user=self.user,
            value=Vote.UP,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        # This should raise an IntegrityError due to unique_together constraint
        with self.assertRaises(Exception):
            Vote.objects.create(
                user=self.user,
                value=Vote.DOWN,
                content_type=self.content_type,
                object_id=self.exercise.id
            )

    def test_vote_count_property(self):
        """Test vote count calculation"""
        user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123'
        )
        
        # Create upvote
        Vote.objects.create(
            user=self.user,
            value=Vote.UP,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        # Create downvote
        Vote.objects.create(
            user=user2,
            value=Vote.DOWN,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        self.assertEqual(self.exercise.vote_count, 0)  # 1 up - 1 down = 0


class SaveModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_save_creation(self):
        """Test creating a save"""
        save = Save.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        self.assertEqual(save.user, self.user)
        self.assertEqual(save.content_object, self.exercise)
        self.assertTrue(save.saved_at)

    def test_unique_save_constraint(self):
        """Test that a user can only save an object once"""
        Save.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        # This should raise an IntegrityError due to unique_together constraint
        with self.assertRaises(Exception):
            Save.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.exercise.id
            )

    def test_save_str_method(self):
        """Test the string representation of Save"""
        save = Save.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        expected_str = f"{self.user.username} saved {self.exercise.title}"
        self.assertEqual(str(save), expected_str)


class CompleteModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_complete_creation(self):
        """Test creating a completion record"""
        complete = Complete.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            status='success'
        )
        self.assertEqual(complete.user, self.user)
        self.assertEqual(complete.content_object, self.exercise)
        self.assertEqual(complete.status, 'success')

    def test_complete_status_choices(self):
        """Test completion status choices"""
        valid_statuses = ['success', 'review']
        for status in valid_statuses:
            complete = Complete.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.exercise.id,
                status=status
            )
            self.assertEqual(complete.status, status)
            complete.delete()  # Clean up for next iteration

    def test_complete_str_method(self):
        """Test the string representation of Complete"""
        complete = Complete.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            status='success'
        )
        expected_str = f"{self.user.username} - {self.exercise.title}: Success"
        self.assertEqual(str(complete), expected_str)


class TimeSessionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_time_session_creation(self):
        """Test creating a time session"""
        start_time = timezone.now() - timedelta(minutes=30)
        end_time = timezone.now()
        duration = end_time - start_time
        
        session = TimeSession.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            session_duration=duration,
            started_at=start_time,
            ended_at=end_time,
            session_type='study',
            notes='Test session'
        )
        
        self.assertEqual(session.user, self.user)
        self.assertEqual(session.content_object, self.exercise)
        self.assertEqual(session.session_duration, duration)
        self.assertEqual(session.session_type, 'study')
        self.assertEqual(session.notes, 'Test session')

    def test_session_duration_in_seconds_property(self):
        """Test session duration in seconds property"""
        duration = timedelta(minutes=5, seconds=30)  # 330 seconds
        session = TimeSession.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            session_duration=duration,
            started_at=timezone.now() - duration,
            ended_at=timezone.now()
        )
        
        self.assertEqual(session.session_duration_in_seconds, 330)

    def test_session_type_choices(self):
        """Test session type choices"""
        valid_types = ['study', 'review', 'practice', 'exam']
        for session_type in valid_types:
            session = TimeSession.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.exercise.id,
                session_duration=timedelta(minutes=10),
                started_at=timezone.now() - timedelta(minutes=10),
                ended_at=timezone.now(),
                session_type=session_type
            )
            self.assertEqual(session.session_type, session_type)
            session.delete()  # Clean up for next iteration


class TimeSpentModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_time_spent_creation(self):
        """Test creating a time spent record"""
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        self.assertEqual(time_spent.user, self.user)
        self.assertEqual(time_spent.content_object, self.exercise)
        self.assertEqual(time_spent.total_time, timedelta(0))
        self.assertEqual(time_spent.current_session_time, timedelta(0))

    def test_total_time_in_seconds_property(self):
        """Test total time in seconds property"""
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            total_time=timedelta(minutes=10, seconds=30)  # 630 seconds
        )
        
        self.assertEqual(time_spent.total_time_in_seconds, 630)

    def test_current_session_in_seconds_property(self):
        """Test current session in seconds property"""
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            current_session_time=timedelta(minutes=5)  # 300 seconds
        )
        
        self.assertEqual(time_spent.current_session_in_seconds, 300)

    def test_update_session_time(self):
        """Test updating session time"""
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        time_spent.update_session_time(600)  # 10 minutes
        time_spent.refresh_from_db()
        
        self.assertEqual(time_spent.current_session_in_seconds, 600)

    @patch('django.utils.timezone.now')
    def test_save_and_reset_session(self, mock_now):
        """Test saving and resetting session"""
        mock_time = timezone.now()
        mock_now.return_value = mock_time
        
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            current_session_time=timedelta(minutes=10),
            last_session_start=mock_time - timedelta(minutes=10)
        )
        
        initial_total = time_spent.total_time
        session_time = time_spent.current_session_time
        
        result = time_spent.save_and_reset_session('study', 'Test notes')
        time_spent.refresh_from_db()
        
        self.assertTrue(result)
        self.assertEqual(time_spent.total_time, initial_total + session_time)
        self.assertEqual(time_spent.current_session_time, timedelta(0))
        self.assertIsNone(time_spent.last_session_start)
        
        # Check that a TimeSession was created
        session = TimeSession.objects.filter(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        ).first()
        
        self.assertIsNotNone(session)
        self.assertEqual(session.session_duration, session_time)
        self.assertEqual(session.session_type, 'study')
        self.assertEqual(session.notes, 'Test notes')

    def test_save_and_reset_session_no_time(self):
        """Test saving and resetting session with no current time"""
        time_spent = TimeSpent.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        result = time_spent.save_and_reset_session()
        
        self.assertFalse(result)
        self.assertEqual(TimeSession.objects.count(), 0)


class EvaluateModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_evaluate_creation(self):
        """Test creating an evaluation"""
        evaluate = Evaluate.objects.create(
            user=self.user,
            rating=4,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        
        self.assertEqual(evaluate.user, self.user)
        self.assertEqual(evaluate.rating, 4)
        self.assertEqual(evaluate.content_object, self.exercise)

    def test_evaluate_rating_range(self):
        """Test evaluation rating range (1-5)"""
        for rating in range(1, 6):
            evaluate = Evaluate.objects.create(
                user=self.user,
                rating=rating,
                content_type=self.content_type,
                object_id=self.exercise.id
            )
            self.assertEqual(evaluate.rating, rating)
            evaluate.delete()  # Clean up for next iteration

    def test_evaluate_str_method(self):
        """Test the string representation of Evaluate"""
        evaluate = Evaluate.objects.create(
            user=self.user,
            rating=5,
            content_type=self.content_type,
            object_id=self.exercise.id
        )
        expected_str = f"{self.user.username} rated {self.exercise.title} as 5/5"
        self.assertEqual(str(evaluate), expected_str)


class ReportModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.content_type = ContentType.objects.get_for_model(Exercise)

    def test_report_creation(self):
        """Test creating a report"""
        report = Report.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            reason='Inappropriate content'
        )
        
        self.assertEqual(report.user, self.user)
        self.assertEqual(report.content_object, self.exercise)
        self.assertEqual(report.reason, 'Inappropriate content')
        self.assertTrue(report.created_at)

    def test_report_str_method(self):
        """Test the string representation of Report"""
        report = Report.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.exercise.id,
            reason='Test reason'
        )
        expected_str = f"Report by {self.user.username} on {self.exercise}"
        self.assertEqual(str(report), expected_str)