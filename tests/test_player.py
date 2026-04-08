from __future__ import annotations

import unittest

from doomgame.player import Player


class _OpenWorld:
    def is_blocked(self, x: float, y: float) -> bool:
        return False

    def get_local_floor_height(self, x: float, y: float, radius: float) -> int:
        return 0

    def get_local_ceiling_height(self, x: float, y: float, radius: float) -> int:
        return 2


class _WallWorld(_OpenWorld):
    def is_blocked(self, x: float, y: float) -> bool:
        return x >= 1.0


class PlayerMovementTests(unittest.TestCase):
    def test_velocity_builds_up_and_decays(self) -> None:
        player = Player(0.0, 0.0)
        world = _OpenWorld()

        for _ in range(12):
            player.move(1.0, 0.0, world, 1.0 / 60.0)

        self.assertGreater(player.vel_x, 0.0)
        self.assertGreater(player.x, 0.0)
        speed_while_moving = player.planar_speed

        for _ in range(18):
            player.move(0.0, 0.0, world, 1.0 / 60.0)

        self.assertLess(player.planar_speed, speed_while_moving)
        self.assertAlmostEqual(player.vel_y, 0.0, places=4)

    def test_collision_clears_blocked_velocity_component(self) -> None:
        player = Player(0.95, 0.0, vel_x=3.0)
        world = _WallWorld()

        player.move(1.0, 0.0, world, 1.0 / 60.0)

        self.assertLess(player.x, 1.0)
        self.assertEqual(player.vel_x, 0.0)

    def test_jump_creates_short_hop_and_lands(self) -> None:
        player = Player(0.0, 0.0)
        world = _OpenWorld()

        self.assertTrue(player.jump(world))
        self.assertFalse(player.grounded)
        initial_view_z = player.view_z

        for _ in range(6):
            player.update_elevation(world, 1.0 / 60.0)

        self.assertGreater(player.jump_offset, 0.0)
        self.assertGreater(player.view_z, initial_view_z)

        for _ in range(60):
            player.update_elevation(world, 1.0 / 60.0)

        self.assertTrue(player.grounded)
        self.assertAlmostEqual(player.jump_offset, 0.0, places=4)
        self.assertAlmostEqual(player.z, 0.0, places=4)

    def test_jump_is_blocked_by_low_ceiling(self) -> None:
        class _LowCeilingWorld(_OpenWorld):
            def get_local_ceiling_height(self, x: float, y: float, radius: float) -> int:
                return 0

        player = Player(0.0, 0.0)
        self.assertFalse(player.jump(_LowCeilingWorld()))


if __name__ == "__main__":
    unittest.main()
