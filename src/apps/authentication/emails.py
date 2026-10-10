"""Account email sending (verification, password reset)."""
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import make_verification_token

logger = logging.getLogger('django')


def _site_url() -> str:
    return settings.FRONTEND_URL.rstrip('/')


def _send_account_email(user, *, subject, preheader, heading, paragraphs,
                        cta_label, link, expiry, safety_note) -> None:
    """Send an account email as HTML plus its plain-text twin.

    Both are built from the same content, so they never drift apart. The text
    version is what shows up in clients that block HTML, and it helps
    deliverability (a message with no text part looks like spam).
    """
    context = {
        'subject': subject,
        'preheader': preheader,
        'heading': heading,
        'username': user.username,
        'paragraphs': paragraphs,
        'cta_label': cta_label,
        'link': link,
        'expiry': expiry,
        'safety_note': safety_note,
        'site_url': _site_url(),
    }
    html = render_to_string('emails/account_action.html', context)
    text = '\n\n'.join([
        f'Bonjour {user.username},',
        *paragraphs,
        f'{cta_label} :\n{link}',
        expiry,
        safety_note,
        "— L'équipe Fidni\nfidni.fr · contact@fidni.fr",
    ])

    send_mail(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html,
        fail_silently=False,
    )


def send_verification_email(user) -> None:
    """Send the email-verification link to a freshly-registered user."""
    token = make_verification_token(user)
    link = f"{_site_url()}/verify-email?token={token}"

    _send_account_email(
        user,
        subject="Confirme ton adresse e-mail — Fidni",
        preheader="Un clic pour activer ton compte Fidni.",
        heading="Bienvenue sur Fidni !",
        paragraphs=[
            "Ton compte est presque prêt. Confirme ton adresse e-mail pour l'activer "
            "et commencer à réviser.",
        ],
        cta_label="Confirmer mon adresse",
        link=link,
        expiry="Ce lien est valable 3 jours.",
        safety_note="Tu n'es pas à l'origine de cette inscription ? Ignore simplement "
                    "cet e-mail : aucun compte ne sera activé.",
    )
    logger.info("Verification email sent to user %s", user.pk)


def send_email_change_verification(user) -> None:
    """Nouvelle adresse d'un compte existant (réglages) : même lien que l'inscription
    (VerifyEmailView), lié à cette adresse ; il confirme l'adresse sans ouvrir de session."""
    token = make_verification_token(user)
    link = f"{_site_url()}/verify-email?token={token}"

    _send_account_email(
        user,
        subject="Confirme ta nouvelle adresse e-mail — Fidni",
        preheader="Un clic pour confirmer la nouvelle adresse de ton compte Fidni.",
        heading="Confirme ta nouvelle adresse",
        paragraphs=[
            "Tu as changé l'adresse e-mail de ton compte Fidni. Confirme-la pour qu'elle serve "
            "à récupérer ton compte (mot de passe oublié, connexion avec Google).",
            "En attendant, tu peux continuer à te connecter avec ton mot de passe.",
        ],
        cta_label="Confirmer ma nouvelle adresse",
        link=link,
        expiry="Ce lien est valable 3 jours.",
        safety_note="Tu n'as rien changé ? Quelqu'un a peut-être saisi ton adresse par erreur : "
                    "ignore cet e-mail, elle ne sera pas confirmée.",
    )
    logger.info("Email change verification sent to user %s", user.pk)


def send_password_reset_email(user) -> None:
    """Send a single-use password-reset link.

    Django's token generator hashes the current password and last login into the
    token: once the password changes (or the user logs in), the link stops working.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{_site_url()}/reset-password?uid={uid}&token={token}"
    hours = max(1, settings.PASSWORD_RESET_TIMEOUT // 3600)

    _send_account_email(
        user,
        subject="Réinitialise ton mot de passe — Fidni",
        preheader="Choisis un nouveau mot de passe pour ton compte Fidni.",
        heading="Nouveau mot de passe",
        paragraphs=[
            "Tu as demandé à changer le mot de passe de ton compte Fidni. "
            "Choisis-en un nouveau en suivant le lien ci-dessous.",
            "Une fois changé, tu seras déconnecté de tes autres appareils.",
        ],
        cta_label="Choisir un nouveau mot de passe",
        link=link,
        expiry=f"Ce lien ne sert qu'une fois et expire dans {hours} h.",
        safety_note="Tu n'as rien demandé ? Ignore cet e-mail : ton mot de passe reste "
                    "inchangé. L'équipe Fidni ne te demandera jamais ton mot de passe.",
    )
    logger.info("Password reset email sent to user %s", user.pk)
