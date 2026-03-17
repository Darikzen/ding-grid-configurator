PKGDATADIR  = /usr/share/ding-grid-configurator
APPDIR      = /usr/share/applications
POLKITDIR   = /usr/share/polkit-1/actions

.PHONY: install uninstall

install:
	@echo "==> Installing Python package..."
	pip3 install --break-system-packages .
	@echo "==> Installing privileged helper..."
	install -Dm755 ding_grid_configurator/pkexec_helper.sh \
		$(PKGDATADIR)/pkexec_helper.sh
	@echo "==> Installing desktop entry..."
	install -Dm644 data/com.github.darikzen.ding-grid-configurator.desktop \
		$(APPDIR)/com.github.darikzen.ding-grid-configurator.desktop
	@echo "==> Installing PolicyKit policy..."
	install -Dm644 data/com.github.darikzen.ding-grid-configurator.policy \
		$(POLKITDIR)/com.github.darikzen.ding-grid-configurator.policy
	@echo "==> Updating desktop database..."
	update-desktop-database $(APPDIR) 2>/dev/null || true
	@echo ""
	@echo "Done. Launch with: ding-grid-configurator"

uninstall:
	@echo "==> Removing Python package..."
	pip3 uninstall -y ding-grid-configurator || true
	@echo "==> Removing installed files..."
	rm -rf $(PKGDATADIR)
	rm -f  $(APPDIR)/com.github.darikzen.ding-grid-configurator.desktop
	rm -f  $(POLKITDIR)/com.github.darikzen.ding-grid-configurator.policy
	update-desktop-database $(APPDIR) 2>/dev/null || true
	@echo "Done."
