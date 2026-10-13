"""Pilotage › Quiz (administrateurs) : écrire les questions du quiz de chaque chapitre, puis le mettre en ligne.

Un quiz de chapitre = ses questions QCM actives (SkillQuestion.is_active). Une question créée ici est un
brouillon ; « Mettre en ligne » active toutes celles du chapitre, et le quiz apparaît alors aux élèves
(page /skill-iq, qui lit /api/skill-assessments/available/). Chaque passage tire 10 questions au hasard.

Questions importées (13/10/2026, commande `quiz_importer`, rédigées par Claude d'après les résultats des élèves) :
brouillons « à relire » (a_relire). « Mettre en ligne » les laisse de côté ; seule la validation de
l'administrateur (une à une, ou celles qu'il a relues) les rend publiables — en ligne aussitôt si le quiz du
chapitre l'est déjà.
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
            'source': q.source, 'a_relire': q.a_relire, 'motif': q.motif, 'updated_at': q.updated_at.isoformat(),
            'theoremes': [{'id': th.id, 'name': th.name} for th in q.theorems.all()]}


def _theoremes(ch, valeur, err):
    """Ids de théorèmes du chapitre (« theoremes ») → liste de Theorem ; une erreur sinon."""
    from apps.caracteristics.models import Theorem
    if not isinstance(valeur, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in valeur):
        err['theoremes'] = 'Liste de théorèmes attendue.'
        return []
    ths = list(Theorem.objects.filter(chapters=ch, id__in=valeur).distinct())
    if len(ths) != len(set(valeur)):
        err['theoremes'] = 'Théorème inconnu pour ce chapitre.'
    return ths


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


def _en_ligne(chapitre_id):
    """Le quiz du chapitre est-il visible des élèves (au moins une question validée active) ?"""
    return SkillQuestion.objects.filter(chapter_id=chapitre_id, is_active=True, a_relire=False).exists()


def _chapitres_en_ligne(niveau):
    """Chapitres de ce niveau qui ont au moins un contenu (exercice, leçon, examen) en ligne à ce niveau."""
    return (Chapter.objects.filter(class_levels=niveau, content_items__class_levels=niveau)
            .distinct().order_by('subfield__name', 'name'))


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
        a_relire=Count('skill_questions', filter=Q(skill_questions__a_relire=True), distinct=True),
        passages=Count('assessments', distinct=True),
    ).distinct()
    # contenus : le chapitre a-t-il un contenu en ligne à ce niveau (ceux qu'exporte quiz_constats) ?
    avec_contenu = (set(_chapitres_en_ligne(int(niveau)).values_list('id', flat=True))
                    if niveau and niveau.isdigit() else None)
    return Response([{
        'id': c.id, 'name': c.name, 'domaine': c.subfield.name if c.subfield else '',
        'total': c.total, 'en_ligne': c.actives, 'brouillons': c.total - c.actives, 'a_relire': c.a_relire,
        'passages': c.passages, 'contenus': avec_contenu is None or c.id in avec_contenu,
    } for c in qs])


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def chapitre(request, pk):
    """GET : les questions du chapitre. POST : une nouvelle question (brouillon)."""
    ch = get_object_or_404(Chapter, pk=pk)
    if request.method == 'POST':
        champs, err = _valider(request.data)
        ths = _theoremes(ch, request.data.get('theoremes', []), err)
        if err:
            return Response(err, status=status.HTTP_400_BAD_REQUEST)
        champs.setdefault('is_active', False)
        q = SkillQuestion.objects.create(chapter=ch, **champs)
        q.theorems.set(ths)
        return Response(_question(q), status=status.HTTP_201_CREATED)
    from apps.caracteristics.models import Theorem
    questions = SkillQuestion.objects.filter(chapter=ch).prefetch_related('theorems').order_by('id')
    theoremes = Theorem.objects.filter(chapters=ch).prefetch_related('class_levels').distinct().order_by('name')
    return Response({
        'chapitre': {'id': ch.id, 'name': ch.name, 'domaine': ch.subfield.name if ch.subfield_id else '',
                     'niveaux': list(ch.class_levels.values_list('name', flat=True)),
                     'theoremes': [{'id': th.id, 'name': th.name,
                                    'niveaux': [lv.name for lv in th.class_levels.all()]} for th in theoremes]},
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
    if 'valider' in data:
        if data.pop('valider') is not True:
            return Response({'valider': 'true attendu.'}, status=status.HTTP_400_BAD_REQUEST)
        if q.a_relire:  # question importée relue : publiable, en ligne aussitôt si le quiz du chapitre l'est
            data.setdefault('en_ligne', _en_ligne(q.chapter_id))
            q.a_relire = False
    elif data.get('en_ligne') is True:
        q.a_relire = False  # la mettre en ligne soi-même vaut validation
    if 'correct_answer' in data and 'options' not in data:
        data['options'] = q.options  # la bonne réponse se contrôle contre les réponses existantes
    if 'options' in data and 'correct_answer' not in data:
        data['correct_answer'] = q.correct_answer
    champs, err = _valider(data, partiel=True)
    ths = _theoremes(q.chapter, data['theoremes'], err) if 'theoremes' in data else None
    if err:
        return Response(err, status=status.HTTP_400_BAD_REQUEST)
    for k, v in champs.items():
        setattr(q, k, v)
    q.save()
    if ths is not None:
        q.theorems.set(ths)
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
    if en_ligne:
        qs = qs.filter(a_relire=False)  # les questions importées non validées restent hors ligne
    if en_ligne and qs.count() < MIN_EN_LIGNE:
        attente = SkillQuestion.objects.filter(chapter=ch, a_relire=True).count()
        return Response({'detail': f'{MIN_EN_LIGNE} questions validées au moins pour mettre un quiz en ligne '
                                   f'(chaque passage en tire {QUESTIONS_PAR_QUIZ} au hasard).'
                                   + (f' {attente} question(s) importée(s) attendent ta relecture.' if attente else '')},
                        status=status.HTTP_400_BAD_REQUEST)
    n = qs.update(is_active=en_ligne)
    return Response({'en_ligne': en_ligne, 'questions': n})


def _ids(valeur):
    return isinstance(valeur, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in valeur)


@api_view(['POST'])
@permission_classes([IsSuperuser])
def valider(request, pk):
    """{"ids": [...]} : valide ces questions importées, relues (sans « ids » : toutes celles du chapitre)."""
    ch = get_object_or_404(Chapter, pk=pk)
    qs = SkillQuestion.objects.filter(chapter=ch, a_relire=True)
    if 'ids' in request.data:
        if not _ids(request.data['ids']):
            return Response({'ids': 'Liste d’identifiants attendue.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = qs.filter(id__in=request.data['ids'])
    en_ligne = _en_ligne(ch.id)
    n = qs.update(a_relire=False, is_active=en_ligne)
    return Response({'validees': n, 'en_ligne': en_ligne})
