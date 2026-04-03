from __future__ import annotations

from dataclasses import dataclass
import math
import random

from doomgame.enemies import EnemyProjectile, EnemySpawn, WorldEnemy, build_enemy_runtime
from doomgame import settings
from doomgame.doors import DoorSpawn, KeyPickup, KeySpawn, WorldDoor
from doomgame.loot import PickupDefinition, get_pickup_definition
from doomgame.mapgen import ExitSpawn, GeneratedMap, LootSpawn


@dataclass
class LootPickup:
    pickup_id: str
    x: float
    y: float
    kind: str
    amount: int
    collected: bool = False
    bob_phase: float = 0.0
    scale: float = 1.0

    @property
    def definition(self) -> PickupDefinition:
        return get_pickup_definition(self.kind)

    @property
    def sprite_kind(self) -> str:
        return self.kind


@dataclass
class HitscanImpact:
    distance: float
    hit_x: float
    hit_y: float
    enemy: WorldEnemy | None = None
    blocked_by_wall: bool = False
    enemy_pain: bool = False
    enemy_killed: bool = False


@dataclass
class World:
    tiles: list[list[int]]
    floor_heights: list[list[int]]
    stair_mask: list[list[int]]
    room_kinds: list[list[int]]
    loot: list[LootPickup]
    enemies: list[WorldEnemy]
    enemy_projectiles: list[EnemyProjectile]
    doors: list[WorldDoor]
    keys: list[KeyPickup]
    exit_zone: "LevelExit | None"
    spawn: tuple[float, float]
    seed: int
    combat_rng: random.Random = None
    noise_position: tuple[float, float] | None = None
    noise_radius: float = 0.0
    noise_timer: float = 0.0

    @classmethod
    def from_generated_map(cls, generated: GeneratedMap) -> "World":
        world = cls(
            tiles=generated.tiles,
            floor_heights=generated.floor_heights,
            stair_mask=generated.stair_mask,
            room_kinds=generated.room_kinds,
            loot=[cls._loot_from_generated(entry) for entry in generated.loot_spawns],
            enemies=[cls._enemy_from_generated(entry) for entry in generated.enemy_spawns],
            enemy_projectiles=[],
            doors=[cls._door_from_generated(entry) for entry in generated.door_spawns],
            keys=[cls._key_from_generated(entry) for entry in generated.key_spawns],
            exit_zone=cls._exit_from_generated(generated.exit_spawn),
            spawn=generated.spawn,
            seed=generated.seed,
        )
        world.combat_rng = random.Random(generated.seed ^ 0xE61F)
        return world

    @staticmethod
    def _loot_from_generated(entry: LootSpawn) -> LootPickup:
        definition = get_pickup_definition(entry.kind)
        return LootPickup(
            pickup_id=entry.pickup_id,
            x=entry.x,
            y=entry.y,
            kind=entry.kind,
            amount=entry.amount,
            bob_phase=((entry.x * 1.73) + (entry.y * 0.91)) % math.tau,
            scale=definition.visual.world_scale,
        )

    @staticmethod
    def _enemy_from_generated(entry: EnemySpawn) -> WorldEnemy:
        return build_enemy_runtime(entry)

    @staticmethod
    def _door_from_generated(entry: DoorSpawn) -> WorldDoor:
        return WorldDoor(
            door_id=entry.door_id,
            grid_x=entry.grid_x,
            grid_y=entry.grid_y,
            orientation=entry.orientation,
            door_type=entry.door_type,
            guard_enemy_id=entry.guard_enemy_id,
        )

    @staticmethod
    def _key_from_generated(entry: KeySpawn) -> KeyPickup:
        key = KeyPickup(
            key_id=entry.key_id,
            key_type=entry.key_type,
            x=entry.x,
            y=entry.y,
        )
        key.bob_phase = ((entry.x * 1.67) + (entry.y * 1.19)) % math.tau
        key.scale = key.definition.visual.world_scale
        return key

    @staticmethod
    def _exit_from_generated(entry: ExitSpawn | None) -> "LevelExit | None":
        if entry is None:
            return None
        return LevelExit(
            exit_id=entry.exit_id,
            x=entry.x,
            y=entry.y,
            required_door_id=entry.required_door_id,
        )

    @property
    def width(self) -> int:
        return len(self.tiles[0])

    @property
    def height(self) -> int:
        return len(self.tiles)

    def update(
        self,
        delta_time: float,
        player=None,
        damage_player=None,
        audio=None,
    ) -> None:
        for door in self.doors:
            door.update(delta_time)
        self.noise_timer = max(0.0, self.noise_timer - delta_time)
        if self.noise_timer <= 0.0:
            self.noise_position = None
            self.noise_radius = 0.0
        if player is None or damage_player is None or audio is None:
            return
        for enemy in self.enemies:
            enemy.update(self, player, delta_time, self.combat_rng, damage_player, audio)
        for projectile in self.enemy_projectiles:
            projectile.update(self, player, delta_time, damage_player, audio)
        self.enemy_projectiles = [projectile for projectile in self.enemy_projectiles if not projectile.removed]
        self.resolve_enemy_separation(player)

    def is_wall(self, grid_x: int, grid_y: int) -> bool:
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return True
        return self.tiles[grid_y][grid_x] == 1

    def is_blocked(self, x: float, y: float, ignore_door_id: str | None = None) -> bool:
        return self.is_wall(int(x), int(y)) or self._door_blocks_point(x, y, ignore_door_id)

    def _door_blocks_point(self, x: float, y: float, ignore_door_id: str | None = None) -> bool:
        grid_x = int(x)
        grid_y = int(y)
        for door in self.doors:
            if door.door_id == ignore_door_id or not door.blocks_passage():
                continue
            if door.grid_x != grid_x or door.grid_y != grid_y:
                continue
            center_x = door.grid_x + 0.5
            center_y = door.grid_y + 0.5
            if door.orientation == "vertical":
                if abs(x - center_x) <= settings.DOOR_THICKNESS and door.grid_y <= y <= door.grid_y + 1.0:
                    return True
            else:
                if abs(y - center_y) <= settings.DOOR_THICKNESS and door.grid_x <= x <= door.grid_x + 1.0:
                    return True
        return False

    def get_floor_height_at(self, grid_x: int, grid_y: int) -> int:
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return 0
        return self.floor_heights[grid_y][grid_x]

    def get_floor_height(self, x: float, y: float) -> int:
        return self.get_floor_height_at(int(x), int(y))

    def get_local_floor_height(self, x: float, y: float, radius: float) -> int:
        points = (
            (x, y),
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x - radius, y + radius),
            (x + radius, y + radius),
        )
        heights = [
            self.get_floor_height(px, py)
            for px, py in points
            if not self.is_blocked(px, py)
        ]
        if not heights:
            return self.get_floor_height(x, y)
        return max(heights)

    def is_stair_at(self, grid_x: int, grid_y: int) -> bool:
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return False
        return self.stair_mask[grid_y][grid_x] != 0

    def active_loot(self) -> list[LootPickup]:
        return [loot for loot in self.loot if not loot.collected]

    def active_keys(self) -> list[KeyPickup]:
        return [key for key in self.keys if not key.collected]

    def active_enemies(self, include_corpses: bool = True) -> list[WorldEnemy]:
        result: list[WorldEnemy] = []
        for enemy in self.enemies:
            if enemy.removed:
                continue
            if include_corpses:
                result.append(enemy)
            elif enemy.alive and not enemy.dead:
                result.append(enemy)
        return result

    def active_enemy_projectiles(self) -> list[EnemyProjectile]:
        return [projectile for projectile in self.enemy_projectiles if not projectile.removed]

    def emit_noise(self, x: float, y: float, radius: float, duration: float) -> None:
        self.noise_position = (x, y)
        self.noise_radius = max(self.noise_radius, radius)
        self.noise_timer = max(self.noise_timer, duration)

    def enemy_can_hear_player(self, enemy: WorldEnemy, player_distance: float) -> bool:
        if self.noise_position is None or self.noise_timer <= 0.0:
            return False
        return player_distance <= self.noise_radius

    def add_loot_drop(self, kind: str, amount: int, x: float, y: float) -> None:
        pickup_id = f"drop-{self.seed}-{len(self.loot):03d}"
        definition = get_pickup_definition(kind)
        self.loot.append(
            LootPickup(
                pickup_id=pickup_id,
                x=x,
                y=y,
                kind=kind,
                amount=amount,
                bob_phase=((x * 1.29) + (y * 0.87)) % math.tau,
                scale=definition.visual.world_scale,
            )
        )

    def spawn_enemy_projectile(self, enemy: WorldEnemy, target_x: float, target_y: float) -> None:
        direction_x = target_x - enemy.x
        direction_y = target_y - enemy.y
        distance = math.hypot(direction_x, direction_y)
        if distance <= 0.0001:
            return
        direction_x /= distance
        direction_y /= distance
        definition = enemy.definition
        spawn_offset = enemy.radius + definition.projectile_radius + 0.08
        projectile = EnemyProjectile(
            projectile_id=f"projectile-{self.seed}-{len(self.enemy_projectiles):03d}",
            owner_id=enemy.enemy_id,
            owner_type=enemy.enemy_type,
            x=enemy.x + direction_x * spawn_offset,
            y=enemy.y + direction_y * spawn_offset,
            dir_x=direction_x,
            dir_y=direction_y,
            speed=definition.projectile_speed,
            damage=definition.damage,
            radius=definition.projectile_radius,
            ttl=settings.ENEMY_PROJECTILE_TIMEOUT,
        )
        self.enemy_projectiles.append(projectile)

    def has_line_of_sight(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        ignore_door_id: str | None = None,
    ) -> bool:
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        distance = math.hypot(delta_x, delta_y)
        if distance <= 0.0001:
            return True

        steps = max(2, int(distance / settings.LOOT_LOS_STEP))
        for index in range(1, steps):
            t = index / steps
            sample_x = start_x + delta_x * t
            sample_y = start_y + delta_y * t
            if self.is_blocked(sample_x, sample_y, ignore_door_id=ignore_door_id):
                return False
        return True

    def trace_ray_distance(
        self,
        start_x: float,
        start_y: float,
        dir_x: float,
        dir_y: float,
        max_distance: float = settings.MAX_RAY_DISTANCE,
        step: float = 0.05,
    ) -> float:
        x = start_x
        y = start_y
        distance = 0.0
        while distance < max_distance:
            x += dir_x * step
            y += dir_y * step
            distance += step
            if self.is_blocked(x, y):
                return distance
        return max_distance

    def resolve_hitscan(
        self,
        start_x: float,
        start_y: float,
        dir_x: float,
        dir_y: float,
        damage: int,
        max_distance: float = settings.MAX_RAY_DISTANCE,
    ) -> HitscanImpact:
        wall_distance = self.trace_ray_distance(start_x, start_y, dir_x, dir_y, max_distance)
        best_enemy: WorldEnemy | None = None
        best_distance = wall_distance

        for enemy in self.active_enemies(include_corpses=False):
            if not enemy.can_take_damage:
                continue
            offset_x = enemy.x - start_x
            offset_y = enemy.y - start_y
            projected = offset_x * dir_x + offset_y * dir_y
            if projected <= 0.0 or projected > best_distance:
                continue
            closest_x = start_x + dir_x * projected
            closest_y = start_y + dir_y * projected
            lateral = math.hypot(enemy.x - closest_x, enemy.y - closest_y)
            if lateral > enemy.radius:
                continue
            entry_distance = max(0.0, projected - math.sqrt(max(0.0, enemy.radius * enemy.radius - lateral * lateral)))
            if entry_distance > best_distance:
                continue
            if not self.has_line_of_sight(start_x, start_y, enemy.x, enemy.y):
                continue
            best_enemy = enemy
            best_distance = entry_distance

        if best_enemy is None:
            hit_x = start_x + dir_x * wall_distance
            hit_y = start_y + dir_y * wall_distance
            return HitscanImpact(distance=wall_distance, hit_x=hit_x, hit_y=hit_y, blocked_by_wall=True)

        impact_x = start_x + dir_x * best_distance
        impact_y = start_y + dir_y * best_distance
        damage_result = best_enemy.take_damage(damage, self.combat_rng)
        if damage_result.drop_kind is not None and damage_result.drop_amount > 0:
            self.add_loot_drop(damage_result.drop_kind, damage_result.drop_amount, best_enemy.x, best_enemy.y)
        return HitscanImpact(
            distance=best_distance,
            hit_x=impact_x,
            hit_y=impact_y,
            enemy=best_enemy,
            blocked_by_wall=False,
            enemy_pain=damage_result.played_pain,
            enemy_killed=damage_result.played_death,
        )

    def move_enemy(self, enemy: WorldEnemy, dx: float, dy: float, player) -> bool:
        moved = False
        target_x = enemy.x + dx
        if self.is_enemy_position_valid(enemy, target_x, enemy.y, player):
            enemy.x = target_x
            moved = True
        target_y = enemy.y + dy
        if self.is_enemy_position_valid(enemy, enemy.x, target_y, player):
            enemy.y = target_y
            moved = True
        return moved

    def is_blocked_circle(self, x: float, y: float, radius: float, ignore_door_id: str | None = None) -> bool:
        points = (
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x - radius, y + radius),
            (x + radius, y + radius),
            (x, y),
            (x - radius, y),
            (x + radius, y),
            (x, y - radius),
            (x, y + radius),
        )
        return any(self.is_blocked(px, py, ignore_door_id=ignore_door_id) for px, py in points)

    def is_enemy_position_valid(self, enemy: WorldEnemy, x: float, y: float, player) -> bool:
        radius = enemy.radius
        if self.is_blocked_circle(x, y, radius):
            return False
        current_floor = self.get_local_floor_height(enemy.x, enemy.y, radius)
        target_floor = self.get_local_floor_height(x, y, radius)
        if abs(target_floor - current_floor) > settings.MAX_STEP_HEIGHT:
            return False
        if math.hypot(x - player.x, y - player.y) < radius + settings.PLAYER_RADIUS + 0.08:
            return False
        for other in self.enemies:
            if other.enemy_id == enemy.enemy_id or not other.blocks_movement:
                continue
            if math.hypot(x - other.x, y - other.y) < radius + other.radius:
                return False
        return True

    def resolve_enemy_separation(self, player) -> None:
        live_enemies = [enemy for enemy in self.enemies if enemy.blocks_movement]
        for index, enemy in enumerate(live_enemies):
            for other in live_enemies[index + 1 :]:
                delta_x = other.x - enemy.x
                delta_y = other.y - enemy.y
                distance = math.hypot(delta_x, delta_y)
                min_distance = enemy.radius + other.radius + 0.04
                if distance <= 0.0001 or distance >= min_distance:
                    continue
                overlap = (min_distance - distance) * 0.5
                normal_x = delta_x / distance
                normal_y = delta_y / distance
                push_x = normal_x * overlap * settings.ENEMY_SEPARATION_PUSH
                push_y = normal_y * overlap * settings.ENEMY_SEPARATION_PUSH
                if self.is_enemy_position_valid(enemy, enemy.x - push_x, enemy.y - push_y, player):
                    enemy.x -= push_x
                    enemy.y -= push_y
                if self.is_enemy_position_valid(other, other.x + push_x, other.y + push_y, player):
                    other.x += push_x
                    other.y += push_y

    def find_interactable_door(self, player_x: float, player_y: float, player_angle: float) -> WorldDoor | None:
        nearest: WorldDoor | None = None
        best_score = float("inf")

        for door in self.doors:
            if door.is_open:
                continue
            center_x, center_y = door.center
            distance = math.hypot(center_x - player_x, center_y - player_y)
            if distance > settings.DOOR_INTERACT_DISTANCE:
                continue
            direction = math.atan2(center_y - player_y, center_x - player_x)
            angle_delta = self._normalize_angle(direction - player_angle)
            if abs(angle_delta) > settings.DOOR_INTERACT_HALF_ANGLE:
                continue
            if not self.has_line_of_sight(player_x, player_y, center_x, center_y, ignore_door_id=door.door_id):
                continue

            score = distance + abs(angle_delta) * 0.45
            if score < best_score:
                best_score = score
                nearest = door

        return nearest

    def interact_with_door(
        self,
        player_x: float,
        player_y: float,
        player_angle: float,
        owned_keys: set[str],
    ) -> tuple[WorldDoor | None, str | None, bool]:
        door = self.find_interactable_door(player_x, player_y, player_angle)
        if door is None:
            return None, None, False
        if door.state in {"opening", "open"}:
            return door, None, False
        if door.guard_enemy_id is not None and not self.is_enemy_defeated(door.guard_enemy_id):
            door.state = "locked"
            return door, "FINAL DOOR LOCKED - WARDEN ALIVE", False
        if not door.can_open(owned_keys, guard_defeated=True):
            door.state = "locked"
            return door, door.definition.visual.locked_message, False
        door.unlock()
        opened = door.begin_open()
        return door, None, opened

    def is_enemy_defeated(self, enemy_id: str) -> bool:
        for enemy in self.enemies:
            if enemy.enemy_id == enemy_id:
                return enemy.dead or enemy.removed
        return True

    def is_exit_active(self) -> bool:
        if self.exit_zone is None:
            return False
        if self.exit_zone.required_door_id is None:
            return True
        for door in self.doors:
            if door.door_id == self.exit_zone.required_door_id:
                return door.is_open
        return False

    def is_player_in_exit(self, player_x: float, player_y: float) -> bool:
        if self.exit_zone is None or not self.is_exit_active():
            return False
        return math.hypot(self.exit_zone.x - player_x, self.exit_zone.y - player_y) <= self.exit_zone.radius

    def _normalize_angle(self, angle: float) -> float:
        while angle > math.pi:
            angle -= math.tau
        while angle < -math.pi:
            angle += math.tau
        return angle


@dataclass
class LevelExit:
    exit_id: str
    x: float
    y: float
    required_door_id: str | None
    radius: float = settings.EXIT_TRIGGER_RADIUS
