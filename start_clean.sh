#!/bin/bash
echo "🚀 Starting Arolana - Clean Mode"
echo "================================"
echo ""

# Kill existing processes
pkill -f "python manage.py runserver" 2>/dev/null
lsof -ti:8000 | xargs kill -9 2>/dev/null

# Clear Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Start server with minimal output
python manage.py runserver --noreload --verbosity 0 2>&1 | grep -v "Auto-detected\|Auto-set\|WARNING.*favicon\|WARNING.*wishlist"
