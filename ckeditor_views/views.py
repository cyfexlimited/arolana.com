import time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import json
import os
from django.conf import settings

@csrf_exempt
def upload_file(request):
    """Handle file uploads for CKEditor 5"""
    if request.method == 'POST' and request.FILES.get('upload'):
        uploaded_file = request.FILES['upload']
        
        # Create upload directory if it doesn't exist
        upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads', 'ckeditor5')
        os.makedirs(upload_path, exist_ok=True)
        
        # Save the file
        timestamp = int(time.time())
        safe_name = uploaded_file.name.replace(' ', '_')
        file_name = f"{timestamp}_{safe_name}"
        file_path = os.path.join('uploads', 'ckeditor5', file_name)
        saved_path = default_storage.save(file_path, ContentFile(uploaded_file.read()))
        
        # Return the URL
        file_url = default_storage.url(saved_path)
        
        return JsonResponse({
            'uploaded': True,
            'url': file_url,
            'fileName': file_name
        })
    
    return JsonResponse({'uploaded': False, 'error': {
        'message': 'No file uploaded or incorrect field name. Expected "upload" field.'
    }})

@csrf_exempt
def browse_files(request):
    """Browse files for CKEditor 5"""
    upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads', 'ckeditor5')
    files = []
    
    if os.path.exists(upload_path):
        for filename in os.listdir(upload_path):
            file_path = os.path.join('uploads', 'ckeditor5', filename)
            full_path = os.path.join(upload_path, filename)
            if os.path.isfile(full_path):
                files.append({
                    'name': filename,
                    'url': default_storage.url(file_path),
                    'size': os.path.getsize(full_path)
                })
    
    return JsonResponse({'files': files})