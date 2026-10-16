# apps/skilliq/views.py
# Quiz par chapitre côté élève. Depuis le 13/10/2026, un quiz = (chapitre, niveau) : le niveau vient de ?niveau=
# (ou « niveau » dans le corps), sinon du profil (tirage.niveau_demande) ; jamais de questions d'un autre niveau.
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tirage
from .models import QuizEnCours, SkillQuestion, SkillAssessment, reponse_valide
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


def _correction(q, answer):
    """Correction d'une question pour l'élève (et figée dans le dernier résultat). `correct_answers` : toutes les
    bonnes réponses (une seule, ou plusieurs : l'élève doit les cocher toutes, et rien d'autre)."""
    return {'id': q.id, 'question': q.question, 'options': list(q.options), 'your_answer': answer,
            'correct_answer': q.correct_answer, 'correct_answers': q.bonnes(), 'is_correct': q.est_juste(answer),
            'explanation': q.explanation, 'theoremes': [th.name for th in q.theorems.all()]}


def _questions_du_passage(passage):
    """Questions du passage, dans l'ordre servi (une question supprimée depuis est sautée)."""
    par_id = {q.id: q for q in SkillQuestion.objects.filter(id__in=passage.questions).prefetch_related('theorems')}
    return [par_id[i] for i in passage.questions if i in par_id]


def _oublier_passages_anciens(user):
    QuizEnCours.objects.filter(user=user, maj__lt=timezone.now() - timedelta(hours=QuizEnCours.REPRISE_HEURES)).delete()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_quiz(request, chapter_id):
    """Les questions du quiz (chapitre, niveau), une par théorème d'abord (tirage.py) ; jamais une question à relire
    ni d'un autre niveau. Le passage est gardé en base (QuizEnCours) : un passage commencé est repris (mêmes
    questions, corrections déjà vues, temps restant) tant qu'il n'est pas envoyé ; ?nouveau=1 : nouveau tirage."""
    niveau = tirage.niveau_demande(request)
    if niveau is None:
        return Response({'error': 'No questions available for this chapter'}, status=status.HTTP_404_NOT_FOUND)
    _oublier_passages_anciens(request.user)
    passage = None
    if not request.query_params.get('nouveau'):
        passage = QuizEnCours.objects.filter(user=request.user, chapter_id=chapter_id, class_level=niveau).first()
    questions = _questions_du_passage(passage) if passage else []
    reprise = bool(questions)
    if not reprise:
        questions = tirage.tirer(tirage.disponibles(niveau, chapter_id))
        if not questions:
            return Response({'error': 'No questions available for this chapter'}, status=status.HTTP_404_NOT_FOUND)
        passage, _ = QuizEnCours.objects.update_or_create(
            user=request.user, chapter_id=chapter_id, class_level=niveau,
            defaults={'questions': [q.id for q in questions], 'reponses': {}, 'temps': 0,
                      # Minuteur façon concours (13/10/2026) : 1 min par question, en pause pendant les corrections.
                      'duree_secondes': SECONDES_PAR_QUESTION * len(questions), 'debut': timezone.now()})
    reponses = passage.reponses or {}
    return Response({
        'chapter_id': chapter_id,
        'niveau': niveau.id,
        'questions': SkillQuestionSerializer(questions, many=True).data,
        'duree_secondes': passage.duree_secondes,
        'reprise': reprise,
        'restant_secondes': max(passage.duree_secondes - passage.temps, 0),
        # Corrections déjà données (reprise) : la réponse verrouillée et son explication.
        'verifiees': [_correction(q, reponses[str(q.id)]) for q in questions if str(q.id) in reponses],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_en_cours(request):
    """Quiz commencés, pas encore envoyés : [{chapitre, niveau, repondues, total, maj}] (« Reprendre »)."""
    _oublier_passages_anciens(request.user)
    return Response([{'chapitre': p.chapter_id, 'niveau': p.class_level_id, 'repondues': len(p.reponses or {}),
                      'total': len(p.questions or []), 'maj': p.maj.isoformat()}
                     for p in QuizEnCours.objects.filter(user=request.user).order_by('-maj')])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_quiz(request, chapter_id):
    """Fin du passage en cours (chapitre, niveau) → score, correction, bilan par théorème.

    Toutes les questions du passage sont notées (14/10/2026 : avant, seules celles envoyées l'étaient, et n'envoyer que
    ses bonnes réponses donnait 100 %) : la réponse verrouillée à la correction d'abord, sinon celle envoyée, sinon
    sans réponse (fausse). Sans passage en cours (expiré, déjà envoyé) : 409. La correction est figée dans le résultat
    (dernière_correction), le passage supprimé."""
    serializer = QuizSubmissionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    answers = serializer.validated_data['answers']
    time_spent = serializer.validated_data.get('time_spent', 0)
    niveau = tirage.niveau_demande(request)
    if niveau is None:
        return Response({'error': 'Invalid questions'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        passage = (QuizEnCours.objects.select_for_update()
                   .filter(user=request.user, chapter_id=chapter_id, class_level=niveau).first())
        if passage is None:
            return Response({'error': 'Aucun quiz en cours : recommence le quiz.'}, status=status.HTTP_409_CONFLICT)
        questions = _questions_du_passage(passage)
        if not questions:
            passage.delete()
            return Response({'error': 'Invalid questions'}, status=status.HTTP_400_BAD_REQUEST)
        verrou = passage.reponses or {}
        finales = {}
        for q in questions:
            r = reponse_valide(verrou.get(str(q.id), answers.get(str(q.id), -1)), len(q.options))
            finales[str(q.id)] = -1 if r is None else r
        # Temps : jamais plus que le temps réel écoulé depuis le début du passage.
        ecoule = int((timezone.now() - passage.debut).total_seconds())
        time_spent = min(max(time_spent, passage.temps), ecoule)

        # Score pondéré par la difficulté (jamais montrée aux élèves).
        points = {'easy': 1, 'medium': 2, 'hard': 3}
        max_score = sum(points.get(q.difficulty, 1) for q in questions)
        score = sum(points.get(q.difficulty, 1) for q in questions if q.est_juste(finales[str(q.id)]))
        # Bilan par théorème : ce que l'élève maîtrise, ce qu'il doit revoir (tirage.bilan).
        par_theoreme = tirage.bilan(questions, finales, tirage.disponibles(niveau, chapter_id))
        correction = [_correction(q, finales[str(q.id)]) for q in questions]

        # Un résultat par (chapitre, niveau) ; un nouveau passage garde le score précédent (« 40 % → 80 % »).
        # Un résultat d'avant le découpage par niveau (sans niveau) est repris par ce passage.
        mine = SkillAssessment.objects.select_for_update().filter(user=request.user, chapter_id=chapter_id)
        assessment = mine.filter(class_level=niveau).first() or mine.filter(class_level__isnull=True).first()
        if assessment is None:
            assessment = SkillAssessment.objects.create(
                user=request.user, chapter_id=chapter_id, class_level=niveau, score=score, max_score=max_score,
                answers=finales, time_spent=time_spent, par_theoreme=par_theoreme, derniere_correction=correction)
        else:
            assessment.class_level = niveau
            assessment.previous_score, assessment.previous_max = assessment.score, assessment.max_score
            assessment.attempts = (assessment.attempts or 1) + 1
            assessment.score, assessment.max_score = score, max_score
            assessment.answers, assessment.time_spent = finales, time_spent
            assessment.par_theoreme = par_theoreme
            assessment.derniere_correction = correction
            assessment.save()
        passage.delete()

    from apps.users.maitrise import forget
    forget(request.user.id)  # « Ma progression » : le quiz compte dans la maîtrise du chapitre
    result = SkillAssessmentSerializer(assessment, context={'request': request}).data
    result['correction'] = correction
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_answer(request, question_id):
    """Correction d'une question dès que l'élève a répondu : {"answer": i, "temps": s} → bonne réponse, explication,
    théorèmes ; question à plusieurs bonnes réponses : {"answer": [i, j]} (index distincts, juste ssi exactement
    l'ensemble des bonnes réponses). Seulement pour une question de SON passage en cours (sinon 404 : avant le 14/10/2026, n'importe quelle
    question pouvait être corrigée, donc toutes les bonnes réponses récupérées) ; la première réponse est verrouillée
    (une nouvelle demande renvoie la même correction). `temps` : minuteur utilisé, pour reprendre plus tard."""
    answer = request.data.get('answer')
    with transaction.atomic():
        passage = next((p for p in QuizEnCours.objects.select_for_update().filter(user=request.user)
                        if question_id in (p.questions or [])), None)
        # Une question retirée entre-temps (à relire, désactivée) n'est plus corrigée.
        q = (SkillQuestion.objects.filter(pk=question_id, is_active=True, a_relire=False)
             .prefetch_related('theorems').first() if passage is not None else None)
        if q is None:
            return Response({'error': 'Question introuvable'}, status=status.HTTP_404_NOT_FOUND)
        reponses = dict(passage.reponses or {})
        if str(q.id) not in reponses:
            propre = reponse_valide(answer, len(q.options))
            if propre is None:
                return Response({'answer': 'Réponse invalide'}, status=status.HTTP_400_BAD_REQUEST)
            reponses[str(q.id)] = propre
            passage.reponses = reponses
        temps = request.data.get('temps')
        if isinstance(temps, int) and not isinstance(temps, bool) and temps >= 0:
            ecoule = int((timezone.now() - passage.debut).total_seconds())
            passage.temps = max(passage.temps, min(temps, ecoule, passage.duree_secondes))
        passage.save()
    return Response(_correction(q, reponses[str(q.id)]))


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
    """Dernier résultat de l'élève sur le quiz (chapitre, niveau), avec la correction figée de ce passage."""
    niveau = tirage.niveau_demande(request)
    assessment = (SkillAssessment.objects.filter(user=request.user, chapter_id=chapter_id, class_level=niveau).first()
                  or SkillAssessment.objects.filter(user=request.user, chapter_id=chapter_id,
                                                    class_level__isnull=True).first())
    if assessment is None:
        return Response(
            {'error': 'No assessment found for this chapter'},
            status=status.HTTP_404_NOT_FOUND
        )
    data = SkillAssessmentSerializer(assessment, context={'request': request}).data
    data['correction'] = assessment.derniere_correction or []  # dernier passage, figé (« Voir mon dernier résultat »)
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_new(request):
    """Quiz sortis depuis moins de 14 jours : [{niveau, chapitre, depuis}] (étiquette « Nouveau », annonces.py)."""
    from .annonces import nouveaux
    return Response([{'niveau': lv, 'chapitre': ch, 'depuis': d.isoformat()} for (ch, lv), d in nouveaux().items()])
