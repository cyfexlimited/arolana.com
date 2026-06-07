from django.db import models
from core.models import BaseModel
from accounts.models import User
from products.models import Product


class SearchHistory(BaseModel):
    """Track user search history for AI learning."""
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='search_history',
    )
    session_id = models.CharField(max_length=200, blank=True)
    query = models.CharField(max_length=500)
    intent = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=160, blank=True)
    results_count = models.IntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['query']),
            models.Index(fields=['intent']),
            models.Index(fields=['category']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Search: {self.query}"


class SearchAnalytics(BaseModel):
    """Analytics for search performance."""
    query = models.CharField(max_length=500)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='search_analytics',
    )
    position = models.IntegerField()
    score = models.IntegerField(default=0)
    clicked = models.BooleanField(default=False)
    session_id = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['query']),
            models.Index(fields=['clicked']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.query} - {self.product.name} - {'Clicked' if self.clicked else 'Not clicked'}"


class VoiceSearchLog(BaseModel):
    """Track mobile voice search transcripts and AI replies."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=200, blank=True)
    transcript = models.CharField(max_length=500)
    ai_reply = models.TextField(blank=True)
    results_count = models.IntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transcript']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Voice Search: {self.transcript}"
