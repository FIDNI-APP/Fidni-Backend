"""Importe un lot de défis (JSON) en brouillons à valider dans Pilotage › Défis.

Usage : manage.py defis_importer lot.json [--essai]
Une clé déjà connue met à jour le défi s'il n'a pas encore de tentative, et le repasse « à valider » ; sinon elle est sautée.
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.defis import reponses
from apps.defis.models import DIFFICULTES, THEMES, Defi

CHAMPS = ('date', 'titre', 'theme', 'difficulte', 'enonce', 'consigne', 'reponse', 'indices', 'solution')


def controler(x):
    manque = [c for c in ('cle',) + CHAMPS if not x.get(c)]
    if manque:
        return f"champs manquants : {', '.join(manque)}"
    if reponses.lire(x['reponse']) is None:
        return f"réponse illisible : {x['reponse']!r}"
    if x['theme'] not in dict(THEMES) or x['difficulte'] not in dict(DIFFICULTES):
        return 'thème ou difficulté inconnus'
    if not all(i.get('titre') and i.get('texte') for i in x['indices']):
        return 'un indice sans titre ou sans texte'
    try:
        datetime.strptime(x['date'], '%Y-%m-%d')
    except ValueError:
        return f"date invalide : {x['date']!r}"
    return None


class Command(BaseCommand):
    help = 'Importe un lot de défis du jour, à valider dans le Pilotage.'

    def add_arguments(self, parser):
        parser.add_argument('fichier')
        parser.add_argument('--essai', action='store_true', help='Contrôle sans rien écrire.')

    def handle(self, *args, fichier, essai=False, **kw):
        with open(fichier, encoding='utf-8') as f:
            lot = json.load(f)
        erreurs = [f"{x.get('cle', '?')} : {e}" for x in lot for e in [controler(x)] if e]
        if not erreurs and (len({x['date'] for x in lot}) != len(lot) or len({x['cle'] for x in lot}) != len(lot)):
            erreurs.append('deux défis du lot ont la même date ou la même clé')
        if erreurs:
            raise CommandError('\n'.join(erreurs))
        crees = maj = sautes = 0
        with transaction.atomic():
            for x in lot:
                valeurs = {c: x[c] for c in CHAMPS} | {'source': x.get('source', ''), 'valide': False}
                autre = Defi.objects.filter(date=x['date']).exclude(cle=x['cle']).first()
                if autre:
                    raise CommandError(f"{x['cle']} : le {x['date']} est déjà pris par {autre.cle}")
                d = Defi.objects.filter(cle=x['cle']).first()
                if d is None:
                    Defi.objects.create(cle=x['cle'], **valeurs)
                    crees += 1
                elif d.tentatives.exists():
                    sautes += 1
                else:
                    Defi.objects.filter(pk=d.pk).update(**valeurs)
                    maj += 1
            if essai:
                transaction.set_rollback(True)
        self.stdout.write(f"{'ESSAI — ' if essai else ''}créés {crees}, mis à jour {maj}, sautés {sautes}")
