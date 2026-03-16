#!/bin/bash
# pkexec_helper.sh — Privileged file operations for DING Grid Configurator
# Invoked via: pkexec /path/to/pkexec_helper.sh <command> [args]
#
# Commands:
#   backup                 — create .bak copies if they don't exist
#   write-enums   <src>    — install <src> as enums.js
#   write-grid    <src>    — install <src> as desktopGrid.js
#   restore                — restore both files from .bak backups

set -euo pipefail

DING_PATH="/usr/share/gnome-shell/extensions/ding@rastersoft.com"
ENUMS="$DING_PATH/app/enums.js"
GRID="$DING_PATH/app/desktopGrid.js"

cmd="${1:-}"
shift || true

case "$cmd" in
    backup)
        [[ -f "$ENUMS.bak" ]] || cp -- "$ENUMS" "$ENUMS.bak"
        [[ -f "$GRID.bak"  ]] || cp -- "$GRID"  "$GRID.bak"
        ;;
    write-enums)
        src="${1:?write-enums requires a source file argument}"
        cp -- "$src" "$ENUMS"
        chmod 644 "$ENUMS"
        ;;
    write-grid)
        src="${1:?write-grid requires a source file argument}"
        cp -- "$src" "$GRID"
        chmod 644 "$GRID"
        ;;
    restore)
        [[ -f "$ENUMS.bak" ]] && cp -- "$ENUMS.bak" "$ENUMS" && chmod 644 "$ENUMS"
        [[ -f "$GRID.bak"  ]] && cp -- "$GRID.bak"  "$GRID"  && chmod 644 "$GRID"
        ;;
    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: pkexec_helper.sh {backup|write-enums <src>|write-grid <src>|restore}" >&2
        exit 1
        ;;
esac
