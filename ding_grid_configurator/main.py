import sys
import gi
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gio # type: ignore

from .window import DingConfiguratorWindow


class DingConfiguratorApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='com.github.darikzen.ding-grid-configurator',
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect('activate', self._on_activate)

    def _on_activate(self, app):
        win = DingConfiguratorWindow(application=app)
        win.present()


def main():
    app = DingConfiguratorApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
