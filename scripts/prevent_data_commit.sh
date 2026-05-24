#!/usr/bin/env bash
set -euo pipefail

blocked_pattern='(^|/)(db\.sqlite3|db\.sqlite3\.|.*\.sqlite3|.*\.dump|.*\.sql|fixtures/.*(product|category).*\.json|exports?/|dumpdata/|media/(products|categories)/|.*products.*\.csv|.*categories.*\.csv|.*product-data.*\.json|.*category-data.*\.json|.*product_export.*|.*category_export.*)'

blocked_files="$(
  git diff --cached --name-only --diff-filter=ACMR \
    | grep -Ev '^(venv|venv[0-9]*|\.venv|env|ENV)/' \
    | grep -E "$blocked_pattern" || true
)"

if [ -n "$blocked_files" ]; then
  echo "Blocked commit: product/category data or database dump files are staged." >&2
  echo "$blocked_files" >&2
  echo "Unstage them with: git restore --staged <file>" >&2
  exit 1
fi
