# Social publishing token-key rollout

`SOCIAL_PUBLISHING_TOKEN_KEY` is optional for compatibility today. New writes use
the dedicated key when configured, while reads first try that key and then the
legacy `SECRET_KEY`-derived key. Existing Instagram ciphertext is not rewritten
by the Phase 2A migration.

Safe production rollout:

1. Generate a Fernet key in an approved secrets system; never store it in Git.
2. Back up the database and retain the current Django `SECRET_KEY`.
3. Set `SOCIAL_PUBLISHING_TOKEN_KEY` on a non-production environment and verify
   that an existing Instagram account decrypts through the legacy read path.
4. Deploy the application and migration before setting the production key.
5. Set the dedicated key and restart normally. Existing credentials remain
   legacy-readable; newly connected/refreshed credentials use the dedicated key.
6. Run a separate, reviewed data migration that decrypts each credential through
   the dual-read path and rewrites it with the dedicated key. Audit counts only;
   never log plaintext or ciphertext.
7. Verify all rows, then remove legacy fallback in a later release. Do not rotate
   Django `SECRET_KEY` until every legacy credential has been rewritten.

Key rotation after migration should use an explicit current/previous key ring,
rewrite credentials transactionally in bounded batches, verify counts, and only
then retire the previous key.
