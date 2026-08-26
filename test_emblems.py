"""Checks the committed emblems/ directory against palette.py, and the runtime
lookup that finds the installed copy of it.

The install has no build step: `make install` copies emblems/hashcolor-*.png
straight into the icon theme by glob. So the shipped set has to match what
palette.py can actually ask for - a name with no file renders as a broken icon
in Caja, and a leftover file from a renamed emblem gets installed for nothing.
Dimensions are read from the PNG header rather than with Pillow, which is a
dev-only dependency of generate_emblems.py and not something the test suite
should require.
"""
import os
import struct
import tempfile
import unittest
from unittest.mock import patch

from caja_hashcolor import emblems
from caja_hashcolor.palette import ALL_EMBLEM_NAMES, CLEAR_EMBLEM_NAME, EMBLEM_SIZE_PX

EMBLEM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emblems')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def png_size(path: str) -> tuple[int, int]:
    """Width and height from a PNG's IHDR chunk, which the format requires to be
    the first chunk right after the 8-byte signature."""
    with open(path, 'rb') as f:
        header = f.read(24)
    if header[:8] != PNG_SIGNATURE or header[12:16] != b'IHDR':
        raise ValueError(f'not a PNG with a leading IHDR chunk: {path}')
    return struct.unpack('>II', header[16:24])


def expected_names() -> list[str]:
    """Every emblem name the extension can ask the icon theme for. CLEAR_EMBLEM_NAME
    is deliberately outside ALL_EMBLEM_NAMES (it is never a hash result, only the
    'directory disabled' placeholder), so it has to be added back by hand here."""
    return ALL_EMBLEM_NAMES + [CLEAR_EMBLEM_NAME]


def installed_names() -> list[str]:
    """The files `make install-emblems` would copy, by emblem name."""
    return [
        name[:-len('.png')]
        for name in os.listdir(EMBLEM_DIR)
        if name.startswith('hashcolor-') and name.endswith('.png')
    ]


class TestEmblemFiles(unittest.TestCase):
    def test_every_name_has_a_file(self) -> None:
        """A name palette.py can return but no file ships for shows as a broken icon."""
        missing = [name for name in expected_names() if not os.path.isfile(os.path.join(EMBLEM_DIR, f'{name}.png'))]
        self.assertEqual([], missing)

    def test_no_orphan_files(self) -> None:
        """A file no name maps to (e.g. left behind by a rename) would still be installed."""
        self.assertEqual(set(), set(installed_names()) - set(expected_names()))

    def test_names_are_unique(self) -> None:
        """Two specs colliding on one name would silently share a single file."""
        names = expected_names()
        self.assertEqual(len(names), len(set(names)))

    def test_all_files_are_one_size(self) -> None:
        """Emblems are resolved as unthemed icons, so GTK hands Caja whatever the
        file happens to be - a stray odd-sized one would render inconsistently."""
        wrong = {
            name: png_size(os.path.join(EMBLEM_DIR, f'{name}.png'))
            for name in installed_names()
            if png_size(os.path.join(EMBLEM_DIR, f'{name}.png')) != (EMBLEM_SIZE_PX, EMBLEM_SIZE_PX)
        }
        self.assertEqual({}, wrong)


class TestFindEmblemDir(unittest.TestCase):
    """find_emblem_dir() decides which installed copy of emblems/ the extension
    registers with the icon theme, so a user install has to win over a system one."""

    user_dir: str
    system_dir: str

    def setUp(self) -> None:
        self.user_dir = tempfile.mkdtemp()
        self.system_dir = tempfile.mkdtemp()

    def _make_emblem_dir(self, base: str) -> str:
        path = os.path.join(base, emblems.EMBLEM_SUBDIR)
        os.makedirs(path)
        return path

    def test_finds_a_system_install(self) -> None:
        expected = self._make_emblem_dir(self.system_dir)
        with patch.dict(os.environ, {'XDG_DATA_HOME': self.user_dir, 'XDG_DATA_DIRS': self.system_dir}):
            self.assertEqual(expected, emblems.find_emblem_dir())

    def test_user_install_wins_over_system(self) -> None:
        """Both installed at once must resolve the same way caja-python resolves
        the extension itself, or the emblems could come from the older copy."""
        expected = self._make_emblem_dir(self.user_dir)
        self._make_emblem_dir(self.system_dir)
        with patch.dict(os.environ, {'XDG_DATA_HOME': self.user_dir, 'XDG_DATA_DIRS': self.system_dir}):
            self.assertEqual(expected, emblems.find_emblem_dir())

    def test_falls_back_to_the_source_checkout(self) -> None:
        """Nothing installed: running from a clone still has to find its emblems."""
        with patch.dict(os.environ, {'XDG_DATA_HOME': self.user_dir, 'XDG_DATA_DIRS': self.system_dir}):
            self.assertEqual(EMBLEM_DIR, emblems.find_emblem_dir())
        self.assertTrue(os.path.isdir(EMBLEM_DIR))


if __name__ == '__main__':
    unittest.main()
