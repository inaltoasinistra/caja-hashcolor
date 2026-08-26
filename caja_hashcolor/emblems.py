"""Locating the installed emblem images at runtime.

The emblems are deliberately *not* installed into the hicolor icon theme's
emblems directory. Caja's emblem chooser (Properties -> Emblems) is populated
by gtk_icon_theme_list_icons(theme, "Emblems"), so anything installed there
shows up as a manually pickable emblem - and ~480 hash colors, which mean
nothing when chosen by hand, would bury the handful of emblems a user actually
wants. Icons registered through Gtk.IconTheme.append_search_path() are unthemed:
they have no context, never appear in that listing, and are still resolved by
name through the normal icon lookup that Caja.FileInfo.add_emblem() goes
through. Hence a private data directory plus a search path.
"""
import os

EMBLEM_SUBDIR = os.path.join('caja-hashcolor', 'emblems')
# Where the emblems sit in a source checkout: this file is caja_hashcolor/emblems.py,
# so the repository root is two levels up. Only reachable when running straight from
# a clone; an install always finds one of the data directories below first.
SOURCE_EMBLEM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'emblems')


def data_dirs() -> list[str]:
    """The XDG data directories, most specific first - the same search order
    caja-python itself uses to find extensions, so a user install shadows a
    system one for the emblems exactly as it does for the extension."""
    user_dir = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    system_dirs = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    return [user_dir] + [directory for directory in system_dirs.split(':') if directory]


def find_emblem_dir() -> str:
    """The directory to hand to Gtk.IconTheme.append_search_path(). Falls back to
    the source checkout, which is what makes running from a clone work at all."""
    for base in data_dirs():
        candidate = os.path.join(base, EMBLEM_SUBDIR)
        if os.path.isdir(candidate):
            return candidate
    return SOURCE_EMBLEM_DIR
