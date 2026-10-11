"""Pilotage › Quiz (administrateurs) : écrire les questions du quiz de chaque chapitre, puis le mettre en ligne.

Un quiz de chapitre = ses questions QCM actives (SkillQuestion.is_active). Une question créée ici est un
brouillon ; « Mettre en ligne » active toutes celles du chapitre, et le quiz apparaît alors aux élèves
(page /skill-iq, qui lit /api/skill-assessments/available/). Chaque passage tire 10 questions au hasard.
"""
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.caracteristics.models import Chapter
from apps.users.admin_dashboard import IsSuperuser

from .models import SkillAssessment, SkillQuestion

QUESTIONS_PAR_QUIZ = 10
MIN_EN_LIGNE = 5  # en dessous, le quiz serait trop court : la mise en ligne est refusée
DIFFICULTES = {k for k, _ in SkillQuestion.DIFFICULTY_CHOICES}
TEXTE_MAX = 2000


def _question(q):
    return {'id': q.id, 'question': q.question, 'options': q.options, 'correct_answer': q.correct_answer,
            'difficulty': q.difficulty, 'explanation': q.explanation, 'en_ligne': q.is_active,
            'updated_at': q.updated_at.isoformat()}


def _valider(data, partiel=False):
    """→ (champs propres, erreurs) ; `partiel` : seuls les champs envoyés sont contrôlés (modification)."""
    out, err = {}, {}
    if not partiel or 'question' in data:
        texte = str(data.get('question') or '').strip()
        if not texte:
            err['question'] = 'Écris la question.'
        elif len(texte) > TEXTE_MAX:
            err['question'] = f'{TEXTE_MAX} caractères au plus.'
        out['question'] = texte
    if not partiel or 'options' in data or 'correct_answer' in data:
        opts = data.get('options')
        if not isinstance(opts, list):
            err['options'] = 'Liste de réponses attendue.'
        else:
            opts = [str(o).strip() for o in opts]
            if len(opts) < 2 or len(opts) > 6 or any(not o for o in opts):
                err['options'] = 'Entre 2 et 6 réponses, aucune vide.'
            elif len(set(opts)) != len(opts):
                err['options'] = 'Deux réponses identiques.'
            out['options'] = opts
            ca = data.get('correct_answer')
            if not isinstance(ca, int) or isinstance(ca, bool) or not 0 <= ca < len(opts):
                err['correct_answer'] = 'Coche la bonne réponse.'
            out['correct_answer'] = ca
    if 'difficulty' in data or not partiel:
        d = data.get('difficulty') or 'medium'
        if d not in DIFFICULTES:
            err['difficulty'] = 'easy, medium ou hard.'
        out['difficulty'] = d
    if 'explanation' in data or not partiel:
        out['explanation'] = str(data.get('explanation') or '').strip()[:TEXTE_MAX]
    if 'en_ligne' in data:
        if not isinstance(data['en_ligne'], bool):
            err['en_ligne'] = 'true ou false.'
        out['is_active'] = data['en_ligne']
    return out, err


@api_view(['GET'])
@permission_classes([IsSuperuser])
def chapitres(request):
    """Chapitres d'un niveau (?niveau=<id>, sinon tous), avec l'état de leur quiz."""
    qs = Chapter.objects.select_related('subfield').order_by('subfield__name', 'name')
    niveau = request.query_params.get('niveau')
    if niveau and niveau.isdigit():
        qs = qs.filter(class_levels__id=int(niveau))
    qs = qs.annotate(
        total=Count('skill_questions', distinct=True),
        actives=Count('skill_questions', filter=Q(skill_questions__is_active=True), distinct=True),
        passages=Count('assessments', distinct=True),
    ).distinct()
    return Response([{
        'id': c.id, 'name': c.name, 'domaine': c.subfield.name if c.subfield else '',
        'total': c.total, 'en_ligne': c.actives, 'brouillons': c.total - c.actives, 'passages': c.passages,
    } for c in qs])


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def chapitre(request, pk):
    """GET : les questions du chapitre. POST : une nouvelle question (brouillon)."""
    ch = get_object_or_404(Chapter, pk=pk)
    if request.method == 'POST':
        champs, err = _valider(request.data)
        if err:
            return Response(err, status=status.HTTP_400_BAD_REQUEST)
        champs.setdefault('is_active', False)
        q = SkillQuestion.objects.create(chapter=ch, **champs)
        return Response(_question(q), status=status.HTTP_201_CREATED)
    questions = SkillQuestion.objects.filter(chapter=ch).order_by('id')
    return Response({
        'chapitre': {'id': ch.id, 'name': ch.name, 'domaine': ch.subfield.name if ch.subfield_id else '',
                     'niveaux': list(ch.class_levels.values_list('name', flat=True))},
        'questions': [_question(q) for q in questions],
        'par_quiz': QUESTIONS_PAR_QUIZ, 'min_en_ligne': MIN_EN_LIGNE,
        'passages': SkillAssessment.objects.filter(chapter=ch).count(),
    })


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperuser])
def question(request, pk):
    q = get_object_or_404(SkillQuestion, pk=pk)
    if request.method == 'DELETE':
        q.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = dict(request.data)
    if 'correct_answer' in data and 'options' not in data:
        data['options'] = q.options  # la bonne réponse se contrôle contre les réponses existantes
    if 'options' in data and 'correct_answer' not in data:
        data['correct_answer'] = q.correct_answer
    champs, err = _valider(data, partiel=True)
    if err:
        return Response(err, status=status.HTTP_400_BAD_REQUEST)
    for k, v in champs.items():
        setattr(q, k, v)
    q.save()
    return Response(_question(q))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def publier(request, pk):
    """{"en_ligne": true} : toutes les questions du chapitre en ligne (5 au moins) ; false : quiz retiré."""
    ch = get_object_or_404(Chapter, pk=pk)
    en_ligne = request.data.get('en_ligne')
    if not isinstance(en_ligne, bool):
        return Response({'en_ligne': 'true ou false.'}, status=status.HTTP_400_BAD_REQUEST)
    qs = SkillQuestion.objects.filter(chapter=ch)
    if en_ligne and qs.count() < MIN_EN_LIGNE:
        return Response({'detail': f'{MIN_EN_LIGNE} questions au moins pour mettre un quiz en ligne '
                                   f'(chaque passage en tire {QUESTIONS_PAR_QUIZ} au hasard).'},
                        status=status.HTTP_400_BAD_REQUEST)
    n = qs.update(is_active=en_ligne)
    return Response({'en_ligne': en_ligne, 'questions': n})
