from django import template
from django.utils.safestring import mark_safe
from videos.models import Video, VideoGallery
import json

register = template.Library()

@register.inclusion_tag('videos/player.html', takes_context=True)
def render_video(context, video_id):
    """Render a video player with modern features"""
    try:
        video = Video.objects.get(id=video_id, is_active=True)
    except Video.DoesNotExist:
        return {'video': None}
    
    # Track view
    video.increment_view()
    
    return {
        'video': video,
        'request': context.get('request'),
    }

@register.inclusion_tag('videos/gallery.html')
def render_video_gallery(gallery_slug, limit=None):
    """Render a video gallery/playlist"""
    try:
        gallery = VideoGallery.objects.get(slug=gallery_slug, is_active=True)
        videos = gallery.videos.filter(is_active=True)
        if limit:
            videos = videos[:limit]
    except VideoGallery.DoesNotExist:
        return {'gallery': None, 'videos': []}
    
    return {
        'gallery': gallery,
        'videos': videos,
    }

@register.simple_tag
def get_featured_videos(limit=6):
    """Get featured videos"""
    return Video.objects.filter(is_featured=True, is_active=True)[:limit]

@register.filter
def video_embed_url(video):
    """Get embed URL for video"""
    return video.get_embed_url()
