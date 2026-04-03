from __future__ import annotations

from dataclasses import dataclass

from doomgame import settings


@dataclass(frozen=True)
class PickupVisual:
    sprite_size: tuple[int, int]
    minimap_color: tuple[int, int, int]
    glow_color: tuple[int, int, int]
    hover_height: float
    world_scale: float


@dataclass(frozen=True)
class PickupEffect:
    stat: str
    mode: str
    cap: int
    pickup_name: str

    def apply(self, current: int, amount: int) -> tuple[int, str] | None:
        if self.mode == "add":
            if current >= self.cap:
                return None
            gained = min(amount, self.cap - current)
            if gained <= 0:
                return None
            return current + gained, self._message(gained)

        if self.mode == "set_floor":
            if current >= self.cap:
                return None
            new_value = max(current, min(amount, self.cap))
            if new_value <= current:
                return None
            return new_value, self._message(new_value - current)

        raise ValueError(f"Unsupported pickup effect mode: {self.mode}")

    def _message(self, gained: int) -> str:
        if self.mode == "set_floor":
            return self.pickup_name
        return f"{self.pickup_name} +{gained}"


@dataclass(frozen=True)
class PickupDefinition:
    kind: str
    display_name: str
    default_amount: int
    effect: PickupEffect
    visual: PickupVisual


@dataclass(frozen=True)
class LootTableEntry:
    kind: str
    amount: int
    weight: int


PICKUP_DEFINITIONS: dict[str, PickupDefinition] = {
    "shells": PickupDefinition(
        kind="shells",
        display_name="Shells",
        default_amount=4,
        effect=PickupEffect("ammo", "add", settings.MAX_SHELLS, "PICKED UP SHELLS"),
        visual=PickupVisual((22, 28), (214, 76, 54), (255, 152, 84), 0.34, 0.78),
    ),
    "shell_box": PickupDefinition(
        kind="shell_box",
        display_name="Shell Box",
        default_amount=20,
        effect=PickupEffect("ammo", "add", settings.MAX_SHELLS, "PICKED UP SHELL BOX"),
        visual=PickupVisual((28, 24), (234, 144, 64), (255, 188, 96), 0.36, 0.86),
    ),
    "stimpack": PickupDefinition(
        kind="stimpack",
        display_name="Stimpack",
        default_amount=10,
        effect=PickupEffect("health", "add", settings.MAX_HEALTH, "STIMPACK"),
        visual=PickupVisual((22, 22), (74, 214, 126), (108, 255, 164), 0.33, 0.72),
    ),
    "medkit": PickupDefinition(
        kind="medkit",
        display_name="Medkit",
        default_amount=25,
        effect=PickupEffect("health", "add", settings.MAX_HEALTH, "MEDKIT"),
        visual=PickupVisual((30, 30), (186, 234, 196), (210, 255, 220), 0.36, 0.92),
    ),
    "armor_bonus": PickupDefinition(
        kind="armor_bonus",
        display_name="Armor Bonus",
        default_amount=1,
        effect=PickupEffect("armor", "add", settings.MAX_ARMOR, "ARMOR BONUS"),
        visual=PickupVisual((24, 24), (90, 180, 234), (110, 196, 255), 0.37, 0.72),
    ),
    "green_armor": PickupDefinition(
        kind="green_armor",
        display_name="Green Armor",
        default_amount=100,
        effect=PickupEffect("armor", "set_floor", 100, "GREEN ARMOR"),
        visual=PickupVisual((28, 30), (64, 164, 120), (118, 230, 160), 0.38, 0.94),
    ),
}


ROOM_LOOT_TABLES: dict[str, tuple[LootTableEntry, ...]] = {
    "start": (
        LootTableEntry("shells", 4, 8),
        LootTableEntry("stimpack", 10, 5),
        LootTableEntry("armor_bonus", 1, 2),
    ),
    "storage": (
        LootTableEntry("shells", 4, 12),
        LootTableEntry("shell_box", 20, 7),
        LootTableEntry("armor_bonus", 1, 2),
    ),
    "arena": (
        LootTableEntry("shells", 4, 9),
        LootTableEntry("shell_box", 20, 6),
        LootTableEntry("stimpack", 10, 4),
        LootTableEntry("medkit", 25, 3),
    ),
    "tech": (
        LootTableEntry("stimpack", 10, 5),
        LootTableEntry("armor_bonus", 1, 7),
        LootTableEntry("green_armor", 100, 2),
    ),
    "shrine": (
        LootTableEntry("medkit", 25, 6),
        LootTableEntry("green_armor", 100, 4),
        LootTableEntry("armor_bonus", 1, 5),
        LootTableEntry("shell_box", 20, 2),
    ),
    "cross": (
        LootTableEntry("shells", 4, 7),
        LootTableEntry("stimpack", 10, 5),
        LootTableEntry("armor_bonus", 1, 3),
    ),
}


ROOM_LOOT_COUNTS: dict[str, tuple[int, int]] = {
    "start": (1, 2),
    "storage": (2, 4),
    "arena": (2, 4),
    "tech": (1, 3),
    "shrine": (1, 2),
    "cross": (1, 2),
}


def get_pickup_definition(kind: str) -> PickupDefinition:
    return PICKUP_DEFINITIONS[kind]


def resolve_pickup_amount(kind: str, amount: int | None = None) -> int:
    definition = get_pickup_definition(kind)
    return definition.default_amount if amount is None else amount
