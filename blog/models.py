from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django_ckeditor_5.fields import CKEditor5Field
from core.models import BaseModel
from accounts.models import User

class BlogCategory(BaseModel):
    """Article categories like Reviews, Guides, News, etc."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon")
    color = models.CharField(max_length=20, default="#3B82F6", help_text="Category color")
    featured_image = models.ImageField(upload_to='blog/categories/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name_plural = "Blog Categories"
        ordering = ['name']
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('blog:category', args=[self.slug])

class BlogTag(BaseModel):
    """Tags for articles"""
    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    
    class Meta:
        ordering = ['name']
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class BlogPost(BaseModel):
    """Article/Blog post with B&H style layout"""
    
    # Basic Info
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    excerpt = models.TextField(help_text="Short summary for listing pages")
    content = CKEditor5Field(config_name='default', help_text="Main article content")
    
    # Media
    featured_image = models.ImageField(upload_to='blog/featured/', null=True, blank=True, help_text="Main article image (1200x630 recommended)")
    thumbnail_image = models.ImageField(upload_to='blog/thumbnails/', null=True, blank=True, help_text="Small thumbnail (300x200)")
    gallery_images = models.JSONField(default=list, blank=True, help_text="Additional images for gallery")
    video_url = models.URLField(blank=True, help_text="YouTube or Vimeo URL for video content")
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.CharField(max_length=500, blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    
    # Organization
    category = models.ForeignKey(BlogCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    tags = models.ManyToManyField(BlogTag, blank=True, related_name='posts')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blog_posts')
    
    # Statistics
    views = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    reading_time = models.IntegerField(default=5, help_text="Estimated reading time in minutes")
    
    # Publication
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, help_text="Show on homepage")
    published_at = models.DateTimeField(default=timezone.now)
    
    # Advanced Features
    table_of_contents = models.JSONField(default=list, blank=True, help_text="Auto-generated TOC")
    related_posts = models.ManyToManyField('self', blank=True, symmetrical=False)
    schema_markup = models.JSONField(default=dict, blank=True, help_text="JSON-LD schema")
    
    # Styling
    custom_css = models.TextField(blank=True, help_text="Custom CSS for this article")
    layout_style = models.CharField(max_length=20, choices=[
        ('standard', 'Standard'),
        ('featured', 'Featured Image Top'),
        ('video', 'Video Focus'),
        ('gallery', 'Gallery Focus'),
        ('review', 'Product Review'),
    ], default='standard')
    
    class Meta:
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['slug', 'is_published']),
            models.Index(fields=['category', '-published_at']),
            models.Index(fields=['-views']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if not self.reading_time:
            # Estimate reading time (200 words per minute)
            word_count = len(self.content.split())
            self.reading_time = max(1, round(word_count / 200))
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('blog:detail', args=[self.slug])
    
    def increment_views(self):
        self.views += 1
        self.save(update_fields=['views'])
    
    def get_reading_time_display(self):
        if self.reading_time == 1:
            return "1 min read"
        return f"{self.reading_time} min read"

class BlogComment(BaseModel):
    """Comments on articles"""
    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blog_comments')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    comment = models.TextField()
    is_approved = models.BooleanField(default=True)
    likes = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment by {self.user.username} on {self.post.title}"
    
    @property
    def is_reply(self):
        return self.parent is not None

class NewsletterSubscriber(BaseModel):
    """Email newsletter subscribers"""
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.email
