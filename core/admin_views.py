from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from accounts.models import UserProfile
import os

@staff_member_required
def upload_logo(request):
    if request.method == 'POST' and request.FILES.get('logo'):
        logo_file = request.FILES['logo']
        
        # Save logo to static directory (not staticfiles)
        static_dir = os.path.join(settings.BASE_DIR, 'static', 'admin', 'images')
        os.makedirs(static_dir, exist_ok=True)
        
        logo_path = os.path.join(static_dir, 'arolana-logo.png')
        
        # Save the file
        with open(logo_path, 'wb+') as destination:
            for chunk in logo_file.chunks():
                destination.write(chunk)
        
        # Also copy to staticfiles if it exists
        staticfiles_dir = os.path.join(settings.BASE_DIR, 'staticfiles', 'admin', 'images')
        if os.path.exists(settings.BASE_DIR / 'staticfiles'):
            os.makedirs(staticfiles_dir, exist_ok=True)
            with open(os.path.join(staticfiles_dir, 'arolana-logo.png'), 'wb+') as dest:
                for chunk in logo_file.chunks():
                    dest.write(chunk)
        
        messages.success(request, 'Logo uploaded successfully!')
        return redirect('/admin/')
    
    return render(request, 'admin/upload_logo.html')

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