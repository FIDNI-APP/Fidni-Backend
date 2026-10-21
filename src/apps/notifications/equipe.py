"""Message de l'équipe à un membre (21/10/2026) : une notification (cloche → onglet « Messages » du profil, message en
entier) et un e-mail mis en page, avec les mêmes mots. Pour un remerciement, une annonce ciblée : à la main, via
`envoyer_message()` dans le shell du serveur ; jamais en masse.

L'e-mail s'adresse au pseudo du membre (pas à son prénom, qui reste privé) ; il est en HTML (images hébergées sur
fidni.fr/emails/) et en texte brut, construits du même contenu.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import Notification

logger = logging.getLogger('django')


def _site():
    return settings.FRONTEND_URL.rstrip('/')


def envoyer_message(user, titre, paragraphes_avant, paragraphes_apres=(), *, sujet=None, apercu='',
                    hero=None, hero_alt='', partage_image=None, partage_alt='', cta_label='', cta_link='',
                    cta_note='', signature='L’équipe Fidni', signature_ligne='À bientôt sur Fidni,',
                    notification=True, email=True):
    """Envoie la notification et/ou l'e-mail ; renvoie {'notification': id | None, 'email': bool}."""
    site = _site()
    avant, apres = list(paragraphes_avant), list(paragraphes_apres)
    out = {'notification': None, 'email': False}

    if notification:
        corps = '\n\n'.join(avant + apres)
        n = Notification.objects.create(
            recipient=user, kind=Notification.KIND_MESSAGE, target=f'message:{user.id}', title=titre[:200],
            link=f'/profile/{user.username}?tab=messages', excerpt=(avant[0] if avant else '')[:200], message=corps)
        out['notification'] = n.id

    if email and user.email:
        contexte = {
            'subject': sujet or titre, 'preheader': apercu or (avant[0] if avant else ''), 'heading': titre,
            'username': user.username, 'paragraphs_avant': avant, 'paragraphs_apres': apres,
            'hero': f'{site}{hero}' if hero else '', 'hero_alt': hero_alt,
            'partage_image': f'{site}{partage_image}' if partage_image else '', 'partage_alt': partage_alt,
            'cta_label': cta_label, 'cta_link': cta_link, 'cta_note': cta_note,
            'signature': signature, 'signature_ligne': signature_ligne, 'site_url': site,
        }
        html = render_to_string('emails/message_equipe.html', contexte)
        texte = '\n\n'.join([f'Bonjour {user.username},', *avant, *apres]
                            + ([f'{cta_label} :\n{cta_link}'] if cta_link else [])
                            + [f'{signature_ligne}\n{signature}', 'fidni.fr · contact@fidni.fr'])
        msg = EmailMultiAlternatives(sujet or titre, texte, settings.DEFAULT_FROM_EMAIL, [user.email])
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        out['email'] = True
    return out
