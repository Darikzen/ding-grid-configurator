"""Main application window."""

import os
import tempfile
from pathlib import Path

import gi
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, Gio, GLib

from . import ding_parser as parser
from .ding_restart import restart_extension

HELPER_SCRIPT = str(Path(__file__).parent / 'pkexec_helper.sh')
PRESET_LABELS = ['Tiny', 'Small', 'Standard', 'Large']
PRESET_KEYS   = ['tiny', 'small', 'standard', 'large']


class DingConfiguratorWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._ding_path = None          # None → use default
        self._icon_size = {}
        self._icon_width = {}
        self._icon_height = {}
        self._margins = {}
        self._active_preset_idx = 2     # 'standard'
        self._link_margins = False
        self._busy = False

        self._build_ui()
        self._detect_and_load()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.set_title('DING Grid Configurator')
        self.set_default_size(520, 680)

        # Header bar
        header = Adw.HeaderBar()

        self._apply_btn = Gtk.Button(label='Apply & Restart')
        self._apply_btn.add_css_class('suggested-action')
        self._apply_btn.connect('clicked', self._on_apply)
        header.pack_end(self._apply_btn)

        self._restore_btn = Gtk.Button(label='Restore Defaults')
        self._restore_btn.add_css_class('destructive-action')
        self._restore_btn.connect('clicked', self._on_restore)
        header.pack_start(self._restore_btn)

        # Scroll + preferences page
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Adw.PreferencesPage()
        scroll.set_child(page)

        page.add(self._build_preset_group())
        page.add(self._build_margins_group())
        page.add(self._build_info_group())

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(scroll)
        self.set_content(toolbar_view)

    def _build_preset_group(self):
        group = Adw.PreferencesGroup(title='Icon Size Presets')
        group.set_description(
            'Edit the pixel values for each desktop icon size preset.'
        )

        # Preset selector
        self._preset_combo = Adw.ComboRow(title='Preset')
        model = Gtk.StringList()
        for label in PRESET_LABELS:
            model.append(label)
        self._preset_combo.set_model(model)
        self._preset_combo.set_selected(self._active_preset_idx)
        self._preset_combo.connect('notify::selected', self._on_preset_changed)
        group.add(self._preset_combo)

        # Active preset indicator row
        self._active_row = Adw.ActionRow(
            title='Active Preset (gsettings)',
            subtitle='Loading…',
        )
        group.add(self._active_row)

        # Spin rows
        self._size_row   = self._make_spin_row('Icon Size',  'Graphic size in pixels',  16, 256)
        self._width_row  = self._make_spin_row('Cell Width', 'Grid cell width in pixels', 48, 512)
        self._height_row = self._make_spin_row('Cell Height','Grid cell height in pixels',48, 512)

        self._size_row.connect('notify::value',   self._on_size_changed)
        self._width_row.connect('notify::value',  self._on_width_changed)
        self._height_row.connect('notify::value', self._on_height_changed)

        group.add(self._size_row)
        group.add(self._width_row)
        group.add(self._height_row)
        return group

    def _build_margins_group(self):
        group = Adw.PreferencesGroup(title='Desktop Grid Margins')
        group.set_description(
            'Extra pixel offsets added to DING\'s desktop margins. '
            'Useful for panels, docks, or reserved areas.'
        )

        self._top_row    = self._make_spin_row('Extra Top',    'Additional top margin',    0, 500)
        self._bottom_row = self._make_spin_row('Extra Bottom', 'Additional bottom margin', 0, 500)
        self._left_row   = self._make_spin_row('Extra Left',   'Additional left margin',   0, 500)
        self._right_row  = self._make_spin_row('Extra Right',  'Additional right margin',  0, 500)

        for row, cb in [
            (self._top_row,    self._on_margin_top_changed),
            (self._bottom_row, self._on_margin_bottom_changed),
            (self._left_row,   self._on_margin_left_changed),
            (self._right_row,  self._on_margin_right_changed),
        ]:
            row.connect('notify::value', cb)

        # Link toggle
        self._link_row = Adw.SwitchRow(
            title='Link Margins',
            subtitle='Synchronise all four margins to the same value',
        )
        self._link_row.connect('notify::active', self._on_link_toggled)

        group.add(self._link_row)
        group.add(self._top_row)
        group.add(self._bottom_row)
        group.add(self._left_row)
        group.add(self._right_row)
        return group

    def _build_info_group(self):
        group = Adw.PreferencesGroup(title='Info')

        self._path_row = Adw.ActionRow(
            title='DING Extension Path',
            subtitle='Detecting…',
        )
        self._path_row.set_subtitle_selectable(True)

        self._backup_row = Adw.ActionRow(
            title='Backup Status',
            subtitle='Checking…',
        )

        self._res_row = Adw.ActionRow(
            title='Screen Resolution',
            subtitle='Detecting…',
        )

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
            self._restore_btn.set_sensitive(False)
            return
        self._load_values()

    def _load_values(self):
        try:
            self._icon_size, self._icon_width, self._icon_height = \
                parser.read_enums(self._ding_path)
            self._margins = parser.read_margins(self._ding_path)
        except Exception as e:
            self._show_error('Read Error', str(e))
            return

        self._refresh_preset_spins()
        self._refresh_margin_spins()

        active = parser.get_active_preset()
        self._active_row.set_subtitle(active.capitalize())
        try:
            idx = PRESET_KEYS.index(active)
            self._active_preset_idx = idx
        except ValueError:
            pass

        # Info rows
        base = self._ding_path or str(parser.DING_PATH)
        self._path_row.set_subtitle(base)
        has_bak = parser.backup_exists(self._ding_path)
        self._backup_row.set_subtitle('Backup exists ✓' if has_bak else 'No backup yet')
        self._res_row.set_subtitle(parser.get_screen_resolution())

    def _refresh_preset_spins(self):
        key = PRESET_KEYS[self._preset_combo.get_selected()]
        self._size_row.set_value(self._icon_size.get(key, 64))
        self._width_row.set_value(self._icon_width.get(key, 120))
        self._height_row.set_value(self._icon_height.get(key, 106))

    def _refresh_margin_spins(self):
        self._top_row.set_value(self._margins.get('top', 0))
        self._bottom_row.set_value(self._margins.get('bottom', 0))
        self._left_row.set_value(self._margins.get('left', 0))
        self._right_row.set_value(self._margins.get('right', 0))

    # ------------------------------------------------------------------ #
    # Signal handlers                                                      #
    # ------------------------------------------------------------------ #

    def _on_preset_changed(self, combo, _pspec):
        key = PRESET_KEYS[combo.get_selected()]
        # Save currently displayed values back before switching
        self._save_current_spin_values()
        self._refresh_preset_spins()

    def _save_current_spin_values(self):
        # Called before a preset switch — saves previous preset's values
        pass  # Values are updated incrementally via _on_size/width/height_changed

    def _on_size_changed(self, row, _pspec):
        key = PRESET_KEYS[self._preset_combo.get_selected()]
        self._icon_size[key] = int(row.get_value())

    def _on_width_changed(self, row, _pspec):
        key = PRESET_KEYS[self._preset_combo.get_selected()]
        self._icon_width[key] = int(row.get_value())

    def _on_height_changed(self, row, _pspec):
        key = PRESET_KEYS[self._preset_combo.get_selected()]
        self._icon_height[key] = int(row.get_value())

    def _on_margin_top_changed(self, row, _pspec):
        self._margins['top'] = int(row.get_value())
        if self._link_margins:
            self._set_all_margins(int(row.get_value()))

    def _on_margin_bottom_changed(self, row, _pspec):
        self._margins['bottom'] = int(row.get_value())
        if self._link_margins:
            self._set_all_margins(int(row.get_value()))

    def _on_margin_left_changed(self, row, _pspec):
        self._margins['left'] = int(row.get_value())
        if self._link_margins:
            self._set_all_margins(int(row.get_value()))

    def _on_margin_right_changed(self, row, _pspec):
        self._margins['right'] = int(row.get_value())
        if self._link_margins:
            self._set_all_margins(int(row.get_value()))

    def _on_link_toggled(self, switch, _pspec):
        self._link_margins = switch.get_active()
        if self._link_margins:
            self._set_all_margins(int(self._top_row.get_value()))

    def _set_all_margins(self, value):
        for key, row in [
            ('top', self._top_row),
            ('bottom', self._bottom_row),
            ('left', self._left_row),
            ('right', self._right_row),
        ]:
            self._margins[key] = value
            row.set_value(value)

    # ------------------------------------------------------------------ #
    # Apply / Restore                                                      #
    # ------------------------------------------------------------------ #

    def _on_apply(self, _btn):
        if self._busy:
            return
        self._set_busy(True)
        try:
            enums_content = parser.build_enums_content(
                self._icon_size, self._icon_width, self._icon_height,
                self._ding_path,
            )
            grid_content = parser.build_grid_content(self._margins, self._ding_path)
        except Exception as e:
            self._set_busy(False)
            self._show_error('Build Error', str(e))
            return

        self._run_privileged_write(enums_content, grid_content)

    def _on_restore(self, _btn):
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

    def _on_restore_confirmed(self, dialog, response):
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

    # ------------------------------------------------------------------ #
    # Privileged file writing                                              #
    # ------------------------------------------------------------------ #

    def _run_privileged_write(self, enums_content, grid_content):
        # Write temp files (no root needed)
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

        # Step 1: backup
        self._pkexec_run(['backup'], self._after_backup)

    def _after_backup(self, success, error):
        if not success:
            self._cleanup_tmp()
            self._set_busy(False)
            self._show_error('Backup Failed', error or 'Could not create backup files.')
            return
        # Step 2: write enums
        self._pkexec_run(['write-enums', self._enums_tmp.name], self._after_write_enums)

    def _after_write_enums(self, success, error):
        if not success:
            self._cleanup_tmp()
            self._set_busy(False)
            self._show_error('Write Failed', error or 'Could not write enums.js.')
            return
        # Step 3: write grid
        self._pkexec_run(['write-grid', self._grid_tmp.name], self._after_write_grid)

    def _after_write_grid(self, success, error):
        self._cleanup_tmp()
        if not success:
            self._set_busy(False)
            self._show_error('Write Failed', error or 'Could not write desktopGrid.js.')
            return
        # Step 4: restart extension
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
                ok, _out, stderr_bytes = proc.communicate_finish(result)
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
        self._restore_btn.set_sensitive(not busy)

    def _show_toast(self, message):
        overlay = self.get_content()
        if isinstance(overlay, Adw.ToastOverlay):
            overlay.add_toast(Adw.Toast.new(message))
        else:
            # Wrap content in ToastOverlay on first use
            content = self.get_content()
            toast_overlay = Adw.ToastOverlay()
            self.set_content(toast_overlay)
            toast_overlay.set_child(content)
            toast_overlay.add_toast(Adw.Toast.new(message))

    def _show_error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response('ok', 'OK')
        dialog.present(self)
