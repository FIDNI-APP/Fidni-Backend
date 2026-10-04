"""Brevo transactional email over HTTP.

Brevo's SMTP relay authorises senders by source IP, so it fails with
`525 5.7.1 Unauthorized IP address` from any host whose public address is not
on the allow-list — which a home connection changes on its own, and an ECS
task changes on every deploy. The HTTP API authenticates with a key instead,
so it keeps working wherever the backend happens to run.

Stdlib only on purpose: `requests` is not installed in the runtime image, and
one POST does not justify rebuilding it.
"""
import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger('django')

API_URL = 'https://api.brevo.com/v3/smtp/email'


def _address(value):
    """'Fidni <no-reply@fidni.fr>' -> {'name': 'Fidni', 'email': 'no-reply@fidni.fr'}"""
    name, email = parseaddr(value)
    return {'email': email, 'name': name} if name else {'email': email}


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Django email backend posting to Brevo's /v3/smtp/email endpoint."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, 'BREVO_API_KEY', '')
        self.timeout = getattr(settings, 'BREVO_TIMEOUT', 10)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not self.api_key:
            if self.fail_silently:
                return 0
            raise ValueError(
                'BREVO_API_KEY is not set — cannot send through the Brevo API.'
            )

        sent = 0
        for message in email_messages:
            if self._send(message):
                sent += 1
        return sent

    def _build_payload(self, message):
        payload = {
            'sender': _address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            'to': [_address(a) for a in message.to],
            'subject': message.subject,
        }

        # Brevo rejects a message carrying neither textContent nor htmlContent.
        if message.body:
            payload['textContent'] = message.body
        for content, mimetype in getattr(message, 'alternatives', None) or []:
            if mimetype == 'text/html':
                payload['htmlContent'] = content
                break

        if message.cc:
            payload['cc'] = [_address(a) for a in message.cc]
        if message.bcc:
            payload['bcc'] = [_address(a) for a in message.bcc]
        if message.reply_to:
            payload['replyTo'] = _address(message.reply_to[0])

        return payload

    def _send(self, message):
        if not message.to:
            return False

        request = urllib.request.Request(
            API_URL,
            data=json.dumps(self._build_payload(message)).encode('utf-8'),
            headers={
                'api-key': self.api_key,
                'content-type': 'application/json',
                'accept': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
            return True
        except urllib.error.HTTPError as exc:
            # Brevo explains refusals in the body (bad key, unverified sender);
            # without it the log would only say "400".
            detail = exc.read().decode('utf-8', 'replace')[:500]
            logger.error('Brevo refused the message (%s): %s', exc.code, detail)
            if not self.fail_silently:
                raise
            return False
        except Exception:
            logger.exception('Brevo request failed')
            if not self.fail_silently:
                raise
            return False
