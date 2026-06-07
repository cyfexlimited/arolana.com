import os
import mimetypes

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Sync all files from the local MEDIA_ROOT directory to the configured '
        'S3-compatible bucket (Railway Tidy Drop), preserving directory structure.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Walk the local media directory and report what would be uploaded without actually uploading.',
        )
        parser.add_argument(
            '--prefix',
            type=str,
            default='',
            help='Only sync files whose relative path starts with this prefix (e.g. "products/").',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            default=True,
            help='Skip files that already exist in the bucket (default: True).',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite files that already exist in the bucket.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        prefix = options['prefix'].lstrip('/')
        overwrite = options['overwrite']
        skip_existing = not overwrite

        # ── Validate S3 configuration ──────────────────────────────────────
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '')
        endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', '')

        if not bucket_name or not endpoint_url:
            raise CommandError(
                'AWS_STORAGE_BUCKET_NAME and AWS_S3_ENDPOINT_URL must both be set '
                'in your environment before running this command.'
            )

        media_root = str(settings.MEDIA_ROOT)
        if not os.path.isdir(media_root):
            raise CommandError(
                f'MEDIA_ROOT directory does not exist or is not a directory: {media_root}'
            )

        # ── Build boto3 client ─────────────────────────────────────────────
        client_kwargs = {
            'endpoint_url': endpoint_url,
            'region_name': getattr(settings, 'AWS_S3_REGION_NAME', 'auto'),
        }
        aws_access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        aws_secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
        if aws_access_key and aws_secret_key:
            client_kwargs['aws_access_key_id'] = aws_access_key
            client_kwargs['aws_secret_access_key'] = aws_secret_key

        s3 = boto3.client('s3', **client_kwargs)

        # ── Pre-fetch existing keys for skip-existing mode ─────────────────
        existing_keys: set[str] = set()
        if skip_existing and not dry_run:
            self.stdout.write('Fetching existing keys from bucket …')
            paginator = s3.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=bucket_name,
                Prefix=prefix,
            )
            for page in page_iterator:
                for obj in page.get('Contents', []):
                    existing_keys.add(obj['Key'])
            self.stdout.write(f'  Found {len(existing_keys):,} existing object(s) in bucket.')

        # ── Walk MEDIA_ROOT ────────────────────────────────────────────────
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('📂  SYNC MEDIA → S3')
        if dry_run:
            self.stdout.write('⚠️   DRY RUN — no files will be uploaded')
        self.stdout.write(f'    Bucket   : {bucket_name}')
        self.stdout.write(f'    Endpoint : {endpoint_url}')
        self.stdout.write(f'    Local    : {media_root}')
        if prefix:
            self.stdout.write(f'    Prefix   : {prefix}')
        self.stdout.write('=' * 70 + '\n')

        uploaded = 0
        skipped = 0
        errors = 0
        total_bytes = 0

        for dirpath, _dirnames, filenames in os.walk(media_root):
            for filename in filenames:
                local_path = os.path.join(dirpath, filename)

                # Compute the S3 key (relative to MEDIA_ROOT)
                relative_path = os.path.relpath(local_path, media_root)
                # Normalise to forward slashes for S3
                s3_key = relative_path.replace(os.sep, '/')

                # Apply optional prefix filter
                if prefix and not s3_key.startswith(prefix):
                    skipped += 1
                    continue

                # Skip existing unless --overwrite
                if skip_existing and s3_key in existing_keys:
                    self.stdout.write(f'  ⏭  SKIP  {s3_key}')
                    skipped += 1
                    continue

                file_size = os.path.getsize(local_path)
                content_type, _ = mimetypes.guess_type(local_path)
                content_type = content_type or 'application/octet-stream'

                size_label = self._human_size(file_size)
                self.stdout.write(f'  ⬆  {s3_key}  ({size_label})')

                if dry_run:
                    uploaded += 1
                    total_bytes += file_size
                    continue

                try:
                    extra_args = {'ContentType': content_type}
                    cache_control = getattr(settings, 'AWS_S3_OBJECT_PARAMETERS', {}).get('CacheControl')
                    if cache_control:
                        extra_args['CacheControl'] = cache_control

                    s3.upload_file(
                        Filename=local_path,
                        Bucket=bucket_name,
                        Key=s3_key,
                        ExtraArgs=extra_args,
                    )
                    uploaded += 1
                    total_bytes += file_size
                except (BotoCoreError, ClientError, OSError) as exc:
                    self.stdout.write(
                        self.style.ERROR(f'  ❌ ERROR  {s3_key}: {exc}')
                    )
                    errors += 1

        # ── Summary ────────────────────────────────────────────────────────
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('📊  SUMMARY')
        self.stdout.write('=' * 70)
        action = 'Would upload' if dry_run else 'Uploaded'
        self.stdout.write(
            self.style.SUCCESS(f'  ✅ {action}  : {uploaded:,} file(s)  ({self._human_size(total_bytes)})')
        )
        self.stdout.write(f'  ⏭  Skipped  : {skipped:,} file(s)')
        if errors:
            self.stdout.write(self.style.ERROR(f'  ❌ Errors   : {errors:,} file(s)'))
        else:
            self.stdout.write(f'  ❌ Errors   : 0')
        self.stdout.write('=' * 70 + '\n')

        if dry_run:
            self.stdout.write('💡  Re-run without --dry-run to perform the actual upload.\n')

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _human_size(num_bytes: int) -> str:
        """Return a human-readable file size string."""
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if num_bytes < 1024:
                return f'{num_bytes:.1f} {unit}'
            num_bytes /= 1024
        return f'{num_bytes:.1f} PB'
