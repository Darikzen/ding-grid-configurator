"""Parse and modify DING extension source files."""

import re
import subprocess
from pathlib import Path

DING_PATH = Path('/usr/share/gnome-shell/extensions/ding@rastersoft.com')
ENUMS_FILE = DING_PATH / 'app' / 'enums.js'
GRID_FILE = DING_PATH / 'app' / 'desktopGrid.js'

DEFAULT_ICON_SIZE = {'tiny': 36, 'small': 48, 'standard': 64, 'large': 96}
DEFAULT_ICON_WIDTH = {'tiny': 70, 'small': 90, 'standard': 120, 'large': 130}
DEFAULT_ICON_HEIGHT = {'tiny': 80, 'small': 90, 'standard': 106, 'large': 138}
DEFAULT_MARGINS = {'top': 0, 'bottom': 0, 'left': 0, 'right': 0}

PRESETS = ['tiny', 'small', 'standard', 'large']


def ding_installed(path=None):
    base = Path(path) if path else DING_PATH
    return base.exists() and (base / 'app' / 'enums.js').exists()


def backup_exists(path=None):
    base = Path(path) if path else DING_PATH
    return (base / 'app' / 'enums.js.bak').exists()


def _parse_js_object(line):
    result = {}
    for key, val in re.findall(r"'(\w+)':\s*(\d+)", line):
        result[key] = int(val)
    return result


def read_enums(path=None):
    f = (Path(path) / 'app' / 'enums.js') if path else ENUMS_FILE
    content = f.read_text()
    icon_size, icon_width, icon_height = {}, {}, {}
    for line in content.splitlines():
        if re.search(r'\bICON_SIZE\b', line):
            icon_size = _parse_js_object(line)
        elif re.search(r'\bICON_WIDTH\b', line):
            icon_width = _parse_js_object(line)
        elif re.search(r'\bICON_HEIGHT\b', line):
            icon_height = _parse_js_object(line)
    # Fill in any missing keys with defaults
    for preset in PRESETS:
        icon_size.setdefault(preset, DEFAULT_ICON_SIZE[preset])
        icon_width.setdefault(preset, DEFAULT_ICON_WIDTH[preset])
        icon_height.setdefault(preset, DEFAULT_ICON_HEIGHT[preset])
    return icon_size, icon_width, icon_height


def read_margins(path=None):
    f = (Path(path) / 'app' / 'desktopGrid.js') if path else GRID_FILE
    content = f.read_text()
    margins = dict(DEFAULT_MARGINS)
    for key in margins:
        m = re.search(rf'const\s+extra{key.capitalize()}\s*=\s*(\d+)\s*;', content)
        if m:
            margins[key] = int(m.group(1))
    return margins


def _format_js_object(name, values):
    items = ', '.join(f"'{k}': {values[k]}" for k in PRESETS if k in values)
    return f"var {name} = {{{items}}};"


def build_enums_content(icon_size, icon_width, icon_height, path=None):
    f = (Path(path) / 'app' / 'enums.js') if path else ENUMS_FILE
    content = f.read_text()
    content = re.sub(
        r'var\s+ICON_SIZE\s*=\s*\{[^}]*\};',
        _format_js_object('ICON_SIZE', icon_size),
        content,
    )
    content = re.sub(
        r'var\s+ICON_WIDTH\s*=\s*\{[^}]*\};',
        _format_js_object('ICON_WIDTH', icon_width),
        content,
    )
    content = re.sub(
        r'var\s+ICON_HEIGHT\s*=\s*\{[^}]*\};',
        _format_js_object('ICON_HEIGHT', icon_height),
        content,
    )
    return content


def build_grid_content(margins, path=None):
    f = (Path(path) / 'app' / 'desktopGrid.js') if path else GRID_FILE
    content = f.read_text()
    all_zero = all(v == 0 for v in margins.values())

    # Pattern matches the method opening brace, then optional extra* consts,
    # then the four margin assignments (with or without + extra*)
    pattern = re.compile(
        r'(updateUnscaledHeightWidthMargins\(\)\s*\{)'
        r'(?:\s*(?:const\s+extra(?:Top|Bottom|Left|Right)\s*=\s*\d+;\s*)*)'
        r'\s*this\._marginTop\s*=\s*this\._desktopDescription\.marginTop(?:\s*\+\s*extraTop)?\s*;'
        r'\s*this\._marginBottom\s*=\s*this\._desktopDescription\.marginBottom(?:\s*\+\s*extraBottom)?\s*;'
        r'\s*this\._marginLeft\s*=\s*this\._desktopDescription\.marginLeft(?:\s*\+\s*extraLeft)?\s*;'
        r'\s*this\._marginRight\s*=\s*this\._desktopDescription\.marginRight(?:\s*\+\s*extraRight)?\s*;',
        re.DOTALL,
    )

    if all_zero:
        replacement = (
            r'\1'
            '\n        this._marginTop = this._desktopDescription.marginTop;'
            '\n        this._marginBottom = this._desktopDescription.marginBottom;'
            '\n        this._marginLeft = this._desktopDescription.marginLeft;'
            '\n        this._marginRight = this._desktopDescription.marginRight;'
        )
    else:
        t, b, l, r = margins['top'], margins['bottom'], margins['left'], margins['right']
        replacement = (
            r'\1'
            f'\n        const extraTop = {t};'
            f'\n        const extraBottom = {b};'
            f'\n        const extraLeft = {l};'
            f'\n        const extraRight = {r};'
            '\n        this._marginTop = this._desktopDescription.marginTop + extraTop;'
            '\n        this._marginBottom = this._desktopDescription.marginBottom + extraBottom;'
            '\n        this._marginLeft = this._desktopDescription.marginLeft + extraLeft;'
            '\n        this._marginRight = this._desktopDescription.marginRight + extraRight;'
        )

    if not pattern.search(content):
        raise RuntimeError('Could not find updateUnscaledHeightWidthMargins() method to patch.')
    return pattern.sub(replacement, content)


def get_active_preset():
    try:
        result = subprocess.run(
            ['gsettings', 'get', 'org.gnome.shell.extensions.ding', 'icon-size'],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip().strip("'\"")
    except Exception:
        return 'standard'


def get_screen_resolution():
    try:
        result = subprocess.run(
            ['xdpyinfo'],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r'dimensions:\s*(\d+x\d+)\s+pixels', result.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        result = subprocess.run(
            ['xrandr', '--query'],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r'current\s+(\d+)\s+x\s+(\d+)', result.stdout)
        if m:
            return f"{m.group(1)}x{m.group(2)}"
    except Exception:
        pass
    return 'Unknown'
