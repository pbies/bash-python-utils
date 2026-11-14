#!/usr/bin/env bash
#
# sha256sums.sh - traverse 3 given folders and write sha256 sums of every
#                 file inside them into a single output file.
#
# Usage:
#   ./sha256sums.sh <folder1> <folder2> <folder3> [output_file]
#
# If output_file is omitted, sums are written to ./sha256sums.txt

# Note: no 'set -e' here on purpose - we want to skip over any file that
# can't be read (permissions, vanished files, etc.) and keep going.
set -uo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: $0 <folder1> <folder2> <folder3> [output_file]" >&2
    exit 1
fi

dir1="$1"
dir2="$2"
dir3="$3"
out="${4:-sha256sums.txt}"

# Validate the three folders up front.
for d in "$dir1" "$dir2" "$dir3"; do
    if [ ! -d "$d" ]; then
        echo "Error: '$d' is not a directory" >&2
        exit 1
    fi
done

# Pick whichever sha256 tool is available.
if command -v sha256sum >/dev/null 2>&1; then
    hash_cmd="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    hash_cmd="shasum -a 256"
else
    echo "Error: neither sha256sum nor shasum found" >&2
    exit 1
fi

# Start with a fresh output file.
: > "$out"

count=0
errors=0
# -print0 / read -d '' handles spaces, newlines and other odd characters in names.
# find's own errors (e.g. unreadable dirs) are sent to /dev/null.
while IFS= read -r -d '' file; do
    if $hash_cmd "$file" >> "$out" 2>/dev/null; then
        count=$((count + 1))
    else
        # Unreadable / vanished file - report and keep going.
        echo "Skipped (could not hash): $file" >&2
        errors=$((errors + 1))
    fi
done < <(find "$dir1" "$dir2" "$dir3" -type f -print0 2>/dev/null)

echo "Wrote $count checksums to '$out' ($errors skipped)"
