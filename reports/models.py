from django.db import models
from accounts.models import User, UserActivityLog, LoginAttempt
from core.models import BaseModel

class LoginReport(BaseModel):
    """Generate and store login reports"""
    REPORT_TYPES = (
        ('daily', 'Daily Report'),
        ('weekly', 'Weekly Report'),
        ('monthly', 'Monthly Report'),
        ('custom', 'Custom Range'),
    )
    
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    total_logins = models.IntegerField(default=0)
    successful_logins = models.IntegerField(default=0)
    failed_logins = models.IntegerField(default=0)
    unique_users = models.IntegerField(default=0)
    unique_ips = models.IntegerField(default=0)
    report_data = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"{self.report_type} Report - {self.generated_at.strftime('%Y-%m-%d %H:%M')}"

class LoginAlert(BaseModel):
    """Store login alerts for suspicious activities"""
    ALERT_TYPES = (
        ('multiple_failures', 'Multiple Failed Attempts'),
        ('suspicious_ip', 'Suspicious IP Address'),
        ('unusual_time', 'Unusual Login Time'),
        ('rapid_logins', 'Rapid Successive Logins'),
        ('brute_force', 'Brute Force Detected'),
    )
    
    SEVERITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    )
    
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    ip_address = models.GenericIPAddressField()
    email = models.EmailField(blank=True, null=True)
    attempt_count = models.IntegerField(default=0)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_alerts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.ip_address} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
