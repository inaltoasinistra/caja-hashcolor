# Installs the extension for the current user by default; running as root
# (`sudo make install`) switches to the system prefix instead. DESTDIR is kept
# as a plain staging prefix - the meaning distro packaging tools expect - so a
# .deb/.rpm build can point it at a build root without touching either default.
ifeq ($(shell id -u),0)
PREFIX ?= /usr
else
PREFIX ?= $(HOME)/.local
endif

DEST     := $(DESTDIR)$(PREFIX)
EXTDEST  := $(DEST)/share/caja-python/extensions
ICONDEST := $(DEST)/share/icons/hicolor/32x32/emblems

# hash_color.py is the only top-level module: caja-python imports every .py in
# the extensions directory, so everything else has to live inside the package.
EXTENSION := hash_color.py
PACKAGE   := caja_hashcolor
MODULES   := $(wildcard $(PACKAGE)/*.py)
EMBLEMS   := $(wildcard emblems/hashcolor-*.png)

INSTALL_DATA := install -Dm644

.PHONY: install install-extension install-emblems uninstall icon-cache link emblems test

install: install-extension install-emblems icon-cache

install-extension:
	$(INSTALL_DATA) $(EXTENSION) -t $(EXTDEST)
	$(INSTALL_DATA) $(MODULES) -t $(EXTDEST)/$(PACKAGE)

install-emblems:
	$(INSTALL_DATA) $(EMBLEMS) -t $(ICONDEST)

# The leading `-` keeps a missing gtk-update-icon-cache from failing the install.
# Skipped entirely for a staged (DESTDIR) build: the cache belongs to the live
# system, so distro packages regenerate it from their own post-install script
# rather than shipping one built against a staging root.
icon-cache:
ifeq ($(DESTDIR),)
	-gtk-update-icon-cache -q -f -t $(DEST)/share/icons/hicolor
else
	@echo 'DESTDIR set: skipping gtk-update-icon-cache (run it post-install)'
endif

# The extensions directory's __pycache__ is shared with every other Caja
# extension, so only our own entry is deleted, never the directory. rmdir is
# likewise conditional: another package may ship emblems in the same place.
uninstall:
	$(RM) $(EXTDEST)/$(EXTENSION)
	$(RM) -r $(EXTDEST)/$(PACKAGE)
	$(RM) $(EXTDEST)/__pycache__/$(basename $(EXTENSION)).*.pyc
	$(RM) $(ICONDEST)/hashcolor-*.png
	-rmdir --ignore-fail-on-non-empty $(ICONDEST)
	$(MAKE) icon-cache

# Development install: the modules are symlinked, so an edit is live after
# `caja -q`, while the emblems are installed normally (a symlinked directory
# is not something the icon theme would pick up).
link: install-emblems icon-cache
	install -d $(EXTDEST)
	ln -sfn $(CURDIR)/$(EXTENSION) $(CURDIR)/$(PACKAGE) $(EXTDEST)/

emblems:
	python3 generate_emblems.py

test:
	python3 -m unittest discover -p "test_*.py"
