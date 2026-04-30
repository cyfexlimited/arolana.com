from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils.html import escape
from .models import Video, VideoAnalytics
import json
import re


# -----------------------------
# Utilities
# -----------------------------
def extract_youtube_id(url: str) -> str:
    """Extract YouTube video ID (robust for all formats)"""
    if not url:
        return ""

    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11})"
    match = re.search(pattern, url)

    return match.group(1) if match else url.strip()


# -----------------------------
# Views
# -----------------------------
def video_watch(request, video_id):
    """Render video watch page"""
    video = get_object_or_404(Video, id=video_id, is_active=True)

    # Normalize YouTube ID (no unnecessary save)
    if video.youtube_id:
        clean_id = extract_youtube_id(video.youtube_id)
        if clean_id != video.youtube_id:
            Video.objects.filter(id=video.id).update(youtube_id=clean_id)
            video.youtube_id = clean_id

    related_videos = (
        Video.objects
        .filter(is_active=True)
        .exclude(id=video_id)
        .order_by('-views')[:6]
    )

    return render(request, 'videos/watch.html', {
        'video': video,
        'related_videos': related_videos,
    })


@require_POST
def track_video_event(request):
    """Track video analytics"""
    try:
        data = json.loads(request.body.decode('utf-8'))

        video_id = data.get('video_id')
        action = data.get('action')
        watch_time = int(data.get('watch_time', 0))

        if not video_id or not action:
            return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)

        video = get_object_or_404(Video, id=video_id)

        # Ensure session exists
        if not request.session.session_key:
            request.session.create()

        VideoAnalytics.objects.create(
            video=video,
            session_id=request.session.session_key,
            user=request.user if request.user.is_authenticated else None,
            action=action,
            watch_time=watch_time,
            ip_address=request.META.get('REMOTE_ADDR', ''),
        )

        return JsonResponse({'success': True})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def video_gallery(request, slug):
    """Render video gallery"""
    from .models import VideoGallery

    gallery = get_object_or_404(VideoGallery, slug=slug, is_active=True)
    videos = gallery.videos.filter(is_active=True)

    return render(request, 'videos/gallery.html', {
        'gallery': gallery,
        'videos': videos,
    })


def video_embed(request, video_id):
    """Return embeddable video HTML (single clean version)"""
    try:
        video = get_object_or_404(Video, id=video_id, is_active=True)

        # Optional: track view (only if method exists)
        if hasattr(video, "increment_view"):
            video.increment_view()

        # Clean IDs
        yt_id = extract_youtube_id(video.youtube_id) if video.youtube_id else ""

        html = ""

        # -----------------------------
        # YouTube
        # -----------------------------
        if video.video_type == 'youtube' and yt_id:
            html = f"""
            <div class="relative w-full h-full bg-black">
                <iframe
                    class="w-full h-full"
                    src="https://www.youtube.com/embed/{escape(yt_id)}?autoplay=1&rel=0&modestbranding=1"
                    title="{escape(video.title)}"
                    frameborder="0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen>
                </iframe>
            </div>
            """

        # -----------------------------
        # Vimeo
        # -----------------------------
        elif video.video_type == 'vimeo' and video.vimeo_id:
            html = f"""
            <div class="relative w-full h-full bg-black">
                <iframe
                    class="w-full h-full"
                    src="https://player.vimeo.com/video/{video.vimeo_id}?autoplay=1"
                    title="{escape(video.title)}"
                    frameborder="0"
                    allow="autoplay; fullscreen"
                    allowfullscreen>
                </iframe>
            </div>
            """

        # -----------------------------
        # Local video
        # -----------------------------
        elif video.video_file:
            html = f"""
            <div class="relative w-full h-full bg-black">
                <video controls autoplay class="w-full h-full">
                    <source src="{video.video_file.url}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
            """

        # -----------------------------
        # Fallback
        # -----------------------------
        else:
            html = f"""
            <div class="flex items-center justify-center h-full bg-black text-white">
                <div class="text-center">
                    <p>Video unavailable</p>
                    <p class="text-sm opacity-50 mt-2">
                        ID: {escape(video.youtube_id or video.vimeo_id or '')}
                    </p>
                </div>
            </div>
            """

        return JsonResponse({'html': html, 'success': True})

    except Exception as e:
        return JsonResponse({
            'html': f'''
            <div class="flex items-center justify-center h-full bg-black text-white">
                <div class="text-center">
                    <p>Error loading video</p>
                    <p class="text-sm opacity-50 mt-2">{escape(str(e))}</p>
                </div>
            </div>
            ''',
            'success': False
        }, status=500)


def product_videos(request, product_id):
    """Return product videos"""
    from products.models import Product

    try:
        product = get_object_or_404(Product, id=product_id)

        videos = [
            {
                'id': pv.video.id,
                'title': pv.video.title,
                'thumbnail': (
                    pv.video.custom_thumbnail.url
                    if pv.video.custom_thumbnail
                    else pv.video.auto_thumbnail
                ),
            }
            for pv in product.videos.select_related('video')
        ]

        return JsonResponse({'videos': videos, 'success': True})

    except Exception as e:
        return JsonResponse({
            'videos': [],
            'success': False,
            'error': str(e)
        }, status=500)