from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
import os

def validate_file_size(value, max_size_mb=5):
    """Validate file size"""
    filesize = value.size
    max_size_bytes = max_size_mb * 1024 * 1024
    if filesize > max_size_bytes:
        raise ValidationError(f'Maximum file size is {max_size_mb}MB. Your file is {filesize / 1024 / 1024:.2f}MB')

def validate_image_extension(value):
    """Validate image file extension"""
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    if ext not in valid_extensions:
        raise ValidationError(f'Unsupported file extension. Allowed: {", ".join(valid_extensions)}')

def validate_image_dimensions(value, max_width=2000, max_height=2000, min_width=100, min_height=100):
    """Validate image dimensions using PIL"""
    try:
        w, h = get_image_dimensions(value)
        
        if w is None or h is None:
            raise ValidationError('Could not determine image dimensions')
        
        if w > max_width or h > max_height:
            raise ValidationError(f'Image dimensions too large. Maximum {max_width}x{max_height}, got {w}x{h}')
        
        if w < min_width or h < min_height:
            raise ValidationError(f'Image dimensions too small. Minimum {min_width}x{min_height}, got {w}x{h}')
            
        # Check aspect ratio (optional, not too restrictive)
        aspect_ratio = w / h
        if aspect_ratio < 0.5 or aspect_ratio > 2.0:
            # This is just a warning, not an error
            pass
            
    except Exception as e:
        raise ValidationError(f'Invalid image file: {str(e)}')

def validate_image_content_simple(value):
    """Simple content validation by checking file signature (magic bytes)"""
    # Read first few bytes to check file signature
    value.seek(0)
    header = value.read(12)
    value.seek(0)
    
    # Common image file signatures (magic bytes)
    magic_bytes = {
        b'\xff\xd8\xff': 'JPEG',
        b'\x89PNG\r\n\x1a\n': 'PNG',
        b'GIF87a': 'GIF',
        b'GIF89a': 'GIF',
        b'RIFF': 'WEBP',
    }
    
    is_valid = False
    for magic, fmt in magic_bytes.items():
        if header.startswith(magic):
            is_valid = True
            break
    
    if not is_valid:
        raise ValidationError('Invalid image file. Please upload a valid image (JPEG, PNG, GIF, or WEBP).')

# Combined validator for images
def validate_image(value):
    """Combined validation for all image uploads"""
    validate_file_size(value, max_size_mb=5)
    validate_image_extension(value)
    validate_image_content_simple(value)
    validate_image_dimensions(value, max_width=2000, max_height=2000, min_width=100, min_height=100)

# For profile avatars (smaller limits)
def validate_avatar(value):
    """Stricter validation for user avatars"""
    validate_file_size(value, max_size_mb=1)
    validate_image_extension(value)
    validate_image_content_simple(value)
    validate_image_dimensions(value, max_width=500, max_height=500, min_width=100, min_height=100)

# For ad banners
def validate_ad_image(value):
    """Validation for ad banner images"""
    validate_file_size(value, max_size_mb=2)
    validate_image_extension(value)
    validate_image_content_simple(value)
    validate_image_dimensions(value, max_width=1200, max_height=600, min_width=300, min_height=250)
