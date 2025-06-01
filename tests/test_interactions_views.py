import os
import sys
import django
import json
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
django.setup()

from interactions.models import Vote, Save, Complete, TimeSpent, TimeSession, Evaluate
from things.models import Exercise
from interactions.views import VoteMixin


class VoteMixinTest(APITestCase):
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
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_vote_upvote_creation(self):
        """Test creating an upvote"""
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.UP}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], Vote.UP)
        self.assertEqual(response.data['vote_count'], 1)
        
        # Check that vote was created in database
        vote = Vote.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.value, Vote.UP)

    def test_vote_downvote_creation(self):
        """Test creating a downvote"""
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.DOWN}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], Vote.DOWN)
        self.assertEqual(response.data['vote_count'], -1)

    def test_vote_toggle_same_vote(self):
        """Test toggling the same vote (should delete it)"""
        # First, create an upvote
        Vote.objects.create(
            user=self.user,
            value=Vote.UP,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        )
        
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.UP}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], 0)  # Vote was deleted
        self.assertEqual(response.data['vote_count'], 0)
        
        # Check that vote was deleted from database
        vote_exists = Vote.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).exists()
        self.assertFalse(vote_exists)

    def test_vote_change_vote_type(self):
        """Test changing vote from up to down"""
        # First, create an upvote
        Vote.objects.create(
            user=self.user,
            value=Vote.UP,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        )
        
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.DOWN}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], Vote.DOWN)
        self.assertEqual(response.data['vote_count'], -1)
        
        # Check that vote was updated in database
        vote = Vote.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.value, Vote.DOWN)

    def test_vote_invalid_value(self):
        """Test voting with invalid value"""
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': 5}  # Invalid vote value
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_vote_invalid_value_type(self):
        """Test voting with invalid value type"""
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': 'invalid'}  # Invalid type
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_vote_unauthenticated(self):
        """Test voting without authentication"""
        self.client.credentials()  # Remove authentication
        
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.UP}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TimeTrackingAPITest(APITestCase):
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
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_get_time_spent_new_exercise(self):
        """Test getting time spent for a new exercise"""
        url = reverse('exercise-get-time-spent', kwargs={'pk': self.exercise.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_time'], 0)
        self.assertEqual(response.data['current_session_time'], 0)
        self.assertFalse(response.data['is_active'])

    def test_get_time_spent_existing_record(self):
        """Test getting time spent for existing record"""
        # Create existing time spent record
        TimeSpent.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id,
            total_time=timedelta(minutes=30),
            current_session_time=timedelta(minutes=10)
        )
        
        url = reverse('exercise-get-time-spent', kwargs={'pk': self.exercise.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_time'], 1800)  # 30 minutes in seconds
        self.assertEqual(response.data['current_session_time'], 600)  # 10 minutes in seconds

    def test_save_time_spent(self):
        """Test saving time spent"""
        url = reverse('exercise-save-time-spent', kwargs={'pk': self.exercise.pk})
        data = {'seconds': 300}  # 5 minutes
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Time updated successfully')
        
        # Check database
        time_spent = TimeSpent.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        
        self.assertIsNotNone(time_spent)
        self.assertEqual(time_spent.current_session_in_seconds, 300)

    def test_auto_save_time_spent(self):
        """Test auto-saving time spent"""
        url = reverse('exercise-auto-save-time-spent', kwargs={'pk': self.exercise.pk})
        data = {'seconds': 600}  # 10 minutes
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Time auto-saved successfully')

    def test_save_session(self):
        """Test saving a session"""
        # First, create some current session time
        TimeSpent.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id,
            current_session_time=timedelta(minutes=15),
            last_session_start=timezone.now() - timedelta(minutes=15)
        )
        
        url = reverse('exercise-save-session', kwargs={'pk': self.exercise.pk})
        data = {
            'session_type': 'study',
            'notes': 'Good study session'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Session saved successfully')
        
        # Check that TimeSession was created
        session = TimeSession.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        
        self.assertIsNotNone(session)
        self.assertEqual(session.session_type, 'study')
        self.assertEqual(session.notes, 'Good study session')

    def test_get_session_history(self):
        """Test getting session history"""
        # Create some test sessions
        for i in range(3):
            TimeSession.objects.create(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Exercise),
                object_id=self.exercise.id,
                session_duration=timedelta(minutes=10 + i),
                started_at=timezone.now() - timedelta(hours=i+1),
                ended_at=timezone.now() - timedelta(hours=i),
                session_type='study'
            )
        
        url = reverse('exercise-session-history', kwargs={'pk': self.exercise.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        
        # Check that sessions are ordered by creation date (newest first)
        durations = [session['duration'] for session in response.data]
        self.assertEqual(durations, [720, 660, 600])  # 12, 11, 10 minutes in seconds

    def test_save_session_no_current_time(self):
        """Test saving session with no current session time"""
        url = reverse('exercise-save-session', kwargs={'pk': self.exercise.pk})
        data = {'session_type': 'study'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_time_tracking_unauthenticated(self):
        """Test time tracking endpoints without authentication"""
        self.client.credentials()  # Remove authentication
        
        url = reverse('exercise-get-time-spent', kwargs={'pk': self.exercise.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        url = reverse('exercise-save-time-spent', kwargs={'pk': self.exercise.pk})
        response = self.client.post(url, {'seconds': 300})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ExerciseInteractionTest(APITestCase):
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
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_save_exercise(self):
        """Test saving an exercise"""
        url = reverse('exercise-save', kwargs={'pk': self.exercise.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Exercise saved successfully')
        
        # Check database
        save_exists = Save.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).exists()
        self.assertTrue(save_exists)

    def test_unsave_exercise(self):
        """Test unsaving an exercise"""
        # First save the exercise
        Save.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        )
        
        url = reverse('exercise-save', kwargs={'pk': self.exercise.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Exercise unsaved successfully')
        
        # Check database
        save_exists = Save.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).exists()
        self.assertFalse(save_exists)

    def test_complete_exercise(self):
        """Test completing an exercise"""
        url = reverse('exercise-complete', kwargs={'pk': self.exercise.pk})
        data = {'status': 'success'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Exercise marked as success')
        
        # Check database
        complete = Complete.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        
        self.assertIsNotNone(complete)
        self.assertEqual(complete.status, 'success')

    def test_rate_exercise(self):
        """Test rating an exercise"""
        url = reverse('exercise-rate', kwargs={'pk': self.exercise.pk})
        data = {'rating': 4}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Rating saved successfully')
        
        # Check database
        evaluate = Evaluate.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        
        self.assertIsNotNone(evaluate)
        self.assertEqual(evaluate.rating, 4)

    def test_rate_exercise_invalid_rating(self):
        """Test rating an exercise with invalid rating"""
        url = reverse('exercise-rate', kwargs={'pk': self.exercise.pk})
        data = {'rating': 6}  # Invalid rating (should be 1-5)
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_update_existing_rating(self):
        """Test updating an existing rating"""
        # Create existing rating
        Evaluate.objects.create(
            user=self.user,
            rating=3,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        )
        
        url = reverse('exercise-rate', kwargs={'pk': self.exercise.pk})
        data = {'rating': 5}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check that rating was updated
        evaluate = Evaluate.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=self.exercise.id
        ).first()
        
        self.assertEqual(evaluate.rating, 5)


class PaginationTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        
        # Create multiple exercises for pagination testing
        self.exercises = []
        for i in range(25):
            exercise = Exercise.objects.create(
                title=f'Test Exercise {i}',
                content=f'Test content {i}',
                difficulty=3
            )
            self.exercises.append(exercise)

    def test_pagination_default_page_size(self):
        """Test default pagination page size"""
        url = reverse('exercise-list')
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Default page size should be 1000, so all 25 exercises should be returned
        self.assertEqual(len(response.data['results']), 25)

    def test_pagination_custom_page_size(self):
        """Test custom pagination page size"""
        url = reverse('exercise-list')
        
        response = self.client.get(url, {'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNotNone(response.data['next'])  # Should have next page

    def test_pagination_second_page(self):
        """Test accessing second page"""
        url = reverse('exercise-list')
        
        response = self.client.get(url, {'page': 2, 'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNotNone(response.data['previous'])  # Should have previous page