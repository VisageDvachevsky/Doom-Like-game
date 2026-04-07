from __future__ import annotations

from dataclasses import dataclass
import math
import random

from doomgame.debug_log import append_debug_log
from doomgame.enemies import EnemyProjectile, EnemySpawn, WorldEnemy, build_enemy_runtime
from doomgame import settings
from doomgame.doors import DoorSpawn, KeyPickup, KeySpawn, WorldDoor
from doomgame.loot import PickupDefinition, get_pickup_definition
from doomgame.mapgen import GeneratedMap
from doomgame.progression import (
    ACTION_ACTIVATE_EXIT_ROUTE,
    ACTION_ACTIVATE_SECRET,
    ACTION_OPEN_DOOR,
    ACTION_SPAWN_AMBUSH,
    ACTION_UNLOCK_SHORTCUT,
    ACTION_WAKE_ROOM,
    EncounterEventPlan,
    ProgressionAction,
    QualityScoreReport,
    RoomMetadata,
    SecretSpawn,
    ValidationReport,
    WorldSwitchSpawn,
    WorldTriggerSpawn,
)


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
class WorldSwitch:
    switch_id: str
    x: float
    y: float
    room_index: int
    label: str
    event_id: str
    actions: tuple[ProgressionAction, ...]
    once: bool = True
    activated: bool = False

    @property
    def sprite_kind(self) -> str:
        return "switch_on" if self.activated else "switch_off"


@dataclass
class WorldTrigger:
    trigger_id: str
    trigger_type: str
    room_index: int
    x: float
    y: float
    radius: float
    event_id: str
    actions: tuple[ProgressionAction, ...]
    source_id: str | None = None
    once: bool = True
    activated: bool = False


@dataclass
class WorldSecret:
    secret_id: str
    secret_type: str
    room_index: int
    x: float
    y: float
    reward_kind: str | None = None
    reward_amount: int = 0
    door_id: str | None = None
    message: str = ""
    discovered: bool = False

    @property
    def sprite_kind(self) -> str:
        return "secret"


@dataclass
class World:
    tiles: list[list[int]]
    floor_heights: list[list[int]]
    ceiling_heights: list[list[int]]
    stair_mask: list[list[int]]
    room_kinds: list[list[int]]
    sector_types: list[list[int]]
    loot: list[LootPickup]
    enemies: list[WorldEnemy]
    enemy_projectiles: list[EnemyProjectile]
    doors: list[WorldDoor]
    keys: list[KeyPickup]
    exit_zone: "LevelExit | None"
    spawn: tuple[float, float]
    seed: int
    run_seed: int
    per_level_seed: int
    difficulty_id: str
    level_index: int
    level_archetype_id: str
    skeleton_profile_id: str
    level_title: str
    level_subtitle: str
    macro_layout_type: str
    macro_signature: str
    room_metadata: tuple[RoomMetadata, ...]
    switches: list[WorldSwitch]
    triggers: list[WorldTrigger]
    secrets: list[WorldSecret]
    encounter_events: tuple[EncounterEventPlan, ...]
    validation_report: ValidationReport
    quality_report: QualityScoreReport
    combat_rng: random.Random = None
    noise_position: tuple[float, float] | None = None
    noise_radius: float = 0.0
    noise_timer: float = 0.0
    activated_events: set[str] = None
    activated_triggers: set[str] = None
    player_hazard_exposure: float = 0.0
    player_hazard_tick_timer: float = 0.0
    enemy_hazard_timers: dict[str, float] = None

    @classmethod
    def from_generated_map(cls, generated: GeneratedMap) -> "World":
        world = cls(
            tiles=generated.tiles,
            floor_heights=generated.floor_heights,
            ceiling_heights=generated.ceiling_heights,
            stair_mask=generated.stair_mask,
            room_kinds=generated.room_kinds,
            sector_types=generated.sector_types,
            loot=[cls._loot_from_generated(entry) for entry in generated.loot_spawns],
            enemies=[cls._enemy_from_generated(entry) for entry in generated.enemy_spawns],
            enemy_projectiles=[],
            doors=[cls._door_from_generated(entry) for entry in generated.door_spawns],
            keys=[cls._key_from_generated(entry) for entry in generated.key_spawns],
            exit_zone=cls._exit_from_generated(generated.exit_spawn),
            spawn=generated.spawn,
            seed=generated.seed,
            run_seed=generated.run_seed,
            per_level_seed=generated.per_level_seed,
            difficulty_id=generated.difficulty_id,
            level_index=generated.level_index,
            level_archetype_id=generated.level_archetype_id,
            skeleton_profile_id=generated.skeleton_profile_id,
            level_title=generated.level_title,
            level_subtitle=generated.level_subtitle,
            macro_layout_type=generated.macro_layout_type,
            macro_signature=generated.macro_signature,
            room_metadata=generated.room_metadata,
            switches=[cls._switch_from_generated(entry) for entry in generated.switch_spawns],
            triggers=[cls._trigger_from_generated(entry) for entry in generated.trigger_spawns],
            secrets=[cls._secret_from_generated(entry) for entry in generated.secret_spawns],
            encounter_events=generated.encounter_events,
            validation_report=generated.validation_report,
            quality_report=generated.quality_report,
        )
        world.combat_rng = random.Random(generated.seed ^ 0xE61F)
        world.activated_events = set()
        world.activated_triggers = set()
        world.enemy_hazard_timers = {}
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
            required_trigger_id=entry.required_trigger_id,
            locked_message=entry.locked_message,
            secret=entry.secret,
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
    def _switch_from_generated(entry: WorldSwitchSpawn) -> WorldSwitch:
        return WorldSwitch(
            switch_id=entry.switch_id,
            x=entry.x,
            y=entry.y,
            room_index=entry.room_index,
            label=entry.label,
            event_id=entry.event_id,
            actions=entry.actions,
            once=entry.once,
        )

    @staticmethod
    def _trigger_from_generated(entry: WorldTriggerSpawn) -> WorldTrigger:
        return WorldTrigger(
            trigger_id=entry.trigger_id,
            trigger_type=entry.trigger_type,
            room_index=entry.room_index,
            x=entry.x,
            y=entry.y,
            radius=entry.radius,
            event_id=entry.event_id,
            actions=entry.actions,
            source_id=entry.source_id,
            once=entry.once,
        )

    @staticmethod
    def _secret_from_generated(entry: SecretSpawn) -> WorldSecret:
        return WorldSecret(
            secret_id=entry.secret_id,
            secret_type=entry.secret_type,
            room_index=entry.room_index,
            x=entry.x,
            y=entry.y,
            reward_kind=entry.reward_kind,
            reward_amount=entry.reward_amount,
            door_id=entry.door_id,
            message=entry.message,
        )

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
        self._process_proximity_triggers(player, audio)
        for enemy in self.enemies:
            enemy.update(self, player, delta_time, self.combat_rng, damage_player, audio)
        for projectile in self.enemy_projectiles:
            projectile.update(self, player, delta_time, damage_player, audio)
        self.enemy_projectiles = [projectile for projectile in self.enemy_projectiles if not projectile.removed]
        self._update_environmental_hazards(delta_time, player, damage_player, audio)
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

    def get_ceiling_height_at(self, grid_x: int, grid_y: int) -> int:
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return 1
        return self.ceiling_heights[grid_y][grid_x]

    def get_sector_type_at(self, grid_x: int, grid_y: int) -> int:
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return 0
        return self.sector_types[grid_y][grid_x]

    def get_sector_type(self, x: float, y: float) -> int:
        return self.get_sector_type_at(int(x), int(y))

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
            if not enemy.active:
                continue
            if include_corpses:
                result.append(enemy)
            elif enemy.alive and not enemy.dead:
                result.append(enemy)
        return result

    def active_enemy_projectiles(self) -> list[EnemyProjectile]:
        return [projectile for projectile in self.enemy_projectiles if not projectile.removed]

    def active_switches(self) -> list[WorldSwitch]:
        return [switch for switch in self.switches if not switch.activated]

    def visible_secrets(self) -> list[WorldSecret]:
        return [secret for secret in self.secrets if secret.discovered]

    def _update_environmental_hazards(self, delta_time: float, player, damage_player, audio=None) -> None:
        if self.get_sector_type(player.x, player.y) == 1:
            self.player_hazard_exposure += delta_time
            self.player_hazard_tick_timer = max(0.0, self.player_hazard_tick_timer - delta_time)
            if self.player_hazard_exposure >= settings.ACID_GRACE_TIME and self.player_hazard_tick_timer <= 0.0:
                self.player_hazard_tick_timer = settings.ACID_DAMAGE_INTERVAL
                damage_player(settings.ACID_DAMAGE, "acid")
        else:
            self.player_hazard_exposure = 0.0
            self.player_hazard_tick_timer = 0.0

        active_enemy_ids: set[str] = set()
        for enemy in self.active_enemies(include_corpses=False):
            active_enemy_ids.add(enemy.enemy_id)
            if self.get_sector_type(enemy.x, enemy.y) != 1:
                self.enemy_hazard_timers.pop(enemy.enemy_id, None)
                continue
            timer = self.enemy_hazard_timers.get(enemy.enemy_id, settings.ACID_GRACE_TIME * 0.75) - delta_time
            if timer <= 0.0:
                enemy.take_damage(settings.ACID_ENEMY_DAMAGE, self.combat_rng)
                timer = settings.ACID_DAMAGE_INTERVAL
            self.enemy_hazard_timers[enemy.enemy_id] = timer
        for enemy_id in tuple(self.enemy_hazard_timers):
            if enemy_id not in active_enemy_ids:
                self.enemy_hazard_timers.pop(enemy_id, None)

    def handle_key_pickup(self, key_type: str, audio=None) -> tuple[str, ...]:
        return self.activate_trigger_source(f"pickup:{key_type}", audio=audio)

    def activate_trigger_source(self, source_id: str, audio=None) -> tuple[str, ...]:
        messages: list[str] = []
        for trigger in self.triggers:
            if trigger.source_id != source_id:
                continue
            if trigger.once and trigger.activated:
                continue
            messages.extend(self._activate_trigger(trigger, audio))
        return tuple(messages)

    def _process_proximity_triggers(self, player, audio=None) -> None:
        for trigger in self.triggers:
            if trigger.trigger_type != "proximity":
                continue
            if trigger.once and trigger.activated:
                continue
            if math.hypot(trigger.x - player.x, trigger.y - player.y) > trigger.radius:
                continue
            self._activate_trigger(trigger, audio)

    def _activate_trigger(self, trigger: WorldTrigger, audio=None) -> list[str]:
        if trigger.once and trigger.activated:
            return []
        trigger.activated = True
        self.activated_triggers.add(trigger.trigger_id)
        return self.activate_event(trigger.event_id, trigger.actions, audio=audio)

    def activate_event(
        self,
        event_id: str,
        actions: tuple[ProgressionAction, ...],
        audio=None,
    ) -> list[str]:
        if event_id in self.activated_events:
            append_debug_log(f"event-skip event_id={event_id} reason=already-activated")
            return []
        append_debug_log(
            f"event-activate event_id={event_id} "
            f"actions={[action.action_type + ':' + str(action.target_id) for action in actions]}"
        )
        self.activated_events.add(event_id)
        messages: list[str] = []
        for action in actions:
            messages.extend(self._apply_progression_action(action, audio))
        self._wake_enemies_for_trigger(event_id)
        self._wake_enemies_for_trigger(f"event:{event_id}")
        return messages

    def _apply_progression_action(self, action: ProgressionAction, audio=None) -> list[str]:
        messages: list[str] = []
        append_debug_log(
            "action-apply "
            f"type={action.action_type} "
            f"target_id={action.target_id} "
            f"room_index={action.room_index} "
            f"note={action.note!r}"
        )
        if action.action_type in {ACTION_OPEN_DOOR, ACTION_UNLOCK_SHORTCUT, ACTION_ACTIVATE_EXIT_ROUTE}:
            for door in self.doors:
                if door.door_id != action.target_id:
                    continue
                append_debug_log(
                    "action-door-before "
                    f"door_id={door.door_id} "
                    f"door_type={door.door_type} "
                    f"state={door.state} "
                    f"trigger_unlocked={door.trigger_unlocked}"
                )
                door.unlock()
                if action.action_type != ACTION_UNLOCK_SHORTCUT:
                    door.begin_open()
                append_debug_log(
                    "action-door-after "
                    f"door_id={door.door_id} "
                    f"door_type={door.door_type} "
                    f"state={door.state} "
                    f"trigger_unlocked={door.trigger_unlocked}"
                )
                if audio is not None:
                    audio.play_door_open()
                if action.note:
                    messages.append(action.note)
                break
        elif action.action_type in {ACTION_SPAWN_AMBUSH, ACTION_WAKE_ROOM}:
            self._wake_enemies_for_trigger(action.target_id, room_index=action.room_index)
            if action.note:
                messages.append(action.note)
        elif action.action_type == ACTION_ACTIVATE_SECRET:
            for secret in self.secrets:
                if secret.secret_id != action.target_id:
                    continue
                secret.discovered = True
                if secret.reward_kind is not None and secret.reward_amount > 0:
                    self.add_loot_drop(secret.reward_kind, secret.reward_amount, secret.x, secret.y)
                if secret.door_id is not None:
                    for door in self.doors:
                        if door.door_id == secret.door_id:
                            door.unlock()
                            break
                messages.append(secret.message or action.note or "SECRET REVEALED")
                break
        return messages

    def _wake_enemies_for_trigger(self, trigger_id: str, room_index: int = -1) -> None:
        for enemy in self.enemies:
            if enemy.active:
                continue
            if room_index >= 0 and enemy.room_index != room_index:
                continue
            if enemy.wake_trigger_id not in {trigger_id, f"event:{trigger_id}"}:
                continue
            enemy.active = True
            enemy.ai_state = "alert" if enemy.ambush else "wander"
            enemy.state_timer = enemy.definition.reaction_time
            enemy.memory_timer = max(enemy.memory_timer, enemy.definition.memory_time * (1.0 if enemy.ambush else 0.5))

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
        append_debug_log(
            "door-target "
            f"door_id={door.door_id} "
            f"door_type={door.door_type} "
            f"state={door.state} "
            f"required_key={door.definition.required_key_type} "
            f"trigger_unlocked={door.trigger_unlocked} "
            f"required_trigger_id={door.required_trigger_id} "
            f"owned={sorted(owned_keys)}"
        )
        if door.state in {"opening", "open"}:
            return door, None, False
        if door.guard_enemy_id is not None and not self.is_enemy_defeated(door.guard_enemy_id):
            door.state = "locked"
            return door, "FINAL DOOR LOCKED - WARDEN ALIVE", False
        if door.required_trigger_id is not None and not door.trigger_unlocked:
            door.state = "locked"
            return door, door.locked_message or "ACCESS ROUTE LOCKED", False
        if not door.can_open(owned_keys, guard_defeated=True):
            door.state = "locked"
            return door, door.definition.visual.locked_message, False
        door.unlock()
        opened = door.begin_open()
        return door, None, opened

    def find_interactable_switch(self, player_x: float, player_y: float, player_angle: float) -> WorldSwitch | None:
        nearest: WorldSwitch | None = None
        best_score = float("inf")
        for switch in self.active_switches():
            distance = math.hypot(switch.x - player_x, switch.y - player_y)
            if distance > settings.SWITCH_INTERACT_DISTANCE:
                continue
            direction = math.atan2(switch.y - player_y, switch.x - player_x)
            angle_delta = self._normalize_angle(direction - player_angle)
            if abs(angle_delta) > settings.SWITCH_INTERACT_HALF_ANGLE:
                continue
            if not self.has_line_of_sight(player_x, player_y, switch.x, switch.y):
                continue
            score = distance + abs(angle_delta) * 0.45
            if score < best_score:
                best_score = score
                nearest = switch
        return nearest

    def interact_with_switch(self, player_x: float, player_y: float, player_angle: float, audio=None) -> tuple[WorldSwitch | None, tuple[str, ...], bool]:
        switch = self.find_interactable_switch(player_x, player_y, player_angle)
        if switch is None:
            return None, tuple(), False
        if switch.once and switch.activated:
            return switch, tuple(), False
        switch.activated = True
        messages = self.activate_event(switch.event_id, switch.actions, audio=audio)
        self.activated_triggers.add(switch.switch_id)
        return switch, tuple(messages), True

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
