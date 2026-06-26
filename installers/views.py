from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from notifications.models import Notification
from products.models import Product

from .forms import (
    ProviderRegistrationForm,
    ProviderServiceForm,
    ServicePortfolioForm,
    ServiceQuoteRequestForm,
    ServiceReviewForm,
)
from .models import ServiceCategory, ServiceProviderProfile
from .services import filter_public_providers, notify_staff_provider_registration, notify_staff_service_quote


def directory(request):
    providers = filter_public_providers(request.GET)
    categories = (
        ServiceCategory.objects.filter(is_active=True)
        .annotate(provider_count=Count("provider_services__provider", distinct=True))
        .order_by("name")
    )
    page = Paginator(providers, 18).get_page(request.GET.get("page"))
    return render(request, "installers/directory.html", {
        "page_obj": page,
        "providers": page.object_list,
        "categories": categories,
        "provider_types": ServiceProviderProfile.PROVIDER_TYPES,
        "seo_title": "Verified Installers & Engineers | Arolana",
        "seo_description": "Find verified installers, repair engineers, technicians, trainers, and consultants on Arolana.",
    })


def category_detail(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)
    providers = filter_public_providers({**request.GET.dict(), "category": category.slug})
    page = Paginator(providers, 18).get_page(request.GET.get("page"))
    return render(request, "installers/category_detail.html", {
        "category": category,
        "page_obj": page,
        "providers": page.object_list,
        "seo_title": f"Verified {category.name} in Nigeria | Arolana",
        "seo_description": category.description or f"Find trusted and verified {category.name.lower()} on Arolana.",
    })


def provider_detail(request, slug):
    provider = get_object_or_404(
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related("services__category", "portfolio_items", "reviews__customer"),
        slug=slug,
    )
    return render(request, "installers/provider_detail.html", {
        "provider": provider,
        "services": provider.services.filter(is_active=True).select_related("category"),
        "portfolio_items": provider.portfolio_items.all(),
        "reviews": provider.reviews.filter(is_approved=True).select_related("customer")[:20],
        "review_form": ServiceReviewForm(),
        "seo_title": f"{provider.business_name} - Verified {provider.get_provider_type_display()} | Arolana",
        "seo_description": provider.description[:160],
    })


@login_required
def register_provider(request):
    instance = ServiceProviderProfile.objects.filter(user=request.user).first()
    if request.method == "POST":
        form = ProviderRegistrationForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            provider = form.save(commit=False)
            provider.user = request.user
            if instance:
                provider.verification_status = ServiceProviderProfile.STATUS_PENDING
                provider.is_verified = False
            provider.save()
            notify_staff_provider_registration(provider)
            messages.success(request, "Your provider profile was saved and sent for Arolana verification.")
            return redirect("installers:provider_dashboard")
    else:
        initial = {
            "contact_person": request.user.get_full_name(),
            "email": request.user.email,
            "phone_number": getattr(request.user, "phone_number", "") or "",
        }
        form = ProviderRegistrationForm(instance=instance, initial=initial)
    return render(request, "installers/provider_form.html", {"form": form, "provider": instance})


@login_required
def provider_dashboard(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    return render(request, "installers/provider_dashboard.html", {
        "provider": provider,
        "services": provider.services.select_related("category"),
        "portfolio_items": provider.portfolio_items.all(),
        "quote_requests": provider.quote_requests.select_related("product", "category")[:30],
    })


@login_required
def add_provider_service(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    form = ProviderServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = form.save(commit=False)
        service.provider = provider
        service.save()
        messages.success(request, "Service added.")
        return redirect("installers:provider_dashboard")
    return render(request, "installers/simple_form.html", {"form": form, "title": "Add service"})


@login_required
def add_portfolio(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    form = ServicePortfolioForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        portfolio = form.save(commit=False)
        portfolio.provider = provider
        portfolio.save()
        messages.success(request, "Portfolio project added.")
        return redirect("installers:provider_dashboard")
    return render(request, "installers/simple_form.html", {"form": form, "title": "Add portfolio project"})


def request_quote(request):
    initial = {}
    provider_id = request.GET.get("provider")
    category_id = request.GET.get("category")
    product_id = request.GET.get("product")
    if provider_id:
        initial["provider"] = ServiceProviderProfile.objects.public().filter(pk=provider_id).first()
    if category_id:
        initial["category"] = ServiceCategory.objects.filter(pk=category_id, is_active=True).first()
    if product_id:
        product = Product.objects.filter(pk=product_id, is_active=True, approval_status="approved").first()
        initial["product"] = product
        if product:
            initial["service_needed"] = f"Service support for {product.name}"
    if request.user.is_authenticated:
        initial.update({
            "name": request.user.get_full_name(),
            "email": request.user.email,
            "phone": getattr(request.user, "phone_number", "") or "",
        })
    form = ServiceQuoteRequestForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        quote = form.save(commit=False)
        if request.user.is_authenticated:
            quote.customer = request.user
        quote.save()
        notify_staff_service_quote(quote)
        if quote.provider:
            Notification.send(
                quote.provider.user,
                "message",
                "New service quote request",
                f"{quote.name} requested {quote.service_needed} in {quote.city}, {quote.state}.",
                link="/installers/dashboard/",
                metadata={"service_quote_request_id": quote.id, "product_id": quote.product_id},
                priority=3,
            )
        messages.success(request, "Your request has been sent. A verified professional or Arolana support will contact you.")
        return redirect("installers:quote_success")
    return render(request, "installers/quote_form.html", {"form": form})


def quote_success(request):
    return render(request, "installers/quote_success.html")


@login_required
def submit_review(request, slug):
    provider = get_object_or_404(ServiceProviderProfile.objects.public(), slug=slug)
    form = ServiceReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.provider = provider
        review.customer = request.user
        review.save()
        messages.success(request, "Thank you. Your review will appear after moderation.")
        return redirect(provider.get_absolute_url())
    return render(request, "installers/simple_form.html", {"form": form, "title": f"Review {provider.business_name}"})
