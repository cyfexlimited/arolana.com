import base64

from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


class Command(BaseCommand):
    help = 'Generate VAPID keys for Arolana web push notifications.'

    def handle(self, *args, **options):
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_numbers = private_key.private_numbers()
        public_numbers = private_numbers.public_numbers

        private_value = private_numbers.private_value.to_bytes(32, 'big')
        public_value = (
            b'\x04'
            + public_numbers.x.to_bytes(32, 'big')
            + public_numbers.y.to_bytes(32, 'big')
        )

        self.stdout.write('Set these Railway/environment variables:')
        self.stdout.write(f'WEB_PUSH_VAPID_PUBLIC_KEY={_b64url(public_value)}')
        self.stdout.write(f'WEB_PUSH_VAPID_PRIVATE_KEY={_b64url(private_value)}')
        self.stdout.write('WEB_PUSH_VAPID_SUBJECT=mailto:contact@arolana.com')
