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
# A private directory, not share/icons/: emblems installed into the icon theme's
# Emblems context turn up in Caja's manual emblem chooser, where 480 hash colors
# are pure noise. hash_color.py registers this as an icon-theme search path.
EMBLEMDEST := $(DEST)/share/caja-hashcolor/emblems

# hash_color.py is the only top-level module: caja-python imports every .py in
# the extensions directory, so everything else has to live inside the package.
EXTENSION := hash_color.py
PACKAGE   := caja_hashcolor
MODULES   := $(wildcard $(PACKAGE)/*.py)
EMBLEMS   := $(wildcard emblems/hashcolor-*.png)

INSTALL_DATA := install -Dm644

.PHONY: install install-extension install-emblems uninstall link emblems test

install: install-extension install-emblems

install-extension:
	$(INSTALL_DATA) $(EXTENSION) -t $(EXTDEST)
	$(INSTALL_DATA) $(MODULES) -t $(EXTDEST)/$(PACKAGE)

install-emblems:
	$(INSTALL_DATA) $(EMBLEMS) -t $(EMBLEMDEST)

# The extensions directory's __pycache__ is shared with every other Caja
# extension, so only our own entry is deleted, never the directory. The emblem
# directory is ours alone, so it goes whole.
uninstall:
	$(RM) $(EXTDEST)/$(EXTENSION)
	$(RM) -r $(EXTDEST)/$(PACKAGE)
	$(RM) $(EXTDEST)/__pycache__/$(basename $(EXTENSION)).*.pyc
	$(RM) -r $(DEST)/share/caja-hashcolor

# Development install: the modules are symlinked, so an edit is live after
# `caja -q`, while the emblems are installed normally - find_emblem_dir() looks
# in the data directories first, so a symlinked repo copy would be ignored.
link: install-emblems
	install -d $(EXTDEST)
	ln -sfn $(CURDIR)/$(EXTENSION) $(CURDIR)/$(PACKAGE) $(EXTDEST)/

emblems:
	python3 generate_emblems.py

test:
	python3 -m unittest discover -p "test_*.py"
