from django.db import models
from django.utils import timezone
from core.models import BaseModel


class AdPlacement(BaseModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    width = models.PositiveIntegerField(default=300)
    height = models.PositiveIntegerField(default=250)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class AdCampaign(BaseModel):
    name = models.CharField(max_length=200)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def is_running(self):
        now = timezone.now()
        if self.start_date and self.start_date > now:
            return False
        if self.end_date and self.end_date < now:
            return False
        return self.is_active

    def __str__(self):
        return self.name


class AdBanner(BaseModel):
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.CASCADE,
        related_name="banners"
    )
    placement = models.ForeignKey(
        AdPlacement,
        on_delete=models.CASCADE,
        related_name="banners"
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    image = models.ImageField(upload_to='ads/', null=True, blank=True)

    url = models.URLField(default='/')
    button_text = models.CharField(max_length=50, default='Learn More')

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    
    views = models.IntegerField(default=0)
    
    def increment_impression(self):
        from django.db.models import F
        AdBanner.objects.filter(id=self.id).update(impressions=F('impressions') + 1)

    def increment_click(self):
        from django.db.models import F
        AdBanner.objects.filter(id=self.id).update(clicks=F('clicks') + 1)

    @property
    def ctr(self):
        return (self.clicks / self.impressions * 100) if self.impressions else 0

    def __str__(self):
        return f"{self.title} ({self.placement.slug})"
