from django.db import models
from core.models import BaseModel
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import re

class Video(BaseModel):
    """Universal video model that can be attached to any content type"""
    
    VIDEO_TYPES = [
        ('youtube', 'YouTube'),
        ('vimeo', 'Vimeo'),
        ('local', 'Local File'),
        ('embed', 'Embed Code'),
        ('streaming', 'Streaming URL'),
    ]
    
    # Basic Info
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_type = models.CharField(max_length=20, choices=VIDEO_TYPES, default='youtube')
    
    # Video URLs/IDs
    youtube_id = models.CharField(max_length=100, blank=True, help_text="YouTube video ID or URL")
    vimeo_id = models.CharField(max_length=100, blank=True, help_text="Vimeo video ID or URL")
    video_file = models.FileField(upload_to='videos/%Y/%m/', null=True, blank=True)
    embed_code = models.TextField(blank=True, help_text="Custom embed code")
    streaming_url = models.URLField(blank=True, help_text="HLS or MP4 streaming URL")
    
    # Thumbnails
    custom_thumbnail = models.ImageField(upload_to='videos/thumbnails/%Y/%m/', null=True, blank=True)
    auto_thumbnail = models.URLField(blank=True, help_text="Auto-fetched thumbnail")
    
    # Settings
    autoplay = models.BooleanField(default=False)
    loop = models.BooleanField(default=False)
    muted = models.BooleanField(default=False)
    controls = models.BooleanField(default=True)
    start_time = models.IntegerField(default=0, help_text="Start time in seconds")
    end_time = models.IntegerField(null=True, blank=True, help_text="End time in seconds")
    
    # Quality
    QUALITY_CHOICES = [
        ('auto', 'Auto'),
        ('2160p', '4K'),
        ('1440p', '2K'),
        ('1080p', 'Full HD'),
        ('720p', 'HD'),
        ('480p', 'SD'),
    ]
    preferred_quality = models.CharField(max_length=10, choices=QUALITY_CHOICES, default='auto')
    
    # Stats
    views = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    
    # Generic relation to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Display settings
    display_order = models.IntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order', '-created_at']
    
    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        # Extract YouTube ID from URL if needed
        if self.youtube_id:
            self.youtube_id = self.extract_youtube_id(self.youtube_id)
        
        # Extract Vimeo ID from URL if needed
        if self.vimeo_id:
            self.vimeo_id = self.extract_vimeo_id(self.vimeo_id)
        
        # Fetch thumbnail automatically if not set
        if not self.custom_thumbnail and self.video_type == 'youtube' and self.youtube_id:
            self.auto_thumbnail = f"https://img.youtube.com/vi/{self.youtube_id}/maxresdefault.jpg"
        
        super().save(*args, **kwargs)
    
    def extract_youtube_id(self, url):
        """Extract YouTube video ID from various URL formats"""
        # Already just an ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        # Full URL patterns
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)',
            r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)',
            r'(?:youtube\.com\/v\/)([\w-]+)',
            r'(?:youtube\.com\/shorts\/)([\w-]+)',
            r'(?:youtube\.com\/live\/)([\w-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # If no pattern matches, return as is
        return url
    
    def extract_vimeo_id(self, url):
        """Extract Vimeo video ID from URL"""
        patterns = [
            r'(?:vimeo\.com\/)(\d+)',
            r'(?:player\.vimeo\.com\/video\/)(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url
    
    def get_embed_url(self):
        """Get embed URL for iframe"""
        if self.video_type == 'youtube' and self.youtube_id:
            params = []
            if self.autoplay:
                params.append('autoplay=1')
            if self.loop:
                params.append('loop=1')
            if self.muted:
                params.append('mute=1')
            if self.controls:
                params.append('controls=1')
            else:
                params.append('controls=0')
            if self.start_time:
                params.append(f'start={self.start_time}')
            param_str = '&'.join(params) if params else ''
            return f"https://www.youtube.com/embed/{self.youtube_id}?{param_str}"
        
        elif self.video_type == 'vimeo' and self.vimeo_id:
            params = []
            if self.autoplay:
                params.append('autoplay=1')
            if self.muted:
                params.append('muted=1')
            param_str = '&'.join(params) if params else ''
            return f"https://player.vimeo.com/video/{self.vimeo_id}?{param_str}"
        
        return None
    
    def increment_view(self):
        self.views += 1
        self.save()

class VideoGallery(BaseModel):
    """Video gallery/playlist"""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    videos = models.ManyToManyField(Video, related_name='galleries')
    cover_image = models.ImageField(upload_to='videos/galleries/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name

class VideoAnalytics(BaseModel):
    """Track video analytics"""
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='analytics')
    session_id = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=[
        ('play', 'Play'),
        ('pause', 'Pause'),
        ('complete', 'Complete'),
        ('seek', 'Seek'),
    ])
    watch_time = models.IntegerField(default=0, help_text="Watch time in seconds")
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['video', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.video.title} - {self.action}"
