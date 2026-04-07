from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from doomgame.music import (
    AdaptiveMusicLogic,
    DoomMusicPlayer,
    MOOD_CALM,
    MOOD_COMBAT,
    MOOD_FRENZY,
    MusicSnapshot,
    MusicTrack,
)


class AdaptiveMusicLogicTests(unittest.TestCase):
    def test_track_classification_uses_filename_intent(self) -> None:
        self.assertEqual(MOOD_FRENZY, AdaptiveMusicLogic.classify_track(Path("doom_02. Rip & Tear.mp3")))
        self.assertEqual(MOOD_FRENZY, AdaptiveMusicLogic.classify_track(Path("at dooms gate.mp3")))
        self.assertEqual(MOOD_COMBAT, AdaptiveMusicLogic.classify_track(Path("DooM_-_Main_Theme_OST.mp3")))
        self.assertEqual(MOOD_CALM, AdaptiveMusicLogic.classify_track(Path("The_Imp_s_Song.mp3")))

    def test_target_intensity_stays_low_in_calm_state(self) -> None:
        intensity = AdaptiveMusicLogic.compute_target_intensity(MusicSnapshot(movement=0.12))
        self.assertLess(intensity, 0.1)

    def test_target_intensity_rises_with_combat_pressure(self) -> None:
        calm = AdaptiveMusicLogic.compute_target_intensity(MusicSnapshot(active_enemies=1, movement=0.2))
        intense = AdaptiveMusicLogic.compute_target_intensity(
            MusicSnapshot(
                active_enemies=8,
                nearby_enemies=4,
                attacking_enemies=3,
                projectile_count=4,
                movement=1.0,
                recent_shots=0.9,
                recent_damage=0.7,
                recent_kills=0.4,
            )
        )
        self.assertGreater(intense, calm)
        self.assertGreater(intense, 0.7)

    def test_logic_reaches_frenzy_under_sustained_pressure(self) -> None:
        logic = AdaptiveMusicLogic()
        snapshot = MusicSnapshot(
            active_enemies=8,
            nearby_enemies=4,
            attacking_enemies=3,
            projectile_count=4,
            movement=1.0,
            recent_shots=1.0,
            recent_damage=0.8,
            recent_kills=0.5,
        )
        mood = MOOD_CALM
        for _ in range(8):
            mood = logic.update(snapshot, 1.0, {MOOD_CALM, MOOD_COMBAT, MOOD_FRENZY})
        self.assertEqual(MOOD_FRENZY, mood)

    def test_logic_holds_previous_mood_before_switching_back_down(self) -> None:
        logic = AdaptiveMusicLogic()
        heavy = MusicSnapshot(
            active_enemies=8,
            nearby_enemies=4,
            attacking_enemies=3,
            projectile_count=3,
            movement=0.9,
            recent_shots=1.0,
        )
        for _ in range(8):
            logic.update(heavy, 1.0, {MOOD_CALM, MOOD_COMBAT, MOOD_FRENZY})
        self.assertEqual(MOOD_FRENZY, logic.current_mood)

        mood = logic.update(MusicSnapshot(), 0.5, {MOOD_CALM, MOOD_COMBAT, MOOD_FRENZY})
        self.assertEqual(MOOD_FRENZY, mood)

        for _ in range(10):
            mood = logic.update(MusicSnapshot(), 1.0, {MOOD_CALM, MOOD_COMBAT, MOOD_FRENZY})
        self.assertEqual(MOOD_CALM, mood)

    def test_logic_falls_back_to_available_neighboring_mood(self) -> None:
        logic = AdaptiveMusicLogic()
        snapshot = MusicSnapshot(
            active_enemies=7,
            nearby_enemies=4,
            attacking_enemies=3,
            projectile_count=3,
            movement=0.9,
            recent_shots=1.0,
        )
        mood = MOOD_CALM
        for _ in range(8):
            mood = logic.update(snapshot, 1.0, {MOOD_CALM, MOOD_COMBAT})
        self.assertEqual(MOOD_COMBAT, mood)


class DoomMusicPlayerTests(unittest.TestCase):
    def test_music_scan_excludes_doom_sound_effect_assets(self) -> None:
        player = DoomMusicPlayer()

        self.assertFalse(player._is_music_asset(Path("dspistol.wav")))
        self.assertFalse(player._is_music_asset(Path("dsplpain.wav")))
        self.assertTrue(player._is_music_asset(Path("doom_02. Rip & Tear.mp3")))
        self.assertTrue(player._is_music_asset(Path("DooM_-_Main_Theme_OST.mp3")))

    def test_file_track_switch_uses_dedicated_channels_instead_of_stream_reload(self) -> None:
        player = DoomMusicPlayer()
        first_channel = mock.Mock()
        second_channel = mock.Mock()
        second_channel.get_busy.return_value = True
        player._file_music_channels = (first_channel, second_channel)
        player._current_music_channel_index = 0
        track = MusicTrack(path=Path("rip_and_tear.ogg"), mood=MOOD_FRENZY, sound=mock.Mock())

        with mock.patch("doomgame.music.pygame.mixer.music") as streamed_music:
            played = player._play_file_track(track, fade_ms=400)

        self.assertTrue(played)
        first_channel.play.assert_called_once_with(track.sound, loops=-1, fade_ms=400)
        second_channel.fadeout.assert_called_once_with(400)
        streamed_music.load.assert_not_called()
        streamed_music.play.assert_not_called()

    def test_background_bed_marks_calm_as_available_without_calm_overlay_track(self) -> None:
        player = DoomMusicPlayer()
        player._background_enabled = True
        player._tracks = [MusicTrack(path=Path("combat.mp3"), mood=MOOD_COMBAT, sound=mock.Mock())]

        self.assertEqual({MOOD_CALM, MOOD_COMBAT}, player._available_moods())

    def test_calm_update_fades_out_overlay_instead_of_switching_stream(self) -> None:
        player = DoomMusicPlayer()
        player.enabled = True
        player.using_file_music = True
        player._background_enabled = True
        player._tracks = [MusicTrack(path=Path("combat.mp3"), mood=MOOD_COMBAT, sound=mock.Mock())]
        player._current_track = player._tracks[0]
        player._logic.current_mood = MOOD_COMBAT
        player._logic.intensity = 0.4
        first_channel = mock.Mock()
        first_channel.get_busy.return_value = True
        second_channel = mock.Mock()
        second_channel.get_busy.return_value = False
        player._file_music_channels = (first_channel, second_channel)

        with mock.patch.object(player, "_play_file_track") as play_track:
            for _ in range(10):
                player.update(MusicSnapshot(), 1.0)

        first_channel.fadeout.assert_called()
        play_track.assert_not_called()


if __name__ == "__main__":
    unittest.main()
