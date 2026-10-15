#!/usr/bin/env bash
# Symlink each VLSIDA skill into ~/.claude/skills/.
#
# Per skill:
#   target is already a symlink  -> silent (idempotent re-runs)
#   target is a dir/file         -> warn and skip (never overwrite)
#   target does not exist        -> create symlink
#
# A "skill" is any top-level directory in this repo that contains SKILL.md.

set -eu

REPO="$(cd "$(dirname "$0")" && pwd)"
TARGET="${HOME}/.claude/skills"

mkdir -p "$TARGET"

for dir in "$REPO"/*/; do
    skill="$(basename "$dir")"
    [ -f "$dir/SKILL.md" ] || continue

    link="$TARGET/$skill"

    if [ -L "$link" ]; then
        continue
    fi

    if [ -e "$link" ]; then
        echo "WARN: $link already exists and is not a symlink -- skipping" >&2
        continue
    fi

    ln -s "$REPO/$skill" "$link"
    echo "linked $skill"
done
