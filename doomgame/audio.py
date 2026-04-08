from __future__ import annotations

from array import array
import math
from pathlib import Path
import random

import pygame


WEAPON_CHANNEL_VOLUME = 1.0
UI_CHANNEL_VOLUME = 1.0
WORLD_CHANNEL_VOLUME = 1.0
ENEMY_CHANNEL_VOLUME = 1.0


class DoomAudio:
    def __init__(self) -> None:
        self.sample_rate = 22050
        self.enabled = False
        self.channels: dict[str, pygame.mixer.Channel] = {}
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self._last_played_at: dict[str, float] = {}

    def start(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        except pygame.error:
            self.enabled = False
            return

        self.channels = {
            "weapon": pygame.mixer.Channel(1),
            "ui": pygame.mixer.Channel(2),
            "world": pygame.mixer.Channel(3),
            "enemy": pygame.mixer.Channel(4),
        }
        pistol_fire = self._load_asset_sound("dspistol (2).wav")
        shotgun_fire = self._load_asset_sound("dsshotgn (2).wav")
        sawedoff_fire = self._load_asset_sound("dsdshtgn.wav")
        chaingun_fire = self._load_asset_sound("dspistol (1).wav")
        normal_door_open = self._load_asset_sound("dsbdopn.wav")
        locked_door_open = self._load_asset_sound("dsdoropn.wav")
        item_pickup = self._load_asset_sound("dsitemup.wav")
        level_exit = self._load_asset_sound("dstelept.wav")
        charger_attack = self._load_asset_sound("dsfirsht.wav")
        grunt_attack = self._load_asset_sound("dsshotgn (3).wav")
        heavy_attack = self._load_asset_sound("dsrlaunc.wav")
        cacodemon_attack = self._load_asset_sound("dsfirshtcaco.wav")
        cyberdemon_attack = self._load_asset_sound("dsrlaunc (1).wav")
        warden_attack = self._load_asset_sound("dsmanatk.wav")
        charger_death = self._load_asset_sound("dsbgdth1.wav")
        grunt_death = self._load_asset_sound("dsskedth.wav")
        heavy_death = self._load_asset_sound("dscybdth.wav")
        cacodemon_death = self._load_asset_sound("dscacdth.wav")
        cyberdemon_death = self._load_asset_sound("dsslop.wav")
        warden_death = self._load_asset_sound("dsmandth.wav")
        charger_pain = self._load_asset_sound("dspopain.wav")
        grunt_pain = self._load_asset_sound("dchopain.wav")
        heavy_pain = self._load_asset_sound("dsdmpain.wav")
        cacodemon_pain = self._load_asset_sound("dsdmpain.wav")
        cyberdemon_pain = self._load_asset_sound("dspopain.wav")
        warden_pain = self._load_asset_sound("dsbospn.wav")
        cacodemon_alert = self._load_asset_sound("dsdmact.wav")
        cyberdemon_alert = self._load_asset_sound("dscybsit.wav")
        cyberdemon_step = self._load_asset_sound("dshoof.wav")
        player_pain = self._load_asset_sound("dsplpain.wav")
        player_oof = self._load_asset_sound("dsoof.wav")
        player_death = self._load_asset_sound("dspldeth.wav")
        self.sounds = {
            "pistol_fire": pistol_fire if pistol_fire is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "shotgun_fire": shotgun_fire if shotgun_fire is not None else pygame.mixer.Sound(buffer=self._render_shotgun_fire()),
            "sawedoff_fire": sawedoff_fire if sawedoff_fire is not None else shotgun_fire if shotgun_fire is not None else pygame.mixer.Sound(buffer=self._render_shotgun_fire()),
            "chaingun_fire": chaingun_fire if chaingun_fire is not None else shotgun_fire if shotgun_fire is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "empty_click": pygame.mixer.Sound(buffer=self._render_empty_click()),
            "pickup": item_pickup if item_pickup is not None else pygame.mixer.Sound(buffer=self._render_pickup_ping()),
            "key_pickup": pygame.mixer.Sound(buffer=self._render_key_pickup_ping()),
            "level_exit": level_exit if level_exit is not None else pygame.mixer.Sound(buffer=self._render_key_pickup_ping()),
            "door_open": normal_door_open if normal_door_open is not None else pygame.mixer.Sound(buffer=self._render_door_open()),
            "door_open_locked": locked_door_open if locked_door_open is not None else pygame.mixer.Sound(buffer=self._render_door_open()),
            "door_locked": pygame.mixer.Sound(buffer=self._render_door_locked()),
            "enemy_melee": pygame.mixer.Sound(buffer=self._render_enemy_melee()),
            "enemy_ranged": pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "enemy_death": pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "charger_attack": charger_attack if charger_attack is not None else pygame.mixer.Sound(buffer=self._render_enemy_melee()),
            "grunt_attack": grunt_attack if grunt_attack is not None else pygame.mixer.Sound(buffer=self._render_grunt_attack()),
            "heavy_attack": heavy_attack if heavy_attack is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "cacodemon_attack": cacodemon_attack if cacodemon_attack is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "cyberdemon_attack": cyberdemon_attack if cyberdemon_attack is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "warden_attack": warden_attack if warden_attack is not None else pygame.mixer.Sound(buffer=self._render_enemy_ranged()),
            "charger_death": charger_death if charger_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "grunt_death": grunt_death if grunt_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "heavy_death": heavy_death if heavy_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "cacodemon_death": cacodemon_death if cacodemon_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "cyberdemon_death": cyberdemon_death if cyberdemon_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "warden_death": warden_death if warden_death is not None else pygame.mixer.Sound(buffer=self._render_enemy_death()),
            "charger_pain": charger_pain if charger_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "grunt_pain": grunt_pain if grunt_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "heavy_pain": heavy_pain if heavy_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "cacodemon_pain": cacodemon_pain if cacodemon_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "cyberdemon_pain": cyberdemon_pain if cyberdemon_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "warden_pain": warden_pain if warden_pain is not None else pygame.mixer.Sound(buffer=self._render_enemy_pain()),
            "cacodemon_alert": cacodemon_alert if cacodemon_alert is not None else pygame.mixer.Sound(buffer=self._render_enemy_alert()),
            "cyberdemon_alert": cyberdemon_alert if cyberdemon_alert is not None else pygame.mixer.Sound(buffer=self._render_enemy_alert()),
            "cyberdemon_step": cyberdemon_step if cyberdemon_step is not None else pygame.mixer.Sound(buffer=self._render_enemy_melee()),
            "player_pain": player_pain,
            "player_oof": player_oof,
            "player_death": player_death,
        }
        for sound in self.sounds.values():
            if sound is not None:
                sound.set_volume(1.0)
        self.channels["weapon"].set_volume(WEAPON_CHANNEL_VOLUME)
        self.channels["ui"].set_volume(UI_CHANNEL_VOLUME)
        self.channels["world"].set_volume(WORLD_CHANNEL_VOLUME)
        self.channels["enemy"].set_volume(ENEMY_CHANNEL_VOLUME)
        self.enabled = True

    def stop(self) -> None:
        for channel in self.channels.values():
            channel.stop()
        self.enabled = False

    def play_pistol_fire(self) -> None:
        self._play_sound("weapon", "pistol_fire", cooldown=0.08, interrupt=True)

    def play_shotgun_fire(self) -> None:
        self._play_sound("weapon", "shotgun_fire", cooldown=0.08, interrupt=True)

    def play_sawedoff_fire(self) -> None:
        self._play_sound("weapon", "sawedoff_fire", cooldown=0.08, interrupt=True)

    def play_chaingun_fire(self) -> None:
        self._play_sound("weapon", "chaingun_fire", cooldown=0.03, interrupt=True)

    def play_empty_click(self) -> None:
        self._play_sound("weapon", "empty_click", cooldown=0.05, interrupt=True)

    def play_pickup(self) -> None:
        self._play_sound("ui", "pickup", cooldown=0.05)

    def play_key_pickup(self) -> None:
        self._play_sound("ui", "key_pickup", cooldown=0.12)

    def play_level_exit(self) -> None:
        self._play_sound("ui", "level_exit", cooldown=0.4, interrupt=True)

    def play_door_open(self, door_type: str = "normal") -> None:
        sound_key = "door_open_locked" if door_type in {"blue_locked", "yellow_locked", "red_locked"} else "door_open"
        self._play_sound("world", sound_key, cooldown=0.22)

    def play_door_locked(self) -> None:
        self._play_sound("world", "door_locked", cooldown=0.14)

    def play_enemy_alert(self, enemy_type: str) -> None:
        sound_key = {
            "cacodemon": "cacodemon_alert",
            "cyberdemon": "cyberdemon_alert",
        }.get(enemy_type)
        if sound_key is None:
            return
        self._play_sound("enemy", sound_key, cooldown=0.8)

    def play_enemy_attack(self, enemy_type: str) -> None:
        if not self.enabled:
            return
        sound_key = {
            "charger": "charger_attack",
            "grunt": "grunt_attack",
            "heavy": "heavy_attack",
            "cacodemon": "cacodemon_attack",
            "cyberdemon": "cyberdemon_attack",
            "warden": "warden_attack",
        }.get(enemy_type)
        if sound_key is None:
            sound_key = "enemy_melee" if enemy_type == "charger" else "enemy_ranged"
        self._play_sound("enemy", sound_key, cooldown=0.28)

    def play_enemy_attack_hit(self, enemy_type: str) -> None:
        return

    def play_enemy_pain(self, enemy_type: str) -> None:
        sound_key = {
            "charger": "charger_pain",
            "grunt": "grunt_pain",
            "heavy": "heavy_pain",
            "cacodemon": "cacodemon_pain",
            "cyberdemon": "cyberdemon_pain",
            "warden": "warden_pain",
        }.get(enemy_type)
        if sound_key is None:
            return
        self._play_sound("enemy", sound_key, cooldown=0.16)

    def play_enemy_death(self, enemy_type: str) -> None:
        sound_key = {
            "charger": "charger_death",
            "grunt": "grunt_death",
            "heavy": "heavy_death",
            "cacodemon": "cacodemon_death",
            "cyberdemon": "cyberdemon_death",
            "warden": "warden_death",
        }.get(enemy_type, "enemy_death")
        self._play_sound("enemy", sound_key, cooldown=0.12)

    def play_enemy_step(self, enemy_type: str) -> None:
        sound_key = {
            "cyberdemon": "cyberdemon_step",
        }.get(enemy_type)
        if sound_key is None:
            return
        self._play_sound("enemy", sound_key, cooldown=0.32)

    def play_player_hit(self) -> None:
        if not self.enabled:
            return
        choices = []
        if self.sounds.get("player_pain") is not None:
            choices.append(self.sounds["player_pain"])
        if self.sounds.get("player_oof") is not None:
            choices.append(self.sounds["player_oof"])
        if not choices:
            return
        sound = random.choice(choices)
        sound_key = "player_pain" if sound is self.sounds.get("player_pain") else "player_oof"
        self._play_sound("ui", sound_key, cooldown=0.22)

    def play_player_death(self) -> None:
        if not self.enabled:
            return
        sound = self.sounds.get("player_death")
        if sound is None:
            return
        self._play_sound("ui", "player_death", cooldown=0.3, interrupt=True)

    def _play_sound(
        self,
        channel_key: str,
        sound_key: str,
        cooldown: float = 0.0,
        interrupt: bool = False,
    ) -> None:
        if not self.enabled:
            return
        channel = self.channels.get(channel_key)
        sound = self.sounds.get(sound_key)
        if channel is None or sound is None:
            return
        now = pygame.time.get_ticks() * 0.001
        last_played = self._last_played_at.get(sound_key, -10.0)
        if now - last_played < cooldown:
            return
        if channel.get_busy():
            if not interrupt:
                return
            channel.stop()
        channel.play(sound)
        self._last_played_at[sound_key] = now

    def _load_asset_sound(self, asset_name: str) -> pygame.mixer.Sound | None:
        asset_path = Path(__file__).resolve().parent.parent / "assets" / asset_name
        if not asset_path.exists():
            return None
        try:
            return pygame.mixer.Sound(str(asset_path))
        except pygame.error:
            return None

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

    def _render_grunt_attack(self) -> bytes:
        duration = 0.19
        samples = int(duration * self.sample_rate)
        pcm = array("h")
        rng = random.Random(31337)
        noise_lp = 0.0
        for idx in range(samples):
            t = idx / self.sample_rate
            snap = math.sin(math.tau * 1480.0 * t) * math.exp(-t * 24.0) * 0.18
            pop = math.sin(math.tau * 760.0 * t) * math.exp(-t * 18.0) * 0.13
            ring = math.sin(math.tau * 420.0 * t) * math.exp(-t * 11.0) * 0.08
            noise = (rng.random() * 2.0 - 1.0) * math.exp(-t * 30.0) * 0.10
            noise_lp = noise_lp * 0.58 + noise * 0.42
            sample = math.tanh((snap + pop + ring + noise_lp) * 2.1)
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
