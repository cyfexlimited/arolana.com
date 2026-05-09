# Arolana Security Guide

## Current Security Status (Development)

✅ **Good**:
- Environment variables using `.env` file
- `.gitignore` configured to exclude sensitive files
- File validators ready for image uploads
- Security headers configured in settings
- CSRF protection enabled
- Password validators active

⚠️ **For Development (OK for now)**:
- DEBUG = True (development only)
- SQLite database (OK for local testing)
- No HTTPS (local development)

## To Deploy to Production:

1. **Set DEBUG = False** in `.env`
2. **Use PostgreSQL** instead of SQLite
3. **Enable HTTPS** with SSL certificate
4. **Set secure cookie flags**: `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`
5. **Set `ALLOWED_HOSTS`** to your actual domain
6. **Use environment-specific settings** for production
7. **Set up logging** to monitor security events
8. **Regular security updates** for all packages

## Regular Security Tasks

```bash
# Run security checks weekly
./scripts/check_security.sh

# Update dependencies monthly
./scripts/update_deps.sh
