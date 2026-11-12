"""Regression checks for version admission and retained integrity guards."""
import importlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(ROOT))
import fm
import fmsave


class VersionPolicyTests(unittest.TestCase):
    def make_save(self, build, *, game='FM27', schemas=None):
        club = SimpleNamespace(uid=679, name='Test Club', teams=[SimpleNamespace(team_id=557)])
        return SimpleNamespace(
            info=SimpleNamespace(build=build, game=game, known_build=False,
                                 section_schemas=schemas or {}),
            managed_clubs=lambda: [SimpleNamespace(club_uid=679, club_name='Test Club')],
            clubs=lambda: [club], close=lambda: None)

    def open_session(self, save, digest, command='doctor'):
        args = fm.parser().parse_args([command])
        dll = SimpleNamespace(open=lambda mode: io.BytesIO(b'dll'))
        with patch.object(fm, 'resolve_dll', return_value=(dll, 'test')), patch.object(fm, 'load_config', return_value={}), \
             patch.object(fm.hashlib, 'file_digest', return_value=SimpleNamespace(hexdigest=lambda: digest)), \
             patch.object(fm, 'resolve_save', return_value=(Path(__file__), 'test')), \
             patch.object(fmsave, 'open', return_value=save) as opened, \
             patch.dict(fm.os.environ):
            session = fm.Session(args)
            opened.assert_called_once_with(Path(__file__), strict=True)
            return session

    def test_unknown_dll_and_unknown_build_are_admitted(self):
        session = self.open_session(self.make_save('27.0.9+9999999'), 'unknown')
        self.assertFalse(session.profile['version_check_enforced'])
        self.assertFalse(session.profile['native_profile_validated'])
        self.assertTrue(any('unverified' in n for n in session.notices))

    def test_known_dll_with_different_save_build_is_admitted(self):
        session = self.open_session(self.make_save(fm.BUILD), fm.NEW_DLL_HASH)
        self.assertFalse(session.profile['profile_validated'])

    def test_matching_reference_keeps_historical_evidence(self):
        session = self.open_session(self.make_save(fm.BUILD), fm.DLL_HASH)
        self.assertTrue(session.profile['native_profile_validated'])
        self.assertFalse(session.profile['version_check_enforced'])

    def test_schema_damage_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_SCHEMA'):
            self.open_session(self.make_save(fm.NEW_BUILD, schemas={'game_info': -1}), 'unknown')

    def test_non_fm27_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'FM27 saves only'):
            self.open_session(self.make_save(fm.BUILD, game='FM26'), 'unknown')

    def test_failed_season_integrity_capability_stays_disabled(self):
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_CAPABILITY'):
            self.open_session(self.make_save(fm.NEW_BUILD), 'unknown', command='season')

    def test_unknown_dll_reaches_match_structure_validation(self):
        with patch.dict(fm.os.environ, FM27_GAME_DLL='unused.dll'):
            codec = importlib.import_module('match_codec')
        with patch.object(codec, 'dll_hash', return_value='unknown'):
            with self.assertRaisesRegex(codec.UnsupportedVariant, 'match stream version'):
                codec.read_match(b'invalid', {}, build=fm.NEW_BUILD)

    def test_native_decoder_still_rejects_out_of_bounds_stream(self):
        with patch.dict(fm.os.environ, FM27_GAME_DLL='unused.dll'):
            decoder = importlib.import_module('emulate_player_2701').PlayerDecoder2701
        with self.assertRaisesRegex(ValueError, 'outside bounded stream'):
            decoder(b'', 0)

    def test_file_changed_during_read_still_rejected(self):
        session = object.__new__(fm.Session)
        session.before = SimpleNamespace(st_size=10, st_mtime_ns=1)
        session.path = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=11, st_mtime_ns=2))
        with self.assertRaisesRegex(RuntimeError, 'SAVE_CHANGED'):
            session.checked()


if __name__ == '__main__':
    unittest.main(verbosity=2)
