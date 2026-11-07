"""Synthetic tests; no game installation or personal save is read."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import local_paths as paths
import package_release


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        runs = ROOT / 'local/test-runs'
        runs.mkdir(parents=True, exist_ok=True)
        self.run = Path(tempfile.mkdtemp(prefix='case-', dir=runs))
        self.save = self.make('saves/生涯.fm')
        self.dll = self.make('game/fm_Data/Plugins/x86_64/game_plugin.dll')
        self.config_path = self.run / 'settings/paths.json'
        self.config = {'schema_version': 1, 'save_path': str(self.save), 'game_dll': str(self.dll)}
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Fixtures intentionally remain in ignored local/test-runs; no bulk cleanup.

    def make(self, relative, content=b'synthetic test data'):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_missing_config_is_first_run(self):
        self.assertEqual(paths.load_config(self.config_path), {})

    def test_roundtrip_remembers_exact_file(self):
        paths.remember_paths(self.config_path, self.save, self.dll)
        self.assertEqual(paths.load_config(self.config_path), self.config)
        with patch.object(paths, 'discover_saves', side_effect=AssertionError('must reuse config')):
            self.assertEqual(paths.resolve_save(config=self.config), (self.save, 'local_config'))
        self.assertEqual(paths.resolve_dll(config=self.config), (self.dll, 'local_config'))

    def test_explicit_save_and_game_override_environment_and_config(self):
        other = self.make('other/替代.fm')
        os.environ.update(FM27_SAVE_PATH='missing.fm', FM27_GAME_DLL='missing.dll')
        self.assertEqual(paths.resolve_save(other, self.config), (other, '--save'))
        self.assertEqual(paths.resolve_dll(self.run / 'game', self.config), (self.dll, '--game-dir'))

    def test_environment_overrides_config(self):
        other = self.make('other/环境.fm')
        os.environ.update(FM27_SAVE_PATH=str(other), FM27_GAME_DLL=str(self.dll))
        self.assertEqual(paths.resolve_save(config=self.config), (other, 'FM27_SAVE_PATH'))
        self.assertEqual(paths.resolve_dll(config=self.config), (self.dll, 'FM27_GAME_DLL'))

    def test_explicit_dll_file(self):
        self.assertEqual(paths.resolve_dll(self.dll), (self.dll, '--game-dir'))

    def test_stale_saved_path_does_not_switch_careers(self):
        self.config['save_path'] = str(self.run / 'missing.fm')
        with patch.object(paths, 'discover_saves', return_value=[self.save]) as discovery:
            with self.assertRaisesRegex(ValueError, 'do not silently switch'):
                paths.resolve_save(config=self.config)
            discovery.assert_not_called()

    def test_stale_dll_does_not_fall_back(self):
        self.config['game_dll'] = str(self.run / 'missing.dll')
        with patch.object(paths, 'discover_dll') as discovery:
            with self.assertRaisesRegex(ValueError, 'Game DLL not found'):
                paths.resolve_dll(config=self.config)
            discovery.assert_not_called()

    def test_documents_discovery_uses_newest_file(self):
        doc = self.run / 'redirected-documents'
        folder = doc / 'Sports Interactive/Football Manager 27/games'
        folder.mkdir(parents=True)
        older, newer = folder / 'older.fm', folder / 'newer.fm'
        older.write_bytes(b'old'); newer.write_bytes(b'new')
        os.utime(older, ns=(1000000000, 1000000000))
        os.utime(newer, ns=(2000000000, 2000000000))
        with patch.object(paths, 'document_directories', return_value=[doc]):
            self.assertEqual(paths.resolve_save(), (newer, 'newest_discovered_save'))

    def test_steam_library_on_another_volume_or_folder(self):
        steam, library = self.run / 'Steam', self.run / '自定义 Steam 库'
        vdf = steam / 'steamapps/libraryfolders.vdf'
        vdf.parent.mkdir(parents=True)
        escaped = str(library).replace('\\', '\\\\')
        vdf.write_text('"libraryfolders" { "0" { "path" "' + escaped + '" } }', encoding='utf8')
        dll = library / 'steamapps/common/Football Manager 27' / paths.DLL_RELATIVE
        dll.parent.mkdir(parents=True); dll.write_bytes(b'synthetic DLL')
        with patch.object(paths, 'steam_roots', return_value=[steam]):
            self.assertEqual(paths.discover_dll(), dll)

    def test_no_saves_produces_actionable_error(self):
        with patch.object(paths, 'discover_saves', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'Supply --save'):
                paths.resolve_save()

    def test_malformed_config_is_not_silently_ignored(self):
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text('{broken', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'Cannot read local path configuration'):
            paths.load_config(self.config_path)

    def test_config_schema_and_relative_paths_rejected(self):
        self.config_path.parent.mkdir(parents=True)
        for config in ({'schema_version': 2}, {**self.config, 'save_path': 'relative.fm'}):
            self.config_path.write_text(json.dumps(config), encoding='utf8')
            with self.assertRaises(ValueError):
                paths.load_config(self.config_path)

    def test_config_cannot_write_into_save_or_game_directories(self):
        for destination in (self.save.parent / 'config.json', self.run / 'game/config.json'):
            with self.assertRaisesRegex(ValueError, 'outside the save directory'):
                paths.remember_paths(destination, self.save, self.dll)
            self.assertFalse(destination.exists())

    def test_remember_flag_rejected_for_data_commands(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/fm.py'), 'baseline', '--remember-paths',
                                 '--config', str(self.config_path)], capture_output=True, text=True, encoding='utf8')
        self.assertEqual(result.returncode, 1)
        self.assertIn('only for doctor', json.loads(result.stdout)['message'])
        self.assertFalse(self.config_path.exists())

    def test_failed_doctor_does_not_create_config(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/fm.py'), 'doctor', '--remember-paths',
                                 '--save', str(self.save), '--game-dir', str(self.dll), '--config', str(self.config_path)],
                                capture_output=True, text=True, encoding='utf8')
        self.assertEqual(result.returncode, 1)
        self.assertIn('UNSUPPORTED_BUILD', json.loads(result.stdout)['message'])
        self.assertFalse(self.config_path.exists())

    def test_release_omits_private_files_but_keeps_runtime(self):
        source = self.run / 'release-fixture'
        for name in ('SKILL.md', 'LICENSE', 'local/paths.json', 'work/baseline.json', 'scripts/private.fm',
                     'scripts/game_plugin.dll', 'scripts/__pycache__/x.pyc', 'scripts/fm.py',
                     'scripts/vendor/unicorn/lib/unicorn.dll', 'references/licenses/unicorn-source.tar.gz'):
            self.make('release-fixture/' + name)
        archive_path = package_release.package(self.run / 'release.zip', source)
        with zipfile.ZipFile(archive_path) as archive:
            members = set(archive.namelist())
        self.assertEqual(members, {'release-fixture/' + p for p in (
            'SKILL.md', 'LICENSE', 'scripts/fm.py', 'scripts/vendor/unicorn/lib/unicorn.dll',
            'references/licenses/unicorn-source.tar.gz')})

    def test_third_party_source_archive_hash(self):
        source = ROOT / 'references/licenses/unicorn-2.1.4-source.tar.gz'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '00567a70e323f749b419cd86bee4f9115beab7ebba32194581c090cbb7c59cff')


if __name__ == '__main__':
    unittest.main()
