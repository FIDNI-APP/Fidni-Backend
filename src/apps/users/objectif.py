"""« Ton prochain objectif » de « Ma progression » (13/10/2026) : une seule priorité, expliquée, avec son action.

Déterministe et explicable : chaque objectif dit pourquoi (`pourquoi` : les observations), quoi faire (`action`,
`phrase`) et, sur la page, propose jusqu'à 5 exercices ciblés (exercices()).

Priorité des chapitres (champ `priorite`, qui ordonne aussi « Mes chapitres ») :
  DS dans 7 jours (ses chapitres d'abord ; tous maîtrisés → DS blanc) › à consolider (rechute d'abord) ›
  à renforcer › vérification due › en bonne voie › pas encore évalué (commencé, puis dans l'ordre du programme) ›
  maîtrisé (aller plus loin) › chapitres sans exercice.
Types : consolider, renforcer, verifier, continuer, evaluer, approfondir, ds_blanc, decouvrir.
"""
from datetime import date, timedelta

from django.db.models import Count, F, Q

from apps.interactions.models import UpcomingTest
from apps.users import maitrise_seuils as S

JOURS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')


def _jm(iso):
    return f'{iso[8:10]}/{iso[5:7]}' if iso else ''


def _rang(c):
    """Clé de priorité d'un chapitre (plus petit = plus urgent)."""
    e, d = c['etat'], c['durable']
    if not c.get('contents'):
        return (8, c['ordre'])
    if e == 'a_consolider':
        return (1, 0 if d['etat'] == 'n_a_pas_tenu' else 1, c['pct'] if c['pct'] is not None else 0, c['ordre'])
    if e == 'a_renforcer':
        return (2, c['pct'] if c['pct'] is not None else 0, c['ordre'])
    if e == 'bonne_voie' and d['etat'] == 'a_verifier' and d['due']:
        return (3, d['a_partir_du'] or '', c['ordre'])
    if e == 'bonne_voie':
        return (4, _neg_date(c['derniere_evaluation']), c['ordre'])
    if e == 'non_evalue' and c['commence']:
        return (5, _neg_date(c['derniere_evaluation']), c['ordre'])
    if e == 'non_evalue':
        return (6, c['ordre'])
    return (7, c['pct'] if c['pct'] is not None else 0, c['ordre'])


def _neg_date(iso):
    return -date.fromisoformat(iso).toordinal() if iso else 0


def _manque(c):
    return next((x for x in c['criteres'] if x['etat'] != 'ok'), None)


def _objectif_chapitre(c, level):
    """Objectif pour un chapitre, selon son état et ce qui lui manque."""
    e, d, pct, n = c['etat'], c['durable'], c['pct'], c['reussite']['questions']
    chapitre = {'id': c['id'], 'name': c['name'], 'hub_url': c['hub_url'], 'etat': e, 'en_progres': c['en_progres'],
                'quiz_ready': c['quiz_ready']}
    worst = (c.get('notions') or {}).get('worst') or []
    surtout = f'Surtout : {worst[0]["label"]} ({worst[0]["pct"]} %).' if worst else None
    review_ids = [r['id'] for r in c.get('review') or []]
    base = {'chapitre': chapitre, 'ds': None, 'secondaire': None}

    if not c.get('contents'):
        return {**base, 'type': 'decouvrir', 'titre': f'Découvre « {c["name"]} »',
                'phrase': 'Pas encore d’exercice sur ce chapitre : commence par le cours.',
                'pourquoi': ['Aucun exercice n’est encore publié pour ce chapitre à ton niveau.'],
                'action': {'kind': 'cours'}, 'cible': None}

    if e == 'a_consolider':
        faibles = [lvl for lvl in ('easy', 'medium', 'hard')
                   if (c['reussite']['par_difficulte'].get(lvl) or {}).get('questions', 0) >= 2
                   and (c['reussite']['par_difficulte'][lvl]['pct'] or 0) < S.SEUIL_BONNE_VOIE]
        cible_diff = faibles[:1] + [x for x in ('easy', 'medium') if x not in faibles[:1]] if faibles else ['medium', 'easy']
        pourquoi = [c['raison']]
        if pct is not None:
            pourquoi.append(f'{pct} % de réussite sur {n} questions.')
        if surtout:
            pourquoi.append(surtout)
        return {**base, 'type': 'consolider', 'titre': f'Consolide « {c["name"]} »',
                'phrase': 'Revois la méthode dans le cours, puis refais des exercices ciblés.',
                'pourquoi': pourquoi, 'action': {'kind': 'entrainer', 'difficulte': cible_diff[0]},
                'secondaire': {'kind': 'cours'},
                'cible': {'difficultes': cible_diff, 'n': S.OBJECTIF_EXERCICES, 'prefer': review_ids}}

    if e == 'a_renforcer':
        pourquoi = [f'{pct} % de réussite sur {n} questions : les erreurs reviennent souvent.']
        if surtout:
            pourquoi.append(surtout)
        return {**base, 'type': 'renforcer', 'titre': f'Reprends les bases de « {c["name"]} »',
                'phrase': 'Relis le cours, puis fais des exercices faciles avant de monter en difficulté.',
                'pourquoi': pourquoi, 'action': {'kind': 'cours'},
                'secondaire': {'kind': 'entrainer', 'difficulte': 'easy'},
                'cible': {'difficultes': ['easy', 'medium'], 'n': S.OBJECTIF_EXERCICES, 'prefer': review_ids}}

    if e == 'bonne_voie' and d['etat'] == 'a_verifier' and d['due']:
        reussis = [lvl for lvl in ('medium', 'easy', 'hard') if (c['reussite']['par_difficulte'].get(lvl) or {}).get('pct')]
        return {**base, 'type': 'verifier', 'titre': f'Vérifie que « {c["name"]} » est acquis',
                'phrase': f'Fais {S.VERIFIER_EXERCICES} exercices que tu n’as jamais faits, sans indice ni solution.',
                'pourquoi': [f'Tu as réussi ce chapitre ({pct} % sur {n} questions).' if pct is not None else
                             'Tu as réussi des questions de ce chapitre.',
                             'Pas encore revérifié sans aide sur d’autres questions, quelques jours plus tard : '
                             'c’est ce qui montre que c’est vraiment acquis.'],
                'action': {'kind': 'entrainer', 'difficulte': reussis[0] if reussis else 'medium'},
                'cible': {'difficultes': (reussis[:1] or ['medium']) + ['medium', 'hard'], 'n': S.VERIFIER_EXERCICES,
                          'exclure_vus': True}}

    if e == 'bonne_voie':
        m = _manque(c)
        cle = m['cle'] if m else ''
        cible = {'difficultes': ['medium', 'hard', 'easy'], 'n': S.OBJECTIF_EXERCICES}
        phrase = 'Continue avec des exercices du chapitre.'
        if cle == 'difficultes':
            niveaux = c['reussite']['par_difficulte']
            manquant = next((lvl for lvl in ('medium', 'hard') if not (niveaux.get(lvl) or {}).get('pct')), 'medium')
            cible['difficultes'] = [manquant, 'hard' if manquant == 'medium' else 'medium']
            phrase = f'Essaie des exercices {"moyens" if manquant == "medium" else "difficiles"}.'
        elif cle == 'synthese':
            cible['difficultes'] = ['hard', 'medium']
            phrase = 'Essaie un exercice difficile, où tu choisis toi-même la méthode.'
        elif cle == 'notions':
            cible['notions'] = c['notions_couvertes']['manquantes'][:3]
            phrase = 'Travaille les notions que tu n’as pas encore réussies.'
        elif cle == 'autonomie':
            phrase = 'Refais des exercices sans ouvrir l’indice ni la solution.'
        elif cle == 'durable' and d['etat'] == 'a_verifier':
            phrase = f'Continue ; tu pourras le revérifier à partir du {_jm(d["a_partir_du"])}.'
        pourquoi = [c['raison']]
        if c.get('recents') and c['en_progres']:
            pourquoi.append(f'{c["recents"]["pct"]} % sur tes {c["recents"]["questions"]} dernières questions.')
        return {**base, 'type': 'continuer', 'titre': f'Continue « {c["name"]} »', 'phrase': phrase,
                'pourquoi': pourquoi, 'action': {'kind': 'entrainer', 'difficulte': cible['difficultes'][0]},
                'cible': cible}

    if e == 'non_evalue':
        quiz = c['quiz_ready']
        return {**base, 'type': 'evaluer', 'titre': f'Évalue-toi sur « {c["name"]} »',
                'phrase': ('Passe le quiz du chapitre pour établir ton point de départ.' if quiz else
                           f'Fais {S.EVALUER_EXERCICES} exercices et dis pour chaque question si tu l’as réussie.'),
                'pourquoi': [c['raison'], 'Pas encore évalué ne veut pas dire en difficulté : il faut juste quelques '
                             'résultats pour savoir où tu en es.'],
                'action': {'kind': 'quiz' if quiz else 'entrainer', 'difficulte': 'easy'},
                'secondaire': {'kind': 'entrainer', 'difficulte': 'easy'} if quiz else {'kind': 'cours'},
                'cible': {'difficultes': ['easy', 'medium'], 'n': S.EVALUER_EXERCICES, 'evaluer': True}}

    # Maîtrisé : aller plus loin.
    deuxieme = bool(level and level.name.startswith('2ème'))
    return {**base, 'type': 'approfondir', 'titre': f'Va plus loin sur « {c["name"]} »',
            'phrase': 'Entraîne-toi sur des exercices difficiles, des devoirs ou des sujets du Bac.',
            'pourquoi': [c['raison']], 'action': {'kind': 'entrainer', 'difficulte': 'hard'},
            'secondaire': {'kind': 'nationaux' if deuxieme else 'devoirs'},
            'cible': {'difficultes': ['hard', 'medium'], 'n': S.OBJECTIF_EXERCICES}}


def choisir(user, chapters, level, today):
    """Pose `priorite` sur chaque chapitre et renvoie l'objectif (sans les exercices), ou None (pas de niveau, prof,
    aucun chapitre)."""
    order = sorted(chapters, key=_rang)
    for i, c in enumerate(order):
        c['priorite'] = i
    profile = getattr(user, 'profile', None)
    if level is None or getattr(profile, 'user_type', 'student') == 'teacher' or not chapters:
        return None
    by_id = {c['id']: c for c in chapters}
    test = (UpcomingTest.objects.filter(user=user, date__gte=today, date__lte=today + timedelta(days=S.DS_PRIORITE_JOURS))
            .order_by('date', 'id').prefetch_related('chapters').first())
    if test is not None:
        dans = [by_id[ch.id] for ch in test.chapters.all() if ch.id in by_id]
        jours = (test.date - today).days
        ds = {'id': test.id, 'date': test.date.isoformat(), 'jours': jours,
              'quand': 'aujourd’hui' if jours == 0 else 'demain' if jours == 1 else f'{JOURS[test.date.weekday()]}'}
        if dans and all(c['etat'] == 'maitrise' for c in dans):
            return {'type': 'ds_blanc', 'titre': 'Ton DS approche : fais un DS blanc',
                    'phrase': 'Tous les chapitres du DS sont maîtrisés : entraîne-toi en conditions réelles.',
                    'pourquoi': [f'DS {ds["quand"]} ({len(dans)} chapitres, tous maîtrisés).'],
                    'chapitre': None, 'action': {'kind': 'ds_blanc', 'test_id': test.id}, 'secondaire': None,
                    'ds': ds, 'cible': None}
        if dans:
            c = min(dans, key=_rang)
            obj = _objectif_chapitre(c, level)
            obj['ds'] = ds
            obj['titre'] = f'Pour ton DS de {ds["quand"]} : {obj["titre"][0].lower()}{obj["titre"][1:]}' \
                if jours > 1 else f'DS {ds["quand"]} : {obj["titre"][0].lower()}{obj["titre"][1:]}'
            obj['pourquoi'] = [f'« {c["name"]} » est le chapitre du DS le plus à travailler.'] + obj['pourquoi']
            return obj
    return _objectif_chapitre(order[0], level)


def exercices(user, obj, level):
    """Jusqu'à 5 exercices pour l'objectif (page « Ma progression » seulement : l'accueil ne les charge pas)."""
    from apps.interactions.devoirs import _for_you
    if not obj or not obj.get('cible') or not obj.get('chapitre'):
        return []
    from apps.users.maitrise import _notions_dispo
    cible, ch = obj['cible'], obj['chapitre']
    names = {ch['id']: ch['name']}
    common = dict(level=level, exclude_seen=bool(cible.get('exclure_vus')), prefer_ids=cible.get('prefer') or (),
                  exclude_ids=_tout_reussi(user))
    only = None
    if cible.get('notions'):
        dispo = _notions_dispo(level).get(ch['id'], {})
        only = {cid for sk in cible['notions'] for cid in dispo.get(sk, [])} or None
    n = cible.get('n') or S.OBJECTIF_EXERCICES
    if cible.get('evaluer'):
        # Point de départ : 1 facile + 2 moyens, complétés au besoin.
        rows = _for_you(user, [ch['id']], names, ['easy'], limit=1, **common)
        rows += _for_you(user, [ch['id']], names, ['medium'], limit=n - len(rows),
                         **{**common, 'exclude_ids': set(common['exclude_ids']) | {r['id'] for r in rows}})
        rows = [r for r in rows if r['difficulty'] in ('easy', 'medium')] + [r for r in rows if r['difficulty'] not in ('easy', 'medium')]
        return rows[:n]
    return _for_you(user, [ch['id']], names, cible.get('difficultes'), limit=n, only_ids=only, **common)


def _tout_reussi(user):
    """Contenus dont l'élève a réussi toutes les questions évaluées (sans « Réussi » du contenu) : pas proposés."""
    from apps.interactions.models import QuestionProgress
    return set(QuestionProgress.objects.filter(user=user).exclude(status='').values('object_id')
               .annotate(n=Count('id'), ok=Count('id', filter=Q(status='success'))).filter(ok=F('n'))
               .values_list('object_id', flat=True))
