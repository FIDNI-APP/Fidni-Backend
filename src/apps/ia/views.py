"""Pilotage › IA (administrateurs) : import d'un document par l'IA, correction des signalements par l'IA.

Les travaux longs (plusieurs minutes) tournent hors requête web (commande `ia_traiter`) ;
la page interroge leur état toutes les quelques secondes.
"""
import os
import subprocess
import sys

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.things.models import ContentReport
from apps.users.admin_dashboard import IsSuperuser

from . import client, consignes as ia_consignes, depot, documents, pipeline
from .client import IAErreur
from .models import IAFile, IAJob

MAX_EN_COURS = 3
INSTRUCTION_MAX = 4000
CREDIT_MAX = 120


def lancer(job):
    """Démarre le traitement dans un processus détaché (double fork : pas de processus zombie)."""
    if getattr(settings, 'IA_LANCEMENT', 'processus') != 'processus':
        return  # tests : le traitement est appelé directement
    manage = os.path.join(str(settings.BASE_DIR), 'manage.py')
    subprocess.Popen(['sh', '-c', f'"{sys.executable}" "{manage}" ia_traiter {int(job.pk)} &'],
                     start_new_session=True).wait()


def _occupe():
    pipeline.interrompus().update(status=IAJob.ERREUR, etape='',
                                  error='Travail interrompu (serveur redémarré ?) : le relancer.')
    return IAJob.objects.filter(status__in=[IAJob.EN_ATTENTE, IAJob.EN_COURS]).count() >= MAX_EN_COURS


def _resume(job):
    r = job.result or {}
    out = {
        'id': job.id, 'kind': job.kind, 'status': job.status, 'etape': job.etape, 'error': job.error,
        'created_at': job.created_at.isoformat(), 'updated_at': job.updated_at.isoformat(),
        'created_by': job.created_by.username if job.created_by else None,
        'document': job.options.get('document', ''),
        'usage': job.usage,
    }
    if job.kind == IAJob.IMPORT:
        out['fiches'] = [{'cle': f.get('cle'), 'titre': f.get('titre'), 'type': f.get('type')}
                         for f in r.get('fiches') or [] if isinstance(f, dict)]
        out['publies'] = r.get('publies') or []
        out['nb_doutes'] = len(r.get('doutes') or []) + len(r.get('problemes') or [])
        # Préparé par Claude (ia/depot.py, 14/10/2026) : ses commentaires sont les `doutes` ; `remplace` = contenu
        # déjà publié que ce brouillon met à jour (même clé).
        out['depot'] = job.options.get('depot') == 'claude'
        out['remplace'] = job.options.get('contenu') if job.options.get('remplacer') else None
        if out['depot'] and not out['created_by']:
            out['created_by'] = 'Claude'
    else:
        rep = job.report
        out['signalement'] = rep.id if rep else None
        out['fonde'] = r.get('fonde')
        out['contenu'] = {'id': rep.content_id, 'titre': rep.content.title} if rep else None
    return out


def _detail(job):
    out = _resume(job)
    r = job.result or {}
    out['options'] = {k: v for k, v in job.options.items() if k != 'instruction'}
    out['history'] = job.history
    if job.kind == IAJob.IMPORT:
        out.update({
            'doutes': r.get('doutes') or [], 'problemes': r.get('problemes') or [],
            'solutions_du_document': bool(r.get('solutions_du_document')),
            'controles': r.get('controles') or [], 'erreurs_figures': r.get('erreurs_figures') or [],
            'avertissements': r.get('avertissements') or [],
            'apercus': pipeline.apercus(job) if r.get('fiches') else [],
            'fichiers': [{'id': f.id, 'nom': f.name, 'mime': f.mime} for f in job.files.all()],
        })
        if out.get('depot'):  # brouillon de Claude : le résumé de sa carte (établissement, compteurs…)
            out['carte'] = depot.carte(job)
    else:
        out.update({k: r.get(k) for k in ('explication', 'doutes', 'modifications', 'erreurs')})
        rep = job.report
        if rep:
            out['report'] = {'id': rep.id, 'reason': rep.get_reason_display(), 'item_label': rep.item_label,
                             'description': rep.description, 'status': rep.status}
    return out


@api_view(['GET'])
@permission_classes([IsSuperuser])
def jobs(request):
    """Travaux récents, et si l'IA est prête (clé configurée)."""
    _occupe()
    # Les brouillons de Claude ont leur onglet (« À valider », brouillons()).
    qs = IAJob.objects.select_related('created_by', 'report__content').exclude(pk__in=depot.travaux().values('pk'))
    kind = request.query_params.get('kind')
    if kind in (IAJob.IMPORT, IAJob.SIGNALEMENT):
        qs = qs.filter(kind=kind)
    return Response({
        'configuree': client.configuree(),
        'modele': getattr(settings, 'ANTHROPIC_MODEL', ''),
        'results': [_resume(j) for j in qs[:60]],
    })


GROUPES = {
    'a_valider': [IAJob.PRET, IAJob.ERREUR, IAJob.EN_ATTENTE, IAJob.EN_COURS],
    'publies': [IAJob.PUBLIE],
    'rejetes': [IAJob.REJETE],
}


@api_view(['GET'])
@permission_classes([IsSuperuser])
def brouillons(request):
    """Onglet « À valider » : les contenus préparés par Claude, en cartes. ?statut=a_valider|publies|rejetes"""
    _occupe()
    statut = request.query_params.get('statut') or 'a_valider'
    if statut not in GROUPES:
        return Response({'detail': 'statut : ' + ', '.join(GROUPES)}, status=status.HTTP_400_BAD_REQUEST)
    qs = depot.travaux()
    # Dans l'ordre du dépôt pour relire une série comme elle se lit ; les traités, du plus récent au plus ancien.
    lignes = qs.filter(status__in=GROUPES[statut]).order_by('created_at' if statut == 'a_valider' else '-updated_at')
    return Response({
        'compte': {k: qs.filter(status__in=v).count() for k, v in GROUPES.items()},
        'ia_configuree': client.configuree(),
        'results': [depot.carte(j) for j in lignes[:150]],
    })


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([MultiPartParser, FormParser])
def nouvel_import(request):
    """Envoi d'un document (PDF, Word, ou images) et des options ; l'IA rédige le brouillon."""
    if not client.configuree():
        return Response({'detail': 'IA non configurée sur le serveur.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    d = request.data
    origine = d.get('origine')
    if origine not in pipeline.ORIGINES:
        return Response({'origine': 'Préciser les droits du document.'}, status=status.HTTP_400_BAD_REQUEST)
    credit = (d.get('credit') or '').strip()
    if len(credit) > CREDIT_MAX:
        return Response({'credit': f'{CREDIT_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    consignes = (d.get('consignes') or '').strip()
    if len(consignes) > INSTRUCTION_MAX:
        return Response({'consignes': f'{INSTRUCTION_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    fichiers = request.FILES.getlist('fichiers')
    lus = [(f.name, documents.type_mime(f.name, f.content_type), f.read()) for f in fichiers]
    try:
        documents.controler(lus)
    except IAErreur as exc:
        return Response({'fichiers': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    niveau = (d.get('niveau') or '').strip()
    type_ = d.get('type') if d.get('type') in ('exercice', 'examen', 'lecon') else ''
    job = IAJob.objects.create(
        kind=IAJob.IMPORT, created_by=request.user,
        options={'origine': origine, 'credit': credit, 'consignes': consignes, 'niveau': niveau[:60],
                 'type': type_, 'document': ', '.join(n for n, _, _ in lus)[:250],
                 # Programme envoyé à l'IA : niveau imposé + niveau précédent (aucun : les 4), fixé pour tout le travail.
                 'niveaux': ia_consignes.niveaux_du_travail([niveau] if niveau else [])},
    )
    for nom, mime, data in lus:
        IAFile.objects.create(job=job, name=nom[:255], mime=mime, data=data)
    lancer(job)
    return Response(_resume(job), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsSuperuser])
def corriger_signalement(request, pk):
    """L'IA examine un signalement et propose une correction (rien n'est modifié avant votre accord)."""
    report = get_object_or_404(ContentReport, pk=pk)
    if not client.configuree():
        return Response({'detail': 'IA non configurée sur le serveur.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    instruction = (request.data.get('instruction') or '').strip()[:INSTRUCTION_MAX]
    # Programme envoyé à l'IA : niveaux du contenu signalé + leur niveau précédent.
    options = {'niveaux': ia_consignes.niveaux_du_travail(report.content.class_levels.values_list('name', flat=True))}
    if instruction:
        options['instruction'] = instruction
    job = IAJob.objects.create(kind=IAJob.SIGNALEMENT, created_by=request.user, report=report, options=options)
    lancer(job)
    return Response(_resume(job), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsSuperuser])
def signalement_jobs(request, pk):
    """Dernière proposition de l'IA pour ce signalement (s'il y en a une)."""
    job = IAJob.objects.filter(kind=IAJob.SIGNALEMENT, report_id=pk).first()
    return Response(_detail(job) if job else None)


@api_view(['GET'])
@permission_classes([IsSuperuser])
def job_detail(request, pk):
    _occupe()
    return Response(_detail(get_object_or_404(IAJob, pk=pk)))


def _pret(job):
    if job.status != IAJob.PRET:
        return Response({'detail': 'Ce travail n’est pas prêt (ou a déjà été traité).'}, status=status.HTTP_409_CONFLICT)
    return None


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_corriger(request, pk):
    """Brouillon d'import : demander une modification à l'IA (« la question 2 est mal recopiée… »)."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    if (bloque := _pret(job)):
        return bloque
    if (job.result or {}).get('editions'):
        return Response({'detail': 'Ce brouillon a été modifié dans l’éditeur : la correction par l’IA repartirait de la '
                                   'version d’origine. Continue dans l’éditeur.'}, status=status.HTTP_409_CONFLICT)
    instruction = (request.data.get('instruction') or '').strip()
    if not instruction:
        return Response({'instruction': 'Écrire la demande.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(instruction) > INSTRUCTION_MAX:
        return Response({'instruction': f'{INSTRUCTION_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    job.options['instruction'] = instruction
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username, 'texte': instruction})
    job.status, job.etape, job.error = IAJob.EN_ATTENTE, 'En attente', ''
    job.save()
    lancer(job)
    return Response(_resume(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_relancer(request, pk):
    """Relancer un travail en erreur (crédit rechargé, coupure…)."""
    job = get_object_or_404(IAJob, pk=pk)
    if job.status != IAJob.ERREUR:
        return Response({'detail': 'Seul un travail en erreur se relance.'}, status=status.HTTP_409_CONFLICT)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    job.status, job.etape, job.error = IAJob.EN_ATTENTE, 'En attente', ''
    job.save()
    lancer(job)
    return Response(_resume(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_publier(request, pk):
    """Publier le brouillon. Corps : {"doublon_ok": bool} (`a_verifier` des anciens fronts : ignoré)."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    if (bloque := _pret(job)):
        return bloque
    doublon_ok = request.data.get('doublon_ok', False)
    if not isinstance(doublon_ok, bool):
        return Response({'detail': 'doublon_ok : true ou false'}, status=status.HTTP_400_BAD_REQUEST)
    doublon_ok = doublon_ok or bool(job.options.get('doublon_ignore'))  # doublon déjà écarté (job_doublon)
    try:
        publies = pipeline.publier(job, doublon_ok=doublon_ok, auteur=request.user)
    except (IAErreur, Exception) as exc:  # FicheError, contrôle refusé : le brouillon reste intact
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    job.result['publies'] = publies
    job.status = IAJob.PUBLIE
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username,
                        'texte': 'Publié'})
    job.save()
    return Response(_detail(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_doublon(request, pk):
    """« Ignorer le doublon » : {"ignorer": bool}. Le doublon probable n'empêche plus de publier ce brouillon (gardé
    tant que ce brouillon existe ; un nouveau dépôt de la même fiche est un nouveau brouillon, contrôlé à nouveau)."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    if job.status not in (IAJob.PRET, IAJob.ERREUR):
        return Response({'detail': 'Ce brouillon a déjà été traité.'}, status=status.HTTP_409_CONFLICT)
    ignorer = request.data.get('ignorer')
    if not isinstance(ignorer, bool):
        return Response({'detail': 'ignorer : true ou false'}, status=status.HTTP_400_BAD_REQUEST)
    if ignorer:
        job.options['doublon_ignore'] = True
    else:
        job.options.pop('doublon_ignore', None)
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username,
                        'texte': 'Doublon ignoré' if ignorer else 'Doublon de nouveau signalé'})
    job.save()
    return Response(_detail(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_appliquer(request, pk):
    """Signalement : appliquer la correction proposée (`a_verifier` des anciens fronts : ignoré)."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.SIGNALEMENT)
    if (bloque := _pret(job)):
        return bloque
    try:
        pipeline.appliquer(job, auteur=request.user)
    except IAErreur as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
    job.status = IAJob.APPLIQUE
    job.save()
    return Response(_detail(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_rejeter(request, pk):
    job = get_object_or_404(IAJob, pk=pk)
    if job.status not in (IAJob.PRET, IAJob.ERREUR):
        return Response({'detail': 'Ce travail ne peut plus être rejeté.'}, status=status.HTTP_409_CONFLICT)
    job.status = IAJob.REJETE
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username, 'texte': 'Rejeté'})
    job.save()
    job.files.all().delete()  # le document n'est plus utile
    return Response(_resume(job))


def _fiche_du_job(job, cle):
    fiches = [f for f in (job.result or {}).get('fiches') or [] if isinstance(f, dict)]
    if not fiches:
        return None
    return next((f for f in fiches if f.get('cle') == cle), None) if cle else fiches[0]


def _pour_editeur(job, fiche):
    """Le brouillon au format d'un contenu (GET /contents/<id>/) pour l'éditeur du site : sa version modifiée s'il y
    en a une, sinon la fiche convertie ; figures en data URI (affichables sans être publiées)."""
    from apps.caracteristics.models import Chapter, ClassLevel, School, Subject, Theorem
    from apps.things import importing
    src_map = pipeline.figures_data_uri(job)
    e = ((job.result or {}).get('editions') or {}).get(fiche.get('cle'))
    if e:
        def noms(model, ids):
            return [{'id': o.id, 'name': o.name} for o in model.objects.filter(pk__in=ids or [])]
        school = School.objects.filter(pk=e.get('school')).first() if e.get('school') else None
        return {
            'type': importing.TYPES.get(fiche.get('type')), 'title': e['title'], 'difficulty': e.get('difficulty'),
            'class_levels': noms(ClassLevel, e.get('class_levels')), 'chapters': noms(Chapter, e.get('chapters')),
            'theorems': noms(Theorem, e.get('theorems')),
            'subject': ({'id': s.id, 'name': s.name} if (s := Subject.objects.filter(pk=e.get('subject')).first()) else None),
            'school': {'id': school.id, 'name': school.name, 'city': school.city} if school else None,
            'duration_minutes': e.get('duration_minutes'), 'is_national_exam': bool(e.get('is_national_exam')),
            'national_year': e.get('national_year'),
            'json_content': importing.remplacer_sources(e['json_content'], src_map), 'edite': True,
        }
    _, _, res = importing.check_against_db(fiche)
    ex = fiche.get('examen') or {}
    school = res.get('school')
    return {
        'type': importing.TYPES.get(fiche.get('type')), 'title': fiche.get('titre') or '',
        'difficulty': importing.DIFFICULTIES.get(fiche.get('difficulte')),
        'class_levels': [{'id': o.id, 'name': o.name} for o in res.get('levels') or []],
        'chapters': [{'id': o.id, 'name': o.name} for o in res.get('chapters') or []],
        'theorems': [{'id': o.id, 'name': o.name} for o in res.get('theorems') or []],
        'subject': {'id': res['subject'].id, 'name': res['subject'].name} if res.get('subject') else None,
        'school': {'id': school.id, 'name': school.name, 'city': school.city} if school else None,
        'duration_minutes': ex.get('duree_minutes'), 'is_national_exam': bool(ex.get('national')),
        'national_year': ex.get('annee'),
        'json_content': importing.to_structure(fiche, src_map), 'edite': False,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_editeur(request, pk):
    """Modifier un brouillon à la main dans l'éditeur du site (Pilotage › À valider, Natsu 15/10/2026) : GET le donne
    au format d'un contenu, POST (même corps que POST /contents/) enregistre la version modifiée dans le brouillon
    (result['editions'][clé]) ; « Valider et publier » publie ensuite cette version. ?fiche=<clé> (défaut : la première)."""
    import json
    from apps.caracteristics.models import Chapter, ClassLevel, School, Subject, Theorem
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    fiche = _fiche_du_job(job, request.query_params.get('fiche'))
    if fiche is None:
        return Response({'detail': 'Fiche introuvable dans ce brouillon.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(_pour_editeur(job, fiche))
    if (bloque := _pret(job)):
        return bloque
    d = request.data if isinstance(request.data, dict) else {}
    title = str(d.get('title') or '').strip()
    st = d.get('json_content')
    erreurs = {}
    if not 3 <= len(title) <= 200:
        erreurs['title'] = 'Un titre de 3 à 200 caractères.'
    if not isinstance(st, dict) or not (isinstance(st.get('blocks'), list) or isinstance(st.get('sections'), list)):
        erreurs['json_content'] = 'Contenu illisible.'

    def ids(cle, model):
        v = d.get(cle) or []
        if not isinstance(v, list) or not all(isinstance(x, int) for x in v):
            erreurs[cle] = 'Liste d’identifiants attendue.'
            return []
        ok = set(model.objects.filter(pk__in=v).values_list('pk', flat=True))
        if len(ok) != len(set(v)):
            erreurs[cle] = 'Identifiant inconnu.'
        return sorted(ok)

    levels, chapters, theorems = ids('class_levels', ClassLevel), ids('chapters', Chapter), ids('theorems', Theorem)
    if not levels:
        erreurs.setdefault('class_levels', 'Au moins un niveau.')
    if not chapters:
        erreurs.setdefault('chapters', 'Au moins un chapitre.')
    kind = pipeline.importing.TYPES.get(fiche.get('type'))
    diff = d.get('difficulty')
    if kind != 'lesson' and diff not in ('easy', 'medium', 'hard'):
        erreurs['difficulty'] = 'Facile, moyen ou difficile.'
    school = d.get('school')
    if school is not None and not (isinstance(school, int) and School.objects.filter(pk=school).exists()):
        erreurs['school'] = 'Établissement inconnu.'
    subject = d.get('subject')
    if subject is not None and not (isinstance(subject, int) and Subject.objects.filter(pk=subject).exists()):
        erreurs['subject'] = 'Matière inconnue.'
    if erreurs:
        return Response(erreurs, status=status.HTTP_400_BAD_REQUEST)
    # Les figures du brouillon (data URI pour l'éditeur) redeviennent « figures/nom » : publiées avec le contenu.
    inverse = {uri: rel for rel, uri in pipeline.figures_data_uri(job).items()}
    texte = json.dumps(st, ensure_ascii=False)
    for uri, rel in inverse.items():
        texte = texte.replace(uri, rel)
    if 'data:image' in texte:
        return Response({'json_content': 'Image collée dans le texte : ajoute-la avec le bouton image de l’éditeur.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(texte) > 2_000_000:
        return Response({'json_content': 'Contenu trop long.'}, status=status.HTTP_400_BAD_REQUEST)
    noms_niveaux = list(ClassLevel.objects.filter(pk__in=levels).values_list('name', flat=True))
    noms_chapitres = [c.name for c in Chapter.objects.filter(pk__in=chapters)]
    job.result.setdefault('editions', {})[fiche['cle']] = {
        'title': title, 'difficulty': diff if kind != 'lesson' else None, 'subject': subject,
        'class_levels': levels, 'chapters': chapters, 'theorems': theorems, 'school': school,
        'subfields': [x for x in (d.get('subfields') or []) if isinstance(x, int)],
        'duration_minutes': d.get('duration_minutes') if isinstance(d.get('duration_minutes'), int) else None,
        'is_national_exam': bool(d.get('is_national_exam')),
        'national_year': d.get('national_year') if isinstance(d.get('national_year'), int) else None,
        'json_content': json.loads(texte),
        'niveaux': noms_niveaux, 'chapitres': noms_chapitres,
        'theoremes_noms': list(Theorem.objects.filter(pk__in=theorems).values_list('name', flat=True)),
        'par': request.user.username, 'le': timezone.now().isoformat(),
    }
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username,
                        'texte': 'Modifié dans l’éditeur'})
    job.save()
    return Response({'ok': True, 'id': job.id})
