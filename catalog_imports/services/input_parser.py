import re
from typing import Dict, List

URL_RE = re.compile(r"^https?://", flags=re.I)


def parse_inputs(value: str, maximum: int = 50) -> List[Dict[str, str]]:
    results = []
    seen = set()
    for raw in re.split(r"[\r\n]+", value or ""):
        item = raw.strip().strip("•-")
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({"value": item, "kind": "url" if URL_RE.match(item) else "name"})
        if len(results) >= maximum:
            break
    return results
