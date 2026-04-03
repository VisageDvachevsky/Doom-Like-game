from __future__ import annotations

from dataclasses import dataclass
import math

from doomgame import settings
from doomgame.world import World


@dataclass
class Player:
    x: float
    y: float
    angle: float = 0.0
    z: float = 0.0

    @property
    def radius(self) -> float:
        return settings.PLAYER_RADIUS

    def rotate_by(self, delta_angle: float) -> None:
        self.angle = (self.angle + delta_angle) % (math.tau)

    def rotate(self, direction: float, delta_time: float) -> None:
        self.rotate_by(direction * settings.TURN_SPEED * delta_time)

    def move(self, forward: float, strafe: float, world: World, delta_time: float) -> None:
        if not forward and not strafe:
            return

        move_step = settings.MOVE_SPEED * delta_time
        sin_a = math.sin(self.angle)
        cos_a = math.cos(self.angle)
        dx = (cos_a * forward - sin_a * strafe) * move_step
        dy = (sin_a * forward + cos_a * strafe) * move_step

        self._try_move(world, dx, 0.0)
        self._try_move(world, 0.0, dy)

    def _try_move(self, world: World, dx: float, dy: float) -> None:
        new_x = self.x + dx
        new_y = self.y + dy

        if not self._collides(world, new_x, self.y):
            self.x = new_x
        if not self._collides(world, self.x, new_y):
            self.y = new_y

    def _collides(self, world: World, x: float, y: float) -> bool:
        radius = settings.PLAYER_RADIUS
        points = (
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x - radius, y + radius),
            (x + radius, y + radius),
        )
        if any(world.is_blocked(px, py) for px, py in points):
            return True

        current_floor = world.get_local_floor_height(self.x, self.y, radius)
        target_floor = world.get_local_floor_height(x, y, radius)
        return abs(target_floor - current_floor) > settings.MAX_STEP_HEIGHT

    def update_elevation(self, world: World, delta_time: float) -> None:
        target = world.get_local_floor_height(self.x, self.y, settings.PLAYER_RADIUS)
        if abs(target - self.z) < 0.001:
            self.z = float(target)
            return

        blend = min(1.0, delta_time * settings.ELEVATION_SMOOTH_SPEED)
        self.z += (target - self.z) * blend
