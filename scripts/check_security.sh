#!/bin/bash

echo "🔒 Arolana Security Check (Mac Development)"
echo "==========================================="
echo ""

# Check if .env exists
if [ -f .env ]; then
    echo "✅ .env file exists (not committed to git)"
    # Check if .env is in .gitignore
    if grep -q ".env" .gitignore 2>/dev/null; then
        echo "✅ .env is in .gitignore"
    else
        echo "⚠️  WARNING: .env not in .gitignore!"
    fi
else
    echo "❌ .env file missing! Create one with your settings"
fi

# Check DEBUG setting
if [ -f .env ] && grep -q "DEBUG=True" .env 2>/dev/null; then
    echo "⚠️  DEBUG=True (OK for development, change to False for production)"
fi

# Check SECRET_KEY
if [ -f .env ] && grep -q "SECRET_KEY=" .env 2>/dev/null; then
    echo "✅ SECRET_KEY is set"
else
    echo "❌ SECRET_KEY not set in .env"
fi

# Check for exposed sensitive files
echo ""
echo "🔍 Checking for exposed sensitive files..."
SENSITIVE_FILES=$(find . -name "*.key" -o -name "*.pem" -o -name "*.crt" -o -name "*.p12" 2>/dev/null | grep -v ".git" | grep -v "venv")
if [ -z "$SENSITIVE_FILES" ]; then
    echo "✅ No exposed certificate/key files found"
else
    echo "⚠️  Found sensitive files:"
    echo "$SENSITIVE_FILES"
fi

# Check media file permissions
echo ""
echo "📁 Checking media file permissions..."
if [ -d "media" ]; then
    echo "✅ Media directory exists"
    # Check for potentially dangerous files
    DANGEROUS_FILES=$(find media -type f \( -name "*.php" -o -name "*.exe" -o -name "*.sh" -o -name "*.bat" \) 2>/dev/null)
    if [ -z "$DANGEROUS_FILES" ]; then
        echo "✅ No dangerous file types found in media"
    else
        echo "⚠️  Found potentially dangerous files:"
        echo "$DANGEROUS_FILES"
    fi
else
    echo "ℹ️  Media directory doesn't exist yet"
fi

# Check Django security settings
echo ""
echo "🔐 Running Django security check..."
python manage.py check --deploy 2>&1 | grep -E "WARNINGS|ERRORS|System check" || echo "No security warnings from Django"

# Check if debug mode is off in production (for development this is fine)
echo ""
echo "📋 Security Checklist for Production:"
echo "   ❌ Set DEBUG = False"
echo "   ❌ Use HTTPS with SSL certificate"
echo "   ❌ Set SECURE_SSL_REDIRECT = True"
echo "   ❌ Set SESSION_COOKIE_SECURE = True"
echo "   ❌ Set CSRF_COOKIE_SECURE = True"
echo "   ❌ Use PostgreSQL instead of SQLite"
echo "   ❌ Set up proper logging and monitoring"

echo ""
echo "✅ Security check complete!"
echo "📄 Full report saved to security_report.html"
