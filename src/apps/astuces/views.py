"""API des astuces (bêta du 27/11/2026).

GET    /api/astuces/?niveau=<nom|id>  → {astuces, filtres, ouvert, peut_modifier}
POST   /api/astuces/                  → nouvelle astuce (équipe)
GET    /api/astuces/<slug>/           → une astuce
PATCH  /api/astuces/<slug>/           → modifier (équipe) — le site fait foi ensuite (charger_astuces ne l'écrase plus)
DELETE /api/astuces/<slug>/           → retirer (équipe) : supprimée si créée sur le site, sinon masquée
GET    /api/astuces/etat/             → {ouvert, peut_modifier} (menu du site)
PATCH  /api/astuces/etat/  {ouvert}   → montrer la section à tous les membres, ou la garder pour l'équipe

Lecture : l'équipe toujours ; les autres seulement quand la section est ouverte (Natsu, 27/11/2026 : « un bouton admin
pour activer ou désactiver la vue pour les autres utilisateurs »). L'équipe voit aussi les astuces masquées.
« Sur Fidni » : une référence = {cle, bloc} (import) ou {id, question « 3.1 », partie} (saisie sur le site) ; elle devient
un lien vers la question, numérotée comme le site. Une référence introuvable est ignorée à l'affichage.
"""
import re
import unicodedata
from collections import Counter

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.caracteristics import programme
from apps.caracteristics.models import Chapter, ClassLevel
from apps.things.models import Content
from config.permissions import is_admin

from .models import Astuce, ReglageAstuces

URL_TYPE = {'exercise': '/exercises', 'exam': '/exams', 'lesson': '/lessons'}
TEXTES = ('titre', 'resume', 'type_question', 'technique', 'pourquoi', 'exemple_enonce', 'exemple_solution', 'piege')
LONGUEURS = {'titre': 200, 'resume': 300, 'type_question': 120, 'technique': 80}
TEXTE_MAX = 8000


def _ancre(path):
    """Même ancre que le front (ExerciseRenderer.questionAnchor)."""
    return 'question-' + ''.join(c if c.isalnum() or c in '_-' else '-' for c in path)


def _questions(structure):
    """[(chemin, numéro, partie, id du bloc)] dans l'ordre du site (lib/reportTargets.questionNumbering)."""
    out, partie, parties, q = [], None, 0, 0
    for b in (structure or {}).get('blocks') or []:
        if b.get('type') == 'section':
            parties += 1
            partie, q = parties, 0
            continue
        if b.get('type') != 'question':
            continue
        q += 1
        subs = [s for s in b.get('subQuestions') or [] if s.get('id')]
        if not subs:
            out.append((b['id'], str(q), partie, b.get('id')))
        for k, s in enumerate(subs, 1):
            out.append((f"{b['id']}.{s['id']}", f'{q}.{k}', partie, s['id']))
            if k == 1:
                out.append((f"{b['id']}.{s['id']}", str(q), partie, b.get('id')))  # « question 3 » = sa première sous-question
    return out


def numero_question(structure, bloc):
    """(chemin, numéro, partie) de la question dont l'id de bloc est `bloc`."""
    for chemin, num, partie, b in _questions(structure):
        if b == bloc:
            return chemin, num, partie
    return None


def par_numero(structure, numero, partie=None):
    """(chemin, numéro, partie) de la question « 3.1 » (dans la partie `partie` d'un devoir si elle est donnée)."""
    numero = str(numero).strip().replace(',', '.')
    for chemin, num, p, _ in _questions(structure):
        if num == numero and (not partie or p == int(partie)):
            return chemin, num, p
    return None


def _contenus(astuces):
    cles, ids = set(), set()
    for a in astuces:
        for r in a.sur_le_site or []:
            if r.get('cle'):
                cles.add(r['cle'])
            if str(r.get('id') or '').isdigit():
                ids.add(int(r['id']))
    par_cle, par_id = {}, {}
    if cles:
        for c in Content.objects.filter(json_content__import__cle__in=list(cles)).only('id', 'type', 'title', 'json_content'):
            par_cle[(c.json_content.get('import') or {}).get('cle')] = c
    if ids:
        par_id = {c.id: c for c in Content.objects.filter(id__in=ids).only('id', 'type', 'title', 'json_content')}
    return par_cle, par_id


def _lien(r, par_cle, par_id):
    """Une référence → lien vers la question (None si le contenu est introuvable)."""
    c = par_cle.get(r.get('cle')) or (par_id.get(int(r['id'])) if str(r.get('id') or '').isdigit() else None)
    if c is None:
        return None
    if r.get('bloc'):
        num = numero_question(c.json_content, r['bloc'])
    elif r.get('question'):
        num = par_numero(c.json_content, r['question'], r.get('partie'))
    else:
        num = None
    lien = {'contenu': c.id, 'type': c.type, 'titre': c.title, 'url': f"{URL_TYPE.get(c.type, '/exercises')}/{c.id}"}
    if num:
        chemin, numero, partie = num
        lien.update(question=numero, exercice=partie, url=lien['url'] + '#' + _ancre(chemin))
    if r.get('note'):
        lien['note'] = r['note']
    return lien


def _liens(a, par_cle, par_id):
    return [li for li in (_lien(r, par_cle, par_id) for r in a.sur_le_site or []) if li]


def _carte(a, par_cle, par_id, rangs, equipe=False):
    carte = {
        'slug': a.slug, 'titre': a.titre, 'resume': a.resume,
        'niveau': a.niveau.name, 'chapitre': a.chapitre.name, 'rang_chapitre': rangs.get(a.chapitre.name, 99),
        'type_question': a.type_question, 'technique': a.technique,
        'signaux': a.signaux, 'pourquoi': a.pourquoi, 'methode': a.methode,
        'exemple': {'enonce': a.exemple_enonce, 'solution': a.exemple_solution},
        'piege': a.piege, 'sur_le_site': _liens(a, par_cle, par_id), 'ordre': a.ordre,
    }
    if equipe:
        # Pour l'éditeur : l'état, et chaque référence au format « id + numéro » (une référence d'import y est traduite).
        refs = []
        for r in a.sur_le_site or []:
            li = _lien(r, par_cle, par_id)
            refs.append({'id': li['contenu'], 'question': li.get('question') or '', 'partie': li.get('exercice'),
                         'note': r.get('note') or '', 'titre': li['titre']} if li else
                        {'id': r.get('id') or '', 'question': r.get('question') or '', 'partie': r.get('partie'),
                         'note': r.get('note') or '', 'introuvable': True})
        carte.update(publie=a.publie, source=a.source, references=refs,
                     modifiee_le=a.modifiee_le.isoformat() if a.modifiee_le else None,
                     modifiee_par=a.modifiee_par.username if a.modifiee_par_id else None)
    return carte


def _lecture_permise(request):
    return is_admin(request.user) or ReglageAstuces.courant().ouvert_a_tous


def _refus():
    return Response({'detail': 'Les astuces ne sont pas encore ouvertes.'}, status=status.HTTP_403_FORBIDDEN)


def _slug(titre):
    s = unicodedata.normalize('NFKD', re.sub(r'\$[^$]*\$', '', titre)).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:70] or 'astuce'
    base, n = s, 2
    while Astuce.objects.filter(slug=s).exists():
        s, n = f'{base}-{n}', n + 1
    return s


def _appliquer(a, data):
    """Champs envoyés par l'éditeur → astuce (sans enregistrer). Renvoie un message d'erreur ou None."""
    for k in TEXTES:
        if k in data:
            v = str(data[k] or '').strip()
            if len(v) > LONGUEURS.get(k, TEXTE_MAX):
                return f'« {k} » est trop long.'
            setattr(a, k, v)
    for k in ('signaux', 'methode'):
        if k in data:
            items = [str(x).strip() for x in (data[k] or []) if str(x or '').strip()]
            if len(items) > 15 or any(len(x) > 2000 for x in items):
                return f'« {k} » : trop d’éléments ou trop longs.'
            setattr(a, k, items)
    if 'sur_le_site' in data:
        refs = []
        for r in (data['sur_le_site'] or [])[:12]:
            if r.get('cle'):
                refs.append({k: r[k] for k in ('cle', 'bloc', 'note') if r.get(k)})
                continue
            m = re.search(r'(\d+)', str(r.get('id') or ''))
            if not m:
                continue
            ref = {'id': int(m.group(1))}
            if str(r.get('question') or '').strip():
                ref['question'] = str(r['question']).strip()[:10]
            if str(r.get('partie') or '').isdigit():
                ref['partie'] = int(r['partie'])
            if str(r.get('note') or '').strip():
                ref['note'] = str(r['note']).strip()[:200]
            refs.append(ref)
        a.sur_le_site = refs
    if 'publie' in data:
        a.publie = bool(data['publie'])
    if 'chapitre' in data or 'niveau' in data:
        niveau = ClassLevel.objects.filter(name=data.get('niveau') or (a.niveau.name if a.niveau_id else '')).first()
        if not niveau:
            return 'Niveau inconnu.'
        chapitre = Chapter.objects.filter(name=data.get('chapitre') or a.chapitre.name, class_levels=niveau).first()
        if not chapitre:
            return 'Chapitre inconnu pour ce niveau.'
        a.niveau, a.chapitre = niveau, chapitre
    if not a.titre:
        return 'Le titre est obligatoire.'
    if not (a.type_question and a.technique):
        return 'Le type de question et la technique sont obligatoires.'
    return None


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def liste(request):
    equipe = is_admin(request.user)
    if request.method == 'POST':
        if not equipe:
            return Response(status=status.HTTP_403_FORBIDDEN)
        a = Astuce(source='admin', publie=True, ordre=9999)
        erreur = _appliquer(a, {'niveau': '2ème Bac SM', **request.data})
        if erreur:
            return Response({'detail': erreur}, status=status.HTTP_400_BAD_REQUEST)
        a.slug = _slug(a.titre)
        a.modifiee_le, a.modifiee_par = timezone.now(), request.user
        a.save()
        par_cle, par_id = _contenus([a])
        return Response(_carte(a, par_cle, par_id, programme.rang(a.niveau.name), True), status=status.HTTP_201_CREATED)

    if not _lecture_permise(request):
        return _refus()
    qs = Astuce.objects.select_related('niveau', 'chapitre', 'modifiee_par')
    if not equipe:
        qs = qs.filter(publie=True)
    niveau = request.query_params.get('niveau')
    if niveau:
        qs = qs.filter(niveau_id=int(niveau)) if niveau.isdigit() else qs.filter(niveau__name=niveau)
    astuces = list(qs)
    par_cle, par_id = _contenus(astuces)
    rangs_par_niveau = {}
    cartes = []
    for a in astuces:
        rangs = rangs_par_niveau.setdefault(a.niveau.name, programme.rang(a.niveau.name))
        cartes.append(_carte(a, par_cle, par_id, rangs, equipe))
    cartes.sort(key=lambda c: (c['niveau'], c['rang_chapitre'], c['ordre']))
    chapitres = Counter((c['rang_chapitre'], c['chapitre']) for c in cartes)
    reponse = {
        'astuces': cartes,
        'ouvert': ReglageAstuces.courant().ouvert_a_tous,
        'peut_modifier': equipe,
        'filtres': {
            'niveaux': sorted({c['niveau'] for c in cartes}),
            'chapitres': [{'nom': nom, 'nombre': n} for (_, nom), n in sorted(chapitres.items())],
            'types': [{'nom': k, 'nombre': n} for k, n in sorted(Counter(c['type_question'] for c in cartes).items())],
            'techniques': [{'nom': k, 'nombre': n} for k, n in Counter(c['technique'] for c in cartes).most_common()],
        },
    }
    if equipe:
        # Chapitres proposés dans l'éditeur (ordre du programme).
        reponse['chapitres_niveau'] = [c.name for c in programme.chapitres_du_niveau('2ème Bac SM')]
    return Response(reponse)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def detail(request, slug):
    equipe = is_admin(request.user)
    if request.method != 'GET' and not equipe:
        return Response(status=status.HTTP_403_FORBIDDEN)
    if not _lecture_permise(request):
        return _refus()
    qs = Astuce.objects.select_related('niveau', 'chapitre', 'modifiee_par')
    a = get_object_or_404(qs if equipe else qs.filter(publie=True), slug=slug)
    if request.method == 'DELETE':
        if a.source == 'admin':
            a.delete()
        else:
            # Venue du fichier : masquée (supprimée, charger_astuces la recréerait au prochain démarrage).
            a.publie, a.modifiee_le, a.modifiee_par = False, timezone.now(), request.user
            a.save(update_fields=['publie', 'modifiee_le', 'modifiee_par'])
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == 'PATCH':
        erreur = _appliquer(a, request.data)
        if erreur:
            return Response({'detail': erreur}, status=status.HTTP_400_BAD_REQUEST)
        a.modifiee_le, a.modifiee_par = timezone.now(), request.user
        a.save()
    par_cle, par_id = _contenus([a])
    return Response(_carte(a, par_cle, par_id, programme.rang(a.niveau.name), equipe))


@api_view(['GET', 'PATCH'])
@permission_classes([AllowAny])
def etat(request):
    reglage = ReglageAstuces.courant()
    equipe = is_admin(request.user)
    if request.method == 'PATCH':
        if not equipe:
            return Response(status=status.HTTP_403_FORBIDDEN)
        reglage.ouvert_a_tous = bool(request.data.get('ouvert'))
        reglage.modifie_par = request.user
        reglage.save()
    return Response({'ouvert': reglage.ouvert_a_tous, 'peut_modifier': equipe})
