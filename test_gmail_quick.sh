#!/bin/bash
echo "📧 Testing Gmail SMTP Configuration"
echo "=================================="
echo ""

# Check if .env exists
if [ -f .env ]; then
    source .env
    echo "✅ Loading credentials from .env"
else
    echo "⚠️ .env file not found"
    echo "Create .env with:"
    echo "EMAIL_HOST_USER=cyfexlimited8@gmail.com"
    echo "EMAIL_HOST_PASSWORD=your-app-password"
    echo ""
fi

# Run the test
python manage.py test_gmail cyfexlimited8@gmail.com
