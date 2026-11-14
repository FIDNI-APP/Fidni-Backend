# Enseignants des contenus déjà en ligne (Natsu, 14/11/2026) : déduits de la mention « Proposé par … » de chaque
# contenu (json_content["credit"], « M. Haddar, professeur de mathématiques »), comme le fera chaque import
# (things/enseignants.py). Même nom sans accents ni casse = même enseignant ; « M. Haddar » devient
# « M. Khalid Haddar » (prénom donné par Natsu le 14/11). Les doublons d'orthographe (Naoufel / Naoufal / Noufal)
# restent séparés : à fusionner dans Pilotage › Enseignants. Le retour arrière supprime les enseignants.
from django.db import migrations

from apps.things.enseignants import analyser, cle

PRENOMS_CONNUS = {'haddar': 'Khalid'}


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    Enseignant = apps.get_model('things', 'Enseignant')
    par_nom = {}  # clé du nom → [enseignants]

    def trouver(civ, prenom, nom):
        prenom = prenom or PRENOMS_CONNUS.get(cle(nom), '')
        memes = par_nom.setdefault(cle(nom), [])
        if prenom:
            for e in memes:
                if cle(e.prenom) == cle(prenom):
                    return e
            sans = [e for e in memes if not e.prenom]
            if len(sans) == 1:
                sans[0].prenom = prenom
                sans[0].save(update_fields=['prenom'])
                return sans[0]
        elif memes:
            return memes[0]
        e = Enseignant.objects.create(civilite=civ, prenom=prenom, nom=nom)
        memes.append(e)
        return e

    for c in Content.objects.exclude(json_content={}).only('id', 'json_content').iterator():
        credit = (c.json_content or {}).get('credit') if isinstance(c.json_content, dict) else None
        if not isinstance(credit, str) or not credit.strip():
            continue
        ens = [trouver(p['civilite'], p['prenom'], p['nom']) for p in analyser(credit)]
        if ens:
            c.enseignants.add(*ens)


def backwards(apps, schema_editor):
    apps.get_model('things', 'Enseignant').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('things', '0028_enseignants'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
