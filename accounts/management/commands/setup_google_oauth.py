from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp

class Command(BaseCommand):
    help = 'Setup Google OAuth application'
    
    def add_arguments(self, parser):
        parser.add_argument('--client_id', type=str, required=True, help='Google OAuth Client ID')
        parser.add_argument('--secret', type=str, required=True, help='Google OAuth Client Secret')
    
    def handle(self, *args, **options):
        client_id = options['client_id']
        secret = options['secret']
        
        # Update site
        site = Site.objects.get_current()
        site.domain = 'localhost:8000'
        site.name = 'Arolana Local'
        site.save()
        self.stdout.write(self.style.SUCCESS(f'✅ Site updated: {site.domain}'))
        
        # Create or update Google Social App
        google_app, created = SocialApp.objects.get_or_create(
            provider='google',
            name='Google',
            defaults={
                'client_id': client_id,
                'secret': secret,
            }
        )
        
        if not created:
            google_app.client_id = client_id
            google_app.secret = secret
            google_app.save()
        
        google_app.sites.add(site)
        google_app.save()
        
        self.stdout.write(self.style.SUCCESS(f'✅ Google OAuth {"created" if created else "updated"}'))
        self.stdout.write(f'   Client ID: {client_id[:20]}...')
        self.stdout.write(f'   Redirect URI: http://localhost:8000/accounts/google/login/callback/')
        self.stdout.write(self.style.WARNING('\n⚠️ Important: Add this redirect URI to your Google Cloud Console:'))
        self.stdout.write('   http://localhost:8000/accounts/google/login/callback/')
