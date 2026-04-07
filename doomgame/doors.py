from __future__ import annotations

from dataclasses import dataclass

from doomgame import settings

KEY_TYPES = ("blue", "yellow", "red")
DOOR_STATES = ("closed", "opening", "open", "locked")


@dataclass(frozen=True)
class KeyVisual:
    glow_color: tuple[int, int, int]
    world_scale: float
    hover_height: float
    hud_color: tuple[int, int, int]
    sprite_primary: tuple[int, int, int]
    sprite_secondary: tuple[int, int, int]


@dataclass(frozen=True)
class KeyDefinition:
    key_type: str
    display_name: str
    pickup_message: str
    visual: KeyVisual


KEY_DEFINITIONS: dict[str, KeyDefinition] = {
    "blue": KeyDefinition(
        key_type="blue",
        display_name="Blue Key",
        pickup_message="PICKED UP BLUE KEY",
        visual=KeyVisual(
            glow_color=(82, 168, 255),
            world_scale=0.88,
            hover_height=0.36,
            hud_color=(64, 112, 214),
            sprite_primary=(54, 128, 240),
            sprite_secondary=(216, 236, 255),
        ),
    ),
    "yellow": KeyDefinition(
        key_type="yellow",
        display_name="Yellow Key",
        pickup_message="PICKED UP YELLOW KEY",
        visual=KeyVisual(
            glow_color=(255, 218, 94),
            world_scale=0.88,
            hover_height=0.36,
            hud_color=(214, 180, 54),
            sprite_primary=(228, 186, 44),
            sprite_secondary=(255, 242, 190),
        ),
    ),
    "red": KeyDefinition(
        key_type="red",
        display_name="Red Key",
        pickup_message="PICKED UP RED KEY",
        visual=KeyVisual(
            glow_color=(255, 104, 92),
            world_scale=0.88,
            hover_height=0.36,
            hud_color=(180, 38, 34),
            sprite_primary=(198, 48, 44),
            sprite_secondary=(255, 222, 214),
        ),
    ),
}


@dataclass(frozen=True)
class DoorVisual:
    minimap_color: tuple[int, int, int]
    base_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    locked_message: str | None


@dataclass(frozen=True)
class DoorDefinition:
    door_type: str
    required_key_type: str | None
    label: str
    visual: DoorVisual


DOOR_DEFINITIONS: dict[str, DoorDefinition] = {
    "normal": DoorDefinition(
        door_type="normal",
        required_key_type=None,
        label="Door",
        visual=DoorVisual((158, 130, 96), (98, 90, 82), (196, 182, 132), None),
    ),
    "blue_locked": DoorDefinition(
        door_type="blue_locked",
        required_key_type="blue",
        label="Blue Door",
        visual=DoorVisual((64, 112, 214), (62, 78, 112), (82, 168, 255), "BLUE DOOR - KEY REQUIRED"),
    ),
    "yellow_locked": DoorDefinition(
        door_type="yellow_locked",
        required_key_type="yellow",
        label="Yellow Door",
        visual=DoorVisual((214, 180, 54), (118, 96, 44), (252, 220, 92), "YELLOW DOOR - KEY REQUIRED"),
    ),
    "red_locked": DoorDefinition(
        door_type="red_locked",
        required_key_type="red",
        label="Red Door",
        visual=DoorVisual((180, 38, 34), (110, 62, 60), (255, 104, 92), "RED DOOR - KEY REQUIRED"),
    ),
}


def locked_door_type_for_key(key_type: str) -> str:
    return f"{key_type}_locked"


@dataclass(frozen=True)
class DoorSpawn:
    door_id: str
    grid_x: int
    grid_y: int
    orientation: str
    door_type: str
    guard_enemy_id: str | None = None
    required_trigger_id: str | None = None
    locked_message: str | None = None
    secret: bool = False


@dataclass(frozen=True)
class KeySpawn:
    key_id: str
    key_type: str
    x: float
    y: float


@dataclass
class KeyPickup:
    key_id: str
    key_type: str
    x: float
    y: float
    collected: bool = False
    bob_phase: float = 0.0
    scale: float = 1.0

    @property
    def definition(self) -> KeyDefinition:
        return KEY_DEFINITIONS[self.key_type]

    @property
    def sprite_kind(self) -> str:
        return f"{self.key_type}_key"


@dataclass
class WorldDoor:
    door_id: str
    grid_x: int
    grid_y: int
    orientation: str
    door_type: str
    guard_enemy_id: str | None = None
    required_trigger_id: str | None = None
    locked_message: str | None = None
    secret: bool = False
    state: str = "closed"
    open_progress: float = 0.0
    trigger_unlocked: bool = False

    def __post_init__(self) -> None:
        required = self.definition.required_key_type
        if required is not None and self.state == "closed":
            self.state = "locked"
        if self.required_trigger_id is not None and not self.trigger_unlocked:
            self.state = "locked"

    @property
    def definition(self) -> DoorDefinition:
        return DOOR_DEFINITIONS[self.door_type]

    @property
    def is_open(self) -> bool:
        return self.state == "open" or self.open_progress >= 1.0

    @property
    def is_animating(self) -> bool:
        return self.state == "opening"

    @property
    def center(self) -> tuple[float, float]:
        return (self.grid_x + 0.5, self.grid_y + 0.5)

    def current_lift(self) -> float:
        return max(0.0, min(1.0, self.open_progress))

    def blocks_passage(self) -> bool:
        return self.current_lift() < settings.DOOR_PASSABLE_PROGRESS

    def can_open(self, owned_keys: set[str], guard_defeated: bool = True) -> bool:
        if not guard_defeated:
            return False
        if self.required_trigger_id is not None and not self.trigger_unlocked:
            return False
        required = self.definition.required_key_type
        if required is None:
            return True
        return required in owned_keys

    def unlock(self) -> None:
        if self.required_trigger_id is not None:
            self.trigger_unlocked = True
        if self.state == "locked" and (
            self.definition.required_key_type is not None
            or self.required_trigger_id is not None
        ):
            self.state = "closed"

    def begin_open(self) -> bool:
        if self.state == "locked":
            return False
        if self.state in {"opening", "open"}:
            return False
        self.state = "opening"
        return True

    def update(self, delta_time: float) -> None:
        if self.state != "opening":
            return
        self.open_progress = min(1.0, self.open_progress + delta_time * settings.DOOR_OPEN_SPEED)
        if self.open_progress >= 1.0:
            self.state = "open"

    def interaction_distance(self, player_x: float, player_y: float) -> float:
        cx, cy = self.center
        return ((cx - player_x) ** 2 + (cy - player_y) ** 2) ** 0.5
