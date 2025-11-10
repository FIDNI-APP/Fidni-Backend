"""
Simple content-based recommendation system
Recommends content based on shared taxonomy (chapters, subjects, theorems, subfields)
Can be replaced with ML model later
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q, Count
from .models import Exercise, Lesson, Exam
from .serializers import ExerciseSerializer, LessonSerializer, ExamSerializer


@api_view(['GET'])
def get_exercise_recommendations(request, exercise_id):
    """
    Recommend similar exercises, lessons, and exams based on shared taxonomy
    """
    try:
        exercise = Exercise.objects.get(id=exercise_id)

        # Get taxonomy
        chapters = exercise.chapters.all()
        theorems = exercise.theorems.all()
        subfields = exercise.subfields.all()
        subject = exercise.subject

        # Find similar exercises (exclude current)
        similar_exercises = Exercise.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).exclude(id=exercise_id).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:3]

        # Find related lessons
        related_lessons = Lesson.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:2]

        # Find related exams
        related_exams = Exam.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:2]

        return Response({
            'exercises': ExerciseSerializer(similar_exercises, many=True, context={'request': request}).data,
            'lessons': LessonSerializer(related_lessons, many=True, context={'request': request}).data,
            'exams': ExamSerializer(related_exams, many=True, context={'request': request}).data,
        })

    except Exercise.DoesNotExist:
        return Response({'error': 'Exercise not found'}, status=404)


@api_view(['GET'])
def get_lesson_recommendations(request, lesson_id):
    """
    Recommend related exercises and exams for a lesson
    """
    try:
        lesson = Lesson.objects.get(id=lesson_id)

        # Get taxonomy
        chapters = lesson.chapters.all()
        theorems = lesson.theorems.all()
        subfields = lesson.subfields.all()
        subject = lesson.subject

        # Find related exercises
        related_exercises = Exercise.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:4]

        # Find related exams
        related_exams = Exam.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:3]

        return Response({
            'exercises': ExerciseSerializer(related_exercises, many=True, context={'request': request}).data,
            'exams': ExamSerializer(related_exams, many=True, context={'request': request}).data,
        })

    except Lesson.DoesNotExist:
        return Response({'error': 'Lesson not found'}, status=404)


@api_view(['GET'])
def get_exam_recommendations(request, exam_id):
    """
    Recommend similar exams, exercises, and lessons based on shared taxonomy
    """
    try:
        exam = Exam.objects.get(id=exam_id)

        # Get taxonomy
        chapters = exam.chapters.all()
        theorems = exam.theorems.all()
        subfields = exam.subfields.all()
        subject = exam.subject

        # Find similar exams (exclude current)
        similar_exams = Exam.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).exclude(id=exam_id).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:3]

        # Find related exercises
        related_exercises = Exercise.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:3]

        # Find related lessons
        related_lessons = Lesson.objects.filter(
            Q(chapters__in=chapters) |
            Q(theorems__in=theorems) |
            Q(subfields__in=subfields) |
            Q(subject=subject)
        ).distinct().annotate(
            relevance=Count('chapters') + Count('theorems') + Count('subfields')
        ).order_by('-relevance', '-view_count')[:2]

        return Response({
            'exams': ExamSerializer(similar_exams, many=True, context={'request': request}).data,
            'exercises': ExerciseSerializer(related_exercises, many=True, context={'request': request}).data,
            'lessons': LessonSerializer(related_lessons, many=True, context={'request': request}).data,
        })

    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=404)
