"""python manage.py purger_messages : messages de plus de 12 mois (RGPD), conversations vides, appels terminés.

Lancée chaque nuit sur le serveur (deploy/ovh/installer-serveur.sh). Les messages signalés et pas encore traités
restent jusqu'à leur traitement.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.messagerie.models import Appel, Conversation, Message, PresenceAppel, SignalementMessage

CONSERVATION = timedelta(days=365)


class Command(BaseCommand):
    help = 'Supprime les messages de plus de 12 mois et les traces des appels terminés.'

    def handle(self, **options):
        limite = timezone.now() - CONSERVATION
        signales = SignalementMessage.objects.filter(message=OuterRef('pk'), traite_le__isnull=True)
        n, _ = (Message.objects.filter(created_at__lt=limite).annotate(s=Exists(signales)).filter(s=False).delete())
        a, _ = Appel.objects.filter(fin__lt=limite).delete()
        # Présences restées ouvertes (serveur arrêté pendant un appel) : fermées au bout d'un jour.
        PresenceAppel.objects.filter(parti_le__isnull=True, rejoint_le__lt=timezone.now() - timedelta(days=1)).update(
            parti_le=timezone.now())
        Appel.objects.filter(fin__isnull=True, debut__lt=timezone.now() - timedelta(days=1)).update(fin=timezone.now())
        c, _ = (Conversation.objects.filter(dernier_message_at__lt=limite)
                .annotate(m=Exists(Message.objects.filter(conversation=OuterRef('pk')))).filter(m=False).delete())
        self.stdout.write(self.style.SUCCESS(f'{n} messages, {a} appels, {c} conversations supprimés (plus de 12 mois).'))
