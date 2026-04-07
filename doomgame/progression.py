from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

DifficultyId = str
MacroLayoutType = str
RoomRole = str
ProgressionActionType = str
SecretType = str
TriggerType = str
RouteEdgeKind = str
LevelArchetypeId = str
LevelSkeletonProfileId = str

DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"
DIFFICULTY_IDS: tuple[DifficultyId, ...] = (
    DIFFICULTY_EASY,
    DIFFICULTY_MEDIUM,
    DIFFICULTY_HARD,
)
DEFAULT_DIFFICULTY_ID: DifficultyId = DIFFICULTY_MEDIUM

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
    encounter_escalation_tier: int
    title: str
    subtitle: str
    flavor_line: str = ""


@dataclass(frozen=True)
class LevelGenerationRequest:
    run_seed: int
    per_level_seed: int
    difficulty_id: DifficultyId
    level_index: int
    total_level_count: int
    level_archetype_id: LevelArchetypeId
    skeleton_profile_id: LevelSkeletonProfileId
    encounter_escalation_tier: int
    level_title: str
    level_subtitle: str
    flavor_line: str = ""


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
    ),
    SKELETON_DOUBLE_RING: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_DOUBLE_RING,
        macro_layout_type=MACRO_LAYOUT_DOUBLE_LOOP,
        template_variant="pockets:wide:dogleg:base",
        title="Double Ring Circulation",
    ),
    SKELETON_SPLIT_FORK: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_SPLIT_FORK,
        macro_layout_type=MACRO_LAYOUT_FORK_RETURN,
        template_variant="staggered:balanced:dogleg:mirror_x",
        title="Split Fork Reconverge",
    ),
    SKELETON_PERIMETER_PUSH: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_PERIMETER_PUSH,
        macro_layout_type=MACRO_LAYOUT_LOOP_SPOKE,
        template_variant="perimeter:wide:perimeter:base",
        title="Perimeter Inward Push",
    ),
    SKELETON_TWO_HUB_FINALE: LevelSkeletonProfile(
        skeleton_profile_id=SKELETON_TWO_HUB_FINALE,
        macro_layout_type=MACRO_LAYOUT_TWO_HUB,
        template_variant="twinhub:wide:twohub:base",
        title="Two Hub Finale",
    ),
}


ARCHETYPE_DEFINITIONS: dict[LevelArchetypeId, LevelArchetypeDefinition] = {
    ARCHETYPE_TECH_BASE: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_TECH_BASE,
        label="Tech Base",
        compatible_skeleton_ids=(SKELETON_INTRO_HUB_SPOKES,),
    ),
    ARCHETYPE_RELAY_STATION: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_RELAY_STATION,
        label="Relay Station",
        compatible_skeleton_ids=(SKELETON_DOUBLE_RING,),
    ),
    ARCHETYPE_WASTE_PLANT: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_WASTE_PLANT,
        label="Waste Plant",
        compatible_skeleton_ids=(SKELETON_SPLIT_FORK,),
    ),
    ARCHETYPE_OUTER_RING: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_OUTER_RING,
        label="Outer Ring",
        compatible_skeleton_ids=(SKELETON_PERIMETER_PUSH,),
    ),
    ARCHETYPE_SHRINE_FORTRESS: LevelArchetypeDefinition(
        archetype_id=ARCHETYPE_SHRINE_FORTRESS,
        label="Shrine Fortress",
        compatible_skeleton_ids=(SKELETON_TWO_HUB_FINALE,),
    ),
}


CAMPAIGN_LEVEL_SEQUENCE: tuple[CampaignLevelDefinition, ...] = (
    CampaignLevelDefinition(
        level_index=1,
        archetype_id=ARCHETYPE_TECH_BASE,
        skeleton_profile_id=SKELETON_INTRO_HUB_SPOKES,
        encounter_escalation_tier=0,
        title="Tech Base",
        subtitle="Bootstrap Access",
        flavor_line="Readable hub and clean key progression.",
    ),
    CampaignLevelDefinition(
        level_index=2,
        archetype_id=ARCHETYPE_RELAY_STATION,
        skeleton_profile_id=SKELETON_DOUBLE_RING,
        encounter_escalation_tier=1,
        title="Relay Station",
        subtitle="Double Ring Sweep",
        flavor_line="Inner and outer circulation routes stay hot.",
    ),
    CampaignLevelDefinition(
        level_index=3,
        archetype_id=ARCHETYPE_WASTE_PLANT,
        skeleton_profile_id=SKELETON_SPLIT_FORK,
        encounter_escalation_tier=2,
        title="Waste Plant",
        subtitle="Forked Pressure",
        flavor_line="Switch events reroute the return path.",
    ),
    CampaignLevelDefinition(
        level_index=4,
        archetype_id=ARCHETYPE_OUTER_RING,
        skeleton_profile_id=SKELETON_PERIMETER_PUSH,
        encounter_escalation_tier=3,
        title="Outer Ring",
        subtitle="Perimeter Collapse",
        flavor_line="The perimeter burns as the route folds inward.",
    ),
    CampaignLevelDefinition(
        level_index=5,
        archetype_id=ARCHETYPE_SHRINE_FORTRESS,
        skeleton_profile_id=SKELETON_TWO_HUB_FINALE,
        encounter_escalation_tier=4,
        title="Shrine Fortress",
        subtitle="Final Convergence",
        flavor_line="Twin hubs feed the last gate and the final arena.",
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
    return "|".join(
        (
            skeleton_profile_id,
            macro_layout_type,
            role_signature,
            stage_signature,
            edge_signature,
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
    loop_count = len([edge for edge in route_plan.edges if edge.edge_kind == EDGE_LOOP])
    shortcut_count = len([edge for edge in route_plan.edges if edge.edge_kind == EDGE_SHORTCUT])
    score = (
        unique_roles * 0.32
        + unique_shapes * 0.18
        + unique_archetypes * 0.16
        + loop_count * 0.45
        + shortcut_count * 0.34
        + len(route_plan.vista_room_indices) * 0.2
        + len(route_plan.return_room_indices) * 0.24
    )
    return round(score, 3)


class CampaignSequenceDirector:
    def __init__(self, campaign_levels: tuple[CampaignLevelDefinition, ...] | None = None) -> None:
        self.campaign_levels = campaign_levels or CAMPAIGN_LEVEL_SEQUENCE

    @property
    def total_level_count(self) -> int:
        return len(self.campaign_levels)

    def build_run_state(self, difficulty_id: DifficultyId, run_seed: int) -> RunState:
        first_level_seed = self.derive_level_seed(run_seed, self.campaign_levels[0])
        return RunState(
            run_seed=run_seed,
            difficulty_id=difficulty_id,
            current_level_index=1,
            total_level_count=self.total_level_count,
            completed_levels=[],
            current_level_seed=first_level_seed,
            campaign_levels=self.campaign_levels,
        )

    def get_level_definition(self, level_index: int) -> CampaignLevelDefinition:
        for level in self.campaign_levels:
            if level.level_index == level_index:
                return level
        raise IndexError(f"Unknown campaign level index: {level_index}")

    def derive_level_seed(self, run_seed: int, level_definition: CampaignLevelDefinition) -> int:
        return _stable_seed(
            "campaign-level",
            run_seed,
            level_definition.level_index,
            level_definition.archetype_id,
            level_definition.skeleton_profile_id,
        )

    def build_generation_request(self, run_state: RunState, level_index: int | None = None) -> LevelGenerationRequest:
        resolved_index = level_index if level_index is not None else run_state.current_level_index
        level_definition = self.get_level_definition(resolved_index)
        return LevelGenerationRequest(
            run_seed=run_state.run_seed,
            per_level_seed=self.derive_level_seed(run_state.run_seed, level_definition),
            difficulty_id=run_state.difficulty_id,
            level_index=resolved_index,
            total_level_count=run_state.total_level_count,
            level_archetype_id=level_definition.archetype_id,
            skeleton_profile_id=level_definition.skeleton_profile_id,
            encounter_escalation_tier=level_definition.encounter_escalation_tier,
            level_title=level_definition.title,
            level_subtitle=level_definition.subtitle,
            flavor_line=level_definition.flavor_line,
        )

    def evaluate_sequence(self, generated_levels: tuple[object, ...]) -> SequenceValidationReport:
        skeleton_reuse_penalty = 0.0
        repeated_macro_signature_penalty = 0.0
        repeated_signatures: list[str] = []
        identity_scores: list[float] = []
        previous_skeleton: str | None = None
        previous_signature: str | None = None
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
            previous_skeleton = generated.skeleton_profile_id
            previous_signature = generated.macro_signature

        average_identity = sum(identity_scores) / max(1, len(identity_scores))
        diversity_score = max(
            0.0,
            round(average_identity - skeleton_reuse_penalty * 0.9 - repeated_macro_signature_penalty * 1.2, 3),
        )
        return SequenceValidationReport(
            sequence_diversity_score=diversity_score,
            skeleton_reuse_penalty=round(skeleton_reuse_penalty, 3),
            repeated_macro_signature_penalty=round(repeated_macro_signature_penalty, 3),
            level_identity_scores=tuple(identity_scores),
            repeated_signatures=tuple(repeated_signatures),
        )
