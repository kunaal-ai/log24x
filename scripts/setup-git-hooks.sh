#!/bin/sh
# Run once per clone: use tracked hooks in .githooks/ (strips Cursor Co-authored-by lines).
cd "$(dirname "$0")/.." || exit 1
git config core.hooksPath .githooks
echo "Set core.hooksPath=.githooks for $(pwd)"
