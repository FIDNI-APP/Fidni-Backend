"""Plan du site pour les moteurs de recherche : https://api.fidni.fr/sitemap.xml

Déclaré dans le robots.txt de fidni.fr (un sitemap peut être hébergé sur un autre domaine s'il y est
annoncé). Contient les pages publiques et chaque exercice / leçon / examen, avec sa date de mise à jour.
Parcours n'y figure pas tant qu'il n'est pas publié.
"""
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import cache_page

PAGES_BY_TYPE = {'exercise': 'exercises', 'lesson': 'lessons', 'exam': 'exams'}
STATIC_PAGES = ['', '/exercises', '/lessons', '/exams', '/concours']


@cache_page(60 * 60)
def sitemap(request):
    from apps.things.models import Content

    site = settings.FRONTEND_URL.rstrip('/')
    urls = [(f'{site}{path}', None) for path in STATIC_PAGES]
    rows = Content.objects.order_by('-updated_at').values_list('id', 'type', 'updated_at')[:45000]
    # Pages par niveau et par chapitre (seulement celles qui ont du contenu).
    from apps.caracteristics.hubs import all_hubs
    urls.extend((f'{site}{path}', updated) for path, updated in all_hubs())
    for pk, kind, updated in rows:
        section = PAGES_BY_TYPE.get(kind)
        if section:
            urls.append((f'{site}/{section}/{pk}', updated))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, updated in urls:
        lastmod = f'<lastmod>{updated.date().isoformat()}</lastmod>' if updated else ''
        parts.append(f'<url><loc>{escape(loc)}</loc>{lastmod}</url>')
    parts.append('</urlset>')
    return HttpResponse('\n'.join(parts), content_type='application/xml; charset=utf-8')
