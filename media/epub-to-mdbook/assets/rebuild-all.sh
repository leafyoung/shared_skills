#!/bin/bash
# Rebuild every converted book under the given roots and print one line per book:
# build exit code, WARN count, ERROR count, and the link-check result.
#
# Usage: rebuild-all.sh <root> [<root> ...]
#
# A book is any folder holding mdbook/book.toml. Run it yourself after a review round:
# a subagent's "clean build" report is a claim, and one such report was wrong (a SUMMARY
# with in-page "#anchor" entries makes mdbook 0.5.4 fail with "failed to read chapter").
# Nothing is regenerated or deleted; mdbook only rewrites each book's own book/ output.

LINKS=~/.claude/skills/mdbook-authoring/assets/scripts/check_links.py
LOG="$(mktemp)"
trap 'rm -f -- "$LOG"' EXIT

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <root> [<root> ...]" >&2
  exit 2
fi

find "$@" -maxdepth 8 -type f -path '*/mdbook/book.toml' | sort | while IFS= read -r toml; do
  dir="$(dirname "$toml")"
  (
    cd "$dir" || exit 1
    mdbook build > "$LOG" 2>&1
    rc=$?
    echo "rc=$rc warn=$(grep -c WARN "$LOG") err=$(grep -c ERROR "$LOG") links=$(python3 "$LINKS" book 2>&1 | tail -1 | cut -c1-60)  $dir"
  )
done
