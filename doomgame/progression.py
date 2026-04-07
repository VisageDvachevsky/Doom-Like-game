from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

DifficultyId = str
MacroLayoutType = str
RoomRole = str
ProgressionActionType = str
SecretType = str
TriggerType = str
RouteEdgeKind = str
LevelArchetypeId = str
LevelSkeletonProfileId = str
MacroVariantId = str
SpatialProfileId = str
EncounterStyleId = str
ThemeModifierId = str
LevelModifierId = str

DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"
DIFFICULTY_IDS: tuple[DifficultyId, ...] = (
    DIFFICULTY_EASY,
    DIFFICULTY_MEDIUM,
    DIFFICULTY_HARD,
)
DEFAULT_DIFFICULTY_ID: DifficultyId = DIFFICULTY_MEDIUM
COMPATIBILITY_CACHE_VERSION = 4
COMPATIBILITY_CACHE_PATH = Path(__file__).with_name("_campaign_compatibility_cache.json")

MACRO_LAYOUT_HUB_SPOKE = "hub_spoke"
MACRO_LAYOUT_LOOP_SPOKE = "loop_spoke"
MACRO_LAYOUT_FORK_RETURN = "fork_return"
MACRO_LAYOUT_DOUBLE_LOOP = "double_loop"
MACRO_LAYOUT_TWO_HUB = "two_hub"
MACRO_LAYOUT_TYPES: tuple[MacroLayoutType, ...] = (
    MACRO_LAYOUT_HUB_SPOKE,
    MACRO_LAYOUT_LOOP_SPOKE,
    MACRO_LAYOUT_FORK_RETURN,
    MACRO_LAYOUT_DOUBLE_LOOP,
    MACRO_LAYOUT_TWO_HUB,
)

ARCHETYPE_TECH_BASE = "tech_base"
ARCHETYPE_RELAY_STATION = "relay_station"
ARCHETYPE_WASTE_PLANT = "waste_plant"
ARCHETYPE_OUTER_RING = "outer_ring"
ARCHETYPE_SHRINE_FORTRESS = "shrine_fortress"

SKELETON_INTRO_HUB_SPOKES = "intro_hub_spokes"
SKELETON_DOUBLE_RING = "double_ring_circulation"
SKELETON_SPLIT_FORK = "split_fork_reconverge"
SKELETON_PERIMETER_PUSH = "perimeter_inward_push"
SKELETON_TWO_HUB_FINALE = "two_hub_finale"

ROOM_ROLE_START = "start"
ROOM_ROLE_VISTA = "vista"
ROOM_ROLE_PRESSURE_CORRIDOR = "pressure_corridor"
ROOM_ROLE_AMBUSH_ROOM = "ambush_room"
ROOM_ROLE_SWITCH_ROOM = "switch_room"
ROOM_ROLE_KEY_ROOM = "key_room"
ROOM_ROLE_RETURN_ROUTE = "return_route"
ROOM_ROLE_SHORTCUT_HALL = "shortcut_hall"
ROOM_ROLE_SECRET_ROOM = "secret_room"
ROOM_ROLE_FINAL_ROOM = "final_room"

ACTION_OPEN_DOOR = "open_door"
ACTION_UNLOCK_SHORTCUT = "unlock_shortcut"
ACTION_SPAWN_AMBUSH = "spawn_ambush"
ACTION_WAKE_ROOM = "wake_room"
ACTION_ACTIVATE_SECRET = "activate_secret"
ACTION_ACTIVATE_EXIT_ROUTE = "activate_exit_route"

TRIGGER_PROXIMITY = "proximity"
TRIGGER_PICKUP = "pickup"
TRIGGER_SWITCH = "switch"

SECRET_WALL_PANEL = "wall_panel"
SECRET_FAKE_DEAD_END = "fake_dead_end"
SECRET_OPTIONAL_SHORTCUT = "optional_shortcut"
SECRET_STASH_ROOM = "stash_room"

EDGE_MAIN = "main"
EDGE_LOOP = "loop"
EDGE_SHORTCUT = "shortcut"

MACRO_VARIANT_DEFAULT = "default"
MACRO_VARIANT_BRANCHY = "branchy"
MACRO_VARIANT_CROSS_LINK = "cross_link"
MACRO_VARIANT_COLLAPSE = "collapse"
MACRO_VARIANT_PINCER = "pincer"

SPATIAL_PROFILE_BALANCED = "balanced"
SPATIAL_PROFILE_TIGHT = "tight"
SPATIAL_PROFILE_EXPANSIVE = "expansive"
SPATIAL_PROFILE_VERTICAL = "vertical"

ENCOUNTER_STYLE_STANDARD = "standard"
ENCOUNTER_STYLE_HOLDOUT = "holdout"
ENCOUNTER_STYLE_HUNTER = "hunter"
ENCOUNTER_STYLE_PINCER = "pincer"

THEME_MODIFIER_DEFAULT = "default"
THEME_MODIFIER_POWER_FAILURE = "power_failure"
THEME_MODIFIER_CORROSION = "corrosion"
THEME_MODIFIER_RITUAL = "ritual"
THEME_MODIFIER_SIEGE = "siege"

LEVEL_MODIFIER_STANDARD = "standard"
LEVEL_MODIFIER_SHORTCUT_SURGE = "shortcut_surge"
LEVEL_MODIFIER_LOCKDOWN = "lockdown"
LEVEL_MODIFIER_BACKTRACK_PRESSURE = "backtrack_pressure"
LEVEL_MODIFIER_VISTA_DOMINANT = "vista_dominant"


@dataclass(frozen=True)
class DifficultyDefinition:
    difficulty_id: DifficultyId
    label: str
    enemy_count_scale: float
    enemy_room_cap_bonus: int
    ambush_probability: float
    boss_guard_probability: float
    pickup_density_scale: float
    damage_pressure_bias: float
    safe_room_bias: float
    target_pressure_min: float
    target_pressure_max: float


DIFFICULTY_PRESETS: dict[DifficultyId, DifficultyDefinition] = {
    DIFFICULTY_EASY: DifficultyDefinition(
        difficulty_id=DIFFICULTY_EASY,
        label="I'm Too Young To Die",
        enemy_count_scale=0.9,
        enemy_room_cap_bonus=-1,
        ambush_probability=0.3,
        boss_guard_probability=0.62,
        pickup_density_scale=1.18,
        damage_pressure_bias=0.88,
        safe_room_bias=1.1,
        target_pressure_min=1.0,
        target_pressure_max=1.7,
    ),
    DIFFICULTY_MEDIUM: DifficultyDefinition(
        difficulty_id=DIFFICULTY_MEDIUM,
        label="Hey, Not Too Rough",
        enemy_count_scale=1.0,
        enemy_room_cap_bonus=0,
        ambush_probability=0.64,
        boss_guard_probability=0.82,
        pickup_density_scale=1.0,
        damage_pressure_bias=1.0,
        safe_room_bias=1.0,
        target_pressure_min=1.45,
        target_pressure_max=2.35,
    ),
    DIFFICULTY_HARD: DifficultyDefinition(
        difficulty_id=DIFFICULTY_HARD,
        label="Ultra-Violence",
        enemy_count_scale=1.12,
        enemy_room_cap_bonus=0,
        ambush_probability=0.78,
        boss_guard_probability=1.0,
        pickup_density_scale=0.82,
        damage_pressure_bias=1.16,
        safe_room_bias=0.86,
        target_pressure_min=1.9,
        target_pressure_max=2.8,
    ),
}


def get_difficulty_definition(difficulty_id: DifficultyId) -> DifficultyDefinition:
    return DIFFICULTY_PRESETS.get(difficulty_id, DIFFICULTY_PRESETS[DEFAULT_DIFFICULTY_ID])


@dataclass(frozen=True)
class ProgressionAction:
    action_type: ProgressionActionType
    target_id: str
    room_index: int = -1
    amount: int = 0
    note: str = ""


@dataclass(frozen=True)
class ProgressionBeat:
    beat_id: str
    stage_index: int
    room_index: int
    role: RoomRole
    key_type: str | None = None
    label: str = ""
    trigger_id: str | None = None


@dataclass(frozen=True)
class RoomMetadata:
    room_index: int
    stage_index: int
    room_kind: str
    role: RoomRole
    encounter_weight: float
    has_vista: bool = False
    is_return_route: bool = False
    is_secret_room: bool = False
    is_safe_room: bool = False
    shape_family: str = "rectangular"
    spatial_archetype: str = "standard"
    ceiling_height: int = 1
    hazard_type: str = "safe"
    has_bridge: bool = False
    height_variance: int = 0
    geometry_preset_id: str = "standard"
    encounter_template_id: str = "standard"
    combat_profile_id: str = "standard"
    sightline_class: str = "medium"
    mobility_class: str = "standard"


@dataclass(frozen=True)
class WorldSwitchSpawn:
    switch_id: str
    x: float
    y: float
    room_index: int
    label: str
    event_id: str
    actions: tuple[ProgressionAction, ...]
    once: bool = True


@dataclass(frozen=True)
class WorldTriggerSpawn:
    trigger_id: str
    trigger_type: TriggerType
    room_index: int
    x: float
    y: float
    radius: float
    event_id: str
    actions: tuple[ProgressionAction, ...]
    source_id: str | None = None
    once: bool = True


@dataclass(frozen=True)
class SecretSpawn:
    secret_id: str
    secret_type: SecretType
    room_index: int
    x: float
    y: float
    reward_kind: str | None = None
    reward_amount: int = 0
    door_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class EncounterEventPlan:
    event_id: str
    room_index: int
    beat_type: str
    trigger_type: TriggerType
    trigger_ref: str
    target_enemy_ids: tuple[str, ...]
    actions: tuple[ProgressionAction, ...]
    pressure_value: float


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    mandatory_backtrack_count: int
    vista_count: int
    meaningful_loop_count: int
    key_room_event_count: int
    return_shortcut_count: int
    progression_break_count: int
    wide_bypass_count: int
    hazard_room_count: int = 0
    bridge_crossing_count: int = 0
    vertical_variety_score: float = 0.0
    silhouette_variety_score: float = 0.0
    non_linear_path_score: float = 0.0
    vista_height_score: float = 0.0
    key_occlusion_score: float = 0.0
    same_shape_run_length: int = 0


@dataclass(frozen=True)
class QualityScoreReport:
    doom_likeness_score: float
    encounter_pressure_score: float
    mandatory_backtrack_count: int
    vista_count: int
    meaningful_loop_count: int
    key_room_event_count: int
    return_shortcut_count: int
    progression_break_count: int
    wide_bypass_count: int
    same_role_run_length: int
    hazard_room_count: int = 0
    bridge_crossing_count: int = 0
    vertical_variety_score: float = 0.0
    silhouette_variety_score: float = 0.0
    non_linear_path_score: float = 0.0
    vista_height_score: float = 0.0
    key_occlusion_score: float = 0.0
    same_shape_run_length: int = 0
    level_identity_score: float = 0.0
    skeleton_reuse_penalty: float = 0.0
    repeated_macro_signature_penalty: float = 0.0


@dataclass(frozen=True)
class MacroRouteNode:
    room_index: int
    stage_index: int
    role_hint: RoomRole
    kind_hint: str
    branch_slot: int = 0
    requires_vista: bool = False


@dataclass(frozen=True)
class MacroRouteEdge:
    edge_id: str
    room_a_index: int
    room_b_index: int
    edge_kind: RouteEdgeKind
    trigger_source: str | None = None
    note: str = ""


@dataclass(frozen=True)
class MacroRoutePlan:
    layout_type: MacroLayoutType
    nodes: tuple[MacroRouteNode, ...]
    edges: tuple[MacroRouteEdge, ...]
    key_room_indices: tuple[int, ...]
    return_room_indices: tuple[int, ...]
    final_room_index: int
    vista_room_indices: tuple[int, ...]


@dataclass(frozen=True)
class LevelSkeletonProfile:
    skeleton_profile_id: LevelSkeletonProfileId
    macro_layout_type: MacroLayoutType
    template_variant: str
    title: str
    template_variants: tuple[str, ...] = ()
    macro_variant_ids: tuple[MacroVariantId, ...] = (MACRO_VARIANT_DEFAULT,)


@dataclass(frozen=True)
class LevelArchetypeDefinition:
    archetype_id: LevelArchetypeId
    label: str
    compatible_skeleton_ids: tuple[LevelSkeletonProfileId, ...]


@dataclass(frozen=True)
class CampaignLevelDefinition:
    level_index: int
    archetype_id: LevelArchetypeId
    skeleton_profile_id: LevelSkeletonProfileId
    macro_variant_id: MacroVariantId
    spatial_profile_id: SpatialProfileId
    encounter_style_id: EncounterStyleId
    theme_modifier_id: ThemeModifierId
    level_modifier_id: LevelModifierId
    encounter_escalation_tier: int
    title: str
    subtitle: str
    flavor_line: str = ""
    sequencing_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignLevelBlueprint:
    level_index: int
    archetype_ids: tuple[LevelArchetypeId, ...]
    skeleton_profile_ids: tuple[LevelSkeletonProfileId, ...]
    macro_variant_ids: tuple[MacroVariantId, ...]
    spatial_profile_ids: tuple[SpatialProfileId, ...]
    encounter_style_ids: tuple[EncounterStyleId, ...]
    theme_modifier_ids: tuple[ThemeModifierId, ...]
    level_modifier_ids: tuple[LevelModifierId, ...]
    encounter_escalation_tier: int
    title: str
    subtitle: str
    flavor_line: str = ""
    sequencing_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class LevelGenerationRequest:
    run_seed: int
    per_level_seed: int
    difficulty_id: DifficultyId
    level_index: int
    total_level_count: int
    level_archetype_id: LevelArchetypeId
    skeleton_profile_id: LevelSkeletonProfileId
    macro_variant_id: MacroVariantId
    spatial_profile_id: SpatialProfileId
    encounter_style_id: EncounterStyleId
    theme_modifier_id: ThemeModifierId
    level_modifier_id: LevelModifierId
    encounter_escalation_tier: int
    level_title: str
    level_subtitle: str
    flavor_line: str = ""
    sequencing_tags: tuple[str, ...] = ()
    validation_probe: bool = False


@dataclass
class RunState:
    run_seed: int
    difficulty_id: DifficultyId
    current_level_index: int
    total_level_count: int
    completed_levels: list[int] = field(default_factory=list)
    current_level_seed: int = 0
    campaign_levels: tuple[CampaignLevelDefinition, ...] = ()


@dataclass(frozen=True)
class SequenceValidationReport:
    sequence_diversity_score: float
    skeleton_reuse_penalty: float
    repeated_macro_signature_penalty: float
    level_identity_scores: tuple[float, ...]
    repeated_signatures: tuple[str, ...] = ()


SKELETON_PROFILES: dict[LevelSkeletonProfileId, LevelSkeletonProfile] = {
    SKELETON_INTRO_HUB_SPOKES: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_INTRO_HUB_SPOKES,
        macro_layout_type=MACRO_LAYOUT_HUB_SPOKE,
        template_variant="spine:balanced:direct:base",
        title="Intro Hub Spokes",
        template_variants=(
            "spine:balanced:direct:base",
            "staggered:tight:dogleg:mirror_x",
            "pockets:wide:dogleg:mirror_y",
        ),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_BRANCHY, MACRO_VARIANT_CROSS_LINK),
    ),
    SKELETON_DOUBLE_RING: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_DOUBLE_RING,
        macro_layout_type=MACRO_LAYOUT_DOUBLE_LOOP,
        template_variant="pockets:wide:dogleg:base",
        title="Double Ring Circulation",
        template_variants=(
            "pockets:wide:dogleg:base",
            "spine:balanced:direct:mirror_x",
            "staggered:balanced:dogleg:mirror_y",
        ),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_CROSS_LINK, MACRO_VARIANT_COLLAPSE),
    ),
    SKELETON_SPLIT_FORK: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_SPLIT_FORK,
        macro_layout_type=MACRO_LAYOUT_FORK_RETURN,
        template_variant="staggered:balanced:dogleg:mirror_x",
        title="Split Fork Reconverge",
        template_variants=(
            "staggered:balanced:dogleg:mirror_x",
            "spine:tight:direct:base",
            "pockets:wide:dogleg:mirror_y",
        ),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_BRANCHY, MACRO_VARIANT_PINCER),
    ),
    SKELETON_PERIMETER_PUSH: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_PERIMETER_PUSH,
        macro_layout_type=MACRO_LAYOUT_LOOP_SPOKE,
        template_variant="perimeter:wide:perimeter:base",
        title="Perimeter Inward Push",
        template_variants=(
            "perimeter:wide:perimeter:base",
            "staggered:balanced:dogleg:mirror_x",
            "pockets:tight:direct:mirror_y",
        ),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_COLLAPSE, MACRO_VARIANT_CROSS_LINK),
    ),
    SKELETON_TWO_HUB_FINALE: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_TWO_HUB_FINALE,
        macro_layout_type=MACRO_LAYOUT_TWO_HUB,
        template_variant="twinhub:wide:twohub:base",
        title="Two Hub Finale",
        template_variants=(
            "twinhub:wide:twohub:base",
            "twinhub:balanced:dogleg:mirror_x",
            "twinhub:balanced:direct:mirror_y",
        ),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_PINCER, MACRO_VARIANT_COLLAPSE),
    ),
}


ARCHETYPE_DEFINITIONS: dict[LevelArchetypeId, LevelArchetypeDefinition] = {
    ARCHETYPE_TECH_BASE: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_TECH_BASE,
        label="Tech Base",
        compatible_skeleton_ids=(SKELETON_INTRO_HUB_SPOKES, SKELETON_DOUBLE_RING, SKELETON_SPLIT_FORK),
    ),
    ARCHETYPE_RELAY_STATION: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_RELAY_STATION,
        label="Relay Station",
        compatible_skeleton_ids=(SKELETON_DOUBLE_RING, SKELETON_PERIMETER_PUSH, SKELETON_INTRO_HUB_SPOKES),
    ),
    ARCHETYPE_WASTE_PLANT: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_WASTE_PLANT,
        label="Waste Plant",
        compatible_skeleton_ids=(SKELETON_SPLIT_FORK, SKELETON_PERIMETER_PUSH, SKELETON_DOUBLE_RING),
    ),
    ARCHETYPE_OUTER_RING: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_OUTER_RING,
        label="Outer Ring",
        compatible_skeleton_ids=(SKELETON_PERIMETER_PUSH, SKELETON_DOUBLE_RING, SKELETON_TWO_HUB_FINALE),
    ),
    ARCHETYPE_SHRINE_FORTRESS: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_SHRINE_FORTRESS,
        label="Shrine Fortress",
        compatible_skeleton_ids=(SKELETON_TWO_HUB_FINALE, SKELETON_SPLIT_FORK, SKELETON_PERIMETER_PUSH),
    ),
}


CAMPAIGN_LEVEL_BLUEPRINTS: tuple[CampaignLevelBlueprint, ...] = (
    CampaignLevelBlueprint(
        level_index=1,
        archetype_ids=(ARCHETYPE_TECH_BASE, ARCHETYPE_RELAY_STATION),
        skeleton_profile_ids=(SKELETON_INTRO_HUB_SPOKES, SKELETON_DOUBLE_RING),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_BRANCHY),
        spatial_profile_ids=(SPATIAL_PROFILE_BALANCED, SPATIAL_PROFILE_TIGHT),
        encounter_style_ids=(ENCOUNTER_STYLE_STANDARD, ENCOUNTER_STYLE_HUNTER),
        theme_modifier_ids=(THEME_MODIFIER_DEFAULT, THEME_MODIFIER_POWER_FAILURE),
        level_modifier_ids=(LEVEL_MODIFIER_STANDARD, LEVEL_MODIFIER_VISTA_DOMINANT),
        encounter_escalation_tier=0,
        title="Tech Base",
        subtitle="Bootstrap Access",
        flavor_line="Readable hub and clean key progression.",
        sequencing_tags=("intro", "readable", "hub"),
    ),
    CampaignLevelBlueprint(
        level_index=2,
        archetype_ids=(ARCHETYPE_RELAY_STATION, ARCHETYPE_TECH_BASE, ARCHETYPE_WASTE_PLANT),
        skeleton_profile_ids=(SKELETON_DOUBLE_RING, SKELETON_INTRO_HUB_SPOKES, SKELETON_PERIMETER_PUSH),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_CROSS_LINK, MACRO_VARIANT_BRANCHY),
        spatial_profile_ids=(SPATIAL_PROFILE_BALANCED, SPATIAL_PROFILE_EXPANSIVE),
        encounter_style_ids=(ENCOUNTER_STYLE_STANDARD, ENCOUNTER_STYLE_PINCER),
        theme_modifier_ids=(THEME_MODIFIER_DEFAULT, THEME_MODIFIER_POWER_FAILURE, THEME_MODIFIER_SIEGE),
        level_modifier_ids=(LEVEL_MODIFIER_STANDARD, LEVEL_MODIFIER_SHORTCUT_SURGE),
        encounter_escalation_tier=1,
        title="Relay Station",
        subtitle="Double Ring Sweep",
        flavor_line="Inner and outer circulation routes stay hot.",
        sequencing_tags=("mid", "circulation", "loop"),
    ),
    CampaignLevelBlueprint(
        level_index=3,
        archetype_ids=(ARCHETYPE_WASTE_PLANT, ARCHETYPE_RELAY_STATION, ARCHETYPE_OUTER_RING),
        skeleton_profile_ids=(SKELETON_SPLIT_FORK, SKELETON_PERIMETER_PUSH, SKELETON_DOUBLE_RING),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_BRANCHY, MACRO_VARIANT_COLLAPSE),
        spatial_profile_ids=(SPATIAL_PROFILE_VERTICAL, SPATIAL_PROFILE_BALANCED),
        encounter_style_ids=(ENCOUNTER_STYLE_HOLDOUT, ENCOUNTER_STYLE_HUNTER),
        theme_modifier_ids=(THEME_MODIFIER_CORROSION, THEME_MODIFIER_DEFAULT),
        level_modifier_ids=(LEVEL_MODIFIER_BACKTRACK_PRESSURE, LEVEL_MODIFIER_SHORTCUT_SURGE),
        encounter_escalation_tier=2,
        title="Waste Plant",
        subtitle="Forked Pressure",
        flavor_line="Switch events reroute the return path.",
        sequencing_tags=("mid", "hazard", "fork"),
    ),
    CampaignLevelBlueprint(
        level_index=4,
        archetype_ids=(ARCHETYPE_OUTER_RING, ARCHETYPE_SHRINE_FORTRESS, ARCHETYPE_WASTE_PLANT),
        skeleton_profile_ids=(SKELETON_PERIMETER_PUSH, SKELETON_DOUBLE_RING, SKELETON_TWO_HUB_FINALE),
        macro_variant_ids=(MACRO_VARIANT_COLLAPSE, MACRO_VARIANT_CROSS_LINK, MACRO_VARIANT_PINCER),
        spatial_profile_ids=(SPATIAL_PROFILE_EXPANSIVE, SPATIAL_PROFILE_VERTICAL),
        encounter_style_ids=(ENCOUNTER_STYLE_PINCER, ENCOUNTER_STYLE_HOLDOUT),
        theme_modifier_ids=(THEME_MODIFIER_SIEGE, THEME_MODIFIER_CORROSION),
        level_modifier_ids=(LEVEL_MODIFIER_LOCKDOWN, LEVEL_MODIFIER_BACKTRACK_PRESSURE),
        encounter_escalation_tier=3,
        title="Outer Ring",
        subtitle="Perimeter Collapse",
        flavor_line="The perimeter burns as the route folds inward.",
        sequencing_tags=("late", "perimeter", "collapse"),
    ),
    CampaignLevelBlueprint(
        level_index=5,
        archetype_ids=(ARCHETYPE_SHRINE_FORTRESS, ARCHETYPE_OUTER_RING),
        skeleton_profile_ids=(SKELETON_TWO_HUB_FINALE, SKELETON_SPLIT_FORK, SKELETON_PERIMETER_PUSH),
        macro_variant_ids=(MACRO_VARIANT_DEFAULT, MACRO_VARIANT_PINCER, MACRO_VARIANT_COLLAPSE),
        spatial_profile_ids=(SPATIAL_PROFILE_VERTICAL, SPATIAL_PROFILE_EXPANSIVE),
        encounter_style_ids=(ENCOUNTER_STYLE_HOLDOUT, ENCOUNTER_STYLE_PINCER),
        theme_modifier_ids=(THEME_MODIFIER_RITUAL, THEME_MODIFIER_SIEGE),
        level_modifier_ids=(LEVEL_MODIFIER_LOCKDOWN, LEVEL_MODIFIER_VISTA_DOMINANT),
        encounter_escalation_tier=4,
        title="Shrine Fortress",
        subtitle="Final Convergence",
        flavor_line="Twin hubs feed the last gate and the final arena.",
        sequencing_tags=("finale", "convergence", "high_pressure"),
    ),
)


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:15], 16) % 999_999_937


def get_skeleton_profile(skeleton_profile_id: LevelSkeletonProfileId) -> LevelSkeletonProfile:
    return SKELETON_PROFILES[skeleton_profile_id]


def get_archetype_definition(archetype_id: LevelArchetypeId) -> LevelArchetypeDefinition:
    return ARCHETYPE_DEFINITIONS[archetype_id]


def build_macro_signature(
    *,
    skeleton_profile_id: str,
    macro_layout_type: str,
    room_metadata: tuple[RoomMetadata, ...],
    route_plan: MacroRoutePlan,
) -> str:
    role_signature = ",".join(room.role for room in room_metadata)
    stage_signature = ",".join(str(room.stage_index) for room in room_metadata)
    edge_signature = ",".join(edge.edge_kind for edge in route_plan.edges)
    geometry_signature = ",".join(room.geometry_preset_id for room in room_metadata)
    encounter_signature = ",".join(room.encounter_template_id for room in room_metadata)
    return "|".join(
        (
            skeleton_profile_id,
            macro_layout_type,
            role_signature,
            stage_signature,
            edge_signature,
            geometry_signature,
            encounter_signature,
            f"loops={len([edge for edge in route_plan.edges if edge.edge_kind == EDGE_LOOP])}",
            f"vistas={len(route_plan.vista_room_indices)}",
            f"returns={len(route_plan.return_room_indices)}",
        )
    )


def calculate_level_identity_score(
    *,
    route_plan: MacroRoutePlan,
    room_metadata: tuple[RoomMetadata, ...],
) -> float:
    unique_roles = len({room.role for room in room_metadata})
    unique_shapes = len({room.shape_family for room in room_metadata})
    unique_archetypes = len({room.spatial_archetype for room in room_metadata})
    unique_geometry_presets = len({room.geometry_preset_id for room in room_metadata})
    unique_encounter_templates = len({room.encounter_template_id for room in room_metadata})
    loop_count = len([edge for edge in route_plan.edges if edge.edge_kind == EDGE_LOOP])
    shortcut_count = len([edge for edge in route_plan.edges if edge.edge_kind == EDGE_SHORTCUT])
    score = (
        unique_roles * 0.32
        + unique_shapes * 0.18
        + unique_archetypes * 0.16
        + unique_geometry_presets * 0.24
        + unique_encounter_templates * 0.21
        + loop_count * 0.45
        + shortcut_count * 0.34
        + len(route_plan.vista_room_indices) * 0.2
        + len(route_plan.return_room_indices) * 0.24
    )
    return round(score, 3)


def build_playfeel_signature(
    *,
    macro_variant_id: str | None,
    room_metadata: tuple[RoomMetadata, ...],
) -> tuple[str | None, str, str, str]:
    geometry_counts: dict[str, int] = {}
    encounter_counts: dict[str, int] = {}
    combat_counts: dict[str, int] = {}
    mobility_counts: dict[str, int] = {}
    for room in room_metadata:
        geometry_counts[room.geometry_preset_id] = geometry_counts.get(room.geometry_preset_id, 0) + 1
        encounter_counts[room.encounter_template_id] = encounter_counts.get(room.encounter_template_id, 0) + 1
        combat_counts[room.combat_profile_id] = combat_counts.get(room.combat_profile_id, 0) + 1
        mobility_counts[room.mobility_class] = mobility_counts.get(room.mobility_class, 0) + 1

    def dominant(counts: dict[str, int]) -> str:
        if not counts:
            return "none"
        return sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))[0][0]

    return (
        macro_variant_id,
        dominant(geometry_counts),
        dominant(encounter_counts),
        dominant(combat_counts) + ":" + dominant(mobility_counts),
    )


def build_request_playfeel_signature(level_definition: CampaignLevelDefinition) -> tuple[str, str, str, str]:
    return (
        level_definition.skeleton_profile_id,
        level_definition.macro_variant_id,
        level_definition.encounter_style_id,
        f"{level_definition.spatial_profile_id}:{level_definition.level_modifier_id}",
    )


class CampaignSequenceDirector:
    def __init__(self, campaign_blueprints: tuple[CampaignLevelBlueprint, ...] | None = None) -> None:
        self.campaign_blueprints = campaign_blueprints or CAMPAIGN_LEVEL_BLUEPRINTS
        self._compatibility_cache: dict[tuple[object, ...], bool] = {}
        self._compatibility_cache_dirty = False
        self._candidate_search_limits = {
            "archetype": 2,
            "skeleton": 2,
            "macro": 2,
            "spatial": 2,
            "encounter": 2,
            "theme": 1,
            "level_modifier": 2,
        }
        self._load_compatibility_cache()

    @property
    def total_level_count(self) -> int:
        return len(self.campaign_blueprints)

    def build_run_state(self, difficulty_id: DifficultyId, run_seed: int) -> RunState:
        resolved_levels: list[CampaignLevelDefinition] = []
        for blueprint in self.campaign_blueprints:
            resolved_levels.append(
                self.resolve_level_definition(
                    run_seed,
                    blueprint.level_index,
                    tuple(resolved_levels),
                )
            )
        self._save_compatibility_cache()
        first_level_definition = resolved_levels[0]
        first_level_seed = self.derive_level_seed(run_seed, first_level_definition)
        return RunState(
            run_seed=run_seed,
            difficulty_id=difficulty_id,
            current_level_index=1,
            total_level_count=self.total_level_count,
            completed_levels=[],
            current_level_seed=first_level_seed,
            campaign_levels=tuple(resolved_levels),
        )

    def get_level_blueprint(self, level_index: int) -> CampaignLevelBlueprint:
        for blueprint in self.campaign_blueprints:
            if blueprint.level_index == level_index:
                return blueprint
        raise IndexError(f"Unknown campaign level index: {level_index}")

    def _pick_distinct_option(
        self,
        *,
        run_seed: int,
        level_index: int,
        label: str,
        options: tuple[str, ...],
        recent_values: tuple[str, ...],
    ) -> str:
        ranked = []
        for option in options:
            repeat_penalty = 0
            if recent_values:
                if option == recent_values[-1]:
                    repeat_penalty += 900
                if option in recent_values[-2:]:
                    repeat_penalty += 320
                if option in recent_values[-3:]:
                    repeat_penalty += 120
            entropy = _stable_seed("resolve-option", run_seed, level_index, label, option) % 1000
            ranked.append((repeat_penalty + entropy, option))
        ranked.sort(key=lambda entry: entry[0])
        return ranked[0][1]

    def _cache_key_tuple(
        self,
        *,
        run_seed: int,
        level_definition: CampaignLevelDefinition,
    ) -> tuple[str, ...]:
        return (
            str(COMPATIBILITY_CACHE_VERSION),
            str(run_seed),
            str(level_definition.level_index),
            level_definition.archetype_id,
            level_definition.skeleton_profile_id,
            level_definition.macro_variant_id,
            level_definition.spatial_profile_id,
            level_definition.encounter_style_id,
            level_definition.theme_modifier_id,
            level_definition.level_modifier_id,
        )

    def _cache_key_string(self, cache_key: tuple[object, ...]) -> str:
        return "|".join(str(part) for part in cache_key)

    def _load_compatibility_cache(self) -> None:
        try:
            if not COMPATIBILITY_CACHE_PATH.exists():
                return
            payload = json.loads(COMPATIBILITY_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("version") != COMPATIBILITY_CACHE_VERSION:
            return
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return
        for raw_key, compatible in entries.items():
            if not isinstance(raw_key, str) or not isinstance(compatible, bool):
                continue
            self._compatibility_cache[tuple(raw_key.split("|"))] = compatible

    def _save_compatibility_cache(self) -> None:
        if not self._compatibility_cache_dirty:
            return
        serialized = {
            self._cache_key_string(cache_key): compatible
            for cache_key, compatible in self._compatibility_cache.items()
        }
        payload = {
            "version": COMPATIBILITY_CACHE_VERSION,
            "entries": serialized,
        }
        try:
            COMPATIBILITY_CACHE_PATH.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            return
        self._compatibility_cache_dirty = False

    def _ranked_options(
        self,
        *,
        run_seed: int,
        level_index: int,
        label: str,
        options: tuple[str, ...],
        recent_values: tuple[str, ...],
    ) -> tuple[str, ...]:
        ranked = []
        for option in options:
            repeat_penalty = 0
            if recent_values:
                if option == recent_values[-1]:
                    repeat_penalty += 900
                if option in recent_values[-2:]:
                    repeat_penalty += 320
                if option in recent_values[-3:]:
                    repeat_penalty += 120
            entropy = _stable_seed("resolve-option", run_seed, level_index, label, option) % 1000
            ranked.append((repeat_penalty + entropy, option))
        ranked.sort(key=lambda entry: entry[0])
        return tuple(option for _, option in ranked)

    def _candidate_level_definitions(
        self,
        *,
        run_seed: int,
        blueprint: CampaignLevelBlueprint,
        resolved_history: tuple[CampaignLevelDefinition, ...],
    ) -> tuple[CampaignLevelDefinition, ...]:
        recent_playfeel_signatures = tuple(
            build_request_playfeel_signature(level)
            for level in resolved_history
        )
        recent_archetypes = tuple(level.archetype_id for level in resolved_history)
        ranked_archetypes = self._ranked_options(
            run_seed=run_seed,
            level_index=blueprint.level_index,
            label="archetype",
            options=blueprint.archetype_ids,
            recent_values=recent_archetypes,
        )[: self._candidate_search_limits["archetype"]]
        candidates: list[tuple[int, CampaignLevelDefinition]] = []
        for archetype_index, archetype_id in enumerate(ranked_archetypes):
            archetype_definition = get_archetype_definition(archetype_id)
            compatible_skeleton_ids = tuple(
                skeleton_id
                for skeleton_id in blueprint.skeleton_profile_ids
                if skeleton_id in archetype_definition.compatible_skeleton_ids
            ) or archetype_definition.compatible_skeleton_ids
            ranked_skeletons = self._ranked_options(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label=f"skeleton:{archetype_id}",
                options=compatible_skeleton_ids,
                recent_values=tuple(level.skeleton_profile_id for level in resolved_history),
            )[: self._candidate_search_limits["skeleton"]]
            for skeleton_index, skeleton_profile_id in enumerate(ranked_skeletons):
                skeleton_profile = get_skeleton_profile(skeleton_profile_id)
                compatible_macro_variants = tuple(
                    variant_id
                    for variant_id in blueprint.macro_variant_ids
                    if variant_id in skeleton_profile.macro_variant_ids
                ) or skeleton_profile.macro_variant_ids
                ranked_macros = self._ranked_options(
                    run_seed=run_seed,
                    level_index=blueprint.level_index,
                    label=f"macro:{skeleton_profile_id}",
                    options=compatible_macro_variants,
                    recent_values=tuple(level.macro_variant_id for level in resolved_history),
                )[: self._candidate_search_limits["macro"]]
                ranked_spatials = self._ranked_options(
                    run_seed=run_seed,
                    level_index=blueprint.level_index,
                    label="spatial",
                    options=blueprint.spatial_profile_ids,
                    recent_values=tuple(level.spatial_profile_id for level in resolved_history),
                )[: self._candidate_search_limits["spatial"]]
                ranked_encounters = self._ranked_options(
                    run_seed=run_seed,
                    level_index=blueprint.level_index,
                    label="encounter",
                    options=blueprint.encounter_style_ids,
                    recent_values=tuple(level.encounter_style_id for level in resolved_history),
                )[: self._candidate_search_limits["encounter"]]
                ranked_themes = self._ranked_options(
                    run_seed=run_seed,
                    level_index=blueprint.level_index,
                    label="theme",
                    options=blueprint.theme_modifier_ids,
                    recent_values=tuple(level.theme_modifier_id for level in resolved_history),
                )[: self._candidate_search_limits["theme"]]
                ranked_modifiers = self._ranked_options(
                    run_seed=run_seed,
                    level_index=blueprint.level_index,
                    label="level_modifier",
                    options=blueprint.level_modifier_ids,
                    recent_values=tuple(level.level_modifier_id for level in resolved_history),
                )[: self._candidate_search_limits["level_modifier"]]
                for macro_index, macro_variant_id in enumerate(ranked_macros):
                    for spatial_index, spatial_profile_id in enumerate(ranked_spatials):
                        for encounter_index, encounter_style_id in enumerate(ranked_encounters):
                            for theme_index, theme_modifier_id in enumerate(ranked_themes):
                                for modifier_index, level_modifier_id in enumerate(ranked_modifiers):
                                    priority = (
                                        archetype_index * 100000
                                        + skeleton_index * 20000
                                        + macro_index * 4000
                                        + spatial_index * 800
                                        + encounter_index * 160
                                        + theme_index * 32
                                        + modifier_index * 6
                                    )
                                    candidates.append(
                                        (
                                            priority,
                                            CampaignLevelDefinition(
                                                level_index=blueprint.level_index,
                                                archetype_id=archetype_id,
                                                skeleton_profile_id=skeleton_profile_id,
                                                macro_variant_id=macro_variant_id,
                                                spatial_profile_id=spatial_profile_id,
                                                encounter_style_id=encounter_style_id,
                                                theme_modifier_id=theme_modifier_id,
                                                level_modifier_id=level_modifier_id,
                                                encounter_escalation_tier=blueprint.encounter_escalation_tier,
                                                title=blueprint.title,
                                                subtitle=blueprint.subtitle,
                                                flavor_line=blueprint.flavor_line,
                                                sequencing_tags=blueprint.sequencing_tags,
                                            ),
                                        )
                                    )
        scored_candidates: list[tuple[int, CampaignLevelDefinition]] = []
        for base_priority, candidate in candidates:
            playfeel_signature = build_request_playfeel_signature(candidate)
            playfeel_penalty = 0
            if recent_playfeel_signatures:
                if playfeel_signature == recent_playfeel_signatures[-1]:
                    playfeel_penalty += 50000
                if playfeel_signature in recent_playfeel_signatures[-2:]:
                    playfeel_penalty += 12000
                if candidate.macro_variant_id == resolved_history[-1].macro_variant_id:
                    playfeel_penalty += 2400
                if candidate.encounter_style_id == resolved_history[-1].encounter_style_id:
                    playfeel_penalty += 1200
                if candidate.spatial_profile_id == resolved_history[-1].spatial_profile_id:
                    playfeel_penalty += 900
                if candidate.level_modifier_id == resolved_history[-1].level_modifier_id:
                    playfeel_penalty += 600
            scored_candidates.append((base_priority + playfeel_penalty, candidate))
        scored_candidates.sort(key=lambda entry: entry[0])
        return tuple(candidate for _, candidate in scored_candidates)

    def _preferred_level_definition(
        self,
        *,
        run_seed: int,
        blueprint: CampaignLevelBlueprint,
        resolved_history: tuple[CampaignLevelDefinition, ...],
    ) -> CampaignLevelDefinition:
        recent_archetypes = tuple(level.archetype_id for level in resolved_history)
        archetype_id = self._pick_distinct_option(
            run_seed=run_seed,
            level_index=blueprint.level_index,
            label="archetype",
            options=blueprint.archetype_ids,
            recent_values=recent_archetypes,
        )
        archetype_definition = get_archetype_definition(archetype_id)
        compatible_skeleton_ids = tuple(
            skeleton_id
            for skeleton_id in blueprint.skeleton_profile_ids
            if skeleton_id in archetype_definition.compatible_skeleton_ids
        ) or archetype_definition.compatible_skeleton_ids
        skeleton_profile_id = self._pick_distinct_option(
            run_seed=run_seed,
            level_index=blueprint.level_index,
            label="skeleton",
            options=compatible_skeleton_ids,
            recent_values=tuple(level.skeleton_profile_id for level in resolved_history),
        )
        skeleton_profile = get_skeleton_profile(skeleton_profile_id)
        compatible_macro_variants = tuple(
            variant_id
            for variant_id in blueprint.macro_variant_ids
            if variant_id in skeleton_profile.macro_variant_ids
        ) or skeleton_profile.macro_variant_ids
        return CampaignLevelDefinition(
            level_index=blueprint.level_index,
            archetype_id=archetype_id,
            skeleton_profile_id=skeleton_profile_id,
            macro_variant_id=self._pick_distinct_option(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label="macro",
                options=compatible_macro_variants,
                recent_values=tuple(level.macro_variant_id for level in resolved_history),
            ),
            spatial_profile_id=self._pick_distinct_option(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label="spatial",
                options=blueprint.spatial_profile_ids,
                recent_values=tuple(level.spatial_profile_id for level in resolved_history),
            ),
            encounter_style_id=self._pick_distinct_option(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label="encounter",
                options=blueprint.encounter_style_ids,
                recent_values=tuple(level.encounter_style_id for level in resolved_history),
            ),
            theme_modifier_id=self._pick_distinct_option(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label="theme",
                options=blueprint.theme_modifier_ids,
                recent_values=tuple(level.theme_modifier_id for level in resolved_history),
            ),
            level_modifier_id=self._pick_distinct_option(
                run_seed=run_seed,
                level_index=blueprint.level_index,
                label="level_modifier",
                options=blueprint.level_modifier_ids,
                recent_values=tuple(level.level_modifier_id for level in resolved_history),
            ),
            encounter_escalation_tier=blueprint.encounter_escalation_tier,
            title=blueprint.title,
            subtitle=blueprint.subtitle,
            flavor_line=blueprint.flavor_line,
            sequencing_tags=blueprint.sequencing_tags,
        )

    def _is_generator_compatible(self, run_seed: int, level_definition: CampaignLevelDefinition) -> bool:
        cache_key = self._cache_key_tuple(
            run_seed=run_seed,
            level_definition=level_definition,
        )
        cached = self._compatibility_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            from doomgame.mapgen import MapGenerator

            generated = MapGenerator(
                generation_request=LevelGenerationRequest(
                    run_seed=run_seed,
                    per_level_seed=self.derive_level_seed(run_seed, level_definition),
                    difficulty_id=DEFAULT_DIFFICULTY_ID,
                    level_index=level_definition.level_index,
                    total_level_count=self.total_level_count,
                    level_archetype_id=level_definition.archetype_id,
                    skeleton_profile_id=level_definition.skeleton_profile_id,
                    macro_variant_id=level_definition.macro_variant_id,
                    spatial_profile_id=level_definition.spatial_profile_id,
                    encounter_style_id=level_definition.encounter_style_id,
                    theme_modifier_id=level_definition.theme_modifier_id,
                    level_modifier_id=level_definition.level_modifier_id,
                    encounter_escalation_tier=level_definition.encounter_escalation_tier,
                    level_title=level_definition.title,
                    level_subtitle=level_definition.subtitle,
                    flavor_line=level_definition.flavor_line,
                    sequencing_tags=level_definition.sequencing_tags,
                    validation_probe=True,
                )
            ).generate()
            compatible = bool(generated.validation_report.valid)
        except Exception:
            compatible = False
        self._compatibility_cache[cache_key] = compatible
        self._compatibility_cache_dirty = True
        return compatible

    def resolve_level_definition(
        self,
        run_seed: int,
        level_index: int,
        resolved_history: tuple[CampaignLevelDefinition, ...] = (),
    ) -> CampaignLevelDefinition:
        blueprint = self.get_level_blueprint(level_index)
        preferred = self._preferred_level_definition(
            run_seed=run_seed,
            blueprint=blueprint,
            resolved_history=resolved_history,
        )
        if self._is_generator_compatible(run_seed, preferred):
            return preferred
        candidates = self._candidate_level_definitions(
            run_seed=run_seed,
            blueprint=blueprint,
            resolved_history=resolved_history,
        )
        for candidate in candidates:
            if self._is_generator_compatible(run_seed, candidate):
                return candidate
        return preferred

    def get_level_definition(self, run_seed: int, level_index: int) -> CampaignLevelDefinition:
        resolved_history: list[CampaignLevelDefinition] = []
        for current_index in range(1, level_index + 1):
            resolved = self.resolve_level_definition(
                run_seed,
                current_index,
                tuple(resolved_history),
            )
            resolved_history.append(resolved)
        return resolved_history[-1]

    def derive_level_seed(self, run_seed: int, level_definition: CampaignLevelDefinition) -> int:
        return _stable_seed(
            "campaign-level",
            run_seed,
            level_definition.level_index,
            level_definition.archetype_id,
            level_definition.skeleton_profile_id,
            level_definition.macro_variant_id,
            level_definition.spatial_profile_id,
            level_definition.encounter_style_id,
        )

    def build_generation_request(self, run_state: RunState, level_index: int | None = None) -> LevelGenerationRequest:
        resolved_index = level_index if level_index is not None else run_state.current_level_index
        if run_state.campaign_levels and 1 <= resolved_index <= len(run_state.campaign_levels):
            level_definition = run_state.campaign_levels[resolved_index - 1]
        else:
            level_definition = self.get_level_definition(run_state.run_seed, resolved_index)
        return LevelGenerationRequest(
            run_seed=run_state.run_seed,
            per_level_seed=self.derive_level_seed(run_state.run_seed, level_definition),
            difficulty_id=run_state.difficulty_id,
            level_index=resolved_index,
            total_level_count=run_state.total_level_count,
            level_archetype_id=level_definition.archetype_id,
            skeleton_profile_id=level_definition.skeleton_profile_id,
            macro_variant_id=level_definition.macro_variant_id,
            spatial_profile_id=level_definition.spatial_profile_id,
            encounter_style_id=level_definition.encounter_style_id,
            theme_modifier_id=level_definition.theme_modifier_id,
            level_modifier_id=level_definition.level_modifier_id,
            encounter_escalation_tier=level_definition.encounter_escalation_tier,
            level_title=level_definition.title,
            level_subtitle=level_definition.subtitle,
            flavor_line=level_definition.flavor_line,
            sequencing_tags=level_definition.sequencing_tags,
            validation_probe=False,
        )

    def evaluate_sequence(self, generated_levels: tuple[object, ...]) -> SequenceValidationReport:
        skeleton_reuse_penalty = 0.0
        repeated_macro_signature_penalty = 0.0
        repeated_playfeel_penalty = 0.0
        repeated_signatures: list[str] = []
        identity_scores: list[float] = []
        previous_skeleton: str | None = None
        previous_signature: str | None = None
        previous_playfeel_signature: tuple[str | None, str, str, str] | None = None
        for generated in generated_levels:
            identity_score = calculate_level_identity_score(
                route_plan=generated.route_plan,
                room_metadata=generated.room_metadata,
            )
            identity_scores.append(identity_score)
            if previous_skeleton == generated.skeleton_profile_id:
                skeleton_reuse_penalty += 1.0
            if previous_signature == generated.macro_signature:
                repeated_macro_signature_penalty += 1.0
                repeated_signatures.append(generated.macro_signature)
            current_playfeel_signature = build_playfeel_signature(
                macro_variant_id=getattr(generated, "macro_variant_id", None),
                room_metadata=generated.room_metadata,
            )
            if previous_playfeel_signature == current_playfeel_signature:
                repeated_playfeel_penalty += 0.75
            previous_skeleton = generated.skeleton_profile_id
            previous_signature = generated.macro_signature
            previous_playfeel_signature = current_playfeel_signature

        average_identity = sum(identity_scores) / max(1, len(identity_scores))
        diversity_score = max(
            0.0,
            round(
                average_identity
                - skeleton_reuse_penalty * 0.9
                - repeated_macro_signature_penalty * 1.2
                - repeated_playfeel_penalty,
                3,
            ),
        )
        return SequenceValidationReport(
            sequence_diversity_score=diversity_score,
            skeleton_reuse_penalty=round(skeleton_reuse_penalty, 3),
            repeated_macro_signature_penalty=round(repeated_macro_signature_penalty, 3),
            level_identity_scores=tuple(identity_scores),
            repeated_signatures=tuple(repeated_signatures),
        )
