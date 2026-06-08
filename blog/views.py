import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from .models import BlogPost, BlogCategory, BlogTag, BlogComment

# Prefer the newsletter app subscriber model, but fall back safely if your project stores it in blog.models.
try:
    from newsletter.models import NewsletterSubscriber as NewsletterSubscriberModel
except Exception:
    from .models import NewsletterSubscriber as NewsletterSubscriberModel

def blog_list(request):
    """Blog listing page with filters, search, featured posts, and duplicate prevention."""
    base_posts = (
        BlogPost.objects
        .filter(is_published=True)
        .select_related('category', 'author')
        .prefetch_related('tags')
    )

    posts = base_posts

    # Filters
    category_slug = (request.GET.get('category') or '').strip()
    tag_slug = (request.GET.get('tag') or '').strip()
    search_query = (request.GET.get('q') or '').strip()
    sort_by = (request.GET.get('sort') or '-published_at').strip()

    if category_slug:
        posts = posts.filter(category__slug=category_slug)

    if tag_slug:
        posts = posts.filter(tags__slug=tag_slug)

    if search_query:
        posts = posts.filter(
            Q(title__icontains=search_query) |
            Q(content__icontains=search_query) |
            Q(excerpt__icontains=search_query)
        )

    # Use the filtered queryset for featured posts so category/search/tag pages stay relevant.
    filtered_posts = posts.distinct()

    # When user explicitly sorts by featured, show featured posts in the main grid,
    # and hide the separate featured section to avoid an empty "More Blog Posts" section.
    if sort_by == 'featured':
        featured_posts = []
        posts = filtered_posts.filter(is_featured=True).order_by('-published_at')
    else:
        featured_posts = list(
            filtered_posts
            .filter(is_featured=True)
            .order_by('-published_at')[:3]
        )
        featured_ids = [post.id for post in featured_posts]

        if featured_ids:
            posts = filtered_posts.exclude(id__in=featured_ids)
        else:
            posts = filtered_posts

        if sort_by == 'popular':
            posts = posts.order_by('-views', '-published_at')
        else:
            posts = posts.order_by('-published_at')

    posts = posts.distinct()

    paginator = Paginator(posts, 12)
    page = request.GET.get('page', 1)
    posts_page = paginator.get_page(page)

    categories = (
        BlogCategory.objects
        .filter(is_active=True)
        .annotate(post_count=Count('posts', filter=Q(posts__is_published=True), distinct=True))
        .filter(post_count__gt=0)
        .order_by('name')
    )

    popular_tags = (
        BlogTag.objects
        .annotate(post_count=Count('posts', filter=Q(posts__is_published=True), distinct=True))
        .filter(post_count__gt=0)
        .order_by('-post_count', 'name')[:15]
    )

    context = {
        'posts': posts_page,
        'featured_posts': featured_posts,
        'categories': categories,
        'popular_tags': popular_tags,
        'current_category': category_slug,
        'current_tag': tag_slug,
        'search_query': search_query,
        'sort_by': sort_by,
    }
    return render(request, 'blog/list.html', context)


def blog_detail(request, slug):
    """Article detail page with B&H style layout and integrated ads"""
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    
    # Increment view count
    post.views += 1
    post.save(update_fields=['views'])
    
    # Get related posts (same category or tags)
    related_posts = BlogPost.objects.filter(
        Q(category=post.category) | Q(tags__in=post.tags.all()),
        is_published=True
    ).exclude(id=post.id).distinct()[:4]
    
    # Get comments
    comments = post.comments.filter(is_approved=True, parent=None)
    
    # Get popular posts for sidebar
    popular_posts = BlogPost.objects.filter(is_published=True).order_by('-views')[:5]
    
    # Get categories with post counts
    categories = BlogCategory.objects.filter(is_active=True).annotate(
        post_count=Count('posts', filter=Q(posts__is_published=True), distinct=True)
    )
    
    # Generate table of contents from headings
    headings = re.findall(r'<h2[^>]*>(.*?)</h2>', post.content)
    toc = []
    for h in headings[:10]:
        clean_heading = re.sub(r'<[^>]+>', '', h).strip()
        heading_id = slugify(clean_heading)
        if clean_heading and heading_id:
            toc.append({'title': clean_heading, 'id': heading_id})
    
    article_image = post.display_image
    article_video_embed_url = post.get_video_embed_url()
    article_local_video_url = post.local_video_url

    # JSON-LD Schema for article
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title,
        "description": post.excerpt[:200],
        "image": request.build_absolute_uri(article_image.url) if article_image else None,
        "author": {
            "@type": "Person",
            "name": post.author.get_full_name() or post.author.username
        },
        "datePublished": post.published_at.isoformat(),
        "dateModified": post.updated_at.isoformat(),
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": request.build_absolute_uri()
        }
    }
    
    # ========== AD CONTROLS (can be overridden via context) ==========
    # These control which ad sections appear on the page
    # Set to False to hide specific ad sections
    
    ad_controls = {
        # Main content ads
        'display_ad_top': getattr(settings, 'DISPLAY_ARTICLE_TOP_AD', True) and post.show_article_top_ad,
        'display_ad_after_header': getattr(settings, 'DISPLAY_ARTICLE_AFTER_HEADER_AD', True),
        'display_ad_mid_1': getattr(settings, 'DISPLAY_ARTICLE_MID_AD', True),
        'display_ad_native': getattr(settings, 'DISPLAY_ARTICLE_NATIVE_AD', True) and post.show_article_native_ad,
        'display_ad_before_conclusion': getattr(settings, 'DISPLAY_ARTICLE_BEFORE_CONCLUSION_AD', True),
        'display_ad_after_author': getattr(settings, 'DISPLAY_ARTICLE_AFTER_AUTHOR_AD', True) and post.show_article_after_author_ad,
        'display_ad_footer': getattr(settings, 'DISPLAY_ARTICLE_FOOTER_AD', True) and post.show_article_footer_ad,
        
        # Sidebar ads
        'display_sidebar_search': getattr(settings, 'DISPLAY_SIDEBAR_SEARCH', True),
        'display_sidebar_ad_top': getattr(settings, 'DISPLAY_SIDEBAR_TOP_AD', True) and post.show_sidebar_top_ad,
        'display_sidebar_newsletter': getattr(settings, 'DISPLAY_SIDEBAR_NEWSLETTER', True) and post.show_sidebar_newsletter,
        'display_sidebar_ad_mid': getattr(settings, 'DISPLAY_SIDEBAR_MID_AD', True) and post.show_sidebar_mid_ad,
        'display_sidebar_popular': getattr(settings, 'DISPLAY_SIDEBAR_POPULAR', True),
        'display_sidebar_ad_bottom': getattr(settings, 'DISPLAY_SIDEBAR_BOTTOM_AD', True) and post.show_sidebar_bottom_ad,
        'display_sidebar_categories': getattr(settings, 'DISPLAY_SIDEBAR_CATEGORIES', True),
        'display_sidebar_sticky': getattr(settings, 'DISPLAY_SIDEBAR_STICKY_AD', True) and post.show_sidebar_sticky_ad,
    }
    
    context = {
        'post': post,
        'related_posts': related_posts,
        'comments': comments,
        'popular_posts': popular_posts,
        'categories': categories,
        'table_of_contents': toc,
        'schema': json.dumps(schema),
        'article_video_embed_url': article_video_embed_url,
        'article_local_video_url': article_local_video_url,
        # Ad controls
        **ad_controls,
        # Additional context for template
        'is_blog_detail': True,
    }
    return render(request, 'blog/detail.html', context)

def blog_category(request, slug):
    """Category page"""
    category = get_object_or_404(BlogCategory, slug=slug, is_active=True)
    posts = BlogPost.objects.filter(category=category, is_published=True)
    
    paginator = Paginator(posts, 12)
    page = request.GET.get('page', 1)
    posts_page = paginator.get_page(page)
    
    context = {
        'category': category,
        'posts': posts_page,
    }
    return render(request, 'blog/category.html', context)

def blog_tag(request, slug):
    """View posts by tag"""
    tag = get_object_or_404(BlogTag, slug=slug)
    posts = BlogPost.objects.filter(tags=tag, is_published=True)
    
    paginator = Paginator(posts, 12)
    page = request.GET.get('page', 1)
    posts_page = paginator.get_page(page)
    
    context = {
        'tag': tag,
        'posts': posts_page,
    }
    return render(request, 'blog/tag.html', context)

@login_required
def add_comment(request, slug):
    """Add comment or reply to a published blog post."""
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)

    if request.method != 'POST':
        return redirect('blog:detail', slug=post.slug)

    comment_text = (request.POST.get('comment') or '').strip()
    parent_id = request.POST.get('parent_id')

    if not comment_text:
        messages.error(request, 'Please enter a comment.')
        return redirect('blog:detail', slug=post.slug)

    parent = None
    if parent_id:
        # Keep replies tied to the same post only.
        parent = get_object_or_404(BlogComment, id=parent_id, post=post, parent=None)

    BlogComment.objects.create(
        post=post,
        user=request.user,
        parent=parent,
        comment=comment_text,
        is_approved=True
    )

    messages.success(request, 'Comment added successfully!')
    return redirect('blog:detail', slug=post.slug)


@login_required
def like_post(request, post_id):
    """Like a post via AJAX"""
    if request.method == 'POST':
        post = get_object_or_404(BlogPost, id=post_id, is_published=True)
        post.likes += 1
        post.save()
        return JsonResponse({'success': True, 'likes': post.likes})
    return JsonResponse({'success': False})

def newsletter_subscribe(request):
    """Newsletter subscription from blog"""
    if request.method == 'POST':
        import re
        from django.http import JsonResponse
        
        email = request.POST.get('email', '').strip()
        next_url = request.POST.get('next', '/')
        
        # Validate email
        if not email:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Email is required'})
            messages.error(request, 'Please enter your email address.')
            return redirect(next_url)
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Invalid email format'})
            messages.error(request, 'Please enter a valid email address.')
            return redirect(next_url)
        
        # Create subscriber
        subscriber, created = NewsletterSubscriberModel.objects.get_or_create(
            email=email,
            defaults={'source': 'blog', 'is_active': True}
        )
        
        if created:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'Successfully subscribed with {email}!'})
            messages.success(request, f'Successfully subscribed with {email}!')
        else:
            if subscriber.is_active:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Already subscribed', 'already_subscribed': True})
                messages.info(request, f'{email} is already subscribed.')
            else:
                subscriber.is_active = True
                subscriber.save()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': f'Welcome back! {email} has been re-subscribed.'})
                messages.success(request, f'Welcome back! {email} has been re-subscribed.')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Subscription successful!'})
        
        return redirect(next_url)
    
    return redirect('/')

@staff_member_required
def newsletter_admin(request):
    """Admin view for newsletter management"""
    subscribers = NewsletterSubscriberModel.objects.all().order_by('-created_at')
    
    # Statistics
    total_subscribers = subscribers.count()
    active_subscribers = subscribers.filter(is_active=True).count()
    inactive_subscribers = subscribers.filter(is_active=False).count()
    new_today = subscribers.filter(created_at__date=timezone.now().date()).count()
    
    # Pagination
    paginator = Paginator(subscribers, 50)
    page = request.GET.get('page', 1)
    subscribers_page = paginator.get_page(page)
    
    context = {
        'subscribers': subscribers_page,
        'total_subscribers': total_subscribers,
        'active_subscribers': active_subscribers,
        'inactive_subscribers': inactive_subscribers,
        'new_today': new_today,
    }
    return render(request, 'blog/newsletter_admin.html', context)

@staff_member_required
def send_newsletter(request):
    """Send newsletter to subscribers"""
    if request.method == 'POST':
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        if subject and message:
            subscribers = NewsletterSubscriberModel.objects.filter(is_active=True)
            # Here you would integrate with an email service
            # For now, just log it
            print(f"Sending newsletter '{subject}' to {subscribers.count()} subscribers")
            messages.success(request, f'Newsletter sent to {subscribers.count()} subscribers!')
        else:
            messages.error(request, 'Please provide both subject and message.')
        
        return redirect('blog:newsletter_admin')
    
    return render(request, 'blog/send_newsletter.html')
