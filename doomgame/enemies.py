from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import TYPE_CHECKING

from doomgame import settings

if TYPE_CHECKING:
    from doomgame.player import Player
    from doomgame.world import World


ENEMY_STATES = ("idle", "wander", "alert", "chase", "attack", "pain", "dead")
ENEMY_ATTACK_KINDS = ("melee", "projectile")


@dataclass(frozen=True)
class EnemyDrop:
    kind: str
    chance: float
    amount: int


@dataclass(frozen=True)
class EnemyVisual:
    base_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    glow_color: tuple[int, int, int]
    projectile_color: tuple[int, int, int]
    corpse_color: tuple[int, int, int]
    sprite_scale: float
    height_scale: float
    minimap_color: tuple[int, int, int]


@dataclass(frozen=True)
class EnemyDefinition:
    enemy_type: str
    display_name: str
    attack_kind: str
    max_hp: int
    collision_radius: float
    move_speed: float
    aggro_range: float
    attack_range: float
    attack_cooldown: float
    attack_windup: float
    damage: int
    projectile_speed: float
    projectile_radius: float
    reaction_time: float
    pain_time: float
    memory_time: float
    wander_radius: float
    hit_reaction_chance: float
    corpse_time: float
    preferred_range_min: float
    preferred_range_max: float
    strafe_speed_scale: float
    dodge_chance: float
    dodge_time: float
    dodge_cooldown: float
    search_aggressiveness: float
    drops: tuple[EnemyDrop, ...]
    visual: EnemyVisual


@dataclass(frozen=True)
class EnemySpawn:
    enemy_id: str
    enemy_type: str
    x: float
    y: float
    room_index: int
    difficulty_tier: int
    wake_trigger_id: str | None = None
    ambush: bool = False


@dataclass
class EnemyDamageResult:
    died: bool = False
    played_pain: bool = False
    played_death: bool = False
    drop_kind: str | None = None
    drop_amount: int = 0


@dataclass
class EnemyProjectile:
    projectile_id: str
    owner_id: str
    owner_type: str
    x: float
    y: float
    dir_x: float
    dir_y: float
    speed: float
    damage: int
    radius: float
    ttl: float
    age: float = 0.0
    animation_timer: float = 0.0
    removed: bool = False

    @property
    def sprite_state(self) -> str:
        return "projectile"

    @property
    def bob_phase(self) -> float:
        return self.age * 10.0

    def update(self, world: "World", player: "Player", delta_time: float, damage_player, audio) -> None:
        if self.removed:
            return

        self.age += delta_time
        self.animation_timer += delta_time
        self.ttl -= delta_time
        if self.ttl <= 0.0:
            self._explode(player, damage_player, audio)
            return

        step = max(0.02, self.speed * delta_time / 3.0)
        travel = self.speed * delta_time
        steps = max(1, int(math.ceil(travel / step)))
        segment = travel / steps
        for _ in range(steps):
            self.x += self.dir_x * segment
            self.y += self.dir_y * segment
            if world.is_blocked_circle(self.x, self.y, max(self.radius, settings.ENEMY_PROJECTILE_WALL_RADIUS)):
                self._explode(player, damage_player, audio)
                return
            if math.hypot(self.x - player.x, self.y - player.y) <= self.radius + settings.ENEMY_PROJECTILE_PLAYER_HIT_RADIUS:
                if player.jump_offset >= settings.PLAYER_PROJECTILE_DODGE_HEIGHT and self.owner_type != "cyberdemon":
                    continue
                self._explode(player, damage_player, audio, direct_hit=True)
                return

    def _explosion_profile(self) -> tuple[float, int]:
        if self.owner_type == "cyberdemon":
            return (1.15, self.damage + 10)
        return (0.0, self.damage)

    def _explode(self, player: "Player", damage_player, audio, direct_hit: bool = False) -> None:
        splash_radius, max_damage = self._explosion_profile()
        if direct_hit:
            damage_player(max_damage, self.owner_type)
            audio.play_enemy_attack_hit(self.owner_type)
            self.removed = True
            return
        if splash_radius > 0.0:
            distance = math.hypot(self.x - player.x, self.y - player.y)
            if distance <= splash_radius:
                falloff = 1.0 - min(1.0, distance / splash_radius)
                splash_damage = max(8, int(max_damage * (0.42 + falloff * 0.58)))
                damage_player(splash_damage, self.owner_type)
        audio.play_enemy_attack_hit(self.owner_type)
        self.removed = True


@dataclass
class WorldEnemy:
    enemy_id: str
    enemy_type: str
    x: float
    y: float
    room_index: int
    difficulty_tier: int
    radius: float
    hp: int
    max_hp: int
    wake_trigger_id: str | None = None
    ambush: bool = False
    active: bool = True
    ai_state: str = "idle"
    alive: bool = True
    dead: bool = False
    removed: bool = False
    attack_cooldown_timer: float = 0.0
    attack_timer: float = 0.0
    think_timer: float = 0.0
    state_timer: float = 0.0
    animation_timer: float = 0.0
    pain_timer: float = 0.0
    corpse_timer: float = settings.ENEMY_CORPSE_TIME
    memory_timer: float = 0.0
    wander_timer: float = 0.0
    wander_angle: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    last_seen_x: float = 0.0
    last_seen_y: float = 0.0
    attack_applied: bool = False
    has_alerted: bool = False
    cached_los: bool = False
    recent_hit_flash: float = 0.0
    sprite_phase: float = 0.0
    step_sound_timer: float = 0.0
    dodge_timer: float = 0.0
    dodge_cooldown_timer: float = 0.0
    dodge_dir: int = 0
    search_timer: float = 0.0
    search_angle: float = 0.0

    def __post_init__(self) -> None:
        self.origin_x = self.x
        self.origin_y = self.y
        self.target_x = self.x
        self.target_y = self.y
        self.last_seen_x = self.x
        self.last_seen_y = self.y

    @property
    def definition(self) -> EnemyDefinition:
        return ENEMY_DEFINITIONS[self.enemy_type]

    @property
    def blocks_movement(self) -> bool:
        return self.active and self.alive and not self.dead and not self.removed

    @property
    def can_take_damage(self) -> bool:
        return self.active and self.alive and not self.dead and not self.removed

    @property
    def corpse_visible(self) -> bool:
        return self.dead and not self.removed

    @property
    def attack_progress(self) -> float:
        if self.ai_state != "attack":
            return 0.0
        windup = max(0.001, self.definition.attack_windup)
        return max(0.0, min(1.0, 1.0 - self.attack_timer / windup))

    def sprite_state(self) -> str:
        if self.dead:
            return "dead"
        if self.ai_state == "pain":
            return "pain"
        if self.ai_state == "attack":
            return "attack"
        if self.ai_state in {"chase", "wander"}:
            return "walk"
        if self.ai_state == "alert":
            return "alert"
        return "idle"

    def sprite_frame(self) -> int:
        state = self.sprite_state()
        if state == "attack":
            return min(2, int(self.attack_progress * 3.0))
        if state == "pain":
            return min(1, int(self.animation_timer * 9.0) % 2)
        if state == "dead":
            return min(1, int(self.animation_timer * 1.3))
        if state == "alert":
            return min(1, int(self.animation_timer * 5.0) % 2)
        if state == "walk":
            return int(self.animation_timer * 7.0) % 4
        return int(self.animation_timer * 2.8) % 2

    def take_damage(self, amount: int, rng: random.Random) -> EnemyDamageResult:
        result = EnemyDamageResult()
        if amount <= 0 or not self.can_take_damage:
            return result

        self.hp = max(0, self.hp - amount)
        self.recent_hit_flash = max(0.32, self.definition.pain_time + 0.12)
        self.has_alerted = True
        self.memory_timer = max(self.memory_timer, self.definition.memory_time)
        self.last_seen_x = self.x
        self.last_seen_y = self.y
        if self.hp <= 0:
            self._die(rng)
            result.died = True
            result.played_death = True
            drop = self._roll_drop(rng)
            if drop is not None:
                result.drop_kind, result.drop_amount = drop
            return result

        if rng.random() <= self.definition.hit_reaction_chance:
            self.ai_state = "pain"
            self.pain_timer = self.definition.pain_time
            self.state_timer = self.definition.pain_time
            self.animation_timer = 0.0
            result.played_pain = True
        elif self.ai_state in {"idle", "wander"}:
            self.ai_state = "alert"
            self.state_timer = self.definition.reaction_time
        return result

    def _die(self, rng: random.Random) -> None:
        self.alive = False
        self.dead = True
        self.ai_state = "dead"
        self.attack_timer = 0.0
        self.attack_applied = False
        self.attack_cooldown_timer = 0.0
        self.memory_timer = 0.0
        self.animation_timer = 0.0
        self.corpse_timer = self.definition.corpse_time + rng.uniform(-1.1, 1.0)
        self.state_timer = self.corpse_timer

    def _roll_drop(self, rng: random.Random) -> tuple[str, int] | None:
        for entry in self.definition.drops:
            if rng.random() <= entry.chance:
                return (entry.kind, entry.amount)
        return None

    def update(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        rng: random.Random,
        damage_player,
        audio,
    ) -> None:
        if self.removed:
            return
        if not self.active:
            return

        self.animation_timer += delta_time
        self.recent_hit_flash = max(0.0, self.recent_hit_flash - delta_time * 3.5)
        if self.dead:
            self.corpse_timer -= delta_time
            if self.corpse_timer <= 0.0:
                self.removed = True
            return

        self.attack_cooldown_timer = max(0.0, self.attack_cooldown_timer - delta_time)
        self.think_timer = max(0.0, self.think_timer - delta_time)
        self.memory_timer = max(0.0, self.memory_timer - delta_time)
        self.wander_timer = max(0.0, self.wander_timer - delta_time)
        self.step_sound_timer = max(0.0, self.step_sound_timer - delta_time)
        self.dodge_timer = max(0.0, self.dodge_timer - delta_time)
        self.dodge_cooldown_timer = max(0.0, self.dodge_cooldown_timer - delta_time)
        self.search_timer = max(0.0, self.search_timer - delta_time)

        player_dx = player.x - self.x
        player_dy = player.y - self.y
        player_distance = math.hypot(player_dx, player_dy)

        if self.think_timer <= 0.0:
            self.cached_los = (
                player_distance <= self.definition.aggro_range * 1.35
                and world.has_line_of_sight(self.x, self.y, player.x, player.y)
            )
            self.think_timer = settings.ENEMY_THINK_INTERVAL + rng.uniform(0.02, 0.12)
        can_see_player = self.cached_los
        heard_player = world.enemy_can_hear_player(self, player_distance)
        under_aim_threat = self._is_under_player_aim(player, world, player_distance)
        shot_threat = world.was_enemy_threatened_by_player_shot(self)
        local_support = world.get_enemy_local_support(self)

        if can_see_player:
            self.last_seen_x = player.x
            self.last_seen_y = player.y
            self.target_x = player.x
            self.target_y = player.y
            self.memory_timer = max(self.memory_timer, self.definition.memory_time)
            if not self.has_alerted:
                self.has_alerted = True
                audio.play_enemy_alert(self.enemy_type)
                world.propagate_enemy_alert(
                    self,
                    player.x,
                    player.y,
                    radius=settings.ENEMY_ALERT_PROPAGATION_RADIUS,
                )
            if self.ai_state in {"idle", "wander"}:
                self.ai_state = "alert"
                self.state_timer = self.definition.reaction_time
                self.animation_timer = 0.0
        elif heard_player and self.ai_state in {"idle", "wander"}:
            self.target_x = player.x
            self.target_y = player.y
            self.memory_timer = max(self.memory_timer, 1.35)
            self.ai_state = "alert"
            self.state_timer = max(self.state_timer, self.definition.reaction_time * 0.72)
            self.animation_timer = 0.0
            if not self.has_alerted:
                self.has_alerted = True
                audio.play_enemy_alert(self.enemy_type)
                world.propagate_enemy_alert(
                    self,
                    player.x,
                    player.y,
                    radius=settings.ENEMY_ALERT_PROPAGATION_RADIUS * 0.78,
                )

        if self.ai_state == "pain":
            self.pain_timer -= delta_time
            if self.pain_timer <= 0.0:
                self.ai_state = "chase" if self.memory_timer > 0.0 else "wander"
                self.animation_timer = 0.0
            return

        if self.ai_state == "alert":
            self.state_timer -= delta_time
            if self.state_timer <= 0.0:
                self.ai_state = "chase" if self.memory_timer > 0.0 else "wander"
                self.animation_timer = 0.0
            else:
                return

        if self.ai_state == "attack":
            self._update_attack(world, player, delta_time, damage_player, audio)
            return

        if self._should_start_dodge(can_see_player, under_aim_threat, shot_threat, rng):
            self._start_dodge(player, rng)

        if self.dodge_timer > 0.0 and self.memory_timer > 0.0:
            self.ai_state = "chase"
            self._perform_dodge(world, player, delta_time, rng, audio)
            return

        if self.attack_cooldown_timer <= 0.0 and self._can_begin_attack(player_distance, can_see_player):
            self._begin_attack(audio)
            return

        if self.memory_timer > 0.0:
            self.ai_state = "chase"
            if can_see_player:
                self._update_combat_movement(world, player, player_distance, local_support, delta_time, rng, audio)
            else:
                self._update_search(world, player, delta_time, rng, audio)
            return

        if self.ai_state not in {"idle", "wander"}:
            self.ai_state = "wander"
            self.wander_timer = 0.0
        self._update_wander(world, player, delta_time, rng, audio)

    def _is_under_player_aim(self, player: "Player", world: "World", player_distance: float) -> bool:
        if player_distance > settings.ENEMY_AIM_THREAT_MAX_DISTANCE:
            return False
        if not world.has_line_of_sight(player.x, player.y, self.x, self.y):
            return False
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        to_enemy_x = self.x - player.x
        to_enemy_y = self.y - player.y
        norm = max(0.001, player_distance)
        aim_dot = (to_enemy_x / norm) * dir_x + (to_enemy_y / norm) * dir_y
        danger_cos = settings.ENEMY_AIM_DANGER_COS if world.noise_timer > 0.0 else settings.ENEMY_AIM_THREAT_COS
        return aim_dot >= danger_cos

    def _should_start_dodge(
        self,
        can_see_player: bool,
        under_aim_threat: bool,
        shot_threat: bool,
        rng: random.Random,
    ) -> bool:
        if not can_see_player or not (under_aim_threat or shot_threat):
            return False
        if self.dodge_timer > 0.0 or self.dodge_cooldown_timer > 0.0:
            return False
        if self.ai_state in {"pain", "attack"}:
            return False
        dodge_chance = self.definition.dodge_chance * (1.1 if shot_threat else 1.0)
        return rng.random() <= min(0.7, dodge_chance)

    def _start_dodge(self, player: "Player", rng: random.Random) -> None:
        self.dodge_timer = self.definition.dodge_time
        self.dodge_cooldown_timer = self.definition.dodge_cooldown
        player_dx = player.x - self.x
        player_dy = player.y - self.y
        cross = math.cos(player.angle) * player_dy - math.sin(player.angle) * player_dx
        if abs(cross) > 0.02:
            self.dodge_dir = -1 if cross > 0.0 else 1
        else:
            self.dodge_dir = rng.choice((-1, 1))
        self.search_angle = math.atan2(player_dy, player_dx)

    def _perform_dodge(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        rng: random.Random,
        audio,
    ) -> None:
        base_angle = math.atan2(player.y - self.y, player.x - self.x)
        strafe_angle = base_angle + self.dodge_dir * (math.pi / 2.0)
        speed_scale = self.definition.strafe_speed_scale * settings.ENEMY_DODGE_SPEED_SCALE
        if self._move_in_direction(world, player, strafe_angle, delta_time, audio, speed_scale=speed_scale):
            return
        self.dodge_dir *= -1
        strafe_angle = base_angle + self.dodge_dir * (math.pi / 2.0)
        if self._move_in_direction(world, player, strafe_angle, delta_time, audio, speed_scale=speed_scale):
            return
        self._move_in_direction(
            world,
            player,
            base_angle + rng.choice((-0.75, 0.75)),
            delta_time,
            audio,
            speed_scale=self.definition.strafe_speed_scale * 0.88,
        )

    def _update_combat_movement(
        self,
        world: "World",
        player: "Player",
        player_distance: float,
        local_support: int,
        delta_time: float,
        rng: random.Random,
        audio,
    ) -> None:
        stance = self._combat_stance(player_distance, local_support)
        if stance == "rush":
            self._move_towards(world, player, player.x, player.y, delta_time, rng, audio, speed_scale=1.08)
            return
        if stance == "retreat":
            self._move_away_from(world, player, player.x, player.y, delta_time, rng, audio, speed_scale=0.94)
            return
        if stance == "orbit":
            orbit_dir = self._orbit_direction(player)
            if not self._orbit_player(world, player, delta_time, audio, orbit_dir, speed_scale=self.definition.strafe_speed_scale):
                self._move_towards(world, player, player.x, player.y, delta_time, rng, audio, speed_scale=0.72)
            return
        if stance == "anchor":
            if not self._orbit_player(world, player, delta_time, audio, self._orbit_direction(player), speed_scale=self.definition.strafe_speed_scale * 0.92):
                self._move_towards(world, player, player.x, player.y, delta_time, rng, audio, speed_scale=0.48)
            return
        self._move_towards(world, player, player.x, player.y, delta_time, rng, audio)

    def _update_search(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        rng: random.Random,
        audio,
    ) -> None:
        if math.hypot(self.x - self.target_x, self.y - self.target_y) <= settings.ENEMY_SEARCH_REACHED_EPSILON or self.search_timer <= 0.0:
            self.search_timer = settings.ENEMY_SEARCH_POINT_INTERVAL + rng.uniform(0.0, 0.35)
            self.search_angle += rng.uniform(0.55, 1.25) * rng.choice((-1, 1))
            radius = settings.ENEMY_SEARCH_POINT_RADIUS * self.definition.search_aggressiveness
            self.target_x = self.last_seen_x + math.cos(self.search_angle) * radius
            self.target_y = self.last_seen_y + math.sin(self.search_angle) * radius
        self._move_towards(world, player, self.target_x, self.target_y, delta_time, rng, audio, speed_scale=0.78)

    def _combat_stance(self, player_distance: float, local_support: int) -> str:
        if self.enemy_type == "charger":
            return "rush"
        if self.enemy_type == "cyberdemon":
            return "anchor" if player_distance >= self.definition.preferred_range_min else "retreat"
        if self.enemy_type == "grunt" and local_support >= 2 and player_distance <= self.definition.preferred_range_max:
            return "orbit"
        if self.enemy_type == "heavy" and local_support >= 1 and player_distance >= self.definition.preferred_range_min:
            return "anchor"
        if self.enemy_type == "warden" and local_support >= 1:
            return "orbit"
        if player_distance < self.definition.preferred_range_min:
            return "retreat"
        if self.enemy_type in {"warden", "cacodemon"}:
            return "orbit"
        if self.enemy_type == "heavy":
            return "anchor"
        if player_distance > self.definition.preferred_range_max:
            return "advance"
        return "orbit"

    def _orbit_direction(self, player: "Player") -> int:
        delta_x = self.x - player.x
        delta_y = self.y - player.y
        cross = math.cos(player.angle) * delta_y - math.sin(player.angle) * delta_x
        return -1 if cross > 0.0 else 1

    def _orbit_player(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        audio,
        orbit_dir: int,
        speed_scale: float,
    ) -> bool:
        angle = math.atan2(player.y - self.y, player.x - self.x) + orbit_dir * (math.pi / 2.0)
        return self._move_in_direction(world, player, angle, delta_time, audio, speed_scale=speed_scale)

    def _move_in_direction(
        self,
        world: "World",
        player: "Player",
        angle: float,
        delta_time: float,
        audio,
        speed_scale: float = 1.0,
    ) -> bool:
        speed = self.definition.move_speed * speed_scale * delta_time
        if speed <= 0.0:
            return False
        moved = world.move_enemy(self, math.cos(angle) * speed, math.sin(angle) * speed, player)
        if moved:
            self._maybe_play_step(audio)
        return moved

    def _can_begin_attack(self, player_distance: float, can_see_player: bool) -> bool:
        if not can_see_player:
            return False
        return player_distance <= self.definition.attack_range

    def _should_kite_player(self, player_distance: float, can_see_player: bool) -> bool:
        if self.enemy_type != "cacodemon" or not can_see_player:
            return False
        return player_distance <= self.definition.attack_range * 0.58

    def _begin_attack(self, audio) -> None:
        self.ai_state = "attack"
        self.attack_timer = self.definition.attack_windup
        self.attack_applied = False
        self.animation_timer = 0.0
        audio.play_enemy_attack(self.enemy_type)

    def _update_attack(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        damage_player,
        audio,
    ) -> None:
        self.attack_timer -= delta_time
        impact_point = self.definition.attack_windup * 0.45
        player_distance = math.hypot(player.x - self.x, player.y - self.y)
        if not self.attack_applied and self.attack_timer <= impact_point:
            if self.definition.attack_kind == "melee":
                can_hit = player_distance <= self.definition.attack_range + player.radius
                can_hit = can_hit and world.has_line_of_sight(self.x, self.y, player.x, player.y)
                if can_hit:
                    damage_player(self.definition.damage, self.definition.display_name)
                    audio.play_enemy_attack_hit(self.enemy_type)
            else:
                can_hit = (
                    player_distance <= self.definition.attack_range
                    and world.has_line_of_sight(self.x, self.y, player.x, player.y)
                )
                if can_hit:
                    target_x, target_y = self._projectile_target_point(player)
                    world.spawn_enemy_projectile(self, target_x, target_y)
            self.attack_applied = True

        if self.attack_timer <= 0.0:
            self.attack_cooldown_timer = self.definition.attack_cooldown
            self.ai_state = "chase" if self.memory_timer > 0.0 else "wander"
            self.animation_timer = 0.0

    def _projectile_target_point(self, player: "Player") -> tuple[float, float]:
        speed = max(0.001, self.definition.projectile_speed)
        distance = math.hypot(player.x - self.x, player.y - self.y)
        lead_time = min(0.55, distance / speed)
        if self.enemy_type == "heavy":
            lead_time *= 0.82
        elif self.enemy_type in {"warden", "cyberdemon"}:
            lead_time *= 1.08
        return (
            player.x + player.vel_x * lead_time,
            player.y + player.vel_y * lead_time,
        )

    def _update_wander(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        rng: random.Random,
        audio,
    ) -> None:
        if self.wander_timer <= 0.0:
            if rng.random() < 0.28:
                self.ai_state = "idle"
                self.wander_timer = rng.uniform(0.45, 1.2)
                self.animation_timer = 0.0
                return
            self.ai_state = "wander"
            self.wander_angle = rng.uniform(0.0, math.tau)
            wander_distance = rng.uniform(0.45, self.definition.wander_radius)
            self.target_x = self.origin_x + math.cos(self.wander_angle) * wander_distance
            self.target_y = self.origin_y + math.sin(self.wander_angle) * wander_distance
            self.wander_timer = rng.uniform(0.8, 1.8)
            self.animation_timer = 0.0
        if self.ai_state == "wander":
            self._move_towards(world, player, self.target_x, self.target_y, delta_time, rng, audio, speed_scale=0.52)

    def _move_towards(
        self,
        world: "World",
        player: "Player",
        target_x: float,
        target_y: float,
        delta_time: float,
        rng: random.Random,
        audio,
        speed_scale: float = 1.0,
    ) -> None:
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.hypot(dx, dy)
        if distance <= 0.001:
            return

        speed = self.definition.move_speed * speed_scale * delta_time
        step_x = dx / distance * speed
        step_y = dy / distance * speed
        if world.move_enemy(self, step_x, step_y, player):
            self._maybe_play_step(audio)
            return

        perp_x = -step_y
        perp_y = step_x
        if world.move_enemy(self, perp_x, perp_y, player):
            self._maybe_play_step(audio)
            return
        if world.move_enemy(self, -perp_x, -perp_y, player):
            self._maybe_play_step(audio)
            return

        angle = math.atan2(dy, dx) + rng.choice((-0.72, 0.72))
        if world.move_enemy(
            self,
            math.cos(angle) * speed * 0.84,
            math.sin(angle) * speed * 0.84,
            player,
        ):
            self._maybe_play_step(audio)

    def _move_away_from(
        self,
        world: "World",
        player: "Player",
        target_x: float,
        target_y: float,
        delta_time: float,
        rng: random.Random,
        audio,
        speed_scale: float = 1.0,
    ) -> None:
        dx = self.x - target_x
        dy = self.y - target_y
        distance = math.hypot(dx, dy)
        if distance <= 0.001:
            return

        speed = self.definition.move_speed * speed_scale * delta_time
        step_x = dx / distance * speed
        step_y = dy / distance * speed
        if world.move_enemy(self, step_x, step_y, player):
            self._maybe_play_step(audio)
            return

        strafe_angle = math.atan2(dy, dx) + rng.choice((-0.92, 0.92))
        if world.move_enemy(
            self,
            math.cos(strafe_angle) * speed * 0.9,
            math.sin(strafe_angle) * speed * 0.9,
            player,
        ):
            self._maybe_play_step(audio)
            return

        if world.move_enemy(
            self,
            -step_y * 0.7,
            step_x * 0.7,
            player,
        ):
            self._maybe_play_step(audio)

    def _maybe_play_step(self, audio) -> None:
        if self.enemy_type != "cyberdemon" or audio is None:
            return
        if self.step_sound_timer > 0.0:
            return
        self.step_sound_timer = 0.52
        audio.play_enemy_step(self.enemy_type)


ENEMY_DEFINITIONS: dict[str, EnemyDefinition] = {
    "grunt": EnemyDefinition(
        enemy_type="grunt",
        display_name="Grunt",
        attack_kind="projectile",
        max_hp=46,
        collision_radius=0.28,
        move_speed=2.2,
        aggro_range=12.5,
        attack_range=9.8,
        attack_cooldown=1.35,
        attack_windup=0.56,
        damage=11,
        projectile_speed=7.8,
        projectile_radius=0.13,
        reaction_time=0.18,
        pain_time=0.18,
        memory_time=3.2,
        wander_radius=2.2,
        hit_reaction_chance=0.76,
        corpse_time=settings.ENEMY_CORPSE_TIME,
        preferred_range_min=4.8,
        preferred_range_max=8.7,
        strafe_speed_scale=0.96,
        dodge_chance=0.18,
        dodge_time=0.18,
        dodge_cooldown=1.08,
        search_aggressiveness=1.0,
        drops=(
            EnemyDrop("bullets", 0.42, 20),
            EnemyDrop("shells", 0.22, 4),
            EnemyDrop("stimpack", 0.12, 10),
        ),
        visual=EnemyVisual(
            base_color=(116, 122, 130),
            accent_color=(214, 88, 68),
            glow_color=(224, 124, 96),
            projectile_color=(255, 168, 92),
            corpse_color=(82, 54, 48),
            sprite_scale=0.98,
            height_scale=1.24,
            minimap_color=(196, 96, 74),
        ),
    ),
    "charger": EnemyDefinition(
        enemy_type="charger",
        display_name="Charger",
        attack_kind="melee",
        max_hp=64,
        collision_radius=0.3,
        move_speed=3.25,
        aggro_range=10.2,
        attack_range=0.72,
        attack_cooldown=0.9,
        attack_windup=0.34,
        damage=17,
        projectile_speed=0.0,
        projectile_radius=0.0,
        reaction_time=0.1,
        pain_time=0.14,
        memory_time=2.7,
        wander_radius=2.5,
        hit_reaction_chance=0.52,
        corpse_time=settings.ENEMY_CORPSE_TIME,
        preferred_range_min=0.0,
        preferred_range_max=1.2,
        strafe_speed_scale=1.12,
        dodge_chance=0.24,
        dodge_time=0.16,
        dodge_cooldown=0.96,
        search_aggressiveness=1.18,
        drops=(EnemyDrop("shells", 0.2, 4), EnemyDrop("armor_bonus", 0.16, 1)),
        visual=EnemyVisual(
            base_color=(158, 66, 58),
            accent_color=(242, 186, 98),
            glow_color=(255, 142, 88),
            projectile_color=(0, 0, 0),
            corpse_color=(86, 42, 34),
            sprite_scale=0.96,
            height_scale=1.1,
            minimap_color=(214, 96, 64),
        ),
    ),
    "heavy": EnemyDefinition(
        enemy_type="heavy",
        display_name="Heavy",
        attack_kind="projectile",
        max_hp=128,
        collision_radius=0.34,
        move_speed=1.55,
        aggro_range=13.0,
        attack_range=10.8,
        attack_cooldown=1.92,
        attack_windup=0.8,
        damage=24,
        projectile_speed=5.8,
        projectile_radius=0.18,
        reaction_time=0.26,
        pain_time=0.2,
        memory_time=4.1,
        wander_radius=1.9,
        hit_reaction_chance=0.34,
        corpse_time=settings.ENEMY_CORPSE_TIME + 1.0,
        preferred_range_min=6.8,
        preferred_range_max=11.2,
        strafe_speed_scale=0.74,
        dodge_chance=0.1,
        dodge_time=0.14,
        dodge_cooldown=1.45,
        search_aggressiveness=0.82,
        drops=(
            EnemyDrop("bullet_box", 0.46, 60),
            EnemyDrop("shell_box", 0.24, 20),
            EnemyDrop("green_armor", 0.08, 100),
        ),
        visual=EnemyVisual(
            base_color=(70, 92, 120),
            accent_color=(138, 228, 176),
            glow_color=(134, 234, 188),
            projectile_color=(112, 255, 214),
            corpse_color=(42, 54, 62),
            sprite_scale=1.18,
            height_scale=1.42,
            minimap_color=(108, 148, 188),
        ),
    ),
    "cacodemon": EnemyDefinition(
        enemy_type="cacodemon",
        display_name="Cacodemon",
        attack_kind="projectile",
        max_hp=172,
        collision_radius=0.54,
        move_speed=1.72,
        aggro_range=14.6,
        attack_range=11.6,
        attack_cooldown=1.84,
        attack_windup=0.86,
        damage=26,
        projectile_speed=4.9,
        projectile_radius=0.24,
        reaction_time=0.24,
        pain_time=0.42,
        memory_time=5.1,
        wander_radius=1.8,
        hit_reaction_chance=0.3,
        corpse_time=settings.ENEMY_CORPSE_TIME + 1.6,
        preferred_range_min=6.4,
        preferred_range_max=10.4,
        strafe_speed_scale=1.02,
        dodge_chance=0.16,
        dodge_time=0.2,
        dodge_cooldown=1.2,
        search_aggressiveness=1.1,
        drops=(EnemyDrop("shell_box", 0.38, 20), EnemyDrop("medkit", 0.18, 25)),
        visual=EnemyVisual(
            base_color=(170, 52, 44),
            accent_color=(255, 196, 112),
            glow_color=(255, 96, 82),
            projectile_color=(255, 120, 74),
            corpse_color=(92, 34, 28),
            sprite_scale=1.0,
            height_scale=0.98,
            minimap_color=(222, 92, 78),
        ),
    ),
    "warden": EnemyDefinition(
        enemy_type="warden",
        display_name="Warden",
        attack_kind="projectile",
        max_hp=220,
        collision_radius=0.42,
        move_speed=1.32,
        aggro_range=15.0,
        attack_range=12.0,
        attack_cooldown=1.5,
        attack_windup=0.92,
        damage=28,
        projectile_speed=5.1,
        projectile_radius=0.22,
        reaction_time=0.32,
        pain_time=0.18,
        memory_time=6.0,
        wander_radius=1.4,
        hit_reaction_chance=0.18,
        corpse_time=settings.ENEMY_CORPSE_TIME + 2.0,
        preferred_range_min=7.2,
        preferred_range_max=11.6,
        strafe_speed_scale=1.08,
        dodge_chance=0.2,
        dodge_time=0.22,
        dodge_cooldown=1.18,
        search_aggressiveness=1.18,
        drops=(EnemyDrop("shell_box", 0.72, 20), EnemyDrop("medkit", 0.5, 25), EnemyDrop("green_armor", 0.18, 100)),
        visual=EnemyVisual(
            base_color=(92, 70, 138),
            accent_color=(255, 182, 104),
            glow_color=(224, 124, 255),
            projectile_color=(214, 126, 255),
            corpse_color=(64, 44, 90),
            sprite_scale=1.10,
            height_scale=1.34,
            minimap_color=(182, 118, 224),
        ),
    ),
    "cyberdemon": EnemyDefinition(
        enemy_type="cyberdemon",
        display_name="Cyberdemon",
        attack_kind="projectile",
        max_hp=460,
        collision_radius=0.46,
        move_speed=1.18,
        aggro_range=16.0,
        attack_range=13.0,
        attack_cooldown=1.72,
        attack_windup=0.96,
        damage=40,
        projectile_speed=4.4,
        projectile_radius=0.26,
        reaction_time=0.22,
        pain_time=0.34,
        memory_time=7.5,
        wander_radius=1.25,
        hit_reaction_chance=0.08,
        corpse_time=settings.ENEMY_CORPSE_TIME + 3.0,
        preferred_range_min=8.0,
        preferred_range_max=13.2,
        strafe_speed_scale=0.62,
        dodge_chance=0.04,
        dodge_time=0.14,
        dodge_cooldown=1.8,
        search_aggressiveness=0.9,
        drops=(EnemyDrop("shell_box", 1.0, 20), EnemyDrop("medkit", 1.0, 25), EnemyDrop("green_armor", 0.4, 100)),
        visual=EnemyVisual(
            base_color=(116, 82, 72),
            accent_color=(228, 92, 64),
            glow_color=(255, 126, 74),
            projectile_color=(255, 126, 64),
            corpse_color=(62, 42, 36),
            sprite_scale=1.18,
            height_scale=1.28,
            minimap_color=(214, 118, 88),
        ),
    ),
}


def build_enemy_runtime(spawn: EnemySpawn) -> WorldEnemy:
    definition = ENEMY_DEFINITIONS[spawn.enemy_type]
    seed_a = hash(spawn.enemy_id) & 0xFFFFFFFF
    seed_b = (hash(spawn.enemy_id) ^ 0xA51C) & 0xFFFFFFFF
    seed_c = (hash(spawn.enemy_id) ^ 0x1F33) & 0xFFFFFFFF
    return WorldEnemy(
        enemy_id=spawn.enemy_id,
        enemy_type=spawn.enemy_type,
        x=spawn.x,
        y=spawn.y,
        room_index=spawn.room_index,
        difficulty_tier=spawn.difficulty_tier,
        wake_trigger_id=spawn.wake_trigger_id,
        ambush=spawn.ambush,
        active=spawn.wake_trigger_id is None,
        radius=definition.collision_radius,
        hp=definition.max_hp,
        max_hp=definition.max_hp,
        attack_cooldown_timer=random.Random(seed_a).uniform(0.0, definition.attack_cooldown * 0.6),
        think_timer=random.Random(seed_b).uniform(0.02, settings.ENEMY_THINK_INTERVAL),
        wander_timer=random.Random(seed_c).uniform(0.1, 1.0),
        sprite_phase=random.Random(seed_a ^ seed_b).uniform(0.0, math.tau),
    )
