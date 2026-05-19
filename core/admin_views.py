from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.urls import reverse
from accounts.models import UserProfile
from core.models import SiteSettings

@staff_member_required
def upload_logo(request):
    site_settings = SiteSettings.objects.first() or SiteSettings.objects.create()

    if request.method == 'POST' and request.FILES.get('logo'):
        logo_file = request.FILES['logo']
        if site_settings.site_logo:
            site_settings.site_logo.delete(save=False)
        site_settings.site_logo.save(logo_file.name, logo_file, save=True)

        messages.success(request, 'Logo uploaded successfully. It now controls the storefront and admin logo.')
        return redirect(reverse('admin:core_sitesettings_change', args=[site_settings.pk]))

    context = {
        'site_settings': site_settings,
        'site_settings_admin_url': reverse('admin:core_sitesettings_change', args=[site_settings.pk]),
    }
    return render(request, 'admin/upload_logo.html', context)

@staff_member_required
def upload_user_avatar(request, user_id):
    from accounts.models import User
    user = User.objects.get(id=user_id)
    
    if request.method == 'POST' and request.FILES.get('avatar'):
        avatar_file = request.FILES['avatar']
        profile, created = UserProfile.objects.get_or_create(user=user)
        
        # Delete old avatar if exists
        if profile.avatar:
            profile.avatar.delete()
        
        profile.avatar.save(f'avatar_{user.id}_{avatar_file.name}', avatar_file)
        profile.save()
        messages.success(request, 'Avatar uploaded successfully!')
    
    return redirect(f'/admin/accounts/user/{user_id}/change/')

@staff_member_required
def delete_user_avatar(request, user_id):
    from accounts.models import User
    user = User.objects.get(id=user_id)
    
    if hasattr(user, 'profile') and user.profile.avatar:
        user.profile.avatar.delete()
        messages.success(request, 'Avatar deleted successfully!')
    
    return redirect(f'/admin/accounts/user/{user_id}/change/')
