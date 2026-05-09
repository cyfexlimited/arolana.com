from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp

class Command(BaseCommand):
    help = 'Setup social authentication apps'
    
    def handle(self, *args, **options):
        # Get current site
        site, created = Site.objects.get_or_create(
            domain='localhost:8000',
            defaults={'name': 'Arolana Local'}
        )
        
        # Create or update Google app
        google_app, created = SocialApp.objects.get_or_create(
            provider='google',
            name='Google',
            defaults={
                'client_id': '',
                'secret': '',
            }
        )
        google_app.sites.add(site)
        
        self.stdout.write(self.style.SUCCESS(f'✅ Social apps configured on site: {site.domain}'))
        self.stdout.write('⚠️  Please add your Google OAuth credentials in Django admin:')
        self.stdout.write('   Go to: /admin/socialaccount/socialapp/')
