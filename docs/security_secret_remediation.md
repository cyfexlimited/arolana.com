# Arolana exposed-secret remediation and production security verification

Date: 2026-07-20

This runbook documents the remediation sequence for the live-looking credentials identified during the Technical and AI-Commerce Audit. It intentionally does not repeat secret values.

## Immediate rotation order

Rotate in this order so payment and authentication risks are closed before lower-risk integration keys:

1. `SECRET_KEY`
2. `DATABASE_URL` / production database password
3. Paystack secret and public keys
4. Flutterwave secret, public, encryption and webhook keys
5. PayPal client secret
6. Google OAuth client secret
7. Email/SMTP credentials
8. Cloudinary API secret
9. Any remaining analytics, webhook or third-party integration secrets

After each provider-side rotation, update Railway/production environment variables only through the hosting dashboard or CLI secret store. Do not commit secrets to the repository.

## Repository remediation

- Remove committed `.env` material from Git history before treating the repository as safe.
- Keep `.env`, `.env.*`, private keys, generated payment payloads and database dumps ignored.
- Commit only `.env.example` style placeholders.
- Confirm no live-looking credentials remain in tracked files before release:

```bash
git grep -n -I -E "(SECRET_KEY|PAYSTACK|FLUTTERWAVE|PAYPAL|DATABASE_URL|GOOGLE_CLIENT_SECRET|EMAIL_HOST_PASSWORD|CLOUDINARY|api_token|private_key|webhook_secret)"
```

Any result must be reviewed manually because some safe settings names are expected.

## Production verification checklist

Run these checks after rotated values are deployed:

```bash
python manage.py check --deploy --fail-level WARNING
python manage.py audit_mobile_customer_tokens --dry-run
python manage.py test mobile_customers.tests.MobileCustomerWebAccountAuthenticationTests.test_native_registration_creates_real_user_then_verifies_otp ai_core -v 2
```

For the 2026-07-20 local verification pass, `manage.py check` returned no issues. `manage.py check --deploy --fail-level WARNING` failed against the local `.env` because local development has `DEBUG=True`, an insecure placeholder `SECRET_KEY`, SSL redirect disabled and secure cookies disabled. With production-like overrides for `DEBUG=False`, a long rotated `SECRET_KEY`, SSL redirect, secure cookies, HSTS, HSTS subdomains and HSTS preload, the deploy check returned no issues.

Production release gate:

```bash
DEBUG=False \
SECRET_KEY="<rotated-long-random-secret>" \
SECURE_SSL_REDIRECT=True \
SESSION_COOKIE_SECURE=True \
CSRF_COOKIE_SECURE=True \
SECURE_HSTS_SECONDS=31536000 \
SECURE_HSTS_INCLUDE_SUBDOMAINS=True \
SECURE_HSTS_PRELOAD=True \
python manage.py check --deploy --fail-level WARNING
```

Only enable HSTS subdomains and preload after confirming every production subdomain is HTTPS-only.

Then verify these production behaviors:

- New customer registration creates a real `User`, sends/accepts OTP, and returns mobile-safe profile data.
- Legacy mobile tokens are accepted only by the compatibility authenticator and are upgraded/hashed where applicable.
- Staff, vendor, provider and rider mobile authentication paths reject customer-only tokens.
- Payment callbacks still validate provider signatures after gateway secret rotation.
- Admin login, password reset email and OAuth login work after credential rotation.
- `DEBUG=False`, HTTPS redirects, secure cookies, CSRF trusted origins and `ALLOWED_HOSTS` match production domains.
- Object/private media URLs remain protected and cannot be fetched anonymously.

## Rollback notes

If a rotated credential breaks a provider integration, prefer rolling forward with a corrected new credential. Reinstating an exposed old secret should require explicit owner approval and should be treated as a temporary incident exception.
