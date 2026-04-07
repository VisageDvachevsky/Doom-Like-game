from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
import random

import pygame


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

MOOD_CALM = "calm"
MOOD_COMBAT = "combat"
MOOD_FRENZY = "frenzy"
MOOD_ORDER = (MOOD_CALM, MOOD_COMBAT, MOOD_FRENZY)


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
    projectile_count: int = 0
    movement: float = 0.0
    recent_shots: float = 0.0
    recent_damage: float = 0.0
    recent_kills: float = 0.0


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
        self.current_mood = MOOD_CALM
        self._hold_timer = 0.0

    @staticmethod
    def classify_track(path: Path) -> str:
        name = path.stem.casefold()
        if "rip" in name or "tear" in name:
            return MOOD_FRENZY
        if "at dooms gate" in name or "doom's gate" in name or "dooms gate" in name:
            return MOOD_FRENZY
        if "main theme" in name:
            return MOOD_COMBAT
        if "imp" in name:
            return MOOD_CALM
        return MOOD_COMBAT

    @staticmethod
    def compute_target_intensity(snapshot: MusicSnapshot) -> float:
        active_pressure = _clamp(snapshot.active_enemies / 8.0, 0.0, 1.0)
        nearby_pressure = _clamp(snapshot.nearby_enemies / 4.0, 0.0, 1.0)
        attack_pressure = _clamp(snapshot.attacking_enemies / 3.0, 0.0, 1.0)
        projectile_pressure = _clamp(snapshot.projectile_count / 4.0, 0.0, 1.0)
        motion_pressure = _clamp(snapshot.movement, 0.0, 1.0)
        shots_pressure = _clamp(snapshot.recent_shots, 0.0, 1.0)
        damage_pressure = _clamp(snapshot.recent_damage, 0.0, 1.0)
        kill_pressure = _clamp(snapshot.recent_kills, 0.0, 1.0)
        intensity = (
            active_pressure * 0.15
            + nearby_pressure * 0.20
            + attack_pressure * 0.21
            + projectile_pressure * 0.12
            + motion_pressure * 0.08
            + shots_pressure * 0.12
            + damage_pressure * 0.08
            + kill_pressure * 0.04
        )
        return _clamp(intensity, 0.0, 1.0)

    def update(self, snapshot: MusicSnapshot, delta_time: float, available_moods: set[str]) -> str:
        target = self.compute_target_intensity(snapshot)
        blend = 1.0 - math.exp(-max(0.0, delta_time) * 1.65)
        self.intensity += (target - self.intensity) * blend
        self._hold_timer = max(0.0, self._hold_timer - delta_time)

        desired_mood = self._mood_from_intensity(self.intensity)
        desired_mood = self._closest_available_mood(desired_mood, available_moods)
        if desired_mood != self.current_mood and (
            self._is_escalation(desired_mood, self.current_mood) or self._hold_timer <= 0.0
        ):
            self.current_mood = desired_mood
            self._hold_timer = 7.5
        return self.current_mood

    def _mood_from_intensity(self, intensity: float) -> str:
        if self.current_mood == MOOD_FRENZY:
            if intensity >= 0.62:
                return MOOD_FRENZY
        elif intensity >= 0.74:
            return MOOD_FRENZY

        if self.current_mood == MOOD_COMBAT:
            if intensity >= 0.22:
                return MOOD_COMBAT
        elif intensity >= 0.34:
            return MOOD_COMBAT

        return MOOD_CALM

    def _closest_available_mood(self, desired_mood: str, available_moods: set[str]) -> str:
        if desired_mood in available_moods:
            return desired_mood
        desired_index = MOOD_ORDER.index(desired_mood)
        for distance in range(1, len(MOOD_ORDER)):
            lower = desired_index - distance
            upper = desired_index + distance
            if lower >= 0 and MOOD_ORDER[lower] in available_moods:
                return MOOD_ORDER[lower]
            if upper < len(MOOD_ORDER) and MOOD_ORDER[upper] in available_moods:
                return MOOD_ORDER[upper]
        return MOOD_CALM

    def _is_escalation(self, desired_mood: str, current_mood: str) -> bool:
        return MOOD_ORDER.index(desired_mood) > MOOD_ORDER.index(current_mood)


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

    def start(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=self.channels, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        except pygame.error:
            self.enabled = False
            return

        self._background_enabled = self._start_background_bed()
        overlay_tracks = [track for track in self._tracks if track.mood != MOOD_CALM]
        if overlay_tracks:
            self._prepare_file_music_channels()
            self._tracks = self._preload_tracks(overlay_tracks)
            if self._background_enabled or self._tracks:
                self.enabled = True
                self.using_file_music = True
                return

        try:
            self._sound = pygame.mixer.Sound(buffer=self._render_loop())
        except pygame.error:
            self.enabled = False
            return

        self._music_channel = pygame.mixer.Channel(0)
        self._music_channel.set_volume(0.42)
        self._music_channel.play(self._sound, loops=-1)
        self.enabled = True
        self.using_file_music = False

    def stop(self) -> None:
        if self.using_file_music:
            for channel in self._file_music_channels or ():
                channel.stop()
            pygame.mixer.music.stop()
            self.enabled = False
            return
        if self._music_channel is not None:
            self._music_channel.stop()
        self.enabled = False

    def update(self, snapshot: MusicSnapshot, delta_time: float) -> None:
        if not self.enabled or not self.using_file_music or not self._tracks:
            return
        mood = self._logic.update(snapshot, delta_time, self._available_moods())
        if mood == MOOD_CALM:
            self._fade_out_overlay(fade_ms=1800)
            return
        if self._current_track is not None and self._current_track.mood == mood:
            return
        track = self._select_track_for_mood(mood)
        if track is None or track == self._current_track:
            return
        self._play_file_track(track, fade_ms=1800)

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
        music_markers = ("doom", "ost", "theme", "song", "gate", "rip", "tear", "music")
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
            pygame.mixer.music.set_volume(0.24)
            pygame.mixer.music.play(-1, fade_ms=1600)
        except pygame.error:
            return False
        return True

    def _available_moods(self) -> set[str]:
        moods = {track.mood for track in self._tracks}
        if self._background_enabled:
            moods.add(MOOD_CALM)
        return moods

    def _select_track_for_mood(self, mood: str) -> MusicTrack | None:
        matching = [track for track in self._tracks if track.mood == mood]
        if not matching:
            return None
        if len(matching) == 1:
            return matching[0]
        current_path = self._current_track.path if self._current_track is not None else None
        alternatives = [track for track in matching if track.path != current_path]
        pool = alternatives or matching
        return self._rng.choice(pool)

    def _play_file_track(self, track: MusicTrack, fade_ms: int = 0) -> bool:
        if track.sound is None:
            return False
        self._prepare_file_music_channels()
        if self._file_music_channels is None:
            return False
        next_index = self._current_music_channel_index
        previous_index = 1 - next_index
        next_channel = self._file_music_channels[next_index]
        previous_channel = self._file_music_channels[previous_index]
        try:
            next_channel.set_volume(0.42)
            next_channel.play(track.sound, loops=-1, fade_ms=fade_ms)
            if previous_channel.get_busy():
                previous_channel.fadeout(max(fade_ms, 250))
        except pygame.error:
            return False
        self._current_music_channel_index = previous_index
        self._current_track = track
        return True

    def _fade_out_overlay(self, fade_ms: int) -> None:
        if self._current_track is None:
            return
        for channel in self._file_music_channels or ():
            if channel.get_busy():
                channel.fadeout(fade_ms)
        self._current_track = None

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
