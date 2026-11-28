#!/usr/bin/env bash
# PostToolUse hook (Edit/Write): fast checks on the file Claude just changed.
#   Python  → ruff (syntax errors, undefined names)
#   web/src → TypeScript type check
# Exit 2 sends the errors back to Claude so it fixes them right away.
set -u
root="$(cd "$(dirname "$0")/../.." && pwd)"
file="$(jq -r '.tool_input.file_path // empty')"
[ -n "$file" ] || exit 0
case "$file" in
  "$root"/certiflow/*.py|"$root"/tests/*.py)
    ruff="$root/.venv/bin/ruff"; [ -x "$ruff" ] || exit 0
    out="$("$ruff" check --quiet --select E9,F63,F7,F82 "$file" 2>&1)" || { echo "ruff: $out" >&2; exit 2; }
    ;;
  "$root"/web/src/*.ts|"$root"/web/src/*.tsx)
    out="$(cd "$root/web" && npx --no-install tsc -b 2>&1)" || { echo "TypeScript errors:" >&2; echo "$out" | head -40 >&2; exit 2; }
    ;;
esac
exit 0
