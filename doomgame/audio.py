from __future__ import annotations

from array import array
import math
import random

import pygame


class DoomAudio:
    def __init__(self) -> None:
        self.sample_rate = 22050
        self.enabled = False
        self.channels: dict[str, pygame.mixer.Channel] = {}
        self.sounds: dict[str, pygame.mixer.Sound] = {}

    def start(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=2, buffer=512)
        except pygame.error:
            self.enabled = False
            return

        self.channels = {
            "weapon": pygame.mixer.Channel(1),
            "ui": pygame.mixer.Channel(2),
            "world": pygame.mixer.Channel(3),
            "enemy": pygame.mixer.Channel(4),
        }
        self.sounds = {
            "shotgun_fire": pygame.mixer.Sound(buffer=self._render_shotgun_fire()),
            "empty_click": pygame.mixer.Sound(buffer=self._render_empty_click()),
            "pickup": pygame.mixer.Sound(buffer=self._render_pickup_ping()),
            "key_pickup": pygame.mixer.Sound(buffer=self._render_key_pickup_ping()),
            "door_open": pygame.mixer.Sound(buffer=self._render_door_open()),
            "door_locked": pygame.mixer.Sound(buffer=self._render_door_locked()),
            "enemy_alert": pygame.mixer.Sound(buffer=self._render_enemy_alert()),
            "enemy_melee": pygame.mixer.Sound(buffer=self._render_enemy_melee()),
            "enemy_ranged": pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "enemy_pain": pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "enemy_death": pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "enemy_hit": pygame.mixer.Sound(buffer=self._render_enemy_hit()),
        }
        self.channels["weapon"].set_volume(0.66)
        self.channels["ui"].set_volume(0.40)
        self.channels["world"].set_volume(0.48)
        self.channels["enemy"].set_volume(0.44)
        self.enabled = True

    def stop(self) -> None:
        for channel in self.channels.values():
            channel.stop()
        self.enabled = False

    def play_shotgun_fire(self) -> None:
        if self.enabled:
            self.channels["weapon"].play(self.sounds["shotgun_fire"])

    def play_empty_click(self) -> None:
        if self.enabled:
            self.channels["weapon"].play(self.sounds["empty_click"])

    def play_pickup(self) -> None:
        if self.enabled:
            self.channels["ui"].play(self.sounds["pickup"])

    def play_key_pickup(self) -> None:
        if self.enabled:
            self.channels["ui"].play(self.sounds["key_pickup"])

    def play_door_open(self) -> None:
        if self.enabled:
            self.channels["world"].play(self.sounds["door_open"])

    def play_door_locked(self) -> None:
        if self.enabled:
            self.channels["world"].play(self.sounds["door_locked"])

    def play_enemy_alert(self, enemy_type: str) -> None:
        if self.enabled and not self.channels["enemy"].get_busy():
            self.channels["enemy"].play(self.sounds["enemy_alert"])

    def play_enemy_attack(self, enemy_type: str) -> None:
        if not self.enabled:
            return
        sound_key = "enemy_melee" if enemy_type == "charger" else "enemy_ranged"
        self.channels["enemy"].play(self.sounds[sound_key])

    def play_enemy_attack_hit(self, enemy_type: str) -> None:
        if self.enabled:
            self.channels["enemy"].play(self.sounds["enemy_hit"])

    def play_enemy_pain(self, enemy_type: str) -> None:
        if self.enabled:
            self.channels["enemy"].play(self.sounds["enemy_pain"])

    def play_enemy_death(self, enemy_type: str) -> None:
        if self.enabled:
            self.channels["enemy"].play(self.sounds["enemy_death"])

    def _render_shotgun_fire(self) -> bytes:
        duration = 0.78
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        rng = random.Random(9001)
        crack_lp = 0.0
        tail_lp = 0.0
        for idx in range(samples):
            t = idx / self.sample_rate
            # Hard attack: mechanical click + muzzle crack.
            mech = math.sin(math.tau * 1820.0 * t) * math.exp(-t * 75.0) * 0.16
            crack_noise = (rng.random() * 2.0 - 1.0) * math.exp(-t * 42.0) * 0.95
            crack_lp = crack_lp * 0.70 + crack_noise * 0.30

            # Low-end body with short downward sweep for the thump.
            boom_freq = 124.0 - 56.0 * min(1.0, t * 4.8)
            boom = math.sin(math.tau * boom_freq * t) * math.exp(-t * 12.0) * 0.78
            chest = math.sin(math.tau * 72.0 * t) * math.exp(-t * 7.0) * 0.54

            # Mid bark keeps it aggressive and less “sine-wave”.
            bark = math.sin(math.tau * 246.0 * t) * math.exp(-t * 18.0) * 0.24
            bark += math.sin(math.tau * 332.0 * t) * math.exp(-t * 16.0) * 0.15

            # Room tail: darker noise burst plus light ring.
            tail_noise = (rng.random() * 2.0 - 1.0) * math.exp(-max(0.0, t - 0.028) * 7.4) * (0.20 if t > 0.028 else 0.0)
            tail_lp = tail_lp * 0.94 + tail_noise * 0.06
            ring = math.sin(math.tau * 186.0 * t) * math.exp(-max(0.0, t - 0.035) * 6.2) * (0.11 if t > 0.035 else 0.0)

            transient = mech + crack_lp * 0.52
            body = boom + chest + bark
            tail = tail_lp + ring

            signal = math.tanh((transient + body + tail) * 2.05)

            # Slight stereo widening without turning it into a sci-fi effect.
            left = signal * (0.97 + 0.03 * math.sin(t * 7.0))
            right = signal * (0.93 + 0.07 * math.cos(t * 6.0))
            pcm.append(int(max(-1.0, min(1.0, left)) * 32767))
            pcm.append(int(max(-1.0, min(1.0, right)) * 32767))
        return pcm.tobytes()

    def _render_empty_click(self) -> bytes:
        duration = 0.16
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            hit = math.sin(math.tau * 1600.0 * t) * math.exp(-t * 44.0) * 0.28
            body = math.sin(math.tau * 620.0 * t) * math.exp(-t * 28.0) * 0.16
            ring = math.sin(math.tau * 310.0 * t) * math.exp(-t * 18.0) * 0.11
            sample = math.tanh((hit + body + ring) * 1.8)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_pickup_ping(self) -> bytes:
        duration = 0.22
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            env = math.exp(-t * 14.0)
            tone_a = math.sin(math.tau * 880.0 * t) * env * 0.18
            tone_b = math.sin(math.tau * 1320.0 * t) * math.exp(-t * 18.0) * 0.11
            sample = math.tanh((tone_a + tone_b) * 1.4)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_key_pickup_ping(self) -> bytes:
        duration = 0.32
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            env = math.exp(-t * 8.5)
            tone_a = math.sin(math.tau * 740.0 * t) * env * 0.16
            tone_b = math.sin(math.tau * 1110.0 * t) * math.exp(-t * 10.5) * 0.15
            tone_c = math.sin(math.tau * 1480.0 * t) * math.exp(-t * 14.0) * 0.08
            sample = math.tanh((tone_a + tone_b + tone_c) * 1.55)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_door_open(self) -> bytes:
        duration = 0.56
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        rng = random.Random(1204)
        low_pass = 0.0
        for idx in range(samples):
            t = idx / self.sample_rate
            servo = math.sin(math.tau * (82.0 + 18.0 * t) * t) * math.exp(-t * 1.9) * 0.32
            rumble = math.sin(math.tau * 48.0 * t) * math.exp(-t * 2.8) * 0.24
            grit = (rng.random() * 2.0 - 1.0) * math.exp(-t * 4.2) * 0.11
            low_pass = low_pass * 0.89 + grit * 0.11
            sample = math.tanh((servo + rumble + low_pass) * 1.85)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_door_locked(self) -> bytes:
        duration = 0.24
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            thunk = math.sin(math.tau * 196.0 * t) * math.exp(-t * 12.0) * 0.28
            buzz = math.sin(math.tau * 840.0 * t) * math.exp(-t * 22.0) * 0.18
            sample = math.tanh((thunk + buzz) * 1.9)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_alert(self) -> bytes:
        duration = 0.34
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            tone = math.sin(math.tau * (260.0 + 170.0 * t) * t) * math.exp(-t * 6.2) * 0.26
            rasp = math.sin(math.tau * 92.0 * t) * math.exp(-t * 3.0) * 0.18
            sample = math.tanh((tone + rasp) * 2.2)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_melee(self) -> bytes:
        duration = 0.28
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            whoosh = math.sin(math.tau * 180.0 * t) * math.exp(-t * 8.0) * 0.24
            snap = math.sin(math.tau * 680.0 * t) * math.exp(-t * 18.0) * 0.16
            sample = math.tanh((whoosh + snap) * 1.8)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_ranged(self) -> bytes:
        duration = 0.32
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            charge = math.sin(math.tau * (420.0 - 80.0 * t) * t) * math.exp(-t * 5.5) * 0.19
            crack = math.sin(math.tau * 1240.0 * t) * math.exp(-t * 16.0) * 0.18
            boom = math.sin(math.tau * 140.0 * t) * math.exp(-t * 7.0) * 0.18
            sample = math.tanh((charge + crack + boom) * 1.95)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_pain(self) -> bytes:
        duration = 0.18
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            bark = math.sin(math.tau * 360.0 * t) * math.exp(-t * 15.0) * 0.24
            rasp = math.sin(math.tau * 920.0 * t) * math.exp(-t * 22.0) * 0.12
            sample = math.tanh((bark + rasp) * 2.0)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_death(self) -> bytes:
        duration = 0.42
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            fall = math.sin(math.tau * (220.0 - 70.0 * t) * t) * math.exp(-t * 5.0) * 0.26
            low = math.sin(math.tau * 74.0 * t) * math.exp(-t * 6.2) * 0.22
            sample = math.tanh((fall + low) * 2.0)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()

    def _render_enemy_hit(self) -> bytes:
        duration = 0.14
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        for idx in range(samples):
            t = idx / self.sample_rate
            smack = math.sin(math.tau * 540.0 * t) * math.exp(-t * 24.0) * 0.2
            low = math.sin(math.tau * 110.0 * t) * math.exp(-t * 18.0) * 0.16
            sample = math.tanh((smack + low) * 2.2)
            pcm.append(int(sample * 32767))
            pcm.append(int(sample * 32767))
        return pcm.tobytes()
