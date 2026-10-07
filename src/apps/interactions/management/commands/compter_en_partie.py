"""python manage.py compter_en_partie [--jours 30]

Combien d'élèves se servent du bouton « En partie » de l'auto-évaluation (sous chaque question) ?
Pour décider s'il faut le garder. Comptes maison (administrateurs, compte éditorial, tests) exclus.

Sur le serveur : docker exec -it fidni-backend python manage.py compter_en_partie
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.interactions.models import QuestionProgress

LABELS = [('success', 'Réussi'), ('partial', 'En partie'), ('review', 'À revoir'), ('failed', 'Échoué (ancien choix)')]


class Command(BaseCommand):
    help = "Compte les auto-évaluations « En partie » face à « Réussi » et « À revoir »."

    def add_arguments(self, parser):
        parser.add_argument('--jours', type=int, default=None,
                            help='Seulement les N derniers jours (par défaut : depuis toujours).')

    def handle(self, jours=None, **options):
        from apps.users.admin_dashboard import _house_filter
        from django.contrib.auth.models import User

        qs = QuestionProgress.objects.exclude(user__in=User.objects.filter(_house_filter()))
        when = 'depuis toujours'
        if jours:
            qs = qs.filter(assessed_at__gte=timezone.now() - timedelta(days=jours))
            when = f'sur les {jours} derniers jours'

        by_status = dict(qs.values_list('status').annotate(n=Count('id')))
        total = sum(by_status.values())
        out = self.stdout.write
        out(f'Auto-évaluations des questions, {when} (comptes maison exclus) : {total}')
        if not total:
            out('Aucune auto-évaluation enregistrée.')
            return
        for key, label in LABELS:
            n = by_status.get(key, 0)
            if n or key != 'failed':
                out(f'  {label:<22} {n:>7}  ({round(n * 100 / total)} %)')

        users = qs.values('user').distinct().count()
        partial_users = qs.filter(status='partial').values('user').distinct().count()
        out('')
        out(f'Élèves qui s\'auto-évaluent : {users}')
        out(f'… dont qui ont déjà cliqué « En partie » : {partial_users} ({round(partial_users * 100 / users)} %)')

        # Ceux qui s'en servent le plus : la part de « En partie » dans LEURS évaluations (sans les nommer).
        per_user = (qs.values('user').annotate(n=Count('id'))
                    .filter(n__gte=5).values_list('user', 'n'))
        partial_of = dict(qs.filter(status='partial').values('user').annotate(n=Count('id')).values_list('user', 'n'))
        shares = sorted((partial_of.get(u, 0) / n for u, n in per_user), reverse=True)
        if shares:
            heavy = sum(1 for s in shares if s >= 0.25)
            n = len(shares)
            out(f'Élèves avec au moins 5 évaluations : {n} ; {heavy} d\'entre eux mettent « En partie » '
                f'sur au moins 1 question sur 4.')
