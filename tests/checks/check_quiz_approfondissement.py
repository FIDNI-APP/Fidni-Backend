"""Deux quiz par chapitre (31/10/2026) : le quiz du cours et l'approfondissement (vrais problèmes en QCM, pièges).

On vérifie que les deux quiz d'un même (chapitre, niveau) ne se mélangent jamais : import (« type » du fichier, énoncés
plus longs, doublons cherchés dans le bon quiz, type inconnu refusé), Pilotage › Quiz (onglet par type, compteurs de
l'autre quiz, validation et mise en ligne séparées, annonce distincte), passage élève (tirage, reprise, envoi, dernier
résultat par type, les deux en même temps), et que la maîtrise (« Ma progression ») ne lit que le quiz du cours.
"""
import io
import json
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-quiz-approfondissement.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.skilliq import constats  # noqa: E402
from apps.skilliq.models import QuizEnCours, SkillAssessment, SkillQuestion  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


sm = ClassLevel.objects.get(name='2ème Bac SM')
lim = Chapter.objects.get(name='Limites et continuité')
TVI = 'Théorème des valeurs intermédiaires (TVI)'
admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
cl = APIClient()
cl.force_authenticate(admin)


def eleve(nom):
    u = User.objects.create_user(nom, f'{nom}@x.fr', 'Motdepasse-solide-42')
    u.profile.class_level = sm
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return u, c


u, el = eleve('eleve')


def q(texte, bonne='$\\ell = 2$', **kw):
    return {'question': texte, 'bonne': bonne, 'distracteurs': ['$\\ell = 0$', '$\\ell = 1$', '$\\ell = +\\infty$'],
            'explication': 'Piège : confondre la limite de la suite et celle de la fonction.', 'difficulte': 'hard',
            'cible': 'erreur classique', 'theoremes': [TVI], **kw}


# ── Import : « type » du fichier
COURS_Q = [q(f'Cours {i} : quelle hypothèse du TVI ?') for i in range(5)]
LONG = 'Problème : ' + 'soit $f$ continue sur $[0\\,;1]$, ' * 30 + 'que vaut $\\ell$ ?'  # ~1000 caractères
PROF_Q = [q(f'Problème {i} : $u_{{n+1}} = f(u_n)$, $u_0 = 1$. Que vaut $\\ell$ ?') for i in range(5)] + [q(LONG)]
check('énoncé long : refusé au quiz du cours, admis à l’approfondissement', 700 < len(LONG) <= 1400
      and constats.controler(q(LONG))[1] == 'texte trop long' and constats.controler(q(LONG), 'approfondissement')[0])
constats.importer({'niveau': sm.name, 'chapitres': [{'chapitre': lim.name, 'questions': COURS_Q}]})
chemin = os.path.join(tempfile.gettempdir(), 'fidni-quiz-approfondissement.json')
with open(chemin, 'w', encoding='utf-8') as f:
    json.dump({'niveau': sm.name, 'type': 'approfondissement', 'chapitres': [
        {'chapitre': lim.name, 'questions': [*PROF_Q, COURS_Q[0]]}]}, f, ensure_ascii=False)
sortie = io.StringIO()
call_command('quiz_importer', chemin, stdout=sortie)
cours = SkillQuestion.objects.filter(chapter=lim, class_level=sm, type='cours')
prof = SkillQuestion.objects.filter(chapter=lim, class_level=sm, type='approfondissement')
check('import : chaque fichier remplit son quiz (texte du cours admis dans l’approfondissement)',
      cours.count() == 5 and prof.count() == 7, (cours.count(), prof.count()))
check('import : brouillons à relire, hors ligne', all(x.a_relire and not x.is_active and x.source == 'claude'
                                                       for x in [*cours, *prof]))
check('bilan de l’import : l’approfondissement nommé', 'Limites et continuité (2ème Bac SM) — approfondissement : 7'
      in sortie.getvalue(), sortie.getvalue())
call_command('quiz_importer', chemin, stdout=io.StringIO())
check('import rejoué : aucun doublon dans l’approfondissement', prof.count() == 7)
with open(chemin, 'w', encoding='utf-8') as f:
    json.dump({'niveau': sm.name, 'type': 'approfondisement', 'chapitres': []}, f)
try:
    call_command('quiz_importer', chemin, stdout=io.StringIO())
    check('type inconnu (faute de frappe) : refusé, rien n’est versé au cours', False)
except Exception as exc:  # CommandError
    check('type inconnu (faute de frappe) : refusé, rien n’est versé au cours', 'type de quiz inconnu' in str(exc), exc)

# ── Pilotage › Quiz : un onglet par type
N = {'niveau': sm.pk}
row = lambda r: next((x for x in r.data if x['id'] == lim.pk), None)  # noqa: E731
r = cl.get('/api/pilotage/quiz/', N)
check('Pilotage, quiz du cours (défaut) : 5 à relire ; l’autre quiz : 7 à relire', row(r)['total'] == 5
      and row(r)['a_relire'] == 5 and row(r)['autre'] == {'total': 7, 'a_relire': 7}, row(r))
r = cl.get('/api/pilotage/quiz/', {**N, 'type': 'approfondissement'})
check('Pilotage, approfondissement : 7 à relire ; l’autre quiz : 5', row(r)['total'] == 7 and row(r)['a_relire'] == 7
      and row(r)['autre'] == {'total': 5, 'a_relire': 5}, row(r))
base = f'/api/pilotage/quiz/chapitre/{lim.pk}/'
r = cl.get(base, {**N, 'type': 'approfondissement'})
check('questions de l’approfondissement seulement', r.status_code == 200 and r.data['type'] == 'approfondissement'
      and len(r.data['questions']) == 7 and {x['type'] for x in r.data['questions']} == {'approfondissement'}, r.data)
r = cl.post(base + 'valider/', {**N, 'type': 'approfondissement'}, format='json')
check('valider l’approfondissement ne touche pas le cours', r.status_code == 200 and not prof.filter(a_relire=True)
      and cours.filter(a_relire=True).count() == 5, r.data)
r = cl.post(base + 'publier/', {**N, 'type': 'approfondissement', 'en_ligne': True}, format='json')
check('mettre en ligne l’approfondissement seul', r.status_code == 200 and prof.filter(is_active=True).count() == 7
      and not cours.filter(is_active=True).exists(), r.data)
n = Notification.objects.filter(recipient=u, kind='quiz').first()
check('annonce propre à l’approfondissement (cible, lien, extrait)', n is not None
      and n.target == f'quiz-approfondissement:{lim.pk}:{sm.pk}' and n.link.endswith('&type=approfondissement')
      and n.excerpt == 'Approfondissement · 7 questions', n and (n.target, n.link, n.excerpt))
nouvelle = cl.post(base + '?' + f'niveau={sm.pk}&type=approfondissement',
                   {'question': 'Nouveau problème ?', 'options': ['a', 'b', 'c', 'd'], 'correct_answer': 0,
                    'difficulty': 'hard', 'explanation': 'Piège.'}, format='json')
check('question créée dans l’onglet approfondissement', nouvelle.status_code == 201
      and SkillQuestion.objects.get(pk=nouvelle.data['id']).type == 'approfondissement', nouvelle.data)
r = cl.patch(f"/api/pilotage/quiz/question/{nouvelle.data['id']}/", {'type': 'cours', 'question': 'Problème modifié ?'},
             format='json')
check('une question ne change pas de quiz', r.status_code == 200
      and SkillQuestion.objects.get(pk=nouvelle.data['id']).type == 'approfondissement', r.data)
SkillQuestion.objects.filter(pk=nouvelle.data['id']).delete()

# ── Élève : l'approfondissement seul est en ligne
r = el.get('/api/skill-assessments/available/')
check('quiz du cours hors ligne : pas dans « disponibles »', str(lim.pk) not in r.data, r.data)
r = el.get('/api/skill-assessments/available/', {'type': 'approfondissement'})
check('approfondissement : disponible', r.data.get(str(lim.pk)) == 7, r.data)
check('quiz du cours pas encore en ligne : 404', el.get(f'/api/skill-assessments/quiz/{lim.pk}/').status_code == 404)
r = el.get(f'/api/skill-assessments/quiz/{lim.pk}/', {'type': 'approfondissement'})
ids_prof = set(prof.values_list('id', flat=True))
check('tirage de l’approfondissement : ses questions seulement', r.status_code == 200 and r.data['type'] == 'approfondissement'
      and r.data['questions'] and {x['id'] for x in r.data['questions']} <= ids_prof, r.status_code)
servies = [x['id'] for x in r.data['questions']]
check('« en cours » : le type du passage', [(x['chapitre'], x['type']) for x in el.get('/api/skill-assessments/en-cours/').data]
      == [(lim.pk, 'approfondissement')])
nouveaux = el.get('/api/skill-assessments/nouveaux/').data
check('« Nouveau » : l’approfondissement, typé', [(x['chapitre'], x['type']) for x in nouveaux]
      == [(lim.pk, 'approfondissement')], nouveaux)

# Le quiz du cours sort à son tour : les deux passages coexistent.
cl.post(base + 'valider/', N, format='json')
cl.post(base + 'publier/', {**N, 'en_ligne': True}, format='json')
check('quiz du cours en ligne, annoncé à part', Notification.objects.filter(recipient=u, target=f'quiz:{lim.pk}:{sm.pk}').exists()
      and el.get('/api/skill-assessments/available/').data.get(str(lim.pk)) == 5)
r = el.get(f'/api/skill-assessments/quiz/{lim.pk}/')
check('tirage du cours : ses questions seulement', r.status_code == 200 and r.data['type'] == 'cours'
      and {x['id'] for x in r.data['questions']} <= set(cours.values_list('id', flat=True)))
check('deux passages en cours, un par quiz', QuizEnCours.objects.filter(user=u, chapter=lim).count() == 2)
r = el.get(f'/api/skill-assessments/quiz/{lim.pk}/', {'type': 'approfondissement'})
check('reprise de l’approfondissement : mêmes questions', r.data['reprise'] is True
      and [x['id'] for x in r.data['questions']] == servies)

BON = {x.id: x.correct_answer for x in SkillQuestion.objects.filter(chapter=lim)}
r = el.post(f'/api/skill-assessments/submit/{lim.pk}/', {'type': 'approfondissement',
            'answers': {str(i): BON[i] for i in servies}}, format='json')
check('envoi de l’approfondissement : 100 %', r.status_code == 200 and r.data['score'] == r.data['max_score'] > 0, r.data)
a = SkillAssessment.objects.filter(user=u, chapter=lim).first()
check('résultat rangé en approfondissement ; le passage du cours reste en cours', a.type == 'approfondissement'
      and list(QuizEnCours.objects.filter(user=u).values_list('type', flat=True)) == ['cours'])
check('dernier résultat du cours : aucun', el.get(f'/api/skill-assessments/chapter/{lim.pk}/').status_code == 404)
r = el.get(f'/api/skill-assessments/chapter/{lim.pk}/', {'type': 'approfondissement'})
check('dernier résultat de l’approfondissement', r.status_code == 200 and r.data.get('type') == 'approfondissement', r.data)

# ── Maîtrise : seulement le quiz du cours
p = el.get('/api/stats/progression/').data
L = next(x for x in p['chapters'] if x['id'] == lim.pk)
check('Ma progression : l’approfondissement réussi ne compte pas dans la maîtrise', L['skilliq'] is None
      and L['mastery'] is None and L['quiz_ready'] is True, (L['skilliq'], L['mastery'], L['quiz_ready']))
cours_servies = [x['id'] for x in el.get(f'/api/skill-assessments/quiz/{lim.pk}/').data['questions']]
faux = {str(i): (BON[i] + 1) % 4 for i in cours_servies}
r = el.post(f'/api/skill-assessments/submit/{lim.pk}/', {'answers': faux}, format='json')
check('envoi du quiz du cours (type par défaut)', r.status_code == 200 and r.data['score'] == 0, r.data)
check('deux résultats, un par quiz', sorted(SkillAssessment.objects.filter(user=u, chapter=lim)
                                            .values_list('type', flat=True)) == ['approfondissement', 'cours'])
p = el.get('/api/stats/progression/').data
L = next(x for x in p['chapters'] if x['id'] == lim.pk)
check('Ma progression : le quiz du cours seul fait la maîtrise (0 %, pas 100 %)', L['skilliq'] and L['skilliq']['pct'] == 0
      and L['mastery'] == 0, (L['skilliq'], L['mastery']))
mine = el.get('/api/skill-assessments/my/').data
check('« mes quiz » : chaque résultat dit son type', sorted(x['type'] for x in mine if x['chapter'] == lim.pk)
      == ['approfondissement', 'cours'], mine)

ok = sum(results)
print(f'\n{ok}/{len(results)} vérifications OK')
sys.exit(0 if ok == len(results) else 1)
