# apps/skilliq/views.py
# Quiz par chapitre côté élève. Depuis le 13/10/2026, un quiz = (chapitre, niveau) : le niveau vient de ?niveau=
# (ou « niveau » dans le corps), sinon du profil (tirage.niveau_demande) ; jamais de questions d'un autre niveau.
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tirage
from .models import SkillQuestion, SkillAssessment
from .serializers import (
    SkillQuestionSerializer,
    SkillAssessmentSerializer,
    QuizSubmissionSerializer
)

SECONDES_PAR_QUESTION = 60  # minuteur du quiz (côté élève, en pause pendant la correction de chaque question)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_assessments(request):
    """Les derniers résultats de l'élève : un par (chapitre, niveau)."""
    assessments = SkillAssessment.objects.filter(user=request.user).select_related('chapter', 'chapter__subject')
    serializer = SkillAssessmentSerializer(assessments, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_quiz(request, chapter_id):
    """Les questions du quiz (chapitre, niveau), une par théorème d'abord (tirage.py) ; jamais une question à relire
    ni d'un autre niveau."""
    niveau = tirage.niveau_demande(request)
    questions = tirage.tirer(tirage.disponibles(niveau, chapter_id))

    if not questions:
        return Response(
            {'error': 'No questions available for this chapter'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = SkillQuestionSerializer(questions, many=True)
    return Response({
        'chapter_id': chapter_id,
        'niveau': niveau.id,
        'questions': serializer.data,
        # Minuteur façon concours (13/10/2026) : 1 min par question, en pause pendant la correction de chacune.
        'duree_secondes': SECONDES_PAR_QUESTION * len(questions),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_quiz(request, chapter_id):
    """Réponses du quiz (chapitre, niveau) → score, correction, bilan par théorème."""
    serializer = QuizSubmissionSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    answers = serializer.validated_data['answers']
    time_spent = serializer.validated_data.get('time_spent', 0)
    niveau = tirage.niveau_demande(request)

    question_ids = [int(qid) for qid in answers.keys()]
    questions = SkillQuestion.objects.filter(
        id__in=question_ids,
        chapter_id=chapter_id,
        class_level=niveau,
        is_active=True,
        a_relire=False,
    ).prefetch_related('theorems')

    if niveau is None or not questions.exists():
        return Response(
            {'error': 'Invalid questions'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Score pondéré par la difficulté (jamais montrée aux élèves).
    score = 0
    max_score = 0
    difficulty_points = {'easy': 1, 'medium': 2, 'hard': 3}

    for question in questions:
        points = difficulty_points.get(question.difficulty, 1)
        max_score += points

        user_answer = answers.get(str(question.id))
        if user_answer is not None and user_answer == question.correct_answer:
            score += points

    # Bilan par théorème : ce que l'élève maîtrise, ce qu'il doit revoir (tirage.bilan).
    par_theoreme = tirage.bilan(questions, answers, tirage.disponibles(niveau, chapter_id))

    # Un résultat par (chapitre, niveau) ; un nouveau passage garde le score précédent (« 40 % → 80 % »).
    # Un résultat d'avant le découpage par niveau (sans niveau) est repris par ce passage.
    with transaction.atomic():
        mine = SkillAssessment.objects.select_for_update().filter(user=request.user, chapter_id=chapter_id)
        assessment = mine.filter(class_level=niveau).first() or mine.filter(class_level__isnull=True).first()
        if assessment is None:
            assessment = SkillAssessment.objects.create(
                user=request.user, chapter_id=chapter_id, class_level=niveau, score=score, max_score=max_score,
                answers=answers, time_spent=time_spent, par_theoreme=par_theoreme)
        else:
            assessment.class_level = niveau
            assessment.previous_score, assessment.previous_max = assessment.score, assessment.max_score
            assessment.attempts = (assessment.attempts or 1) + 1
            assessment.score, assessment.max_score = score, max_score
            assessment.answers, assessment.time_spent = answers, time_spent
            assessment.par_theoreme = par_theoreme
            assessment.save()

    from apps.users.maitrise import forget
    forget(request.user.id)  # « Ma progression » : le quiz compte dans la maîtrise du chapitre
    result = SkillAssessmentSerializer(assessment, context={'request': request}).data
    # Correction question par question, envoyée seulement APRÈS la soumission (la bonne réponse
    # n'est jamais dans le quiz lui-même) : l'élève voit ses erreurs et l'explication.
    result['correction'] = [
        {'id': q.id, 'your_answer': answers.get(str(q.id)), 'correct_answer': q.correct_answer,
         'is_correct': answers.get(str(q.id)) == q.correct_answer, 'explanation': q.explanation,
         'theoremes': [th.name for th in q.theorems.all()]}
        for q in questions
    ]
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_answer(request, question_id):
    """Correction d'une question dès que l'élève a répondu (13/10/2026) : {"answer": i} → bonne réponse, explication,
    théorèmes. Le score reste calculé à l'envoi du quiz (submit_quiz) ; une question à relire n'est jamais corrigée ici."""
    q = SkillQuestion.objects.filter(pk=question_id, is_active=True, a_relire=False).prefetch_related('theorems').first()
    if q is None:
        return Response({'error': 'Question introuvable'}, status=status.HTTP_404_NOT_FOUND)
    answer = request.data.get('answer')
    if not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(q.options):
        return Response({'answer': 'Réponse invalide'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'id': q.id, 'your_answer': answer, 'correct_answer': q.correct_answer,
                     'is_correct': answer == q.correct_answer, 'explanation': q.explanation,
                     'theoremes': [th.name for th in q.theorems.all()]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_available(request):
    """Quiz prêts : {chapitre: nombre de questions} pour le niveau demandé (sinon celui de l'élève) ;
    ?tous=1 : {niveau: {chapitre: nombre}} pour tous les niveaux (barre de niveaux de la page)."""
    from django.db.models import Count
    qs = SkillQuestion.objects.filter(is_active=True, a_relire=False, class_level__isnull=False)
    if request.query_params.get('tous'):
        out = {}
        for r in qs.values('class_level_id', 'chapter_id').annotate(n=Count('id')):
            out.setdefault(str(r['class_level_id']), {})[str(r['chapter_id'])] = r['n']
        return Response(out)
    niveau = tirage.niveau_demande(request)
    if niveau is None:
        return Response({})
    rows = qs.filter(class_level=niveau).values('chapter_id').annotate(n=Count('id'))
    return Response({str(r['chapter_id']): r['n'] for r in rows})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chapter_assessment(request, chapter_id):
    """Dernier résultat de l'élève sur le quiz (chapitre, niveau)."""
    niveau = tirage.niveau_demande(request)
    assessment = (SkillAssessment.objects.filter(user=request.user, chapter_id=chapter_id, class_level=niveau).first()
                  or SkillAssessment.objects.filter(user=request.user, chapter_id=chapter_id,
                                                    class_level__isnull=True).first())
    if assessment is None:
        return Response(
            {'error': 'No assessment found for this chapter'},
            status=status.HTTP_404_NOT_FOUND
        )
    serializer = SkillAssessmentSerializer(assessment, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_new(request):
    """Quiz sortis depuis moins de 14 jours : [{niveau, chapitre, depuis}] (étiquette « Nouveau », annonces.py)."""
    from .annonces import nouveaux
    return Response([{'niveau': lv, 'chapitre': ch, 'depuis': d.isoformat()} for (ch, lv), d in nouveaux().items()])
