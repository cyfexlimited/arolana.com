#!/usr/bin/env python
import os
import sys
from pathlib import Path

def check_environment():
    """Check if environment is properly configured"""
    issues = []
    warnings = []
    
    print("🔍 Arolana Environment Check\n" + "="*40)
    
    # Check Python version
    python_version = sys.version_info
    print(f"✅ Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Check Django settings
    try:
        from django.conf import settings
        django_settings = settings.configured
        print(f"✅ Django settings loaded")
        
        if settings.DEBUG:
            warnings.append("DEBUG is True (OK for development)")
        else:
            print("✅ DEBUG is False (production mode)")
            
    except Exception as e:
        issues.append(f"Django settings not configured: {e}")
    
    # Check environment variables
    env_vars = ['SECRET_KEY', 'DEBUG', 'ALLOWED_HOSTS']
    for var in env_vars:
        if os.getenv(var):
            print(f"✅ {var} is set")
        else:
            warnings.append(f"{var} not set in environment")
    
    # Check .env file
    if Path('.env').exists():
        print("✅ .env file exists")
    else:
        issues.append(".env file missing")
    
    # Check .gitignore
    if Path('.gitignore').exists():
        if '.env' in Path('.gitignore').read_text():
            print("✅ .env is in .gitignore")
        else:
            warnings.append(".env not in .gitignore")
    else:
        warnings.append(".gitignore not found")
    
    # Check media directory permissions
    if Path('media').exists():
        import stat
        mode = oct(Path('media').stat().st_mode)[-3:]
        print(f"✅ Media directory exists (permissions: {mode})")
        if mode != '755' and mode != '775':
            warnings.append(f"Media directory permissions too open: {mode}")
    
    # Summary
    print("\n" + "="*40)
    if issues:
        print(f"❌ Issues found ({len(issues)}):")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("✅ No critical issues found")
    
    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"   - {warning}")
    
    print("\n✅ Environment check complete!")
    
if __name__ == "__main__":
    check_environment()
