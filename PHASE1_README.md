# Arolana Social Publishing — Phase 1 Foundation

This patch establishes the backend foundation for vendor, service-provider, and admin social publishing without enabling live external publishing yet.

## Included
- Generic SocialAccount owner model for vendor/provider/admin roles.
- SocialPublication state machine for YouTube/Instagram/Facebook/TikTok/LinkedIn.
- TemporaryVideoLease tracking for temporary staging and cleanup lifecycle.
- Subscription entitlement `social_publishing` enabled by default for Pro, Special, Enterprise and disabled for Free, Basic, Plus.
- Provider entitlement mirrors vendor gating through the shared subscription lifecycle.
- Read-only authenticated status API: `/api/social-publishing/accounts/status/?role=vendor|provider|admin`.
- Admin registration and feature flags; external platforms remain dark by default.
- No social passwords are stored.

## Not enabled yet
- Meta OAuth / publishing
- TikTok OAuth / publishing
- LinkedIn OAuth / publishing
- Vendor/provider Social Accounts UI
- Product/service publish selector UI
- Temporary Tigris upload/delete worker
- Retry queue/background worker

## Safety
The migration is included but was not applied to any database in this build environment.
External platform feature flags default to false.
