#!/bin/bash

echo "🚀 Arolana Quick Start"
echo "======================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from example..."
    cp .env.example .env
    echo "✅ .env created - edit it with your settings"
fi

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "🐍 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
echo "📦 Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# Run migrations
echo "🗄️  Running migrations..."
python manage.py migrate

# Create superuser
echo "👤 Creating superuser..."
python manage.py createsuperuser

# Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput

# Start server
echo ""
echo "✅ Setup complete! Starting server..."
echo "📍 Visit: http://127.0.0.1:8000/"
echo "📍 Admin: http://127.0.0.1:8000/admin/"
echo ""
python manage.py runserver 127.0.0.1:8000
