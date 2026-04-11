# apps/skilliq/views.py
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SkillQuestion, SkillAssessment
from .serializers import (
    SkillQuestionSerializer,
    SkillAssessmentSerializer,
    QuizSubmissionSerializer
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_assessments(request):
    """Get all skill assessments for the current user"""
    assessments = SkillAssessment.objects.filter(user=request.user).select_related('chapter', 'chapter__subject')
    serializer = SkillAssessmentSerializer(assessments, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_quiz(request, chapter_id):
    """Get quiz questions for a chapter"""
    questions = SkillQuestion.objects.filter(
        chapter_id=chapter_id,
        is_active=True
    ).order_by('?')[:10]  # Random 10 questions

    if not questions.exists():
        return Response(
            {'error': 'No questions available for this chapter'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = SkillQuestionSerializer(questions, many=True)
    return Response({
        'chapter_id': chapter_id,
        'questions': serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_quiz(request, chapter_id):
    """Submit quiz answers and get results"""
    serializer = QuizSubmissionSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    answers = serializer.validated_data['answers']
    time_spent = serializer.validated_data.get('time_spent', 0)

    # Get questions for this chapter
    question_ids = [int(qid) for qid in answers.keys()]
    questions = SkillQuestion.objects.filter(
        id__in=question_ids,
        chapter_id=chapter_id,
        is_active=True
    )

    if not questions.exists():
        return Response(
            {'error': 'Invalid questions'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Calculate score with weighted difficulty
    score = 0
    max_score = 0
    difficulty_points = {'easy': 1, 'medium': 2, 'hard': 3}

    for question in questions:
        points = difficulty_points.get(question.difficulty, 1)
        max_score += points

        user_answer = answers.get(str(question.id))
        if user_answer is not None and user_answer == question.correct_answer:
            score += points

    # Create or update assessment
    assessment, created = SkillAssessment.objects.update_or_create(
        user=request.user,
        chapter_id=chapter_id,
        defaults={
            'score': score,
            'max_score': max_score,
            'answers': answers,
            'time_spent': time_spent
        }
    )

    result_serializer = SkillAssessmentSerializer(assessment)
    return Response(result_serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chapter_assessment(request, chapter_id):
    """Get assessment for a specific chapter"""
    try:
        assessment = SkillAssessment.objects.get(
            user=request.user,
            chapter_id=chapter_id
        )
        serializer = SkillAssessmentSerializer(assessment)
        return Response(serializer.data)
    except SkillAssessment.DoesNotExist:
        return Response(
            {'error': 'No assessment found for this chapter'},
            status=status.HTTP_404_NOT_FOUND
        )
