from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
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


@dataclass(frozen=True)
class NoteEvent:
    start_beat: float
    duration_beats: float
    note: str
    velocity: float = 1.0
    pan: float = 0.0


class DoomMusicPlayer:
    def __init__(self) -> None:
        self.sample_rate = 22050
        self.channels = 2
        self.bpm = 148
        self.seconds_per_beat = 60.0 / self.bpm
        self._sound: pygame.mixer.Sound | None = None
        self._music_channel: pygame.mixer.Channel | None = None
        self.enabled = False

    def start(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=self.channels, buffer=512)
        except pygame.error:
            self.enabled = False
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

    def stop(self) -> None:
        if self._music_channel is not None:
            self._music_channel.stop()
        self.enabled = False

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
        # Based on the riff the user gave, expanded into a loop with small phrase variations.
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
        for idx in range(length):
            t = idx / self.sample_rate
            phase += frequency / self.sample_rate
            base = math.sin(math.tau * phase)
            octave = math.sin(math.tau * phase * 2.0) * 0.42
            bite = math.sin(math.tau * phase * 3.0) * 0.18
            envelope = self._adsr(t, duration, 0.004, 0.08, 0.72, 0.18)
            palm = 0.70 + 0.30 * math.exp(-t * 18.0)
            distorted = math.tanh((base * 0.95 + octave + bite) * 2.8) * palm
            samples.append(distorted * envelope * velocity * 0.54)
        return samples

    def _lead_sample(self, frequency: float, duration: float, velocity: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        for idx in range(length):
            t = idx / self.sample_rate
            vibrato = math.sin(math.tau * 5.4 * t) * 0.004
            phase = math.tau * frequency * (t + vibrato)
            body = math.sin(phase) * 0.62
            bell = math.sin(phase * 2.0) * 0.22
            sparkle = math.sin(phase * 3.0) * 0.10
            envelope = self._adsr(t, duration, 0.006, 0.18, 0.22, 0.16)
            samples.append((body + bell + sparkle) * envelope * velocity * 0.38)
        return samples

    def _bass_sample(self, frequency: float, duration: float, velocity: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        for idx in range(length):
            t = idx / self.sample_rate
            phase = math.tau * frequency * t
            fundamental = math.sin(phase)
            growl = math.sin(phase * 0.5) * 0.18
            squareish = math.tanh(fundamental * 1.8) * 0.44
            envelope = self._adsr(t, duration, 0.003, 0.07, 0.78, 0.10)
            samples.append((fundamental * 0.7 + squareish + growl) * envelope * velocity * 0.46)
        return samples

    def _kick_sample(self, duration: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        samples: list[float] = []
        for idx in range(length):
            t = idx / self.sample_rate
            sweep = 98.0 * math.exp(-t * 9.0) + 34.0
            phase = math.tau * sweep * t
            envelope = math.exp(-t * 11.5)
            click = math.exp(-t * 45.0) * 0.22
            samples.append((math.sin(phase) * envelope + click) * 0.78)
        return samples

    def _snare_sample(self, duration: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        rng = random.Random(404)
        samples: list[float] = []
        for idx in range(length):
            t = idx / self.sample_rate
            noise = (rng.random() * 2.0 - 1.0)
            body = math.sin(math.tau * 192.0 * t) * math.exp(-t * 16.0) * 0.22
            envelope = math.exp(-t * 19.0)
            samples.append((noise * envelope * 0.52 + body) * 0.58)
        return samples

    def _hat_sample(self, duration: float) -> list[float]:
        length = max(1, int(duration * self.sample_rate))
        rng = random.Random(808)
        last = 0.0
        samples: list[float] = []
        for idx in range(length):
            t = idx / self.sample_rate
            noise = rng.random() * 2.0 - 1.0
            high = noise - last * 0.82
            last = noise
            envelope = math.exp(-t * 52.0)
            samples.append(high * envelope * 0.26)
        return samples

    def _note_frequency(self, note: str) -> float:
        name = note[:-1]
        octave = int(note[-1])
        midi = (octave + 1) * 12 + NOTE_INDEX[name]
        return 440.0 * (2.0 ** ((midi - 69) / 12.0))

    def _adsr(
        self,
        time_position: float,
        duration: float,
        attack: float,
        decay: float,
        sustain_level: float,
        release: float,
    ) -> float:
        release_start = max(0.0, duration - release)
        if time_position < attack:
            return time_position / max(attack, 0.0001)
        if time_position < attack + decay:
            decay_progress = (time_position - attack) / max(decay, 0.0001)
            return 1.0 + (sustain_level - 1.0) * decay_progress
        if time_position < release_start:
            return sustain_level
        release_progress = (time_position - release_start) / max(release, 0.0001)
        return sustain_level * max(0.0, 1.0 - release_progress)

    def _soft_clip(self, value: float) -> float:
        return math.tanh(value * 1.35)
