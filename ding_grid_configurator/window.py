"""Main application window."""

import json
import os
import tempfile
from pathlib import Path

import gi
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, Gio, GLib  # type: ignore

from . import ding_parser as parser
from .ding_restart import restart_extension

HELPER_SCRIPT = str(Path(__file__).parent / 'pkexec_helper.sh')
PRESET_LABELS = ['Tiny', 'Small', 'Standard', 'Large']
PRESET_KEYS   = ['tiny', 'small', 'standard', 'large']
MARGIN_KEYS   = ['top', 'bottom', 'left', 'right']


class DingConfiguratorWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._ding_path = None

        # Preset data
        self._icon_size   = {}
        self._icon_width  = {}
        self._icon_height = {}

        # Margin state — stored separately for linked and unlinked modes so
        # toggling between them always restores the previous values.
        self._margins_unlinked = {k: 0 for k in MARGIN_KEYS}
        self._margins_linked   = 0
        self._link_active      = False

        # Undo / redo
        self._undo_stack:    list[dict] = []
        self._redo_stack:    list[dict] = []
        self._prev_snapshot: dict | None = None
        self._suppress_history = False

        self._busy = False

        self._build_ui()
        self._detect_and_load()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.set_title('DING Grid Configurator')
        self.set_default_size(520, 700)

        header = Adw.HeaderBar()

        # Right side: Apply + hamburger menu
        self._apply_btn = Gtk.Button(label='Apply & Restart')
        self._apply_btn.add_css_class('suggested-action')
        self._apply_btn.connect('clicked', self._on_apply)
        header.pack_end(self._apply_btn)

        menu = Gio.Menu()
        menu.append('Import Settings…', 'win.import')
        menu.append('Export Settings…', 'win.export')
        menu.append('Restore Defaults…', 'win.restore')
        menu_btn = Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu)
        header.pack_end(menu_btn)

        # Left side: undo / redo button pair
        undo_redo_box = Gtk.Box(spacing=0)
        undo_redo_box.add_css_class('linked')

        self._undo_btn = Gtk.Button(icon_name='edit-undo-symbolic', tooltip_text='Undo (Ctrl+Z)')
        self._undo_btn.set_sensitive(False)
        self._undo_btn.connect('clicked', lambda *_: self._undo())
        undo_redo_box.append(self._undo_btn)

        self._redo_btn = Gtk.Button(icon_name='edit-redo-symbolic', tooltip_text='Redo (Ctrl+Shift+Z)')
        self._redo_btn.set_sensitive(False)
        self._redo_btn.connect('clicked', lambda *_: self._redo())
        undo_redo_box.append(self._redo_btn)

        header.pack_start(undo_redo_box)

        # Window actions (for menu items)
        for name, cb in [('import', self._on_import),
                         ('export', self._on_export),
                         ('restore', self._on_restore)]:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', cb)
            self.add_action(action)

        # Keyboard shortcuts
        sc = Gtk.ShortcutController()
        sc.set_scope(Gtk.ShortcutScope.MANAGED)
        self.add_controller(sc)
        sc.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string('<Control>z'),
            Gtk.CallbackAction.new(lambda *_: self._undo() or True),
        ))
        sc.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string('<Control><Shift>z'),
            Gtk.CallbackAction.new(lambda *_: self._redo() or True),
        ))

        # Content
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Adw.PreferencesPage()
        scroll.set_child(page)
        page.add(self._build_preset_group())
        page.add(self._build_margins_group())
        page.add(self._build_info_group())

        # ToastOverlay wraps everything so toasts always work
        self._toast_overlay = Adw.ToastOverlay()
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(scroll)
        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _build_preset_group(self):
        group = Adw.PreferencesGroup(
            title='Icon Size Presets',
            description='Edit the pixel values for each desktop icon size preset.',
        )

        self._preset_combo = Adw.ComboRow(title='Preset')
        model = Gtk.StringList()
        for label in PRESET_LABELS:
            model.append(label)
        self._preset_combo.set_model(model)
        self._preset_combo.set_selected(2)  # standard
        self._preset_combo.connect('notify::selected', self._on_preset_changed)
        group.add(self._preset_combo)

        self._active_row = Adw.ActionRow(
            title='Active Preset (gsettings)',
            subtitle='Loading…',
        )
        group.add(self._active_row)

        self._size_row   = self._make_spin_row('Icon Size',   'Graphic size in pixels',    16, 256)
        self._width_row  = self._make_spin_row('Cell Width',  'Grid cell width in pixels',  48, 512)
        self._height_row = self._make_spin_row('Cell Height', 'Grid cell height in pixels', 48, 512)

        self._size_row.connect('notify::value',   self._on_size_changed)
        self._width_row.connect('notify::value',  self._on_width_changed)
        self._height_row.connect('notify::value', self._on_height_changed)

        group.add(self._size_row)
        group.add(self._width_row)
        group.add(self._height_row)
        return group

    def _build_margins_group(self):
        group = Adw.PreferencesGroup(
            title='Desktop Grid Margins',
            description=(
                "Extra pixel offsets added to DING's desktop margins. "
                'Useful for panels, docks, or reserved areas.'
            ),
        )

        self._link_row = Adw.SwitchRow(
            title='Link Margins',
            subtitle='Synchronise all four margins to the same value',
        )
        self._link_row.connect('notify::active', self._on_link_toggled)

        self._top_row    = self._make_spin_row('Extra Top',    'Additional top margin',    0, 500)
        self._bottom_row = self._make_spin_row('Extra Bottom', 'Additional bottom margin', 0, 500)
        self._left_row   = self._make_spin_row('Extra Left',   'Additional left margin',   0, 500)
        self._right_row  = self._make_spin_row('Extra Right',  'Additional right margin',  0, 500)

        # Map each row to its margin key and the three sibling rows
        _margin_rows = {
            'top':    (self._top_row,    [self._bottom_row, self._left_row, self._right_row]),
            'bottom': (self._bottom_row, [self._top_row,    self._left_row, self._right_row]),
            'left':   (self._left_row,   [self._top_row,    self._bottom_row, self._right_row]),
            'right':  (self._right_row,  [self._top_row,    self._bottom_row, self._left_row]),
        }
        for key, (row, siblings) in _margin_rows.items():
            row.connect(
                'notify::value',
                lambda r, _p, k=key, s=siblings: self._on_margin_changed(r, k, s),
            )

        group.add(self._link_row)
        group.add(self._top_row)
        group.add(self._bottom_row)
        group.add(self._left_row)
        group.add(self._right_row)
        return group

    def _build_info_group(self):
        group = Adw.PreferencesGroup(title='Info')

        self._path_row = Adw.ActionRow(title='DING Extension Path', subtitle='Detecting…')
        self._path_row.set_subtitle_selectable(True)

        self._backup_row = Adw.ActionRow(title='Backup Status', subtitle='Checking…')
        self._res_row    = Adw.ActionRow(title='Screen Resolution', subtitle='Detecting…')

        group.add(self._path_row)
        group.add(self._backup_row)
        group.add(self._res_row)
        return group

    @staticmethod
    def _make_spin_row(title, subtitle, lo, hi):
        row = Adw.SpinRow.new_with_range(lo, hi, 1)
        row.set_title(title)
        row.set_subtitle(subtitle)
        row.set_digits(0)
        row.set_snap_to_ticks(True)
        return row

    # ------------------------------------------------------------------ #
    # Data loading                                                         #
    # ------------------------------------------------------------------ #

    def _detect_and_load(self):
        if not parser.ding_installed(self._ding_path):
            self._show_error(
                'DING Extension Not Found',
                f'Could not find the DING extension at:\n{parser.DING_PATH}\n\n'
                'Please install the DING extension first.',
            )
            self._apply_btn.set_sensitive(False)
            return
        self._load_values()

    def _load_values(self):
        try:
            self._icon_size, self._icon_width, self._icon_height = \
                parser.read_enums(self._ding_path)
            file_margins = parser.read_margins(self._ding_path)
        except Exception as e:
            self._show_error('Read Error', str(e))
            return

        self._margins_unlinked = dict(file_margins)
        # Seed linked value from the top margin so first link-on feels natural
        self._margins_linked = file_margins['top']
        self._link_active = False

        self._suppress_history = True
        self._link_row.set_active(False)
        self._refresh_preset_spins()
        self._refresh_margin_spins()
        self._suppress_history = False

        active = parser.get_active_preset()
        self._active_row.set_subtitle(active.capitalize())
        base = self._ding_path or str(parser.DING_PATH)
        self._path_row.set_subtitle(base)
        self._backup_row.set_subtitle(
            'Backup exists ✓' if parser.backup_exists(self._ding_path) else 'No backup yet'
        )
        self._res_row.set_subtitle(parser.get_screen_resolution())

        self._init_history()

    def _refresh_preset_spins(self):
        key = PRESET_KEYS[self._preset_combo.get_selected()]
        self._size_row.set_value(self._icon_size.get(key, 64))
        self._width_row.set_value(self._icon_width.get(key, 120))
        self._height_row.set_value(self._icon_height.get(key, 106))

    def _refresh_margin_spins(self):
        """Push current margin state into the UI rows without recording history."""
        prev = self._suppress_history
        self._suppress_history = True
        if self._link_active:
            v = self._margins_linked
            for row in (self._top_row, self._bottom_row, self._left_row, self._right_row):
                row.set_value(v)
        else:
            self._top_row.set_value(self._margins_unlinked['top'])
            self._bottom_row.set_value(self._margins_unlinked['bottom'])
            self._left_row.set_value(self._margins_unlinked['left'])
            self._right_row.set_value(self._margins_unlinked['right'])
        self._suppress_history = prev

    # ------------------------------------------------------------------ #
    # Undo / redo                                                          #
    # ------------------------------------------------------------------ #

    def _snapshot(self) -> dict:
        return {
            'icon_size':        dict(self._icon_size),
            'icon_width':       dict(self._icon_width),
            'icon_height':      dict(self._icon_height),
            'margins_unlinked': dict(self._margins_unlinked),
            'margins_linked':   self._margins_linked,
            'link_active':      self._link_active,
        }

    def _init_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._prev_snapshot = self._snapshot()
        self._update_history_buttons()

    def _push_history(self):
        """Save the state from before the most recent change onto the undo stack."""
        if self._suppress_history:
            return
        if self._prev_snapshot is not None:
            self._undo_stack.append(self._prev_snapshot)
        self._prev_snapshot = self._snapshot()   # current (post-change) state
        self._redo_stack.clear()
        self._update_history_buttons()

    def _apply_snapshot(self, snap: dict):
        """Restore all state from a snapshot; caller must set _suppress_history."""
        self._icon_size          = dict(snap['icon_size'])
        self._icon_width         = dict(snap['icon_width'])
        self._icon_height        = dict(snap['icon_height'])
        self._margins_unlinked   = dict(snap['margins_unlinked'])
        self._margins_linked     = snap['margins_linked']
        self._link_active        = snap['link_active']
        # _on_link_toggled returns early while suppressed, so we handle UI here
        self._link_row.set_active(self._link_active)
        self._refresh_preset_spins()
        self._refresh_margin_spins()

    def _undo(self):
        if not self._undo_stack or self._busy:
            return
        self._redo_stack.append(self._snapshot())
        state = self._undo_stack.pop()
        self._suppress_history = True
        self._apply_snapshot(state)
        self._suppress_history = False
        self._prev_snapshot = self._snapshot()
        self._update_history_buttons()

    def _redo(self):
        if not self._redo_stack or self._busy:
            return
        self._undo_stack.append(self._snapshot())
        state = self._redo_stack.pop()
        self._suppress_history = True
        self._apply_snapshot(state)
        self._suppress_history = False
        self._prev_snapshot = self._snapshot()
        self._update_history_buttons()

    def _update_history_buttons(self):
        self._undo_btn.set_sensitive(bool(self._undo_stack) and not self._busy)
        self._redo_btn.set_sensitive(bool(self._redo_stack) and not self._busy)

    # ------------------------------------------------------------------ #
    # Signal handlers — presets                                            #
    # ------------------------------------------------------------------ #

    def _on_preset_changed(self, _combo, _pspec):
        # Switching the preset selector just updates the displayed spin values;
        # each preset's data is already kept live by the spin handlers below.
        if self._suppress_history:
            return
        self._suppress_history = True
        self._refresh_preset_spins()
        self._suppress_history = False

    def _on_size_changed(self, row, _pspec):
        if self._suppress_history:
            return
        self._icon_size[PRESET_KEYS[self._preset_combo.get_selected()]] = int(row.get_value())
        self._push_history()

    def _on_width_changed(self, row, _pspec):
        if self._suppress_history:
            return
        self._icon_width[PRESET_KEYS[self._preset_combo.get_selected()]] = int(row.get_value())
        self._push_history()

    def _on_height_changed(self, row, _pspec):
        if self._suppress_history:
            return
        self._icon_height[PRESET_KEYS[self._preset_combo.get_selected()]] = int(row.get_value())
        self._push_history()

    # ------------------------------------------------------------------ #
    # Signal handlers — margins                                            #
    # ------------------------------------------------------------------ #

    def _on_margin_changed(self, row, key: str, siblings: list):
        if self._suppress_history:
            return
        val = int(row.get_value())
        if self._link_active:
            self._margins_linked = val
            # Sync sibling rows without triggering more history pushes
            self._suppress_history = True
            for r in siblings:
                r.set_value(val)
            self._suppress_history = False
        else:
            self._margins_unlinked[key] = val
        self._push_history()

    def _on_link_toggled(self, switch, _pspec):
        if self._suppress_history:
            return
        self._link_active = switch.get_active()
        # Both margin dicts are preserved as-is; just refresh the UI to show
        # whichever set of values belongs to the newly active mode.
        self._refresh_margin_spins()
        self._push_history()

    # ------------------------------------------------------------------ #
    # Apply / Restore / Import / Export                                    #
    # ------------------------------------------------------------------ #

    def _effective_margins(self) -> dict:
        if self._link_active:
            v = self._margins_linked
            return {k: v for k in MARGIN_KEYS}
        return dict(self._margins_unlinked)

    def _on_apply(self, _btn):
        if self._busy:
            return
        self._set_busy(True)
        try:
            enums_content = parser.build_enums_content(
                self._icon_size, self._icon_width, self._icon_height, self._ding_path,
            )
            grid_content = parser.build_grid_content(self._effective_margins(), self._ding_path)
        except Exception as e:
            self._set_busy(False)
            self._show_error('Build Error', str(e))
            return
        self._run_privileged_write(enums_content, grid_content)

    def _on_restore(self, _action=None, _param=None):
        if self._busy:
            return
        if not parser.backup_exists(self._ding_path):
            self._show_error('No Backup', 'No backup files found. Nothing to restore.')
            return
        dialog = Adw.AlertDialog(
            heading='Restore Default Files?',
            body='This will overwrite the current DING files with the backed-up originals and restart the extension.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('restore', 'Restore')
        dialog.set_response_appearance('restore', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect('response', self._on_restore_confirmed)
        dialog.present(self)

    def _on_restore_confirmed(self, _dialog, response):
        if response != 'restore':
            return
        self._set_busy(True)
        self._pkexec_run(['restore'], self._after_restore)

    def _after_restore(self, success, error):
        if not success:
            self._set_busy(False)
            self._show_error('Restore Failed', error or 'Unknown error')
            return
        restart_extension(self._after_restart)

    # -- Export --

    def _on_export(self, _action=None, _param=None):
        dialog = Gtk.FileDialog()
        dialog.set_title('Export Settings')
        dialog.set_initial_name('ding-grid-settings.json')
        dialog.save(self, None, self._on_export_done)

    def _on_export_done(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # user cancelled
        data = {
            'icon_size':        self._icon_size,
            'icon_width':       self._icon_width,
            'icon_height':      self._icon_height,
            'margins_unlinked': self._margins_unlinked,
            'margins_linked':   self._margins_linked,
            'link_active':      self._link_active,
        }
        try:
            with open(gfile.get_path(), 'w') as f:
                json.dump(data, f, indent=2)
            self._show_toast('Settings exported.')
        except Exception as e:
            self._show_error('Export Failed', str(e))

    # -- Import --

    def _on_import(self, _action=None, _param=None):
        filter_ = Gtk.FileFilter()
        filter_.set_name('JSON files (*.json)')
        filter_.add_pattern('*.json')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_)

        dialog = Gtk.FileDialog()
        dialog.set_title('Import Settings')
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_import_done)

    def _on_import_done(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # user cancelled
        try:
            with open(gfile.get_path()) as f:
                data = json.load(f)
            snap = {
                'icon_size':        {k: int(data['icon_size'][k])        for k in PRESET_KEYS},
                'icon_width':       {k: int(data['icon_width'][k])       for k in PRESET_KEYS},
                'icon_height':      {k: int(data['icon_height'][k])      for k in PRESET_KEYS},
                'margins_unlinked': {k: int(data['margins_unlinked'][k]) for k in MARGIN_KEYS},
                'margins_linked':   int(data.get('margins_linked', 0)),
                'link_active':      bool(data.get('link_active', False)),
            }
        except Exception as e:
            self._show_error('Import Failed', f'Could not read settings file:\n{e}')
            return

        # Push current state so the import can be undone
        if self._prev_snapshot is not None:
            self._undo_stack.append(self._prev_snapshot)
        self._redo_stack.clear()

        self._suppress_history = True
        self._apply_snapshot(snap)
        self._suppress_history = False
        self._prev_snapshot = self._snapshot()
        self._update_history_buttons()
        self._show_toast('Settings imported.')

    # ------------------------------------------------------------------ #
    # Privileged file writing                                              #
    # ------------------------------------------------------------------ #

    def _run_privileged_write(self, enums_content, grid_content):
        try:
            self._enums_tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.js', delete=False, prefix='ding_enums_'
            )
            self._enums_tmp.write(enums_content)
            self._enums_tmp.flush()
            self._enums_tmp.close()

            self._grid_tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.js', delete=False, prefix='ding_grid_'
            )
            self._grid_tmp.write(grid_content)
            self._grid_tmp.flush()
            self._grid_tmp.close()
        except Exception as e:
            self._set_busy(False)
            self._show_error('Temp File Error', str(e))
            return

        # Single pkexec call: backup (if needed) + write both files = one password prompt
        self._pkexec_run(
            ['apply', self._enums_tmp.name, self._grid_tmp.name],
            self._after_apply,
        )

    def _after_apply(self, success, error):
        self._cleanup_tmp()
        if not success:
            self._set_busy(False)
            self._show_error('Write Failed', error or 'Could not write DING files.')
            return
        restart_extension(self._after_restart)

    def _after_restart(self, success, error):
        self._set_busy(False)
        if success:
            self._backup_row.set_subtitle('Backup exists ✓')
            self._show_toast('Changes applied and DING restarted.')
        else:
            self._show_error(
                'Restart Failed',
                (error or 'Unknown error') +
                '\n\nThe files were written; you may need to restart the extension manually.',
            )

    def _cleanup_tmp(self):
        for attr in ('_enums_tmp', '_grid_tmp'):
            tmp = getattr(self, attr, None)
            if tmp:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                setattr(self, attr, None)

    def _pkexec_run(self, args, callback):
        try:
            proc = Gio.Subprocess.new(
                ['pkexec', HELPER_SCRIPT] + args,
                Gio.SubprocessFlags.STDERR_PIPE,
            )
        except Exception as e:
            GLib.idle_add(lambda: callback(False, str(e)))
            return

        def _done(proc, result):
            try:
                _ok, _out, stderr_bytes = proc.communicate_finish(result)
                stderr = stderr_bytes.get_data().decode(errors='replace') if stderr_bytes else ''
                success = proc.get_exit_status() == 0
                callback(success, None if success else stderr.strip())
            except Exception as e:
                callback(False, str(e))

        proc.communicate_async(None, None, _done)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _set_busy(self, busy):
        self._busy = busy
        self._apply_btn.set_sensitive(not busy)
        self._update_history_buttons()

    def _show_toast(self, message):
        self._toast_overlay.add_toast(Adw.Toast.new(message))

    def _show_error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response('ok', 'OK')
        dialog.present(self)
