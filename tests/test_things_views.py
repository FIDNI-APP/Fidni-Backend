import os
import sys
import django
import json
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
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

from things.models import Exercise, Exam
from caracteristics.models import ClassLevel, Subject, Chapter, Subfield, Theorem
from interactions.models import Vote, Save, Complete, TimeSpent, TimeSession, Evaluate
from django.contrib.contenttypes.models import ContentType


class ExerciseViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test data
        self.class_level = ClassLevel.objects.create(
            name="2ème Bac SM",
            order=1
        )
        self.subject = Subject.objects.create(
            name="Mathématiques",
            class_level=self.class_level
        )
        self.chapter = Chapter.objects.create(
            name="Algèbre",
            subject=self.subject
        )
        self.subfield = Subfield.objects.create(
            name="Nombres complexes",
            chapter=self.chapter
        )
        self.theorem = Theorem.objects.create(
            name="Théorème de Moivre",
            subfield=self.subfield
        )
        
        self.exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test exercise content',
            difficulty=3,
            class_level=self.class_level,
            subject=self.subject,
            chapter=self.chapter,
            subfield=self.subfield,
            theorem=self.theorem
        )
        
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_exercise_list(self):
        """Test listing exercises"""
        url = reverse('exercise-list')
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Test Exercise')

    def test_exercise_detail(self):
        """Test retrieving exercise detail"""
        url = reverse('exercise-detail', kwargs={'pk': self.exercise.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Test Exercise')
        self.assertEqual(response.data['content'], 'Test exercise content')
        self.assertEqual(response.data['difficulty'], 3)

    def test_exercise_create_authenticated(self):
        """Test creating an exercise (authenticated user)"""
        url = reverse('exercise-list')
        data = {
            'title': 'New Exercise',
            'content': 'New exercise content',
            'difficulty': 4,
            'class_level': self.class_level.id,
            'subject': self.subject.id
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'New Exercise')
        
        # Check database
        exercise = Exercise.objects.filter(title='New Exercise').first()
        self.assertIsNotNone(exercise)
        self.assertEqual(exercise.content, 'New exercise content')

    def test_exercise_create_unauthenticated(self):
        """Test creating an exercise without authentication"""
        self.client.credentials()  # Remove authentication
        
        url = reverse('exercise-list')
        data = {
            'title': 'New Exercise',
            'content': 'New exercise content',
            'difficulty': 4
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_exercise_update(self):
        """Test updating an exercise"""
        url = reverse('exercise-detail', kwargs={'pk': self.exercise.pk})
        data = {
            'title': 'Updated Exercise',
            'content': 'Updated content',
            'difficulty': 5
        }
        
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Exercise')
        
        # Check database
        self.exercise.refresh_from_db()
        self.assertEqual(self.exercise.title, 'Updated Exercise')
        self.assertEqual(self.exercise.content, 'Updated content')
        self.assertEqual(self.exercise.difficulty, 5)

    def test_exercise_delete(self):
        """Test deleting an exercise"""
        url = reverse('exercise-detail', kwargs={'pk': self.exercise.pk})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Check that exercise is deleted
        self.assertFalse(Exercise.objects.filter(pk=self.exercise.pk).exists())

    def test_exercise_filtering_by_difficulty(self):
        """Test filtering exercises by difficulty"""
        # Create exercises with different difficulties
        Exercise.objects.create(
            title='Easy Exercise',
            content='Easy content',
            difficulty=1
        )
        Exercise.objects.create(
            title='Hard Exercise',
            content='Hard content',
            difficulty=5
        )
        
        url = reverse('exercise-list')
        
        # Filter by difficulty
        response = self.client.get(url, {'difficulty': 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Easy Exercise')

    def test_exercise_filtering_by_class_level(self):
        """Test filtering exercises by class level"""
        # Create another class level and exercise
        other_class_level = ClassLevel.objects.create(
            name="1ère Bac SM",
            order=2
        )
        Exercise.objects.create(
            title='Other Level Exercise',
            content='Other content',
            difficulty=3,
            class_level=other_class_level
        )
        
        url = reverse('exercise-list')
        
        # Filter by class level
        response = self.client.get(url, {'class_level': self.class_level.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Test Exercise')

    def test_exercise_search(self):
        """Test searching exercises"""
        Exercise.objects.create(
            title='Complex Numbers',
            content='Exercise about complex numbers',
            difficulty=3
        )
        
        url = reverse('exercise-list')
        
        # Search by title
        response = self.client.get(url, {'search': 'complex'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Complex Numbers')

    def test_exercise_ordering(self):
        """Test exercise ordering"""
        # Create exercises with different creation times
        exercise1 = Exercise.objects.create(
            title='First Exercise',
            content='First content',
            difficulty=1
        )
        exercise2 = Exercise.objects.create(
            title='Second Exercise',
            content='Second content',
            difficulty=2
        )
        
        url = reverse('exercise-list')
        
        # Default ordering should be newest first
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [ex['title'] for ex in response.data['results']]
        self.assertEqual(titles[0], 'Second Exercise')  # Newest first


class ExamViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test data
        self.class_level = ClassLevel.objects.create(
            name="2ème Bac SM",
            order=1
        )
        self.subject = Subject.objects.create(
            name="Mathématiques",
            class_level=self.class_level
        )
        self.chapter = Chapter.objects.create(
            name="Algèbre",
            subject=self.subject
        )
        
        self.exam = Exam.objects.create(
            title='Test Exam',
            content='Test exam content',
            difficulty=4,
            duration=timedelta(hours=2),
            class_level=self.class_level,
            subject=self.subject,
            chapter=self.chapter
        )
        
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_exam_list(self):
        """Test listing exams"""
        url = reverse('exam-list')
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Test Exam')

    def test_exam_detail(self):
        """Test retrieving exam detail"""
        url = reverse('exam-detail', kwargs={'pk': self.exam.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Test Exam')
        self.assertEqual(response.data['content'], 'Test exam content')
        self.assertEqual(response.data['difficulty'], 4)

    def test_exam_create_authenticated(self):
        """Test creating an exam (authenticated user)"""
        url = reverse('exam-list')
        data = {
            'title': 'New Exam',
            'content': 'New exam content',
            'difficulty': 5,
            'duration': '03:00:00',  # 3 hours
            'class_level': self.class_level.id,
            'subject': self.subject.id
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'New Exam')
        
        # Check database
        exam = Exam.objects.filter(title='New Exam').first()
        self.assertIsNotNone(exam)
        self.assertEqual(exam.content, 'New exam content')
        self.assertEqual(exam.duration, timedelta(hours=3))

    def test_exam_create_unauthenticated(self):
        """Test creating an exam without authentication"""
        self.client.credentials()  # Remove authentication
        
        url = reverse('exam-list')
        data = {
            'title': 'New Exam',
            'content': 'New exam content',
            'difficulty': 4,
            'duration': '02:00:00'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_exam_update(self):
        """Test updating an exam"""
        url = reverse('exam-detail', kwargs={'pk': self.exam.pk})
        data = {
            'title': 'Updated Exam',
            'content': 'Updated content',
            'difficulty': 5,
            'duration': '03:30:00'  # 3.5 hours
        }
        
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Exam')
        
        # Check database
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.title, 'Updated Exam')
        self.assertEqual(self.exam.content, 'Updated content')
        self.assertEqual(self.exam.difficulty, 5)
        self.assertEqual(self.exam.duration, timedelta(hours=3, minutes=30))

    def test_exam_delete(self):
        """Test deleting an exam"""
        url = reverse('exam-detail', kwargs={'pk': self.exam.pk})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Check that exam is deleted
        self.assertFalse(Exam.objects.filter(pk=self.exam.pk).exists())

    def test_exam_filtering_by_difficulty(self):
        """Test filtering exams by difficulty"""
        # Create exams with different difficulties
        Exam.objects.create(
            title='Easy Exam',
            content='Easy content',
            difficulty=1,
            duration=timedelta(hours=1)
        )
        Exam.objects.create(
            title='Hard Exam',
            content='Hard content',
            difficulty=5,
            duration=timedelta(hours=4)
        )
        
        url = reverse('exam-list')
        
        # Filter by difficulty
        response = self.client.get(url, {'difficulty': 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'Easy Exam')

    def test_exam_filtering_by_duration(self):
        """Test filtering exams by duration"""
        # Create exams with different durations
        Exam.objects.create(
            title='Short Exam',
            content='Short content',
            difficulty=3,
            duration=timedelta(hours=1)
        )
        Exam.objects.create(
            title='Long Exam',
            content='Long content',
            difficulty=3,
            duration=timedelta(hours=4)
        )
        
        url = reverse('exam-list')
        
        # Filter by duration (assuming there's a duration filter)
        response = self.client.get(url, {'duration__lte': '02:00:00'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return exams with duration <= 2 hours
        durations = [ex['duration'] for ex in response.data['results']]
        for duration_str in durations:
            hours, minutes, seconds = map(int, duration_str.split(':'))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            self.assertLessEqual(total_seconds, 7200)  # 2 hours in seconds


class ExerciseInteractionEndpointsTest(APITestCase):
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

    def test_exercise_save_endpoint(self):
        """Test the save exercise endpoint"""
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

    def test_exercise_complete_endpoint(self):
        """Test the complete exercise endpoint"""
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

    def test_exercise_rate_endpoint(self):
        """Test the rate exercise endpoint"""
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

    def test_exercise_vote_endpoint(self):
        """Test the vote exercise endpoint"""
        url = reverse('exercise-vote', kwargs={'pk': self.exercise.pk})
        data = {'value': Vote.UP}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], Vote.UP)
        self.assertEqual(response.data['vote_count'], 1)


class ExamInteractionEndpointsTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.exam = Exam.objects.create(
            title='Test Exam',
            content='Test content',
            difficulty=4,
            duration=timedelta(hours=2)
        )
        
        self.client = APIClient()
        
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_exam_save_endpoint(self):
        """Test the save exam endpoint"""
        url = reverse('exam-save', kwargs={'pk': self.exam.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Exam saved successfully')
        
        # Check database
        save_exists = Save.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exam),
            object_id=self.exam.id
        ).exists()
        self.assertTrue(save_exists)

    def test_exam_complete_endpoint(self):
        """Test the complete exam endpoint"""
        url = reverse('exam-complete', kwargs={'pk': self.exam.pk})
        data = {'status': 'success'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Exam marked as success')
        
        # Check database
        complete = Complete.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exam),
            object_id=self.exam.id
        ).first()
        
        self.assertIsNotNone(complete)
        self.assertEqual(complete.status, 'success')

    def test_exam_rate_endpoint(self):
        """Test the rate exam endpoint"""
        url = reverse('exam-rate', kwargs={'pk': self.exam.pk})
        data = {'rating': 5}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Rating saved successfully')
        
        # Check database
        evaluate = Evaluate.objects.filter(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Exam),
            object_id=self.exam.id
        ).first()
        
        self.assertIsNotNone(evaluate)
        self.assertEqual(evaluate.rating, 5)

    def test_exam_vote_endpoint(self):
        """Test the vote exam endpoint"""
        url = reverse('exam-vote', kwargs={'pk': self.exam.pk})
        data = {'value': Vote.DOWN}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user_vote'], Vote.DOWN)
        self.assertEqual(response.data['vote_count'], -1)


class PermissionTest(APITestCase):
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

    def test_unauthenticated_read_access(self):
        """Test that unauthenticated users can read exercises"""
        url = reverse('exercise-list')
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_write_access(self):
        """Test that unauthenticated users cannot create exercises"""
        url = reverse('exercise-list')
        data = {
            'title': 'New Exercise',
            'content': 'New content',
            'difficulty': 3
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_write_access(self):
        """Test that authenticated users can create exercises"""
        # Get JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        
        url = reverse('exercise-list')
        data = {
            'title': 'New Exercise',
            'content': 'New content',
            'difficulty': 3
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)