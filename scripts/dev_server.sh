#!/bin/bash

echo "🚀 Starting Arolana Development Server"
echo "======================================"
echo ""
echo "📌 IMPORTANT: The development server only supports HTTP, not HTTPS"
echo "   Visit: http://127.0.0.1:8000/ (not https://)"
echo ""

# Check if port 8000 is in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 8000 is already in use. Killing existing process..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    sleep 2
fi

# Start the server with proper host
python manage.py runserver 127.0.0.1:8000
