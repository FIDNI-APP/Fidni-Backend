"""Reprise de l'existant dans le journal des auto-évaluations (13/10/2026).

Un événement par évaluation existante (QuestionProgress au statut non vide), daté de sa dernière évaluation
(assessed_at), marqué `reprise` : seul le dernier état de chaque question est connu. L'aide est inconnue (None),
sauf une réponse donnée sous la solution ouverte (source « apres_solution » : 'solution'). Une aide inconnue n'est
jamais comptée comme « sans aide » (apps/users/maitrise.py) : ces événements servent aux résultats, pas à prouver
l'autonomie ni à confirmer une maîtrise durable.
Code figé ici (pas d'import de l'application) ; relancée, elle n'ajoute rien. Retour arrière : rien à défaire
(les événements repris restent, inoffensifs ; la migration 0023 en arrière supprime la table).
"""
from django.db import migrations

LOT = 5000


def reprendre_existant(QuestionProgress, AssessmentEvent, lot=LOT):
    """Renvoie le nombre d'événements créés."""
    deja = set(AssessmentEvent.objects.values_list('user_id', 'object_id', 'question_path').distinct())
    rows = (QuestionProgress.objects.exclude(status='').order_by('id')
            .values_list('user_id', 'object_id', 'question_path', 'status', 'source', 'assessed_at'))
    tampon, crees = [], 0
    for uid, oid, path, st, source, at in rows.iterator(chunk_size=LOT):
        if (uid, oid, path) in deja or len(path) > 100:
            continue
        tampon.append(AssessmentEvent(user_id=uid, object_id=oid, question_path=path, status=st, previous=None,
                                      source=source or 'question',
                                      aide='solution' if source == 'apres_solution' else None,
                                      reprise=True, at=at))
        if len(tampon) >= lot:
            AssessmentEvent.objects.bulk_create(tampon)
            crees += len(tampon)
            tampon = []
    if tampon:
        AssessmentEvent.objects.bulk_create(tampon)
        crees += len(tampon)
    return crees


def avant(apps, schema_editor):
    reprendre_existant(apps.get_model('interactions', 'QuestionProgress'),
                       apps.get_model('interactions', 'AssessmentEvent'))


class Migration(migrations.Migration):
    dependencies = [('interactions', '0023_journal_maitrise')]
    operations = [migrations.RunPython(avant, migrations.RunPython.noop)]
