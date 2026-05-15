import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


def get_html_alternative(message):
    for content, mimetype in getattr(message, 'alternatives', []):
        if mimetype == 'text/html':
            return content
    return None


def parse_email_address(address):
    name, email = parseaddr(address)
    data = {'email': email or address}
    if name:
        data['name'] = name
    return data


class ResendEmailBackend(BaseEmailBackend):
    """Django email backend that sends mail through Resend's HTTPS API."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, 'RESEND_API_KEY', '')
        if not api_key:
            if self.fail_silently:
                return 0
            raise RuntimeError('RESEND_API_KEY is required for ResendEmailBackend')

        sent_count = 0
        for message in email_messages:
            try:
                self._send_message(message, api_key)
            except Exception as exc:
                logger.exception('Resend email delivery failed: %s', exc)
                if not self.fail_silently:
                    raise
            else:
                sent_count += 1

        return sent_count

    def _send_message(self, message, api_key):
        html = get_html_alternative(message)

        payload = {
            'from': message.from_email or settings.DEFAULT_FROM_EMAIL,
            'to': list(message.to or []),
            'subject': message.subject,
            'text': message.body or '',
        }

        if html:
            payload['html'] = html
        if message.cc:
            payload['cc'] = list(message.cc)
        if message.bcc:
            payload['bcc'] = list(message.bcc)
        if message.reply_to:
            payload['reply_to'] = list(message.reply_to)

        response = requests.post(
            settings.RESEND_API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=getattr(settings, 'RESEND_TIMEOUT', 20),
        )
        response.raise_for_status()


class SendGridEmailBackend(BaseEmailBackend):
    """Django email backend that sends mail through SendGrid's HTTPS API."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, 'SENDGRID_API_KEY', '')
        if not api_key:
            if self.fail_silently:
                return 0
            raise RuntimeError('SENDGRID_API_KEY is required for SendGridEmailBackend')

        sent_count = 0
        for message in email_messages:
            try:
                self._send_message(message, api_key)
            except Exception as exc:
                logger.exception('SendGrid email delivery failed: %s', exc)
                if not self.fail_silently:
                    raise
            else:
                sent_count += 1

        return sent_count

    def _send_message(self, message, api_key):
        content = []
        if message.body:
            content.append({'type': 'text/plain', 'value': message.body})

        html = get_html_alternative(message)
        if html:
            content.append({'type': 'text/html', 'value': html})

        if not content:
            content.append({'type': 'text/plain', 'value': ''})

        personalization = {
            'to': [parse_email_address(address) for address in message.to or []],
            'subject': message.subject,
        }
        if message.cc:
            personalization['cc'] = [parse_email_address(address) for address in message.cc]
        if message.bcc:
            personalization['bcc'] = [parse_email_address(address) for address in message.bcc]

        payload = {
            'personalizations': [personalization],
            'from': parse_email_address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            'subject': message.subject,
            'content': content,
        }
        if message.reply_to:
            payload['reply_to'] = parse_email_address(message.reply_to[0])

        response = requests.post(
            settings.SENDGRID_API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=getattr(settings, 'SENDGRID_TIMEOUT', 20),
        )
        response.raise_for_status()
