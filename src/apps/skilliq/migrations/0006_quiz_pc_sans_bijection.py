# Quiz 2ème Bac PC/SVT : plus de « bijection » (hors programme à ce niveau, Natsu 14/10/2026). Les questions déjà
# importées pour ce niveau prennent la variante `par_niveau` de skilliq/quiz/3-deuxieme-bac.json : « fonction
# réciproque » dans les textes, et des théorèmes du programme PC (TVI, continuité de la fonction réciproque) à la
# place du « Théorème de la bijection » dans le bilan de fin de quiz. Les quiz des autres niveaux ne changent pas.
import re

from django.db import migrations

PC = '2ème Bac PC/SVT'
# {morceau de l'énoncé d'origine : champs remplacés}, comme dans le fichier des quiz.
VARIANTES = {'strictement croissante sur $[a\\,;b]$ avec $f(a) \\times f(b) < 0$': {'theoremes': ['Théorème des valeurs '
                                                                                      'intermédiaires '
                                                                                      '(TVI)']},
 'admet une unique solution dans un intervalle $I$, il suffit que': {'theoremes': ['Théorème des valeurs '
                                                                                   'intermédiaires (TVI)']},
 'f(x) = x^3 + x - 1': {'bonne': '$f$ admet une fonction réciproque définie sur $\\mathbb{R}$, et l’équation '
                                 '$f(x) = 0$ a une unique solution, dans $]0\\,;1[$.',
                        'distracteurs': ['$f$ admet une fonction réciproque définie sur $\\mathbb{R}$, et '
                                         'l’équation $f(x) = 0$ a une unique solution, dans $]1\\,;2[$.',
                                         '$f$ admet une fonction réciproque définie sur $]-1\\,;+\\infty[$, '
                                         'et $f(x) = 0$ a une unique solution, dans $]0\\,;1[$.',
                                         '$f$ n’admet pas de fonction réciproque, car l’équation $f(x) = 0$ '
                                         'a plusieurs solutions.'],
                        'explication': "$f$ est continue et strictement croissante ($f'(x) = 3x^2 + 1 > 0$), "
                                       'avec des limites $-\\infty$ et $+\\infty$ : elle admet une fonction '
                                       'réciproque définie sur $f(\\mathbb{R}) = \\mathbb{R}$. Comme $f(0) = '
                                       '-1 < 0 < 1 = f(1)$, la solution est dans $]0\\,;1[$ ; $f(1) > 0$ '
                                       'l’exclut de $]1\\,;2[$.',
                        'theoremes': ['Théorème des valeurs intermédiaires (TVI)',
                                      'Continuité de la fonction réciproque']},
 'f(x) = x - \\sin x': {'theoremes': ['Continuité de la fonction réciproque']},
 'est une bijection dérivable de': {'question': '$f$ est continue, strictement croissante et dérivable sur '
                                                '$\\mathbb{R}$, avec $f(\\mathbb{R}) = \\mathbb{R}$, $f(1) = '
                                                "3$ et $f'(1) = 2$. Que vaut $\\left(f^{-1}\\right)'(3)$ ?"}}


def _propre(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def appliquer(apps, schema_editor):
    SkillQuestion = apps.get_model('skilliq', 'SkillQuestion')
    Theorem = apps.get_model('caracteristics', 'Theorem')
    for morceau, v in VARIANTES.items():
        for q in SkillQuestion.objects.filter(class_level__name=PC, question__contains=morceau):
            if 'question' in v:
                q.question = _propre(v['question'])
            if 'explication' in v:
                q.explanation = _propre(v['explication'])[:2000]
            if 'bonne' in v:
                # Les réponses sont mélangées en base : la bonne garde sa place, les trois autres prennent les
                # nouveaux textes dans l'ordre.
                options = list(q.options)
                autres = iter(_propre(d) for d in v['distracteurs'])
                q.options = [_propre(v['bonne']) if i == q.correct_answer else next(autres)
                             for i in range(len(options))]
            q.save()
            if 'theoremes' in v:
                # Par le nom seul : l'état des modèles de caracteristics à ce point de la migration est celui de 0001.
                ths = {th.name: th for th in Theorem.objects.filter(name__in=v['theoremes'])}
                if len(ths) == len(v['theoremes']):
                    q.theorems.set(list(ths.values()))


class Migration(migrations.Migration):

    dependencies = [
        # Comme 0004 et 0005 : seuls des modèles existants servent (check_migration_programme revient à 0002).
        ('caracteristics', '0001_initial'),
        ('skilliq', '0005_quiz_passage'),
    ]

    operations = [migrations.RunPython(appliquer, migrations.RunPython.noop)]
