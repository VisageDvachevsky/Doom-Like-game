from __future__ import annotations

from dataclasses import dataclass
import math
import multiprocessing
import os
import pickle
import random
from pathlib import Path
import tempfile
import traceback
import pygame

from doomgame import settings
from doomgame.audio import DoomAudio
from doomgame.debug_log import append_debug_log, clear_debug_log
from doomgame.doors import KEY_DEFINITIONS, KEY_TYPES
from doomgame.loot import get_pickup_definition
from doomgame.mapgen import GeneratedMap, MapGenerator
from doomgame.music import DoomMusicPlayer, MusicSnapshot
from doomgame.player import Player
from doomgame.progression import (
    CampaignSequenceDirector,
    DIFFICULTY_IDS,
    LevelGenerationRequest,
    RunState,
    get_difficulty_definition,
)
from doomgame.raycaster import Raycaster
from doomgame.world import World

DIGIT_PATTERNS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "%": ("101", "001", "010", "100", "101"),
}


@dataclass(frozen=True)
class WeaponDefinition:
    weapon_id: str
    slot: int
    ammo_pool: str
    ammo_per_shot: int
    damage: int
    cooldown: float
    anim_frames: list[int]
    recoil: float
    automatic: bool
    audio_key: str
    pickup_name: str
    spread: float = 0.0


@dataclass
class PendingLevelLoad:
    request_id: int
    level_index: int
    preserve_player_state: bool
    show_intermission: bool
    generation_request: LevelGenerationRequest
    difficulty_id: str
    runtime_pressure_bias: float
    loading_label: str
    started_at: float
    process: multiprocessing.Process | None = None
    result_path: str = ""


def _generate_map_payload(
    generation_request: LevelGenerationRequest,
    difficulty_id: str,
    runtime_pressure_bias: float,
) -> GeneratedMap:
    generator = MapGenerator(
        difficulty_id=difficulty_id,
        runtime_pressure_bias=runtime_pressure_bias,
        generation_request=generation_request,
    )
    return generator.generate()


def _run_level_generation_process(
    result_path: str,
    generation_request: LevelGenerationRequest,
    difficulty_id: str,
    runtime_pressure_bias: float,
) -> None:
    try:
        generated = _generate_map_payload(generation_request, difficulty_id, runtime_pressure_bias)
        with open(result_path, "wb") as result_file:
            pickle.dump(("ok", generated), result_file, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        with open(result_path, "wb") as result_file:
            pickle.dump(("error", traceback.format_exc()), result_file, protocol=pickle.HIGHEST_PROTOCOL)


WEAPON_DEFINITIONS: dict[str, WeaponDefinition] = {
    "pistol": WeaponDefinition(
        weapon_id="pistol",
        slot=2,
        ammo_pool="BULL",
        ammo_per_shot=1,
        damage=10,
        cooldown=0.22,
        anim_frames=[1, 2, 2, 3, 0],
        recoil=0.42,
        automatic=False,
        audio_key="pistol_fire",
        pickup_name="PISTOL",
        spread=0.01,
    ),
    "shotgun": WeaponDefinition(
        weapon_id="shotgun",
        slot=3,
        ammo_pool="SHEL",
        ammo_per_shot=1,
        damage=24,
        cooldown=settings.SHOT_COOLDOWN,
        anim_frames=[1, 2, 2, 3, 4, 5, 0],
        recoil=0.8,
        automatic=False,
        audio_key="shotgun_fire",
        pickup_name="SHOTGUN",
    ),
    "sawedoff": WeaponDefinition(
        weapon_id="sawedoff",
        slot=4,
        ammo_pool="SHEL",
        ammo_per_shot=1,
        damage=65,
        cooldown=1.42,
        anim_frames=[1, 2, 2, 3, 0],
        recoil=0.92,
        automatic=False,
        audio_key="sawedoff_fire",
        pickup_name="SAWED-OFF",
        spread=0.014,
    ),
    "chaingun": WeaponDefinition(
        weapon_id="chaingun",
        slot=5,
        ammo_pool="BULL",
        ammo_per_shot=1,
        damage=11,
        cooldown=0.078,
        anim_frames=[1, 2, 1, 0],
        recoil=0.56,
        automatic=True,
        audio_key="chaingun_fire",
        pickup_name="CHAINGUN",
        spread=0.019,
    ),
}


class DoomGame:
    def __init__(
        self,
        dev_start_level: int | None = None,
        dev_immortal: bool = False,
        dev_auto_difficulty: str | None = None,
    ) -> None:
        pygame.init()
        pygame.display.set_caption("Doom-like Pygame")
        self.screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
        self.scene_surface = pygame.Surface(
            (settings.INTERNAL_RENDER_WIDTH, settings.INTERNAL_RENDER_HEIGHT)
        ).convert()
        self.audio = DoomAudio()
        self.music = DoomMusicPlayer()
        self.mouse_captured = False
        self.mouse_delta_x = 0.0
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 20, bold=True)
        self.small_font = pygame.font.SysFont("arial", 14, bold=True)
        self.title_font = pygame.font.SysFont("arial", 42, bold=True)
        self.raycaster = Raycaster(settings.INTERNAL_RENDER_WIDTH, settings.INTERNAL_RENDER_HEIGHT)
        self.show_minimap = True
        self.running = True
        self.awaiting_difficulty_selection = True
        self.difficulty_ids = list(DIFFICULTY_IDS)
        default_id = settings.DEFAULT_DIFFICULTY_ID if settings.DEFAULT_DIFFICULTY_ID in self.difficulty_ids else "medium"
        self.difficulty_index = self.difficulty_ids.index(default_id)
        self.difficulty_id = self.difficulty_ids[self.difficulty_index]
        self.time_seconds = 0.0
        self.walk_time = 0.0
        self.move_amount = 0.0
        self.shot_cooldown = 0.0
        self.shot_anim_time = 0.0
        self.shot_anim_frames = [0]
        self.shot_anim_index = 0
        self.muzzle_flash = 0.0
        self.weapon_recoil = 0.0
        self.health = 100
        self.armor = 50
        self.ammo = 32
        self.pickup_message = ""
        self.pickup_message_timer = 0.0
        self.pickup_flash_timer = 0.0
        self.pickup_flash_color = (255, 220, 160)
        self.level_complete_timer = 0.0
        self.intermission_timer = 0.0
        self.intermission_data: dict[str, str | int] = {}
        self.damage_flash_timer = 0.0
        self.damage_flash_color = (255, 76, 58)
        self.player_death_timer = 0.0
        self.campaign_complete = False
        self.run_state: RunState | None = None
        self.sequence_director = CampaignSequenceDirector()
        self.ammo_pools = {
            "BULL": 60,
            "SHEL": self.ammo,
            "RCKT": 0,
            "CELL": 0,
        }
        self.owned_weapons = {"pistol", "shotgun", "sawedoff"}
        self.current_weapon_id = "pistol"
        self.level_start_snapshot = {
            "health": self.health,
            "armor": self.armor,
            "ammo": self.ammo,
            "ammo_pools": dict(self.ammo_pools),
            "owned_weapons": set(self.owned_weapons),
            "current_weapon_id": self.current_weapon_id,
        }
        self.selected_weapon_slot = WEAPON_DEFINITIONS[self.current_weapon_id].slot
        self.keys_owned: set[str] = set()
        self.face_panel_sprites = {
            "center": self._load_scaled_asset("doomguy_face_center.png", (124, 124)),
            "left": self._load_scaled_asset("doomguy_face_left.png", (124, 124)),
            "right": self._load_scaled_asset("doomguy_face_right.png", (124, 124)),
            "dead": self._load_scaled_asset("doomguy_face_dead.png", (124, 124)),
            "hit_light": self._load_scaled_asset("light_damage.png", (124, 124)),
            "hit_heavy": self._load_scaled_asset("heavy_damage.png", (124, 124)),
        }
        if self.face_panel_sprites["center"] is None:
            self.face_panel_sprites["center"] = self._load_scaled_asset("freedoom_face_panel.png", (124, 124))
        if self.face_panel_sprites["dead"] is None:
            self.face_panel_sprites["dead"] = self._load_scaled_asset("freedoom_skulface.png", (124, 124))
        self.face_idle_sequence = ("center", "left", "center", "right")
        self.face_hit_timer = 0.0
        self.face_hit_state = "hit_light"
        self.music_recent_shots = 0.0
        self.music_recent_damage = 0.0
        self.music_recent_kills = 0.0
        self.music_recent_event = 0.0
        self.music_seen_enemy_ids: set[str] = set()
        self.dev_start_level = dev_start_level
        self.dev_immortal = dev_immortal
        self.dev_auto_difficulty = dev_auto_difficulty
        self.pending_dev_level_index: int | None = None
        self.level_load_request_id = 0
        self.pending_level_load: PendingLevelLoad | None = None
        self._process_context = multiprocessing.get_context("spawn")

        self.world: World | None = None
        self.player: Player | None = None
        self.audio.start()
        self.music.start()
        if self.dev_auto_difficulty is not None:
            self._start_dev_session()

    def run(self) -> None:
        while self.running:
            delta_time = self.clock.tick(settings.FPS) / 1000.0
            self.time_seconds += delta_time
            self._handle_events()
            self._update(delta_time)
            self._render()

        self.audio.stop()
        self.music.stop()
        pygame.quit()

    def _generate_world(
        self,
        seed: int | None = None,
        generation_request: LevelGenerationRequest | None = None,
        runtime_pressure_bias: float | None = None,
        difficulty_id: str | None = None,
    ) -> World:
        if generation_request is not None:
            generated = _generate_map_payload(
                generation_request,
                difficulty_id or self.difficulty_id,
                self._enemy_difficulty_rating() if runtime_pressure_bias is None else runtime_pressure_bias,
            )
            return World.from_generated_map(generated)
        generator = MapGenerator(
            seed=seed,
            difficulty_id=difficulty_id or self.difficulty_id,
            runtime_pressure_bias=(
                self._enemy_difficulty_rating()
                if runtime_pressure_bias is None
                else runtime_pressure_bias
            ),
        )
        return World.from_generated_map(generator.generate())

    def start_run(self, difficulty_id: str, run_seed: int | None = None) -> None:
        self.difficulty_id = difficulty_id
        self.difficulty_index = self.difficulty_ids.index(difficulty_id)
        self.awaiting_difficulty_selection = False
        self.campaign_complete = False
        self._set_mouse_capture(True)
        self.health = settings.MAX_HEALTH
        self.armor = 50
        self.ammo = 32
        self.ammo_pools = {
            "BULL": 60,
            "SHEL": self.ammo,
            "RCKT": 0,
            "CELL": 0,
        }
        self.owned_weapons = {"pistol", "shotgun"}
        self.current_weapon_id = "pistol"
        self._sync_selected_weapon_slot()
        resolved_run_seed = run_seed if run_seed is not None else random.randrange(1, 999_999)
        self.run_state = self.sequence_director.build_run_state(difficulty_id, resolved_run_seed)
        self.load_campaign_level(1, preserve_player_state=False, show_intermission=False)

    def load_campaign_level(
        self,
        level_index: int,
        preserve_player_state: bool = True,
        show_intermission: bool = True,
    ) -> None:
        if self.run_state is None:
            raise RuntimeError("Campaign run state is not initialized.")
        if not preserve_player_state:
            self.health = settings.MAX_HEALTH
            self.armor = 50
            self.ammo = 32
            self.ammo_pools = {
                "BULL": 60,
                "SHEL": self.ammo,
                "RCKT": 0,
                "CELL": 0,
            }
            self.owned_weapons = {"pistol", "shotgun", "sawedoff"}
            self.current_weapon_id = "pistol"
            self._sync_selected_weapon_slot()

        generation_request = self.sequence_director.build_generation_request(self.run_state, level_index)
        clear_debug_log()
        self.level_load_request_id += 1
        loading_label = (
            "INITIALIZING NEW RUN"
            if level_index == 1 and not preserve_player_state
            else f"GENERATING LEVEL {level_index}"
        )
        task = PendingLevelLoad(
            request_id=self.level_load_request_id,
            level_index=level_index,
            preserve_player_state=preserve_player_state,
            show_intermission=show_intermission,
            generation_request=generation_request,
            difficulty_id=self.difficulty_id,
            runtime_pressure_bias=self._enemy_difficulty_rating(),
            loading_label=loading_label,
            started_at=self.time_seconds,
        )
        result_file = tempfile.NamedTemporaryFile(
            prefix=f"doom-level-{task.request_id:04d}-",
            suffix=".bin",
            delete=False,
        )
        result_file.close()
        task.result_path = result_file.name
        process = self._process_context.Process(
            target=_run_level_generation_process,
            args=(
                task.result_path,
                task.generation_request,
                task.difficulty_id,
                task.runtime_pressure_bias,
            ),
            name=f"level-load-{task.request_id}",
            daemon=True,
        )
        task.process = process
        self.pending_level_load = task
        self._draw_loading_screen()
        pygame.display.flip()
        pygame.event.pump()
        process.start()

    def _finalize_level_load(self, task: PendingLevelLoad, generated_map: GeneratedMap) -> None:
        self.world = World.from_generated_map(generated_map)
        self.raycaster.set_world(self.world)
        spawn_z = self.world.get_floor_height(*self.world.spawn)
        self.player = Player(*self.world.spawn, angle=math.radians(15), z=float(spawn_z))
        self.run_state.current_level_index = task.level_index
        self.run_state.current_level_seed = task.generation_request.per_level_seed
        self.keys_owned.clear()
        self.pickup_message = ""
        self.pickup_message_timer = 0.0
        self.pickup_flash_timer = 0.0
        self.level_complete_timer = 0.0
        self.intermission_timer = 1.6 if task.show_intermission else 0.0
        self.intermission_data = {
            "level_index": task.level_index,
            "total_level_count": self.run_state.total_level_count,
            "title": self.world.level_title,
            "subtitle": self.world.level_subtitle,
            "difficulty": self.difficulty_id.upper(),
            "seed": self.world.per_level_seed,
        }
        self.damage_flash_timer = 0.0
        self.player_death_timer = 0.0
        self.face_hit_timer = 0.0
        self.face_hit_state = "hit_light"
        self.music_recent_shots = 0.0
        self.music_recent_damage = 0.0
        self.music_recent_kills = 0.0
        self.music_recent_event = 0.0
        self.music_seen_enemy_ids.clear()
        self._reset_weapon_state()
        self.level_start_snapshot = {
            "health": self.health,
            "armor": self.armor,
            "ammo": self.ammo,
            "ammo_pools": dict(self.ammo_pools),
            "owned_weapons": set(self.owned_weapons),
            "current_weapon_id": self.current_weapon_id,
        }
        append_debug_log(
            "campaign-level-load "
            f"run_seed={self.run_state.run_seed} "
            f"level={self.world.level_index}/{self.run_state.total_level_count} "
            f"archetype={self.world.level_archetype_id} "
            f"skeleton={self.world.skeleton_profile_id} "
            f"seed={self.world.per_level_seed}"
        )
        self._apply_dev_loadout()

    def _cancel_pending_level_load(self) -> None:
        task = self.pending_level_load
        self.pending_level_load = None
        if task is None:
            return
        if task.process is not None and task.process.is_alive():
            task.process.terminate()
            task.process.join(timeout=0.2)
        if task.result_path:
            try:
                os.remove(task.result_path)
            except FileNotFoundError:
                pass

    def _finish_pending_level_load(self) -> None:
        task = self.pending_level_load
        if task is None or task.process is None:
            return
        if task.process.is_alive():
            return
        task.process.join(timeout=0.2)
        if not task.result_path or not os.path.exists(task.result_path):
            status, payload = "error", "Level generation process exited without producing a result file."
        else:
            with open(task.result_path, "rb") as result_file:
                status, payload = pickle.load(result_file)
            try:
                os.remove(task.result_path)
            except FileNotFoundError:
                pass
        self.pending_level_load = None
        if status != "ok":
            self.awaiting_difficulty_selection = True
            self.run_state = None
            self.world = None
            self.player = None
            self.campaign_complete = False
            self._set_mouse_capture(False)
            append_debug_log(f"campaign-level-load-failed\n{payload}")
            self._show_message("LEVEL GENERATION FAILED", (255, 112, 96))
            return
        self._finalize_level_load(task, payload)
        if self.pending_dev_level_index is not None and self.run_state is not None:
            target_level = self.pending_dev_level_index
            if task.level_index != target_level:
                self.pending_dev_level_index = None
                self.load_campaign_level(
                    target_level,
                    preserve_player_state=True,
                    show_intermission=False,
                )
                return
            self.pending_dev_level_index = None

    def advance_to_next_level(self) -> None:
        if self.run_state is None or self.world is None:
            return
        current_level = self.run_state.current_level_index
        if current_level not in self.run_state.completed_levels:
            self.run_state.completed_levels.append(current_level)
        if current_level >= self.run_state.total_level_count:
            self.campaign_complete = True
            self.intermission_timer = 0.0
            self._set_mouse_capture(False)
            self._show_message("CAMPAIGN CLEAR", (120, 255, 168))
            return
        self.load_campaign_level(current_level + 1, preserve_player_state=True, show_intermission=True)

    def restart_current_level_after_death(self) -> None:
        if self.run_state is None:
            return
        self.health = self.level_start_snapshot["health"]
        self.armor = self.level_start_snapshot["armor"]
        self.ammo = self.level_start_snapshot["ammo"]
        self.ammo_pools = dict(self.level_start_snapshot["ammo_pools"])
        self.owned_weapons = set(self.level_start_snapshot.get("owned_weapons", {"shotgun"}))
        self.current_weapon_id = str(self.level_start_snapshot.get("current_weapon_id", "shotgun"))
        if self.current_weapon_id not in self.owned_weapons:
            self.current_weapon_id = "pistol" if "pistol" in self.owned_weapons else "shotgun"
        self._sync_selected_weapon_slot()
        self.load_campaign_level(
            self.run_state.current_level_index,
            preserve_player_state=True,
            show_intermission=False,
        )

    def _enemy_difficulty_rating(self) -> float:
        health = getattr(self, "health", settings.MAX_HEALTH) / max(1, settings.MAX_HEALTH)
        armor = getattr(self, "armor", 0) / max(1, settings.MAX_ARMOR)
        ammo = getattr(self, "ammo", 0) / max(1, settings.MAX_SHELLS)
        rating = (
            1.0
            + (health - 0.65) * settings.ENEMY_DIFFICULTY_HEALTH_WEIGHT
            + (armor - 0.2) * settings.ENEMY_DIFFICULTY_ARMOR_WEIGHT
            + (ammo - 0.24) * settings.ENEMY_DIFFICULTY_AMMO_WEIGHT
        )
        return max(settings.ENEMY_DIFFICULTY_MIN, min(settings.ENEMY_DIFFICULTY_MAX, rating))

    def _set_mouse_capture(self, enabled: bool) -> None:
        self.mouse_captured = enabled
        pygame.event.set_grab(enabled)
        pygame.mouse.set_visible(not enabled)
        pygame.mouse.get_rel()
        self.mouse_delta_x = 0.0

    def _load_scaled_asset(self, asset_name: str, size: tuple[int, int]) -> pygame.Surface | None:
        path = Path(__file__).resolve().parent.parent / "assets" / asset_name
        if not path.exists():
            return None
        image = pygame.image.load(str(path)).convert_alpha()
        return pygame.transform.scale(image, size)

    def _current_face_sprite(self) -> pygame.Surface | None:
        if self.health <= 0:
            return self.face_panel_sprites.get("dead") or self.face_panel_sprites.get("center")
        if self.face_hit_timer > 0.0:
            return (
                self.face_panel_sprites.get(self.face_hit_state)
                or self.face_panel_sprites.get("center")
                or self.face_panel_sprites.get("dead")
            )

        frame = int(self.time_seconds * 2.4) % len(self.face_idle_sequence)
        state = self.face_idle_sequence[frame]
        return (
            self.face_panel_sprites.get(state)
            or self.face_panel_sprites.get("center")
            or self.face_panel_sprites.get("dead")
        )

    def _sync_selected_weapon_slot(self) -> None:
        self.selected_weapon_slot = WEAPON_DEFINITIONS[self.current_weapon_id].slot

    def _current_weapon_definition(self) -> WeaponDefinition:
        return WEAPON_DEFINITIONS[self.current_weapon_id]

    def _current_weapon_ammo(self) -> int:
        return self.ammo_pools.get(self._current_weapon_definition().ammo_pool, 0)

    def _available_weapon_ids(self) -> list[str]:
        return sorted(self.owned_weapons, key=lambda weapon_id: WEAPON_DEFINITIONS[weapon_id].slot)

    def _switch_weapon(self, weapon_id: str, announce: bool = False) -> None:
        if weapon_id not in self.owned_weapons or weapon_id == self.current_weapon_id:
            return
        self.current_weapon_id = weapon_id
        self._sync_selected_weapon_slot()
        self.shot_anim_frames = [0]
        self.shot_anim_index = 0
        self.shot_anim_time = 0.0
        self.muzzle_flash = 0.0
        self.weapon_recoil = min(self.weapon_recoil, 0.18)
        if announce:
            weapon = WEAPON_DEFINITIONS[weapon_id]
            self._show_message(f"{weapon.pickup_name} READY", (232, 198, 118))

    def _select_weapon_by_slot(self, slot: int, announce: bool = False) -> None:
        for weapon_id, weapon in WEAPON_DEFINITIONS.items():
            if weapon.slot == slot and weapon_id in self.owned_weapons:
                self._switch_weapon(weapon_id, announce=announce)
                return

    def _cycle_weapon(self, direction: int) -> None:
        weapons = self._available_weapon_ids()
        if len(weapons) <= 1:
            return
        current_index = weapons.index(self.current_weapon_id)
        next_index = (current_index + direction) % len(weapons)
        self._switch_weapon(weapons[next_index], announce=True)

    def _begin_run_with_difficulty(self, difficulty_id: str) -> None:
        self.start_run(difficulty_id)

    def _apply_dev_loadout(self) -> None:
        if self.run_state is None:
            return
        if not self.dev_immortal and self.dev_start_level is None:
            return
        self.health = settings.MAX_HEALTH
        self.armor = settings.MAX_ARMOR
        self.ammo = settings.MAX_SHELLS
        self.ammo_pools = {
            "BULL": 400,
            "SHEL": settings.MAX_SHELLS,
            "RCKT": 99,
            "CELL": 300,
        }
        self.owned_weapons = {"pistol", "shotgun", "sawedoff", "chaingun"}
        self.current_weapon_id = "chaingun"
        self._sync_selected_weapon_slot()
        self.level_start_snapshot = {
            "health": self.health,
            "armor": self.armor,
            "ammo": self.ammo,
            "ammo_pools": dict(self.ammo_pools),
            "owned_weapons": set(self.owned_weapons),
            "current_weapon_id": self.current_weapon_id,
        }

    def _start_dev_session(self) -> None:
        difficulty_id = (
            self.dev_auto_difficulty
            if self.dev_auto_difficulty in self.difficulty_ids
            else self.difficulty_ids[-1]
        )
        self.start_run(difficulty_id)
        if self.dev_start_level is not None and self.dev_start_level > 1:
            self.pending_dev_level_index = min(
                max(1, self.dev_start_level),
                self.run_state.total_level_count if self.run_state is not None else self.dev_start_level,
            )
        else:
            self.pending_dev_level_index = None
        self._show_message("DEV MODE - LEVEL 5 IMMORTAL", (132, 236, 255))

    def _draw_difficulty_menu(self) -> None:
        self.screen.fill((10, 8, 12))
        panel = pygame.Rect(settings.SCREEN_WIDTH // 2 - 260, settings.SCREEN_HEIGHT // 2 - 180, 520, 360)
        pygame.draw.rect(self.screen, (28, 16, 16), panel, border_radius=8)
        pygame.draw.rect(self.screen, (146, 108, 72), panel, 3, border_radius=8)

        title = self.title_font.render("SELECT DIFFICULTY", True, (244, 218, 160))
        subtitle = self.small_font.render("Difficulty changes encounter pressure, ambush density, and resources.", True, (204, 188, 152))
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 44)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 82)))

        for idx, difficulty_id in enumerate(self.difficulty_ids):
            definition = get_difficulty_definition(difficulty_id)
            row = pygame.Rect(panel.x + 34, panel.y + 118 + idx * 68, panel.width - 68, 54)
            active = idx == self.difficulty_index
            fill = (96, 34, 26) if active else (44, 26, 24)
            border = (236, 188, 132) if active else (122, 96, 80)
            pygame.draw.rect(self.screen, fill, row, border_radius=6)
            pygame.draw.rect(self.screen, border, row, 2, border_radius=6)
            label = self.font.render(f"{idx + 1}. {definition.label}", True, (255, 236, 186))
            pressure = self.small_font.render(
                f"Enemies x{definition.enemy_count_scale:.2f}  |  ambush {int(definition.ambush_probability * 100)}%  |  pickups x{definition.pickup_density_scale:.2f}",
                True,
                (214, 198, 164),
            )
            self.screen.blit(label, (row.x + 14, row.y + 8))
            self.screen.blit(pressure, (row.x + 14, row.y + 30))

        footer = self.small_font.render("Arrow keys / 1-3 to choose, Enter to start", True, (188, 170, 136))
        self.screen.blit(footer, footer.get_rect(center=(panel.centerx, panel.bottom - 24)))

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif self.pending_level_load is not None:
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_F2:
                    self.awaiting_difficulty_selection = True
                    self.campaign_complete = False
                    self.run_state = None
                    self.world = None
                    self.player = None
                    self.pending_dev_level_index = None
                    self._cancel_pending_level_load()
                    self._set_mouse_capture(False)
            elif self.awaiting_difficulty_selection:
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key in (pygame.K_UP, pygame.K_w):
                    self.difficulty_index = (self.difficulty_index - 1) % len(self.difficulty_ids)
                    self.difficulty_id = self.difficulty_ids[self.difficulty_index]
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    self.difficulty_index = (self.difficulty_index + 1) % len(self.difficulty_ids)
                    self.difficulty_id = self.difficulty_ids[self.difficulty_index]
                elif event.key in (pygame.K_1, pygame.K_KP1):
                    self._begin_run_with_difficulty(self.difficulty_ids[0])
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    self._begin_run_with_difficulty(self.difficulty_ids[1])
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    self._begin_run_with_difficulty(self.difficulty_ids[2])
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._begin_run_with_difficulty(self.difficulty_id)
            elif event.type == pygame.MOUSEMOTION and self.mouse_captured:
                self.mouse_delta_x += event.rel[0]
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_F2:
                    self.awaiting_difficulty_selection = True
                    self.campaign_complete = False
                    self.run_state = None
                    self._set_mouse_capture(False)
                elif event.key == pygame.K_r:
                    self.restart_current_level_after_death()
                elif event.key == pygame.K_e:
                    if self.campaign_complete:
                        continue
                    self._try_use_door()
                elif event.key == pygame.K_SPACE and self.mouse_captured:
                    self.player.jump(self.world)
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    self._select_weapon_by_slot(2)
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    self._select_weapon_by_slot(3)
                elif event.key in (pygame.K_4, pygame.K_KP4):
                    self._select_weapon_by_slot(4)
                elif event.key in (pygame.K_5, pygame.K_KP5):
                    self._select_weapon_by_slot(5)
                elif event.key == pygame.K_TAB:
                    self.show_minimap = not self.show_minimap
            elif event.type == pygame.WINDOWFOCUSGAINED:
                self._set_mouse_capture(True)
            elif event.type == pygame.WINDOWFOCUSLOST:
                self.mouse_delta_x = 0.0
            elif event.type == pygame.MOUSEBUTTONDOWN and not self.mouse_captured:
                self._set_mouse_capture(True)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.mouse_captured:
                self._try_fire()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 4 and self.mouse_captured:
                self._cycle_weapon(-1)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 5 and self.mouse_captured:
                self._cycle_weapon(1)

    def _update(self, delta_time: float) -> None:
        self._decay_music_impulses(delta_time)
        self._finish_pending_level_load()
        if self.pending_level_load is not None:
            self.music.update(MusicSnapshot(), delta_time)
            return
        if self.awaiting_difficulty_selection or self.world is None or self.player is None:
            self.music.update(MusicSnapshot(), delta_time)
            return
        if self.campaign_complete:
            self.music.update(MusicSnapshot(), delta_time)
            return
        if self.intermission_timer > 0.0:
            self.intermission_timer = max(0.0, self.intermission_timer - delta_time)
        if self.player_death_timer > 0.0:
            self.player_death_timer = max(0.0, self.player_death_timer - delta_time)
            self.damage_flash_timer = max(0.0, self.damage_flash_timer - delta_time * 2.6)
            self._update_music_events()
            self.music.update(self._build_music_snapshot(), delta_time)
            if self.player_death_timer <= 0.0:
                self.restart_current_level_after_death()
            return
        if self.level_complete_timer > 0.0:
            self.level_complete_timer = max(0.0, self.level_complete_timer - delta_time)
            self._update_music_events()
            self.music.update(self._build_music_snapshot(), delta_time)
            if self.level_complete_timer <= 0.0:
                self.advance_to_next_level()
            return
        keys = pygame.key.get_pressed()

        forward = float(keys[pygame.K_w] or keys[pygame.K_UP]) - float(keys[pygame.K_s] or keys[pygame.K_DOWN])
        strafe = float(keys[pygame.K_d]) - float(keys[pygame.K_a])

        mouse_dx = self.mouse_delta_x
        self.mouse_delta_x = 0.0
        self.player.rotate_by(mouse_dx * settings.MOUSE_SENSITIVITY)
        self.player.move(forward, strafe, self.world, delta_time)
        self.player.update_elevation(self.world, delta_time)
        self.world.update(delta_time, self.player, self._apply_player_damage, self.audio)
        self._collect_keys()
        self._collect_loot()
        self._check_level_exit()
        self.ammo_pools["SHEL"] = self.ammo
        if self.mouse_captured and pygame.mouse.get_pressed(num_buttons=3)[0]:
            if self._current_weapon_definition().automatic:
                self._try_fire()
        self._update_weapon_state(delta_time)
        self.pickup_message_timer = max(0.0, self.pickup_message_timer - delta_time)
        self.pickup_flash_timer = max(0.0, self.pickup_flash_timer - delta_time * 2.8)
        self.damage_flash_timer = max(0.0, self.damage_flash_timer - delta_time * 2.8)
        self.face_hit_timer = max(0.0, self.face_hit_timer - delta_time)
        if self.pickup_message_timer <= 0.0:
            self.pickup_message = ""

        self.move_amount = self.player.speed_ratio
        if self.move_amount > 0.0:
            self.walk_time += delta_time * (3.2 + self.move_amount * 8.4)
            self.ammo = max(0, self.ammo - 0)
        self._update_music_events()
        self.music.update(self._build_music_snapshot(), delta_time)

    def _render(self) -> None:
        if self.pending_level_load is not None:
            self._draw_loading_screen()
            pygame.display.flip()
            return
        if self.awaiting_difficulty_selection or self.world is None or self.player is None:
            self._draw_difficulty_menu()
            pygame.display.flip()
            return
        self.scene_surface.fill((0, 0, 0))
        self.raycaster.render(
            self.scene_surface,
            self.world,
            self.player,
            self.time_seconds,
            self.walk_time,
            self.move_amount,
            self.current_weapon_id,
            self.shot_anim_frames[self.shot_anim_index],
            self.muzzle_flash,
            self.weapon_recoil,
            self.player.jump_offset,
        )
        scaled_scene = pygame.transform.scale(
            self.scene_surface, (settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
        )
        self.screen.blit(scaled_scene, (0, 0))
        self._draw_damage_flash()
        self._draw_pickup_flash()
        if self.show_minimap:
            self._draw_minimap()
        self._draw_pickup_message()
        self._draw_hud()
        self._draw_interact_debug()
        if self.intermission_timer > 0.0:
            self._draw_intermission_overlay()
        if self.campaign_complete:
            self._draw_campaign_complete_overlay()
        pygame.display.flip()

    def _draw_loading_screen(self) -> None:
        task = self.pending_level_load
        self.screen.fill((8, 6, 10))
        overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((20, 10, 10, 186))
        self.screen.blit(overlay, (0, 0))

        panel = pygame.Rect(
            settings.SCREEN_WIDTH // 2 - 280,
            settings.SCREEN_HEIGHT // 2 - 120,
            560,
            240,
        )
        pygame.draw.rect(self.screen, (28, 16, 16), panel, border_radius=8)
        pygame.draw.rect(self.screen, (166, 124, 84), panel, 3, border_radius=8)

        title = self.title_font.render("PROCEDURAL GENERATION", True, (248, 226, 172))
        subtitle = self.font.render("Building level layout. Please wait...", True, (214, 194, 154))
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 54)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 96)))

        if task is not None:
            level_line = self.font.render(task.loading_label, True, (236, 208, 152))
            meta = self.small_font.render(
                f"Difficulty {task.difficulty_id.upper()}  |  level {task.level_index}  |  seed {task.generation_request.per_level_seed}",
                True,
                (188, 170, 136),
            )
            elapsed = max(0.0, self.time_seconds - task.started_at)
            elapsed_line = self.small_font.render(
                f"Elapsed {elapsed:0.1f}s",
                True,
                (188, 170, 136),
            )
            self.screen.blit(level_line, level_line.get_rect(center=(panel.centerx, panel.y + 138)))
            self.screen.blit(meta, meta.get_rect(center=(panel.centerx, panel.y + 174)))
            self.screen.blit(elapsed_line, elapsed_line.get_rect(center=(panel.centerx, panel.y + 198)))

        pulse = 0.5 + 0.5 * math.sin(self.time_seconds * 4.0)
        bar_rect = pygame.Rect(panel.x + 74, panel.bottom - 42, panel.width - 148, 14)
        pygame.draw.rect(self.screen, (42, 28, 24), bar_rect, border_radius=5)
        pygame.draw.rect(self.screen, (122, 96, 72), bar_rect, 2, border_radius=5)
        fill_width = max(28, int((bar_rect.width - 4) * (0.18 + pulse * 0.64)))
        fill_rect = pygame.Rect(bar_rect.x + 2, bar_rect.y + 2, fill_width, bar_rect.height - 4)
        pygame.draw.rect(self.screen, (198, 78, 58), fill_rect, border_radius=4)

    def _draw_minimap(self) -> None:
        scale = settings.MINIMAP_SCALE
        pad = settings.MINIMAP_MARGIN
        width = self.world.width * scale
        height = self.world.height * scale
        minimap = pygame.Surface((width, height), pygame.SRCALPHA)
        minimap.fill((8, 8, 8, 170))

        for y, row in enumerate(self.world.tiles):
            for x, tile in enumerate(row):
                if tile:
                    color = (148, 76, 54)
                else:
                    level = self.world.floor_heights[y][x]
                    sector_type = self.world.get_sector_type_at(x, y)
                    if sector_type == 1:
                        color = (72, 182, 96)
                    elif sector_type == 2:
                        color = (202, 186, 118)
                    elif self.world.is_stair_at(x, y):
                        color = (196, 176, 84)
                    else:
                        shade = min(220, 34 + level * 38)
                        color = (24 + level * 16, shade // 2, shade)
                pygame.draw.rect(minimap, color, (x * scale, y * scale, scale - 1, scale - 1))

        for door in self.world.doors:
            if door.is_open:
                continue
            door_color = door.definition.visual.minimap_color
            if door.orientation == "vertical":
                start = (int((door.grid_x + 0.5) * scale), door.grid_y * scale + 1)
                end = (int((door.grid_x + 0.5) * scale), (door.grid_y + 1) * scale - 1)
            else:
                start = (door.grid_x * scale + 1, int((door.grid_y + 0.5) * scale))
                end = ((door.grid_x + 1) * scale - 1, int((door.grid_y + 0.5) * scale))
            pygame.draw.line(minimap, door_color, start, end, max(2, scale // 3))

        if settings.DEV_MODE:
            for key in self.world.active_keys():
                key_color = key.definition.visual.hud_color
                pygame.draw.circle(minimap, key_color, (int(key.x * scale), int(key.y * scale)), max(2, scale // 3))
                pygame.draw.circle(minimap, (255, 250, 220), (int(key.x * scale), int(key.y * scale)), max(2, scale // 3), 1)

        if self.world.exit_zone is not None:
            exit_color = (120, 255, 168) if self.world.is_exit_active() else (64, 108, 84)
            exit_pos = (int(self.world.exit_zone.x * scale), int(self.world.exit_zone.y * scale))
            pygame.draw.circle(minimap, exit_color, exit_pos, max(3, scale // 2), 1)

        for loot in self.world.active_loot():
            lx = int(loot.x * scale)
            ly = int(loot.y * scale)
            loot_color = loot.definition.visual.minimap_color
            pygame.draw.circle(minimap, loot_color, (lx, ly), max(2, scale // 3))
            pygame.draw.circle(minimap, (255, 244, 220), (lx, ly), max(2, scale // 3), 1)

        for switch in self.world.active_switches():
            sx = int(switch.x * scale)
            sy = int(switch.y * scale)
            pygame.draw.rect(minimap, (98, 232, 176), (sx - 2, sy - 2, 5, 5))

        if settings.DEV_MODE:
            for secret in self.world.secrets:
                sx = int(secret.x * scale)
                sy = int(secret.y * scale)
                pygame.draw.circle(minimap, (228, 194, 98), (sx, sy), max(2, scale // 3), 1)

        px = self.player.x * scale
        py = self.player.y * scale
        pygame.draw.circle(minimap, (255, 230, 164), (int(px), int(py)), max(2, scale // 3))
        facing_x = px + math.cos(self.player.angle) * scale * 2.4
        facing_y = py + math.sin(self.player.angle) * scale * 2.4
        pygame.draw.line(minimap, (255, 230, 164), (px, py), (facing_x, facing_y), 2)

        self.screen.blit(minimap, (pad, pad))
        pygame.draw.rect(self.screen, (222, 192, 128), (pad - 2, pad - 2, width + 4, height + 4), 2)

    def _reset_weapon_state(self) -> None:
        self.shot_cooldown = 0.0
        self.shot_anim_time = 0.0
        self.shot_anim_frames = [0]
        self.shot_anim_index = 0
        self.muzzle_flash = 0.0
        self.weapon_recoil = 0.0

    def _try_fire(self) -> None:
        if self.player_death_timer > 0.0 or self.campaign_complete:
            return
        weapon = self._current_weapon_definition()
        current_ammo = self.ammo_pools.get(weapon.ammo_pool, 0)
        if self.shot_cooldown > 0.0 or current_ammo < weapon.ammo_per_shot:
            if current_ammo < weapon.ammo_per_shot:
                self.audio.play_empty_click()
                self.shot_cooldown = max(self.shot_cooldown, 0.08)
            return
        self.ammo_pools[weapon.ammo_pool] = max(0, current_ammo - weapon.ammo_per_shot)
        self.ammo = self.ammo_pools["SHEL"]
        self.shot_cooldown = weapon.cooldown
        self.shot_anim_time = 0.0
        self.shot_anim_frames = list(weapon.anim_frames)
        self.shot_anim_index = 0
        self.muzzle_flash = 1.0 if weapon.weapon_id in {"shotgun", "sawedoff"} else 0.82
        self.weapon_recoil = weapon.recoil
        self._bump_music_impulse("music_recent_shots", 0.42 if weapon.weapon_id in {"shotgun", "sawedoff"} else 0.26)
        if weapon.audio_key == "pistol_fire":
            self.audio.play_pistol_fire()
        elif weapon.audio_key == "sawedoff_fire":
            self.audio.play_sawedoff_fire()
        elif weapon.audio_key == "chaingun_fire":
            self.audio.play_chaingun_fire()
        else:
            self.audio.play_shotgun_fire()
        self.world.emit_noise(
            self.player.x,
            self.player.y,
            settings.ENEMY_GUNSHOT_NOISE_RADIUS,
            settings.ENEMY_GUNSHOT_NOISE_TIME,
        )
        self._fire_hitscan(weapon)

    def _update_weapon_state(self, delta_time: float) -> None:
        weapon = self._current_weapon_definition()
        if self.shot_cooldown > 0.0:
            self.shot_cooldown = max(0.0, self.shot_cooldown - delta_time)

        if len(self.shot_anim_frames) > 1:
            self.shot_anim_time += delta_time * settings.SHOT_ANIM_FPS
            frame = min(len(self.shot_anim_frames) - 1, int(self.shot_anim_time))
            self.shot_anim_index = frame
            if frame >= len(self.shot_anim_frames) - 1 and self.shot_anim_time >= len(self.shot_anim_frames) - 0.05:
                self.shot_anim_frames = [0]
                self.shot_anim_index = 0
                self.shot_anim_time = 0.0

        self.muzzle_flash = max(0.0, self.muzzle_flash - delta_time * settings.SHOT_FLASH_DECAY)
        recoil_decay = 4.2 if weapon.weapon_id in {"shotgun", "sawedoff"} else 5.4
        self.weapon_recoil = max(0.0, self.weapon_recoil - delta_time * recoil_decay)

    def _fire_hitscan(self, weapon: WeaponDefinition) -> None:
        shot_angle = self.player.angle
        if weapon.spread > 0.0:
            shot_angle += random.uniform(-weapon.spread, weapon.spread)
        ray_x = math.cos(shot_angle)
        ray_y = math.sin(shot_angle)
        self.world.register_player_shot(
            self.player.x,
            self.player.y,
            ray_x,
            ray_y,
            settings.MAX_RAY_DISTANCE,
        )
        impact = self.world.resolve_hitscan(self.player.x, self.player.y, ray_x, ray_y, damage=weapon.damage)
        if impact.enemy is None:
            return
        if impact.enemy.enemy_type in {"warden", "cyberdemon"} and impact.enemy_killed:
            boss_name = "CYBERDEMON" if impact.enemy.enemy_type == "cyberdemon" else "WARDEN"
            self._show_message(f"{boss_name} DOWN - FINAL DOOR UNLOCKED", (255, 182, 104))
        if impact.enemy_killed:
            self._bump_music_impulse("music_recent_kills", 0.34)
            if impact.enemy.enemy_type == "cyberdemon":
                self._bump_music_impulse("music_recent_event", 0.82)
            elif impact.enemy.enemy_type == "warden":
                self._bump_music_impulse("music_recent_event", 0.58)
            elif impact.enemy.enemy_type == "cacodemon":
                self._bump_music_impulse("music_recent_event", 0.34)
            elif impact.enemy.enemy_type == "heavy":
                self._bump_music_impulse("music_recent_event", 0.22)
            self.audio.play_enemy_death(impact.enemy.enemy_type)
            self._trigger_damage_flash((255, 126, 96), settings.ENEMY_HIT_FLASH_TIME)
        elif impact.enemy_pain:
            self.audio.play_enemy_pain(impact.enemy.enemy_type)
            self._trigger_damage_flash((236, 170, 110), settings.ENEMY_HIT_FLASH_TIME * 0.9)
        else:
            self.audio.play_enemy_attack_hit(impact.enemy.enemy_type)
            self._trigger_damage_flash((224, 144, 94), settings.ENEMY_HIT_FLASH_TIME * 0.7)

    def _collect_loot(self) -> None:
        for loot in self.world.active_loot():
            if math.hypot(loot.x - self.player.x, loot.y - self.player.y) > settings.PICKUP_RADIUS:
                continue
            if not self.world.has_line_of_sight(self.player.x, self.player.y, loot.x, loot.y):
                continue
            message = self._apply_loot(loot.kind, loot.amount)
            if message is None:
                continue
            loot.collected = True
            self._show_message(message, loot.definition.visual.glow_color)
            self.audio.play_pickup()

    def _collect_keys(self) -> None:
        if self.world is None or self.player is None:
            return
        for key in self.world.active_keys():
            if math.hypot(key.x - self.player.x, key.y - self.player.y) > settings.PICKUP_RADIUS:
                continue
            if not self.world.has_line_of_sight(self.player.x, self.player.y, key.x, key.y):
                continue
            if key.key_type in self.keys_owned:
                key.collected = True
                continue
            key.collected = True
            self.keys_owned.add(key.key_type)
            append_debug_log(
                "key-picked "
                f"key_id={key.key_id} "
                f"key_type={key.key_type} "
                f"pos=({key.x:.2f},{key.y:.2f}) "
                f"owned={sorted(self.keys_owned)}"
            )
            self._show_message(key.definition.pickup_message, key.definition.visual.glow_color)
            self.audio.play_key_pickup()
            for message in self.world.handle_key_pickup(key.key_type, audio=self.audio):
                self._show_message(message, key.definition.visual.glow_color)

    def _try_use_door(self) -> None:
        if self.world is None or self.player is None:
            return
        switch, switch_messages, activated = self.world.interact_with_switch(
            self.player.x,
            self.player.y,
            self.player.angle,
            audio=self.audio,
        )
        if activated and switch is not None:
            self._show_message(switch.label, (120, 240, 176))
            for message in switch_messages:
                self._show_message(message, (236, 210, 140))
            return
        door, message, opened = self.world.interact_with_door(
            self.player.x,
            self.player.y,
            self.player.angle,
            self.keys_owned,
        )
        if door is None:
            append_debug_log(
                "door-interact-none "
                f"player=({self.player.x:.2f},{self.player.y:.2f}) "
                f"angle={self.player.angle:.3f} "
                f"owned={sorted(self.keys_owned)}"
            )
            return
        append_debug_log(
            "door-interact-result "
            f"door_id={door.door_id} "
            f"door_type={door.door_type} "
            f"state={door.state} "
            f"trigger_unlocked={door.trigger_unlocked} "
            f"required_trigger_id={door.required_trigger_id} "
            f"opened={opened} "
            f"message={message!r} "
            f"owned={sorted(self.keys_owned)}"
        )
        if opened:
            self.audio.play_door_open(door.door_type)
            return
        if message:
            self._show_message(message, door.definition.visual.accent_color)
            self.audio.play_door_locked()

    def _check_level_exit(self) -> None:
        if self.level_complete_timer > 0.0:
            return
        if not self.world.is_player_in_exit(self.player.x, self.player.y):
            return
        self.level_complete_timer = 0.7
        self.audio.play_level_exit()
        if self.run_state is not None and self.run_state.current_level_index >= self.run_state.total_level_count:
            self._show_message("FINAL GATE CLEARED", (120, 255, 168))
        else:
            self._show_message("LEVEL CLEAR", (120, 255, 168))

    def _reset_level(self, seed: int, reroll_stats: bool) -> None:
        if reroll_stats:
            self.ammo = random.randint(18, 48)
            self.armor = random.choice((0, 25, 50, 100))
            self.ammo_pools["SHEL"] = self.ammo
        self.world = self._generate_world(seed=seed)
        self.raycaster.set_world(self.world)
        spawn_z = self.world.get_floor_height(*self.world.spawn)
        self.player = Player(*self.world.spawn, angle=math.radians(15), z=float(spawn_z))
        self.keys_owned.clear()
        self.level_complete_timer = 0.0
        self.intermission_timer = 0.0
        self.player_death_timer = 0.0
        self._reset_weapon_state()

    def _apply_loot(self, kind: str, amount: int) -> str | None:
        if kind == "pistol":
            gained_weapon = "pistol" not in self.owned_weapons
            if gained_weapon:
                self.owned_weapons.add("pistol")
            bullets_before = self.ammo_pools["BULL"]
            self.ammo_pools["BULL"] = min(settings.MAX_BULLETS, bullets_before + amount)
            if not gained_weapon and self.ammo_pools["BULL"] == bullets_before:
                return None
            self._switch_weapon("pistol")
            return "FOUND THE PISTOL" if gained_weapon else f"PISTOL AMMO +{self.ammo_pools['BULL'] - bullets_before}"
        if kind == "chaingun":
            gained_weapon = "chaingun" not in self.owned_weapons
            if gained_weapon:
                self.owned_weapons.add("chaingun")
            bullets_before = self.ammo_pools["BULL"]
            self.ammo_pools["BULL"] = min(settings.MAX_BULLETS, bullets_before + amount)
            if not gained_weapon and self.ammo_pools["BULL"] == bullets_before:
                return None
            self._switch_weapon("chaingun")
            return "FOUND THE CHAINGUN" if gained_weapon else f"CHAINGUN AMMO +{self.ammo_pools['BULL'] - bullets_before}"
        if kind == "sawedoff":
            gained_weapon = "sawedoff" not in self.owned_weapons
            if gained_weapon:
                self.owned_weapons.add("sawedoff")
            shells_before = self.ammo_pools["SHEL"]
            self.ammo_pools["SHEL"] = min(settings.MAX_SHELLS, shells_before + amount)
            self.ammo = self.ammo_pools["SHEL"]
            if not gained_weapon and self.ammo_pools["SHEL"] == shells_before:
                return None
            self._switch_weapon("sawedoff")
            return "FOUND THE SAWED-OFF" if gained_weapon else f"SAWED-OFF AMMO +{self.ammo_pools['SHEL'] - shells_before}"
        definition = get_pickup_definition(kind)
        current_value = self._get_pickup_stat(definition.effect.stat)
        result = definition.effect.apply(current_value, amount)
        if result is None:
            return None
        new_value, message = result
        self._set_pickup_stat(definition.effect.stat, new_value)
        return message

    def _get_pickup_stat(self, stat: str) -> int:
        if stat == "health":
            return self.health
        if stat == "armor":
            return self.armor
        if stat == "ammo":
            return self.ammo
        if stat == "bullets":
            return self.ammo_pools["BULL"]
        raise ValueError(f"Unsupported pickup stat: {stat}")

    def _set_pickup_stat(self, stat: str, value: int) -> None:
        if stat == "health":
            self.health = min(settings.MAX_HEALTH, max(0, value))
            return
        if stat == "armor":
            self.armor = min(settings.MAX_ARMOR, max(0, value))
            return
        if stat == "ammo":
            self.ammo = min(settings.MAX_SHELLS, max(0, value))
            self.ammo_pools["SHEL"] = self.ammo
            return
        if stat == "bullets":
            self.ammo_pools["BULL"] = min(settings.MAX_BULLETS, max(0, value))
            return
        raise ValueError(f"Unsupported pickup stat: {stat}")

    def _show_message(self, message: str, color: tuple[int, int, int]) -> None:
        self.pickup_message = message
        self.pickup_message_timer = 1.8
        self.pickup_flash_timer = 0.85
        self.pickup_flash_color = color

    def _trigger_damage_flash(self, color: tuple[int, int, int], duration: float) -> None:
        self.damage_flash_color = color
        self.damage_flash_timer = max(self.damage_flash_timer, duration)

    def _apply_player_damage(self, amount: int, source: str) -> None:
        if amount <= 0 or self.player_death_timer > 0.0:
            return
        self._bump_music_impulse("music_recent_damage", min(1.0, amount / 30.0))
        if self.dev_immortal:
            self.audio.play_player_hit()
            if source == "acid":
                self._show_message("ACID BURNS", (132, 236, 118))
            self.face_hit_state = "hit_heavy" if amount >= 18 else "hit_light"
            self.face_hit_timer = 0.32 if amount >= 18 else 0.18
            flash_color = (148, 236, 88) if source == "acid" else (255, 72, 52)
            self._trigger_damage_flash(flash_color, settings.PLAYER_DAMAGE_FLASH_TIME)
            return
        absorbed = min(self.armor, int(math.ceil(amount * settings.PLAYER_ARMOR_ABSORB)))
        self.armor = max(0, self.armor - absorbed)
        damage_taken = max(0, amount - absorbed)
        self.health = max(0, self.health - damage_taken)
        self.audio.play_player_hit()
        if source == "acid":
            self._show_message("ACID BURNS", (132, 236, 118))
        if damage_taken >= 18:
            self.face_hit_state = "hit_heavy"
            self.face_hit_timer = 0.32
        else:
            self.face_hit_state = "hit_light"
            self.face_hit_timer = 0.18
        flash_color = (148, 236, 88) if source == "acid" else (255, 72, 52)
        self._trigger_damage_flash(flash_color, settings.PLAYER_DAMAGE_FLASH_TIME)
        if self.health > 0:
            return
        self.player_death_timer = settings.PLAYER_DEATH_RESET_TIME
        self.audio.play_player_death()
        self._show_message("YOU DIED", (255, 96, 72))

    def _bump_music_impulse(self, attr: str, amount: float) -> None:
        current = getattr(self, attr, 0.0)
        setattr(self, attr, min(1.0, current + amount))

    def _update_music_events(self) -> None:
        if self.world is None or self.player is None:
            return
        for enemy in self.world.active_enemies(include_corpses=False):
            if enemy.enemy_id in self.music_seen_enemy_ids:
                continue
            if math.hypot(enemy.x - self.player.x, enemy.y - self.player.y) > 8.0:
                continue
            if not self.world.has_line_of_sight(self.player.x, self.player.y, enemy.x, enemy.y):
                continue
            self.music_seen_enemy_ids.add(enemy.enemy_id)
            if enemy.enemy_type == "cyberdemon":
                self._bump_music_impulse("music_recent_event", 0.88)
            elif enemy.enemy_type == "warden":
                self._bump_music_impulse("music_recent_event", 0.62)
            elif enemy.enemy_type == "cacodemon":
                self._bump_music_impulse("music_recent_event", 0.4)
            elif enemy.enemy_type == "heavy":
                self._bump_music_impulse("music_recent_event", 0.28)
            else:
                self._bump_music_impulse("music_recent_event", 0.12)

    def _decay_music_impulses(self, delta_time: float) -> None:
        self.music_recent_shots = max(0.0, self.music_recent_shots - delta_time * 0.55)
        self.music_recent_damage = max(0.0, self.music_recent_damage - delta_time * 0.42)
        self.music_recent_kills = max(0.0, self.music_recent_kills - delta_time * 0.26)
        self.music_recent_event = max(0.0, self.music_recent_event - delta_time * 0.34)

    def _build_music_snapshot(self) -> MusicSnapshot:
        if self.world is None or self.player is None:
            return MusicSnapshot()
        live_enemies = self.world.active_enemies(include_corpses=False)
        _, planned_room_pressure, room_enemy_count, room_dormant_enemy_count = self.world.room_music_state(
            self.player.x,
            self.player.y,
        )
        nearby_enemies = 0
        attacking_enemies = 0
        active_threat = 0.0
        nearby_threat = 0.0
        attacking_threat = 0.0
        boss_nearby_threat = 0.0
        for enemy in live_enemies:
            threat = self._enemy_music_threat(enemy.enemy_type)
            distance = math.hypot(enemy.x - self.player.x, enemy.y - self.player.y)
            active_threat += threat
            if distance <= 7.5:
                nearby_enemies += 1
                nearby_threat += threat
                if enemy.enemy_type in {"warden", "cacodemon", "cyberdemon"}:
                    boss_nearby_threat += threat
            if enemy.ai_state == "attack":
                attacking_enemies += 1
                attacking_threat += threat
            elif enemy.ai_state == "chase" and distance <= 9.5:
                attacking_enemies += 1
                attacking_threat += threat * 0.9
            elif enemy.ai_state == "alert" and distance <= 6.5:
                attacking_enemies += 1
                attacking_threat += threat * 0.65
        return MusicSnapshot(
            active_enemies=len(live_enemies),
            nearby_enemies=nearby_enemies,
            attacking_enemies=attacking_enemies,
            active_threat=active_threat,
            nearby_threat=nearby_threat,
            attacking_threat=attacking_threat,
            projectile_count=len(self.world.active_enemy_projectiles()),
            movement=self.move_amount,
            recent_shots=self.music_recent_shots,
            recent_damage=self.music_recent_damage,
            recent_kills=self.music_recent_kills,
            recent_event=self.music_recent_event,
            boss_nearby_threat=boss_nearby_threat,
            player_health_ratio=max(0.0, min(1.0, self.health / max(1, settings.MAX_HEALTH))),
            planned_room_pressure=planned_room_pressure,
            room_enemy_count=room_enemy_count,
            room_dormant_enemy_count=room_dormant_enemy_count,
        )

    def _enemy_music_threat(self, enemy_type: str) -> float:
        return {
            "charger": 1.15,
            "grunt": 1.0,
            "heavy": 2.35,
            "cacodemon": 2.82,
            "warden": 3.15,
            "cyberdemon": 4.8,
        }.get(enemy_type, 1.0)

    def _draw_pickup_message(self) -> None:
        if not self.pickup_message:
            return
        text = self.font.render(self.pickup_message, True, (248, 222, 150))
        bg = text.get_rect(midbottom=(settings.SCREEN_WIDTH // 2, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT - 14))
        bg.inflate_ip(24, 12)
        overlay = pygame.Surface(bg.size, pygame.SRCALPHA)
        overlay.fill((24, 12, 10, 188))
        self.screen.blit(overlay, bg.topleft)
        pygame.draw.rect(self.screen, (186, 164, 108), bg, 2, border_radius=4)
        self.screen.blit(text, text.get_rect(center=bg.center))

    def _draw_pickup_flash(self) -> None:
        if self.pickup_flash_timer <= 0.0:
            return
        alpha = int(36 * min(1.0, self.pickup_flash_timer))
        overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((*self.pickup_flash_color, alpha))
        self.screen.blit(overlay, (0, 0))

    def _draw_damage_flash(self) -> None:
        if self.damage_flash_timer <= 0.0:
            return
        alpha = int(62 * min(1.0, self.damage_flash_timer))
        overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((*self.damage_flash_color, alpha))
        self.screen.blit(overlay, (0, 0))

    def _draw_hud(self) -> None:
        hud_y = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT
        hud_rect = pygame.Rect(0, hud_y, settings.SCREEN_WIDTH, settings.HUD_HEIGHT)
        self._draw_hud_panel(hud_rect)

        top_strip = pygame.Rect(0, hud_y - 8, settings.SCREEN_WIDTH, 8)
        pygame.draw.rect(self.screen, (120, 88, 54), top_strip)
        pygame.draw.line(self.screen, (198, 170, 118), (0, hud_y - 8), (settings.SCREEN_WIDTH, hud_y - 8), 2)
        pygame.draw.line(self.screen, (54, 28, 20), (0, hud_y - 1), (settings.SCREEN_WIDTH, hud_y - 1), 2)

        ammo_rect = pygame.Rect(20, hud_y + 18, 220, 88)
        face_rect = pygame.Rect(settings.SCREEN_WIDTH // 2 - 92, hud_y + 14, 184, 94)
        health_rect = pygame.Rect(settings.SCREEN_WIDTH - 264, hud_y + 18, 122, 88)
        armor_rect = pygame.Rect(settings.SCREEN_WIDTH - 134, hud_y + 18, 114, 88)
        left_panel_x = face_rect.left - 132

        self._draw_stat_box(ammo_rect, "AMMO", self._current_weapon_ammo(), None, (188, 42, 34))
        self._draw_face_panel(face_rect)
        self._draw_stat_box(health_rect, "HEALTH", self.health, "%", (188, 42, 34))
        self._draw_stat_box(armor_rect, "ARMOR", self.armor, "%", (188, 42, 34))
        self._draw_weapon_slots(pygame.Rect(left_panel_x, hud_y + 18, 120, 38))
        self._draw_weapon_slots(pygame.Rect(face_rect.right + 12, hud_y + 18, 132, 38), start_slot=5)
        self._draw_key_panel(pygame.Rect(left_panel_x, hud_y + 62, 120, 44))
        self._draw_status_text(pygame.Rect(face_rect.right + 12, hud_y + 62, 132, 44))
        self._draw_ammo_reserves(pygame.Rect(252, hud_y + 18, 150, 88))

    def _draw_interact_debug(self) -> None:
        if self.world is None or self.player is None:
            return
        lines = self._current_interact_debug_lines()
        if not lines:
            return
        panel_width = 438
        line_height = 18
        panel_height = 10 + len(lines) * line_height
        panel = pygame.Rect(
            settings.SCREEN_WIDTH - panel_width - 14,
            14,
            panel_width,
            panel_height,
        )
        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill((8, 8, 10, 210))
        self.screen.blit(overlay, panel.topleft)
        pygame.draw.rect(self.screen, (186, 154, 104), panel, 2, border_radius=4)
        for index, line in enumerate(lines):
            color = (250, 224, 176) if index == 0 else (220, 202, 164)
            text = self.small_font.render(line, True, color)
            self.screen.blit(text, (panel.x + 10, panel.y + 6 + index * line_height))

    def _current_interact_debug_lines(self) -> list[str]:
        if self.world is None or self.player is None:
            return []
        switch = self.world.find_interactable_switch(
            self.player.x,
            self.player.y,
            self.player.angle,
        )
        if switch is not None:
            return [
                "TARGET SWITCH",
                switch.label,
            ]

        door = self.world.find_interactable_door(
            self.player.x,
            self.player.y,
            self.player.angle,
        )
        if door is None:
            return []
        required_key = door.definition.required_key_type
        if required_key is not None:
            title = f"{required_key.upper()} DOOR"
        elif door.required_trigger_id is not None:
            title = "LOCKED SHORTCUT"
        else:
            title = "DOOR"
        state_parts: list[str] = [f"state={door.state}"]
        if required_key is not None:
            state_parts.append(f"key={'YES' if required_key in self.keys_owned else 'NO'}")
        if door.required_trigger_id is not None:
            state_parts.append(f"route={'OPEN' if door.trigger_unlocked else 'LOCKED'}")
        if door.guard_enemy_id is not None:
            state_parts.append("boss-lock")
        return [
            f"TARGET {title}",
            " | ".join(state_parts),
        ]

    def _draw_hud_panel(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, (62, 56, 52), rect)
        for x in range(0, rect.width, 32):
            color = (76, 68, 62) if (x // 32) % 2 == 0 else (68, 60, 56)
            pygame.draw.rect(self.screen, color, (rect.x + x, rect.y, 16, rect.height))
            pygame.draw.line(self.screen, (90, 82, 74), (rect.x + x, rect.y), (rect.x + x, rect.bottom), 1)
        for y in range(rect.y + 14, rect.bottom, 20):
            pygame.draw.line(self.screen, (52, 46, 42), (rect.x, y), (rect.right, y), 1)
        pygame.draw.rect(self.screen, (168, 150, 128), rect, 3)
        pygame.draw.line(self.screen, (226, 210, 182), (rect.x + 2, rect.y + 2), (rect.right - 2, rect.y + 2), 2)
        pygame.draw.line(self.screen, (32, 26, 22), (rect.x + 2, rect.bottom - 3), (rect.right - 2, rect.bottom - 3), 2)

        for x in range(18, rect.width, 96):
            bolt_y = rect.y + 12 + (x // 96) % 2 * 88
            self._draw_bolt(rect.x + x, bolt_y)
            self._draw_bolt(rect.x + x + 46, bolt_y)

    def _draw_bolt(self, x: int, y: int) -> None:
        pygame.draw.circle(self.screen, (146, 146, 150), (x, y), 6)
        pygame.draw.line(self.screen, (74, 74, 82), (x - 3, y), (x + 3, y), 2)
        pygame.draw.line(self.screen, (74, 74, 82), (x, y - 3), (x, y + 3), 2)

    def _draw_stat_box(
        self,
        rect: pygame.Rect,
        label: str,
        value: int,
        suffix: str | None,
        digit_color: tuple[int, int, int],
    ) -> None:
        pygame.draw.rect(self.screen, (42, 40, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 12, 12), rect.inflate(-8, -8), border_radius=3)
        pygame.draw.rect(self.screen, (142, 136, 126), rect, 3, border_radius=4)
        label_surface = self.small_font.render(label, True, (206, 188, 144))
        self.screen.blit(label_surface, (rect.x + 10, rect.y + 8))
        digit_scale = 8 if suffix is None else 7
        self._draw_big_number(rect.x + 10, rect.y + 32, value, suffix=suffix, scale=digit_scale, color=digit_color)

    def _draw_big_number(
        self,
        x: int,
        y: int,
        value: int,
        suffix: str | None = None,
        scale: int = 8,
        color: tuple[int, int, int] = (188, 42, 34),
    ) -> None:
        text = f"{max(0, value):03d}"
        if suffix:
            text += suffix

        cursor_x = x
        for char in text:
            pattern = DIGIT_PATTERNS.get(char)
            if pattern is None:
                cursor_x += scale * 2
                continue
            for row_index, row in enumerate(pattern):
                for col_index, bit in enumerate(row):
                    if bit == "1":
                        px = cursor_x + col_index * scale
                        py = y + row_index * scale
                        pygame.draw.rect(self.screen, (34, 8, 6), (px + 2, py + 2, scale, scale))
                        pygame.draw.rect(self.screen, color, (px, py, scale, scale))
                        pygame.draw.line(self.screen, (250, 118, 94), (px, py), (px + scale - 1, py), 1)
            cursor_x += (len(pattern[0]) + 1) * scale

    def _draw_face_panel(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, (38, 38, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 18, 22), rect.inflate(-8, -8), border_radius=4)
        pygame.draw.rect(self.screen, (150, 144, 136), rect, 3, border_radius=4)
        inner = rect.inflate(-18, -18)
        pygame.draw.rect(self.screen, (92, 18, 18), inner, border_radius=3)
        pygame.draw.rect(self.screen, (164, 142, 62), (inner.x + 8, inner.y + 8, inner.width - 16, 6), border_radius=2)

        face_sprite = self._current_face_sprite()
        if face_sprite is None:
            return

        draw_sprite = face_sprite.copy()
        if self.health < 35:
            overlay = pygame.Surface(draw_sprite.get_size(), pygame.SRCALPHA)
            overlay.fill((100, 0, 0, 56))
            draw_sprite.blit(overlay, (0, 0))
        elif self.health < 70:
            overlay = pygame.Surface(draw_sprite.get_size(), pygame.SRCALPHA)
            overlay.fill((40, 0, 0, 24))
            draw_sprite.blit(overlay, (0, 0))

        face_rect = draw_sprite.get_rect(center=(rect.centerx, rect.centery + 2))
        self.screen.blit(draw_sprite, face_rect)

        ammo_flash = (196, 182, 92) if self._current_weapon_ammo() > 0 else (132, 42, 42)
        for side in (-1, 1):
            lamp_rect = pygame.Rect(rect.centerx + side * 58 - 10, rect.y + 16, 20, 14)
            pygame.draw.rect(self.screen, ammo_flash, lamp_rect, border_radius=3)
            pygame.draw.rect(self.screen, (56, 48, 28), lamp_rect, 2, border_radius=3)

    def _draw_weapon_slots(self, rect: pygame.Rect, start_slot: int = 2) -> None:
        pygame.draw.rect(self.screen, (42, 40, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 12, 12), rect.inflate(-6, -6), border_radius=3)
        pygame.draw.rect(self.screen, (142, 136, 126), rect, 2, border_radius=4)
        caption = self.small_font.render("ARMS", True, (208, 192, 148))
        self.screen.blit(caption, (rect.x + 8, rect.y + 4))

        for idx in range(3):
            slot = start_slot + idx
            slot_rect = pygame.Rect(rect.x + 8 + idx * 40, rect.y + 16, 32, 16)
            active = self.selected_weapon_slot == slot
            owned = any(
                weapon.slot == slot and weapon.weapon_id in self.owned_weapons
                for weapon in WEAPON_DEFINITIONS.values()
            )
            fill = (164, 38, 28) if active else (60, 54, 52) if owned else (28, 26, 28)
            pygame.draw.rect(self.screen, fill, slot_rect, border_radius=2)
            pygame.draw.rect(self.screen, (142, 136, 126), slot_rect, 2, border_radius=2)
            number = self.small_font.render(str(slot), True, (240, 214, 170) if owned else (114, 108, 102))
            self.screen.blit(number, number.get_rect(center=slot_rect.center))

    def _draw_key_panel(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, (42, 40, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 12, 12), rect.inflate(-6, -6), border_radius=3)
        pygame.draw.rect(self.screen, (142, 136, 126), rect, 2, border_radius=4)
        caption = self.small_font.render("KEYS", True, (208, 192, 148))
        self.screen.blit(caption, (rect.x + 8, rect.y + 4))

        for idx, key_type in enumerate(KEY_TYPES):
            key_color = KEY_DEFINITIONS[key_type].visual.hud_color
            key_rect = pygame.Rect(rect.x + 10 + idx * 38, rect.y + 18, 24, 16)
            fill = key_color if key_type in self.keys_owned else (40, 40, 42)
            pygame.draw.rect(self.screen, fill, key_rect, border_radius=3)
            pygame.draw.rect(self.screen, (150, 144, 136), key_rect, 2, border_radius=3)
            pygame.draw.circle(self.screen, (244, 228, 186), (key_rect.x + 8, key_rect.y + 8), 3, 1)
            pygame.draw.rect(self.screen, (244, 228, 186), (key_rect.x + 11, key_rect.y + 7, 7, 2))

    def _draw_status_text(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, (42, 40, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 12, 12), rect.inflate(-6, -6), border_radius=3)
        pygame.draw.rect(self.screen, (142, 136, 126), rect, 2, border_radius=4)
        label = self.small_font.render("LEVEL", True, (208, 192, 148))
        level_text = (
            f"L{self.world.level_index}/{self.run_state.total_level_count}"
            if self.run_state is not None
            else f"SEED {self.world.seed}"
        )
        seed = self.small_font.render(level_text, True, (238, 212, 166))
        difficulty = self.small_font.render(self.difficulty_id.upper(), True, (188, 104, 92))
        subtitle = self.small_font.render(self.world.level_subtitle[:14], True, (198, 176, 138))
        self.screen.blit(label, (rect.x + 8, rect.y + 4))
        self.screen.blit(seed, (rect.x + 8, rect.y + 20))
        self.screen.blit(difficulty, difficulty.get_rect(topright=(rect.right - 8, rect.y + 20)))
        self.screen.blit(subtitle, (rect.x + 8, rect.y + 32))

    def _draw_intermission_overlay(self) -> None:
        if not self.intermission_data:
            return
        overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((6, 4, 8, 176))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(settings.SCREEN_WIDTH // 2 - 250, settings.SCREEN_HEIGHT // 2 - 120, 500, 240)
        pygame.draw.rect(self.screen, (28, 16, 16), panel, border_radius=8)
        pygame.draw.rect(self.screen, (186, 144, 90), panel, 3, border_radius=8)
        level_line = self.title_font.render(
            f"LEVEL {self.intermission_data['level_index']}",
            True,
            (248, 226, 172),
        )
        title = self.font.render(str(self.intermission_data["title"]).upper(), True, (236, 208, 152))
        subtitle = self.font.render(str(self.intermission_data["subtitle"]), True, (206, 188, 156))
        meta = self.small_font.render(
            f"{self.intermission_data['difficulty']}  |  seed {self.intermission_data['seed']}",
            True,
            (188, 170, 136),
        )
        total_line = self.small_font.render(
            f"{self.intermission_data['level_index']}/{self.intermission_data['total_level_count']}",
            True,
            (188, 104, 92),
        )
        self.screen.blit(level_line, level_line.get_rect(center=(panel.centerx, panel.y + 56)))
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 106)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 140)))
        self.screen.blit(meta, meta.get_rect(center=(panel.centerx, panel.y + 178)))
        self.screen.blit(total_line, total_line.get_rect(center=(panel.centerx, panel.y + 204)))

    def _draw_campaign_complete_overlay(self) -> None:
        overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 4, 8, 208))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(settings.SCREEN_WIDTH // 2 - 280, settings.SCREEN_HEIGHT // 2 - 150, 560, 300)
        pygame.draw.rect(self.screen, (30, 14, 14), panel, border_radius=8)
        pygame.draw.rect(self.screen, (210, 176, 112), panel, 3, border_radius=8)
        title = self.title_font.render("CAMPAIGN CLEAR", True, (255, 234, 182))
        difficulty = self.font.render(f"DIFFICULTY: {self.difficulty_id.upper()}", True, (236, 208, 152))
        completed = self.font.render(
            f"COMPLETED: {len(self.run_state.completed_levels)}/{self.run_state.total_level_count}",
            True,
            (236, 208, 152),
        )
        seed = self.font.render(f"RUN SEED: {self.run_state.run_seed}", True, (188, 104, 92))
        footer = self.small_font.render("F2 to return to difficulty select", True, (188, 170, 136))
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 64)))
        self.screen.blit(difficulty, difficulty.get_rect(center=(panel.centerx, panel.y + 136)))
        self.screen.blit(completed, completed.get_rect(center=(panel.centerx, panel.y + 176)))
        self.screen.blit(seed, seed.get_rect(center=(panel.centerx, panel.y + 216)))
        self.screen.blit(footer, footer.get_rect(center=(panel.centerx, panel.y + 258)))

    def _draw_ammo_reserves(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, (42, 40, 42), rect, border_radius=4)
        pygame.draw.rect(self.screen, (18, 12, 12), rect.inflate(-6, -6), border_radius=3)
        pygame.draw.rect(self.screen, (142, 136, 126), rect, 2, border_radius=4)

        rows = list(self.ammo_pools.items())
        for idx, (label, value) in enumerate(rows):
            y = rect.y + 8 + idx * 18
            label_surface = self.small_font.render(label, True, (208, 192, 148))
            value_surface = self.small_font.render(f"{value:03d}", True, (188, 42, 34))
            self.screen.blit(label_surface, (rect.x + 10, y))
            self.screen.blit(value_surface, value_surface.get_rect(topright=(rect.right - 12, y)))
