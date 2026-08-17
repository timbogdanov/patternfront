#!/usr/bin/env bash
# Run every check in the repo. Exit non-zero if any fails.
#
#   ./tools/verify-all.sh [path/to/OpenFrontIO]
#
# Two suites cross-check the docs against OpenFront's real cosmetics.json. That
# data is CC BY-SA 4.0 and is not redistributed here (see NOTICE), so those two
# SKIP when no checkout is present rather than failing — a skip is reported
# loudly so it can never be mistaken for a pass. Everything else is
# self-contained and always runs, including the codec corpus that replaced the
# game-data round-trip.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

OPENFRONT="${1:-$HOME/Desktop/OpenFrontIO}"
fail=0
skipped=()

run() {
    local name="$1"; shift
    printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$name"
    "$@"
    local rc=$?
    if [ "$rc" -eq 0 ]; then
        printf '\033[32m✓ %s\033[0m\n' "$name"
    elif [ "$rc" -eq 2 ]; then
        # Exit 2 means "could not run", not "found a problem".
        printf '\033[33m⊘ %s — SKIPPED\033[0m\n' "$name"
        skipped+=("$name")
    else
        printf '\033[31m✗ %s\033[0m\n' "$name"
        fail=1
    fi
}

run "codec corpus"                 python3 tools/gen-codec-fixtures.py --check
run "editor codec vs corpus"       node    tools/verify-codec.js
run "DSL prototype + seam metric"  python3 tools/dsl_demo.py
run "router prompt examples"       python3 tools/verify-prompt.py
run "map-scale sampling"           python3 tools/preview_prototype.py
run "UI design rules"              python3 tools/verify-ui.py
run "stamp library"                python3 tools/verify-stamps.py
run "editor behaviour"             node    tools/verify-behaviour.js
run "desktop documents"            node    tools/verify-documents.js
run "electron shell"               python3 tools/verify-electron.py

# Optional: only runs with a local OpenFront checkout.
run "docs match OpenFront source"  python3 tools/verify-docs.py "$OPENFRONT"

printf '\n'
if [ "${#skipped[@]}" -gt 0 ]; then
    printf '\033[33mskipped %d: %s\033[0m\n' "${#skipped[@]}" "${skipped[*]}"
    printf '\033[33m  (pass a path to an OpenFrontIO checkout to run them)\033[0m\n'
fi
if [ "$fail" -eq 0 ]; then
    printf '\033[32m\033[1mALL CHECKS PASSED\033[0m\n'
else
    printf '\033[31m\033[1mSOME CHECKS FAILED\033[0m\n'
fi
exit "$fail"
