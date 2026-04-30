from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages
from .models import Page, FAQ, SupportTopic, HelpCenterHero, SupportArticle, JobPosition, CareerCategory

def help_center(request):
    """Help Center page"""
    topics = SupportTopic.objects.filter(is_active=True).order_by('order')
    featured_faqs = FAQ.objects.filter(is_active=True, is_featured=True).order_by('order')[:6]
    hero = HelpCenterHero.objects.filter(is_active=True).first()
    
    if not featured_faqs:
        featured_faqs = FAQ.objects.filter(is_active=True).order_by('order')[:6]
    
    context = {
        'topics': topics,
        'featured_faqs': featured_faqs,
        'hero': hero,
        'page_title': 'Help Center',
    }
    return render(request, 'pages/help_center.html', context)

def faq_page(request):
    """FAQ page"""
    faqs = FAQ.objects.filter(is_active=True).order_by('category', 'order')
    
    categories = {}
    for faq in faqs:
        category_display = faq.get_category_display()
        if category_display not in categories:
            categories[category_display] = []
        categories[category_display].append(faq)
    
    context = {
        'categories': categories,
        'total_faqs': faqs.count(),
        'page_title': 'Frequently Asked Questions',
    }
    return render(request, 'pages/faq.html', context)

def article_detail(request, slug):
    """Support article detail page"""
    article = get_object_or_404(SupportArticle, slug=slug, is_active=True)
    article.views += 1
    article.save()
    
    # Get related articles from same category
    related_articles = SupportArticle.objects.filter(
        category=article.category,
        is_active=True
    ).exclude(id=article.id)[:5]
    
    context = {
        'article': article,
        'related_articles': related_articles,
    }
    return render(request, 'pages/article_detail.html', context)

def page_detail(request, slug):
    """Generic page detail"""
    page = get_object_or_404(Page, slug=slug, is_active=True)
    return render(request, 'pages/page_detail.html', {'page': page})

def support_redirect(request):
    """Redirect support to help center"""
    return HttpResponseRedirect(reverse('pages:help_center'))

def article_helpful(request, article_id):
    """Mark article as helpful or not"""
    if request.method == 'POST':
        article = get_object_or_404(SupportArticle, id=article_id)
        helpful = request.POST.get('helpful') == 'true'
        
        if helpful:
            article.helpful_count += 1
        else:
            article.not_helpful_count += 1
        article.save()
        
        messages.success(request, 'Thank you for your feedback!')
    
    return redirect('pages:article_detail', slug=article.slug)

def contact_page(request):
    """Contact page with form handling"""
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Here you can add email sending logic
        messages.success(request, 'Thank you for your message. We will get back to you soon!')
        return redirect('contact')
    
    return render(request, 'support/contact.html')

def careers_page(request):
    """Careers page - Dynamic from database"""
    # Get all active job positions from the database
    open_positions = JobPosition.objects.filter(is_active=True)
    
    # Get featured positions
    featured_positions = open_positions.filter(is_featured=True)[:3]
    
    # Get categories with positions
    categories = CareerCategory.objects.filter(is_active=True)
    
    # Group positions by category
    positions_by_category = {}
    for category in categories:
        positions = open_positions.filter(category=category)
        if positions.exists():
            positions_by_category[category.name] = positions
    
    context = {
        'page_title': 'Careers at Arolana',
        'open_positions': open_positions,
        'featured_positions': featured_positions,
        'positions_by_category': positions_by_category,
        'categories': categories,
        'total_positions': open_positions.count(),
    }
    return render(request, 'pages/careers.html', context)

def job_detail(request, slug):
    """View individual job position details"""
    position = get_object_or_404(JobPosition, slug=slug, is_active=True)
    
    # Get related positions (same category)
    related_positions = JobPosition.objects.filter(
        category=position.category,
        is_active=True
    ).exclude(id=position.id)[:3]
    
    context = {
        'position': position,
        'related_positions': related_positions,
    }
    return render(request, 'pages/job_detail.html', context)

def apply_for_job(request, position_id):
    """Handle job applications"""
    from .models import JobPosition, JobApplication
    
    if request.method == 'POST':
        position = get_object_or_404(JobPosition, id=position_id, is_active=True)
        
        # Validate required fields
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        
        if not all([first_name, last_name, email]):
            messages.error(request, 'Please fill in all required fields.')
            return redirect('pages:careers')
        
        # Create application
        application = JobApplication.objects.create(
            position=position,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=request.POST.get('phone', ''),
            cover_letter=request.POST.get('cover_letter', ''),
            portfolio_url=request.POST.get('portfolio_url', ''),
            linkedin_url=request.POST.get('linkedin_url', ''),
        )
        
        # Handle resume upload
        if request.FILES.get('resume'):
            application.resume = request.FILES['resume']
            application.save()
        
        messages.success(request, f'Thank you for applying for {position.title}! We will review your application and get back to you soon.')
        return redirect('pages:careers')
    
    # GET request - show application form
    position = get_object_or_404(JobPosition, id=position_id, is_active=True)
    return render(request, 'pages/apply_form.html', {'position': position})

def help_center_redirect(request, invalid_path=None):
    """Redirect any help center invalid paths to main help center"""
    return redirect('pages:help_center')
