from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
import random

import pygame


MUSIC_TRACK_VOLUME = 1.0
SYNTH_LOOP_VOLUME = 1.0
BACKGROUND_BED_VOLUME = 0.7


NOTE_INDEX = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

STATE_EXPLORATION = "exploration"
STATE_THREAT = "threat"
STATE_COMBAT = "combat"
STATE_CLIMAX = "climax"
STATE_AFTERMATH = "aftermath"

# Backward-compatible aliases used by tests and existing code.
MOOD_CALM = STATE_EXPLORATION
MOOD_COMBAT = STATE_COMBAT
MOOD_FRENZY = STATE_CLIMAX
MOOD_ORDER = (STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX, STATE_AFTERMATH)
STATE_URGENCY = {
    STATE_EXPLORATION: 0.0,
    STATE_AFTERMATH: 0.5,
    STATE_THREAT: 1.0,
    STATE_COMBAT: 2.0,
    STATE_CLIMAX: 3.0,
}
MIN_TRACK_TIME_BY_MOOD = {
    STATE_EXPLORATION: 6.0,
    STATE_THREAT: 10.0,
    STATE_COMBAT: 20.0,
    STATE_CLIMAX: 26.0,
    STATE_AFTERMATH: 12.0,
}
MIN_ESCALATION_TIME = 6.0
TRACK_RESUME_WINDOW = 8.0
PHASE_FALLBACKS = {
    STATE_EXPLORATION: (STATE_EXPLORATION, STATE_AFTERMATH, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX),
    STATE_THREAT: (STATE_THREAT, STATE_COMBAT, STATE_EXPLORATION, STATE_AFTERMATH, STATE_CLIMAX),
    STATE_COMBAT: (STATE_COMBAT, STATE_THREAT, STATE_CLIMAX, STATE_AFTERMATH, STATE_EXPLORATION),
    STATE_CLIMAX: (STATE_CLIMAX, STATE_COMBAT, STATE_THREAT, STATE_AFTERMATH, STATE_EXPLORATION),
    STATE_AFTERMATH: (STATE_AFTERMATH, STATE_EXPLORATION, STATE_THREAT, STATE_COMBAT, STATE_CLIMAX),
}


@dataclass(frozen=True)
class NoteEvent:
    start_beat: float
    duration_beats: float
    note: str
    velocity: float = 1.0
    pan: float = 0.0


@dataclass(frozen=True)
class MusicSnapshot:
    active_enemies: int = 0
    nearby_enemies: int = 0
    attacking_enemies: int = 0
    active_threat: float = 0.0
    nearby_threat: float = 0.0
    attacking_threat: float = 0.0
    projectile_count: int = 0
    movement: float = 0.0
    recent_shots: float = 0.0
    recent_damage: float = 0.0
    recent_kills: float = 0.0
    player_health_ratio: float = 1.0


@dataclass(frozen=True)
class MusicTrack:
    path: Path
    mood: str
    sound: pygame.mixer.Sound | None = None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class AdaptiveMusicLogic:
    def __init__(self) -> None:
        self.intensity = 0.0
        self.tension = 0.0
        self.pressure = 0.0
        self.momentum = 0.0
        self.recovery = 1.0
        self.combat_memory = 0.0
        self.current_mood = STATE_EXPLORATION
        self._hold_timer = 0.0
        self._climax_tail = 0.0

    @staticmethod
    def classify_track(path: Path) -> str:
        name = path.stem.casefold()
        if "bfg division" in name:
            return STATE_CLIMAX
        if "rip" in name or "tear" in name:
            return STATE_CLIMAX
        if "cultist base" in name:
            return STATE_COMBAT
        if "at dooms gate" in name or "doom's gate" in name or "dooms gate" in name:
            return STATE_COMBAT
        if "faust" in name:
            return STATE_THREAT
        if "main theme" in name or "main_theme" in name:
            return STATE_THREAT
        if "ride to the base" in name:
            return STATE_EXPLORATION
        if "imp" in name:
            return STATE_EXPLORATION
        return STATE_COMBAT

    @staticmethod
    def compute_target_intensity(snapshot: MusicSnapshot) -> float:
        active_pressure = max(
            _clamp(snapshot.active_enemies / 8.0, 0.0, 1.0),
            _clamp(snapshot.active_threat / 9.5, 0.0, 1.0),
        )
        nearby_pressure = max(
            _clamp(snapshot.nearby_enemies / 4.0, 0.0, 1.0),
            _clamp(snapshot.nearby_threat / 5.2, 0.0, 1.0),
        )
        attack_pressure = max(
            _clamp(snapshot.attacking_enemies / 3.0, 0.0, 1.0),
            _clamp(snapshot.attacking_threat / 4.6, 0.0, 1.0),
        )
        projectile_pressure = _clamp(snapshot.projectile_count / 3.0, 0.0, 1.0)
        motion_pressure = _clamp(snapshot.movement, 0.0, 1.0)
        shots_pressure = _clamp(snapshot.recent_shots, 0.0, 1.0)
        damage_pressure = _clamp(snapshot.recent_damage, 0.0, 1.0)
        kill_pressure = _clamp(snapshot.recent_kills, 0.0, 1.0)
        low_health_pressure = _clamp(1.0 - snapshot.player_health_ratio, 0.0, 1.0)
        intensity = (
            active_pressure * 0.14
            + nearby_pressure * 0.27
            + attack_pressure * 0.22
            + projectile_pressure * 0.14
            + motion_pressure * 0.04
            + shots_pressure * 0.10
            + damage_pressure * 0.05
            + kill_pressure * 0.06
            + low_health_pressure * 0.08
        )
        return _clamp(intensity, 0.0, 1.0)

    def update(self, snapshot: MusicSnapshot, delta_time: float, available_moods: set[str]) -> str:
        targets = self._compute_targets(snapshot)
        self.tension = self._approach(self.tension, targets["tension"], delta_time, up=3.0, down=1.0)
        self.pressure = self._approach(self.pressure, targets["pressure"], delta_time, up=4.4, down=1.3)
        self.momentum = self._approach(self.momentum, targets["momentum"], delta_time, up=3.8, down=0.62)
        self.recovery = self._approach(self.recovery, targets["recovery"], delta_time, up=1.8, down=5.2)
        self.intensity = self._approach(self.intensity, self.compute_target_intensity(snapshot), delta_time, up=3.5, down=0.9)
        combat_anchor = max(self.tension * 0.92, self.pressure, self.momentum * 0.95)
        self.combat_memory = self._approach(
            self.combat_memory,
            combat_anchor,
            delta_time,
            up=2.8,
            down=0.26,
        )
        self._climax_tail = max(0.0, self._climax_tail - delta_time)
        if combat_anchor >= 0.84 or (self.pressure >= 0.72 and self.momentum >= 0.54):
            self._climax_tail = max(self._climax_tail, 10.0)
        self._hold_timer = max(0.0, self._hold_timer - delta_time)

        desired_mood = self._phase_from_scores(snapshot)
        desired_mood = self._closest_available_mood(desired_mood, available_moods)
        if desired_mood != self.current_mood and (
            self._is_escalation(desired_mood, self.current_mood) or self._hold_timer <= 0.0
        ):
            self.current_mood = desired_mood
            self._hold_timer = 4.5 if desired_mood in {STATE_THREAT, STATE_AFTERMATH} else 6.0
        return self.current_mood

    def _compute_targets(self, snapshot: MusicSnapshot) -> dict[str, float]:
        proximity = max(
            _clamp(snapshot.nearby_enemies / 4.5, 0.0, 1.0),
            _clamp(snapshot.nearby_threat / 6.0, 0.0, 1.0),
        )
        awareness = max(
            _clamp(snapshot.active_enemies / 7.5, 0.0, 1.0),
            _clamp(snapshot.active_threat / 9.0, 0.0, 1.0),
        )
        attack_lane = max(
            _clamp(snapshot.attacking_enemies / 3.0, 0.0, 1.0),
            _clamp(snapshot.attacking_threat / 5.0, 0.0, 1.0),
        )
        projectile_density = _clamp(snapshot.projectile_count / 3.5, 0.0, 1.0)
        low_health = _clamp(1.0 - snapshot.player_health_ratio, 0.0, 1.0)
        tension_target = _clamp(
            awareness * 0.34
            + proximity * 0.38
            + attack_lane * 0.18
            + projectile_density * 0.10,
            0.0,
            1.0,
        )
        pressure_target = _clamp(
            attack_lane * 0.38
            + projectile_density * 0.24
            + snapshot.recent_damage * 0.22
            + proximity * 0.08
            + low_health * 0.08,
            0.0,
            1.0,
        )
        momentum_target = _clamp(
            snapshot.recent_shots * 0.38
            + snapshot.recent_kills * 0.28
            + snapshot.movement * 0.08
            + attack_lane * 0.12
            + projectile_density * 0.06
            + snapshot.recent_damage * 0.08,
            0.0,
            1.0,
        )
        recovery_target = 1.0 if max(tension_target, pressure_target, momentum_target) < 0.18 else 0.0
        return {
            "tension": tension_target,
            "pressure": pressure_target,
            "momentum": momentum_target,
            "recovery": recovery_target,
        }

    def _phase_from_scores(self, snapshot: MusicSnapshot) -> str:
        if (
            self._climax_tail > 0.0
            and max(self.pressure, self.momentum, self.combat_memory) >= 0.42
        ) or (
            self.pressure >= 0.76
            or (self.momentum >= 0.84 and self.tension >= 0.64)
            or (snapshot.nearby_threat >= 5.4 and snapshot.projectile_count >= 2)
        ):
            return STATE_CLIMAX
        if (
            self.tension >= 0.40
            or self.pressure >= 0.30
            or self.momentum >= 0.40
            or self.combat_memory >= 0.62
        ):
            return STATE_COMBAT
        if (
            self.combat_memory >= 0.22
            and self.tension < 0.18
            and self.pressure < 0.16
            and self.momentum < 0.20
        ):
            return STATE_AFTERMATH
        if (
            self.tension >= 0.14
            or snapshot.active_enemies > 0
            or snapshot.active_threat >= 0.8
        ):
            return STATE_THREAT
        return STATE_EXPLORATION

    def _approach(self, current: float, target: float, delta_time: float, up: float, down: float) -> float:
        rate = up if target > current else down
        blend = 1.0 - math.exp(-max(0.0, delta_time) * rate)
        return current + (target - current) * blend

    def _closest_available_mood(self, desired_mood: str, available_moods: set[str]) -> str:
        for candidate in PHASE_FALLBACKS.get(desired_mood, (desired_mood,)):
            if candidate in available_moods:
                return candidate
        return STATE_EXPLORATION

    def _is_escalation(self, desired_mood: str, current_mood: str) -> bool:
        return STATE_URGENCY.get(desired_mood, 0.0) > STATE_URGENCY.get(current_mood, 0.0)


class DoomMusicPlayer:
    def __init__(self) -> None:
        self.sample_rate = 22050
        self.channels = 2
        self.bpm = 148
        self.seconds_per_beat = 60.0 / self.bpm
        self._sound: pygame.mixer.Sound | None = None
        self._music_channel: pygame.mixer.Channel | None = None
        self._tracks = self._find_external_tracks()
        self._logic = AdaptiveMusicLogic()
        self._current_track: MusicTrack | None = None
        self._current_music_channel_index = 0
        self._rng = random.Random(666)
        self.enabled = False
        self.using_file_music = False
        self._file_music_channels: tuple[pygame.mixer.Channel, pygame.mixer.Channel] | None = None
        self._background_track: Path | None = self._find_background_track()
        self._background_enabled = False
        self._background_volume = 0.0
        self._session_time = 0.0
        self._current_track_started_at = 0.0
        self._track_last_started_at: dict[Path, float] = {}
        self._channel_track: dict[int, MusicTrack | None] = {0: None, 1: None}
        self._channel_suspended_until: dict[int, float] = {0: 0.0, 1: 0.0}

    def start(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=self.channels, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        except pygame.error:
            self.enabled = False
            return

        preloaded_tracks = self._preload_tracks(self._tracks)
        if preloaded_tracks:
            self._prepare_file_music_channels()
            self._tracks = preloaded_tracks
            self._background_enabled = False
            self.enabled = True
            self.using_file_music = True
            return

        self._background_enabled = self._start_background_bed()
        if self._background_enabled:
            self.enabled = True
            self.using_file_music = True
            return

        try:
            self._sound = pygame.mixer.Sound(buffer=self._render_loop())
        except pygame.error:
            self.enabled = False
            return

        self._music_channel = pygame.mixer.Channel(0)
        self._music_channel.set_volume(SYNTH_LOOP_VOLUME)
        self._music_channel.play(self._sound, loops=-1)
        self.enabled = True
        self.using_file_music = False

    def stop(self) -> None:
        if self.using_file_music:
            for channel in self._file_music_channels or ():
                channel.stop()
            if self._background_enabled:
                pygame.mixer.music.stop()
            self.enabled = False
            return
        if self._music_channel is not None:
            self._music_channel.stop()
        self.enabled = False

    def update(self, snapshot: MusicSnapshot, delta_time: float) -> None:
        self._session_time += max(0.0, delta_time)
        if not self.enabled or not self.using_file_music or not self._tracks:
            return
        self._cleanup_suspended_channels()
        mood = self._logic.update(snapshot, delta_time, self._available_moods())
        if self._current_track is not None and self._current_track.mood == mood:
            return
        if self._current_track is not None and not self._can_switch_to_mood(mood):
            return
        track = self._select_track_for_mood(mood, self._logic.intensity)
        if track is None or track == self._current_track:
            return
        self._play_file_track(track, fade_ms=450)

    def _find_external_tracks(self) -> list[MusicTrack]:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        candidates: list[Path] = []
        for ext in ("*.mp3", "*.ogg", "*.flac"):
            candidates.extend(sorted(assets_dir.glob(ext)))

        tracks: list[MusicTrack] = []
        for path in candidates:
            if not self._is_music_asset(path):
                continue
            tracks.append(MusicTrack(path=path, mood=AdaptiveMusicLogic.classify_track(path)))
        return tracks

    def _is_music_asset(self, path: Path) -> bool:
        name = path.stem.casefold()
        if name.startswith("ds"):
            return False
        music_markers = (
            "doom",
            "ost",
            "theme",
            "song",
            "gate",
            "rip",
            "tear",
            "music",
            "bfg",
            "faust",
            "cultist",
            "ride to the base",
        )
        return any(marker in name for marker in music_markers)

    def _find_background_track(self) -> Path | None:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        preferred = assets_dir / "d_e2m6.mid"
        return preferred if preferred.exists() else None

    def _preload_tracks(self, tracks: list[MusicTrack]) -> list[MusicTrack]:
        loaded_tracks: list[MusicTrack] = []
        for track in tracks:
            try:
                sound = pygame.mixer.Sound(str(track.path))
            except pygame.error:
                continue
            sound.set_volume(1.0)
            loaded_tracks.append(MusicTrack(path=track.path, mood=track.mood, sound=sound))
        return loaded_tracks

    def _prepare_file_music_channels(self) -> None:
        if self._file_music_channels is not None:
            return
        primary = pygame.mixer.Channel(0)
        secondary = pygame.mixer.Channel(5)
        primary.set_volume(0.0)
        secondary.set_volume(0.0)
        self._file_music_channels = (primary, secondary)

    def _start_background_bed(self) -> bool:
        if self._background_track is None:
            return False
        try:
            pygame.mixer.music.load(str(self._background_track))
            self._background_volume = BACKGROUND_BED_VOLUME
            pygame.mixer.music.set_volume(self._background_volume)
            pygame.mixer.music.play(-1, fade_ms=800)
        except pygame.error:
            return False
        return True

    def _available_moods(self) -> set[str]:
        return {track.mood for track in self._tracks}

    def _select_track_for_mood(self, mood: str, intensity: float) -> MusicTrack | None:
        matching = [track for track in self._tracks if track.mood == mood]
        if not matching:
            return None
        if len(matching) == 1:
            return matching[0]
        current_path = self._current_track.path if self._current_track is not None else None
        alternatives = [track for track in matching if track.path != current_path]
        pool = alternatives or matching
        best_score = None
        best_track = None
        for track in pool:
            energy_delta = abs(self._track_energy(track) - intensity)
            last_started = self._track_last_started_at.get(track.path, -9999.0)
            recency_penalty = max(0.0, 12.0 - (self._session_time - last_started)) * 0.05
            score = energy_delta + recency_penalty
            if best_score is None or score < best_score:
                best_score = score
                best_track = track
        return best_track

    def _track_energy(self, track: MusicTrack) -> float:
        name = track.path.stem.casefold()
        if "bfg division" in name:
            return 0.98
        if "at dooms gate" in name or "doom's gate" in name or "dooms gate" in name:
            return 0.66
        if "rip" in name and "tear" in name:
            return 0.92
        if "cultist base" in name:
            return 0.56
        if "faust" in name:
            return 0.24
        if "main theme" in name:
            return 0.36
        if "ride to the base" in name:
            return 0.14
        if "imp" in name:
            return 0.08
        return {
            STATE_EXPLORATION: 0.10,
            STATE_THREAT: 0.28,
            STATE_COMBAT: 0.58,
            STATE_CLIMAX: 0.88,
            STATE_AFTERMATH: 0.18,
        }.get(track.mood, 0.5)

    def _play_file_track(self, track: MusicTrack, fade_ms: int = 0) -> bool:
        if track.sound is None:
            return False
        self._prepare_file_music_channels()
        if self._file_music_channels is None:
            return False
        resumed_index = self._find_channel_index_for_track(track)
        if resumed_index is not None:
            return self._resume_existing_track(track, resumed_index, fade_ms)
        next_index = self._next_channel_index_for_new_track()
        previous_index = self._current_music_channel_index
        next_channel = self._file_music_channels[next_index]
        previous_channel = self._file_music_channels[previous_index]
        try:
            next_channel.set_volume(MUSIC_TRACK_VOLUME)
            next_channel.play(track.sound, loops=-1, fade_ms=fade_ms)
            if next_index != previous_index and previous_channel.get_busy():
                previous_channel.set_volume(0.0)
                self._channel_suspended_until[previous_index] = self._session_time + TRACK_RESUME_WINDOW
        except pygame.error:
            return False
        self._current_music_channel_index = next_index
        self._current_track = track
        self._current_track_started_at = self._session_time
        self._track_last_started_at[track.path] = self._session_time
        self._channel_track[next_index] = track
        return True

    def _fade_out_overlay(self, fade_ms: int) -> None:
        if self._current_track is None:
            return
        for channel in self._file_music_channels or ():
            if channel.get_busy():
                channel.fadeout(fade_ms)
        self._current_track = None

    def _cleanup_suspended_channels(self) -> None:
        if self._file_music_channels is None:
            return
        for index, channel in enumerate(self._file_music_channels):
            if index == self._current_music_channel_index:
                continue
            if self._channel_track.get(index) is None:
                continue
            if self._channel_suspended_until.get(index, 0.0) > self._session_time:
                continue
            if channel.get_busy():
                channel.stop()
            self._channel_track[index] = None
            self._channel_suspended_until[index] = 0.0

    def _find_channel_index_for_track(self, track: MusicTrack) -> int | None:
        if self._file_music_channels is None:
            return None
        for index, channel_track in self._channel_track.items():
            if channel_track is None or channel_track.path != track.path:
                continue
            if self._channel_suspended_until.get(index, 0.0) < self._session_time:
                continue
            channel = self._file_music_channels[index]
            if channel.get_busy():
                return index
        return None

    def _resume_existing_track(self, track: MusicTrack, channel_index: int, fade_ms: int) -> bool:
        if self._file_music_channels is None:
            return False
        resume_channel = self._file_music_channels[channel_index]
        previous_index = self._current_music_channel_index
        previous_channel = self._file_music_channels[previous_index]
        try:
            resume_channel.set_volume(MUSIC_TRACK_VOLUME)
            if previous_index != channel_index and previous_channel.get_busy():
                previous_channel.set_volume(0.0)
                self._channel_suspended_until[previous_index] = self._session_time + TRACK_RESUME_WINDOW
        except pygame.error:
            return False
        self._current_music_channel_index = channel_index
        self._current_track = track
        self._current_track_started_at = self._session_time
        self._track_last_started_at[track.path] = self._session_time
        self._channel_suspended_until[channel_index] = 0.0
        return True

    def _next_channel_index_for_new_track(self) -> int:
        if self._file_music_channels is None:
            return 0
        inactive_index = 1 - self._current_music_channel_index
        if self._channel_track.get(inactive_index) is None:
            return inactive_index
        if self._channel_suspended_until.get(inactive_index, 0.0) <= self._session_time:
            return inactive_index
        current_track = self._channel_track.get(self._current_music_channel_index)
        if current_track is None:
            return self._current_music_channel_index
        current_mood = current_track.mood
        current_hold = MIN_TRACK_TIME_BY_MOOD.get(current_mood, 10.0)
        elapsed = self._session_time - self._current_track_started_at
        if elapsed >= current_hold:
            return inactive_index
        return self._current_music_channel_index

    def _can_switch_to_mood(self, desired_mood: str) -> bool:
        if self._current_track is None:
            return True
        current_mood = self._current_track.mood
        elapsed = self._session_time - self._current_track_started_at
        current_urgency = STATE_URGENCY.get(current_mood, 0.0)
        desired_urgency = STATE_URGENCY.get(desired_mood, 0.0)
        if desired_urgency > current_urgency:
            return elapsed >= MIN_ESCALATION_TIME or self._logic.intensity >= 0.9
        if desired_mood == STATE_AFTERMATH and current_mood in {STATE_COMBAT, STATE_CLIMAX}:
            return elapsed >= max(10.0, MIN_TRACK_TIME_BY_MOOD.get(current_mood, 10.0) * 0.7)
        return elapsed >= MIN_TRACK_TIME_BY_MOOD.get(current_mood, 10.0)

    def _render_loop(self) -> bytes:
        total_beats = 32.0
        total_samples = int(total_beats * self.seconds_per_beat * self.sample_rate)
        left = [0.0] * total_samples
        right = [0.0] * total_samples

        for event in self._build_guitar_events(total_beats):
            self._mix_event(left, right, event, self._guitar_sample)
        for event in self._build_melody_events(total_beats):
            self._mix_event(left, right, event, self._lead_sample)
        for event in self._build_bass_events(total_beats):
            self._mix_event(left, right, event, self._bass_sample)

        self._mix_drums(left, right, total_beats)
        self._mix_room_tone(left, right)

        pcm = array("h")
        for idx in range(total_samples):
            l = self._soft_clip(left[idx] * 0.92)
            r = self._soft_clip(right[idx] * 0.92)
            pcm.append(int(max(-1.0, min(1.0, l)) * 32767))
            pcm.append(int(max(-1.0, min(1.0, r)) * 32767))
        return pcm.tobytes()

    def _build_guitar_events(self, total_beats: float) -> list[NoteEvent]:
        phrase_a = [
            ("E2", 0.0, 0.50, 1.00),
            ("E2", 0.5, 0.50, 0.98),
            ("G2", 1.0, 0.50, 0.98),
            ("E2", 1.5, 0.50, 1.00),
            ("A2", 2.0, 0.50, 1.00),
            ("E2", 2.5, 0.50, 0.98),
            ("Bb2", 3.0, 0.50, 1.00),
            ("A2", 3.5, 0.50, 0.98),
            ("G2", 4.0, 1.00, 1.00),
        ]
        phrase_b = [
            ("E2", 0.0, 0.50, 1.00),
            ("E2", 0.5, 0.50, 0.98),
            ("G2", 1.0, 0.50, 1.00),
            ("E2", 1.5, 0.50, 1.00),
            ("A2", 2.0, 0.50, 1.00),
            ("E2", 2.5, 0.50, 0.98),
            ("Bb2", 3.0, 0.25, 0.96),
            ("A2", 3.25, 0.25, 0.94),
            ("G2", 3.5, 0.50, 0.98),
            ("A2", 4.0, 0.50, 0.98),
            ("G2", 4.5, 0.50, 0.96),
        ]
        phrase_c = [
            ("E2", 0.0, 0.50, 1.00),
            ("E2", 0.5, 0.50, 0.98),
            ("G2", 1.0, 0.50, 1.00),
            ("E2", 1.5, 0.50, 0.98),
            ("A2", 2.0, 0.50, 1.00),
            ("Bb2", 2.5, 0.50, 1.00),
            ("B2", 3.0, 0.50, 0.98),
            ("Bb2", 3.5, 0.50, 1.00),
            ("A2", 4.0, 1.00, 0.98),
        ]
        phrases = [phrase_a, phrase_a, phrase_b, phrase_a, phrase_a, phrase_b, phrase_c, phrase_b]
        events: list[NoteEvent] = []
        beat_cursor = 0.0
        for phrase in phrases:
            for note, start, duration, velocity in phrase:
                events.append(NoteEvent(beat_cursor + start, duration, note, velocity, pan=-0.18))
            beat_cursor += 4.0
            if beat_cursor >= total_beats:
                break
        return events

    def _build_melody_events(self, total_beats: float) -> list[NoteEvent]:
        motif = ["E4", "E4", "G4", "E4", "A4", "E4", "Bb4", "A4", "G4"]
        durations = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0]
        response = ["G4", "A4", "Bb4", "A4", "G4", "E4", "D4", "E4"]
        response_durations = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0]

        events: list[NoteEvent] = []
        for block in range(int(total_beats // 8)):
            start = block * 8.0
            beat = start
            for note, duration in zip(motif, durations):
                events.append(NoteEvent(beat, duration, note, 0.50, pan=0.14))
                beat += duration
            beat = start + 4.0
            phrase = response if block % 2 else motif
            phrase_durations = response_durations if block % 2 else durations
            for note, duration in zip(phrase, phrase_durations):
                events.append(NoteEvent(beat, duration, note, 0.46, pan=0.18))
                beat += duration
        return events

    def _build_bass_events(self, total_beats: float) -> list[NoteEvent]:
        bar_pattern = ["E1", "E1", "C2", "E1", "D2", "E1", "Eb2", "E1"]
        events: list[NoteEvent] = []
        for bar in range(int(total_beats // 4)):
            start = bar * 4.0
            for index, note in enumerate(bar_pattern):
                events.append(NoteEvent(start + index * 0.5, 0.46, note, 0.62, pan=0.02))
        return events

    def _mix_event(
        self,
        left: list[float],
        right: list[float],
        event: NoteEvent,
        synth,
    ) -> None:
        start_index = int(event.start_beat * self.seconds_per_beat * self.sample_rate)
        duration_seconds = event.duration_beats * self.seconds_per_beat
        wave = synth(self._note_frequency(event.note), duration_seconds, event.velocity)
        pan_left = 0.5 * (1.0 - event.pan)
        pan_right = 0.5 * (1.0 + event.pan)
        for idx, sample in enumerate(wave):
            target = start_index + idx
            if target >= len(left):
                break
            left[target] += sample * pan_left
            right[target] += sample * pan_right

    def _mix_drums(self, left: list[float], right: list[float], total_beats: float) -> None:
        kick = self._kick_sample(0.34)
        snare = self._snare_sample(0.24)
        hat = self._hat_sample(0.10)

        for beat in [x * 0.5 for x in range(int(total_beats * 2))]:
            step = int(beat * 2) % 8
            if step in (0, 3, 4, 6):
                self._mix_one_shot(left, right, kick, beat, 0.0, 0.88)
            if step in (2, 6):
                self._mix_one_shot(left, right, snare, beat, 0.0, 0.70)
            self._mix_one_shot(left, right, hat, beat, 0.10 if step % 2 == 0 else -0.10, 0.34)

    def _mix_room_tone(self, left: list[float], right: list[float]) -> None:
        rng = random.Random(1337)
        cutoff = 0.0
        for idx in range(len(left)):
            noise = (rng.random() * 2.0 - 1.0) * 0.010
            cutoff = cutoff * 0.992 + noise * 0.008
            left[idx] += cutoff * 0.22
            right[idx] += cutoff * 0.18

    def _mix_one_shot(
        self,
        left: list[float],
        right: list[float],
        wave: list[float],
        start_beat: float,
        pan: float,
        gain: float,
    ) -> None:
        start_index = int(start_beat * self.seconds_per_beat * self.sample_rate)
        pan_left = 0.5 * (1.0 - pan)
        pan_right = 0.5 * (1.0 + pan)
        for idx, sample in enumerate(wave):
            target = start_index + idx
            if target >= len(left):
                break
            shaped = sample * gain
            left[target] += shaped * pan_left
            right[target] += shaped * pan_right

    def _guitar_sample(self, frequency: float, duration: float, velocity: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        phase = 0.0
        detune_phase = 0.0
        for index in range(length):
            t = index / self.sample_rate
            envelope = math.exp(-5.2 * t) * 0.82 + math.exp(-1.8 * t) * 0.18
            tremolo = 1.0 + math.sin(t * 18.0) * 0.08
            sample = (
                math.sin(phase)
                + 0.62 * math.sin(phase * 2.0 + 0.3)
                + 0.25 * math.sin(phase * 3.0)
                + 0.18 * math.sin(detune_phase)
            )
            sample = math.tanh(sample * 1.35) * envelope * velocity * tremolo * 0.44
            samples.append(sample)
            phase += math.tau * frequency / self.sample_rate
            detune_phase += math.tau * (frequency * 1.006) / self.sample_rate
        return samples

    def _lead_sample(self, frequency: float, duration: float, velocity: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        phase = 0.0
        for index in range(length):
            t = index / self.sample_rate
            envelope = math.exp(-4.4 * t)
            vibrato = math.sin(t * 7.5) * 0.014
            phase += math.tau * frequency * (1.0 + vibrato) / self.sample_rate
            sample = (
                math.sin(phase)
                + 0.4 * math.sin(phase * 2.0)
                + 0.18 * math.sin(phase * 4.0 + 0.4)
            )
            sample = math.tanh(sample * 1.18) * envelope * velocity * 0.24
            samples.append(sample)
        return samples

    def _bass_sample(self, frequency: float, duration: float, velocity: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        phase = 0.0
        for index in range(length):
            t = index / self.sample_rate
            envelope = math.exp(-3.2 * t)
            square = 1.0 if math.sin(phase) >= 0.0 else -1.0
            sample = (square * 0.66 + math.sin(phase) * 0.34) * envelope * velocity * 0.26
            samples.append(sample)
            phase += math.tau * frequency / self.sample_rate
        return samples

    def _kick_sample(self, duration: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        phase = 0.0
        for index in range(length):
            t = index / self.sample_rate
            freq = 120.0 - 82.0 * (t / max(duration, 0.001))
            phase += math.tau * max(28.0, freq) / self.sample_rate
            envelope = math.exp(-12.0 * t)
            click = math.exp(-280.0 * t) * 0.5
            sample = math.sin(phase) * envelope * 0.95 + click
            samples.append(sample * 0.58)
        return samples

    def _snare_sample(self, duration: float) -> list[float]:
        rng = random.Random(29)
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        tone_phase = 0.0
        for index in range(length):
            t = index / self.sample_rate
            noise = (rng.random() * 2.0 - 1.0) * math.exp(-18.0 * t)
            tone_phase += math.tau * 220.0 / self.sample_rate
            tone = math.sin(tone_phase) * math.exp(-16.0 * t) * 0.24
            sample = noise * 0.92 + tone
            samples.append(sample * 0.36)
        return samples

    def _hat_sample(self, duration: float) -> list[float]:
        rng = random.Random(7)
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        prev = 0.0
        for index in range(length):
            t = index / self.sample_rate
            noise = (rng.random() * 2.0 - 1.0)
            prev = prev * 0.18 + noise * 0.82
            sample = (noise - prev) * math.exp(-34.0 * t)
            samples.append(sample * 0.16)
        return samples

    def _soft_clip(self, value: float) -> float:
        return math.tanh(value * 1.35)

    def _note_frequency(self, note: str) -> float:
        pitch = note[:-1]
        octave = int(note[-1])
        semitone = NOTE_INDEX[pitch] + (octave + 1) * 12
        return 440.0 * (2.0 ** ((semitone - 69) / 12.0))
