"""Restart the DING GNOME Shell extension."""

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib # type: ignore


EXTENSION_UUID = 'ding@rastersoft.com'


def restart_extension(callback=None):
    """
    Disable then re-enable the DING extension via gnome-extensions CLI.
    callback(success: bool, error_msg: str | None) is called when done.
    """
    def _disable_done(proc, result):
        try:
            proc.wait_finish(result)
        except Exception as e:
            if callback:
                callback(False, str(e))
            return
        _run_enable()

    def _enable_done(proc, result):
        try:
            proc.wait_finish(result)
            if callback:
                callback(True, None)
        except Exception as e:
            if callback:
                callback(False, str(e))

    def _run_enable():
        proc = Gio.Subprocess.new(
            ['gnome-extensions', 'enable', EXTENSION_UUID],
            Gio.SubprocessFlags.NONE,
        )
        proc.wait_async(None, _enable_done)

    proc = Gio.Subprocess.new(
        ['gnome-extensions', 'disable', EXTENSION_UUID],
        Gio.SubprocessFlags.NONE,
    )
    proc.wait_async(None, _disable_done)
