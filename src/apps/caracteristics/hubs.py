"""Pages par niveau et par chapitre (« hubs ») : /exercises/niveau/2eme-bac-sm/limites-et-continuite.

Les élèves cherchent « exercices corrigés 2 bac sm » ou « limites et continuité 2 bac sm » : une page
dont le titre et le texte répondent exactement à cette recherche, avec les liens vers chaque contenu,
remonte bien mieux que la liste générale filtrée par un paramètre (?classLevels=3, ignoré par Google).

Une seule source pour les textes : l'API (/api/hubs/, lue par l'application) et la page pré-remplie
pour les moteurs de recherche (config/seo.py) disent exactement la même chose.
Une page sans aucun contenu reste consultable mais n'est ni indexée ni dans le sitemap.

Navigation en dossiers (10/10/2026) : Maths › niveau › chapitre, comme des dossiers qui contiennent les
contenus (« fichiers »). `folders` = TOUS les chapitres du niveau (un chapitre sans contenu reste visible,
marqué vide) ; GET /api/hubs/niveaux/ = les dossiers de niveaux d'une rubrique ; GET /api/hubs/nationaux/ =
les dossiers par année du Bac national. Les devoirs (rubrique exams) ne comptent pas les sujets du Bac
national, qui ont leur propre rubrique (même règle que la liste : is_national_exam=false).

Programme officiel (11/10/2026) : les chapitres d'un niveau sont ceux de programme.chapitres_du_niveau()
(Mathématiques, ordre d'enseignement) partout — dossiers, textes, sitemap. Chaque dossier porte `ordre` et
`aussi` (mots d'un ancien dossier absorbé, repris dans les textes de la page). Ancienne adresse de chapitre
(ALIAS_SLUGS) : resolve() ne renvoie que {'redirect': nouvelle adresse} (l'API répond 200 avec ce seul champ,
la page pré-remplie redirige en 301).
"""
import re

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.caracteristics import programme
from apps.caracteristics.models import Chapter, ClassLevel, Subject

SECTION_TYPE = {'exercises': 'exercise', 'lessons': 'lesson', 'exams': 'exam'}
SECTION_LABEL = {'exercises': 'Exercices corrigés', 'lessons': 'Cours', 'exams': 'Devoirs et examens corrigés'}

# Comment les élèves écrivent leur niveau dans Google : (forme courte, formes longues).
LEVEL_WORDS = {
    'Tronc commun Sciences': ('TCS', 'Tronc commun scientifique, TC BIOF'),
    '1ère Bac SM': ('1 Bac SM', '1ère année Bac Sciences Mathématiques, 1BAC SM BIOF'),
    '2ème Bac SM': ('2 Bac SM', '2ème année Bac Sciences Mathématiques A et B, 2BAC SM BIOF'),
    '2ème Bac PC/SVT': ('2 Bac PC/SVT', '2ème année Bac Sciences Physiques et SVT, 2BAC PC BIOF, 2BAC SVT BIOF'),
}


def slug(name):
    """Adresse d'un niveau ou d'un chapitre. « / » sépare comme un espace (« 2ème Bac PC/SVT » → 2eme-bac-pc-svt) ;
    même règle côté front (lib/api/hubApi.ts slugify) et pour les niveaux de l'API (ClassLevelSerializer)."""
    return slugify((name or '').replace('/', ' '))


def hub_url(section, level, chapter=None):
    path = f'/{section}/niveau/{slug(level.name)}'
    return f'{path}/{slug(chapter.name)}' if chapter else path


def _folder_contents(kind, level=None):
    """Contenus d'une rubrique tels que la liste les montre (devoirs : sans les sujets du Bac national, qui ont
    leur rubrique). Même règle pour la page, ses dossiers, ses textes, le sitemap et la page pré-remplie."""
    from apps.things.models import Content
    qs = Content.objects.filter(type=kind)
    if level is not None:
        qs = qs.filter(class_levels=level)
    if kind == 'exam':
        qs = qs.filter(is_national_exam=False)
    return qs


def _contents(kind, level, chapter=None):
    qs = _folder_contents(kind, level)
    if chapter is not None:
        qs = qs.filter(chapters=chapter)
    return qs.distinct()


# Au-delà, Google coupe le titre : les mots d'un dossier absorbé n'y entrent que s'il reste court.
TITLE_MAX = 70


def _plural(n, one, many):
    return f'{n} {one if n == 1 else many}'


def _programme(level):
    """{nom de chapitre: entrée de programme.py} du niveau (lecture seule)."""
    return {c['nom']: c for c in programme.PROGRAMME.get(level.name, [])}


# Programme affiché sur la page d'un chapitre : seulement ce qui s'adresse aux élèves. Les notes de travail
# de programme.py (« (à vérifier) », renvois au document officiel, numéros de capacité) sont retirées.
_NOTE = re.compile(r'\s*\((?:[^()]*?(?:document|partition|titre|vérifier|cadres|capacité|\bch\d|programme de|'
                   r'anciens programmes|habituellement|nommé|prérequis|BIOF)[^()]*)\)', re.I)
_NUM_PREFIX = re.compile(r'^\s*\d+(?:\.\d+)+\.?\s*')
_NUM_PAREN = re.compile(r'\s*\(\d+(?:\.\d+)+\)')
_HORS = re.compile(r'\s*:\s*hors programme(?: en [^;]+)?', re.I)
_DROP = re.compile(r'à vérifier|document|partition|\bch\d|cadres|incertaine|^(?:capacités|orientation) habituelle', re.I)


def _public_items(items):
    out = []
    for item in items or []:
        text = str(item)
        if re.search(r'à vérifier', text, re.I):
            continue
        text = _HORS.sub('', _NOTE.sub('', _NUM_PAREN.sub('', _NUM_PREFIX.sub('', text))))
        text = re.sub(r',\s*nommé[^,;]*', '', text).strip().rstrip(' ;.,:').strip()
        if text and not _DROP.search(text):
            out.append(text[0].upper() + text[1:])
    return out


def programme_public(level, chapter):
    """Ce que dit le programme d'un chapitre (page du chapitre et sa version pré-remplie), ou None.
    1ère Bac SM : le document officiel ne donne que les titres ; ses repères (indicatifs) sont dits comme tels."""
    entree = programme.chapitre(level.name, chapter.name)
    if not entree:
        return None
    periode = entree.get('periode') or ''
    data = {
        'periode': None if re.search(r'document|habituellement', periode, re.I) else (periode or None),
        'heures': entree.get('heures') or None,
        'contenus': _public_items(entree.get('contenus')),
        'capacites': _public_items(entree.get('capacites')),
        'reperes': [] if entree.get('capacites') else _public_items(entree.get('reperes')),
        'theoremes': _public_items(entree.get('theoremes')),
        'hors_programme': _public_items(entree.get('hors_programme')),
    }
    if not any(data[k] for k in ('contenus', 'capacites', 'reperes', 'theoremes', 'hors_programme')):
        return None
    return data


def _aussi(level, chapter):
    entree = _programme(level).get(chapter.name)
    return list(entree['aussi']) if entree else []


def _avec_aussi(nom, aussi):
    """« Probabilités et dénombrement » : le chapitre suivi des mots de l'ancien dossier qu'il a absorbé."""
    if not aussi:
        return nom
    return nom + (', ' if ' et ' in nom else ' et ') + ', '.join(aussi)


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
        # Mots d'un ancien dossier absorbé (« dénombrement » dans Probabilités du 2ème Bac SM) : gardés dans le
        # H1, l'introduction, la description, et le titre s'il reste court.
        aussi = _aussi(level, chapter)
        full = _avec_aussi(ch, aussi)
        compris = f', {", ".join(aussi)} compris' if aussi else ''
        if section == 'exercises':
            title = f'{ch} – Exercices corrigés {alias} | Fidni'
            title_full = f'{full} – Exercices corrigés {alias} | Fidni'
            h1 = f'{full} : exercices corrigés – {lv}'
            intro = (f'Exercices corrigés sur le chapitre « {ch} » du {lv} ({long}){compris}, programme marocain. '
                     f'Énoncés et solutions détaillées, de l’application directe aux exercices de type Bac.')
            description = (f'{_plural(count, "exercice corrigé", "exercices corrigés")} sur {full} pour le {alias} : '
                           f'énoncés et solutions détaillées étape par étape, programme marocain. Gratuit.')
        elif section == 'lessons':
            title = f'{ch} – Cours de maths {alias} | Fidni'
            title_full = f'{full} – Cours de maths {alias} | Fidni'
            h1 = f'{full} : cours – {lv}'
            intro = (f'Le cours « {ch} » du {lv} ({long}){compris} : définitions, théorèmes, propriétés et méthodes, '
                     f'avec des exemples, conformes au programme marocain.')
            description = (f'Cours de maths sur {full} pour le {alias} : définitions, théorèmes, propriétés, méthodes '
                           f'et exemples, programme marocain. Gratuit.')
        else:
            title = f'{ch} – Devoirs surveillés corrigés {alias} | Fidni'
            title_full = f'{full} – Devoirs surveillés corrigés {alias} | Fidni'
            h1 = f'{full} : devoirs et examens corrigés – {lv}'
            intro = (f'Devoirs surveillés et examens de mathématiques portant sur « {ch} » au {lv} ({long}){compris}, '
                     f'avec barème et corrigé détaillé.')
            description = (f'{_plural(count, "devoir corrigé", "devoirs et examens corrigés")} sur {full} pour le {alias} : '
                           f'barème, durée et corrigé détaillé, programme marocain.')
        if aussi and len(title_full) <= TITLE_MAX:
            title = title_full
    return {'title': title, 'h1': h1, 'intro': intro, 'description': description}


def _counts(qs):
    """{id de chapitre: nombre de contenus} d'un queryset de contenus."""
    return {r['chapters']: r['n'] for r in qs.order_by().values('chapters').annotate(n=Count('id', distinct=True))
            if r['chapters'] is not None}


def _level_chapters(kind, level, chapters=None):
    """Chapitres du niveau qui ont au moins un contenu de ce type, dans l'ordre du programme."""
    chapters = programme.chapitres_du_niveau(level) if chapters is None else chapters
    counts = _counts(_folder_contents(kind, level))
    return [(ch, counts[ch.id]) for ch in chapters if ch.id in counts]


def _subject_name():
    """La matière du site, s'il n'y en a qu'une (les maths) : racine du fil d'Ariane des dossiers."""
    names = list(Subject.objects.values_list('name', flat=True)[:2])
    return names[0] if len(names) == 1 else None


def _progress(user, content_ids):
    """{id du contenu: 'success' | 'review'} : contenus terminés par l'élève (Complete, object_id en str)."""
    from apps.interactions.models import Complete
    from apps.things.models import Content
    if not content_ids:
        return {}
    ct = ContentType.objects.get_for_model(Content)
    rows = Complete.objects.filter(user=user, content_type=ct,
                                   object_id__in=[str(i) for i in content_ids]).values_list('object_id', 'status')
    return {int(o): st for o, st in rows if str(o).isdigit()}


def _folders(section, level, user=None, chapters=None):
    """Tous les chapitres du niveau dans l'ordre du programme (`ordre`, `aussi`), contenus comptés (0 = dossier
    vide), et pour un élève connecté ce qu'il a terminé dans chacun (`mine`)."""
    from apps.things.models import Content
    kind = SECTION_TYPE[section]
    qs = _folder_contents(kind, level)
    counts = _counts(qs)
    mine = {}
    if user is not None and getattr(user, 'is_authenticated', False):
        ids = list(qs.values_list('id', flat=True).distinct())
        done = _progress(user, ids)
        if done:
            links = Content.chapters.through.objects.filter(content_id__in=list(done)).values_list('content_id', 'chapter_id')
            for cid, chid in links:
                m = mine.setdefault(chid, {'done': 0, 'success': 0})
                m['done'] += 1
                m['success'] += done[cid] == 'success'
    if chapters is None:
        chapters = programme.chapitres_du_niveau(level, Chapter.objects.select_related('subfield'))
    prog = _programme(level)
    out = []
    for ch in chapters:
        entree = prog.get(ch.name)
        folder = {'id': ch.id, 'name': ch.name, 'slug': slug(ch.name), 'url': hub_url(section, level, ch),
                  'count': counts.get(ch.id, 0), 'subfield': ch.subfield.name if ch.subfield else None,
                  # Rang dans le programme du niveau (None : chapitre hors programme, rangé à la fin).
                  'ordre': entree['ordre'] if entree else None,
                  'aussi': list(entree['aussi']) if entree else []}
        if user is not None and getattr(user, 'is_authenticated', False):
            folder['mine'] = mine.get(ch.id, {'done': 0, 'success': 0})
        out.append(folder)
    return out


def levels(section):
    """Dossiers de niveaux d'une rubrique : contenus et chapitres remplis de chacun."""
    kind = SECTION_TYPE.get(section)
    if kind is None:
        return None
    out = []
    for level in ClassLevel.objects.order_by('order', 'id'):
        qs = _folder_contents(kind, level)
        level_chapters = {ch.id for ch in programme.chapitres_du_niveau(level)}
        used = set(qs.order_by().values_list('chapters', flat=True).distinct())
        out.append({'id': level.id, 'name': level.name, 'slug': slug(level.name), 'url': hub_url(section, level),
                    'count': qs.distinct().count(), 'chapters_total': len(level_chapters),
                    'chapters_filled': len(level_chapters & used)})
    return {'section': section, 'type': kind, 'subject': _subject_name(), 'label': SECTION_LABEL[section], 'levels': out}


def national_years():
    """Dossiers du Bac national, un par année (la plus récente d'abord) ; les sujets sans année à part (year=None)."""
    from apps.things.models import Content
    rows = (Content.objects.filter(type='exam', is_national_exam=True).order_by()
            .values('id', 'national_year', 'class_levels__name').distinct())
    years = {}
    for r in rows:
        y = years.setdefault(r['national_year'], {'ids': set(), 'levels': set()})
        y['ids'].add(r['id'])
        if r['class_levels__name']:
            y['levels'].add(r['class_levels__name'])
    order = {lv.name: lv.order for lv in ClassLevel.objects.all()}
    out = [{'year': year, 'count': len(v['ids']), 'levels': sorted(v['levels'], key=lambda n: (order.get(n, 99), n))}
           for year, v in years.items()]
    out.sort(key=lambda y: (y['year'] is None, -(y['year'] or 0)))
    return {'subject': _subject_name(), 'years': out}


def resolve(section, level_slug, chapter_slug=None, user=None):
    """Tout ce qu'il faut pour afficher un hub, ou None si le niveau ou le chapitre n'existe pas.
    Ancienne adresse d'un chapitre de ce niveau (programme.ALIAS_SLUGS) ou d'un niveau renommé (programme.ALIAS_NIVEAUX) :
    {'redirect': nouvelle adresse}, seul champ."""
    kind = SECTION_TYPE.get(section)
    if kind is None:
        return None
    level = next((lv for lv in ClassLevel.objects.all() if slug(lv.name) == level_slug), None)
    if level is None:
        # Ancienne adresse d'un niveau renommé (« 2eme-bac-pc » → « 2eme-bac-pc-svt ») : même chapitre au nouveau niveau.
        nouveau = programme.ALIAS_NIVEAUX.get(level_slug)
        if nouveau and any(slug(lv.name) == nouveau for lv in ClassLevel.objects.all()):
            return {'redirect': f'/{section}/niveau/{nouveau}' + (f'/{chapter_slug}' if chapter_slug else '')}
        return None
    chapters = programme.chapitres_du_niveau(level, Chapter.objects.select_related('subfield'))
    chapter = None
    if chapter_slug:
        chapter = next((ch for ch in chapters if slug(ch.name) == chapter_slug), None)
        if chapter is None:
            nouveau = programme.ALIAS_SLUGS.get(slug(level.name), {}).get(chapter_slug)
            if nouveau and any(slug(ch.name) == nouveau for ch in chapters):
                return {'redirect': f'/{section}/niveau/{slug(level.name)}/{nouveau}'}
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
            for ch, n in _level_chapters(kind, level, chapters)
        ],
        # Dossiers : tous les chapitres du niveau, vides compris (navigation Maths › niveau › chapitre).
        'folders': _folders(section, level, user, chapters),
        # Contenus du niveau rangés dans aucun de ses chapitres : un dossier « Sans chapitre » à part, sinon
        # introuvables depuis les dossiers (liste : /api/contents/?class_levels=<id>&sans_chapitre=true).
        'unfiled': (_folder_contents(kind, level).exclude(chapters__class_levels=level).distinct().count()
                    if chapter is None else 0),
        'subject': _subject_name(),
        # Page d'un chapitre : ce que dit le programme officiel (contenus, capacités, théorèmes, hors programme).
        'programme': programme_public(level, chapter) if chapter else None,
        # Même niveau (et même chapitre) dans les autres rubriques : cours ↔ exercices ↔ examens.
        'related': [
            {'section': other, 'label': SECTION_LABEL[other], 'count': n, 'url': hub_url(other, level, chapter)}
            for other, okind in SECTION_TYPE.items() if other != section
            # Comptés comme les dossiers de la rubrique (devoirs : sans les sujets du Bac national).
            for n in [_contents(okind, level, chapter).count()] if n > 0
        ],
    }
    return data


def all_hubs():
    """(url, dernière mise à jour) de chaque hub qui a du contenu : pour le sitemap. Chapitres rattachés au niveau
    seulement, dans l'ordre du programme (jamais une ancienne adresse redirigée)."""
    out = []
    for section, kind in SECTION_TYPE.items():
        for level in ClassLevel.objects.order_by('order', 'id'):
            qs = _folder_contents(kind, level)
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
    """GET /api/hubs/?section=exercises&level=2eme-bac-sm[&chapter=limites-et-continuite]

    Ancienne adresse de chapitre : 200 avec {"redirect": "/exercises/niveau/2eme-bac-sm/probabilites"} seulement
    (le front remplace l'adresse, filtres compris)."""
    data = resolve(request.query_params.get('section', ''), request.query_params.get('level', ''),
                   request.query_params.get('chapter') or None, user=request.user)
    if data is None:
        return Response({'detail': 'Page introuvable.'}, status=404)
    return Response(data)


@api_view(['GET'])
@permission_classes([AllowAny])
def levels_view(request):
    """GET /api/hubs/niveaux/?section=exercises : dossiers de niveaux de la rubrique."""
    data = levels(request.query_params.get('section', ''))
    if data is None:
        return Response({'detail': 'Rubrique inconnue.'}, status=404)
    return Response(data)


@api_view(['GET'])
@permission_classes([AllowAny])
def national_years_view(request):
    """GET /api/hubs/nationaux/ : dossiers par année du Bac national."""
    return Response(national_years())
