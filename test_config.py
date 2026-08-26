#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caja_hashcolor import config


class TestConfig(unittest.TestCase):
    tmp_dir: str

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        config_path = Path(self.tmp_dir) / 'config.json'
        self.config_path_patch = patch.object(config, 'CONFIG_PATH', config_path)
        self.config_dir_patch = patch.object(config, 'CONFIG_DIR', config_path.parent)
        self.config_path_patch.start()
        self.config_dir_patch.start()

    def tearDown(self) -> None:
        self.config_path_patch.stop()
        self.config_dir_patch.stop()

    def test_defaults_are_empty(self):
        loaded = config.load_config()
        self.assertEqual(loaded, {'fast_dirs': [], 'precise_dirs': []})

    def test_get_mode_for_directory_absent_is_none(self):
        loaded = config.load_config()
        self.assertIsNone(config.get_mode_for_directory('/some/dir', loaded))

    def test_set_mode_enables_directory(self):
        config.set_mode_for_directory('/some/dir', 'fast')
        loaded = config.load_config()
        self.assertEqual(config.get_mode_for_directory('/some/dir', loaded), 'fast')

    def test_setting_precise_disables_fast_for_same_directory(self):
        """Enabling one mode for a directory must turn off the other - a directory
        should never be in both lists at once."""
        config.set_mode_for_directory('/some/dir', 'fast')
        config.set_mode_for_directory('/some/dir', 'precise')
        loaded = config.load_config()
        self.assertEqual(config.get_mode_for_directory('/some/dir', loaded), 'precise')
        self.assertNotIn('/some/dir', loaded['fast_dirs'])

    def test_set_mode_none_disables_directory(self):
        config.set_mode_for_directory('/some/dir', 'fast')
        config.set_mode_for_directory('/some/dir', None)
        loaded = config.load_config()
        self.assertIsNone(config.get_mode_for_directory('/some/dir', loaded))

    def test_directories_are_independent(self):
        config.set_mode_for_directory('/dir/a', 'fast')
        config.set_mode_for_directory('/dir/b', 'precise')
        loaded = config.load_config()
        self.assertEqual(config.get_mode_for_directory('/dir/a', loaded), 'fast')
        self.assertEqual(config.get_mode_for_directory('/dir/b', loaded), 'precise')

    def test_prune_missing_dirs_removes_only_nonexistent_directories(self):
        surviving_dir = os.path.join(self.tmp_dir, 'exists')
        os.mkdir(surviving_dir)
        config.set_mode_for_directory(surviving_dir, 'fast')
        config.set_mode_for_directory('/no/such/dir', 'precise')

        removed_count = config.prune_missing_dirs()

        self.assertEqual(removed_count, 1)
        loaded = config.load_config()
        self.assertEqual(config.get_mode_for_directory(surviving_dir, loaded), 'fast')
        self.assertIsNone(config.get_mode_for_directory('/no/such/dir', loaded))

    def test_save_leaves_no_leftover_temp_file(self):
        """save_config() writes via a temp file + atomic rename, so a crash or kill
        mid-write can never leave config.json truncated - confirm the temp file
        doesn't linger after a normal save."""
        config.set_mode_for_directory('/some/dir', 'fast')
        temp_path = config.CONFIG_PATH.with_suffix('.json.tmp')
        self.assertTrue(config.CONFIG_PATH.exists())
        self.assertFalse(temp_path.exists())

    def test_corrupt_config_file_is_treated_as_empty_not_a_crash(self):
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.CONFIG_PATH, 'w') as corrupt_file:
            corrupt_file.write('{not valid json')

        loaded = config.load_config()

        self.assertEqual(loaded, {'fast_dirs': [], 'precise_dirs': []})


if __name__ == '__main__':
    unittest.main()
