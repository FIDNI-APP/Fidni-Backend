import os
import sys
import django
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
django.setup()

from things.models import Exercise, Exam
from caracteristics.models import ClassLevel, Subject, Chapter, Subfield, Theorem


class ExerciseModelTest(TestCase):
    def setUp(self):
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

    def test_exercise_creation(self):
        """Test creating an exercise with required fields"""
        exercise = Exercise.objects.create(
            title='Test Exercise',
            content='This is a test exercise content',
            difficulty=3
        )
        
        self.assertEqual(exercise.title, 'Test Exercise')
        self.assertEqual(exercise.content, 'This is a test exercise content')
        self.assertEqual(exercise.difficulty, 3)
        self.assertTrue(exercise.created_at)
        self.assertTrue(exercise.updated_at)
        self.assertTrue(exercise.is_active)

    def test_exercise_with_relationships(self):
        """Test creating an exercise with foreign key relationships"""
        exercise = Exercise.objects.create(
            title='Advanced Exercise',
            content='Advanced exercise content',
            difficulty=4,
            class_level=self.class_level,
            subject=self.subject,
            chapter=self.chapter,
            subfield=self.subfield,
            theorem=self.theorem
        )
        
        self.assertEqual(exercise.class_level, self.class_level)
        self.assertEqual(exercise.subject, self.subject)
        self.assertEqual(exercise.chapter, self.chapter)
        self.assertEqual(exercise.subfield, self.subfield)
        self.assertEqual(exercise.theorem, self.theorem)

    def test_exercise_difficulty_validation(self):
        """Test exercise difficulty validation (should be 1-5)"""
        # Valid difficulties
        for difficulty in range(1, 6):
            exercise = Exercise.objects.create(
                title=f'Exercise {difficulty}',
                content='Test content',
                difficulty=difficulty
            )
            self.assertEqual(exercise.difficulty, difficulty)
            exercise.delete()  # Clean up

    def test_exercise_str_method(self):
        """Test the string representation of Exercise"""
        exercise = Exercise.objects.create(
            title='Test Exercise',
            content='Test content',
            difficulty=3
        )
        self.assertEqual(str(exercise), 'Test Exercise')

    def test_exercise_ordering(self):
        """Test exercise ordering (should be by creation date, newest first)"""
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
        
        exercises = Exercise.objects.all()
        self.assertEqual(exercises[0], exercise2)  # Newest first
        self.assertEqual(exercises[1], exercise1)

    def test_exercise_optional_fields(self):
        """Test exercise with optional fields"""
        exercise = Exercise.objects.create(
            title='Exercise with extras',
            content='Content with extras',
            difficulty=3,
            hint='This is a hint',
            solution='This is the solution',
            explanation='This is an explanation',
            source='Test source',
            tags='algebra,complex-numbers'
        )
        
        self.assertEqual(exercise.hint, 'This is a hint')
        self.assertEqual(exercise.solution, 'This is the solution')
        self.assertEqual(exercise.explanation, 'This is an explanation')
        self.assertEqual(exercise.source, 'Test source')
        self.assertEqual(exercise.tags, 'algebra,complex-numbers')

    def test_exercise_is_active_default(self):
        """Test that exercises are active by default"""
        exercise = Exercise.objects.create(
            title='Active Exercise',
            content='Active content',
            difficulty=3
        )
        self.assertTrue(exercise.is_active)

    def test_exercise_deactivation(self):
        """Test deactivating an exercise"""
        exercise = Exercise.objects.create(
            title='Exercise to deactivate',
            content='Content to deactivate',
            difficulty=3
        )
        
        exercise.is_active = False
        exercise.save()
        
        self.assertFalse(exercise.is_active)


class ExamModelTest(TestCase):
    def setUp(self):
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

    def test_exam_creation(self):
        """Test creating an exam with required fields"""
        exam = Exam.objects.create(
            title='Test Exam',
            content='This is a test exam content',
            difficulty=4,
            duration=timedelta(hours=2)
        )
        
        self.assertEqual(exam.title, 'Test Exam')
        self.assertEqual(exam.content, 'This is a test exam content')
        self.assertEqual(exam.difficulty, 4)
        self.assertEqual(exam.duration, timedelta(hours=2))
        self.assertTrue(exam.created_at)
        self.assertTrue(exam.updated_at)
        self.assertTrue(exam.is_active)

    def test_exam_with_relationships(self):
        """Test creating an exam with foreign key relationships"""
        exam = Exam.objects.create(
            title='Advanced Exam',
            content='Advanced exam content',
            difficulty=5,
            duration=timedelta(hours=3),
            class_level=self.class_level,
            subject=self.subject,
            chapter=self.chapter,
            subfield=self.subfield
        )
        
        self.assertEqual(exam.class_level, self.class_level)
        self.assertEqual(exam.subject, self.subject)
        self.assertEqual(exam.chapter, self.chapter)
        self.assertEqual(exam.subfield, self.subfield)

    def test_exam_difficulty_validation(self):
        """Test exam difficulty validation (should be 1-5)"""
        # Valid difficulties
        for difficulty in range(1, 6):
            exam = Exam.objects.create(
                title=f'Exam {difficulty}',
                content='Test content',
                difficulty=difficulty,
                duration=timedelta(hours=2)
            )
            self.assertEqual(exam.difficulty, difficulty)
            exam.delete()  # Clean up

    def test_exam_str_method(self):
        """Test the string representation of Exam"""
        exam = Exam.objects.create(
            title='Test Exam',
            content='Test content',
            difficulty=3,
            duration=timedelta(hours=2)
        )
        self.assertEqual(str(exam), 'Test Exam')

    def test_exam_ordering(self):
        """Test exam ordering (should be by creation date, newest first)"""
        exam1 = Exam.objects.create(
            title='First Exam',
            content='First content',
            difficulty=1,
            duration=timedelta(hours=1)
        )
        exam2 = Exam.objects.create(
            title='Second Exam',
            content='Second content',
            difficulty=2,
            duration=timedelta(hours=2)
        )
        
        exams = Exam.objects.all()
        self.assertEqual(exams[0], exam2)  # Newest first
        self.assertEqual(exams[1], exam1)

    def test_exam_duration_property(self):
        """Test exam duration handling"""
        exam = Exam.objects.create(
            title='Timed Exam',
            content='Timed content',
            difficulty=3,
            duration=timedelta(hours=2, minutes=30)
        )
        
        self.assertEqual(exam.duration.total_seconds(), 9000)  # 2.5 hours in seconds

    def test_exam_optional_fields(self):
        """Test exam with optional fields"""
        exam = Exam.objects.create(
            title='Exam with extras',
            content='Content with extras',
            difficulty=4,
            duration=timedelta(hours=3),
            instructions='Read carefully before starting',
            solution='Complete solution here',
            source='National Exam 2023',
            tags='final,comprehensive'
        )
        
        self.assertEqual(exam.instructions, 'Read carefully before starting')
        self.assertEqual(exam.solution, 'Complete solution here')
        self.assertEqual(exam.source, 'National Exam 2023')
        self.assertEqual(exam.tags, 'final,comprehensive')

    def test_exam_is_active_default(self):
        """Test that exams are active by default"""
        exam = Exam.objects.create(
            title='Active Exam',
            content='Active content',
            difficulty=3,
            duration=timedelta(hours=2)
        )
        self.assertTrue(exam.is_active)

    def test_exam_deactivation(self):
        """Test deactivating an exam"""
        exam = Exam.objects.create(
            title='Exam to deactivate',
            content='Content to deactivate',
            difficulty=3,
            duration=timedelta(hours=2)
        )
        
        exam.is_active = False
        exam.save()
        
        self.assertFalse(exam.is_active)


class ExerciseExamRelationshipTest(TestCase):
    def setUp(self):
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

    def test_exercise_filtering_by_class_level(self):
        """Test filtering exercises by class level"""
        exercise1 = Exercise.objects.create(
            title='Exercise 1',
            content='Content 1',
            difficulty=3,
            class_level=self.class_level
        )
        
        # Create another class level and exercise
        other_class_level = ClassLevel.objects.create(
            name="1ère Bac SM",
            order=2
        )
        exercise2 = Exercise.objects.create(
            title='Exercise 2',
            content='Content 2',
            difficulty=3,
            class_level=other_class_level
        )
        
        # Filter by class level
        exercises = Exercise.objects.filter(class_level=self.class_level)
        self.assertEqual(exercises.count(), 1)
        self.assertEqual(exercises.first(), exercise1)

    def test_exam_filtering_by_subject(self):
        """Test filtering exams by subject"""
        exam1 = Exam.objects.create(
            title='Math Exam',
            content='Math content',
            difficulty=4,
            duration=timedelta(hours=2),
            subject=self.subject
        )
        
        # Create another subject and exam
        other_subject = Subject.objects.create(
            name="Physique",
            class_level=self.class_level
        )
        exam2 = Exam.objects.create(
            title='Physics Exam',
            content='Physics content',
            difficulty=4,
            duration=timedelta(hours=2),
            subject=other_subject
        )
        
        # Filter by subject
        exams = Exam.objects.filter(subject=self.subject)
        self.assertEqual(exams.count(), 1)
        self.assertEqual(exams.first(), exam1)

    def test_exercise_filtering_by_difficulty(self):
        """Test filtering exercises by difficulty"""
        easy_exercise = Exercise.objects.create(
            title='Easy Exercise',
            content='Easy content',
            difficulty=1
        )
        hard_exercise = Exercise.objects.create(
            title='Hard Exercise',
            content='Hard content',
            difficulty=5
        )
        
        # Filter by difficulty
        easy_exercises = Exercise.objects.filter(difficulty__lte=2)
        hard_exercises = Exercise.objects.filter(difficulty__gte=4)
        
        self.assertIn(easy_exercise, easy_exercises)
        self.assertNotIn(hard_exercise, easy_exercises)
        self.assertIn(hard_exercise, hard_exercises)
        self.assertNotIn(easy_exercise, hard_exercises)

    def test_exercise_filtering_by_active_status(self):
        """Test filtering exercises by active status"""
        active_exercise = Exercise.objects.create(
            title='Active Exercise',
            content='Active content',
            difficulty=3,
            is_active=True
        )
        inactive_exercise = Exercise.objects.create(
            title='Inactive Exercise',
            content='Inactive content',
            difficulty=3,
            is_active=False
        )
        
        # Filter by active status
        active_exercises = Exercise.objects.filter(is_active=True)
        inactive_exercises = Exercise.objects.filter(is_active=False)
        
        self.assertIn(active_exercise, active_exercises)
        self.assertNotIn(inactive_exercise, active_exercises)
        self.assertIn(inactive_exercise, inactive_exercises)
        self.assertNotIn(active_exercise, inactive_exercises)

    def test_exercise_search_by_title(self):
        """Test searching exercises by title"""
        exercise1 = Exercise.objects.create(
            title='Complex Numbers Exercise',
            content='Content about complex numbers',
            difficulty=3
        )
        exercise2 = Exercise.objects.create(
            title='Algebra Basics',
            content='Basic algebra content',
            difficulty=2
        )
        
        # Search by title
        complex_exercises = Exercise.objects.filter(title__icontains='complex')
        algebra_exercises = Exercise.objects.filter(title__icontains='algebra')
        
        self.assertIn(exercise1, complex_exercises)
        self.assertNotIn(exercise2, complex_exercises)
        self.assertIn(exercise2, algebra_exercises)
        self.assertNotIn(exercise1, algebra_exercises)

    def test_exercise_content_search(self):
        """Test searching exercises by content"""
        exercise1 = Exercise.objects.create(
            title='Exercise 1',
            content='This exercise covers derivatives and integrals',
            difficulty=3
        )
        exercise2 = Exercise.objects.create(
            title='Exercise 2',
            content='This exercise covers matrices and determinants',
            difficulty=3
        )
        
        # Search by content
        calculus_exercises = Exercise.objects.filter(content__icontains='derivatives')
        algebra_exercises = Exercise.objects.filter(content__icontains='matrices')
        
        self.assertIn(exercise1, calculus_exercises)
        self.assertNotIn(exercise2, calculus_exercises)
        self.assertIn(exercise2, algebra_exercises)
        self.assertNotIn(exercise1, algebra_exercises)