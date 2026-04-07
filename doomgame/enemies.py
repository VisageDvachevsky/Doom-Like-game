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
            self.removed = True
            return

        step = max(0.02, self.speed * delta_time / 3.0)
        travel = self.speed * delta_time
        steps = max(1, int(math.ceil(travel / step)))
        segment = travel / steps
        for _ in range(steps):
            self.x += self.dir_x * segment
            self.y += self.dir_y * segment
            if world.is_blocked_circle(self.x, self.y, max(self.radius, settings.ENEMY_PROJECTILE_WALL_RADIUS)):
                self.removed = True
                return
            if math.hypot(self.x - player.x, self.y - player.y) <= self.radius + settings.ENEMY_PROJECTILE_PLAYER_HIT_RADIUS:
                damage_player(self.damage, self.owner_type)
                audio.play_enemy_attack_hit(self.owner_type)
                self.removed = True
                return


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
        return self.alive and not self.dead and not self.removed

    @property
    def can_take_damage(self) -> bool:
        return self.alive and not self.dead and not self.removed

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
        self.recent_hit_flash = 0.22
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

        if can_see_player:
            self.last_seen_x = player.x
            self.last_seen_y = player.y
            self.target_x = player.x
            self.target_y = player.y
            self.memory_timer = max(self.memory_timer, self.definition.memory_time)
            if not self.has_alerted:
                self.has_alerted = True
                audio.play_enemy_alert(self.enemy_type)
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

        if self.attack_cooldown_timer <= 0.0 and self._can_begin_attack(player_distance, can_see_player):
            self._begin_attack(audio)
            return

        if self.memory_timer > 0.0:
            self.ai_state = "chase"
            self._move_towards(world, player, self.target_x, self.target_y, delta_time, rng)
            return

        if self.ai_state not in {"idle", "wander"}:
            self.ai_state = "wander"
            self.wander_timer = 0.0
        self._update_wander(world, player, delta_time, rng)

    def _can_begin_attack(self, player_distance: float, can_see_player: bool) -> bool:
        if not can_see_player:
            return False
        return player_distance <= self.definition.attack_range

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
                    world.spawn_enemy_projectile(self, player.x, player.y)
            self.attack_applied = True

        if self.attack_timer <= 0.0:
            self.attack_cooldown_timer = self.definition.attack_cooldown
            self.ai_state = "chase" if self.memory_timer > 0.0 else "wander"
            self.animation_timer = 0.0

    def _update_wander(
        self,
        world: "World",
        player: "Player",
        delta_time: float,
        rng: random.Random,
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
            self._move_towards(world, player, self.target_x, self.target_y, delta_time, rng, speed_scale=0.52)

    def _move_towards(
        self,
        world: "World",
        player: "Player",
        target_x: float,
        target_y: float,
        delta_time: float,
        rng: random.Random,
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
            return

        perp_x = -step_y
        perp_y = step_x
        if world.move_enemy(self, perp_x, perp_y, player):
            return
        if world.move_enemy(self, -perp_x, -perp_y, player):
            return

        angle = math.atan2(dy, dx) + rng.choice((-0.72, 0.72))
        world.move_enemy(
            self,
            math.cos(angle) * speed * 0.84,
            math.sin(angle) * speed * 0.84,
            player,
        )


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
        drops=(EnemyDrop("shells", 0.34, 4), EnemyDrop("stimpack", 0.12, 10)),
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
        drops=(EnemyDrop("shell_box", 0.42, 20), EnemyDrop("green_armor", 0.08, 100)),
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
        drops=(EnemyDrop("shell_box", 0.72, 20), EnemyDrop("medkit", 0.5, 25), EnemyDrop("green_armor", 0.18, 100)),
        visual=EnemyVisual(
            base_color=(92, 70, 138),
            accent_color=(255, 182, 104),
            glow_color=(224, 124, 255),
            projectile_color=(214, 126, 255),
            corpse_color=(64, 44, 90),
            sprite_scale=1.34,
            height_scale=1.56,
            minimap_color=(182, 118, 224),
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
        radius=definition.collision_radius,
        hp=definition.max_hp,
        max_hp=definition.max_hp,
        attack_cooldown_timer=random.Random(seed_a).uniform(0.0, definition.attack_cooldown * 0.6),
        think_timer=random.Random(seed_b).uniform(0.02, settings.ENEMY_THINK_INTERVAL),
        wander_timer=random.Random(seed_c).uniform(0.1, 1.0),
        sprite_phase=random.Random(seed_a ^ seed_b).uniform(0.0, math.tau),
    )
