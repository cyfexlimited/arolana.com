from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialApp

class Command(BaseCommand):
    help = 'Setup Google OAuth application for the active site'
    
    def add_arguments(self, parser):
        parser.add_argument('--client_id', type=str, default='', help='Google OAuth Client ID')
        parser.add_argument('--secret', type=str, default='', help='Google OAuth Client Secret')
        parser.add_argument('--domain', type=str, default='', help='Production site domain')
        parser.add_argument('--from-env', action='store_true', help='Read credentials from Railway/environment variables')
    
    def handle(self, *args, **options):
        client_id = options['client_id'] or getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
        secret = options['secret'] or getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
        domain = options['domain'] or self._site_domain()

        site, _ = Site.objects.update_or_create(
            id=settings.SITE_ID,
            defaults={
                'domain': domain,
                'name': 'Arolana',
            },
        )

        self.stdout.write(self.style.SUCCESS(f'Site ready: {site.domain}'))

        if not client_id or not secret:
            self.stdout.write(self.style.WARNING(
                'Google OAuth skipped: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET '
                'on Railway to enable production Google sign in/sign up.'
            ))
            return

        if options['from_env'] and getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') and getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', ''):
            deleted, _ = SocialApp.objects.filter(provider='google').delete()
            redirect_uri = f'https://{site.domain}/accounts/google/login/callback/'
            self.stdout.write(self.style.SUCCESS('Google OAuth env configuration is active for production.'))
            if deleted:
                self.stdout.write(f'Removed {deleted} duplicate database Google app record(s).')
            self.stdout.write(f'Redirect URI: {redirect_uri}')
            return
        
        apps = list(SocialApp.objects.filter(provider='google').order_by('id'))
        google_app = apps[0] if apps else SocialApp(provider='google')
        created = google_app.pk is None
        google_app.name = 'Google'
        google_app.client_id = client_id
        google_app.secret = secret
        google_app.key = ''
        google_app.provider_id = ''
        google_app.settings = {}
        google_app.save()
        google_app.sites.set([site])

        duplicate_ids = [app.id for app in apps[1:]]
        if duplicate_ids:
            SocialApp.objects.filter(id__in=duplicate_ids).delete()

        redirect_uri = f'https://{site.domain}/accounts/google/login/callback/'
        self.stdout.write(self.style.SUCCESS(f'Google OAuth {"created" if created else "updated"} for production.'))
        self.stdout.write(f'Redirect URI: {redirect_uri}')

    def _site_domain(self):
        site_url = getattr(settings, 'SITE_URL', '') or ''
        parsed = urlparse(site_url)
        if parsed.netloc:
            return parsed.netloc
        railway_domain = getattr(settings, 'RAILWAY_PUBLIC_DOMAIN', '')
        if railway_domain:
            return railway_domain
        return 'arolana.com'
