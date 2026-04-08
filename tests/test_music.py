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
    STATE_AFTERMATH,
    STATE_CLIMAX,
    STATE_COMBAT,
    STATE_EXPLORATION,
    STATE_THREAT,
    MusicSnapshot,
    MusicTrack,
)


class AdaptiveMusicLogicTests(unittest.TestCase):
    def test_track_classification_uses_filename_intent(self) -> None:
        self.assertEqual(STATE_CLIMAX, AdaptiveMusicLogic.classify_track(Path("doom_02. Rip & Tear.mp3")))
        self.assertEqual(STATE_CLIMAX, AdaptiveMusicLogic.classify_track(Path("Mick Gordon - Bfg Division.mp3")))
        self.assertEqual(STATE_COMBAT, AdaptiveMusicLogic.classify_track(Path("at dooms morgen.mp3")))
        self.assertEqual(STATE_COMBAT, AdaptiveMusicLogic.classify_track(Path("at dooms gate.mp3")))
        self.assertEqual(STATE_COMBAT, AdaptiveMusicLogic.classify_track(Path("Mick Gordon - Cultist Base.mp3")))
        self.assertEqual(STATE_THREAT, AdaptiveMusicLogic.classify_track(Path("Mick Gordon - Faust.mp3")))
        self.assertEqual(STATE_THREAT, AdaptiveMusicLogic.classify_track(Path("DooM_-_Main_Theme_OST.mp3")))
        self.assertEqual(STATE_EXPLORATION, AdaptiveMusicLogic.classify_track(Path("Mick Gordon - Ride to the Base.mp3")))
        self.assertEqual(STATE_EXPLORATION, AdaptiveMusicLogic.classify_track(Path("The_Imp_s_Song.mp3")))

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
                active_threat=9.0,
                nearby_threat=6.0,
                attacking_threat=5.0,
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
            active_threat=9.0,
            nearby_threat=6.0,
            attacking_threat=5.0,
            projectile_count=4,
            movement=1.0,
            recent_shots=1.0,
            recent_damage=0.8,
            recent_kills=0.5,
        )
        mood = MOOD_CALM
        for _ in range(8):
            mood = logic.update(snapshot, 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX})
        self.assertEqual(STATE_CLIMAX, mood)

    def test_logic_holds_previous_mood_before_switching_back_down(self) -> None:
        logic = AdaptiveMusicLogic()
        heavy = MusicSnapshot(
            active_enemies=8,
            nearby_enemies=4,
            attacking_enemies=3,
            active_threat=9.0,
            nearby_threat=6.0,
            attacking_threat=5.0,
            projectile_count=4,
            movement=0.9,
            recent_shots=1.0,
            recent_damage=0.7,
            recent_kills=0.6,
        )
        for _ in range(8):
            logic.update(heavy, 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX})
        self.assertEqual(STATE_CLIMAX, logic.current_mood)

        mood = logic.update(MusicSnapshot(), 0.5, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX, STATE_AFTERMATH})
        self.assertEqual(STATE_CLIMAX, mood)

        for _ in range(10):
            mood = logic.update(MusicSnapshot(), 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX, STATE_AFTERMATH})
        self.assertIn(mood, {STATE_AFTERMATH, STATE_EXPLORATION})

    def test_logic_falls_back_to_available_neighboring_mood(self) -> None:
        logic = AdaptiveMusicLogic()
        snapshot = MusicSnapshot(
            active_enemies=7,
            nearby_enemies=4,
            attacking_enemies=3,
            active_threat=8.5,
            nearby_threat=5.8,
            attacking_threat=4.5,
            projectile_count=3,
            movement=0.9,
            recent_shots=1.0,
        )
        mood = MOOD_CALM
        for _ in range(8):
            mood = logic.update(snapshot, 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT})
        self.assertEqual(STATE_COMBAT, mood)

    def test_logic_escalates_quickly_when_multiple_heavies_are_nearby(self) -> None:
        logic = AdaptiveMusicLogic()
        snapshot = MusicSnapshot(
            active_enemies=4,
            nearby_enemies=4,
            active_threat=9.4,
            nearby_threat=9.4,
            movement=0.5,
            recent_shots=0.85,
            recent_kills=0.7,
        )

        mood = logic.update(snapshot, 0.35, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX})

        self.assertEqual(STATE_COMBAT, mood)

    def test_logic_uses_threat_phase_for_visible_but_not_active_danger(self) -> None:
        logic = AdaptiveMusicLogic()
        snapshot = MusicSnapshot(
            active_enemies=2,
            active_threat=2.2,
            nearby_enemies=1,
            nearby_threat=1.2,
        )

        mood = logic.update(snapshot, 0.8, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX})

        self.assertEqual(STATE_THREAT, mood)

    def test_logic_enters_aftermath_after_battle_resolves(self) -> None:
        logic = AdaptiveMusicLogic()
        peak = MusicSnapshot(
            active_enemies=7,
            nearby_enemies=4,
            attacking_enemies=3,
            active_threat=8.8,
            nearby_threat=6.4,
            attacking_threat=5.2,
            projectile_count=3,
            recent_shots=1.0,
            recent_damage=0.7,
            recent_kills=0.6,
        )
        for _ in range(6):
            logic.update(peak, 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX, STATE_AFTERMATH})

        mood = STATE_COMBAT
        for _ in range(8):
            mood = logic.update(MusicSnapshot(), 1.0, {STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX, STATE_AFTERMATH})
            if mood == STATE_AFTERMATH:
                break

        self.assertEqual(STATE_AFTERMATH, mood)


class DoomMusicPlayerTests(unittest.TestCase):
    def test_music_scan_excludes_doom_sound_effect_assets(self) -> None:
        player = DoomMusicPlayer()

        self.assertFalse(player._is_music_asset(Path("dspistol.wav")))
        self.assertFalse(player._is_music_asset(Path("dsplpain.wav")))
        self.assertTrue(player._is_music_asset(Path("doom_02. Rip & Tear.mp3")))
        self.assertTrue(player._is_music_asset(Path("at dooms morgen.mp3")))
        self.assertTrue(player._is_music_asset(Path("DooM_-_Main_Theme_OST.mp3")))
        self.assertTrue(player._is_music_asset(Path("Mick Gordon - Bfg Division.mp3")))
        self.assertTrue(player._is_music_asset(Path("Mick Gordon - Faust.mp3")))
        self.assertTrue(player._is_music_asset(Path("Mick Gordon - Ride to the Base.mp3")))
        self.assertTrue(player._is_music_asset(Path("Mick Gordon - Cultist Base.mp3")))

    def test_file_track_switch_uses_dedicated_channels_instead_of_stream_reload(self) -> None:
        player = DoomMusicPlayer()
        first_channel = mock.Mock()
        second_channel = mock.Mock()
        first_channel.get_busy.return_value = True
        second_channel.get_busy.return_value = False
        player._file_music_channels = (first_channel, second_channel)
        player._current_music_channel_index = 0
        track = MusicTrack(path=Path("rip_and_tear.ogg"), mood=MOOD_FRENZY, sound=mock.Mock())

        with mock.patch("doomgame.music.pygame.mixer.music") as streamed_music:
            played = player._play_file_track(track, fade_ms=400)

        self.assertTrue(played)
        second_channel.play.assert_called_once_with(track.sound, loops=-1)
        first_channel.set_volume.assert_called_with(0.0)
        streamed_music.load.assert_not_called()
        streamed_music.play.assert_not_called()
        self.assertEqual(1.0, player._channel_target_volume[player._current_music_channel_index])

    def test_available_moods_are_derived_from_loaded_tracks(self) -> None:
        player = DoomMusicPlayer()
        player._tracks = [
            MusicTrack(path=Path("imp_song.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock()),
            MusicTrack(path=Path("combat.mp3"), mood=STATE_COMBAT, sound=mock.Mock()),
        ]

        self.assertEqual({STATE_EXPLORATION, STATE_COMBAT}, player._available_moods())

    def test_select_track_prefers_at_dooms_gate_for_high_combat_intensity(self) -> None:
        player = DoomMusicPlayer()
        at_dooms_gate = MusicTrack(path=Path("at dooms gate.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        main_theme = MusicTrack(path=Path("DooM_-_Main_Theme_OST.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        player._tracks = [main_theme, at_dooms_gate]

        selected = player._select_track_for_mood(STATE_COMBAT, 0.64)

        self.assertEqual(at_dooms_gate, selected)

    def test_select_track_prefers_main_theme_for_mid_combat_intensity(self) -> None:
        player = DoomMusicPlayer()
        at_dooms_gate = MusicTrack(path=Path("at dooms gate.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        main_theme = MusicTrack(path=Path("DooM_-_Main_Theme_OST.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        player._tracks = [main_theme, at_dooms_gate]

        selected = player._select_track_for_mood(STATE_COMBAT, 0.34)

        self.assertEqual(main_theme, selected)

    def test_select_track_prefers_rip_and_tear_for_climax(self) -> None:
        player = DoomMusicPlayer()
        rip = MusicTrack(path=Path("doom_02. Rip & Tear.mp3"), mood=STATE_CLIMAX, sound=mock.Mock())
        generic = MusicTrack(path=Path("climax_generic.mp3"), mood=STATE_CLIMAX, sound=mock.Mock())
        player._tracks = [generic, rip]

        selected = player._select_track_for_mood(STATE_CLIMAX, 0.93)

        self.assertEqual(rip, selected)

    def test_select_track_prefers_bfg_division_for_peak_climax(self) -> None:
        player = DoomMusicPlayer()
        rip = MusicTrack(path=Path("doom_02. Rip & Tear.mp3"), mood=STATE_CLIMAX, sound=mock.Mock())
        bfg = MusicTrack(path=Path("Mick Gordon - Bfg Division.mp3"), mood=STATE_CLIMAX, sound=mock.Mock())
        player._tracks = [rip, bfg]

        selected = player._select_track_for_mood(STATE_CLIMAX, 0.985)

        self.assertEqual(bfg, selected)

    def test_select_track_prefers_cultist_base_for_regular_combat(self) -> None:
        player = DoomMusicPlayer()
        at_dooms_gate = MusicTrack(path=Path("at dooms gate.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        cultist = MusicTrack(path=Path("Mick Gordon - Cultist Base.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        player._tracks = [at_dooms_gate, cultist]

        selected = player._select_track_for_mood(STATE_COMBAT, 0.57)

        self.assertEqual(cultist, selected)

    def test_select_track_prefers_ride_to_the_base_for_exploration(self) -> None:
        player = DoomMusicPlayer()
        imp = MusicTrack(path=Path("The_Imp_s_Song.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock())
        ride = MusicTrack(path=Path("Mick Gordon - Ride to the Base.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock())
        player._tracks = [imp, ride]

        selected = player._select_track_for_mood(STATE_EXPLORATION, 0.15)

        self.assertEqual(ride, selected)

    def test_calm_update_switches_to_calm_track(self) -> None:
        player = DoomMusicPlayer()
        player.enabled = True
        player.using_file_music = True
        calm_track = MusicTrack(path=Path("The_Imp_s_Song.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock())
        combat_track = MusicTrack(path=Path("combat.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        player._tracks = [calm_track, combat_track]
        player._current_track = combat_track
        player._session_time = 24.0
        player._current_track_started_at = 0.0

        with (
            mock.patch.object(player._logic, "update", return_value=STATE_EXPLORATION),
            mock.patch.object(player, "_play_file_track") as play_track,
        ):
            player.update(MusicSnapshot(), 1.0)

        play_track.assert_called_once_with(calm_track, fade_ms=450)

    def test_player_keeps_combat_track_until_minimum_runtime_before_calm(self) -> None:
        player = DoomMusicPlayer()
        player.enabled = True
        player.using_file_music = True
        current_track = MusicTrack(path=Path("at dooms gate.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        player._tracks = [
            MusicTrack(path=Path("The_Imp_s_Song.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock()),
            current_track,
        ]
        player._current_track = current_track
        player._session_time = 8.0
        player._current_track_started_at = 0.0

        with mock.patch.object(player._logic, "update", return_value=STATE_EXPLORATION):
            player.update(MusicSnapshot(), 0.2)

        self.assertEqual(current_track, player._current_track)

    def test_quick_return_resumes_recent_track_without_restarting(self) -> None:
        player = DoomMusicPlayer()
        player.enabled = True
        player.using_file_music = True
        combat_track = MusicTrack(path=Path("at dooms gate.mp3"), mood=STATE_COMBAT, sound=mock.Mock())
        calm_track = MusicTrack(path=Path("The_Imp_s_Song.mp3"), mood=STATE_EXPLORATION, sound=mock.Mock())
        current_channel = mock.Mock()
        current_channel.get_busy.return_value = True
        suspended_channel = mock.Mock()
        suspended_channel.get_busy.return_value = True
        player._file_music_channels = (current_channel, suspended_channel)
        player._channel_track = {0: calm_track, 1: combat_track}
        player._channel_suspended_until = {0: 0.0, 1: 12.0}
        player._current_music_channel_index = 0
        player._current_track = calm_track
        player._session_time = 6.0

        resumed = player._play_file_track(combat_track, fade_ms=450)

        self.assertTrue(resumed)
        suspended_channel.play.assert_not_called()
        current_channel.set_volume.assert_called_with(0.0)
        self.assertEqual(combat_track, player._current_track)
        self.assertEqual(1.0, player._channel_target_volume[1])
        self.assertEqual(0.0, player._channel_target_volume[0])

    def test_same_mood_can_retarget_to_better_energy_match(self) -> None:
        player = DoomMusicPlayer()
        player.enabled = True
        player.using_file_music = True
        lower_combat = MusicTrack(path=Path("combat_low.mp3"), mood=STATE_COMBAT, sound=mock.Mock(), energy=0.42)
        higher_combat = MusicTrack(path=Path("combat_high.mp3"), mood=STATE_COMBAT, sound=mock.Mock(), energy=0.74)
        player._tracks = [lower_combat, higher_combat]
        player._current_track = lower_combat
        player._session_time = 20.0
        player._current_track_started_at = 0.0
        player._logic.intensity = 0.74

        with (
            mock.patch.object(player._logic, "update", return_value=STATE_COMBAT),
            mock.patch.object(player, "_play_file_track") as play_track,
        ):
            player.update(MusicSnapshot(recent_shots=1.0), 0.5)

        play_track.assert_called_once_with(higher_combat, fade_ms=450)


if __name__ == "__main__":
    unittest.main()
