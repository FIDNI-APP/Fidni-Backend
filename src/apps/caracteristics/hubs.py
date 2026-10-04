"""Pages par niveau et par chapitre (« hubs ») : /exercises/niveau/2eme-bac-sm/limites-et-continuite.

Les élèves cherchent « exercices corrigés 2 bac sm » ou « limites et continuité 2 bac sm » : une page
dont le titre et le texte répondent exactement à cette recherche, avec les liens vers chaque contenu,
remonte bien mieux que la liste générale filtrée par un paramètre (?classLevels=3, ignoré par Google).

Une seule source pour les textes : l'API (/api/hubs/, lue par l'application) et la page pré-remplie
pour les moteurs de recherche (config/seo.py) disent exactement la même chose.
Une page sans aucun contenu reste consultable mais n'est ni indexée ni dans le sitemap.
"""
from django.db.models import Max
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.caracteristics.models import Chapter, ClassLevel

SECTION_TYPE = {'exercises': 'exercise', 'lessons': 'lesson', 'exams': 'exam'}
SECTION_LABEL = {'exercises': 'Exercices corrigés', 'lessons': 'Cours', 'exams': 'Devoirs et examens corrigés'}

# Comment les élèves écrivent leur niveau dans Google : (forme courte, formes longues).
LEVEL_WORDS = {
    'Tronc commun Sciences': ('TCS', 'Tronc commun scientifique, TC BIOF'),
    '1ère Bac SM': ('1 Bac SM', '1ère année Bac Sciences Mathématiques, 1BAC SM BIOF'),
    '2ème Bac SM': ('2 Bac SM', '2ème année Bac Sciences Mathématiques A et B, 2BAC SM BIOF'),
    '2ème Bac PC': ('2 Bac PC', '2ème année Bac Sciences Physiques, 2BAC PC BIOF'),
}


def slug(name):
    return slugify(name)


def hub_url(section, level, chapter=None):
    path = f'/{section}/niveau/{slug(level.name)}'
    return f'{path}/{slug(chapter.name)}' if chapter else path


def _contents(kind, level, chapter=None):
    from apps.things.models import Content
    qs = Content.objects.filter(type=kind, class_levels=level)
    if chapter is not None:
        qs = qs.filter(chapters=chapter)
    return qs.distinct()


def _plural(n, one, many):
    return f'{n} {one if n == 1 else many}'


def _texts(section, level, chapter, count):
    """Titre, description, H1 et introduction, avec les mots que tapent les élèves."""
    short, long = LEVEL_WORDS.get(level.name, (level.name, level.name))
    lv = level.name
    alias = f'{lv} ({short})' if short != lv else lv
    if chapter is None:
        if section == 'exercises':
            title = f'Exercices corrigés de maths {alias} – Maroc | Fidni'
            h1 = f'Exercices corrigés de maths – {lv}'
            intro = (f'Les exercices de mathématiques corrigés du {lv} ({long}), programme marocain, '
                     f'classés par chapitre. Chaque exercice a sa solution détaillée, étape par étape, '
                     f'et tu peux t’auto-évaluer question par question.')
            description = (f'{_plural(count, "exercice de maths corrigé", "exercices de maths corrigés")} pour le {alias}, '
                           f'programme marocain, classés par chapitre, avec solutions détaillées. Gratuit.')
        elif section == 'lessons':
            title = f'Cours de maths {alias} – Maroc | Fidni'
            h1 = f'Cours de maths – {lv}'
            intro = (f'Les cours de mathématiques du {lv} ({long}), chapitre par chapitre : définitions, '
                     f'théorèmes, propriétés, méthodes et exemples, conformes au programme marocain.')
            description = (f'{_plural(count, "cours de maths", "cours de maths")} pour le {alias} : définitions, théorèmes, '
                           f'méthodes et exemples, programme marocain. À lire en ligne ou à imprimer. Gratuit.')
        else:
            title = f'Devoirs surveillés et examens corrigés {alias} – Maroc | Fidni'
            h1 = f'Devoirs surveillés et examens corrigés – {lv}'
            intro = (f'Des devoirs surveillés et sujets d’examen de mathématiques du {lv} ({long}), avec leur '
                     f'barème et un corrigé détaillé. Entraîne-toi en conditions réelles avec l’épreuve chronométrée.')
            description = (f'{_plural(count, "devoir ou examen de maths corrigé", "devoirs et examens de maths corrigés")} '
                           f'pour le {alias} : barème, durée et corrigé détaillé, programme marocain.')
    else:
        ch = chapter.name
        if section == 'exercises':
            title = f'{ch} – Exercices corrigés {alias} | Fidni'
            h1 = f'{ch} : exercices corrigés – {lv}'
            intro = (f'Exercices corrigés sur le chapitre « {ch} » du {lv} ({long}), programme marocain. '
                     f'Énoncés et solutions détaillées, de l’application directe aux exercices de type Bac.')
            description = (f'{_plural(count, "exercice corrigé", "exercices corrigés")} sur {ch} pour le {alias} : '
                           f'énoncés et solutions détaillées étape par étape, programme marocain. Gratuit.')
        elif section == 'lessons':
            title = f'{ch} – Cours de maths {alias} | Fidni'
            h1 = f'{ch} : cours – {lv}'
            intro = (f'Le cours « {ch} » du {lv} ({long}) : définitions, théorèmes, propriétés et méthodes, '
                     f'avec des exemples, conformes au programme marocain.')
            description = (f'Cours de maths sur {ch} pour le {alias} : définitions, théorèmes, propriétés, méthodes '
                           f'et exemples, programme marocain. Gratuit.')
        else:
            title = f'{ch} – Devoirs surveillés corrigés {alias} | Fidni'
            h1 = f'{ch} : devoirs et examens corrigés – {lv}'
            intro = (f'Devoirs surveillés et examens de mathématiques portant sur « {ch} » au {lv} ({long}), '
                     f'avec barème et corrigé détaillé.')
            description = (f'{_plural(count, "devoir corrigé", "devoirs et examens corrigés")} sur {ch} pour le {alias} : '
                           f'barème, durée et corrigé détaillé, programme marocain.')
    return {'title': title, 'h1': h1, 'intro': intro, 'description': description}


def _level_chapters(kind, level):
    """Chapitres du niveau qui ont au moins un contenu de ce type, dans l'ordre du programme."""
    from apps.things.models import Content
    level_chapters = set(Chapter.objects.filter(class_levels=level).values_list('id', flat=True))
    counts = {}
    for content in Content.objects.filter(type=kind, class_levels=level).distinct().prefetch_related('chapters'):
        for ch in content.chapters.all():
            if ch.id in level_chapters:
                counts[ch.id] = counts.get(ch.id, 0) + 1
    chapters = Chapter.objects.filter(id__in=counts).order_by('id')
    return [(ch, counts[ch.id]) for ch in chapters]


def resolve(section, level_slug, chapter_slug=None):
    """Tout ce qu'il faut pour afficher un hub, ou None si le niveau ou le chapitre n'existe pas."""
    kind = SECTION_TYPE.get(section)
    if kind is None:
        return None
    level = next((lv for lv in ClassLevel.objects.all() if slug(lv.name) == level_slug), None)
    if level is None:
        return None
    chapter = None
    if chapter_slug:
        chapter = next((ch for ch in Chapter.objects.filter(class_levels=level) if slug(ch.name) == chapter_slug), None)
        if chapter is None:
            return None

    contents = _contents(kind, level, chapter)
    count = contents.count()
    data = {
        'section': section,
        'type': kind,
        'url': hub_url(section, level, chapter),
        'level': {'id': level.id, 'name': level.name, 'slug': slug(level.name), 'url': hub_url(section, level)},
        'chapter': {'id': chapter.id, 'name': chapter.name, 'slug': slug(chapter.name)} if chapter else None,
        'count': count,
        'indexable': count > 0,
        **_texts(section, level, chapter, count),
        'chapters': [
            {'id': ch.id, 'name': ch.name, 'slug': slug(ch.name), 'count': n, 'url': hub_url(section, level, ch)}
            for ch, n in _level_chapters(kind, level)
        ],
        # Même niveau (et même chapitre) dans les autres rubriques : cours ↔ exercices ↔ examens.
        'related': [
            {'section': other, 'label': SECTION_LABEL[other], 'count': n, 'url': hub_url(other, level, chapter)}
            for other, okind in SECTION_TYPE.items() if other != section
            for n in [_contents(okind, level, chapter).count()] if n > 0
        ],
    }
    return data


def all_hubs():
    """(url, dernière mise à jour) de chaque hub qui a du contenu : pour le sitemap."""
    from apps.things.models import Content
    out = []
    for section, kind in SECTION_TYPE.items():
        for level in ClassLevel.objects.order_by('id'):
            qs = Content.objects.filter(type=kind, class_levels=level)
            last = qs.aggregate(m=Max('updated_at'))['m']
            if last is None:
                continue
            out.append((hub_url(section, level), last))
            for ch, _ in _level_chapters(kind, level):
                last_ch = qs.filter(chapters=ch).aggregate(m=Max('updated_at'))['m']
                out.append((hub_url(section, level, ch), last_ch))
    return out


@api_view(['GET'])
@permission_classes([AllowAny])
def hub_view(request):
    """GET /api/hubs/?section=exercises&level=2eme-bac-sm[&chapter=limites-et-continuite]"""
    data = resolve(request.query_params.get('section', ''), request.query_params.get('level', ''),
                   request.query_params.get('chapter') or None)
    if data is None:
        return Response({'detail': 'Page introuvable.'}, status=404)
    return Response(data)
