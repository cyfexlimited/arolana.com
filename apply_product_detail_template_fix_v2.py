#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import re
import shutil

TARGET = Path('templates/products/detail.html')

if not TARGET.exists():
    raise SystemExit(
        'ERROR: templates/products/detail.html not found.\n'
        'Run this script from the Arolana project root.'
    )

src = TARGET.read_text(encoding='utf-8')
original = src
changes = []

# 1) Locate the review form and fix the nearest Alpine tab panel before it.
review_form_pos = src.find('id="review-form"')
if review_form_pos == -1:
    raise RuntimeError('Could not find id="review-form".')

review_loop_pos = src.rfind('product.visible_reviews', 0, review_form_pos)
if review_loop_pos == -1:
    raise RuntimeError('Could not find product.visible_reviews before the review form.')

# Search backwards in a generous window around the Reviews section.
window_start = max(0, review_loop_pos - 25000)
window = src[window_start:review_loop_pos]

panel_pattern = re.compile(
    r'<div(?P<attrs>[^>]*\bx-show\s*=\s*["\']tab\s*==\s*\\?["\'](?P<tab>[A-Za-z0-9_-]+)\\?["\']["\'][^>]*)>',
    re.IGNORECASE,
)

matches = list(panel_pattern.finditer(window))
if not matches:
    raise RuntimeError('Could not locate the Alpine tab panel containing Reviews.')

panel_match = matches[-1]
opening_tag = panel_match.group(0)

if 'reviews' not in opening_tag.lower():
    fixed_tag = re.sub(
        r'(x-show\s*=\s*["\'])tab\s*==\s*\\?["\']qa\\?["\'](["\'])',
        r"\1tab=='reviews'\2",
        opening_tag,
        count=1,
        flags=re.IGNORECASE,
    )
    if fixed_tag == opening_tag:
        # Fallback: rewrite the whole x-show attribute only.
        fixed_tag = re.sub(
            r'x-show\s*=\s*["\'][^"\']+["\']',
            'x-show="tab==\'reviews\'"',
            opening_tag,
            count=1,
            flags=re.IGNORECASE,
        )
    if fixed_tag == opening_tag:
        raise RuntimeError('Found the Reviews panel but could not safely change its x-show binding.')

    absolute_start = window_start + panel_match.start()
    absolute_end = window_start + panel_match.end()
    src = src[:absolute_start] + fixed_tag + src[absolute_end:]
    changes.append('Reviews tab binding fixed')
else:
    print('INFO: Reviews tab binding is already correct.')

# 2) Remove misleading comment.
before = src
src = re.sub(
    r'^[ \t]*<!--\s*CLOSE REVIEWS TAB\s*-->\s*\n?',
    '',
    src,
    count=1,
    flags=re.MULTILINE,
)
if src != before:
    changes.append('Misleading Reviews comment removed')

# 3) Remove the late duplicate Lightbox V5 controller if present.
lightbox_script_pattern = re.compile(
    r'<script>\s*/\*\s*(?:=+\s*)?AROLANA LIGHTBOX IMAGE SOURCE FIX V5.*?</script>\s*',
    re.DOTALL | re.IGNORECASE,
)
lightbox_matches = list(lightbox_script_pattern.finditer(src))
if lightbox_matches:
    src = lightbox_script_pattern.sub(
        '<!-- Duplicate Lightbox V5 override removed by Arolana patch. -->\n',
        src,
    )
    changes.append(f'Removed {len(lightbox_matches)} duplicate Lightbox V5 controller block(s)')
else:
    print('INFO: No duplicate Lightbox V5 script block found; skipping.')

# 4) Add imported article sanitizer if missing.
if 'const sanitizeImportedArticleContent = function (root)' not in src:
    anchor = '                const removeImportedNoise = function (root) {\n                    if (!root) return;\n'
    if anchor not in src:
        raise RuntimeError('Article reader cleanup function anchor was not found.')

    sanitizer = '''                const sanitizeImportedArticleContent = function (root) {
                    if (!root) return;

                    root.querySelectorAll(
                        'script, noscript, object, embed, base, meta, link[rel="stylesheet"], form'
                    ).forEach(function (node) {
                        node.remove();
                    });

                    root.querySelectorAll('*').forEach(function (node) {
                        Array.from(node.attributes || []).forEach(function (attribute) {
                            const name = String(attribute.name || '').toLowerCase();
                            const value = String(attribute.value || '').trim();

                            if (name.startsWith('on') || name === 'srcdoc') {
                                node.removeAttribute(attribute.name);
                                return;
                            }

                            if (['href', 'src', 'poster', 'action', 'formaction'].includes(name)) {
                                const normalized = value
                                    .replace(/[\\u0000-\\u001F\\u007F\\s]+/g, '')
                                    .toLowerCase();

                                if (
                                    normalized.startsWith('javascript:') ||
                                    normalized.startsWith('vbscript:') ||
                                    normalized.startsWith('data:text/html')
                                ) {
                                    node.removeAttribute(attribute.name);
                                }
                            }
                        });

                        if (node.tagName === 'IFRAME') {
                            const rawSrc = node.getAttribute('src') || '';
                            try {
                                const parsedUrl = new URL(rawSrc, window.location.origin);
                                const host = parsedUrl.hostname.toLowerCase();
                                const allowedHosts = [
                                    window.location.hostname.toLowerCase(),
                                    'youtube.com',
                                    'www.youtube.com',
                                    'youtube-nocookie.com',
                                    'www.youtube-nocookie.com',
                                    'player.vimeo.com',
                                    'vimeo.com'
                                ];
                                if (!allowedHosts.includes(host)) {
                                    node.remove();
                                }
                            } catch (error) {
                                node.remove();
                            }
                        }
                    });
                };

'''
    src = src.replace(anchor, sanitizer + anchor, 1)
    changes.append('Imported article sanitizer added')
else:
    print('INFO: Imported article sanitizer already exists.')

if 'sanitizeImportedArticleContent(contentRoot);' not in src:
    call_anchor = '                removeImportedNoise(contentRoot);\n'
    if call_anchor not in src:
        raise RuntimeError('Article reader cleanup call was not found.')
    src = src.replace(
        call_anchor,
        call_anchor + '                sanitizeImportedArticleContent(contentRoot);\n',
        1,
    )
    changes.append('Imported article sanitizer call added')
else:
    print('INFO: Imported article sanitizer call already exists.')

# 5) Add x-cloak to all Alpine tab content panels.
tab_panel_pattern = re.compile(
    r'<div(?P<attrs>[^>]*\bx-show\s*=\s*["\']tab\s*==[^>]+)>',
    re.IGNORECASE,
)
cloak_count = 0

def add_cloak(match):
    global cloak_count
    whole = match.group(0)
    if re.search(r'\bx-cloak\b', whole):
        return whole
    cloak_count += 1
    return '<div x-cloak' + match.group('attrs') + '>'

src = tab_panel_pattern.sub(add_cloak, src)
if cloak_count:
    changes.append(f'Added x-cloak to {cloak_count} Alpine tab panel(s)')

if '[x-cloak]' not in src:
    style_close = src.find('\n</style>')
    if style_close == -1:
        raise RuntimeError('Could not find </style> for x-cloak CSS insertion.')
    src = src[:style_close] + '\n    [x-cloak] { display: none !important; }\n' + src[style_close:]
    changes.append('x-cloak CSS rule added')

# 6) Remove no-op image fallbacks.
for old in (
    'data-fallback-src="{{ article_card_url }}"',
    'data-fallback-src="{{ article_tab_url }}"',
):
    if old in src:
        src = src.replace(old, 'data-fallback-src=""')
        changes.append(f'Cleaned redundant article image fallback: {old}')

# Safety checks.
if 'sanitizeImportedArticleContent(contentRoot);' not in src:
    raise RuntimeError('Safety check failed: sanitizer call missing.')
if '[x-cloak]' not in src:
    raise RuntimeError('Safety check failed: x-cloak CSS missing.')

# Re-check that the Reviews area has a reviews-bound panel nearby.
review_form_pos = src.find('id="review-form"')
review_loop_pos = src.rfind('product.visible_reviews', 0, review_form_pos)
nearby = src[max(0, review_loop_pos - 25000):review_loop_pos]
if 'reviews' not in nearby.lower():
    raise RuntimeError('Safety check failed: Reviews panel binding could not be verified.')

if src == original:
    print('=' * 76)
    print('NO CHANGES NEEDED')
    print('=' * 76)
    print('The template already contains the requested fixes.')
    raise SystemExit(0)

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = TARGET.with_name(TARGET.name + '.backup_' + stamp)
shutil.copy2(TARGET, backup)
TARGET.write_text(src, encoding='utf-8')

print('=' * 76)
print('AROLANA PRODUCT DETAIL TEMPLATE FIX APPLIED')
print('=' * 76)
print('Updated:', TARGET)
print('Backup: ', backup)
print()
for change in changes:
    print('PASS', change)
print()
print('Run:')
print('  python manage.py check')
print('  python manage.py test_private_upload_validation')
print('  python manage.py audit_private_media_authorization --fail-on-error')
