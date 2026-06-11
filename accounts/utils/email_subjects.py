import re

from django.utils.encoding import force_str


AROLANA_SUBJECT_PREFIX = "[Arolana]"
_REPEATED_PREFIX = re.compile(r"^(?:\[Arolana\]\s*)+", re.IGNORECASE)


def format_arolana_subject(subject):
    """Return a subject with exactly one Arolana brand prefix."""
    clean_subject = _REPEATED_PREFIX.sub("", force_str(subject or "")).strip()
    return f"{AROLANA_SUBJECT_PREFIX} {clean_subject}".strip()
