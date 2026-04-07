from __future__ import annotations

import unittest
from unittest import mock

from doomgame.audio import DoomAudio


class DoomAudioTests(unittest.TestCase):
    def test_busy_enemy_channel_does_not_restart_same_sound(self) -> None:
        audio = DoomAudio()
        audio.enabled = True
        enemy_channel = mock.Mock()
        enemy_channel.get_busy.return_value = True
        audio.channels = {"enemy": enemy_channel}
        audio.sounds = {"grunt_attack": mock.Mock()}

        with mock.patch("doomgame.audio.pygame.time.get_ticks", return_value=1000):
            audio.play_enemy_attack("grunt")

        enemy_channel.stop.assert_not_called()
        enemy_channel.play.assert_not_called()

    def test_weapon_channel_can_interrupt_for_new_shot(self) -> None:
        audio = DoomAudio()
        audio.enabled = True
        weapon_channel = mock.Mock()
        weapon_channel.get_busy.return_value = True
        audio.channels = {"weapon": weapon_channel}
        audio.sounds = {"shotgun_fire": mock.Mock()}
        audio._last_played_at["shotgun_fire"] = 0.0

        with mock.patch("doomgame.audio.pygame.time.get_ticks", return_value=100):
            audio.play_shotgun_fire()

        weapon_channel.stop.assert_called_once()
        weapon_channel.play.assert_called_once_with(audio.sounds["shotgun_fire"])

    def test_enemy_pain_uses_type_specific_sound(self) -> None:
        audio = DoomAudio()
        audio.enabled = True
        enemy_channel = mock.Mock()
        enemy_channel.get_busy.return_value = False
        audio.channels = {"enemy": enemy_channel}
        grunt_pain = mock.Mock()
        audio.sounds = {"grunt_pain": grunt_pain}

        with mock.patch("doomgame.audio.pygame.time.get_ticks", return_value=1000):
            audio.play_enemy_pain("grunt")

        enemy_channel.play.assert_called_once_with(grunt_pain)


if __name__ == "__main__":
    unittest.main()
