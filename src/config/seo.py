"""Pages de contenu lisibles par les moteurs de recherche sans JavaScript.

fidni.fr est une application React : sans ce module, chaque exercice, leçon ou examen arrivait chez
Google avec le même titre et la même description que l'accueil, et une page vide (le texte n'apparaît
qu'après exécution du JavaScript). Les pages se ressemblaient toutes : peu de chances d'être indexées.

Le nginx du frontend envoie /exercises/<id>, /lessons/<id> et /exams/<id> ici (content_page), ainsi que
l'accueil et les listes /exercises, /lessons, /exams (listing_page). On renvoie le même
index.html que l'application, avec :
- un <title>, une description, un lien canonique et des balises Open Graph propres au contenu ;
- des données structurées schema.org (LearningResource) ;
- l'énoncé en texte brut dans <div id="root"> (React le remplace au démarrage : c'est le même texte
  que celui que voit l'élève, ce n'est pas du contenu caché). Il est enveloppé dans .fd-prerender, que
  l'index.html rend invisible le temps du chargement (sinon ce texte sans mise en forme, LaTeX compris,
  s'affichait une fraction de seconde) et fait réapparaître si le JavaScript ne démarre pas.
En cas d'erreur (backend indisponible…), nginx retombe sur l'index.html statique : le site marche.
"""
import html
import json
import re
import time
import urllib.request

from django.conf import settings
from django.http import HttpResponse

SECTIONS = {'exercise': 'exercises', 'lesson': 'lessons', 'exam': 'exams'}
KIND = {'exercise': 'Exercice', 'lesson': 'Leçon', 'exam': 'Examen'}
KIND_PLURAL = {'exercise': 'Exercices corrigés', 'lesson': 'Cours', 'exam': 'Devoirs et examens'}
KIND_BY_SECTION = {v: k for k, v in SECTIONS.items()}
# Parties du JSON qui ne sont pas l'énoncé affiché d'emblée (solutions repliées, métadonnées d'import).
SKIP_KEYS = {'solution', 'solutions', 'import', 'meta', 'hint', 'hints', 'indice', 'erreurs_frequentes'}
MAX_TEXT = 6000

_index_cache = {'html': None, 'at': 0.0}


def _index_html():
    """index.html de l'application (conteneur frontend), gardé 5 secondes en mémoire.

    Pas plus : il référence les fichiers JavaScript de la version en ligne (noms hachés). Gardé
    5 minutes, une mise en ligne du seul frontend servait l'ancien index.html, dont les fichiers
    n'existent plus : pages blanches pendant ces minutes-là. L'appel est interne et quasi gratuit.
    """
    now = time.time()
    if _index_cache['html'] and now - _index_cache['at'] < 5:
        return _index_cache['html']
    url = getattr(settings, 'SEO_INDEX_URL', 'http://frontend:8080/index.html')
    with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 (URL interne fixe)
        page = resp.read().decode('utf-8')
    _index_cache.update(html=page, at=now)
    return page


def _to_text(fragment):
    """HTML d'un bloc → lignes de texte (les formules restent en LaTeX, lisibles et indexables)."""
    fragment = re.sub(r'(?i)</(p|li|h\d|div|tr)>|<br\s*/?>', '\n', fragment)
    fragment = re.sub(r'<[^>]+>', ' ', fragment)
    lines = (re.sub(r'[ \t\xa0]+', ' ', html.unescape(line)).strip() for line in fragment.split('\n'))
    return [line for line in lines if line]


def _statement_lines(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SKIP_KEYS:
                continue
            if key == 'html' and isinstance(value, str):
                out.extend(_to_text(value))
            elif key in ('title', 'titre') and isinstance(value, str) and value.strip():
                out.append(('h2', value.strip()))  # titre de partie (leçon) : vrai intertitre
            else:
                _statement_lines(value, out)
    elif isinstance(node, list):
        for value in node:
            _statement_lines(value, out)
    return out


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0] + '…'


def _render(page, *, title, description, url, body, json_ld=None, status=200, noindex=False):
    esc = lambda s: html.escape(s, quote=True)  # noqa: E731
    page = re.sub(r'<title>.*?</title>', f'<title>{esc(title)}</title>', page, count=1, flags=re.S)
    page = re.sub(r'<meta name="title"[^>]*>', f'<meta name="title" content="{esc(title)}" />', page, count=1)
    page = re.sub(r'<meta name="description"[^>]*>', f'<meta name="description" content="{esc(description)}" />', page, count=1)
    if noindex:
        page = re.sub(r'<meta name="(robots|googlebot)"[^>]*>', r'<meta name="\1" content="noindex" />', page)
    head = [f'<link rel="canonical" href="{esc(url)}" />',
            f'<meta property="og:title" content="{esc(title)}" />',
            f'<meta property="og:description" content="{esc(description)}" />',
            f'<meta property="og:url" content="{esc(url)}" />']
    if json_ld:
        # « < », « > », « & » échappés : aucun titre ne peut fermer ou perturber la balise <script>.
        data = (json.dumps(json_ld, ensure_ascii=False)
                .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))
        head.append(f'<script type="application/ld+json">{data}</script>')
    page = page.replace('</head>', '    ' + '\n    '.join(head) + '\n  </head>', 1)
    if body:
        body = f'<div class="fd-prerender">{body}</div>'
    page = page.replace('<div id="root"></div>', f'<div id="root">{body}</div>', 1)
    resp = HttpResponse(page, status=status, content_type='text/html; charset=utf-8')
    resp['Cache-Control'] = 'no-cache'
    return resp


def content_page(request, section, pk):
    from apps.things.models import Content

    page = _index_html()
    site = settings.FRONTEND_URL.rstrip('/')
    kind = KIND_BY_SECTION.get(section)
    content = (Content.objects.filter(pk=pk, type=kind).select_related('subject')
               .prefetch_related('chapters', 'class_levels').first() if kind else None)
    if content is None:
        return _render(page, title='Contenu introuvable | Fidni', description='Ce contenu n’existe pas ou a été retiré.',
                       url=f'{site}/{section}/{pk}', body='', status=404, noindex=True)

    url = f'{site}/{section}/{pk}'
    kind_label = KIND[content.type]
    levels = [lv.name for lv in content.class_levels.all()]
    chapters = [ch.name for ch in content.chapters.all()]
    subject = content.subject.name if content.subject else 'Mathématiques'
    corrige = ' corrigé' if content.type in ('exercise', 'exam') else ''
    title = _clip(f'{content.title} – {kind_label}{corrige}'
                  + (f' {levels[0]}' if levels else '') + ' | Fidni', 110)
    context = ', '.join(filter(None, [', '.join(levels), ', '.join(chapters)]))
    if content.type == 'lesson':
        description = f'Leçon de {subject.lower()}' + (f' ({context})' if context else '') \
                      + f' : {content.title}. Définitions, théorèmes, méthodes et exemples, sur Fidni.'
    else:
        description = f'{kind_label} de {subject.lower()}' + (f' ({context})' if context else '') \
                      + f' : {content.title}. Énoncé et solution détaillée étape par étape, programme marocain, sur Fidni.'
    description = _clip(description, 300)

    from apps.caracteristics.hubs import hub_url
    level_objs = sorted(content.class_levels.all(), key=lambda lv: lv.id)
    level = level_objs[0] if level_objs else None
    chapter = next((ch for ch in content.chapters.all() if level and level in ch.class_levels.all()), None)

    lines, total = [], 0
    for line in _statement_lines(content.json_content or {}, []):
        if total > MAX_TEXT:
            break
        lines.append(line)
        total += len(line if isinstance(line, str) else line[1])
    esc = html.escape
    # Fil d'Ariane en liens : rubrique › niveau › chapitre (pages hubs, config/../hubs.py).
    crumb_links = [f'<a href="/{section}">{esc(KIND_PLURAL[content.type])}</a>']
    if level:
        crumb_links.append(f'<a href="{hub_url(section, level)}">{esc(level.name)}</a>')
        if chapter:
            crumb_links.append(f'<a href="{hub_url(section, level, chapter)}">{esc(chapter.name)}</a>')
    crumbs = ' › '.join(crumb_links)
    credit = (content.json_content or {}).get('credit')

    # Contenus voisins : même rubrique, même niveau, même chapitre.
    related_html = ''
    if level and chapter:
        neighbours = list(Content.objects.filter(type=content.type, class_levels=level, chapters=chapter)
                          .exclude(pk=content.pk).distinct().order_by('-updated_at')[:8])
        if neighbours:
            related_html = (f'<h2 style="font-size:20px;margin-top:32px">Autres {esc(KIND_PLURAL[content.type].lower())} '
                            f'– {esc(chapter.name)} ({esc(level.name)})</h2><ul>'
                            + ''.join(f'<li><a href="/{section}/{c.id}">{esc(c.title)}</a></li>' for c in neighbours)
                            + f'</ul><p><a href="{hub_url(section, level, chapter)}">Tous les {esc(KIND_PLURAL[content.type].lower())} '
                            f'sur {esc(chapter.name)}</a></p>')
    body = (f'<main style="max-width:760px;margin:40px auto;padding:0 16px;font-family:system-ui,sans-serif;'
            f'line-height:1.6;color:#1a1a1a">'
            f'<p style="font-size:13px;color:#6b6862">{crumbs}</p>'
            f'<h1 style="font-size:26px">{esc(content.title)}</h1>'
            + (f'<p style="font-size:13px;color:#6b6862">Proposé par {esc(credit)}</p>' if credit else '')
            + ''.join(f'<p>{esc(line)}</p>' if isinstance(line, str)
                      else f'<h2 style="font-size:20px;margin-top:28px">{esc(line[1])}</h2>' for line in lines)
            + related_html + '</main>')

    json_ld = {
        '@context': 'https://schema.org',
        '@type': 'LearningResource',
        'name': content.title,
        'description': description,
        'url': url,
        'inLanguage': 'fr',
        'learningResourceType': {'exercise': 'Exercice', 'lesson': 'Leçon', 'exam': 'Examen'}[content.type],
        'educationalLevel': levels or None,
        'about': chapters or None,
        'dateModified': content.updated_at.date().isoformat() if content.updated_at else None,
        'isAccessibleForFree': True,
        'provider': {'@type': 'EducationalOrganization', 'name': 'Fidni', 'url': site},
    }
    json_ld = {k: v for k, v in json_ld.items() if v is not None}
    trail = [('Accueil', f'{site}/'), (KIND_PLURAL[content.type], f'{site}/{section}')]
    if level:
        trail.append((level.name, site + hub_url(section, level)))
        if chapter:
            trail.append((chapter.name, site + hub_url(section, level, chapter)))
    trail.append((content.title, url))
    return _render(page, title=title, description=description, url=url, body=body,
                   json_ld=[json_ld, _breadcrumbs(trail)])


def _breadcrumbs(trail):
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': i + 1, 'name': name, 'item': link} for i, (name, link) in enumerate(trail)]}


# ───────────────────────────── Accueil et listes

SITE_NAME = 'Fidni'
LISTINGS = {
    'exercises': {
        'type': 'exercise',
        'title': 'Exercices de maths corrigés – Tronc commun, 1ère et 2ème Bac (Maroc) | Fidni',
        'h1': 'Exercices de maths corrigés',
        'description': ('Exercices de maths corrigés pour le lycée au Maroc : Tronc commun, 1ère Bac SM, 2ème Bac SM '
                        'et PC (BIOF). Classés par chapitre, avec solutions détaillées. Gratuit.'),
        'intro': ('Des exercices de mathématiques corrigés pour le programme marocain, du Tronc commun au 2ème Bac, '
                  'classés par niveau et par chapitre. Chaque exercice a sa solution détaillée, étape par étape, '
                  'et tu peux t’auto-évaluer question par question.'),
    },
    'lessons': {
        'type': 'lesson',
        'title': 'Cours de maths – Tronc commun, 1ère et 2ème Bac (Maroc) | Fidni',
        'h1': 'Cours de mathématiques',
        'description': ('Cours de maths du lycée au Maroc : définitions, théorèmes, propriétés et méthodes, du Tronc '
                        'commun au 2ème Bac SM. Leçons claires, à imprimer ou à ranger dans ton cahier. Gratuit.'),
        'intro': ('Les leçons de mathématiques du programme marocain, chapitre par chapitre : définitions, '
                  'théorèmes, propriétés, méthodes et exemples.'),
    },
    'exams': {
        'type': 'exam',
        'title': 'Devoirs surveillés et examens de maths corrigés – Bac Maroc | Fidni',
        'h1': 'Devoirs surveillés et examens de maths corrigés',
        'description': ('Devoirs surveillés et sujets d’examen de maths corrigés pour le Bac au Maroc : Tronc commun, '
                        '1ère Bac SM, 2ème Bac SM et PC. Barème, durée, corrigé détaillé et épreuve chronométrée.'),
        'intro': ('Des sujets de devoirs surveillés et d’examens de mathématiques, avec leur barème et un corrigé '
                  'détaillé. Entraîne-toi en conditions réelles avec l’épreuve chronométrée.'),
    },
}
HOME = {
    'title': 'Fidni – Exercices de maths corrigés, cours et examens | Lycée et Bac au Maroc',
    'description': ('Exercices de maths corrigés, cours et devoirs surveillés pour les lycéens marocains : Tronc commun, '
                    '1ère Bac SM, 2ème Bac SM et PC (BIOF). Solutions détaillées, suivi de progression. Gratuit.'),
}
BODY_STYLE = ('max-width:860px;margin:40px auto;padding:0 16px;font-family:system-ui,sans-serif;'
              'line-height:1.6;color:#1a1a1a')


def _grouped(kind):
    """Contenus d'un type, rangés par niveau puis par chapitre (ordre du programme)."""
    from apps.things.models import Content
    rows = (Content.objects.filter(type=kind).prefetch_related('class_levels', 'chapters')
            .order_by('-updated_at')[:2000])
    groups = {}
    for c in rows:
        level = min(c.class_levels.all(), key=lambda lv: lv.id, default=None)
        chapter = min(c.chapters.all(), key=lambda ch: ch.name, default=None)
        lkey = (level.id if level else 10**9, level.name if level else 'Autres niveaux')
        groups.setdefault(lkey, {}).setdefault(chapter.name if chapter else 'Autres', []).append(c)
    return [(lname, sorted(chapters.items())) for (_, lname), chapters in sorted(groups.items())]


def _links_html(section, groups, esc):
    from django.utils.text import slugify
    out = []
    for level, chapters in groups:
        lpath = f'/{section}/niveau/{slugify(level)}'
        out.append(f'<h2 style="font-size:21px;margin-top:32px"><a href="{lpath}">{esc(level)}</a></h2>'
                   if level != 'Autres niveaux' else f'<h2 style="font-size:21px;margin-top:32px">{esc(level)}</h2>')
        for chapter, items in chapters:
            heading = (f'<a href="{lpath}/{slugify(chapter)}">{esc(chapter)}</a>'
                       if level != 'Autres niveaux' and chapter != 'Autres' else esc(chapter))
            out.append(f'<h3 style="font-size:17px;margin-top:18px">{heading}</h3><ul>')
            out.extend(f'<li><a href="/{section}/{c.id}">{esc(c.title)}</a></li>' for c in items)
            out.append('</ul>')
    return ''.join(out)


def _nav_html():
    return ('<nav><a href="/exercises">Exercices corrigés</a> · <a href="/lessons">Cours</a> · '
            '<a href="/exams">Devoirs et examens</a> · <a href="/concours">Concours</a></nav>')


def _levels_html():
    """Accueil : par niveau, les liens vers les exercices, cours et examens (pages hubs)."""
    from apps.caracteristics.hubs import SECTION_LABEL, SECTION_TYPE, hub_url
    from apps.caracteristics.models import ClassLevel
    from apps.things.models import Content
    rows = []
    for level in ClassLevel.objects.order_by('id'):
        links = [f'<a href="{hub_url(section, level)}">{SECTION_LABEL[section]} {html.escape(level.name)}</a>'
                 for section, kind in SECTION_TYPE.items()
                 if Content.objects.filter(type=kind, class_levels=level).exists()]
        if links:
            rows.append(f'<li><strong>{html.escape(level.name)}</strong> : {" · ".join(links)}</li>')
    return ('<h2 style="font-size:21px;margin-top:28px">Par niveau</h2><ul>' + ''.join(rows) + '</ul>') if rows else ''


def hub_page(request, section, level, chapter=None):
    """Page par niveau ou par chapitre (/exercises/niveau/2eme-bac-sm[/limites-et-continuite])."""
    from apps.caracteristics.hubs import SECTION_TYPE, resolve
    from apps.things.models import Content

    page = _index_html()
    site = settings.FRONTEND_URL.rstrip('/')
    esc = html.escape
    data = resolve(section, level, chapter)
    if data is None:
        return _render(page, title='Page introuvable | Fidni', description='Cette page n’existe pas.',
                       url=f'{site}/{section}', body='', status=404, noindex=True)
    url = site + data['url']
    qs = Content.objects.filter(type=SECTION_TYPE[section], class_levels__id=data['level']['id'])
    if data['chapter']:
        qs = qs.filter(chapters__id=data['chapter']['id'])
    items = list(qs.distinct().order_by('-updated_at')[:300])

    parts = [f'<main style="{BODY_STYLE}">',
             f'<p style="font-size:13px;color:#6b6862"><a href="/{section}">{esc(SECTION_NAV[section])}</a> › '
             f'<a href="{data["level"]["url"]}">{esc(data["level"]["name"])}</a>'
             + (f' › {esc(data["chapter"]["name"])}' if data['chapter'] else '') + '</p>',
             f'<h1 style="font-size:28px">{esc(data["h1"])}</h1>', f'<p>{esc(data["intro"])}</p>']
    if items:
        parts.append('<ul>' + ''.join(f'<li><a href="/{section}/{c.id}">{esc(c.title)}</a></li>' for c in items) + '</ul>')
    if data['chapters'] and not data['chapter']:
        parts.append('<h2 style="font-size:21px;margin-top:28px">Par chapitre</h2><ul>' + ''.join(
            f'<li><a href="{ch["url"]}">{esc(ch["name"])}</a> ({ch["count"]})</li>' for ch in data['chapters']) + '</ul>')
    elif data['chapters']:
        others = [ch for ch in data['chapters'] if ch['id'] != data['chapter']['id']]
        if others:
            parts.append(f'<h2 style="font-size:21px;margin-top:28px">Autres chapitres – {esc(data["level"]["name"])}</h2><ul>'
                         + ''.join(f'<li><a href="{ch["url"]}">{esc(ch["name"])}</a> ({ch["count"]})</li>' for ch in others) + '</ul>')
    if data['related']:
        parts.append('<p>Aussi : ' + ' · '.join(f'<a href="{r["url"]}">{esc(r["label"])}</a> ({r["count"]})'
                                                for r in data['related']) + '</p>')
    parts.append(_nav_html() + '</main>')

    trail = [('Accueil', f'{site}/'), (SECTION_NAV[section], f'{site}/{section}'),
             (data['level']['name'], site + data['level']['url'])]
    if data['chapter']:
        trail.append((data['chapter']['name'], url))
    json_ld = [
        {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': data['h1'], 'url': url,
         'description': data['description'], 'inLanguage': 'fr',
         'isPartOf': {'@type': 'WebSite', 'name': SITE_NAME, 'url': f'{site}/'},
         'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(items), 'itemListElement': [
             {'@type': 'ListItem', 'position': i + 1, 'url': f'{site}/{section}/{c.id}', 'name': c.title}
             for i, c in enumerate(items[:100])]}},
        _breadcrumbs(trail),
    ]
    return _render(page, title=data['title'], description=data['description'], url=url, body=''.join(parts),
                   json_ld=json_ld, noindex=not data['indexable'])


SECTION_NAV = {'exercises': 'Exercices corrigés', 'lessons': 'Cours', 'exams': 'Devoirs et examens'}


def _site_json_ld(site):
    return [
        {'@context': 'https://schema.org', '@type': 'WebSite', 'name': SITE_NAME, 'alternateName': 'fidni.fr',
         'url': f'{site}/', 'inLanguage': 'fr'},
        {'@context': 'https://schema.org', '@type': 'EducationalOrganization', 'name': SITE_NAME, 'url': f'{site}/',
         'logo': f'{site}/android-chrome-512x512.png', 'areaServed': 'MA'},
    ]


def listing_page(request, name):
    """Accueil (/) et listes (/exercises, /lessons, /exams) pré-remplis pour les moteurs de recherche."""
    from apps.things.models import Content

    page = _index_html()
    site = settings.FRONTEND_URL.rstrip('/')
    esc = html.escape

    if name == 'home':
        counts = {k: Content.objects.filter(type=k).count() for k in ('exercise', 'lesson', 'exam')}
        latest = {k: list(Content.objects.filter(type=k).order_by('-updated_at')[:8]) for k in ('exercise', 'lesson', 'exam')}
        blocks = []
        for kind, label in (('exercise', 'Derniers exercices corrigés'), ('lesson', 'Cours'), ('exam', 'Devoirs et examens')):
            section = SECTIONS[kind]
            blocks.append(f'<h2 style="font-size:21px;margin-top:28px"><a href="/{section}">{label}</a> '
                          f'<small>({counts[kind]})</small></h2><ul>'
                          + ''.join(f'<li><a href="/{section}/{c.id}">{esc(c.title)}</a></li>' for c in latest[kind])
                          + '</ul>')
        body = (f'<main style="{BODY_STYLE}">'
                '<h1 style="font-size:28px">Fidni : exercices de maths corrigés, cours et examens pour le lycée au Maroc</h1>'
                '<p>Fidni accompagne les lycéens marocains en mathématiques, du Tronc commun au 2ème Bac '
                '(Sciences mathématiques et Sciences physiques, option française). Exercices corrigés pas à pas, '
                'cours clairs, devoirs surveillés et sujets d’examen avec barème, suivi de ta progression, '
                'listes de révision et quiz pour mesurer ta maîtrise de chaque chapitre.</p>'
                + _nav_html() + _levels_html() + ''.join(blocks) + '</main>')
        return _render(page, title=HOME['title'], description=HOME['description'], url=f'{site}/',
                       body=body, json_ld=_site_json_ld(site))

    conf = LISTINGS.get(name)
    if conf is None:
        return _render(page, title='Page introuvable | Fidni', description='Cette page n’existe pas.',
                       url=f'{site}/', body='', status=404, noindex=True)
    groups = _grouped(conf['type'])
    total = sum(len(items) for _, chapters in groups for _, items in chapters)
    url = f'{site}/{name}'
    body = (f'<main style="{BODY_STYLE}"><h1 style="font-size:28px">{esc(conf["h1"])}</h1>'
            f'<p>{esc(conf["intro"])}</p><p>{total} disponibles.</p>' + _nav_html()
            + _links_html(name, groups, esc) + '</main>')
    items = [c for _, chapters in groups for _, lst in chapters for c in lst][:100]
    json_ld = [
        {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': conf['h1'], 'url': url,
         'description': conf['description'], 'inLanguage': 'fr',
         'isPartOf': {'@type': 'WebSite', 'name': SITE_NAME, 'url': f'{site}/'},
         'mainEntity': {'@type': 'ItemList', 'numberOfItems': total, 'itemListElement': [
             {'@type': 'ListItem', 'position': i + 1, 'url': f'{site}/{name}/{c.id}', 'name': c.title}
             for i, c in enumerate(items)]}},
        {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Accueil', 'item': f'{site}/'},
            {'@type': 'ListItem', 'position': 2, 'name': conf['h1'], 'item': url}]},
    ]
    return _render(page, title=conf['title'], description=conf['description'], url=url, body=body, json_ld=json_ld)
