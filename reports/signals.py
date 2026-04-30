from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import UserActivityLog, LoginAttempt
from .models import LoginAlert
from django.utils import timezone
from datetime import timedelta

@receiver(post_save, sender=UserActivityLog)
def create_alert_on_failed_login(sender, instance, created, **kwargs):
    """Create alert when multiple failed logins occur"""
    if created and instance.action == 'failed_login':
        # Check for multiple failures from same IP
        recent_failures = UserActivityLog.objects.filter(
            action='failed_login',
            ip_address=instance.ip_address,
            timestamp__gte=timezone.now() - timedelta(minutes=30)
        ).count()
        
        if recent_failures >= 5:
            alert, created = LoginAlert.objects.get_or_create(
                ip_address=instance.ip_address,
                alert_type='brute_force',
                defaults={
                    'severity': 'high',
                    'attempt_count': recent_failures,
                    'notes': f'Multiple failed attempts detected: {recent_failures} in 30 minutes'
                }
            )
            if not created and alert.attempt_count < recent_failures:
                alert.attempt_count = recent_failures
                alert.save()
