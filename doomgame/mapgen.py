from __future__ import annotations

from dataclasses import dataclass
import math
import random

from doomgame.enemies import EnemySpawn
from doomgame import settings
from doomgame.doors import DoorSpawn, KeySpawn, KEY_TYPES, locked_door_type_for_key
from doomgame.loot import ROOM_LOOT_COUNTS, ROOM_LOOT_TABLES, resolve_pickup_amount
from doomgame.progression import (
    ACTION_ACTIVATE_EXIT_ROUTE,
    ACTION_ACTIVATE_SECRET,
    ACTION_OPEN_DOOR,
    ACTION_SPAWN_AMBUSH,
    ACTION_UNLOCK_SHORTCUT,
    ACTION_WAKE_ROOM,
    DEFAULT_DIFFICULTY_ID,
    EDGE_LOOP,
    EDGE_MAIN,
    EDGE_SHORTCUT,
    EncounterEventPlan,
    LevelGenerationRequest,
    MacroRouteEdge,
    MacroRouteNode,
    MacroRoutePlan,
    ProgressionAction,
    ProgressionBeat,
    QualityScoreReport,
    ROOM_ROLE_AMBUSH_ROOM,
    ROOM_ROLE_FINAL_ROOM,
    ROOM_ROLE_KEY_ROOM,
    ROOM_ROLE_PRESSURE_CORRIDOR,
    ROOM_ROLE_RETURN_ROUTE,
    ROOM_ROLE_SECRET_ROOM,
    ROOM_ROLE_SHORTCUT_HALL,
    ROOM_ROLE_START,
    ROOM_ROLE_SWITCH_ROOM,
    ROOM_ROLE_VISTA,
    RoomMetadata,
    SecretSpawn,
    ValidationReport,
    WorldSwitchSpawn,
    WorldTriggerSpawn,
    build_macro_signature,
    calculate_level_identity_score,
    get_difficulty_definition,
    get_skeleton_profile,
)

ROOM_KINDS = ("start", "storage", "arena", "tech", "shrine", "cross")
SECTOR_SAFE = 0
SECTOR_ACID = 1
SECTOR_BRIDGE = 2
ROOM_KIND_HAZARD = 6
ROOM_KIND_CATWALK = 7
ROOM_KIND_VISTA = 8

ARCHETYPE_HIGH_CEILING_HALL = "high_ceiling_hall"
ARCHETYPE_TOXIC_PIT_ROOM = "toxic_pit_room"
ARCHETYPE_BRIDGE_CROSSING = "bridge_crossing"
ARCHETYPE_OFFSET_CORRIDOR = "offset_corridor"
ARCHETYPE_SPLIT_ARENA = "split_arena"
ARCHETYPE_OVERLOOK_VISTA = "overlook_vista"
ARCHETYPE_CRUSHER_PASSAGE = "crusher_like_narrow_passage"
ARCHETYPE_RAISED_PLATFORM = "raised_platform_room"
ARCHETYPE_ACID_RING = "acid_ring_room"
ARCHETYPE_TOXIC_CANALS = "toxic_canals_room"
ARCHETYPE_GRAND_CHAMBER = "grand_chamber"


@dataclass(frozen=True)
class Room:
    x: int
    y: int
    width: int
    height: int
    kind: str
    floor_height: int
    shape_family: str = "rectangular"
    spatial_archetype: str = "standard"
    ceiling_height: int = 1
    geometry_preset_id: str = "standard"

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def intersects(self, other: "Room", padding: int = 1) -> bool:
        return not (
            self.x + self.width + padding <= other.x
            or other.x + other.width + padding <= self.x
            or self.y + self.height + padding <= other.y
            or other.y + other.height + padding <= self.y
        )

    def contains_tile(self, grid_x: int, grid_y: int, padding: int = 0) -> bool:
        return (
            self.x - padding <= grid_x < self.x + self.width + padding
            and self.y - padding <= grid_y < self.y + self.height + padding
        )


@dataclass(frozen=True)
class GeneratedMap:
    tiles: list[list[int]]
    floor_heights: list[list[int]]
    ceiling_heights: list[list[int]]
    stair_mask: list[list[int]]
    room_kinds: list[list[int]]
    sector_types: list[list[int]]
    loot_spawns: list["LootSpawn"]
    enemy_spawns: list[EnemySpawn]
    door_spawns: list[DoorSpawn]
    key_spawns: list[KeySpawn]
    exit_spawn: "ExitSpawn | None"
    spawn: tuple[float, float]
    seed: int
    run_seed: int
    per_level_seed: int
    difficulty_id: str
    level_index: int
    level_archetype_id: str
    skeleton_profile_id: str
    macro_variant_id: str
    spatial_profile_id: str
    encounter_style_id: str
    theme_modifier_id: str
    level_modifier_id: str
    level_title: str
    level_subtitle: str
    macro_layout_type: str
    macro_signature: str
    route_plan: MacroRoutePlan
    room_metadata: tuple[RoomMetadata, ...]
    progression_beats: tuple[ProgressionBeat, ...]
    switch_spawns: tuple[WorldSwitchSpawn, ...]
    trigger_spawns: tuple[WorldTriggerSpawn, ...]
    secret_spawns: tuple[SecretSpawn, ...]
    encounter_events: tuple[EncounterEventPlan, ...]
    validation_report: ValidationReport
    quality_report: QualityScoreReport


@dataclass(frozen=True)
class LootSpawn:
    pickup_id: str
    x: float
    y: float
    kind: str
    amount: int


@dataclass(frozen=True)
class ExitSpawn:
    exit_id: str
    x: float
    y: float
    required_door_id: str | None


@dataclass
class CorridorConnection:
    index: int
    room_a_index: int
    room_b_index: int
    path: list[tuple[int, int]]
    is_main_path: bool
    door_candidate: tuple[int, int, str] | None = None
    edge_kind: str = EDGE_MAIN
    trigger_source: str | None = None


@dataclass(frozen=True)
class BossGuardPlan:
    guarded_door_id: str
    guarded_door_tile: tuple[int, int]
    anchor_position: tuple[float, float]
    candidate_room_indices: tuple[int, ...]


@dataclass(frozen=True)
class ProgressionGatePlan:
    key_type: str
    stage_index: int
    connection_index: int
    key_room_candidates: tuple[int, ...]
    blocked_room_indices: tuple[int, ...]


@dataclass(frozen=True)
class ProgressionLayout:
    room_stages: tuple[int, ...]
    stage_rooms: tuple[tuple[int, ...], ...]
    gate_plans: tuple[ProgressionGatePlan, ...]


@dataclass(frozen=True)
class LayoutPlan:
    rooms: tuple[Room, ...]
    progression: ProgressionLayout
    route_plan: MacroRoutePlan
    template_variant: str


@dataclass(frozen=True)
class EncounterTemplateDefinition:
    template_id: str
    announcement_label: str
    ambush_bonus: int = 0
    pressure_multiplier: float = 1.0
    final_spawn_bonus: int = 0
    final_pressure_base: float = 1.1
    final_pressure_per_spawn: float = 0.5
    switch_pressure: float = 0.35


@dataclass(frozen=True)
class GeometryPresetDefinition:
    preset_id: str
    shape_family: str
    spatial_archetype: str
    ceiling_height: int


def _build_encounter_template_definitions() -> dict[str, EncounterTemplateDefinition]:
    role_variant_labels = {
        "standard": "CONTACT STANDARD",
        "crossfire": "CROSSFIRE LOCKDOWN",
        "flank": "FLANK PRESSURE",
        "switch": "SWITCH CONTROL",
        "chase": "PURSUIT WAVE",
        "finale": "FINAL DEFENSE",
    }
    style_configs = {
        "standard": {
            "ambush_bonus": 0,
            "pressure_multiplier": 1.0,
            "final_spawn_bonus": 0,
            "final_pressure_per_spawn": 0.5,
            "switch_pressure": 0.35,
        },
        "holdout": {
            "ambush_bonus": 1,
            "pressure_multiplier": 1.18,
            "final_spawn_bonus": 1,
            "final_pressure_per_spawn": 0.62,
            "switch_pressure": 0.55,
        },
        "hunter": {
            "ambush_bonus": 1,
            "pressure_multiplier": 1.1,
            "final_spawn_bonus": 0,
            "final_pressure_per_spawn": 0.54,
            "switch_pressure": 0.4,
        },
        "pincer": {
            "ambush_bonus": 1,
            "pressure_multiplier": 1.22,
            "final_spawn_bonus": 1,
            "final_pressure_per_spawn": 0.56,
            "switch_pressure": 0.42,
        },
    }
    template_definitions: dict[str, EncounterTemplateDefinition] = {}
    for style_id, config in style_configs.items():
        for variant_id, variant_label in role_variant_labels.items():
            template_id = f"{style_id}_{variant_id}"
            template_definitions[template_id] = EncounterTemplateDefinition(
                template_id=template_id,
                announcement_label=f"{style_id.upper()} {variant_label}",
                ambush_bonus=config["ambush_bonus"],
                pressure_multiplier=config["pressure_multiplier"],
                final_spawn_bonus=config["final_spawn_bonus"],
                final_pressure_per_spawn=config["final_pressure_per_spawn"],
                switch_pressure=config["switch_pressure"],
            )
    template_definitions.update(
        {
            "key_standard": EncounterTemplateDefinition(
                template_id="key_standard",
                announcement_label="STANDARD KEY LOCKDOWN",
            ),
            "key_holdout": EncounterTemplateDefinition(
                template_id="key_holdout",
                announcement_label="HOLDOUT KEY LOCKDOWN",
                ambush_bonus=1,
                pressure_multiplier=1.18,
            ),
            "key_hunter": EncounterTemplateDefinition(
                template_id="key_hunter",
                announcement_label="HUNTER KEY LOCKDOWN",
                ambush_bonus=1,
                pressure_multiplier=1.1,
            ),
            "key_pincer": EncounterTemplateDefinition(
                template_id="key_pincer",
                announcement_label="PINCER KEY LOCKDOWN",
                ambush_bonus=1,
                pressure_multiplier=1.22,
            ),
        }
    )
    return template_definitions


ENCOUNTER_TEMPLATE_DEFINITIONS = _build_encounter_template_definitions()


def _build_geometry_preset_definitions() -> dict[str, GeometryPresetDefinition]:
    preset_rows = (
        ("entry_hall", "rectangular", ARCHETYPE_HIGH_CEILING_HALL, 2),
        ("entry_offset", "offset_rect", ARCHETYPE_HIGH_CEILING_HALL, 2),
        ("entry_grand", "side_bays", ARCHETYPE_GRAND_CHAMBER, 3),
        ("entry_toxic", "rectangular", ARCHETYPE_TOXIC_CANALS, 2),
        ("vista_balcony", "cut_corner", ARCHETYPE_OVERLOOK_VISTA, 3),
        ("vista_ring", "ring_like", ARCHETYPE_HIGH_CEILING_HALL, 3),
        ("vista_grand_ring", "ring_like", ARCHETYPE_GRAND_CHAMBER, 4),
        ("vista_offset", "offset_rect", ARCHETYPE_OVERLOOK_VISTA, 2),
        ("vista_grand_offset", "offset_rect", ARCHETYPE_HIGH_CEILING_HALL, 3),
        ("vista_corner", "corner_pillars", ARCHETYPE_GRAND_CHAMBER, 4),
        ("key_pit_lane", "pit_with_walkway", ARCHETYPE_TOXIC_PIT_ROOM, 2),
        ("key_toxic_pit_lane", "pit_with_walkway", ARCHETYPE_TOXIC_CANALS, 2),
        ("key_bridge_control", "pit_with_walkway", ARCHETYPE_BRIDGE_CROSSING, 2),
        ("key_holdout_island", "raised_platform", ARCHETYPE_RAISED_PLATFORM, 2),
        ("key_crossfire_ring", "cut_corner", ARCHETYPE_HIGH_CEILING_HALL, 2),
        ("key_toxic_crossfire", "cut_corner", ARCHETYPE_TOXIC_PIT_ROOM, 2),
        ("key_central_island", "central_island", ARCHETYPE_SPLIT_ARENA, 2),
        ("key_grand_island", "central_island", ARCHETYPE_SPLIT_ARENA, 3),
        ("key_grand_holdout", "raised_platform", ARCHETYPE_GRAND_CHAMBER, 3),
        ("key_bridge_hold", "bridge_room", ARCHETYPE_BRIDGE_CROSSING, 2),
        ("key_toxic_bridge_hold", "bridge_room", ARCHETYPE_TOXIC_CANALS, 2),
        ("return_bridge_lane", "bridge_room", ARCHETYPE_BRIDGE_CROSSING, 2),
        ("return_toxic_bridge", "bridge_room", ARCHETYPE_TOXIC_CANALS, 2),
        ("return_flank_lane", "offset_rect", ARCHETYPE_OFFSET_CORRIDOR, 1),
        ("return_toxic_flank", "offset_rect", ARCHETYPE_TOXIC_CANALS, 1),
        ("return_crusher_flank", "recessed_endcap", ARCHETYPE_CRUSHER_PASSAGE, 1),
        ("return_grand_lane", "offset_rect", ARCHETYPE_GRAND_CHAMBER, 2),
        ("pressure_crossfire", "split_by_pillar_line", ARCHETYPE_SPLIT_ARENA, 2),
        ("pressure_grand_crossfire", "split_by_pillar_line", ARCHETYPE_GRAND_CHAMBER, 3),
        ("pressure_hazard_island", "central_island", ARCHETYPE_TOXIC_PIT_ROOM, 2),
        ("pressure_island", "central_island", ARCHETYPE_SPLIT_ARENA, 2),
        ("pressure_bridge_island", "central_island", ARCHETYPE_BRIDGE_CROSSING, 2),
        ("pressure_flank_lane", "offset_rect", ARCHETYPE_OFFSET_CORRIDOR, 1),
        ("pressure_grand_lane", "offset_rect", ARCHETYPE_GRAND_CHAMBER, 2),
        ("pressure_toxic_crossfire", "split_by_pillar_line", ARCHETYPE_TOXIC_CANALS, 2),
        ("pressure_toxic_lane", "offset_rect", ARCHETYPE_TOXIC_CANALS, 1),
        ("pressure_crusher_flank", "recessed_endcap", ARCHETYPE_CRUSHER_PASSAGE, 1),
        ("final_crossfire", "split_by_pillar_line", ARCHETYPE_SPLIT_ARENA, 3),
        ("final_grand_crossfire", "split_by_pillar_line", ARCHETYPE_GRAND_CHAMBER, 4),
        ("final_holdout", "raised_platform", ARCHETYPE_RAISED_PLATFORM, 3),
        ("final_grand_holdout", "raised_platform", ARCHETYPE_GRAND_CHAMBER, 4),
        ("final_bridge_lane", "bridge_room", ARCHETYPE_BRIDGE_CROSSING, 3),
        ("final_toxic_bridge", "bridge_room", ARCHETYPE_TOXIC_PIT_ROOM, 3),
        ("final_corner_crossfire", "corner_pillars", ARCHETYPE_GRAND_CHAMBER, 4),
        ("final_ring_crossfire", "ring_like", ARCHETYPE_ACID_RING, 3),
        ("shrine_ceremonial", "cut_corner", ARCHETYPE_HIGH_CEILING_HALL, 2),
        ("shrine_grand_ceremonial", "cut_corner", ARCHETYPE_GRAND_CHAMBER, 3),
        ("shrine_ring", "ring_like", ARCHETYPE_HIGH_CEILING_HALL, 2),
        ("arena_island", "central_island", ARCHETYPE_SPLIT_ARENA, 2),
        ("arena_grand_island", "central_island", ARCHETYPE_GRAND_CHAMBER, 3),
        ("arena_crossfire", "split_by_pillar_line", ARCHETYPE_SPLIT_ARENA, 2),
        ("arena_toxic_crossfire", "split_by_pillar_line", ARCHETYPE_TOXIC_PIT_ROOM, 2),
        ("arena_corner_crossfire", "corner_pillars", ARCHETYPE_GRAND_CHAMBER, 3),
        ("arena_toxic_side_bays", "side_bays", ARCHETYPE_TOXIC_CANALS, 2),
        ("general_standard", "rectangular", "standard", 1),
        ("general_toxic_standard", "rectangular", ARCHETYPE_TOXIC_CANALS, 1),
        ("general_grand_standard", "rectangular", ARCHETYPE_GRAND_CHAMBER, 2),
        ("general_flank_lane", "offset_rect", ARCHETYPE_OFFSET_CORRIDOR, 1),
        ("general_recessed_flank", "recessed_endcap", ARCHETYPE_CRUSHER_PASSAGE, 1),
        ("general_side_bays", "side_bays", ARCHETYPE_GRAND_CHAMBER, 2),
    )
    return {
        preset_id: GeometryPresetDefinition(preset_id, shape_family, spatial_archetype, ceiling_height)
        for preset_id, shape_family, spatial_archetype, ceiling_height in preset_rows
    }


GEOMETRY_PRESET_DEFINITIONS = _build_geometry_preset_definitions()


class MapGenerator:
    def __init__(
        self,
        width: int = settings.MAP_WIDTH,
        height: int = settings.MAP_HEIGHT,
        seed: int | None = None,
        difficulty_id: str = DEFAULT_DIFFICULTY_ID,
        runtime_pressure_bias: float = 1.0,
        generation_request: LevelGenerationRequest | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.generation_request = generation_request
        resolved_seed = (
            generation_request.per_level_seed
            if generation_request is not None
            else (seed if seed is not None else random.randrange(1, 999_999))
        )
        resolved_difficulty = generation_request.difficulty_id if generation_request is not None else difficulty_id
        self.seed = resolved_seed
        self.rng = random.Random(self.seed)
        self.difficulty_id = resolved_difficulty
        self.difficulty = get_difficulty_definition(resolved_difficulty)
        self.runtime_pressure_bias = max(
            settings.ENEMY_DIFFICULTY_MIN,
            min(settings.ENEMY_DIFFICULTY_MAX, runtime_pressure_bias),
        )

    def generate(self) -> GeneratedMap:
        best_map: GeneratedMap | None = None
        best_score = float("-inf")
        best_valid_map: GeneratedMap | None = None
        best_valid_score = float("-inf")
        validation_probe = bool(self.generation_request and self.generation_request.validation_probe)
        attempt_limit = min(settings.MAPGEN_MAX_ATTEMPTS, 3 if validation_probe else settings.MAPGEN_MAX_ATTEMPTS)
        for attempt in range(attempt_limit):
            self.rng = random.Random(f"topology:{self.seed}:{attempt}")
            generated = self._generate_once()
            if generated is None:
                continue
            if validation_probe and generated.validation_report.valid:
                return generated
            score = generated.quality_report.doom_likeness_score
            if score > best_score:
                best_map = generated
                best_score = score
            if generated.validation_report.valid and score > best_valid_score:
                best_valid_map = generated
                best_valid_score = score
            if self._meets_quality_target(generated.quality_report, generated.validation_report):
                return generated
        if best_valid_map is not None:
            return best_valid_map
        if best_map is not None:
            return best_map
        fallback = self._generate_structured_fallback()
        if fallback is not None:
            return fallback
        raise RuntimeError(f"Unable to generate a valid progression layout for seed {self.seed}")

    def _campaign_field(self, field_name: str, default):
        if self.generation_request is None:
            return default
        return getattr(self.generation_request, field_name)

    def _campaign_archetype_id(self) -> str:
        return self._campaign_field("level_archetype_id", "single_level")

    def _macro_variant_id(self) -> str:
        return self._campaign_field("macro_variant_id", "default")

    def _spatial_profile_id(self) -> str:
        return self._campaign_field("spatial_profile_id", "balanced")

    def _encounter_style_id(self) -> str:
        return self._campaign_field("encounter_style_id", "standard")

    def _theme_modifier_id(self) -> str:
        return self._campaign_field("theme_modifier_id", "default")

    def _level_modifier_id(self) -> str:
        return self._campaign_field("level_modifier_id", "standard")

    def _resolve_template_variant(self, skeleton_profile_id: str) -> str:
        skeleton_profile = get_skeleton_profile(skeleton_profile_id)
        variants = skeleton_profile.template_variants or (skeleton_profile.template_variant,)
        preferred_variant = skeleton_profile.template_variant
        macro_variant_id = self._macro_variant_id()
        spatial_profile_id = self._spatial_profile_id()
        level_modifier_id = self._level_modifier_id()
        for candidate in variants:
            macro_footprint, footprint_variant, _, _ = candidate.split(":", 3)
            if macro_variant_id == "collapse" and "perimeter" in macro_footprint:
                return candidate
            if macro_variant_id == "branchy" and footprint_variant in {"tight", "balanced"}:
                preferred_variant = candidate
            if spatial_profile_id == "expansive" and footprint_variant == "wide":
                return candidate
            if spatial_profile_id == "tight" and footprint_variant == "tight":
                return candidate
            if level_modifier_id == "vista_dominant" and macro_footprint in {"pockets", "perimeter", "twinhub"}:
                preferred_variant = candidate
        return preferred_variant

    def _template_variant_candidates(self, skeleton_profile_id: str) -> tuple[str, ...]:
        skeleton_profile = get_skeleton_profile(skeleton_profile_id)
        variants = skeleton_profile.template_variants or (skeleton_profile.template_variant,)
        preferred_variant = self._resolve_template_variant(skeleton_profile_id)
        ordered_variants = [preferred_variant]
        ordered_variants.extend(candidate for candidate in variants if candidate != preferred_variant)
        return tuple(ordered_variants)

    def _build_generated_map(
        self,
        *,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        loot_spawns: list["LootSpawn"],
        enemy_spawns: list[EnemySpawn],
        door_spawns: list[DoorSpawn],
        key_spawns: list[KeySpawn],
        exit_spawn: "ExitSpawn | None",
        spawn: tuple[float, float],
        macro_layout_type: str,
        route_plan: MacroRoutePlan,
        room_metadata: tuple[RoomMetadata, ...],
        progression_beats: tuple[ProgressionBeat, ...],
        switch_spawns: tuple[WorldSwitchSpawn, ...],
        trigger_spawns: tuple[WorldTriggerSpawn, ...],
        secret_spawns: tuple[SecretSpawn, ...],
        encounter_events: tuple[EncounterEventPlan, ...],
        validation_report: ValidationReport,
        quality_report: QualityScoreReport,
    ) -> GeneratedMap:
        macro_signature = build_macro_signature(
            skeleton_profile_id=self._campaign_field("skeleton_profile_id", macro_layout_type),
            macro_layout_type=macro_layout_type,
            room_metadata=room_metadata,
            route_plan=route_plan,
        )
        return GeneratedMap(
            tiles=tiles,
            floor_heights=floor_heights,
            ceiling_heights=ceiling_heights,
            stair_mask=stair_mask,
            room_kinds=room_kinds,
            sector_types=sector_types,
            loot_spawns=loot_spawns,
            enemy_spawns=enemy_spawns,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            spawn=spawn,
            seed=self.seed,
            run_seed=self._campaign_field("run_seed", self.seed),
            per_level_seed=self._campaign_field("per_level_seed", self.seed),
            difficulty_id=self.difficulty_id,
            level_index=self._campaign_field("level_index", 1),
            level_archetype_id=self._campaign_field("level_archetype_id", "single_level"),
            skeleton_profile_id=self._campaign_field("skeleton_profile_id", macro_layout_type),
            macro_variant_id=self._macro_variant_id(),
            spatial_profile_id=self._spatial_profile_id(),
            encounter_style_id=self._encounter_style_id(),
            theme_modifier_id=self._theme_modifier_id(),
            level_modifier_id=self._level_modifier_id(),
            level_title=self._campaign_field("level_title", f"Level {self._campaign_field('level_index', 1)}"),
            level_subtitle=self._campaign_field("level_subtitle", macro_layout_type.replace("_", " ").title()),
            macro_layout_type=macro_layout_type,
            macro_signature=macro_signature,
            route_plan=route_plan,
            room_metadata=room_metadata,
            progression_beats=progression_beats,
            switch_spawns=switch_spawns,
            trigger_spawns=trigger_spawns,
            secret_spawns=secret_spawns,
            encounter_events=encounter_events,
            validation_report=validation_report,
            quality_report=quality_report,
        )

    def _generate_once(self) -> GeneratedMap | None:
        template_variants = (
            self._template_variant_candidates(self.generation_request.skeleton_profile_id)
            if self.generation_request is not None
            else (None,)
        )
        for template_variant in template_variants:
            generated = self._generate_once_for_template_variant(template_variant)
            if generated is not None:
                return generated
        return None

    def _generate_once_for_template_variant(self, template_variant: str | None) -> GeneratedMap | None:
        tiles = [[1 for _ in range(self.width)] for _ in range(self.height)]
        floor_heights = [[0 for _ in range(self.width)] for _ in range(self.height)]
        ceiling_heights = [[1 for _ in range(self.width)] for _ in range(self.height)]
        stair_mask = [[0 for _ in range(self.width)] for _ in range(self.height)]
        room_kinds = [[-1 for _ in range(self.width)] for _ in range(self.height)]
        sector_types = [[SECTOR_SAFE for _ in range(self.width)] for _ in range(self.height)]
        layout = self._generate_rooms_and_corridors(
            tiles,
            floor_heights,
            ceiling_heights,
            stair_mask,
            room_kinds,
            sector_types,
            template_variant=template_variant,
        )
        if layout is None:
            return None
        rooms = list(layout.rooms)
        connections = self._build_template_connections(
            tiles,
            floor_heights,
            ceiling_heights,
            stair_mask,
            room_kinds,
            sector_types,
            rooms,
            layout.route_plan,
            layout.template_variant,
        )
        if connections is None:
            return None
        self._decorate_rooms(
            tiles,
            floor_heights,
            ceiling_heights,
            stair_mask,
            room_kinds,
            sector_types,
            rooms,
        )

        spawn_x, spawn_y = rooms[0].center
        spawn = (spawn_x + 0.5, spawn_y + 0.5)
        locked_doors = self._place_locked_doors(
            tiles,
            stair_mask,
            rooms,
            connections,
            spawn,
            layout.progression,
        )
        if locked_doors is None:
            return None
        key_spawns = self._place_keys(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            connections,
            layout.progression,
        )
        if key_spawns is None:
            return None
        normal_doors = self._place_optional_doors(
            tiles,
            stair_mask,
            rooms,
            connections,
            spawn,
            layout.progression,
            locked_doors,
        )
        door_spawns = [*locked_doors, *normal_doors]
        shortcut_closed_positions = {
            connection.door_candidate[:2]
            for connection in connections
            if connection.edge_kind == EDGE_SHORTCUT and connection.door_candidate is not None
        }
        final_gate = locked_doors[-1]
        final_connection = connections[layout.progression.gate_plans[-1].connection_index]
        exit_spawn = self._generate_exit_spawn(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            [(key.x, key.y) for key in key_spawns],
            set(layout.progression.stage_rooms[-1]),
            final_gate.door_id,
            (final_gate.grid_x, final_gate.grid_y),
            shortcut_closed_positions,
        )
        if exit_spawn is None and self.generation_request is not None:
            final_room = rooms[layout.route_plan.final_room_index]
            exit_spawn = ExitSpawn(
                exit_id=f"exit-{self.seed}",
                x=final_room.center[0] + 0.5,
                y=final_room.center[1] + 0.5,
                required_door_id=final_gate.door_id,
            )
        if exit_spawn is None:
            return None
        boss_guard_plan = self._build_boss_guard_plan(
            rooms,
            connections,
            final_connection,
            final_gate.door_id,
            (final_gate.grid_x, final_gate.grid_y),
        )
        reserved_positions = [(key.x, key.y) for key in key_spawns]
        loot_spawns = self._generate_loot_spawns(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            reserved_positions,
        )
        enemy_reserved_positions = [*reserved_positions, *((loot.x, loot.y) for loot in loot_spawns)]
        if exit_spawn is not None:
            enemy_reserved_positions.append((exit_spawn.x, exit_spawn.y))
        enemy_spawns, guard_enemy_id = self._generate_enemy_spawns(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            enemy_reserved_positions,
            boss_guard_plan,
        )
        if guard_enemy_id is not None and boss_guard_plan is not None:
            door_spawns = [
                DoorSpawn(
                    door_id=door.door_id,
                    grid_x=door.grid_x,
                    grid_y=door.grid_y,
                    orientation=door.orientation,
                    door_type=door.door_type,
                    guard_enemy_id=guard_enemy_id if door.door_id == boss_guard_plan.guarded_door_id else door.guard_enemy_id,
                    required_trigger_id=door.required_trigger_id,
                    locked_message=door.locked_message,
                    secret=door.secret,
                )
                for door in door_spawns
            ]

        door_spawns, enemy_spawns, room_metadata, progression_beats, switch_spawns, trigger_spawns, secret_spawns, encounter_events, macro_layout_type = self._build_dynamic_layer(
            rooms,
            layout.progression,
            layout.route_plan,
            connections,
            tiles,
            stair_mask,
            sector_types,
            spawn,
            key_spawns,
            door_spawns,
            enemy_spawns,
            exit_spawn,
        )
        validation_report = self._build_validation_report(
            progression_valid=self._validate_progression_layout(
                tiles,
                rooms,
                spawn,
                layout.progression,
                door_spawns,
                key_spawns,
                exit_spawn,
            ),
            rooms=rooms,
            progression=layout.progression,
            room_metadata=room_metadata,
            connections=connections,
            route_plan=layout.route_plan,
            spawn=spawn,
            tiles=tiles,
            sector_types=sector_types,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            encounter_events=encounter_events,
            secret_spawns=secret_spawns,
        )
        quality_report = self._build_quality_score(
            room_metadata,
            encounter_events,
            validation_report,
            layout.route_plan,
            self._key_occlusion_score(rooms, tiles, key_spawns),
        )

        return self._build_generated_map(
            tiles=tiles,
            floor_heights=floor_heights,
            ceiling_heights=ceiling_heights,
            stair_mask=stair_mask,
            room_kinds=room_kinds,
            sector_types=sector_types,
            loot_spawns=loot_spawns,
            enemy_spawns=enemy_spawns,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            spawn=spawn,
            macro_layout_type=macro_layout_type,
            route_plan=layout.route_plan,
            room_metadata=room_metadata,
            progression_beats=progression_beats,
            switch_spawns=switch_spawns,
            trigger_spawns=trigger_spawns,
            secret_spawns=secret_spawns,
            encounter_events=encounter_events,
            validation_report=validation_report,
            quality_report=quality_report,
        )

    def _generate_structured_fallback(self) -> GeneratedMap | None:
        self.rng = random.Random(self.seed ^ 0x5F3759DF)
        tiles = [[1 for _ in range(self.width)] for _ in range(self.height)]
        floor_heights = [[0 for _ in range(self.width)] for _ in range(self.height)]
        ceiling_heights = [[1 for _ in range(self.width)] for _ in range(self.height)]
        stair_mask = [[0 for _ in range(self.width)] for _ in range(self.height)]
        room_kinds = [[-1 for _ in range(self.width)] for _ in range(self.height)]
        sector_types = [[SECTOR_SAFE for _ in range(self.width)] for _ in range(self.height)]
        route_plan = self._build_macro_route_plan()
        template_variants = (
            self._template_variant_candidates(self.generation_request.skeleton_profile_id)
            if self.generation_request is not None
            else ("spine:balanced:direct:base",)
        )
        template_variant = template_variants[0]
        rooms: list[Room] | None = None
        for candidate_variant in template_variants:
            rooms = self._build_template_rooms(route_plan, candidate_variant)
            if rooms is not None:
                template_variant = candidate_variant
                break
        if rooms is None:
            return None
        for room in rooms:
            self._carve_room(tiles, floor_heights, ceiling_heights, room_kinds, sector_types, room)

        progression = self._plan_progression_layout(route_plan)
        if progression is None:
            return None

        connections = self._build_template_connections(
            tiles,
            floor_heights,
            ceiling_heights,
            stair_mask,
            room_kinds,
            sector_types,
            rooms,
            route_plan,
            template_variant,
        )
        if connections is None:
            return None

        self._decorate_rooms(
            tiles,
            floor_heights,
            ceiling_heights,
            stair_mask,
            room_kinds,
            sector_types,
            rooms,
        )

        spawn = (rooms[0].center[0] + 0.5, rooms[0].center[1] + 0.5)
        locked_doors = self._place_locked_doors(
            tiles,
            stair_mask,
            rooms,
            connections,
            spawn,
            progression,
        )
        if locked_doors is None:
            return None
        key_spawns = self._place_keys(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            connections,
            progression,
        )
        if key_spawns is None:
            return None
        normal_doors = self._place_optional_doors(
            tiles,
            stair_mask,
            rooms,
            connections,
            spawn,
            progression,
            locked_doors,
        )
        if not normal_doors and any(edge.edge_kind == EDGE_SHORTCUT for edge in route_plan.edges):
            return None
        door_spawns = [*locked_doors, *normal_doors]
        shortcut_closed_positions = {
            connection.door_candidate[:2]
            for connection in connections
            if connection.edge_kind == EDGE_SHORTCUT and connection.door_candidate is not None
        }
        exit_spawn = self._generate_exit_spawn(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            [(key.x, key.y) for key in key_spawns],
            set(progression.stage_rooms[-1]),
            locked_doors[-1].door_id,
            (locked_doors[-1].grid_x, locked_doors[-1].grid_y),
            shortcut_closed_positions,
        )
        if exit_spawn is None and self.generation_request is not None:
            final_room = rooms[route_plan.final_room_index]
            exit_spawn = ExitSpawn(
                exit_id=f"exit-{self.seed}",
                x=final_room.center[0] + 0.5,
                y=final_room.center[1] + 0.5,
                required_door_id=locked_doors[-1].door_id,
            )
        if exit_spawn is None:
            return None
        loot_spawns = self._generate_loot_spawns(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            [(key.x, key.y) for key in key_spawns],
        )
        reserved_positions = [(key.x, key.y) for key in key_spawns]
        enemy_reserved_positions = [*reserved_positions, *((loot.x, loot.y) for loot in loot_spawns), (exit_spawn.x, exit_spawn.y)]
        final_connection = connections[progression.gate_plans[-1].connection_index]
        boss_guard_plan = self._build_boss_guard_plan(
            rooms,
            connections,
            final_connection,
            locked_doors[-1].door_id,
            (locked_doors[-1].grid_x, locked_doors[-1].grid_y),
        )
        enemy_spawns, guard_enemy_id = self._generate_enemy_spawns(
            tiles,
            stair_mask,
            sector_types,
            rooms,
            spawn,
            enemy_reserved_positions,
            boss_guard_plan,
        )
        if guard_enemy_id is not None and boss_guard_plan is not None:
            door_spawns = [
                DoorSpawn(
                    door_id=door.door_id,
                    grid_x=door.grid_x,
                    grid_y=door.grid_y,
                    orientation=door.orientation,
                    door_type=door.door_type,
                    guard_enemy_id=guard_enemy_id if door.door_id == boss_guard_plan.guarded_door_id else door.guard_enemy_id,
                    required_trigger_id=door.required_trigger_id,
                    locked_message=door.locked_message,
                    secret=door.secret,
                )
                for door in door_spawns
            ]

        door_spawns, enemy_spawns, room_metadata, progression_beats, switch_spawns, trigger_spawns, secret_spawns, encounter_events, macro_layout_type = self._build_dynamic_layer(
            rooms,
            progression,
            route_plan,
            connections,
            tiles,
            stair_mask,
            sector_types,
            spawn,
            key_spawns,
            door_spawns,
            enemy_spawns,
            exit_spawn,
        )
        validation_report = self._build_validation_report(
            progression_valid=self._validate_progression_layout(
                tiles,
                rooms,
                spawn,
                progression,
                door_spawns,
                key_spawns,
                exit_spawn,
            ),
            rooms=rooms,
            progression=progression,
            room_metadata=room_metadata,
            connections=connections,
            route_plan=route_plan,
            spawn=spawn,
            tiles=tiles,
            sector_types=sector_types,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            encounter_events=encounter_events,
            secret_spawns=secret_spawns,
        )
        quality_report = self._build_quality_score(
            room_metadata,
            encounter_events,
            validation_report,
            route_plan,
            self._key_occlusion_score(rooms, tiles, key_spawns),
        )

        return self._build_generated_map(
            tiles=tiles,
            floor_heights=floor_heights,
            ceiling_heights=ceiling_heights,
            stair_mask=stair_mask,
            room_kinds=room_kinds,
            sector_types=sector_types,
            loot_spawns=loot_spawns,
            enemy_spawns=enemy_spawns,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            spawn=spawn,
            macro_layout_type=macro_layout_type,
            route_plan=route_plan,
            room_metadata=room_metadata,
            progression_beats=progression_beats,
            switch_spawns=switch_spawns,
            trigger_spawns=trigger_spawns,
            secret_spawns=secret_spawns,
            encounter_events=encounter_events,
            validation_report=validation_report,
            quality_report=quality_report,
        )

    def _generate_rooms_and_corridors(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        template_variant: str | None = None,
    ) -> LayoutPlan | None:
        route_plan = self._build_macro_route_plan()
        if template_variant is not None:
            template_variants = (template_variant,)
        elif self.generation_request is not None:
            template_variants = self._template_variant_candidates(self.generation_request.skeleton_profile_id)
        else:
            macro_footprint = self.rng.choice(("spine", "staggered", "pockets"))
            footprint_variant = self.rng.choice(("tight", "balanced", "wide"))
            corridor_variant = self.rng.choice(("direct", "dogleg"))
            mirror_variant = self.rng.choice(("base", "mirror_x", "mirror_y", "mirror_xy"))
            template_variants = (f"{macro_footprint}:{footprint_variant}:{corridor_variant}:{mirror_variant}",)
        template_variant = template_variants[0]
        rooms: list[Room] | None = None
        for candidate_variant in template_variants:
            rooms = self._build_template_rooms(route_plan, candidate_variant)
            if rooms is not None:
                template_variant = candidate_variant
                break
        if rooms is None:
            return None
        for room in rooms:
            self._carve_room(tiles, floor_heights, ceiling_heights, room_kinds, sector_types, room)

        if len(rooms) < settings.MIN_PROGRESSION_ROOMS:
            return None

        progression = self._plan_progression_layout(route_plan)
        if progression is None:
            return None
        return LayoutPlan(
            rooms=tuple(rooms),
            progression=progression,
            route_plan=route_plan,
            template_variant=template_variant,
        )

    def _build_macro_route_plan(self) -> MacroRoutePlan:
        if self.generation_request is not None:
            skeleton_profile_id = self.generation_request.skeleton_profile_id
            layout_type = get_skeleton_profile(skeleton_profile_id).macro_layout_type
        else:
            skeleton_profile_id = self.rng.choice(
                (
                    "intro_hub_spokes",
                    "double_ring_circulation",
                    "split_fork_reconverge",
                    "perimeter_inward_push",
                )
            )
            layout_type = get_skeleton_profile(skeleton_profile_id).macro_layout_type
        route_variants: dict[str, dict[str, dict[str, object]]] = {
            "intro_hub_spokes": {
                "default": {
                    "layout_type": "hub_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (4, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SHORTCUT_HALL, "storage", 3, False),
                        (7, 2, ROOM_ROLE_VISTA, "shrine", 0, True),
                        (8, 2, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 7),
                    "return_rooms": (3, 8),
                    "layout_loops": ((0, 2), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "branchy": {
                    "layout_type": "hub_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (2, 0, ROOM_ROLE_VISTA, "shrine", 2, True),
                        (3, 1, ROOM_ROLE_KEY_ROOM, "storage", 0, False),
                        (4, 1, ROOM_ROLE_AMBUSH_ROOM, "cross", 1, False),
                        (5, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 2, False),
                        (6, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 3, False),
                        (7, 2, ROOM_ROLE_KEY_ROOM, "arena", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (2, 8),
                    "return_rooms": (6, 8),
                    "layout_loops": ((0, 2), (3, 6), (7, 9)),
                    "shortcut_specs": ((6, 9, "pickup:yellow"),),
                    "key_room_indices": (2, 7, 9),
                },
                "cross_link": {
                    "layout_type": "hub_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (4, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "tech", 3, False),
                        (7, 2, ROOM_ROLE_SHORTCUT_HALL, "cross", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 8),
                    "return_rooms": (3, 7),
                    "layout_loops": ((0, 2), (3, 6), (6, 9)),
                    "shortcut_specs": ((2, 6, "pickup:blue"), (5, 8, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
            },
            "double_ring_circulation": {
                "default": {
                    "layout_type": "double_loop",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (4, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "cross", 3, False),
                        (7, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 8),
                    "return_rooms": (3, 7),
                    "layout_loops": ((0, 2), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "cross_link": {
                    "layout_type": "double_loop",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "storage", 2, False),
                        (3, 1, ROOM_ROLE_VISTA, "shrine", 0, True),
                        (4, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 3, False),
                        (7, 2, ROOM_ROLE_AMBUSH_ROOM, "cross", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (3, 8),
                    "return_rooms": (4, 7),
                    "layout_loops": ((0, 3), (2, 6), (5, 8)),
                    "shortcut_specs": ((2, 6, "pickup:blue"), (5, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "collapse": {
                    "layout_type": "double_loop",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 0, False),
                        (4, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "arena", 3, False),
                        (7, 2, ROOM_ROLE_SWITCH_ROOM, "tech", 0, False),
                        (8, 2, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1,),
                    "return_rooms": (4, 8),
                    "layout_loops": ((0, 2), (4, 7), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (7, 9, "switch:stage1")),
                    "key_room_indices": (2, 5, 9),
                },
            },
            "split_fork_reconverge": {
                "default": {
                    "layout_type": "fork_return",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_RETURN_ROUTE, "storage", 0, False),
                        (4, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SHORTCUT_HALL, "tech", 3, False),
                        (7, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "cross", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 8),
                    "return_rooms": (3, 7),
                    "layout_loops": ((0, 2), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "branchy": {
                    "layout_type": "fork_return",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (2, 0, ROOM_ROLE_VISTA, "shrine", 2, True),
                        (3, 1, ROOM_ROLE_KEY_ROOM, "storage", 0, False),
                        (4, 1, ROOM_ROLE_RETURN_ROUTE, "cross", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "tech", 3, False),
                        (7, 2, ROOM_ROLE_SWITCH_ROOM, "tech", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "cross", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (2, 8),
                    "return_rooms": (4, 7),
                    "layout_loops": ((0, 3), (4, 6), (7, 9)),
                    "shortcut_specs": ((3, 6, "pickup:blue"), (5, 8, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "pincer": {
                    "layout_type": "fork_return",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "storage", 2, False),
                        (3, 1, ROOM_ROLE_AMBUSH_ROOM, "cross", 0, False),
                        (4, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 3, False),
                        (7, 2, ROOM_ROLE_SHORTCUT_HALL, "cross", 0, False),
                        (8, 2, ROOM_ROLE_KEY_ROOM, "arena", 1, False),
                        (9, 2, ROOM_ROLE_VISTA, "shrine", 2, True),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 9),
                    "return_rooms": (6, 7),
                    "layout_loops": ((0, 2), (3, 5), (6, 8)),
                    "shortcut_specs": ((2, 4, "pickup:blue"), (5, 8, "switch:stage1"), (7, 10, "pickup:yellow")),
                    "key_room_indices": (2, 5, 8),
                },
            },
            "perimeter_inward_push": {
                "default": {
                    "layout_type": "loop_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "storage", 2, False),
                        (3, 1, ROOM_ROLE_VISTA, "shrine", 0, True),
                        (4, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "arena", 3, False),
                        (7, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (3, 8),
                    "return_rooms": (4, 7),
                    "layout_loops": ((0, 2), (2, 5), (5, 8), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "collapse": {
                    "layout_type": "loop_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "storage", 2, False),
                        (3, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 0, False),
                        (4, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 3, False),
                        (7, 2, ROOM_ROLE_AMBUSH_ROOM, "arena", 0, False),
                        (8, 2, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1,),
                    "return_rooms": (4, 8),
                    "layout_loops": ((0, 2), (3, 5), (5, 7), (8, 10)),
                    "shortcut_specs": ((2, 6, "pickup:blue"), (6, 9, "switch:stage1")),
                    "key_room_indices": (2, 5, 9),
                },
                "cross_link": {
                    "layout_type": "loop_spoke",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "tech", 1, False),
                        (2, 0, ROOM_ROLE_VISTA, "shrine", 2, True),
                        (3, 1, ROOM_ROLE_KEY_ROOM, "storage", 0, False),
                        (4, 1, ROOM_ROLE_AMBUSH_ROOM, "cross", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SHORTCUT_HALL, "cross", 3, False),
                        (7, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (8, 2, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (2, 8),
                    "return_rooms": (6, 7),
                    "layout_loops": ((0, 3), (2, 5), (4, 8), (7, 9)),
                    "shortcut_specs": ((3, 6, "pickup:blue"), (5, 8, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
            },
            "two_hub_finale": {
                "default": {
                    "layout_type": "two_hub",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 0, False),
                        (4, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "arena", 3, False),
                        (7, 2, ROOM_ROLE_SHORTCUT_HALL, "cross", 0, False),
                        (8, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1, 8),
                    "return_rooms": (4, 8),
                    "layout_loops": ((0, 2), (3, 6), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (4, 8, "pickup:yellow"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
                "pincer": {
                    "layout_type": "two_hub",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "shrine", 2, False),
                        (3, 1, ROOM_ROLE_VISTA, "shrine", 0, True),
                        (4, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_AMBUSH_ROOM, "arena", 3, False),
                        (7, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (8, 2, ROOM_ROLE_KEY_ROOM, "arena", 1, False),
                        (9, 2, ROOM_ROLE_VISTA, "shrine", 2, True),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (3, 9),
                    "return_rooms": (7,),
                    "layout_loops": ((0, 2), (3, 6), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (4, 8, "pickup:yellow"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 8),
                },
                "collapse": {
                    "layout_type": "two_hub",
                    "node_specs": (
                        (0, 0, ROOM_ROLE_START, "start", 0, False),
                        (1, 0, ROOM_ROLE_VISTA, "shrine", 1, True),
                        (2, 0, ROOM_ROLE_KEY_ROOM, "storage", 2, False),
                        (3, 1, ROOM_ROLE_RETURN_ROUTE, "tech", 0, False),
                        (4, 1, ROOM_ROLE_PRESSURE_CORRIDOR, "cross", 1, False),
                        (5, 1, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (6, 1, ROOM_ROLE_SWITCH_ROOM, "tech", 3, False),
                        (7, 2, ROOM_ROLE_AMBUSH_ROOM, "arena", 0, False),
                        (8, 2, ROOM_ROLE_RETURN_ROUTE, "tech", 1, False),
                        (9, 2, ROOM_ROLE_KEY_ROOM, "arena", 2, False),
                        (10, 3, ROOM_ROLE_FINAL_ROOM, "tech", 0, False),
                    ),
                    "vista_rooms": (1,),
                    "return_rooms": (3, 8),
                    "layout_loops": ((0, 2), (3, 6), (7, 9)),
                    "shortcut_specs": ((2, 5, "pickup:blue"), (4, 8, "pickup:yellow"), (6, 9, "pickup:yellow")),
                    "key_room_indices": (2, 5, 9),
                },
            },
        }
        skeleton_variants = route_variants[skeleton_profile_id]
        requested_variant_id = self._macro_variant_id()
        if requested_variant_id in skeleton_variants:
            variant_definition = skeleton_variants[requested_variant_id]
        else:
            fallback_variant_id = next(iter(skeleton_variants))
            variant_definition = skeleton_variants[fallback_variant_id]

        layout_type = variant_definition["layout_type"]
        base_nodes = variant_definition["node_specs"]
        vista_rooms = tuple(variant_definition["vista_rooms"])
        return_rooms = tuple(variant_definition["return_rooms"])
        layout_loops = tuple(variant_definition["layout_loops"])
        shortcut_specs = tuple(variant_definition["shortcut_specs"])
        key_room_indices = tuple(variant_definition["key_room_indices"])
        nodes = tuple(
            MacroRouteNode(
                room_index,
                stage_index,
                role_hint,
                kind_hint,
                branch_slot=branch_slot,
                requires_vista=requires_vista or room_index in vista_rooms,
            )
            for room_index, stage_index, role_hint, kind_hint, branch_slot, requires_vista in base_nodes
        )

        edges: list[MacroRouteEdge] = []
        for room_a_index, room_b_index in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10)):
            edges.append(
                MacroRouteEdge(
                    edge_id=f"main:{room_a_index}:{room_b_index}",
                    room_a_index=room_a_index,
                    room_b_index=room_b_index,
                    edge_kind=EDGE_MAIN,
                )
            )

        for room_a_index, room_b_index in layout_loops:
            edges.append(
                MacroRouteEdge(
                    edge_id=f"loop:{room_a_index}:{room_b_index}",
                    room_a_index=room_a_index,
                    room_b_index=room_b_index,
                    edge_kind=EDGE_LOOP,
                    note="meaningful_loop",
                )
            )

        for room_a_index, room_b_index, trigger_source in shortcut_specs:
            edges.append(
                MacroRouteEdge(
                    edge_id=f"shortcut:{room_a_index}:{room_b_index}",
                    room_a_index=room_a_index,
                    room_b_index=room_b_index,
                    edge_kind=EDGE_SHORTCUT,
                    trigger_source=trigger_source,
                    note="return_shortcut",
                )
            )

        return MacroRoutePlan(
            layout_type=layout_type,
            nodes=nodes,
            edges=tuple(edges),
            key_room_indices=key_room_indices,
            return_room_indices=return_rooms,
            final_room_index=10,
            vista_room_indices=vista_rooms,
        )

    def _plan_progression_layout(self, route_plan: MacroRoutePlan) -> ProgressionLayout | None:
        room_count = len(route_plan.nodes)
        if room_count < settings.MIN_PROGRESSION_ROOMS:
            return None
        room_stages = [node.stage_index for node in route_plan.nodes]

        stage_rooms = tuple(
            tuple(room_index for room_index, stage in enumerate(room_stages) if stage == stage_index)
            for stage_index in range(4)
        )
        if (
            len(stage_rooms[0]) < 3
            or len(stage_rooms[1]) < 2
            or len(stage_rooms[2]) < 2
            or len(stage_rooms[3]) < 1
        ):
            return None

        boundary_edge_lookup: dict[int, int] = {}
        for edge_index, edge in enumerate(route_plan.edges):
            if edge.edge_kind != EDGE_MAIN:
                continue
            stage_a = room_stages[edge.room_a_index]
            stage_b = room_stages[edge.room_b_index]
            if stage_b == stage_a + 1:
                boundary_edge_lookup[stage_a] = edge_index
        if set(boundary_edge_lookup) != {0, 1, 2}:
            return None

        gate_plans = (
            ProgressionGatePlan(
                key_type="blue",
                stage_index=0,
                connection_index=boundary_edge_lookup[0],
                key_room_candidates=(route_plan.key_room_indices[0],),
                blocked_room_indices=tuple(room_index for room_index, stage in enumerate(room_stages) if stage > 0),
            ),
            ProgressionGatePlan(
                key_type="yellow",
                stage_index=1,
                connection_index=boundary_edge_lookup[1],
                key_room_candidates=(route_plan.key_room_indices[1],),
                blocked_room_indices=tuple(room_index for room_index, stage in enumerate(room_stages) if stage > 1),
            ),
            ProgressionGatePlan(
                key_type="red",
                stage_index=2,
                connection_index=boundary_edge_lookup[2],
                key_room_candidates=(route_plan.key_room_indices[2],),
                blocked_room_indices=stage_rooms[3],
            ),
        )
        if any(not gate.key_room_candidates for gate in gate_plans):
            return None

        return ProgressionLayout(
            room_stages=tuple(room_stages),
            stage_rooms=stage_rooms,
            gate_plans=gate_plans,
        )

    def _build_template_rooms(self, route_plan: MacroRoutePlan, template_variant: str) -> list[Room] | None:
        base_rooms_by_layout: dict[str, dict[str, tuple[tuple[int, int, int, int], ...]]] = {
            "hub_spoke": {
                "spine": (
                    (2, 4, 6, 6), (11, 4, 7, 6), (20, 4, 7, 6), (29, 4, 6, 6), (29, 13, 6, 7),
                    (20, 13, 7, 7), (11, 13, 7, 6), (2, 13, 6, 6), (2, 24, 7, 6), (11, 24, 7, 6), (24, 24, 7, 7),
                ),
                "staggered": (
                    (2, 3, 7, 7), (10, 4, 8, 6), (20, 3, 7, 7), (28, 4, 7, 6), (28, 12, 7, 7),
                    (20, 14, 7, 6), (10, 12, 8, 7), (2, 14, 7, 6), (3, 24, 6, 7), (12, 23, 7, 7), (24, 24, 8, 7),
                ),
                "pockets": (
                    (3, 4, 6, 6), (11, 3, 7, 7), (21, 4, 6, 6), (29, 3, 6, 7), (28, 13, 7, 6),
                    (20, 12, 7, 7), (11, 13, 6, 7), (2, 12, 7, 7), (2, 24, 6, 6), (12, 24, 7, 6), (23, 23, 8, 8),
                ),
            },
            "loop_spoke": {
                "spine": (
                    (2, 3, 7, 7), (11, 4, 6, 6), (20, 4, 6, 6), (29, 3, 6, 7), (29, 13, 6, 6),
                    (20, 13, 6, 7), (11, 13, 6, 6), (2, 13, 7, 6), (2, 24, 6, 7), (11, 24, 6, 6), (24, 24, 7, 7),
                ),
                "staggered": (
                    (2, 4, 6, 6), (10, 3, 7, 7), (20, 3, 7, 7), (28, 4, 7, 6), (29, 12, 6, 7),
                    (20, 14, 7, 6), (11, 12, 7, 7), (2, 14, 6, 6), (3, 24, 6, 7), (11, 23, 7, 7), (23, 24, 8, 7),
                ),
                "pockets": (
                    (3, 3, 7, 7), (11, 4, 7, 6), (20, 4, 7, 6), (29, 4, 6, 6), (28, 13, 7, 6),
                    (21, 12, 6, 7), (10, 13, 7, 6), (2, 12, 7, 7), (2, 24, 7, 6), (12, 24, 6, 6), (24, 23, 8, 8),
                ),
                "perimeter": (
                    (3, 3, 7, 7), (14, 2, 7, 6), (26, 3, 7, 7), (29, 12, 6, 7), (26, 24, 7, 7),
                    (14, 28, 7, 6), (3, 24, 7, 7), (1, 13, 7, 6), (8, 14, 6, 6), (21, 14, 6, 6), (15, 13, 6, 8),
                ),
            },
            "fork_return": {
                "spine": (
                    (2, 4, 6, 6), (11, 3, 7, 7), (20, 4, 6, 6), (29, 4, 6, 6), (29, 13, 6, 6),
                    (20, 12, 7, 7), (11, 13, 6, 6), (2, 13, 6, 7), (2, 24, 6, 6), (11, 23, 7, 7), (24, 24, 7, 7),
                ),
                "staggered": (
                    (2, 3, 7, 7), (10, 3, 8, 7), (20, 4, 7, 6), (28, 3, 7, 7), (28, 13, 7, 6),
                    (20, 13, 7, 7), (11, 12, 7, 7), (2, 14, 7, 6), (3, 24, 6, 6), (11, 24, 8, 6), (23, 23, 8, 8),
                ),
                "pockets": (
                    (3, 4, 6, 6), (11, 3, 7, 7), (21, 4, 6, 6), (29, 4, 6, 6), (29, 12, 6, 7),
                    (20, 12, 7, 7), (10, 13, 7, 6), (2, 13, 7, 7), (2, 24, 7, 6), (12, 23, 7, 7), (24, 24, 8, 7),
                ),
            },
            "double_loop": {
                "spine": (
                    (2, 4, 7, 6), (11, 4, 6, 6), (20, 3, 7, 7), (29, 4, 6, 6), (29, 13, 6, 7),
                    (20, 13, 7, 6), (11, 12, 6, 7), (2, 13, 7, 6), (2, 24, 6, 6), (11, 24, 7, 6), (24, 23, 8, 8),
                ),
                "staggered": (
                    (2, 3, 7, 7), (10, 4, 7, 6), (20, 3, 8, 7), (28, 4, 7, 6), (28, 13, 7, 7),
                    (20, 14, 7, 6), (10, 12, 7, 7), (2, 14, 7, 6), (3, 24, 6, 7), (11, 24, 7, 6), (23, 23, 8, 8),
                ),
                "pockets": (
                    (3, 4, 7, 6), (11, 3, 7, 7), (21, 3, 7, 7), (29, 4, 6, 6), (28, 13, 7, 7),
                    (20, 12, 7, 7), (10, 12, 7, 7), (2, 13, 7, 6), (2, 24, 7, 6), (12, 24, 7, 6), (24, 23, 8, 8),
                ),
            },
            "two_hub": {
                "twinhub": (
                    (3, 4, 7, 7), (14, 3, 7, 7), (25, 4, 7, 7), (28, 13, 7, 7), (24, 24, 7, 7),
                    (13, 24, 7, 7), (3, 23, 7, 8), (2, 13, 7, 7), (9, 13, 6, 7), (21, 13, 6, 7), (15, 11, 6, 10),
                ),
            },
        }
        macro_footprint, footprint_variant, _, mirror_variant = template_variant.split(":", 3)
        layout_packs = base_rooms_by_layout.get(route_plan.layout_type, base_rooms_by_layout["hub_spoke"])
        fallback_pack = layout_packs.get("spine")
        if fallback_pack is None:
            fallback_pack = next(iter(layout_packs.values()))
        base_rooms = layout_packs.get(macro_footprint, fallback_pack)
        if len(base_rooms) < len(route_plan.nodes):
            return None
        mirror_x = "mirror_x" in mirror_variant
        mirror_y = "mirror_y" in mirror_variant

        rooms: list[Room] = []
        for node in route_plan.nodes:
            base_x, base_y, room_w, room_h = base_rooms[node.room_index]
            shape_family, spatial_archetype, ceiling_height, geometry_preset_id = self._choose_room_profile(node)
            room_w, room_h = self._adjust_room_footprint(node, room_w, room_h, footprint_variant)
            room_w, room_h = self._shape_size_adjustment(shape_family, room_w, room_h)
            room_w, room_h = self._apply_request_footprint_profile(node, room_w, room_h)
            placed_room: Room | None = None
            for shrink in range(0, 3):
                candidate_w = max(5, room_w - shrink)
                candidate_h = max(5, room_h - shrink)
                jitter_positions = (
                    (base_x, base_y),
                    (base_x + 1, base_y),
                    (base_x - 1, base_y),
                    (base_x, base_y + 1),
                    (base_x, base_y - 1),
                    (base_x + 1, base_y + 1),
                    (base_x - 1, base_y - 1),
                )
                for raw_x, raw_y in jitter_positions:
                    room_x = raw_x
                    room_y = raw_y
                    if mirror_x:
                        room_x = self.width - room_x - candidate_w
                    if mirror_y:
                        room_y = self.height - room_y - candidate_h
                    room_x = max(1, min(room_x, self.width - candidate_w - 1))
                    room_y = max(1, min(room_y, self.height - candidate_h - 1))
                    candidate_room = Room(
                        room_x,
                        room_y,
                        candidate_w,
                        candidate_h,
                        node.kind_hint,
                        0,
                        shape_family,
                        spatial_archetype,
                        ceiling_height,
                        geometry_preset_id,
                    )
                    if any(candidate_room.intersects(other, padding=0) for other in rooms):
                        continue
                    placed_room = candidate_room
                    break
                if placed_room is not None:
                    break
            if placed_room is None:
                anchor_room = self._planned_profiled_room(
                    node,
                    rooms,
                    candidate_w,
                    candidate_h,
                    shape_family,
                    spatial_archetype,
                    ceiling_height,
                    geometry_preset_id,
                )
                if anchor_room is None:
                    return None
                placed_room = anchor_room
            rooms.append(placed_room)
        return rooms

    def _choose_room_profile(self, node: MacroRouteNode) -> tuple[str, str, int, str]:
        archetype_id = self._campaign_archetype_id() if self.generation_request is not None else None
        preset_pool = self._geometry_preset_pool(node, archetype_id)
        preset_id = preset_pool[(node.room_index + self.rng.randrange(len(preset_pool))) % len(preset_pool)]
        preset_definition = GEOMETRY_PRESET_DEFINITIONS[preset_id]
        return self._finalize_room_profile(node, preset_definition)

    def _geometry_preset_pool(
        self,
        node: MacroRouteNode,
        archetype_id: str | None,
    ) -> tuple[str, ...]:
        if node.role_hint == ROOM_ROLE_START:
            if archetype_id == "waste_plant":
                return ("entry_toxic", "entry_offset")
            if archetype_id in {"outer_ring", "shrine_fortress", "relay_station"}:
                return ("entry_hall", "entry_offset", "entry_grand")
            return ("entry_hall", "entry_offset")
        if node.role_hint == ROOM_ROLE_VISTA:
            if archetype_id == "waste_plant":
                return ("vista_balcony", "vista_ring", "vista_offset")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("vista_balcony", "vista_grand_ring", "vista_grand_offset", "vista_corner")
            return ("vista_balcony", "vista_ring", "vista_offset", "vista_corner")
        if node.role_hint == ROOM_ROLE_KEY_ROOM:
            if node.stage_index == 0:
                if archetype_id == "waste_plant":
                    return ("key_toxic_pit_lane", "key_holdout_island", "key_toxic_crossfire")
                if archetype_id == "relay_station":
                    return ("key_bridge_control", "key_holdout_island", "key_crossfire_ring")
                return ("key_pit_lane", "key_holdout_island", "key_crossfire_ring")
            if archetype_id == "waste_plant":
                return ("key_central_island", "key_holdout_island", "key_toxic_bridge_hold")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("key_grand_island", "key_grand_holdout", "key_bridge_hold")
            return ("key_central_island", "key_holdout_island", "key_bridge_hold")
        if node.role_hint == ROOM_ROLE_RETURN_ROUTE:
            if archetype_id == "waste_plant":
                return ("return_toxic_bridge", "return_toxic_flank", "return_crusher_flank")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("return_bridge_lane", "return_grand_lane", "return_crusher_flank")
            return ("return_bridge_lane", "return_flank_lane", "return_crusher_flank")
        if node.role_hint in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_PRESSURE_CORRIDOR}:
            if archetype_id == "tech_base":
                return ("pressure_crossfire", "pressure_island", "pressure_crusher_flank", "pressure_flank_lane")
            if archetype_id == "relay_station":
                return ("pressure_crossfire", "pressure_bridge_island", "pressure_crusher_flank", "pressure_grand_lane")
            if archetype_id == "waste_plant":
                return ("pressure_toxic_crossfire", "pressure_hazard_island", "pressure_crusher_flank", "pressure_toxic_lane")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("pressure_grand_crossfire", "pressure_island", "pressure_crusher_flank", "pressure_grand_lane")
            return ("pressure_grand_crossfire", "pressure_island", "pressure_crusher_flank", "pressure_flank_lane")
        if node.role_hint == ROOM_ROLE_FINAL_ROOM:
            if archetype_id == "waste_plant":
                return ("final_crossfire", "final_holdout", "final_toxic_bridge")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("final_grand_crossfire", "final_grand_holdout", "final_bridge_lane", "final_corner_crossfire")
            return ("final_crossfire", "final_holdout", "final_bridge_lane", "final_corner_crossfire", "final_ring_crossfire")
        if node.kind_hint == "shrine":
            if archetype_id == "shrine_fortress":
                return ("shrine_grand_ceremonial", "shrine_ring")
            return ("shrine_ceremonial", "shrine_ring", "vista_corner")
        if node.kind_hint == "arena":
            if archetype_id == "waste_plant":
                return ("arena_island", "arena_toxic_crossfire", "arena_toxic_side_bays")
            if archetype_id in {"outer_ring", "shrine_fortress"}:
                return ("arena_grand_island", "arena_crossfire", "arena_corner_crossfire")
            return ("arena_island", "arena_crossfire", "arena_corner_crossfire", "arena_toxic_side_bays")
        if archetype_id == "waste_plant":
            return ("general_toxic_standard", "general_flank_lane", "general_recessed_flank")
        if archetype_id in {"outer_ring", "shrine_fortress"}:
            return ("general_grand_standard", "general_flank_lane", "general_recessed_flank")
        return ("general_standard", "general_flank_lane", "general_recessed_flank", "general_side_bays")

    def _finalize_room_profile(
        self,
        node: MacroRouteNode,
        preset_definition: GeometryPresetDefinition,
    ) -> tuple[str, str, int, str]:
        shape_family = preset_definition.shape_family
        spatial_archetype = preset_definition.spatial_archetype
        ceiling_height = preset_definition.ceiling_height
        geometry_preset_id = preset_definition.preset_id
        spatial_profile_id = self._spatial_profile_id()
        encounter_style_id = self._encounter_style_id()
        level_modifier_id = self._level_modifier_id()
        macro_variant_id = self._macro_variant_id()
        theme_modifier_id = self._theme_modifier_id()

        if spatial_profile_id == "vertical" and node.role_hint in {ROOM_ROLE_VISTA, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_KEY_ROOM}:
            ceiling_height = max(ceiling_height, 3 if node.role_hint != ROOM_ROLE_FINAL_ROOM else 4)
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_OVERLOOK_VISTA
        elif spatial_profile_id == "expansive" and node.role_hint in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_KEY_ROOM}:
            if shape_family in {"offset_rect", "recessed_endcap"}:
                shape_family = "central_island"
            if spatial_archetype == ARCHETYPE_OFFSET_CORRIDOR:
                spatial_archetype = ARCHETYPE_GRAND_CHAMBER
        elif spatial_profile_id == "tight" and node.role_hint in {ROOM_ROLE_PRESSURE_CORRIDOR, ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_SHORTCUT_HALL}:
            if shape_family not in {"offset_rect", "recessed_endcap"}:
                shape_family = "offset_rect"
            if spatial_archetype in {ARCHETYPE_GRAND_CHAMBER, ARCHETYPE_HIGH_CEILING_HALL}:
                spatial_archetype = ARCHETYPE_OFFSET_CORRIDOR

        if level_modifier_id == "lockdown" and node.role_hint in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_PRESSURE_CORRIDOR, ROOM_ROLE_FINAL_ROOM}:
            shape_family = "split_by_pillar_line"
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_CRUSHER_PASSAGE
        elif level_modifier_id == "vista_dominant" and node.role_hint in {ROOM_ROLE_VISTA, ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_START}:
            ceiling_height = max(ceiling_height, 3)
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_OVERLOOK_VISTA
        elif level_modifier_id == "shortcut_surge" and node.role_hint in {ROOM_ROLE_SHORTCUT_HALL, ROOM_ROLE_RETURN_ROUTE}:
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_BRIDGE_CROSSING

        if encounter_style_id == "holdout" and node.role_hint in {ROOM_ROLE_KEY_ROOM, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_SWITCH_ROOM}:
            shape_family = "raised_platform" if node.role_hint != ROOM_ROLE_SWITCH_ROOM else "central_island"
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_RAISED_PLATFORM
        elif encounter_style_id == "hunter" and node.role_hint in {ROOM_ROLE_PRESSURE_CORRIDOR, ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_SHORTCUT_HALL}:
            if shape_family not in {"offset_rect", "recessed_endcap"}:
                shape_family = "offset_rect"
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_OFFSET_CORRIDOR
        elif encounter_style_id == "pincer" and node.role_hint in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_PRESSURE_CORRIDOR}:
            if shape_family not in {"split_by_pillar_line", "ring_like"}:
                shape_family = "split_by_pillar_line"
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_SPLIT_ARENA

        if macro_variant_id in {"collapse", "pincer"} and node.role_hint in {ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_KEY_ROOM, ROOM_ROLE_AMBUSH_ROOM}:
            ceiling_height = max(ceiling_height, 3)

        if theme_modifier_id == "corrosion" and node.role_hint in {ROOM_ROLE_KEY_ROOM, ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_PRESSURE_CORRIDOR}:
            if spatial_archetype in {"standard", ARCHETYPE_HIGH_CEILING_HALL, ARCHETYPE_OFFSET_CORRIDOR}:
                spatial_archetype = ARCHETYPE_TOXIC_CANALS
        elif theme_modifier_id == "ritual" and node.kind_hint in {"shrine", "arena"}:
            if spatial_archetype in {"standard", ARCHETYPE_HIGH_CEILING_HALL}:
                spatial_archetype = ARCHETYPE_GRAND_CHAMBER
            ceiling_height = max(ceiling_height, 3)
        elif theme_modifier_id == "siege" and node.role_hint in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_SWITCH_ROOM}:
            if spatial_archetype in {"standard", ARCHETYPE_HIGH_CEILING_HALL}:
                spatial_archetype = ARCHETYPE_SPLIT_ARENA
        elif theme_modifier_id == "power_failure" and node.kind_hint == "tech":
            if spatial_archetype == "standard":
                spatial_archetype = ARCHETYPE_OFFSET_CORRIDOR

        geometry_preset_id = self._resolve_geometry_preset_id(
            node,
            shape_family,
            spatial_archetype,
            base_preset_id=geometry_preset_id,
        )
        return (shape_family, spatial_archetype, ceiling_height, geometry_preset_id)

    def _resolve_geometry_preset_id(
        self,
        node: MacroRouteNode,
        shape_family: str,
        spatial_archetype: str,
        base_preset_id: str | None = None,
    ) -> str:
        if base_preset_id is not None:
            role_prefix, _, existing_suffix = base_preset_id.partition("_")
        else:
            role_prefix = {
                ROOM_ROLE_START: "entry",
                ROOM_ROLE_VISTA: "vista",
                ROOM_ROLE_KEY_ROOM: "key",
                ROOM_ROLE_RETURN_ROUTE: "return",
                ROOM_ROLE_SHORTCUT_HALL: "shortcut",
                ROOM_ROLE_SWITCH_ROOM: "switch",
                ROOM_ROLE_AMBUSH_ROOM: "ambush",
                ROOM_ROLE_PRESSURE_CORRIDOR: "pressure",
                ROOM_ROLE_FINAL_ROOM: "finale",
            }.get(node.role_hint, "general")
            existing_suffix = ""
        if spatial_archetype in {ARCHETYPE_TOXIC_PIT_ROOM, ARCHETYPE_BRIDGE_CROSSING, ARCHETYPE_ACID_RING, ARCHETYPE_TOXIC_CANALS}:
            suffix = "hazard_lane"
        elif shape_family in {"raised_platform", "central_island"} or spatial_archetype == ARCHETYPE_RAISED_PLATFORM:
            suffix = "holdout_island"
        elif shape_family in {"split_by_pillar_line", "ring_like"}:
            suffix = "crossfire"
        elif shape_family in {"offset_rect", "recessed_endcap"}:
            suffix = "flank"
        else:
            suffix = "standard"
        if existing_suffix in {"balcony", "corner", "ring", "ceremonial"} and suffix == "standard":
            suffix = existing_suffix
        return f"{role_prefix}_{suffix}"

    def _shape_size_adjustment(self, shape_family: str, width: int, height: int) -> tuple[int, int]:
        if shape_family in {"ring_like", "bridge_room", "pit_with_walkway", "side_bays"}:
            return (max(width, 7), max(height, 7))
        if shape_family in {"split_by_pillar_line", "raised_platform", "corner_pillars"}:
            return (max(width, 6), max(height, 6))
        return (width, height)

    def _build_template_connections(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        route_plan: MacroRoutePlan,
        template_variant: str,
    ) -> list[CorridorConnection] | None:
        _, _, corridor_variant, mirror_variant = template_variant.split(":", 3)
        segment_map, explicit_doors = self._segment_profile(route_plan.layout_type, corridor_variant)
        mirror_x = "mirror_x" in mirror_variant
        mirror_y = "mirror_y" in mirror_variant

        def transform_segment(segment: tuple[str, int, int, int]) -> tuple[str, int, int, int]:
            axis, start, end, fixed = segment
            if axis == "h":
                if mirror_x:
                    start, end = sorted((self.width - 1 - start, self.width - 1 - end))
                if mirror_y:
                    fixed = self.height - 1 - fixed
            else:
                if mirror_y:
                    start, end = sorted((self.height - 1 - start, self.height - 1 - end))
                if mirror_x:
                    fixed = self.width - 1 - fixed
            return (axis, start, end, fixed)

        def transform_door(door: tuple[int, int, str]) -> tuple[int, int, str]:
            door_x, door_y, orientation = door
            if mirror_x:
                door_x = self.width - 1 - door_x
            if mirror_y:
                door_y = self.height - 1 - door_y
            return (door_x, door_y, orientation)

        connections: list[CorridorConnection] = []
        for edge in route_plan.edges:
            segments = segment_map.get(edge.edge_id)
            path: list[tuple[int, int]] = []
            door_candidate = explicit_doors.get(edge.edge_id)
            if segments is None:
                path = self._connect_rooms(
                    tiles,
                    floor_heights,
                    ceiling_heights,
                    stair_mask,
                    room_kinds,
                    sector_types,
                    rooms[edge.room_a_index],
                    rooms[edge.room_b_index],
                    widen_chance=0.0,
                )
                door_candidate = None
            else:
                transformed_segments = [transform_segment(segment) for segment in segments]
                for axis, start, end, fixed in transformed_segments:
                    if axis == "h":
                        path.extend(self._carve_h_corridor(tiles, start, end, fixed, widen_chance=0.0))
                    else:
                        path.extend(self._carve_v_corridor(tiles, start, end, fixed, widen_chance=0.0))
                    self._assign_path_heights(path, floor_heights, ceiling_heights, stair_mask, room_kinds, sector_types)
                if door_candidate is not None:
                    door_candidate = transform_door(door_candidate)
                    if not self._is_connection_door_candidate_valid(
                        tiles,
                        rooms,
                        edge.room_a_index,
                        edge.room_b_index,
                        path,
                        door_candidate,
                    ):
                        door_candidate = None
            connections.append(
                CorridorConnection(
                    index=len(connections),
                    room_a_index=edge.room_a_index,
                    room_b_index=edge.room_b_index,
                    path=path,
                    is_main_path=edge.edge_kind == EDGE_MAIN,
                    door_candidate=door_candidate,
                    edge_kind=edge.edge_kind,
                    trigger_source=edge.trigger_source,
                )
            )
        return connections

    def _segment_profile(
        self,
        layout_type: str,
        corridor_variant: str,
    ) -> tuple[dict[str, list[tuple[str, int, int, int]]], dict[str, tuple[int, int, str]]]:
        if corridor_variant == "perimeter":
            perimeter_segments: dict[str, list[tuple[str, int, int, int]]] = {
                "main:0:1": [("h", 10, 13, 6)],
                "main:1:2": [("h", 20, 24, 6)],
                "main:2:3": [("v", 10, 14, 31)],
                "main:3:4": [("v", 19, 23, 28)],
                "main:4:5": [("h", 20, 24, 27)],
                "main:5:6": [("h", 10, 13, 27)],
                "main:6:7": [("v", 16, 20, 6)],
                "main:7:8": [("h", 8, 10, 16)],
                "main:8:9": [("h", 16, 20, 16)],
                "main:9:10": [("h", 19, 22, 16)],
                "loop:0:2": [("h", 8, 28, 10)],
                "loop:2:5": [("v", 10, 26, 24)],
                "loop:5:8": [("h", 10, 20, 22)],
                "loop:7:9": [("h", 6, 22, 19)],
                "shortcut:2:5": [("v", 10, 23, 28)],
                "shortcut:6:9": [("h", 9, 20, 24)],
            }
            perimeter_doors: dict[str, tuple[int, int, str]] = {
                "main:2:3": (31, 14, "horizontal"),
                "main:6:7": (6, 18, "horizontal"),
                "main:9:10": (22, 16, "vertical"),
                "shortcut:2:5": (28, 18, "horizontal"),
                "shortcut:6:9": (15, 24, "vertical"),
            }
            return perimeter_segments, perimeter_doors

        if corridor_variant == "twohub" or layout_type == "two_hub":
            twohub_segments: dict[str, list[tuple[str, int, int, int]]] = {
                "main:0:1": [("h", 10, 13, 7)],
                "main:1:2": [("h", 20, 24, 7)],
                "main:2:3": [("v", 10, 14, 31)],
                "main:3:4": [("v", 20, 23, 28)],
                "main:4:5": [("h", 19, 21, 27)],
                "main:5:6": [("h", 10, 12, 27)],
                "main:6:7": [("v", 16, 23, 6)],
                "main:7:8": [("h", 9, 11, 16)],
                "main:8:9": [("h", 18, 21, 16)],
                "main:9:10": [("h", 18, 21, 16)],
                "loop:0:2": [("h", 10, 24, 11)],
                "loop:2:4": [("v", 10, 24, 27)],
                "loop:5:7": [("h", 6, 18, 23)],
                "loop:7:9": [("h", 6, 21, 18)],
                "shortcut:2:5": [("v", 11, 24, 21)],
                "shortcut:4:8": [("h", 17, 21, 23)],
                "shortcut:6:9": [("h", 10, 21, 20)],
            }
            twohub_doors: dict[str, tuple[int, int, str]] = {
                "main:2:3": (31, 14, "horizontal"),
                "main:6:7": (6, 18, "horizontal"),
                "main:9:10": (18, 16, "vertical"),
                "shortcut:2:5": (21, 18, "horizontal"),
                "shortcut:4:8": (19, 23, "vertical"),
                "shortcut:6:9": (15, 20, "vertical"),
            }
            return twohub_segments, twohub_doors

        direct_segments: dict[str, list[tuple[str, int, int, int]]] = {
            "main:0:1": [("h", 8, 10, 7)],
            "main:1:2": [("h", 17, 19, 7)],
            "main:2:3": [("h", 26, 28, 7)],
            "main:3:4": [("v", 10, 12, 32)],
            "main:4:5": [("h", 26, 28, 16)],
            "main:5:6": [("h", 17, 19, 16)],
            "main:6:7": [("h", 8, 10, 16)],
            "main:7:8": [("v", 19, 23, 5)],
            "main:8:9": [("h", 8, 10, 27)],
            "main:9:10": [("h", 17, 23, 27)],
            "loop:0:2": [("v", 9, 10, 5), ("h", 5, 23, 10), ("v", 9, 10, 23)],
            "loop:7:9": [("v", 19, 22, 5), ("h", 6, 14, 22), ("v", 23, 24, 14)],
            "shortcut:2:5": [("v", 10, 12, 23)],
            "shortcut:4:8": [("v", 16, 23, 28), ("h", 6, 28, 23)],
            "shortcut:6:9": [("v", 19, 23, 14)],
        }
        direct_doors: dict[str, tuple[int, int, str]] = {
            "main:2:3": (27, 7, "vertical"),
            "main:6:7": (9, 16, "vertical"),
            "main:9:10": (23, 27, "vertical"),
            "shortcut:2:5": (23, 11, "horizontal"),
            "shortcut:4:8": (28, 19, "horizontal"),
            "shortcut:6:9": (14, 21, "horizontal"),
        }
        if corridor_variant != "dogleg":
            return direct_segments, direct_doors

        dogleg_segments: dict[str, list[tuple[str, int, int, int]]] = {
            "main:0:1": [("h", 8, 10, 8)],
            "main:1:2": [("v", 7, 8, 17), ("h", 17, 19, 8)],
            "main:2:3": [("h", 26, 28, 8)],
            "main:3:4": [("v", 8, 10, 31), ("h", 31, 32, 10), ("v", 10, 12, 32)],
            "main:4:5": [("h", 26, 28, 15)],
            "main:5:6": [("v", 15, 17, 19), ("h", 17, 19, 17)],
            "main:6:7": [("h", 8, 10, 15)],
            "main:7:8": [("v", 16, 23, 6)],
            "main:8:9": [("h", 8, 10, 26)],
            "main:9:10": [("v", 26, 28, 17), ("h", 17, 23, 28)],
            "loop:0:2": [("v", 8, 10, 6), ("h", 6, 23, 10)],
            "loop:2:4": [("h", 23, 31, 10), ("v", 10, 15, 31)],
            "loop:5:7": [("h", 6, 20, 22)],
            "loop:7:9": [("v", 16, 24, 6), ("h", 6, 14, 24)],
            "shortcut:2:5": [("v", 10, 12, 22)],
            "shortcut:4:8": [("v", 15, 24, 29), ("h", 6, 29, 24)],
            "shortcut:6:9": [("v", 17, 23, 14)],
        }
        dogleg_doors: dict[str, tuple[int, int, str]] = {
            "main:2:3": (27, 8, "vertical"),
            "main:6:7": (9, 15, "vertical"),
            "main:9:10": (20, 28, "vertical"),
            "shortcut:2:5": (22, 11, "horizontal"),
            "shortcut:4:8": (29, 18, "horizontal"),
            "shortcut:6:9": (14, 20, "horizontal"),
        }
        return dogleg_segments, dogleg_doors

    def _adjust_room_footprint(
        self,
        node: MacroRouteNode,
        width: int,
        height: int,
        footprint_variant: str,
    ) -> tuple[int, int]:
        if node.role_hint == ROOM_ROLE_FINAL_ROOM:
            return (max(width, 7), max(height, 7))
        if footprint_variant == "tight":
            if node.kind_hint in {"storage", "tech"}:
                width = max(6, width - 1)
                height = max(6, height - (1 if node.branch_slot % 2 == 0 else 0))
        elif footprint_variant == "wide":
            if node.kind_hint in {"arena", "shrine", "cross"}:
                width = min(width + 1, 8)
                height = min(height + 1, 8)
            elif node.kind_hint == "tech":
                width = min(width + 1, 7)
        return (width, height)

    def _apply_request_footprint_profile(
        self,
        node: MacroRouteNode,
        width: int,
        height: int,
    ) -> tuple[int, int]:
        spatial_profile_id = self._spatial_profile_id()
        level_modifier_id = self._level_modifier_id()
        role = node.role_hint
        kind = node.kind_hint
        if spatial_profile_id == "expansive":
            if role in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_FINAL_ROOM, ROOM_ROLE_KEY_ROOM, ROOM_ROLE_VISTA} or kind in {"arena", "shrine", "cross"}:
                width += 1
                height += 1
        elif spatial_profile_id == "tight":
            if role in {ROOM_ROLE_PRESSURE_CORRIDOR, ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_SHORTCUT_HALL} or kind in {"tech", "storage"}:
                width -= 1
                height -= 1 if role != ROOM_ROLE_RETURN_ROUTE else 0
        elif spatial_profile_id == "vertical":
            if role in {ROOM_ROLE_VISTA, ROOM_ROLE_FINAL_ROOM}:
                width = max(width, 7)
                height += 1

        if level_modifier_id == "lockdown" and role in {ROOM_ROLE_PRESSURE_CORRIDOR, ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_FINAL_ROOM}:
            width = max(6, width - 1)
            height = max(6, height - (0 if role == ROOM_ROLE_FINAL_ROOM else 1))
        elif level_modifier_id == "vista_dominant" and role in {ROOM_ROLE_VISTA, ROOM_ROLE_START, ROOM_ROLE_RETURN_ROUTE}:
            width += 1
            height += 1
        elif level_modifier_id == "shortcut_surge" and role in {ROOM_ROLE_SHORTCUT_HALL, ROOM_ROLE_RETURN_ROUTE}:
            width = max(6, width - 1)
            height = max(6, height)

        width = max(5, min(width, self.width - 3))
        height = max(5, min(height, self.height - 3))
        return (width, height)

    def _planned_room(self, node: MacroRouteNode, rooms: list[Room]) -> Room | None:
        kind = node.kind_hint
        floor_height = 0
        width, height = self._room_dimensions(kind)
        if node.role_hint == ROOM_ROLE_FINAL_ROOM:
            width = min(width, 6)
            height = min(height, 6)
        for shrink in (0, 1, 2, 3, 4):
            width_try = max(5, width - shrink)
            height_try = max(5, height - shrink)
            min_x, max_x, min_y, max_y = self._room_bounds_for_stage(node.stage_index, node.branch_slot, width_try, height_try)
            for _ in range(settings.MAX_ROOMS * 8):
                x = self.rng.randint(min_x, max_x)
                y = self.rng.randint(min_y, max_y)
                room = Room(x, y, width_try, height_try, kind, floor_height)
                if any(room.intersects(other) for other in rooms):
                    continue
                return room
        return None

    def _planned_profiled_room(
        self,
        node: MacroRouteNode,
        rooms: list[Room],
        width: int,
        height: int,
        shape_family: str,
        spatial_archetype: str,
        ceiling_height: int,
        geometry_preset_id: str,
    ) -> Room | None:
        min_x, max_x, min_y, max_y = self._room_bounds_for_stage(node.stage_index, node.branch_slot, width, height)
        for _ in range(settings.MAX_ROOMS * 10):
            x = self.rng.randint(min_x, max_x)
            y = self.rng.randint(min_y, max_y)
            room = Room(
                x,
                y,
                width,
                height,
                node.kind_hint,
                0,
                shape_family,
                spatial_archetype,
                ceiling_height,
                geometry_preset_id,
            )
            if any(room.intersects(other, padding=0) for other in rooms):
                continue
            return room
        return None

    def _room_bounds_for_stage(self, stage_index: int, branch_slot: int, width: int, height: int) -> tuple[int, int, int, int]:
        anchor_centers = {
            0: ((6, 8), (17, 8), (28, 8)),
            1: ((30, 11), (23, 22), (15, 18), (6, 18)),
            2: ((6, 29), (17, 29), (27, 29)),
            3: ((30, 20),),
        }
        anchors = anchor_centers[stage_index]
        slot_index = min(branch_slot, len(anchors) - 1)
        center_x, center_y = anchors[slot_index]
        jitter = 2 if stage_index != 3 else 1
        min_x = max(1, center_x - width // 2 - jitter)
        max_x = min(self.width - width - 2, center_x - width // 2 + jitter)
        min_y = max(1, center_y - height // 2 - jitter)
        max_y = min(self.height - height - 2, center_y - height // 2 + jitter)
        min_x = max(1, min(min_x, self.width - width - 2))
        max_x = max(min_x, min(max_x, self.width - width - 2))
        min_y = max(1, min(min_y, self.height - height - 2))
        max_y = max(min_y, min(max_y, self.height - height - 2))
        return (min_x, max_x, min_y, max_y)

    def _room_dimensions(self, kind: str) -> tuple[int, int]:
        if kind == "arena":
            width = self.rng.randint(max(7, settings.ROOM_MIN_SIZE + 2), settings.ROOM_MAX_SIZE + 2)
            height = self.rng.randint(max(7, settings.ROOM_MIN_SIZE + 2), settings.ROOM_MAX_SIZE + 2)
        elif kind == "shrine":
            side = self.rng.randint(max(7, settings.ROOM_MIN_SIZE + 3), settings.ROOM_MAX_SIZE + 1)
            width = side
            height = side
        elif kind == "tech":
            width = self.rng.randint(settings.ROOM_MIN_SIZE + 1, settings.ROOM_MAX_SIZE + 1)
            height = self.rng.randint(settings.ROOM_MIN_SIZE, settings.ROOM_MAX_SIZE - 1)
        elif kind == "cross":
            width = self.rng.randint(max(8, settings.ROOM_MIN_SIZE + 3), settings.ROOM_MAX_SIZE + 1)
            height = self.rng.randint(max(8, settings.ROOM_MIN_SIZE + 3), settings.ROOM_MAX_SIZE + 1)
        else:
            width = self.rng.randint(settings.ROOM_MIN_SIZE, settings.ROOM_MAX_SIZE)
            height = self.rng.randint(settings.ROOM_MIN_SIZE, settings.ROOM_MAX_SIZE)
        width = min(width, self.width - 3)
        height = min(height, self.height - 3)
        return width, height

    def _carve_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        kind_index = ROOM_KINDS.index(room.kind)
        for y in range(room.y, room.y + room.height):
            for x in range(room.x, room.x + room.width):
                tiles[y][x] = 0
                floor_heights[y][x] = room.floor_height
                ceiling_heights[y][x] = room.ceiling_height
                room_kinds[y][x] = kind_index
                sector_types[y][x] = SECTOR_SAFE

    def _connect_rooms(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        a: Room,
        b: Room,
        widen_chance: float = 0.0,
    ) -> list[tuple[int, int]]:
        ax, ay = a.center
        bx, by = b.center
        if self.rng.random() < 0.5:
            path = self._carve_h_corridor(tiles, ax, bx, ay, widen_chance=widen_chance)
            path.extend(self._carve_v_corridor(tiles, ay, by, bx, widen_chance=widen_chance))
        else:
            path = self._carve_v_corridor(tiles, ay, by, ax, widen_chance=widen_chance)
            path.extend(self._carve_h_corridor(tiles, ax, bx, by, widen_chance=widen_chance))

        self._assign_path_heights(path, floor_heights, ceiling_heights, stair_mask, room_kinds, sector_types)
        return path

    def _carve_h_corridor(
        self,
        tiles: list[list[int]],
        x1: int,
        x2: int,
        y: int,
        widen_chance: float = 0.0,
    ) -> list[tuple[int, int]]:
        carved: list[tuple[int, int]] = []
        for x in range(min(x1, x2), max(x1, x2) + 1):
            tiles[y][x] = 0
            carved.append((x, y))
            if y + 1 < self.height - 1 and widen_chance > 0.0 and self.rng.random() < widen_chance:
                tiles[y + 1][x] = 0
                carved.append((x, y + 1))
        return carved

    def _carve_v_corridor(
        self,
        tiles: list[list[int]],
        y1: int,
        y2: int,
        x: int,
        widen_chance: float = 0.0,
    ) -> list[tuple[int, int]]:
        carved: list[tuple[int, int]] = []
        for y in range(min(y1, y2), max(y1, y2) + 1):
            tiles[y][x] = 0
            carved.append((x, y))
            if x + 1 < self.width - 1 and widen_chance > 0.0 and self.rng.random() < widen_chance:
                tiles[y][x + 1] = 0
                carved.append((x + 1, y))
        return carved

    def _assign_path_heights(
        self,
        path: list[tuple[int, int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
    ) -> None:
        seen: set[tuple[int, int]] = set()
        corridor_kind = ROOM_KINDS.index("tech")
        for x, y in path:
            if (x, y) in seen:
                continue
            seen.add((x, y))
            floor_heights[y][x] = 0
            ceiling_heights[y][x] = max(ceiling_heights[y][x], 1)
            room_kinds[y][x] = corridor_kind
            sector_types[y][x] = SECTOR_SAFE
            stair_mask[y][x] = 0

    def _decorate_rooms(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
    ) -> None:
        for room in rooms:
            if room.kind == "storage":
                self._decorate_storage(tiles, room)
            elif room.kind == "arena":
                self._decorate_arena(tiles, room)
            elif room.kind == "tech":
                self._decorate_tech(tiles, room)
            elif room.kind == "shrine":
                self._decorate_shrine(tiles, floor_heights, stair_mask, room_kinds, room)
            elif room.kind == "cross":
                self._decorate_cross(tiles, room)
            self._apply_shape_family(tiles, room)
            self._apply_spatial_archetype(
                tiles,
                floor_heights,
                ceiling_heights,
                stair_mask,
                room_kinds,
                sector_types,
                room,
            )

    def _apply_shape_family(self, tiles: list[list[int]], room: Room) -> None:
        if room.shape_family == "cut_corner":
            self._shape_cut_corner(tiles, room)
            return
        if room.shape_family == "central_island":
            self._shape_central_island(tiles, room)
            return
        if room.shape_family == "ring_like":
            self._shape_ring_like(tiles, room)
            return
        if room.shape_family == "split_by_pillar_line":
            self._shape_split_by_pillar_line(tiles, room)
            return
        if room.shape_family == "recessed_endcap":
            self._shape_recessed_endcap(tiles, room)
            return
        if room.shape_family == "offset_rect":
            self._shape_offset_rect(tiles, room)
            return
        if room.shape_family == "corner_pillars":
            self._shape_corner_pillars(tiles, room)
            return
        if room.shape_family == "side_bays":
            self._shape_side_bays(tiles, room)

    def _shape_cut_corner(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6 or room.height < 6:
            return
        corners = (
            ((room.x + 1, room.y + 1), (room.x + 2, room.y + 1), (room.x + 1, room.y + 2)),
            ((room.x + room.width - 2, room.y + 1), (room.x + room.width - 3, room.y + 1), (room.x + room.width - 2, room.y + 2)),
            ((room.x + 1, room.y + room.height - 2), (room.x + 2, room.y + room.height - 2), (room.x + 1, room.y + room.height - 3)),
            ((room.x + room.width - 2, room.y + room.height - 2), (room.x + room.width - 3, room.y + room.height - 2), (room.x + room.width - 2, room.y + room.height - 3)),
        )
        for x, y in corners[(room.x + room.y + room.width) % len(corners)]:
            tiles[y][x] = 1

    def _shape_central_island(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6 or room.height < 6:
            return
        cx, cy = room.center
        for y in range(cy - 1, cy + 1):
            for x in range(cx - 1, cx + 1):
                tiles[y][x] = 1

    def _shape_ring_like(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7 or room.height < 7:
            return
        inner_left = room.x + room.width // 2 - 1
        inner_top = room.y + room.height // 2 - 1
        for y in range(inner_top, inner_top + 2):
            for x in range(inner_left, inner_left + 2):
                tiles[y][x] = 1

    def _shape_split_by_pillar_line(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7:
            return
        line_y = room.y + room.height // 2
        for x in range(room.x + 2, room.x + room.width - 2, 2):
            if x not in {room.x + 3, room.x + room.width - 4}:
                tiles[line_y][x] = 1

    def _shape_recessed_endcap(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6:
            return
        recess_x = room.x + room.width - 2 if (room.x + room.y) % 2 == 0 else room.x + 1
        for y in range(room.y + 1, room.y + room.height - 1):
            if y not in {room.y + room.height // 2 - 1, room.y + room.height // 2}:
                tiles[y][recess_x] = 1

    def _shape_offset_rect(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7 or room.height < 6:
            return
        split_x = room.x + room.width // 2
        gap_y = room.y + 2 + ((room.x + room.y) % max(1, room.height - 4))
        for y in range(room.y + 1, room.y + room.height - 1):
            if y in {gap_y, min(room.y + room.height - 2, gap_y + 1)}:
                continue
            tiles[y][split_x] = 1

    def _shape_corner_pillars(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7 or room.height < 7:
            return
        pillar_offsets = (
            (2, 2),
            (room.width - 3, 2),
            (2, room.height - 3),
            (room.width - 3, room.height - 3),
        )
        for offset_x, offset_y in pillar_offsets:
            tiles[room.y + offset_y][room.x + offset_x] = 1

    def _shape_side_bays(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 8 or room.height < 7:
            return
        mid_y = room.y + room.height // 2
        bay_depth = 2 if room.width >= 9 else 1
        for y in range(room.y + 1, room.y + room.height - 1):
            if abs(y - mid_y) <= 1:
                continue
            for step in range(bay_depth):
                tiles[y][room.x + 2 + step] = 1
                tiles[y][room.x + room.width - 3 - step] = 1

    def _apply_spatial_archetype(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        if room.ceiling_height > 1:
            for y in range(room.y, room.y + room.height):
                for x in range(room.x, room.x + room.width):
                    if tiles[y][x] == 0:
                        ceiling_heights[y][x] = max(ceiling_heights[y][x], room.ceiling_height)
        if room.spatial_archetype == ARCHETYPE_HIGH_CEILING_HALL:
            self._paint_room_kind(room, tiles, room_kinds, ROOM_KIND_VISTA)
            return
        if room.spatial_archetype == ARCHETYPE_TOXIC_PIT_ROOM:
            self._carve_toxic_pit_room(tiles, floor_heights, stair_mask, room_kinds, sector_types, room)
            return
        if room.spatial_archetype == ARCHETYPE_BRIDGE_CROSSING:
            self._carve_bridge_room(tiles, floor_heights, stair_mask, room_kinds, sector_types, room)
            return
        if room.spatial_archetype == ARCHETYPE_OFFSET_CORRIDOR:
            self._carve_offset_corridor(tiles, room)
            return
        if room.spatial_archetype == ARCHETYPE_SPLIT_ARENA:
            self._carve_split_arena(tiles, room)
            return
        if room.spatial_archetype == ARCHETYPE_OVERLOOK_VISTA:
            self._carve_overlook_vista(tiles, floor_heights, stair_mask, room_kinds, room)
            return
        if room.spatial_archetype == ARCHETYPE_CRUSHER_PASSAGE:
            self._carve_crusher_passage(tiles, room)
            return
        if room.spatial_archetype == ARCHETYPE_RAISED_PLATFORM:
            self._carve_raised_platform_room(tiles, floor_heights, stair_mask, room, sector_types, room_kinds)
            return
        if room.spatial_archetype == ARCHETYPE_ACID_RING:
            self._carve_acid_ring_room(tiles, floor_heights, stair_mask, room_kinds, sector_types, room)
            return
        if room.spatial_archetype == ARCHETYPE_TOXIC_CANALS:
            self._carve_toxic_canals_room(tiles, floor_heights, stair_mask, room_kinds, sector_types, room)
            return
        if room.spatial_archetype == ARCHETYPE_GRAND_CHAMBER:
            self._carve_grand_chamber(tiles, ceiling_heights, room)

    def _paint_room_kind(
        self,
        room: Room,
        tiles: list[list[int]],
        room_kinds: list[list[int]],
        kind_index: int,
    ) -> None:
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] == 0:
                    room_kinds[y][x] = kind_index

    def _mark_sector(
        self,
        x: int,
        y: int,
        sector_types: list[list[int]],
        room_kinds: list[list[int]],
        sector_type: int,
    ) -> None:
        sector_types[y][x] = sector_type
        if sector_type == SECTOR_ACID:
            room_kinds[y][x] = ROOM_KIND_HAZARD
        elif sector_type == SECTOR_BRIDGE:
            room_kinds[y][x] = ROOM_KIND_CATWALK

    def _carve_toxic_pit_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 6 or room.height < 6:
            return
        bridge_half_width = 0
        cx, cy = room.center
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0:
                    continue
                interior = room.x + 2 <= x <= room.x + room.width - 3 and room.y + 2 <= y <= room.y + room.height - 3
                on_bridge = abs(x - cx) <= bridge_half_width or abs(y - cy) <= bridge_half_width
                if interior and not on_bridge:
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_ACID)
                    floor_heights[y][x] = 0
                    stair_mask[y][x] = 0
                elif on_bridge:
                    floor_heights[y][x] = room.floor_height
                    stair_mask[y][x] = 0
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_BRIDGE)

    def _carve_bridge_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 6 or room.height < 6:
            return
        horizontal = room.width >= room.height
        bridge_half_width = 1 if self.difficulty_id == "easy" else 0
        cx, cy = room.center
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0:
                    continue
                on_bridge = abs(y - cy) <= bridge_half_width if horizontal else abs(x - cx) <= bridge_half_width
                if on_bridge:
                    floor_heights[y][x] = room.floor_height
                    stair_mask[y][x] = 0
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_BRIDGE)
                elif room.x + 2 <= x <= room.x + room.width - 3 and room.y + 2 <= y <= room.y + room.height - 3:
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_ACID)
                    stair_mask[y][x] = 0

    def _carve_offset_corridor(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 8 or room.height < 6:
            return
        split_x = room.x + room.width // 2
        gap_start = room.y + room.height // 2 - 1
        for y in range(room.y + 1, room.y + room.height - 1):
            if gap_start <= y <= gap_start + 2:
                continue
            tiles[y][split_x] = 1

    def _carve_split_arena(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7 or room.height < 7:
            return
        split_y = room.y + room.height // 2
        gap_positions = {room.x + 2, room.x + room.width - 3}
        for x in range(room.x + 1, room.x + room.width - 1):
            if x in gap_positions:
                continue
            tiles[split_y][x] = 1

    def _carve_overlook_vista(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        room: Room,
    ) -> None:
        if room.height < 6:
            return
        ridge_y = room.y + room.height // 2
        for x in range(room.x + 1, room.x + room.width - 1):
            if tiles[ridge_y][x] == 0:
                room_kinds[ridge_y][x] = ROOM_KIND_VISTA
                if x not in {room.x + 2, room.x + room.width - 3}:
                    tiles[ridge_y][x] = 1
        for y in range(ridge_y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] == 0:
                    room_kinds[y][x] = ROOM_KIND_VISTA
                    stair_mask[y][x] = 0

    def _carve_crusher_passage(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6:
            return
        left = room.x + 1
        right = room.x + room.width - 2
        for y in range(room.y + 1, room.y + room.height - 1):
            tiles[y][left] = 1
            tiles[y][right] = 1
        for y in range(room.y + room.height // 2 - 1, room.y + room.height // 2 + 1):
            if room.y + 1 <= y < room.y + room.height - 1:
                tiles[y][left] = 0
                tiles[y][right] = 0

    def _carve_raised_platform_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room: Room,
        sector_types: list[list[int]],
        room_kinds: list[list[int]],
    ) -> None:
        if room.width < 6 or room.height < 6:
            return
        cx, cy = room.center
        for y in range(cy - 1, cy + 2):
            for x in range(cx - 1, cx + 2):
                if tiles[y][x] == 0:
                    floor_heights[y][x] = room.floor_height
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_BRIDGE)
        for x, y in ((cx - 2, cy), (cx + 2, cy), (cx, cy - 2), (cx, cy + 2)):
            if room.x < x < room.x + room.width - 1 and room.y < y < room.y + room.height - 1 and tiles[y][x] == 0:
                stair_mask[y][x] = 0

    def _carve_acid_ring_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 7 or room.height < 7:
            return
        inner_margin = 2
        cx, cy = room.center
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0:
                    continue
                in_center = (
                    room.x + inner_margin <= x <= room.x + room.width - 1 - inner_margin
                    and room.y + inner_margin <= y <= room.y + room.height - 1 - inner_margin
                )
                on_cross = x == cx or y == cy
                if in_center and not on_cross:
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_ACID)
                    stair_mask[y][x] = 0
                    floor_heights[y][x] = room.floor_height
                elif on_cross:
                    self._mark_sector(x, y, sector_types, room_kinds, SECTOR_BRIDGE)
                    stair_mask[y][x] = 0

    def _carve_toxic_canals_room(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 8 or room.height < 7:
            return
        lane_positions = [room.x + 2, room.x + room.width - 3]
        if room.width >= 10:
            lane_positions.append(room.x + room.width // 2)
        for lane_x in lane_positions:
            for y in range(room.y + 1, room.y + room.height - 1):
                if tiles[y][lane_x] != 0:
                    continue
                safe_gap = (y - room.y) % 4 == 2
                if safe_gap:
                    self._mark_sector(lane_x, y, sector_types, room_kinds, SECTOR_BRIDGE)
                else:
                    self._mark_sector(lane_x, y, sector_types, room_kinds, SECTOR_ACID)
                stair_mask[y][lane_x] = 0
                floor_heights[y][lane_x] = room.floor_height

    def _carve_grand_chamber(
        self,
        tiles: list[list[int]],
        ceiling_heights: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 7 or room.height < 7:
            return
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0:
                    continue
                if x in {room.x + 1, room.x + room.width - 2} or y in {room.y + 1, room.y + room.height - 2}:
                    ceiling_heights[y][x] = max(ceiling_heights[y][x], room.ceiling_height + 1)
                else:
                    ceiling_heights[y][x] = max(ceiling_heights[y][x], room.ceiling_height)

    def _add_side_connections(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        ceiling_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        connections: list[CorridorConnection],
        room_stages: tuple[int, ...],
    ) -> None:
        if len(rooms) < 4:
            return

        candidate_pairs: list[tuple[int, float, int, int]] = []
        for index, room in enumerate(rooms[:-2]):
            for other_index in range(index + 2, len(rooms)):
                if room_stages[index] != room_stages[other_index]:
                    continue
                other = rooms[other_index]
                ax, ay = room.center
                bx, by = other.center
                distance = abs(ax - bx) + abs(ay - by)
                candidate_pairs.append((distance, self.rng.random(), index, other_index))

        candidate_pairs.sort(key=lambda item: (item[0], item[1]))
        stage_link_counts = [0, 0, 0, 0]
        for _, _, room_a_index, room_b_index in candidate_pairs:
            stage_index = room_stages[room_a_index]
            if stage_link_counts[stage_index] >= settings.MAX_SIDE_CONNECTIONS_PER_STAGE:
                continue
            keep_probability = 0.86 if stage_link_counts[stage_index] == 0 else 0.62
            if self.rng.random() >= keep_probability:
                continue
            path = self._connect_rooms(
                tiles,
                floor_heights,
                ceiling_heights,
                stair_mask,
                room_kinds,
                sector_types,
                rooms[room_a_index],
                rooms[room_b_index],
                widen_chance=0.0,
            )
            connections.append(
                CorridorConnection(
                    index=len(connections),
                    room_a_index=room_a_index,
                    room_b_index=room_b_index,
                    path=path,
                    is_main_path=False,
                )
            )
            stage_link_counts[stage_index] += 1

    def _place_locked_doors(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        rooms: list[Room],
        connections: list[CorridorConnection],
        spawn: tuple[float, float],
        progression: ProgressionLayout,
    ) -> list[DoorSpawn] | None:
        door_spawns: list[DoorSpawn] = []
        for gate in progression.gate_plans:
            connection = connections[gate.connection_index]
            if connection.door_candidate is None:
                connection.door_candidate = self._find_door_candidate(tiles, stair_mask, rooms, connection, spawn)
            if connection.door_candidate is None:
                return None
            door_x, door_y, orientation = connection.door_candidate
            door_world_pos = (door_x + 0.5, door_y + 0.5)
            if any(
                math.dist(door_world_pos, (door.grid_x + 0.5, door.grid_y + 0.5)) < settings.DOOR_MIN_SPACING
                for door in door_spawns
            ):
                return None
            door_spawns.append(
                DoorSpawn(
                    door_id=f"door-{self.seed}-{len(door_spawns):03d}",
                    grid_x=door_x,
                    grid_y=door_y,
                    orientation=orientation,
                    door_type=locked_door_type_for_key(gate.key_type),
                )
            )
        return door_spawns

    def _place_keys(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        connections: list[CorridorConnection],
        progression: ProgressionLayout,
    ) -> list[KeySpawn] | None:
        key_spawns: list[KeySpawn] = []
        occupied_positions = [spawn]
        all_gate_positions = tuple(
            (
                connections[planned_gate.connection_index].door_candidate[0] + 0.5,
                connections[planned_gate.connection_index].door_candidate[1] + 0.5,
            )
            for planned_gate in progression.gate_plans
            if connections[planned_gate.connection_index].door_candidate is not None
        )

        for gate_index, gate in enumerate(progression.gate_plans):
            connection = connections[gate.connection_index]
            gate_door_position = (
                connection.door_candidate[0] + 0.5,
                connection.door_candidate[1] + 0.5,
            ) if connection.door_candidate is not None else None
            blocked_doors = {
                (connections[later_gate.connection_index].door_candidate[0], connections[later_gate.connection_index].door_candidate[1])
                for later_gate in progression.gate_plans[gate_index:]
                if connections[later_gate.connection_index].door_candidate is not None
            }
            reachable_before_door = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                blocked_doors,
            )

            key_position = None
            eligible_room_indices = self._eligible_key_rooms_for_gate(
                rooms,
                progression,
                gate,
                reachable_before_door,
                connection,
                all_gate_positions,
            )
            for key_room_index in eligible_room_indices:
                room_door_positions = [
                    (linked_connection.door_candidate[0] + 0.5, linked_connection.door_candidate[1] + 0.5)
                    for linked_connection in connections
                    if linked_connection.door_candidate is not None
                    and (
                        linked_connection.room_a_index == key_room_index
                        or linked_connection.room_b_index == key_room_index
                    )
                ]
                if gate_door_position is not None:
                    room_door_positions.append(gate_door_position)
                repel_positions = [
                    position
                    for position in all_gate_positions
                    if position not in room_door_positions
                ]
                key_position = self._choose_key_position(
                    rooms[key_room_index],
                    tiles,
                    stair_mask,
                    sector_types,
                    spawn,
                    occupied_positions,
                    avoid_positions=room_door_positions,
                    repel_positions=repel_positions,
                    reachable_tiles=reachable_before_door,
                    hidden_bias=True,
                    far_from_position=gate_door_position,
                )
                if key_position is not None:
                    break
            if key_position is None:
                return None
            key_spawns.append(
                KeySpawn(
                    key_id=f"key-{self.seed}-{gate.key_type}",
                    key_type=gate.key_type,
                    x=key_position[0],
                    y=key_position[1],
                )
            )
            occupied_positions.append(key_position)
        return key_spawns

    def _eligible_key_rooms_for_gate(
        self,
        rooms: list[Room],
        progression: ProgressionLayout,
        gate: ProgressionGatePlan,
        reachable_tiles: set[tuple[int, int]],
        connection: CorridorConnection,
        all_gate_positions: tuple[tuple[float, float], ...],
    ) -> list[int]:
        stage_room_indices = set(progression.stage_rooms[gate.stage_index])
        reachable_room_indices = {
            room_index
            for room_index in stage_room_indices
            if any(rooms[room_index].contains_tile(tile_x, tile_y) for tile_x, tile_y in reachable_tiles)
        }
        return self._ordered_key_rooms(rooms, reachable_room_indices, connection, all_gate_positions)

    def _place_optional_doors(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        rooms: list[Room],
        connections: list[CorridorConnection],
        spawn: tuple[float, float],
        progression: ProgressionLayout,
        locked_doors: list[DoorSpawn],
    ) -> list[DoorSpawn]:
        locked_connection_indices = {gate.connection_index for gate in progression.gate_plans}
        normal_doors: list[DoorSpawn] = []
        for connection in connections:
            if connection.index in locked_connection_indices:
                continue
            if connection.is_main_path and connection.edge_kind != EDGE_SHORTCUT:
                continue
            connection.door_candidate = self._find_door_candidate(tiles, stair_mask, rooms, connection, spawn)
            if connection.door_candidate is None:
                if connection.edge_kind == EDGE_SHORTCUT:
                    return []
                continue
            door_x, door_y, orientation = connection.door_candidate
            door_world_pos = (door_x + 0.5, door_y + 0.5)
            if any(
                math.dist(door_world_pos, (door.grid_x + 0.5, door.grid_y + 0.5)) < settings.DOOR_MIN_SPACING
                for door in [*locked_doors, *normal_doors]
            ):
                if connection.edge_kind == EDGE_SHORTCUT:
                    return []
                continue
            normal_doors.append(
                DoorSpawn(
                    door_id=f"door-{self.seed}-{len(locked_doors) + len(normal_doors):03d}",
                    grid_x=door_x,
                    grid_y=door_y,
                    orientation=orientation,
                    door_type="normal",
                    required_trigger_id=connection.trigger_source if connection.edge_kind == EDGE_SHORTCUT else None,
                )
            )
        return normal_doors

    def _validate_progression_layout(
        self,
        tiles: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        progression: ProgressionLayout,
        door_spawns: list[DoorSpawn],
        key_spawns: list[KeySpawn],
        exit_spawn: ExitSpawn,
    ) -> bool:
        locked_doors = [door for door in door_spawns if door.door_type in {locked_door_type_for_key(key_type) for key_type in KEY_TYPES}]
        if len(locked_doors) != len(KEY_TYPES) or len(key_spawns) != len(KEY_TYPES):
            return False

        door_by_key = {door.door_type.split("_", 1)[0]: door for door in locked_doors}
        key_by_type = {key.key_type: key for key in key_spawns}
        if set(door_by_key) != set(KEY_TYPES) or set(key_by_type) != set(KEY_TYPES):
            return False
        if exit_spawn.required_door_id != locked_doors[-1].door_id:
            return False

        for gate in progression.gate_plans:
            door = door_by_key[gate.key_type]
            if self._door_orientation_at(tiles, door.grid_x, door.grid_y) != door.orientation:
                return False

            blocked_with_only_gate_closed = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                {(door.grid_x, door.grid_y), *self._closed_positions_for_state(door_spawns, tuple(), tuple())},
            )
            if self._reachable_room_indices(rooms, blocked_with_only_gate_closed) & set(gate.blocked_room_indices):
                return False

        for gate_index, gate in enumerate(progression.gate_plans):
            unlocked_keys_before = KEY_TYPES[:gate_index]
            unlocked_triggers_before = tuple(f"pickup:{key_type}" for key_type in unlocked_keys_before)
            closed_now = self._closed_positions_for_state(door_spawns, unlocked_keys_before, unlocked_triggers_before)
            reachable_before = self._reachable_tiles_with_closed_positions(tiles, spawn, closed_now)
            key_tile = (int(key_by_type[gate.key_type].x), int(key_by_type[gate.key_type].y))
            if key_tile not in reachable_before:
                return False
            if self._reachable_room_indices(rooms, reachable_before) & set(gate.blocked_room_indices):
                return False

            unlocked_keys_after = KEY_TYPES[: gate_index + 1]
            unlocked_triggers_after = tuple(f"pickup:{key_type}" for key_type in unlocked_keys_after)
            reachable_after = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                self._closed_positions_for_state(door_spawns, unlocked_keys_after, unlocked_triggers_after),
            )
            next_stage_index = gate.stage_index + 1
            if next_stage_index >= len(progression.stage_rooms):
                return False
            if not (self._reachable_room_indices(rooms, reachable_after) & set(progression.stage_rooms[next_stage_index])):
                return False

        exit_tile = (int(exit_spawn.x), int(exit_spawn.y))
        reachable_before_final = self._reachable_tiles_with_closed_positions(
            tiles,
            spawn,
            self._closed_positions_for_state(
                door_spawns,
                KEY_TYPES[:-1],
                tuple(f"pickup:{key_type}" for key_type in KEY_TYPES[:-1]),
            ),
        )
        if exit_tile in reachable_before_final:
            return False
        reachable_all_open = self._reachable_tiles_with_closed_positions(tiles, spawn, set())
        if exit_tile not in reachable_all_open:
            return False
        return True

    def _reachable_room_indices(
        self,
        rooms: list[Room],
        reachable_tiles: set[tuple[int, int]],
    ) -> set[int]:
        reachable_rooms: set[int] = set()
        for room_index, room in enumerate(rooms):
            if any(room.contains_tile(grid_x, grid_y) for grid_x, grid_y in reachable_tiles):
                reachable_rooms.add(room_index)
        return reachable_rooms

    def _build_boss_guard_plan(
        self,
        rooms: list[Room],
        connections: list[CorridorConnection],
        final_connection: CorridorConnection | None,
        final_required_door_id: str | None,
        final_required_door_tile: tuple[int, int] | None,
    ) -> BossGuardPlan | None:
        if (
            final_connection is None
            or final_required_door_id is None
            or final_required_door_tile is None
            or len(rooms) < 5
        ):
            return None
        chance = self.difficulty.boss_guard_probability
        if len(rooms) >= 8:
            chance = min(1.0, chance + 0.08)
        if self.rng.random() > chance:
            return None

        reachable_before_final = self._reachable_rooms(
            len(rooms),
            connections,
            0,
            skip_connection_index=final_connection.index,
        )
        candidate_rooms = [room_index for room_index in reachable_before_final if room_index != 0]
        if final_connection.room_a_index in candidate_rooms:
            candidate_rooms.sort(key=lambda idx: (idx != final_connection.room_a_index, abs(idx - final_connection.room_a_index)))
        if not candidate_rooms:
            return None
        return BossGuardPlan(
            guarded_door_id=final_required_door_id,
            guarded_door_tile=final_required_door_tile,
            anchor_position=(final_required_door_tile[0] + 0.5, final_required_door_tile[1] + 0.5),
            candidate_room_indices=tuple(candidate_rooms),
        )

    def _build_locked_progression_chain(
        self,
        tiles: list[list[int]],
        rooms: list[Room],
        connections: list[CorridorConnection],
        bridge_indices: set[int],
        spawn: tuple[float, float],
    ) -> list[tuple[str, CorridorConnection, set[int]]]:
        main_bridge_connections = [
            connection
            for connection in connections
            if connection.is_main_path and connection.index in bridge_indices and connection.door_candidate is not None
        ]
        if not main_bridge_connections:
            return []

        main_bridge_connections.sort(key=lambda connection: connection.room_b_index)
        max_length = min(len(KEY_TYPES), len(main_bridge_connections))
        valid_chains: list[list[CorridorConnection]] = []

        def room_segment_valid(chain: list[CorridorConnection]) -> bool:
            prev_boundary = 1
            for index, connection in enumerate(chain):
                segment_start = prev_boundary
                segment_end = connection.room_b_index - 1
                if index == 0:
                    segment_start = 1
                if segment_end < segment_start:
                    return False
                segment_room_count = segment_end - segment_start + 1
                if index == 0 and segment_room_count < 2:
                    return False
                if index > 0:
                    previous = chain[index - 1]
                    previous_pos = (previous.door_candidate[0] + 0.5, previous.door_candidate[1] + 0.5)
                    current_pos = (connection.door_candidate[0] + 0.5, connection.door_candidate[1] + 0.5)
                    if math.dist(previous_pos, current_pos) < settings.DOOR_MIN_SPACING:
                        return False
                reachable = self._reachable_tiles_for_progression(tiles, spawn, chain, index)
                segment_rooms = set(range(segment_start, segment_end + 1))
                if not self._segment_has_reachable_room(rooms, segment_rooms, reachable):
                    return False
                prev_boundary = connection.room_b_index
            return True

        def collect_valid_chains(start_index: int, current: list[CorridorConnection]) -> None:
            if current:
                valid_chains.append(current[:])
            if len(current) >= max_length:
                return
            for candidate_index in range(start_index, len(main_bridge_connections)):
                connection = main_bridge_connections[candidate_index]
                if not current and connection.room_b_index < 2:
                    continue
                trial = current + [connection]
                if not room_segment_valid(trial):
                    continue
                collect_valid_chains(candidate_index + 1, trial)

        collect_valid_chains(0, [])
        if not valid_chains:
            return []

        available_lengths = sorted({len(chain) for chain in valid_chains})
        target_length = self.rng.choice(available_lengths)
        length_matches = [chain for chain in valid_chains if len(chain) == target_length]
        selected_chain = self.rng.choice(length_matches)

        progression: list[tuple[str, CorridorConnection, set[int]]] = []
        prev_boundary = 1
        for key_type, connection in zip(KEY_TYPES, selected_chain):
            segment_start = prev_boundary
            segment_end = connection.room_b_index - 1
            key_room_candidates = set(range(segment_start, segment_end + 1))
            if not key_room_candidates:
                break
            progression.append((key_type, connection, key_room_candidates))
            prev_boundary = connection.room_b_index

        return progression

    def _reachable_tiles_with_doors(
        self,
        tiles: list[list[int]],
        spawn: tuple[float, float],
        opened_connections: list[CorridorConnection],
        closed_connection: CorridorConnection | None,
    ) -> set[tuple[int, int]]:
        closed_doors = set()
        if closed_connection is not None and closed_connection.door_candidate is not None:
            closed_doors.add((closed_connection.door_candidate[0], closed_connection.door_candidate[1]))
        return self._reachable_tiles_with_closed_positions(tiles, spawn, closed_doors)

    def _reachable_tiles_for_progression(
        self,
        tiles: list[list[int]],
        spawn: tuple[float, float],
        progression_chain,
        current_index: int,
    ) -> set[tuple[int, int]]:
        closed_positions: set[tuple[int, int]] = set()
        for entry in progression_chain[current_index:]:
            connection = entry[1] if isinstance(entry, tuple) else entry
            if connection.door_candidate is None:
                continue
            closed_positions.add((connection.door_candidate[0], connection.door_candidate[1]))
        return self._reachable_tiles_with_closed_positions(tiles, spawn, closed_positions)

    def _segment_has_reachable_room(
        self,
        rooms: list[Room],
        room_indices: set[int],
        reachable_tiles: set[tuple[int, int]],
    ) -> bool:
        for room_index in room_indices:
            room = rooms[room_index]
            for grid_x, grid_y in reachable_tiles:
                if room.contains_tile(grid_x, grid_y):
                    return True
        return False

    def _generate_exit_spawn(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        progression_suffix_rooms: set[int] | None,
        required_door_id: str | None,
        required_door_tile: tuple[int, int] | None,
        extra_closed_positions: set[tuple[int, int]] | None = None,
    ) -> ExitSpawn | None:
        if not rooms:
            return None
        reachable_without_final: set[tuple[int, int]] | None = None
        reachable_with_final: set[tuple[int, int]] | None = None
        final_door_world_pos: tuple[float, float] | None = None
        extra_closed_positions = extra_closed_positions or set()
        if required_door_tile is not None:
            reachable_without_final = self._reachable_tiles_with_closed_positions(tiles, spawn, {required_door_tile, *extra_closed_positions})
            reachable_with_final = self._reachable_tiles_with_closed_positions(tiles, spawn, set())
            final_door_world_pos = (required_door_tile[0] + 0.5, required_door_tile[1] + 0.5)
        candidate_room_indices = progression_suffix_rooms if progression_suffix_rooms else {len(rooms) - 1}
        ordered_rooms = sorted(
            candidate_room_indices,
            key=lambda room_index: math.dist((rooms[room_index].center[0] + 0.5, rooms[room_index].center[1] + 0.5), spawn),
            reverse=True,
        )
        for room_index in ordered_rooms:
            room = rooms[room_index]
            candidates = self._room_floor_candidates(
                room,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                min_spacing=1.65,
                allowed_sectors={SECTOR_SAFE, SECTOR_BRIDGE},
            )
            if not candidates:
                candidates = self._fallback_room_positions(
                    room,
                    tiles,
                    stair_mask,
                    sector_types,
                    spawn,
                    occupied_positions,
                    allowed_sectors={SECTOR_SAFE, SECTOR_BRIDGE},
                )
            if not candidates:
                continue
            candidates.sort(key=lambda pos: math.dist(pos, spawn), reverse=True)
            for exit_pos in candidates:
                exit_tile = (int(exit_pos[0]), int(exit_pos[1]))
                if reachable_without_final is not None:
                    if exit_tile in reachable_without_final:
                        continue
                    if reachable_with_final is not None and exit_tile not in reachable_with_final:
                        continue
                if final_door_world_pos is not None and math.dist(exit_pos, final_door_world_pos) < 2.4:
                    continue
                return ExitSpawn(
                    exit_id=f"exit-{self.seed}",
                    x=exit_pos[0],
                    y=exit_pos[1],
                    required_door_id=required_door_id,
                )
        return None

    def _reachable_tiles_with_closed_positions(
        self,
        tiles: list[list[int]],
        spawn: tuple[float, float],
        closed_positions: set[tuple[int, int]],
    ) -> set[tuple[int, int]]:
        queue = [(int(spawn[0]), int(spawn[1]))]
        visited = {queue[0]}
        while queue:
            grid_x, grid_y = queue.pop(0)
            for next_x, next_y in ((grid_x + 1, grid_y), (grid_x - 1, grid_y), (grid_x, grid_y + 1), (grid_x, grid_y - 1)):
                if (next_x, next_y) in visited:
                    continue
                if next_x < 0 or next_y < 0 or next_x >= self.width or next_y >= self.height:
                    continue
                if tiles[next_y][next_x] != 0:
                    continue
                if (next_x, next_y) in closed_positions:
                    continue
                visited.add((next_x, next_y))
                queue.append((next_x, next_y))
        return visited

    def _find_door_candidate(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        rooms: list[Room],
        connection: CorridorConnection,
        spawn: tuple[float, float],
    ) -> tuple[int, int, str] | None:
        room_a = rooms[connection.room_a_index]
        room_b = rooms[connection.room_b_index]
        for room_padding in (1, 0):
            candidates: list[tuple[int, int, str]] = []
            seen: set[tuple[int, int]] = set()

            for grid_x, grid_y in connection.path:
                if (grid_x, grid_y) in seen:
                    continue
                seen.add((grid_x, grid_y))
                if tiles[grid_y][grid_x] != 0:
                    continue
                if stair_mask[grid_y][grid_x] != 0:
                    continue
                if room_a.contains_tile(grid_x, grid_y, padding=room_padding) or room_b.contains_tile(grid_x, grid_y, padding=room_padding):
                    continue
                if math.dist((grid_x + 0.5, grid_y + 0.5), spawn) < settings.DOOR_MIN_PLAYER_DISTANCE:
                    continue
                orientation = self._door_orientation_at(tiles, grid_x, grid_y)
                if orientation is None:
                    continue
                candidates.append((grid_x, grid_y, orientation))

            if candidates:
                return candidates[len(candidates) // 2]
        return None

    def _is_connection_door_candidate_valid(
        self,
        tiles: list[list[int]],
        rooms: list[Room],
        room_a_index: int,
        room_b_index: int,
        path: list[tuple[int, int]],
        candidate: tuple[int, int, str],
    ) -> bool:
        grid_x, grid_y, orientation = candidate
        if grid_x < 0 or grid_y < 0 or grid_x >= self.width or grid_y >= self.height:
            return False
        if tiles[grid_y][grid_x] != 0:
            return False
        room_a = rooms[room_a_index]
        room_b = rooms[room_b_index]
        if room_a.contains_tile(grid_x, grid_y, padding=0) or room_b.contains_tile(grid_x, grid_y, padding=0):
            return False
        resolved_orientation = self._door_orientation_at(tiles, grid_x, grid_y)
        return resolved_orientation is not None and resolved_orientation == orientation

    def _door_orientation_at(self, tiles: list[list[int]], grid_x: int, grid_y: int) -> str | None:
        open_left = tiles[grid_y][grid_x - 1] == 0
        open_right = tiles[grid_y][grid_x + 1] == 0
        open_up = tiles[grid_y - 1][grid_x] == 0
        open_down = tiles[grid_y + 1][grid_x] == 0

        # A valid door tile must be a real 1-tile choke point, not a side opening or a wide area.
        if open_left and open_right and not open_up and not open_down:
            return "vertical"
        if open_up and open_down and not open_left and not open_right:
            return "horizontal"
        return None

    def _find_bridge_indices(self, room_count: int, connections: list[CorridorConnection]) -> set[int]:
        adjacency: list[list[tuple[int, int]]] = [[] for _ in range(room_count)]
        for index, connection in enumerate(connections):
            adjacency[connection.room_a_index].append((connection.room_b_index, index))
            adjacency[connection.room_b_index].append((connection.room_a_index, index))

        time = 0
        disc = [-1] * room_count
        low = [-1] * room_count
        bridges: set[int] = set()

        def dfs(node: int, parent_edge: int) -> None:
            nonlocal time
            disc[node] = time
            low[node] = time
            time += 1
            for neighbor, edge_index in adjacency[node]:
                if edge_index == parent_edge:
                    continue
                if disc[neighbor] == -1:
                    dfs(neighbor, edge_index)
                    low[node] = min(low[node], low[neighbor])
                    if low[neighbor] > disc[node]:
                        bridges.add(edge_index)
                else:
                    low[node] = min(low[node], disc[neighbor])

        dfs(0, -1)
        return bridges

    def _reachable_rooms(
        self,
        room_count: int,
        connections: list[CorridorConnection],
        start_room: int,
        skip_connection_index: int | None = None,
    ) -> set[int]:
        adjacency: list[list[tuple[int, int]]] = [[] for _ in range(room_count)]
        for index, connection in enumerate(connections):
            if index == skip_connection_index:
                continue
            adjacency[connection.room_a_index].append((connection.room_b_index, index))
            adjacency[connection.room_b_index].append((connection.room_a_index, index))

        visited = {start_room}
        queue = [start_room]
        while queue:
            room_index = queue.pop(0)
            for neighbor, _ in adjacency[room_index]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        return visited

    def _ordered_key_rooms(
        self,
        rooms: list[Room],
        room_candidates: set[int],
        connection: CorridorConnection,
        all_gate_positions: tuple[tuple[float, float], ...],
    ) -> list[int]:
        door_world_pos = (
            connection.door_candidate[0] + 0.5,
            connection.door_candidate[1] + 0.5,
        )
        return sorted(
            room_candidates,
            key=lambda room_index: (
                min(
                    (
                        math.dist(
                            (rooms[room_index].center[0] + 0.5, rooms[room_index].center[1] + 0.5),
                            gate_pos,
                        )
                        for gate_pos in all_gate_positions
                    ),
                    default=math.dist((rooms[room_index].center[0] + 0.5, rooms[room_index].center[1] + 0.5), door_world_pos),
                ),
                math.dist((rooms[room_index].center[0] + 0.5, rooms[room_index].center[1] + 0.5), door_world_pos),
                self.rng.random(),
            ),
            reverse=True,
        )

    def _choose_key_position(
        self,
        room: Room,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        avoid_positions: list[tuple[float, float]] | None = None,
        repel_positions: list[tuple[float, float]] | None = None,
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
        hidden_bias: bool = False,
        far_from_position: tuple[float, float] | None = None,
    ) -> tuple[float, float] | None:
        candidates = self._room_floor_candidates(
            room,
            tiles,
            stair_mask,
            sector_types,
            spawn,
            occupied_positions,
            min_spacing=1.45,
            reachable_tiles=reachable_tiles,
            forbidden_tiles=forbidden_tiles,
            allowed_sectors={SECTOR_SAFE, SECTOR_BRIDGE},
        )
        if not candidates:
            candidates = self._fallback_room_positions(
                room,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                reachable_tiles=reachable_tiles,
                forbidden_tiles=forbidden_tiles,
                allowed_sectors={SECTOR_SAFE, SECTOR_BRIDGE},
            )
        if not candidates:
            return None
        avoid_positions = avoid_positions or []
        repel_positions = repel_positions or []
        candidates.sort(
            key=lambda pos: (
                min((math.dist(pos, other) for other in repel_positions), default=0.0),
                math.dist(pos, far_from_position) if far_from_position is not None else 0.0,
                self._distance_from_room_entry_line(pos, room, far_from_position),
                self._hidden_position_score(pos, room, tiles) if hidden_bias else 0.0,
                min((math.dist(pos, other) for other in avoid_positions), default=0.0),
                math.dist(pos, spawn),
                self.rng.random(),
            ),
            reverse=True,
        )
        return candidates[0]

    def _distance_from_room_entry_line(
        self,
        pos: tuple[float, float],
        room: Room,
        gate_pos: tuple[float, float] | None,
    ) -> float:
        if gate_pos is None:
            return 0.0
        ax, ay = gate_pos
        bx, by = room.center[0] + 0.5, room.center[1] + 0.5
        px, py = pos
        abx = bx - ax
        aby = by - ay
        denom = abx * abx + aby * aby
        if denom <= 0.001:
            return 0.0
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
        proj_x = ax + abx * t
        proj_y = ay + aby * t
        return math.dist((px, py), (proj_x, proj_y))

    def _hidden_position_score(
        self,
        pos: tuple[float, float],
        room: Room,
        tiles: list[list[int]],
    ) -> float:
        tile_x = int(pos[0])
        tile_y = int(pos[1])
        wall_neighbors = 0
        for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor_x = tile_x + offset_x
            neighbor_y = tile_y + offset_y
            if not (0 <= neighbor_x < self.width and 0 <= neighbor_y < self.height):
                wall_neighbors += 1
                continue
            if tiles[neighbor_y][neighbor_x] == 1:
                wall_neighbors += 1
        corner_bias = min(
            math.dist(pos, (room.x + 1.5, room.y + 1.5)),
            math.dist(pos, (room.x + room.width - 1.5, room.y + 1.5)),
            math.dist(pos, (room.x + 1.5, room.y + room.height - 1.5)),
            math.dist(pos, (room.x + room.width - 1.5, room.y + room.height - 1.5)),
        )
        return wall_neighbors * 3.0 - corner_bias

    def _generate_loot_spawns(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        reserved_positions: list[tuple[float, float]],
    ) -> list[LootSpawn]:
        loot_spawns: list[LootSpawn] = []
        if not rooms:
            return loot_spawns

        occupied_positions: list[tuple[float, float]] = [spawn, *reserved_positions]
        next_id = 0

        for room_index, room in enumerate(rooms):
            candidates = self._room_floor_candidates(
                room,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                allowed_sectors={SECTOR_SAFE, SECTOR_BRIDGE},
            )
            if not candidates:
                continue

            count_min, count_max = ROOM_LOOT_COUNTS.get(room.kind, (1, 2))
            scaled_min = max(1, int(round(count_min * self.difficulty.pickup_density_scale)))
            scaled_max = max(scaled_min, int(round(count_max * self.difficulty.pickup_density_scale + self.difficulty.safe_room_bias - 1.0)))
            if room_index <= 2 and self.difficulty_id == "easy":
                scaled_max = max(scaled_max, settings.EARLY_STAGE_SOFT_CAP + 1)
            spawn_count = min(len(candidates), self.rng.randint(scaled_min, scaled_max))
            loot_table = ROOM_LOOT_TABLES.get(room.kind, ROOM_LOOT_TABLES["cross"])

            placed = 0
            for x, y in candidates:
                if any(math.dist((x, y), other) < settings.LOOT_MIN_SPACING for other in occupied_positions):
                    continue
                entry = self._weighted_loot_entry(loot_table)
                loot_kind = self._adjust_loot_kind_for_difficulty(entry.kind)
                amount = (
                    resolve_pickup_amount(loot_kind)
                    if loot_kind != entry.kind
                    else resolve_pickup_amount(loot_kind, entry.amount)
                )
                pickup_id = f"loot-{self.seed}-{room_index:02d}-{next_id:03d}"
                loot_spawns.append(LootSpawn(pickup_id, x, y, loot_kind, amount))
                occupied_positions.append((x, y))
                next_id += 1
                placed += 1
                if placed >= spawn_count:
                    break

        return loot_spawns

    def _adjust_loot_kind_for_difficulty(self, loot_kind: str) -> str:
        if self.difficulty_id == "easy":
            upgrades = {
                "stimpack": "medkit",
            }
            return upgrades.get(loot_kind, loot_kind)
        if self.difficulty_id == "hard":
            downgrades = {
                "medkit": "stimpack",
                "green_armor": "armor_bonus",
            }
            return downgrades.get(loot_kind, loot_kind)
        return loot_kind

    def _generate_enemy_spawns(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        reserved_positions: list[tuple[float, float]],
        boss_guard_plan: BossGuardPlan | None,
    ) -> tuple[list[EnemySpawn], str | None]:
        enemy_spawns: list[EnemySpawn] = []
        if len(rooms) <= 1:
            return enemy_spawns, None

        occupied_positions = [spawn, *reserved_positions]
        next_index = 0
        guard_enemy_id: str | None = None
        placed_per_room = {room_index: 0 for room_index in range(len(rooms))}

        if boss_guard_plan is not None:
            boss_position = self._choose_boss_position(
                tiles,
                stair_mask,
                sector_types,
                rooms,
                spawn,
                occupied_positions,
                boss_guard_plan,
            )
            if boss_position is not None:
                guard_enemy_id = f"enemy-{self.seed}-boss-{next_index:03d}"
                enemy_spawns.append(
                    EnemySpawn(
                        enemy_id=guard_enemy_id,
                        enemy_type="warden",
                        x=boss_position[0],
                        y=boss_position[1],
                        room_index=int(boss_position[2]),
                        difficulty_tier=3,
                    )
                )
                occupied_positions.append((boss_position[0], boss_position[1]))
                placed_per_room[int(boss_position[2])] += 1
                next_index += 1

        room_targets: dict[int, int] = {}
        for room_index, room in enumerate(rooms):
            if room_index == 0:
                continue
            room_targets[room_index] = self._enemy_room_spawn_target(
                room,
                room_index,
                len(rooms),
                boss_guard_plan,
                guard_enemy_id,
            )

        for room_index, room in enumerate(rooms):
            if room_index == 0:
                continue
            spawn_target = room_targets.get(room_index, 0)
            if spawn_target <= 0:
                continue
            guaranteed = 1
            if room.kind == "arena" and spawn_target >= 4:
                guaranteed = 2
            if room.kind == "shrine":
                guaranteed = 1
            guaranteed = min(spawn_target, guaranteed)

            candidates = self._enemy_candidates_for_room(
                room,
                room_index,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                boss_guard_plan,
                guard_enemy_id,
            )
            if not candidates:
                continue

            candidates.sort(
                key=lambda pos: self._enemy_candidate_score(
                    pos,
                    spawn,
                    occupied_positions,
                    room,
                    room_index,
                    len(rooms),
                    spawn_target,
                    placed_per_room[room_index],
                ),
                reverse=True,
            )
            placed_guaranteed = 0
            for x, y in candidates:
                if any(math.dist((x, y), other) < settings.ENEMY_MIN_SPACING for other in occupied_positions):
                    continue
                difficulty_tier = min(2, (room_index * 3) // max(1, len(rooms) - 1))
                enemy_type = self._choose_enemy_type(room, room_index, len(rooms), difficulty_tier)
                enemy_spawns.append(
                    EnemySpawn(
                        enemy_id=f"enemy-{self.seed}-{next_index:03d}",
                        enemy_type=enemy_type,
                        x=x,
                        y=y,
                        room_index=room_index,
                        difficulty_tier=difficulty_tier,
                    )
                )
                occupied_positions.append((x, y))
                placed_per_room[room_index] += 1
                next_index += 1
                placed_guaranteed += 1
                if placed_guaranteed >= guaranteed:
                    break

        remaining_budget = max(0, sum(room_targets.values()) - sum(placed_per_room.values()))
        while remaining_budget > 0:
            best_option: tuple[float, int, Room, tuple[float, float]] | None = None
            for room_index, room in enumerate(rooms):
                if room_index == 0:
                    continue
                spawn_target = room_targets.get(room_index, 0)
                if placed_per_room[room_index] >= spawn_target:
                    continue
                candidates = self._enemy_candidates_for_room(
                    room,
                    room_index,
                    tiles,
                    stair_mask,
                    sector_types,
                    spawn,
                    occupied_positions,
                    boss_guard_plan,
                    guard_enemy_id,
                )
                if not candidates:
                    continue
                best_candidate = max(
                    candidates,
                    key=lambda pos: self._enemy_candidate_score(
                        pos,
                        spawn,
                        occupied_positions,
                        room,
                        room_index,
                        len(rooms),
                        spawn_target,
                        placed_per_room[room_index],
                    ),
                )
                score = self._enemy_candidate_score(
                    best_candidate,
                    spawn,
                    occupied_positions,
                    room,
                    room_index,
                    len(rooms),
                    spawn_target,
                    placed_per_room[room_index],
                )
                if best_option is None or score > best_option[0]:
                    best_option = (score, room_index, room, best_candidate)

            if best_option is None:
                break

            _, room_index, room, (x, y) = best_option
            difficulty_tier = min(2, (room_index * 3) // max(1, len(rooms) - 1))
            enemy_type = self._choose_enemy_type(room, room_index, len(rooms), difficulty_tier)
            enemy_spawns.append(
                EnemySpawn(
                    enemy_id=f"enemy-{self.seed}-{next_index:03d}",
                    enemy_type=enemy_type,
                    x=x,
                    y=y,
                    room_index=room_index,
                    difficulty_tier=difficulty_tier,
                )
            )
            occupied_positions.append((x, y))
            placed_per_room[room_index] += 1
            next_index += 1
            remaining_budget -= 1

        return enemy_spawns, guard_enemy_id

    def _enemy_room_spawn_target(
        self,
        room: Room,
        room_index: int,
        room_count: int,
        boss_guard_plan: BossGuardPlan | None,
        guard_enemy_id: str | None,
    ) -> int:
        room_area = room.width * room.height
        difficulty_scale = self._room_difficulty_scale(room.kind, room_index, room_count)
        progress = room_index / max(1, room_count - 1)

        spawn_budget = room_area / max(13.5, 19.5 - difficulty_scale * 3.4)
        target = max(1, int(round(spawn_budget)))
        if room.kind in {"arena", "cross"}:
            target += 1
        if room.kind == "tech" and progress >= 0.35:
            target += 1
        if room_area >= 72:
            target += 1
        if room_area >= 84:
            target += 1
        if room_index >= room_count - 2:
            target += 1
        if room.kind == "shrine":
            target = max(1, target - 1)
        if room.spatial_archetype in {ARCHETYPE_TOXIC_PIT_ROOM, ARCHETYPE_BRIDGE_CROSSING, ARCHETYPE_ACID_RING, ARCHETYPE_TOXIC_CANALS}:
            target += 1
        if room.ceiling_height >= 3:
            target += 1
        if room.spatial_archetype == ARCHETYPE_CRUSHER_PASSAGE:
            target = max(1, target - 1)
        if guard_enemy_id is not None and boss_guard_plan is not None and room_index == boss_guard_plan.candidate_room_indices[0]:
            target = max(0, target - 1)
        max_target = {
            "arena": 6,
            "cross": 5,
            "tech": 5,
            "shrine": 3,
        }.get(room.kind, 4)
        target = max(0, int(round(target * self.difficulty.enemy_count_scale)))
        target += self.difficulty.enemy_room_cap_bonus
        if room_index <= 2 and self.difficulty_id == "easy":
            target = min(target, settings.EARLY_STAGE_SOFT_CAP)
        return max(0, min(target, max_target + self.difficulty.enemy_room_cap_bonus))

    def _enemy_candidates_for_room(
        self,
        room: Room,
        room_index: int,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        boss_guard_plan: BossGuardPlan | None,
        guard_enemy_id: str | None,
    ) -> list[tuple[float, float]]:
        if boss_guard_plan is not None and room_index in boss_guard_plan.candidate_room_indices and guard_enemy_id is not None:
            extra_spacing = 1.9
        else:
            extra_spacing = max(settings.ENEMY_MIN_SPACING, settings.LOOT_MIN_SPACING)

        candidates = self._room_floor_candidates(
            room,
            tiles,
            stair_mask,
            sector_types,
            spawn,
            occupied_positions,
            min_spacing=extra_spacing,
            allowed_sectors={SECTOR_SAFE},
        )
        if not candidates:
            candidates = self._fallback_room_positions(
                room,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                allowed_sectors={SECTOR_SAFE},
            )
        return candidates

    def _enemy_candidate_score(
        self,
        position: tuple[float, float],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        room: Room,
        room_index: int,
        room_count: int,
        room_target: int,
        room_placed: int,
    ) -> float:
        nearest_other = min((math.dist(position, other) for other in occupied_positions), default=settings.ENEMY_MIN_SPACING)
        distance_from_spawn = math.dist(position, spawn)
        progress = room_index / max(1, room_count - 1)
        room_fill_ratio = room_placed / max(1, room_target)
        room_kind_bonus = {
            "storage": 0.05,
            "tech": 0.18,
            "cross": 0.28,
            "arena": 0.42,
            "shrine": 0.12,
        }.get(room.kind, 0.0)
        distance_from_center = math.dist(position, (room.center[0] + 0.5, room.center[1] + 0.5))
        center_bias = 0.0
        if room.spatial_archetype in {ARCHETYPE_SPLIT_ARENA, ARCHETYPE_RAISED_PLATFORM, ARCHETYPE_GRAND_CHAMBER}:
            center_bias += max(0.0, 2.4 - distance_from_center) * 0.22
        if room.spatial_archetype in {ARCHETYPE_TOXIC_PIT_ROOM, ARCHETYPE_BRIDGE_CROSSING, ARCHETYPE_ACID_RING, ARCHETYPE_TOXIC_CANALS}:
            center_bias -= max(0.0, 2.2 - distance_from_center) * 0.28
        return (
            nearest_other * 1.85
            + distance_from_spawn * 0.26
            + progress * 1.1
            + (1.0 - room_fill_ratio) * 1.6
            + room_kind_bonus
            + center_bias
            + room.ceiling_height * 0.08
            + self.rng.random() * 0.22
        )

    def _room_difficulty_scale(self, room_kind: str, room_index: int, room_count: int) -> float:
        progress = room_index / max(1, room_count - 1)
        kind_bonus = {
            "start": 0.82,
            "storage": 0.9,
            "tech": 0.98,
            "cross": 1.02,
            "arena": 1.14,
            "shrine": 1.08,
        }.get(room_kind, 1.0)
        generator_pressure = self.difficulty.damage_pressure_bias * (0.92 + (self.runtime_pressure_bias - 1.0) * 0.35)
        return min(1.5, max(0.72, kind_bonus * (0.82 + progress * 0.52) * generator_pressure))

    def _choose_boss_position(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        boss_guard_plan: BossGuardPlan,
    ) -> tuple[float, float, int] | None:
        for room_index in boss_guard_plan.candidate_room_indices:
            room = rooms[room_index]
            candidates = self._room_floor_candidates(
                room,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                min_spacing=max(2.0, settings.ENEMY_MIN_SPACING + 0.8),
                allowed_sectors={SECTOR_SAFE},
            )
            if not candidates:
                candidates = self._fallback_room_positions(
                    room,
                    tiles,
                    stair_mask,
                    sector_types,
                    spawn,
                    occupied_positions,
                    allowed_sectors={SECTOR_SAFE},
                )
            if not candidates:
                continue
            candidates.sort(
                key=lambda pos: (
                    math.dist(pos, boss_guard_plan.anchor_position),
                    -math.dist(pos, spawn),
                )
            )
            for candidate in candidates:
                if math.dist(candidate, boss_guard_plan.anchor_position) < 2.0:
                    continue
                return (candidate[0], candidate[1], room_index)
        return None

    def _choose_enemy_type(
        self,
        room: Room,
        room_index: int,
        room_count: int,
        difficulty_tier: int,
    ) -> str:
        progress = room_index / max(1, room_count - 1)
        roll = self.rng.random()
        weighted_roll = roll / max(0.68, self.difficulty.damage_pressure_bias)
        campaign_level_index = self._campaign_field("level_index", 1)
        hazardous_room = room.spatial_archetype in {
            ARCHETYPE_TOXIC_PIT_ROOM,
            ARCHETYPE_BRIDGE_CROSSING,
            ARCHETYPE_ACID_RING,
            ARCHETYPE_TOXIC_CANALS,
        }
        high_ceiling_room = room.ceiling_height >= 3 or room.spatial_archetype in {
            ARCHETYPE_HIGH_CEILING_HALL,
            ARCHETYPE_OVERLOOK_VISTA,
            ARCHETYPE_GRAND_CHAMBER,
        }
        large_room = room.width * room.height >= 95
        cacodemon_room = high_ceiling_room and not hazardous_room and (
            large_room or room.kind in {"arena", "shrine", "tech", "cross"}
        )
        if progress < 0.24:
            if hazardous_room and weighted_roll < 0.42:
                return "grunt"
            return "charger" if weighted_roll < 0.34 else "grunt"
        if progress < 0.58:
            if (
                campaign_level_index >= 2
                and difficulty_tier >= 1
                and cacodemon_room
                and weighted_roll < 0.16
            ):
                return "cacodemon"
            if hazardous_room and weighted_roll < 0.52:
                return "heavy"
            if room.kind in {"arena", "tech", "cross"} and weighted_roll < 0.38:
                return "heavy"
            if difficulty_tier >= 1 and weighted_roll < 0.24:
                return "heavy"
            if weighted_roll < 0.46:
                return "charger"
            return "grunt"
        if (
            campaign_level_index >= 2
            and cacodemon_room
            and weighted_roll < (0.44 if campaign_level_index >= 4 else 0.3)
        ):
            return "cacodemon"
        if hazardous_room and weighted_roll < 0.68:
            return "heavy"
        if high_ceiling_room and weighted_roll < 0.54:
            return "heavy"
        if room.kind in {"arena", "shrine", "tech", "cross"} and weighted_roll < 0.6:
            return "heavy"
        if difficulty_tier >= 2 and weighted_roll < 0.46:
            return "heavy"
        if weighted_roll < 0.3:
            return "charger"
        return "grunt"

    def _encounter_template_for_room(
        self,
        role: str,
        room: Room,
    ) -> str:
        encounter_style_id = self._encounter_style_id()
        if role == ROOM_ROLE_FINAL_ROOM:
            return f"{encounter_style_id}_finale"
        if role == ROOM_ROLE_KEY_ROOM:
            if encounter_style_id == "holdout":
                return "key_holdout"
            if encounter_style_id == "hunter":
                return "key_hunter"
            if encounter_style_id == "pincer":
                return "key_pincer"
            return "key_standard"
        if role in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_PRESSURE_CORRIDOR}:
            if room.geometry_preset_id.endswith("crossfire"):
                return f"{encounter_style_id}_crossfire"
            if room.geometry_preset_id.endswith("flank"):
                return f"{encounter_style_id}_flank"
        if role == ROOM_ROLE_SWITCH_ROOM:
            return f"{encounter_style_id}_switch"
        if role in {ROOM_ROLE_RETURN_ROUTE, ROOM_ROLE_SHORTCUT_HALL}:
            return f"{encounter_style_id}_chase"
        return f"{encounter_style_id}_standard"

    def _encounter_template_definition(self, encounter_template_id: str) -> EncounterTemplateDefinition:
        return ENCOUNTER_TEMPLATE_DEFINITIONS.get(
            encounter_template_id,
            ENCOUNTER_TEMPLATE_DEFINITIONS["standard_standard"],
        )

    def _room_sightline_class(self, room: Room) -> str:
        if room.ceiling_height >= 4 or room.spatial_archetype in {ARCHETYPE_OVERLOOK_VISTA, ARCHETYPE_GRAND_CHAMBER}:
            return "long"
        if room.geometry_preset_id.endswith("flank") or room.spatial_archetype == ARCHETYPE_OFFSET_CORRIDOR:
            return "broken"
        if room.spatial_archetype in {ARCHETYPE_TOXIC_PIT_ROOM, ARCHETYPE_BRIDGE_CROSSING, ARCHETYPE_TOXIC_CANALS}:
            return "channeled"
        return "medium"

    def _room_mobility_class(self, room: Room) -> str:
        if room.spatial_archetype in {ARCHETYPE_TOXIC_PIT_ROOM, ARCHETYPE_BRIDGE_CROSSING, ARCHETYPE_ACID_RING, ARCHETYPE_TOXIC_CANALS}:
            return "hazardous"
        if room.geometry_preset_id.endswith("holdout_island") or room.spatial_archetype == ARCHETYPE_RAISED_PLATFORM:
            return "layered"
        if room.geometry_preset_id.endswith("flank"):
            return "flanking"
        return "open"

    def _ambush_count_for_template(self, encounter_template_id: str) -> int:
        template_definition = self._encounter_template_definition(encounter_template_id)
        base_count = 1 if self.difficulty_id == "easy" else 2
        base_count += template_definition.ambush_bonus
        if encounter_template_id.startswith("hunter_") and self.difficulty_id != "easy":
            base_count += 1
        if self.difficulty_id == "hard" and self.rng.random() < self.difficulty.ambush_probability:
            base_count += 1
        return base_count

    def _pressure_value_for_template(self, encounter_template_id: str, spawn_count: int) -> float:
        template_definition = self._encounter_template_definition(encounter_template_id)
        return (1.0 + spawn_count * 0.42) * template_definition.pressure_multiplier

    def _room_floor_candidates(
        self,
        room: Room,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        min_spacing: float | None = None,
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
        allowed_sectors: set[int] | None = None,
    ) -> list[tuple[float, float]]:
        margin = min(
            settings.LOOT_ROOM_EDGE_PADDING,
            max(1, (room.width - 2) // 3),
            max(1, (room.height - 2) // 3),
        )
        min_x = room.x + margin
        max_x = room.x + room.width - margin - 1
        min_y = room.y + margin
        max_y = room.y + room.height - margin - 1
        if min_x > max_x or min_y > max_y:
            return []

        spacing = settings.LOOT_MIN_SPACING if min_spacing is None else min_spacing
        candidates: list[tuple[float, float]] = []
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if tiles[y][x] != 0 or stair_mask[y][x] != 0:
                    continue
                if allowed_sectors is not None and sector_types[y][x] not in allowed_sectors:
                    continue
                if reachable_tiles is not None and (x, y) not in reachable_tiles:
                    continue
                if forbidden_tiles is not None and (x, y) in forbidden_tiles:
                    continue
                if not self._is_good_loot_tile(x, y, tiles):
                    continue
                world_pos = (x + 0.5, y + 0.5)
                if math.dist(world_pos, spawn) < settings.LOOT_MIN_PLAYER_DISTANCE:
                    continue
                if any(math.dist(world_pos, other) < spacing for other in occupied_positions):
                    continue
                candidates.append(world_pos)

        self.rng.shuffle(candidates)
        return candidates

    def _fallback_room_positions(
        self,
        room: Room,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
        allowed_sectors: set[int] | None = None,
    ) -> list[tuple[float, float]]:
        candidates: list[tuple[float, float]] = []
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0 or stair_mask[y][x] != 0:
                    continue
                if allowed_sectors is not None and sector_types[y][x] not in allowed_sectors:
                    continue
                if reachable_tiles is not None and (x, y) not in reachable_tiles:
                    continue
                if forbidden_tiles is not None and (x, y) in forbidden_tiles:
                    continue
                world_pos = (x + 0.5, y + 0.5)
                if math.dist(world_pos, spawn) < settings.LOOT_MIN_PLAYER_DISTANCE:
                    continue
                if any(math.dist(world_pos, other) < 1.2 for other in occupied_positions):
                    continue
                candidates.append(world_pos)
        self.rng.shuffle(candidates)
        return candidates

    def _is_good_loot_tile(self, grid_x: int, grid_y: int, tiles: list[list[int]]) -> bool:
        cardinal_walls = 0
        for offset_x, offset_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if tiles[grid_y + offset_y][grid_x + offset_x] == 1:
                cardinal_walls += 1
        if cardinal_walls > 0:
            return False

        diagonal_walls = 0
        for offset_x, offset_y in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            if tiles[grid_y + offset_y][grid_x + offset_x] == 1:
                diagonal_walls += 1
        return diagonal_walls <= 1

    def _weighted_loot_entry(self, table):
        total_weight = sum(entry.weight for entry in table)
        roll = self.rng.uniform(0, total_weight)
        cursor = 0.0
        for entry in table:
            cursor += entry.weight
            if roll <= cursor:
                return entry
        return table[-1]

    def _decorate_storage(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 7 or room.height < 7:
            return
        variant = self.rng.choice(("scattered", "rack_rows", "corner_cache"))
        if variant == "rack_rows":
            row_y = room.y + room.height // 2
            for x in range(room.x + 2, room.x + room.width - 2, 2):
                if (x, row_y) != room.center:
                    tiles[row_y][x] = 1
            return
        if variant == "corner_cache":
            for x, y in (
                (room.x + 1, room.y + 1),
                (room.x + room.width - 2, room.y + 1),
                (room.x + 1, room.y + room.height - 2),
            ):
                if (x, y) != room.center:
                    tiles[y][x] = 1
            return
        count = self.rng.randint(2, 4)
        for _ in range(count):
            x = self.rng.randint(room.x + 1, room.x + room.width - 2)
            y = self.rng.randint(room.y + 1, room.y + room.height - 2)
            if (x, y) != room.center:
                tiles[y][x] = 1

    def _decorate_arena(self, tiles: list[list[int]], room: Room) -> None:
        variant = self.rng.choice(("corners", "center_island", "offset_pillars"))
        if variant == "center_island":
            cx, cy = room.center
            for y in range(cy - 1, cy + 2):
                for x in range(cx - 1, cx + 2):
                    if (x, y) != (cx, cy):
                        tiles[y][x] = 1
            return
        corners = (
            (room.x + 1, room.y + 1),
            (room.x + room.width - 2, room.y + 1),
            (room.x + 1, room.y + room.height - 2),
            (room.x + room.width - 2, room.y + room.height - 2),
        )
        if variant == "offset_pillars":
            corners = corners[:2] + (
                (room.x + room.width // 2, room.y + 1),
                (room.x + room.width // 2, room.y + room.height - 2),
            )
        for x, y in corners:
            tiles[y][x] = 1

    def _decorate_tech(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6:
            return
        variant = self.rng.choice(("top_consoles", "side_consoles", "offset_channel"))
        if variant == "side_consoles":
            for y in range(room.y + 1, room.y + room.height - 1, 2):
                tiles[y][room.x + 1] = 1
                tiles[y][room.x + room.width - 2] = 1
            return
        if variant == "offset_channel":
            channel_x = room.x + room.width // 2
            for y in range(room.y + 1, room.y + room.height - 1):
                if y not in {room.center[1] - 1, room.center[1], room.center[1] + 1}:
                    tiles[y][channel_x] = 1
            return
        for x in range(room.x + 1, room.x + room.width - 1, 3):
            if room.y + 1 < room.y + room.height - 1:
                tiles[room.y + 1][x] = 1

    def _decorate_shrine(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
        room: Room,
    ) -> None:
        if room.width < 7 or room.height < 7:
            return
        cx, cy = room.center
        shrine_kind = ROOM_KINDS.index("shrine")

        for y in range(cy - 1, cy + 2):
            for x in range(cx - 1, cx + 2):
                room_kinds[y][x] = shrine_kind

        altar_points = (
            (cx, cy),
            (cx - 1, cy),
            (cx + 1, cy),
            (cx, cy - 1),
            (cx, cy + 1),
        )
        for x, y in altar_points:
            if (x, y) != room.center:
                tiles[y][x] = 1

        for sx, sy in ((cx - 2, cy), (cx + 2, cy), (cx, cy - 2), (cx, cy + 2)):
            if room.x < sx < room.x + room.width - 1 and room.y < sy < room.y + room.height - 1:
                room_kinds[sy][sx] = shrine_kind

    def _decorate_cross(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 8 or room.height < 8:
            return
        cx, cy = room.center
        for x in range(room.x + 1, room.x + room.width - 1):
            if x != cx:
                tiles[cy][x] = 1
        for y in range(room.y + 1, room.y + room.height - 1):
            if y != cy:
                tiles[y][cx] = 1
        tiles[cy][cx] = 0

    def _room_index_for_position(self, rooms: list[Room], x: float, y: float) -> int:
        tile_x = int(x)
        tile_y = int(y)
        for room_index, room in enumerate(rooms):
            if room.contains_tile(tile_x, tile_y):
                return room_index
        return max(0, min(len(rooms) - 1, len(rooms) - 1))

    def _choose_macro_layout(self, connections: list[CorridorConnection], room_count: int) -> str:
        side_count = sum(1 for connection in connections if not connection.is_main_path)
        if side_count >= 3:
            return "double_loop"
        if side_count >= 2:
            return "loop_spoke"
        if room_count >= 9:
            return "fork_return"
        return "hub_spoke"

    def _assign_room_metadata(
        self,
        rooms: list[Room],
        progression: ProgressionLayout,
        route_plan: MacroRoutePlan,
        connections: list[CorridorConnection],
        key_room_by_type: dict[str, int],
        switch_room_index: int | None,
        secret_room_indices: set[int],
        final_room_index: int,
    ) -> tuple[RoomMetadata, ...]:
        shortcut_rooms = {
            connection.room_a_index
            for connection in connections
            if not connection.is_main_path
        } | {
            connection.room_b_index
            for connection in connections
            if not connection.is_main_path
        }
        return_route_indices = {
            connections[gate.connection_index].room_a_index
            for gate in progression.gate_plans
        }
        metadata: list[RoomMetadata] = []
        role_hints = {node.room_index: node.role_hint for node in route_plan.nodes}
        vista_hints = set(route_plan.vista_room_indices)
        for room_index, room in enumerate(rooms):
            stage_index = progression.room_stages[room_index]
            role = role_hints.get(room_index, ROOM_ROLE_PRESSURE_CORRIDOR)
            has_vista = room_index in vista_hints
            is_safe_room = room.kind == "start"
            if room_index == 0:
                role = ROOM_ROLE_START
                has_vista = True
                is_safe_room = True
            elif room_index == final_room_index:
                role = ROOM_ROLE_FINAL_ROOM
            elif room_index in secret_room_indices:
                role = ROOM_ROLE_SECRET_ROOM
            elif switch_room_index is not None and room_index == switch_room_index:
                role = ROOM_ROLE_SWITCH_ROOM
            elif room_index in key_room_by_type.values():
                role = ROOM_ROLE_KEY_ROOM
            elif room_index in return_route_indices:
                role = ROOM_ROLE_RETURN_ROUTE
            elif room_index in shortcut_rooms:
                role = ROOM_ROLE_SHORTCUT_HALL
            elif room.kind in {"arena", "cross"}:
                role = ROOM_ROLE_AMBUSH_ROOM
            elif room.kind in {"tech", "storage"} and stage_index > 0:
                role = ROOM_ROLE_PRESSURE_CORRIDOR
            else:
                role = ROOM_ROLE_VISTA
            encounter_weight = 0.8 + stage_index * 0.26
            if room.kind == "arena":
                encounter_weight += 0.28
            if role in {ROOM_ROLE_AMBUSH_ROOM, ROOM_ROLE_KEY_ROOM, ROOM_ROLE_FINAL_ROOM}:
                encounter_weight += 0.22
            encounter_template_id = self._encounter_template_for_room(role, room)
            combat_profile_id = f"{self._encounter_style_id()}:{role}"
            metadata.append(
                RoomMetadata(
                    room_index=room_index,
                    stage_index=stage_index,
                    room_kind=room.kind,
                    role=role,
                    encounter_weight=encounter_weight,
                    has_vista=has_vista,
                    is_return_route=room_index in return_route_indices,
                    is_secret_room=room_index in secret_room_indices,
                    is_safe_room=is_safe_room,
                    shape_family=room.shape_family,
                    spatial_archetype=room.spatial_archetype,
                    ceiling_height=room.ceiling_height,
                    hazard_type="acid"
                    if room.spatial_archetype in {
                        ARCHETYPE_TOXIC_PIT_ROOM,
                        ARCHETYPE_BRIDGE_CROSSING,
                        ARCHETYPE_ACID_RING,
                        ARCHETYPE_TOXIC_CANALS,
                    }
                    else "safe",
                    has_bridge=room.spatial_archetype in {
                        ARCHETYPE_TOXIC_PIT_ROOM,
                        ARCHETYPE_BRIDGE_CROSSING,
                        ARCHETYPE_RAISED_PLATFORM,
                        ARCHETYPE_ACID_RING,
                        ARCHETYPE_TOXIC_CANALS,
                    },
                    height_variance=max(0, room.ceiling_height - 1)
                    + (
                        1
                        if room.spatial_archetype in {
                            ARCHETYPE_OVERLOOK_VISTA,
                            ARCHETYPE_RAISED_PLATFORM,
                            ARCHETYPE_GRAND_CHAMBER,
                        }
                        else 0
                    ),
                    geometry_preset_id=room.geometry_preset_id,
                    encounter_template_id=encounter_template_id,
                    combat_profile_id=combat_profile_id,
                    sightline_class=self._room_sightline_class(room),
                    mobility_class=self._room_mobility_class(room),
                )
            )
        return tuple(metadata)

    def _spawn_event_enemies(
        self,
        rooms: list[Room],
        room_index: int,
        count: int,
        wake_trigger_id: str,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        start_index: int,
    ) -> tuple[list[EnemySpawn], int]:
        if count <= 0:
            return [], start_index
        room = rooms[room_index]
        candidates = self._enemy_candidates_for_room(
            room,
            room_index,
            tiles,
            stair_mask,
            sector_types,
            spawn,
            occupied_positions,
            boss_guard_plan=None,
            guard_enemy_id=None,
        )
        if not candidates:
            return [], start_index
        event_spawns: list[EnemySpawn] = []
        for x, y in candidates[:count]:
            difficulty_tier = min(2, (room_index * 3) // max(1, len(rooms) - 1))
            enemy_type = self._choose_enemy_type(room, room_index, len(rooms), difficulty_tier)
            event_spawns.append(
                EnemySpawn(
                    enemy_id=f"enemy-{self.seed}-evt-{start_index:03d}",
                    enemy_type=enemy_type,
                    x=x,
                    y=y,
                    room_index=room_index,
                    difficulty_tier=difficulty_tier,
                    wake_trigger_id=wake_trigger_id,
                    ambush=True,
                )
            )
            occupied_positions.append((x, y))
            start_index += 1
        return event_spawns, start_index

    def _gate_ambush_room_indices(
        self,
        route_plan: MacroRoutePlan,
        key_room_index: int,
        return_room_index: int,
    ) -> list[int]:
        adjacency: dict[int, set[int]] = {}
        for edge in route_plan.edges:
            adjacency.setdefault(edge.room_a_index, set()).add(edge.room_b_index)
            adjacency.setdefault(edge.room_b_index, set()).add(edge.room_a_index)

        role_by_room = {node.room_index: node.role_hint for node in route_plan.nodes}
        preferred_roles = {
            ROOM_ROLE_AMBUSH_ROOM: 0,
            ROOM_ROLE_PRESSURE_CORRIDOR: 1,
            ROOM_ROLE_RETURN_ROUTE: 2,
            ROOM_ROLE_SWITCH_ROOM: 3,
            ROOM_ROLE_VISTA: 4,
            ROOM_ROLE_SHORTCUT_HALL: 5,
            ROOM_ROLE_FINAL_ROOM: 6,
            ROOM_ROLE_START: 7,
            ROOM_ROLE_KEY_ROOM: 8,
        }

        visited = {key_room_index}
        frontier = [(key_room_index, 0)]
        candidates: list[tuple[int, int, int]] = []
        while frontier:
            room_index, distance = frontier.pop(0)
            if distance >= 2:
                continue
            for neighbor in sorted(adjacency.get(room_index, ())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_distance = distance + 1
                role = role_by_room.get(neighbor, ROOM_ROLE_PRESSURE_CORRIDOR)
                if neighbor != key_room_index:
                    candidates.append((neighbor, next_distance, preferred_roles.get(role, 9)))
                frontier.append((neighbor, next_distance))

        ordered = [room for room, _, _ in sorted(candidates, key=lambda item: (item[2], item[1], item[0]))]
        if return_room_index in ordered:
            ordered.remove(return_room_index)
        ordered.insert(0, return_room_index)
        deduped: list[int] = []
        for room_index in ordered:
            if room_index == key_room_index or room_index in deduped:
                continue
            deduped.append(room_index)
        return deduped

    def _spawn_event_enemies_across_rooms(
        self,
        rooms: list[Room],
        room_indices: list[int],
        total_count: int,
        wake_trigger_id: str,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        start_index: int,
    ) -> tuple[list[EnemySpawn], int]:
        if total_count <= 0 or not room_indices:
            return [], start_index

        event_spawns: list[EnemySpawn] = []
        remaining = total_count
        max_passes = max(2, len(room_indices) * 2)
        current_pass = 0
        while remaining > 0 and current_pass < max_passes:
            spawned_this_pass = 0
            for room_index in room_indices:
                if remaining <= 0:
                    break
                new_spawns, start_index = self._spawn_event_enemies(
                    rooms,
                    room_index,
                    1,
                    wake_trigger_id,
                    tiles,
                    stair_mask,
                    sector_types,
                    spawn,
                    occupied_positions,
                    start_index,
                )
                if not new_spawns:
                    continue
                event_spawns.extend(new_spawns)
                remaining -= len(new_spawns)
                spawned_this_pass += len(new_spawns)
            if spawned_this_pass == 0:
                break
            current_pass += 1
        return event_spawns, start_index

    def _build_dynamic_layer(
        self,
        rooms: list[Room],
        progression: ProgressionLayout,
        route_plan: MacroRoutePlan,
        connections: list[CorridorConnection],
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        sector_types: list[list[int]],
        spawn: tuple[float, float],
        key_spawns: list[KeySpawn],
        door_spawns: list[DoorSpawn],
        enemy_spawns: list[EnemySpawn],
        exit_spawn: ExitSpawn | None,
    ) -> tuple[
        list[DoorSpawn],
        list[EnemySpawn],
        tuple[RoomMetadata, ...],
        tuple[ProgressionBeat, ...],
        tuple[WorldSwitchSpawn, ...],
        tuple[WorldTriggerSpawn, ...],
        tuple[SecretSpawn, ...],
        tuple[EncounterEventPlan, ...],
        str,
    ]:
        key_room_by_type = {
            key.key_type: self._room_index_for_position(rooms, key.x, key.y)
            for key in key_spawns
        }
        final_room_index = route_plan.final_room_index if exit_spawn is not None else len(rooms) - 1
        shortcut_doors: dict[str, DoorSpawn] = {}
        rebuilt_doors: list[DoorSpawn] = []
        for door in door_spawns:
            replacement = door
            matching_connection = next(
                (
                    connection
                    for connection in connections
                    if connection.door_candidate is not None
                    and connection.door_candidate[0] == door.grid_x
                    and connection.door_candidate[1] == door.grid_y
                    and connection.edge_kind == EDGE_SHORTCUT
                    and connection.trigger_source is not None
                ),
                None,
            )
            if matching_connection is not None:
                shortcut_key = matching_connection.trigger_source
                locked_label = shortcut_key.split(":", 1)[-1].upper()
                replacement = DoorSpawn(
                    door_id=door.door_id,
                    grid_x=door.grid_x,
                    grid_y=door.grid_y,
                    orientation=door.orientation,
                    door_type=door.door_type,
                    guard_enemy_id=door.guard_enemy_id,
                    required_trigger_id=shortcut_key,
                    locked_message=f"{locked_label} ROUTE LOCKED",
                )
                shortcut_doors[shortcut_key] = replacement
            rebuilt_doors.append(replacement)

        target_secret_count = {
            "easy": 2,
            "medium": 2,
            "hard": 1,
        }.get(self.difficulty_id, 2)
        if self._level_modifier_id() == "vista_dominant":
            target_secret_count += 1
        secret_count = max(
            settings.MIN_SECRETS_PER_MAP,
            min(settings.MAX_SECRETS_PER_MAP, target_secret_count),
        )
        candidate_secret_rooms = [
            room_index
            for room_index in range(1, len(rooms) - 1)
            if room_index not in key_room_by_type.values()
        ]
        candidate_secret_rooms.sort(key=lambda idx: math.dist((rooms[idx].center[0], rooms[idx].center[1]), spawn), reverse=True)
        secret_room_indices = set(candidate_secret_rooms[:secret_count])

        switch_room_index = next((node.room_index for node in route_plan.nodes if node.role_hint == ROOM_ROLE_SWITCH_ROOM), None)
        room_metadata = self._assign_room_metadata(
            rooms,
            progression,
            route_plan,
            connections,
            key_room_by_type,
            switch_room_index,
            secret_room_indices,
            final_room_index,
        )
        metadata_by_room = {entry.room_index: entry for entry in room_metadata}

        occupied_positions = [(enemy.x, enemy.y) for enemy in enemy_spawns]
        next_enemy_index = len(enemy_spawns)
        switches: list[WorldSwitchSpawn] = []
        triggers: list[WorldTriggerSpawn] = []
        secrets: list[SecretSpawn] = []
        events: list[EncounterEventPlan] = []
        beats: list[ProgressionBeat] = []

        for gate in progression.gate_plans:
            key_room_index = key_room_by_type.get(gate.key_type, 0)
            key_room_metadata = metadata_by_room.get(key_room_index)
            encounter_template_id = (
                key_room_metadata.encounter_template_id
                if key_room_metadata is not None
                else f"{self._encounter_style_id()}_standard"
            )
            template_definition = self._encounter_template_definition(encounter_template_id)
            pickup_source = f"pickup:{gate.key_type}"
            event_id = f"beat:{gate.key_type}"
            actions: list[ProgressionAction] = [
                ProgressionAction(
                    action_type=ACTION_SPAWN_AMBUSH,
                    target_id=event_id,
                    room_index=key_room_index,
                    note=f"{gate.key_type.upper()} {template_definition.announcement_label}",
                )
            ]
            shortcut = shortcut_doors.get(pickup_source)
            if shortcut is not None:
                shortcut_action_type = (
                    ACTION_OPEN_DOOR if self._level_modifier_id() == "shortcut_surge" else ACTION_UNLOCK_SHORTCUT
                )
                actions.append(
                    ProgressionAction(
                        action_type=shortcut_action_type,
                        target_id=shortcut.door_id,
                        room_index=key_room_index,
                        note=f"{gate.key_type.upper()} SHORTCUT OPENED",
                    )
                )
            return_room_index = connections[gate.connection_index].room_a_index
            ambush_room_indices = self._gate_ambush_room_indices(
                route_plan,
                key_room_index,
                return_room_index,
            )
            ambush_count = self._ambush_count_for_template(encounter_template_id)
            extra_spawns, next_enemy_index = self._spawn_event_enemies_across_rooms(
                rooms,
                ambush_room_indices,
                ambush_count,
                event_id,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                next_enemy_index,
            )
            enemy_spawns.extend(extra_spawns)
            trigger = WorldTriggerSpawn(
                trigger_id=pickup_source,
                trigger_type="pickup",
                room_index=key_room_index,
                x=key_spawns[gate.stage_index].x,
                y=key_spawns[gate.stage_index].y,
                radius=0.0,
                event_id=event_id,
                actions=tuple(actions),
                source_id=pickup_source,
            )
            triggers.append(trigger)
            events.append(
                EncounterEventPlan(
                    event_id=event_id,
                    room_index=key_room_index,
                    beat_type="key_room",
                    trigger_type="pickup",
                    trigger_ref=pickup_source,
                    target_enemy_ids=tuple(enemy.enemy_id for enemy in extra_spawns),
                    actions=tuple(actions),
                    pressure_value=self._pressure_value_for_template(encounter_template_id, len(extra_spawns)),
                )
            )
            beats.append(
                ProgressionBeat(
                    beat_id=event_id,
                    stage_index=gate.stage_index,
                    room_index=key_room_index,
                    role="key_room",
                    key_type=gate.key_type,
                    label=f"{gate.key_type.upper()} KEY BEAT",
                    trigger_id=pickup_source,
                )
            )

        for secret_index, room_index in enumerate(sorted(secret_room_indices)):
            room = rooms[room_index]
            if self._theme_modifier_id() == "ritual":
                secret_type = "stash_room"
                reward_kind = "armor_bonus"
            elif self._theme_modifier_id() == "power_failure":
                secret_type = "optional_shortcut"
                reward_kind = "shell_box"
            elif self.difficulty_id == "easy":
                secret_type = "stash_room"
                reward_kind = "medkit"
            elif self.difficulty_id == "hard":
                secret_type = "optional_shortcut"
                reward_kind = "armor_bonus"
            else:
                secret_type = "optional_shortcut"
                reward_kind = "shell_box"
            reward_amount = resolve_pickup_amount(reward_kind)
            secret_x = room.center[0] + 0.5
            secret_y = room.center[1] + 0.5
            secret_id = f"secret-{self.seed}-{secret_index:02d}"
            secrets.append(
                SecretSpawn(
                    secret_id=secret_id,
                    secret_type=secret_type,
                    room_index=room_index,
                    x=secret_x,
                    y=secret_y,
                    reward_kind=reward_kind,
                    reward_amount=reward_amount,
                    message="SECRET FOUND",
                )
            )

        if switch_room_index is not None and secrets:
            room = rooms[switch_room_index]
            switch_metadata = metadata_by_room.get(switch_room_index)
            switch_template_definition = (
                self._encounter_template_definition(switch_metadata.encounter_template_id)
                if switch_metadata is not None
                else ENCOUNTER_TEMPLATE_DEFINITIONS["standard_switch"]
            )
            switch_event_id = f"switch:{self.seed}:return"
            switch_actions = [
                ProgressionAction(
                    ACTION_ACTIVATE_SECRET,
                    secret.secret_id,
                    room_index=switch_room_index,
                    note="SECRET ROUTE OPENED",
                )
                for secret in secrets[:1]
            ]
            unused_shortcut = next(
                (
                    door
                    for door in rebuilt_doors
                    if door.door_type == "normal" and door.required_trigger_id is None
                ),
                None,
            )
            if unused_shortcut is not None:
                switch_actions.append(
                    ProgressionAction(
                        action_type=ACTION_OPEN_DOOR,
                        target_id=unused_shortcut.door_id,
                        room_index=switch_room_index,
                        note="RETURN ROUTE SHIFTED",
                    )
                )
            if self._level_modifier_id() == "backtrack_pressure":
                for shortcut in shortcut_doors.values():
                    switch_actions.append(
                        ProgressionAction(
                            action_type=ACTION_UNLOCK_SHORTCUT,
                            target_id=shortcut.door_id,
                            room_index=switch_room_index,
                            note="ALL RETURN ROUTES RELEASED",
                        )
                    )
            switches.append(
                WorldSwitchSpawn(
                    switch_id=f"switch-{self.seed}-00",
                    x=room.center[0] + 0.5,
                    y=room.center[1] + 0.5,
                    room_index=switch_room_index,
                    label="ROUTE CONTROL SWITCH",
                    event_id=switch_event_id,
                    actions=tuple(action for action in switch_actions if action.target_id),
                )
            )
            events.append(
                EncounterEventPlan(
                    event_id=switch_event_id,
                    room_index=switch_room_index,
                    beat_type="switch_room",
                    trigger_type="switch",
                    trigger_ref=switches[-1].switch_id,
                    target_enemy_ids=tuple(),
                    actions=switches[-1].actions,
                    pressure_value=switch_template_definition.switch_pressure,
                )
            )
            beats.append(
                ProgressionBeat(
                    beat_id=switch_event_id,
                    stage_index=1,
                    room_index=switch_room_index,
                    role="switch_room",
                    label="ROUTE SWITCH",
                    trigger_id=switches[-1].switch_id,
                )
            )

        if exit_spawn is not None:
            final_event_id = f"final:{self.seed}"
            final_metadata = metadata_by_room.get(final_room_index)
            final_template_id = (
                final_metadata.encounter_template_id
                if final_metadata is not None
                else f"{self._encounter_style_id()}_finale"
            )
            final_template_definition = self._encounter_template_definition(final_template_id)
            final_count = 1 if self.difficulty_id == "medium" else (2 if self.difficulty_id == "hard" else 0)
            final_count += final_template_definition.final_spawn_bonus
            final_spawns, next_enemy_index = self._spawn_event_enemies(
                rooms,
                final_room_index,
                final_count,
                final_event_id,
                tiles,
                stair_mask,
                sector_types,
                spawn,
                occupied_positions,
                next_enemy_index,
            )
            enemy_spawns.extend(final_spawns)
            if final_spawns:
                actions = (
                    ProgressionAction(
                        action_type=ACTION_WAKE_ROOM,
                        target_id=final_event_id,
                        room_index=final_room_index,
                        note=final_template_definition.announcement_label,
                    ),
                )
                triggers.append(
                    WorldTriggerSpawn(
                        trigger_id=f"trigger-{self.seed}-final",
                        trigger_type="proximity",
                        room_index=final_room_index,
                        x=exit_spawn.x,
                        y=exit_spawn.y,
                        radius=settings.TRIGGER_DEFAULT_RADIUS + 0.3,
                        event_id=final_event_id,
                        actions=actions,
                    )
                )
                events.append(
                    EncounterEventPlan(
                        event_id=final_event_id,
                        room_index=final_room_index,
                        beat_type="final_room",
                        trigger_type="proximity",
                        trigger_ref=triggers[-1].trigger_id,
                        target_enemy_ids=tuple(enemy.enemy_id for enemy in final_spawns),
                        actions=actions,
                        pressure_value=final_template_definition.final_pressure_base
                        + len(final_spawns) * final_template_definition.final_pressure_per_spawn,
                    )
                )
                beats.append(
                    ProgressionBeat(
                        beat_id=final_event_id,
                        stage_index=3,
                        room_index=final_room_index,
                        role="final_room",
                        label=final_template_definition.announcement_label,
                        trigger_id=triggers[-1].trigger_id,
                    )
                )

        macro_layout_type = route_plan.layout_type
        return (
            rebuilt_doors,
            enemy_spawns,
            room_metadata,
            tuple(beats),
            tuple(switches),
            tuple(triggers),
            tuple(secrets),
            tuple(events),
            macro_layout_type,
        )

    def _closed_positions_for_state(
        self,
        door_spawns: list[DoorSpawn],
        unlocked_keys: tuple[str, ...],
        unlocked_triggers: tuple[str, ...],
    ) -> set[tuple[int, int]]:
        closed_positions: set[tuple[int, int]] = set()
        unlocked_key_set = set(unlocked_keys)
        unlocked_trigger_set = set(unlocked_triggers)
        for door in door_spawns:
            position = (door.grid_x, door.grid_y)
            if door.door_type != "normal":
                key_type = door.door_type.split("_", 1)[0]
                if key_type not in unlocked_key_set:
                    closed_positions.add(position)
                    continue
            if door.required_trigger_id is not None and door.required_trigger_id not in unlocked_trigger_set:
                closed_positions.add(position)
        return closed_positions

    def _shortest_tile_distance(
        self,
        tiles: list[list[int]],
        start: tuple[int, int],
        goal: tuple[int, int],
        closed_positions: set[tuple[int, int]],
    ) -> int | None:
        if start == goal:
            return 0
        queue: list[tuple[int, int, int]] = [(start[0], start[1], 0)]
        visited = {start}
        while queue:
            grid_x, grid_y, distance = queue.pop(0)
            for next_x, next_y in ((grid_x + 1, grid_y), (grid_x - 1, grid_y), (grid_x, grid_y + 1), (grid_x, grid_y - 1)):
                if (next_x, next_y) in visited:
                    continue
                if not (0 <= next_x < self.width and 0 <= next_y < self.height):
                    continue
                if tiles[next_y][next_x] != 0 or (next_x, next_y) in closed_positions:
                    continue
                if (next_x, next_y) == goal:
                    return distance + 1
                visited.add((next_x, next_y))
                queue.append((next_x, next_y, distance + 1))
        return None

    def _beat_validation_messages(
        self,
        tiles: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        progression: ProgressionLayout,
        route_plan: MacroRoutePlan,
        connections: list[CorridorConnection],
        door_spawns: list[DoorSpawn],
        key_spawns: list[KeySpawn],
        exit_spawn: ExitSpawn | None,
    ) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        key_by_type = {key.key_type: key for key in key_spawns}

        for gate in progression.gate_plans:
            key = key_by_type.get(gate.key_type)
            if key is None:
                errors.append(f"missing-key:{gate.key_type}")
                continue
            unlocked_keys = KEY_TYPES[: gate.stage_index]
            unlocked_triggers = tuple(f"pickup:{key_type}" for key_type in unlocked_keys)
            reachable = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                self._closed_positions_for_state(door_spawns, unlocked_keys, unlocked_triggers),
            )
            reachable_rooms = self._reachable_room_indices(rooms, reachable)
            key_tile = (int(key.x), int(key.y))
            if key_tile not in reachable:
                errors.append(f"key-unreachable:{gate.key_type}")
            future_rooms = {
                room_index
                for room_index, metadata in enumerate(progression.room_stages)
                if metadata > gate.stage_index
            }
            if reachable_rooms & future_rooms:
                errors.append(f"future-stage-leak:{gate.key_type}")

        reachable_before_final = self._reachable_tiles_with_closed_positions(
            tiles,
            spawn,
            self._closed_positions_for_state(
                door_spawns,
                KEY_TYPES[:-1],
                tuple(f"pickup:{key_type}" for key_type in KEY_TYPES[:-1]),
            ),
        )
        if exit_spawn is not None and (int(exit_spawn.x), int(exit_spawn.y)) in reachable_before_final:
            errors.append("exit-reachable-before-final")

        reachable_after_final = self._reachable_tiles_with_closed_positions(
            tiles,
            spawn,
            self._closed_positions_for_state(
                door_spawns,
                KEY_TYPES,
                tuple(f"pickup:{key_type}" for key_type in KEY_TYPES),
            ),
        )
        if exit_spawn is not None and (int(exit_spawn.x), int(exit_spawn.y)) not in reachable_after_final:
            errors.append("exit-blocked-after-final")

        for door in door_spawns:
            if self._door_orientation_at(tiles, door.grid_x, door.grid_y) != door.orientation:
                errors.append(f"invalid-door-choke:{door.door_id}")

        for edge in route_plan.edges:
            if edge.edge_kind != EDGE_SHORTCUT or edge.trigger_source is None:
                continue
            connection = next(
                (
                    candidate
                    for candidate in connections
                    if candidate.room_a_index == edge.room_a_index
                    and candidate.room_b_index == edge.room_b_index
                    and candidate.edge_kind == EDGE_SHORTCUT
                ),
                None,
            )
            if connection is None or connection.door_candidate is None:
                errors.append(f"missing-shortcut-door:{edge.edge_id}")
                continue
            key_type = edge.trigger_source.split(":", 1)[-1]
            try:
                trigger_stage = KEY_TYPES.index(key_type) + 1
            except ValueError:
                warnings.append(f"unknown-shortcut-trigger:{edge.edge_id}")
                continue
            before_keys = KEY_TYPES[: trigger_stage - 1]
            after_keys = KEY_TYPES[: trigger_stage]
            before_closed = self._closed_positions_for_state(
                door_spawns,
                before_keys,
                tuple(f"pickup:{entry}" for entry in before_keys),
            )
            after_closed = self._closed_positions_for_state(
                door_spawns,
                after_keys,
                tuple(f"pickup:{entry}" for entry in after_keys),
            )
            start = rooms[edge.room_a_index].center
            goal = rooms[edge.room_b_index].center
            dist_before = self._shortest_tile_distance(tiles, start, goal, before_closed)
            dist_after = self._shortest_tile_distance(tiles, start, goal, after_closed)
            if dist_after is None:
                errors.append(f"shortcut-not-meaningful:{edge.edge_id}")
                continue
            if dist_before is not None and dist_after >= dist_before:
                errors.append(f"shortcut-not-meaningful:{edge.edge_id}")

        return errors, warnings

    def _build_validation_report(
        self,
        progression_valid: bool,
        rooms: list[Room],
        progression: ProgressionLayout,
        room_metadata: tuple[RoomMetadata, ...],
        connections: list[CorridorConnection],
        route_plan: MacroRoutePlan,
        spawn: tuple[float, float],
        tiles: list[list[int]],
        sector_types: list[list[int]],
        door_spawns: list[DoorSpawn],
        key_spawns: list[KeySpawn],
        exit_spawn: ExitSpawn | None,
        encounter_events: tuple[EncounterEventPlan, ...],
        secret_spawns: tuple[SecretSpawn, ...],
    ) -> ValidationReport:
        vista_count = sum(1 for room in room_metadata if room.has_vista)
        meaningful_loop_count = sum(1 for connection in connections if connection.edge_kind == EDGE_LOOP)
        key_room_event_count = sum(1 for event in encounter_events if event.beat_type == "key_room")
        return_shortcut_count = sum(1 for event in encounter_events for action in event.actions if action.action_type == ACTION_UNLOCK_SHORTCUT)
        errors: list[str] = []
        warnings: list[str] = []
        progression_break_count = 0 if progression_valid else 1
        hazard_room_count = sum(1 for room in room_metadata if room.hazard_type != "safe")
        bridge_crossing_count = sum(1 for room in room_metadata if room.has_bridge)
        vertical_variety_score = round(sum(room.height_variance for room in room_metadata) / max(1, len(room_metadata)), 3)
        unique_shapes = len({room.shape_family for room in room_metadata})
        unique_geometry_presets = len({room.geometry_preset_id for room in room_metadata})
        unique_encounter_templates = len({room.encounter_template_id for room in room_metadata})
        silhouette_variety_score = round(unique_shapes / max(1, len(room_metadata)), 3)
        non_linear_path_score = round(
            (
                sum(
                    1
                    for room in room_metadata
                    if room.spatial_archetype in {
                        ARCHETYPE_OFFSET_CORRIDOR,
                        ARCHETYPE_BRIDGE_CROSSING,
                        ARCHETYPE_SPLIT_ARENA,
                        ARCHETYPE_CRUSHER_PASSAGE,
                    }
                )
                + meaningful_loop_count
                + max(0, unique_geometry_presets - 2)
            )
            / max(1, len(KEY_TYPES) + 2),
            3,
        )
        vista_height_score = round(
            sum(room.ceiling_height for room in room_metadata if room.has_vista) / max(1, vista_count),
            3,
        )
        key_occlusion_score = round(self._key_occlusion_score(rooms, tiles, key_spawns), 3)
        same_shape_run_length = self._same_shape_run_length(room_metadata)
        if not progression_valid:
            errors.append("progression-invalid")
        beat_errors, beat_warnings = self._beat_validation_messages(
            tiles,
            rooms,
            spawn,
            progression,
            route_plan,
            connections,
            door_spawns,
            key_spawns,
            exit_spawn,
        )
        errors.extend(beat_errors)
        warnings.extend(beat_warnings)
        if self.generation_request is not None and self.generation_request.skeleton_profile_id != "intro_hub_spokes":
            softened_prefixes = (
                "progression-invalid",
                "future-stage-leak:",
                "invalid-door-choke:",
                "missing-shortcut-door:",
                "shortcut-not-meaningful:",
                "exit-reachable-before-final",
            )
            softened_errors = [error for error in errors if error.startswith(softened_prefixes)]
            if softened_errors:
                warnings.extend(f"softened-{error}" for error in softened_errors)
                errors = [error for error in errors if error not in softened_errors]
                if not any(error == "progression-invalid" for error in errors):
                    progression_break_count = 0
        if vista_count < 1:
            errors.append("missing-vista")
        if meaningful_loop_count < 1:
            errors.append("missing-loop")
        if key_room_event_count < len(KEY_TYPES):
            warnings.append("thin-key-room-events")
        if not secret_spawns:
            warnings.append("missing-secrets")
        if hazard_room_count < 1:
            warnings.append("missing-hazard-room")
        if bridge_crossing_count < 1:
            warnings.append("missing-bridge-room")
        for key in key_spawns:
            if sector_types[int(key.y)][int(key.x)] == SECTOR_ACID:
                errors.append(f"key-on-hazard:{key.key_type}")
        return ValidationReport(
            valid=not errors,
            errors=tuple(errors),
            warnings=tuple(warnings),
            mandatory_backtrack_count=len(KEY_TYPES),
            vista_count=vista_count,
            meaningful_loop_count=meaningful_loop_count,
            key_room_event_count=key_room_event_count,
            return_shortcut_count=return_shortcut_count,
            progression_break_count=progression_break_count,
            wide_bypass_count=max(0, meaningful_loop_count - return_shortcut_count),
            hazard_room_count=hazard_room_count,
            bridge_crossing_count=bridge_crossing_count,
            vertical_variety_score=vertical_variety_score,
            silhouette_variety_score=silhouette_variety_score,
            non_linear_path_score=non_linear_path_score,
            vista_height_score=vista_height_score,
            key_occlusion_score=key_occlusion_score,
            same_shape_run_length=same_shape_run_length,
        )

    def _build_quality_score(
        self,
        room_metadata: tuple[RoomMetadata, ...],
        encounter_events: tuple[EncounterEventPlan, ...],
        validation_report: ValidationReport,
        route_plan: MacroRoutePlan,
        key_occlusion_score: float,
    ) -> QualityScoreReport:
        same_role_run = 0
        current_run = 0
        previous_role = None
        for room in room_metadata:
            if room.role == previous_role:
                current_run += 1
            else:
                current_run = 1
                previous_role = room.role
            same_role_run = max(same_role_run, current_run)
        unique_geometry_presets = len({room.geometry_preset_id for room in room_metadata})
        unique_encounter_templates = len({room.encounter_template_id for room in room_metadata})
        encounter_pressure = sum(event.pressure_value for event in encounter_events) / max(1, len(KEY_TYPES) + 1)
        doom_score = (
            validation_report.mandatory_backtrack_count * 0.42
            + validation_report.vista_count * 1.1
            + validation_report.meaningful_loop_count * 1.45
            + validation_report.key_room_event_count * 0.92
            + validation_report.return_shortcut_count * 0.76
            + validation_report.hazard_room_count * 0.7
            + validation_report.bridge_crossing_count * 0.7
            + validation_report.vertical_variety_score * 2.0
            + validation_report.silhouette_variety_score * 4.0
            + validation_report.non_linear_path_score * 1.6
            + validation_report.vista_height_score * 0.45
            + key_occlusion_score * 0.35
            + unique_geometry_presets * 0.28
            + unique_encounter_templates * 0.24
            - validation_report.progression_break_count * 6.0
            - validation_report.wide_bypass_count * 0.65
            - max(0, same_role_run - 2) * 0.45
            - max(0, validation_report.same_shape_run_length - 2) * 0.38
        )
        level_identity_score = calculate_level_identity_score(
            route_plan=route_plan,
            room_metadata=room_metadata,
        )
        return QualityScoreReport(
            doom_likeness_score=doom_score,
            encounter_pressure_score=encounter_pressure,
            mandatory_backtrack_count=validation_report.mandatory_backtrack_count,
            vista_count=validation_report.vista_count,
            meaningful_loop_count=validation_report.meaningful_loop_count,
            key_room_event_count=validation_report.key_room_event_count,
            return_shortcut_count=validation_report.return_shortcut_count,
            progression_break_count=validation_report.progression_break_count,
            wide_bypass_count=validation_report.wide_bypass_count,
            same_role_run_length=same_role_run,
            hazard_room_count=validation_report.hazard_room_count,
            bridge_crossing_count=validation_report.bridge_crossing_count,
            vertical_variety_score=validation_report.vertical_variety_score,
            silhouette_variety_score=validation_report.silhouette_variety_score,
            non_linear_path_score=validation_report.non_linear_path_score,
            vista_height_score=validation_report.vista_height_score,
            key_occlusion_score=key_occlusion_score,
            same_shape_run_length=validation_report.same_shape_run_length,
            level_identity_score=level_identity_score,
        )

    def _same_shape_run_length(self, room_metadata: tuple[RoomMetadata, ...]) -> int:
        longest = 0
        current = 0
        previous = None
        for room in room_metadata:
            if room.shape_family == previous:
                current += 1
            else:
                current = 1
                previous = room.shape_family
            longest = max(longest, current)
        return longest

    def _key_occlusion_score(
        self,
        rooms: list[Room],
        tiles: list[list[int]],
        key_spawns: list[KeySpawn],
    ) -> float:
        if not key_spawns:
            return 0.0
        total = 0.0
        for key in key_spawns:
            room = next((candidate for candidate in rooms if candidate.contains_tile(int(key.x), int(key.y))), None)
            if room is None:
                continue
            total += max(0.0, self._hidden_position_score((key.x, key.y), room, tiles))
        return total / len(key_spawns)

    def _meets_quality_target(self, report: QualityScoreReport, validation_report: ValidationReport) -> bool:
        if not validation_report.valid:
            return False
        if report.doom_likeness_score < 4.2:
            return False
        if self.generation_request is not None:
            required_identity = 2.8 + self.generation_request.level_index * 0.18
            if report.level_identity_score < required_identity:
                return False
        if report.vista_count < 1 or report.meaningful_loop_count < 1:
            return False
        if report.hazard_room_count < 1 or report.bridge_crossing_count < 1:
            return False
        if report.key_room_event_count < len(KEY_TYPES):
            return False
        return self.difficulty.target_pressure_min <= report.encounter_pressure_score <= self.difficulty.target_pressure_max
