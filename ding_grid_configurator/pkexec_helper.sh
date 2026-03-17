#!/bin/bash
# pkexec_helper.sh — Privileged file operations for DING Grid Configurator
# Invoked via: pkexec /path/to/pkexec_helper.sh <command> [args]
#
# Commands:
#   apply <enums_src> <grid_src> — backup (if needed) then write both files in one shot
#   restore                      — restore both files from .bak backups

set -euo pipefail

DING_PATH="/usr/share/gnome-shell/extensions/ding@rastersoft.com"
ENUMS="$DING_PATH/app/enums.js"
GRID="$DING_PATH/app/desktopGrid.js"

cmd="${1:-}"
shift || true

case "$cmd" in
    apply)
        enums_src="${1:?apply requires <enums_src> <grid_src>}"
        grid_src="${2:?apply requires <enums_src> <grid_src>}"
        # Backup once before touching anything
        [[ -f "$ENUMS.bak" ]] || cp -- "$ENUMS" "$ENUMS.bak"
        [[ -f "$GRID.bak"  ]] || cp -- "$GRID"  "$GRID.bak"
        # Write both files
        cp -- "$enums_src" "$ENUMS" && chmod 644 "$ENUMS"
        cp -- "$grid_src"  "$GRID"  && chmod 644 "$GRID"
        ;;
    restore)
        [[ -f "$ENUMS.bak" ]] && cp -- "$ENUMS.bak" "$ENUMS" && chmod 644 "$ENUMS"
        [[ -f "$GRID.bak"  ]] && cp -- "$GRID.bak"  "$GRID"  && chmod 644 "$GRID"
        ;;
    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: pkexec_helper.sh {apply <enums_src> <grid_src>|restore}" >&2
        exit 1
        ;;
esac
