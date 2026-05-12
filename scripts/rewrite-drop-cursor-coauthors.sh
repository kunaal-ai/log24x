#!/bin/sh
# Optional: rewrite ALL commit messages to drop Co-authored-by lines that mention "cursor".
# This rewrites SHAs — you must force-push and anyone else must re-clone or hard-reset.
set -eu
cd "$(dirname "$0")/.." || exit 1
echo "This will run git filter-branch and rewrite commit hashes."
echo "Press Ctrl+C to cancel, or Enter to continue."
read -r _
git filter-branch -f --msg-filter \
  'perl -ne "print unless /^\\s*co-authored-by:/i && /cursor/i"' \
  -- --all
echo "Done. Next: git push --force-with-lease origin main   (adjust branch if needed)"
