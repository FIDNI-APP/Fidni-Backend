"""Pilotage › Quiz (administrateurs) : écrire les questions du quiz de chaque chapitre, puis le mettre en ligne.

Un quiz de chapitre = ses questions QCM actives (SkillQuestion.is_active). Une question créée ici est un
brouillon ; « Mettre en ligne » active toutes celles du chapitre, et le quiz apparaît alors aux élèves
(page /skill-iq, qui lit /api/skill-assessments/available/). Chaque passage pose toutes les questions (30 au plus).

Un quiz = (chapitre, niveau) depuis le 13/10/2026 : jamais partagé entre deux niveaux (SkillQuestion.class_level) ;
chaque appel précise le niveau (« niveau »), sauf pour un chapitre d’un seul niveau.

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

from apps.caracteristics.models import Chapter, ClassLevel
from apps.users.admin_dashboard import IsSuperuser

from .annonces import annoncer, marquer_en_ligne
from .models import SkillAssessment, SkillQuestion
from .tirage import QUESTIONS_PAR_QUIZ

MIN_EN_LIGNE = 5  # en dessous, le quiz serait trop court : la mise en ligne est refusée
DIFFICULTES = {k for k, _ in SkillQuestion.DIFFICULTY_CHOICES}
TEXTE_MAX = 2000


def _question(q):
    return {'id': q.id, 'question': q.question, 'options': q.options, 'correct_answer': q.correct_answer,
            'correct_answers': q.bonnes(),
            'difficulty': q.difficulty, 'explanation': q.explanation, 'en_ligne': q.is_active,
            'source': q.source, 'a_relire': q.a_relire, 'motif': q.motif, 'updated_at': q.updated_at.isoformat(),
            'niveau': q.class_level_id,
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


def _entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _bonnes(data, opts, err):
    """Bonne(s) réponse(s) → (correct_answer, correct_answers). « correct_answers » (liste d'index, 16/10/2026) :
    plusieurs bonnes réponses (une seule cochée = question à une réponse) ; sinon « correct_answer » (un index)."""
    cas = data.get('correct_answers')
    if cas is not None and cas != []:
        if (not isinstance(cas, list) or not all(_entier(i) and 0 <= i < len(opts) for i in cas)
                or len(set(cas)) != len(cas)):
            err['correct_answers'] = 'Coche les bonnes réponses (parmi les réponses, sans doublon).'
            return None, []
        if len(cas) >= len(opts):
            err['correct_answers'] = 'Il faut au moins une mauvaise réponse.'
            return None, []
        cas = sorted(cas)
        return cas[0], (cas if len(cas) > 1 else [])
    ca = data.get('correct_answer')
    if not _entier(ca) or not 0 <= ca < len(opts):
        err['correct_answer'] = 'Coche la bonne réponse.'
    return ca, []


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
    if not partiel or any(k in data for k in ('options', 'correct_answer', 'correct_answers')):
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
            out['correct_answer'], out['correct_answers'] = _bonnes(data, opts, err)
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




def _niveau(request, ch=None):
    """Niveau du quiz : « niveau » (requête ou corps) ; à défaut, le seul niveau du chapitre. None sinon."""
    brut = request.query_params.get('niveau') or (request.data.get('niveau') if request.method != 'GET' else None)
    if str(brut or '').isdigit():
        lv = ClassLevel.objects.filter(pk=int(brut)).first()
        if lv is not None:
            return lv
    if ch is not None:
        seuls = list(ch.class_levels.all()[:2])
        if len(seuls) == 1:
            return seuls[0]
    return None


NIVEAU_MANQUANT = {'niveau': 'Choisis le niveau du quiz.'}


def _en_ligne(chapitre_id, niveau):
    """Le quiz (chapitre, niveau) est-il visible des élèves (au moins une question validée active) ?"""
    return SkillQuestion.objects.filter(chapter_id=chapitre_id, class_level=niveau, is_active=True,
                                        a_relire=False).exists()


def _chapitres_en_ligne(niveau):
    """Chapitres de ce niveau qui ont au moins un contenu (exercice, leçon, examen) en ligne à ce niveau."""
    return (Chapter.objects.filter(class_levels=niveau, content_items__class_levels=niveau)
            .distinct().order_by('subfield__name', 'name'))


@api_view(['GET'])
@permission_classes([IsSuperuser])
def chapitres(request):
    """Chapitres d'un niveau (?niveau=<id>) avec l'état du quiz de ce niveau (un quiz par chapitre et par niveau)."""
    niveau = _niveau(request)
    if niveau is None:
        return Response(NIVEAU_MANQUANT, status=status.HTTP_400_BAD_REQUEST)
    du_niveau = Q(skill_questions__class_level=niveau)
    qs = (Chapter.objects.select_related('subfield').filter(class_levels=niveau).order_by('subfield__name', 'name')
          .annotate(
              total=Count('skill_questions', filter=du_niveau, distinct=True),
              actives=Count('skill_questions', filter=du_niveau & Q(skill_questions__is_active=True), distinct=True),
              a_relire=Count('skill_questions', filter=du_niveau & Q(skill_questions__a_relire=True), distinct=True),
          ).distinct())
    passages = dict(SkillAssessment.objects.filter(class_level=niveau).values_list('chapter_id').annotate(n=Count('id')))
    # contenus : le chapitre a-t-il un contenu en ligne à ce niveau (ceux qu'exporte quiz_constats) ?
    avec_contenu = set(_chapitres_en_ligne(niveau).values_list('id', flat=True))
    return Response([{
        'id': c.id, 'name': c.name, 'domaine': c.subfield.name if c.subfield else '',
        'total': c.total, 'en_ligne': c.actives, 'brouillons': c.total - c.actives, 'a_relire': c.a_relire,
        'passages': passages.get(c.id, 0), 'contenus': c.id in avec_contenu,
    } for c in qs])


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def chapitre(request, pk):
    """GET : les questions du quiz (chapitre, niveau). POST : une nouvelle question de ce quiz (brouillon)."""
    ch = get_object_or_404(Chapter, pk=pk)
    niveau = _niveau(request, ch)
    if niveau is None:
        return Response(NIVEAU_MANQUANT, status=status.HTTP_400_BAD_REQUEST)
    if request.method == 'POST':
        champs, err = _valider(request.data)
        ths = _theoremes(ch, request.data.get('theoremes', []), err)
        if err:
            return Response(err, status=status.HTTP_400_BAD_REQUEST)
        champs.setdefault('is_active', False)
        q = SkillQuestion.objects.create(chapter=ch, class_level=niveau, **champs)
        q.theorems.set(ths)
        return Response(_question(q), status=status.HTTP_201_CREATED)
    from apps.caracteristics.models import Theorem
    questions = (SkillQuestion.objects.filter(chapter=ch, class_level=niveau).prefetch_related('theorems')
                 .order_by('id'))
    theoremes = (Theorem.objects.filter(chapters=ch).filter(Q(class_levels=niveau) | Q(class_levels__isnull=True))
                 .prefetch_related('class_levels').distinct().order_by('name'))
    return Response({
        'chapitre': {'id': ch.id, 'name': ch.name, 'domaine': ch.subfield.name if ch.subfield_id else '',
                     'niveau': {'id': niveau.id, 'name': niveau.name},
                     'niveaux': list(ch.class_levels.values_list('name', flat=True)),
                     'theoremes': [{'id': th.id, 'name': th.name,
                                    'niveaux': [lv.name for lv in th.class_levels.all()]} for th in theoremes]},
        'questions': [_question(q) for q in questions],
        'par_quiz': QUESTIONS_PAR_QUIZ, 'min_en_ligne': MIN_EN_LIGNE,
        'passages': SkillAssessment.objects.filter(chapter=ch, class_level=niveau).count(),
    })


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperuser])
def question(request, pk):
    q = get_object_or_404(SkillQuestion.objects.select_related('chapter', 'class_level'), pk=pk)
    if request.method == 'DELETE':
        q.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = dict(request.data)
    data.pop('niveau', None)  # une question ne change pas de quiz
    if 'valider' in data:
        if data.pop('valider') is not True:
            return Response({'valider': 'true attendu.'}, status=status.HTTP_400_BAD_REQUEST)
        if q.a_relire:  # question importée relue : publiable, en ligne aussitôt si son quiz l'est
            data.setdefault('en_ligne', _en_ligne(q.chapter_id, q.class_level))
            q.a_relire = False
    elif data.get('en_ligne') is True:
        q.a_relire = False  # la mettre en ligne soi-même vaut validation
    bonne_envoyee = 'correct_answer' in data or 'correct_answers' in data
    if bonne_envoyee and 'options' not in data:
        data['options'] = q.options  # la bonne réponse se contrôle contre les réponses existantes
    if 'options' in data and not bonne_envoyee:
        data['correct_answer'], data['correct_answers'] = q.correct_answer, q.bonnes()
    champs, err = _valider(data, partiel=True)
    ths = _theoremes(q.chapter, data['theoremes'], err) if 'theoremes' in data else None
    if err:
        return Response(err, status=status.HTTP_400_BAD_REQUEST)
    etait = _en_ligne(q.chapter_id, q.class_level)
    for k, v in champs.items():
        setattr(q, k, v)
    q.save()
    if ths is not None:
        q.theorems.set(ths)
    if q.is_active and not q.a_relire:
        marquer_en_ligne(SkillQuestion.objects.filter(pk=q.pk))
        if not etait:
            annoncer(q.chapter, q.class_level)
    return Response(_question(q))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def publier(request, pk):
    """{"niveau": id, "en_ligne": true} : le quiz (chapitre, niveau) en ligne (5 questions validées au moins) ;
    false : quiz retiré. Les quiz des autres niveaux du chapitre ne bougent pas."""
    ch = get_object_or_404(Chapter, pk=pk)
    niveau = _niveau(request, ch)
    if niveau is None:
        return Response(NIVEAU_MANQUANT, status=status.HTTP_400_BAD_REQUEST)
    en_ligne = request.data.get('en_ligne')
    if not isinstance(en_ligne, bool):
        return Response({'en_ligne': 'true ou false.'}, status=status.HTTP_400_BAD_REQUEST)
    qs = SkillQuestion.objects.filter(chapter=ch, class_level=niveau)
    if en_ligne:
        qs = qs.filter(a_relire=False)  # les questions importées non validées restent hors ligne
    if en_ligne and qs.count() < MIN_EN_LIGNE:
        attente = SkillQuestion.objects.filter(chapter=ch, class_level=niveau, a_relire=True).count()
        return Response({'detail': f'{MIN_EN_LIGNE} questions validées au moins pour mettre un quiz en ligne '
                                   f'(chaque passage les pose toutes, {QUESTIONS_PAR_QUIZ} au plus).'
                                   + (f' {attente} question(s) importée(s) attendent ta relecture.' if attente else '')},
                        status=status.HTTP_400_BAD_REQUEST)
    etait = _en_ligne(ch.id, niveau)
    n = qs.update(is_active=en_ligne)
    if en_ligne:
        marquer_en_ligne(qs)
        if not etait:
            annoncer(ch, niveau)  # le quiz sort : les élèves de ce niveau sont prévenus (cloche)
    else:
        qs.update(en_ligne_le=None)  # remis en ligne plus tard, il sera de nouveau « Nouveau »
    return Response({'en_ligne': en_ligne, 'questions': n})


def _ids(valeur):
    return isinstance(valeur, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in valeur)


@api_view(['POST'])
@permission_classes([IsSuperuser])
def valider(request, pk):
    """{"niveau": id, "ids": [...]} : valide ces questions importées, relues (sans « ids » : toutes celles du quiz)."""
    ch = get_object_or_404(Chapter, pk=pk)
    niveau = _niveau(request, ch)
    if niveau is None:
        return Response(NIVEAU_MANQUANT, status=status.HTTP_400_BAD_REQUEST)
    qs = SkillQuestion.objects.filter(chapter=ch, class_level=niveau, a_relire=True)
    if 'ids' in request.data:
        if not _ids(request.data['ids']):
            return Response({'ids': 'Liste d’identifiants attendue.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = qs.filter(id__in=request.data['ids'])
    en_ligne = _en_ligne(ch.id, niveau)
    ids = list(qs.values_list('id', flat=True))
    n = qs.update(a_relire=False, is_active=en_ligne)
    if en_ligne:
        marquer_en_ligne(SkillQuestion.objects.filter(id__in=ids))
    return Response({'validees': n, 'en_ligne': en_ligne})
