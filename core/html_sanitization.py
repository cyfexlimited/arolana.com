"""Small allow-list sanitizer for admin/vendor-authored rich text.

The project deliberately keeps this helper dependency-free so the same policy
is available in model saves, forms, serializers, imports, and management jobs.
"""

from html import escape, unescape
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

from django.utils.html import strip_tags


ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s",
    "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "a",
}
VOID_TAGS = {"br"}
DROP_CONTENT_TAGS = {"script", "style", "iframe", "object", "embed", "form"}
SAFE_LINK_SCHEMES = {"", "http", "https", "mailto", "tel"}


class _RichTextSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self._drop_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in ALLOWED_TAGS:
            return
        rendered_attrs = []
        if tag == "a":
            values = {name.lower(): value for name, value in attrs if value is not None}
            href = values.get("href", "").strip()
            if href and urlparse(href).scheme.lower() in SAFE_LINK_SCHEMES:
                rendered_attrs.append(("href", href))
                title = values.get("title", "").strip()
                if title:
                    rendered_attrs.append(("title", title))
                rendered_attrs.extend([
                    ("target", "_blank"),
                    ("rel", "noopener noreferrer nofollow"),
                ])
        attributes = "".join(
            f' {name}="{escape(value, quote=True)}"'
            for name, value in rendered_attrs
        )
        self.output.append(f"<{tag}{attributes}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if not self._drop_depth and tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._drop_depth:
            self.output.append(escape(data))


def sanitize_rich_html(value):
    """Return safe, display-ready HTML while preserving useful formatting."""
    if not value:
        return ""
    parser = _RichTextSanitizer()
    parser.feed(str(value))
    parser.close()
    return "".join(parser.output).strip()


def normalize_rich_text_input(value):
    """Convert plain app text to safe paragraphs without flattening rich HTML."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.search(r"</?[a-zA-Z][^>]*>", raw):
        return sanitize_rich_html(raw)
    paragraphs = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [escape(line.strip()) for line in block.splitlines() if line.strip()]
        if lines:
            paragraphs.append(f"<p>{'<br>'.join(lines)}</p>")
    return "".join(paragraphs)


def rich_text_to_plain_text(value):
    """Return normalized plain text suitable for cards, search, and apps."""
    plain = unescape(strip_tags(str(value or "")))
    return " ".join(plain.split())


def rich_text_excerpt(value, limit=220):
    plain = rich_text_to_plain_text(value)
    if len(plain) <= limit:
        return plain
    return f"{plain[: max(1, limit - 1)].rstrip()}…"
