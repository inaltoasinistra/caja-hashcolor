"""Tests for XDG base directory resolution.

Every one of these patches os.environ wholesale with clear=True, so the result
never depends on what the developer running the suite happens to have exported.
"""
import os
import unittest
from unittest.mock import patch

from caja_hashcolor import xdg


class TestBaseDirs(unittest.TestCase):
    """config_home(), cache_home() and data_home() are the same function with
    different constants, so each rule is checked once on whichever is clearest
    and the shared behaviour is checked across all three."""

    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_when_unset(self) -> None:
        self.assertEqual(os.path.expanduser('~/.config'), xdg.config_home())
        self.assertEqual(os.path.expanduser('~/.cache'), xdg.cache_home())
        self.assertEqual(os.path.expanduser('~/.local/share'), xdg.data_home())

    @patch.dict(os.environ, {'XDG_CONFIG_HOME': '/srv/conf', 'XDG_CACHE_HOME': '/srv/cache',
                             'XDG_DATA_HOME': '/srv/data'}, clear=True)
    def test_absolute_override_is_used(self) -> None:
        self.assertEqual('/srv/conf', xdg.config_home())
        self.assertEqual('/srv/cache', xdg.cache_home())
        self.assertEqual('/srv/data', xdg.data_home())

    @patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative/path'}, clear=True)
    def test_relative_override_is_ignored(self) -> None:
        """The spec calls a non-absolute value invalid. Honouring it would write
        the config file relative to whatever directory Caja was started from."""
        self.assertEqual(os.path.expanduser('~/.config'), xdg.config_home())

    @patch.dict(os.environ, {'XDG_CACHE_HOME': ''}, clear=True)
    def test_empty_override_is_ignored(self) -> None:
        self.assertEqual(os.path.expanduser('~/.cache'), xdg.cache_home())


class TestDataDirs(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_when_unset(self) -> None:
        self.assertEqual([os.path.expanduser('~/.local/share'), '/usr/local/share', '/usr/share'],
                         xdg.data_dirs())

    @patch.dict(os.environ, {'XDG_DATA_HOME': '/srv/data', 'XDG_DATA_DIRS': '/opt/a:/opt/b'}, clear=True)
    def test_user_dir_comes_first(self) -> None:
        """Order is what makes a user install shadow a system one."""
        self.assertEqual(['/srv/data', '/opt/a', '/opt/b'], xdg.data_dirs())

    @patch.dict(os.environ, {'XDG_DATA_DIRS': '/opt/a:relative:/opt/b'}, clear=True)
    def test_relative_entries_are_dropped(self) -> None:
        self.assertEqual(['/opt/a', '/opt/b'], xdg.data_dirs()[1:])

    @patch.dict(os.environ, {'XDG_DATA_DIRS': ''}, clear=True)
    def test_empty_falls_back_to_the_default_list(self) -> None:
        self.assertEqual(['/usr/local/share', '/usr/share'], xdg.data_dirs()[1:])


if __name__ == '__main__':
    unittest.main()
