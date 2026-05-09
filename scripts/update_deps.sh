#!/bin/bash

echo "🔄 Updating Arolana dependencies..."
echo ""

# Activate virtual environment (if not already)
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

echo "Current outdated packages:"
pip list --outdated

echo ""
echo "Updating Django to latest secure version..."
pip install --upgrade django==5.0.7

echo "Updating security-related packages..."
pip install --upgrade django-allauth django-ckeditor-5 Pillow

echo "Updating all other packages..."
pip freeze | cut -d '=' -f1 | xargs -n1 pip install --upgrade 2>/dev/null || true

echo ""
echo "Running security checks after updates..."
pip install --upgrade safety bandit
safety check
bandit -r . -x ./venv -f html -o security_report_updated.html

echo ""
echo "✅ Dependency updates complete!"
echo "📄 Updated security report: security_report_updated.html"
