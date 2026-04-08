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
    vel_x: float = 0.0
    vel_y: float = 0.0
    vertical_velocity: float = 0.0
    jump_offset: float = 0.0
    grounded: bool = True

    @property
    def radius(self) -> float:
        return settings.PLAYER_RADIUS

    @property
    def planar_speed(self) -> float:
        return math.hypot(self.vel_x, self.vel_y)

    @property
    def speed_ratio(self) -> float:
        return min(1.0, self.planar_speed / max(0.001, settings.MOVE_SPEED))

    @property
    def view_z(self) -> float:
        return self.z + self.jump_offset

    def rotate_by(self, delta_angle: float) -> None:
        self.angle = (self.angle + delta_angle) % (math.tau)

    def rotate(self, direction: float, delta_time: float) -> None:
        self.rotate_by(direction * settings.TURN_SPEED * delta_time)

    def jump(self, world: World) -> bool:
        floor_z = float(world.get_local_floor_height(self.x, self.y, settings.PLAYER_RADIUS))
        if not self.grounded or self.jump_offset > 0.01 or self.z > floor_z + 0.01:
            return False
        ceiling_z = float(world.get_local_ceiling_height(self.x, self.y, settings.PLAYER_RADIUS))
        if ceiling_z - floor_z <= settings.PLAYER_HEIGHT + 0.04:
            return False
        self.vertical_velocity = settings.PLAYER_JUMP_IMPULSE
        self.grounded = False
        return True

    def move(self, forward: float, strafe: float, world: World, delta_time: float) -> None:
        sin_a = math.sin(self.angle)
        cos_a = math.cos(self.angle)
        wish_x = cos_a * forward - sin_a * strafe
        wish_y = sin_a * forward + cos_a * strafe
        wish_length = math.hypot(wish_x, wish_y)
        if wish_length > 1.0:
            wish_x /= wish_length
            wish_y /= wish_length

        control = 1.0 if self.grounded else settings.PLAYER_AIR_CONTROL
        response = min(1.0, delta_time * settings.PLAYER_INPUT_RESPONSE * control)
        target_vel_x = wish_x * settings.MOVE_SPEED
        target_vel_y = wish_y * settings.MOVE_SPEED
        max_delta = settings.PLAYER_ACCELERATION * delta_time * control
        delta_vel_x = (target_vel_x - self.vel_x) * response
        delta_vel_y = (target_vel_y - self.vel_y) * response
        self.vel_x += max(-max_delta, min(max_delta, delta_vel_x))
        self.vel_y += max(-max_delta, min(max_delta, delta_vel_y))

        if wish_length <= 0.001 and self.grounded:
            friction = max(0.0, 1.0 - delta_time * settings.PLAYER_FRICTION)
            self.vel_x *= friction
            self.vel_y *= friction

        planar_speed = self.planar_speed
        if planar_speed > settings.MOVE_SPEED:
            limit = settings.MOVE_SPEED / planar_speed
            self.vel_x *= limit
            self.vel_y *= limit

        if abs(self.vel_x) < 0.0001:
            self.vel_x = 0.0
        if abs(self.vel_y) < 0.0001:
            self.vel_y = 0.0

        self._try_move(world, self.vel_x * delta_time, 0.0)
        self._try_move(world, 0.0, self.vel_y * delta_time)

    def _try_move(self, world: World, dx: float, dy: float) -> None:
        new_x = self.x + dx
        new_y = self.y + dy

        if not self._collides(world, new_x, self.y):
            self.x = new_x
        elif dx:
            self.vel_x = 0.0
        if not self._collides(world, self.x, new_y):
            self.y = new_y
        elif dy:
            self.vel_y = 0.0

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
        floor_z = float(world.get_local_floor_height(self.x, self.y, settings.PLAYER_RADIUS))
        ceiling_z = float(world.get_local_ceiling_height(self.x, self.y, settings.PLAYER_RADIUS))
        if abs(floor_z - self.z) < 0.001:
            self.z = floor_z
        else:
            blend = min(1.0, delta_time * settings.ELEVATION_SMOOTH_SPEED)
            self.z += (floor_z - self.z) * blend

        max_jump_offset = max(0.0, ceiling_z - floor_z - settings.PLAYER_HEIGHT)

        if self.grounded and self.jump_offset <= 0.001 and self.vertical_velocity <= 0.0:
            self.jump_offset = 0.0
            self.vertical_velocity = 0.0
            return

        self.vertical_velocity -= settings.PLAYER_GRAVITY * delta_time
        self.jump_offset += self.vertical_velocity * delta_time

        if self.jump_offset >= max_jump_offset:
            self.jump_offset = max_jump_offset
            self.vertical_velocity = min(0.0, self.vertical_velocity)

        if self.jump_offset <= 0.0:
            self.jump_offset = 0.0
            self.vertical_velocity = 0.0
            self.grounded = True
            return

        self.grounded = False
