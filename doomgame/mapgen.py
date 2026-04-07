from __future__ import annotations

from dataclasses import dataclass
import math
import random

from doomgame.enemies import EnemySpawn
from doomgame import settings
from doomgame.doors import DoorSpawn, KeySpawn, KEY_TYPES, locked_door_type_for_key
from doomgame.loot import ROOM_LOOT_COUNTS, ROOM_LOOT_TABLES, resolve_pickup_amount

ROOM_KINDS = ("start", "storage", "arena", "tech", "shrine", "cross")


@dataclass(frozen=True)
class Room:
    x: int
    y: int
    width: int
    height: int
    kind: str
    floor_height: int

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
    stair_mask: list[list[int]]
    room_kinds: list[list[int]]
    loot_spawns: list["LootSpawn"]
    enemy_spawns: list[EnemySpawn]
    door_spawns: list[DoorSpawn]
    key_spawns: list[KeySpawn]
    exit_spawn: "ExitSpawn | None"
    spawn: tuple[float, float]
    seed: int


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


class MapGenerator:
    def __init__(
        self,
        width: int = settings.MAP_WIDTH,
        height: int = settings.MAP_HEIGHT,
        seed: int | None = None,
        difficulty_rating: float = 1.0,
    ) -> None:
        self.width = width
        self.height = height
        self.seed = seed if seed is not None else random.randrange(1, 999_999)
        self.rng = random.Random(self.seed)
        self.difficulty_rating = max(settings.ENEMY_DIFFICULTY_MIN, min(settings.ENEMY_DIFFICULTY_MAX, difficulty_rating))

    def generate(self) -> GeneratedMap:
        best_map: GeneratedMap | None = None
        best_locked_count = -1
        for attempt in range(settings.MAPGEN_MAX_ATTEMPTS):
            self.rng = random.Random(self.seed + attempt * 7919)
            generated = self._generate_once()
            if generated is None:
                continue
            locked_count = sum(1 for door in generated.door_spawns if door.door_type != "normal")
            if locked_count > best_locked_count:
                best_map = generated
                best_locked_count = locked_count
            if (
                locked_count == len(KEY_TYPES)
                and len(generated.key_spawns) == len(KEY_TYPES)
                and generated.exit_spawn is not None
                and generated.exit_spawn.required_door_id is not None
            ):
                return generated
        if best_map is not None:
            return best_map
        fallback = self._generate_structured_fallback()
        if fallback is not None:
            return fallback
        raise RuntimeError(f"Unable to generate a valid progression layout for seed {self.seed}")

    def _generate_once(self) -> GeneratedMap | None:
        tiles = [[1 for _ in range(self.width)] for _ in range(self.height)]
        floor_heights = [[0 for _ in range(self.width)] for _ in range(self.height)]
        stair_mask = [[0 for _ in range(self.width)] for _ in range(self.height)]
        room_kinds = [[-1 for _ in range(self.width)] for _ in range(self.height)]
        layout = self._generate_rooms_and_corridors(tiles, floor_heights, stair_mask, room_kinds)
        if layout is None:
            return None
        rooms = list(layout.rooms)
        connections: list[CorridorConnection] = []
        room_stages = layout.progression.room_stages
        for room_index in range(1, len(rooms)):
            path = self._connect_rooms(
                tiles,
                floor_heights,
                stair_mask,
                room_kinds,
                rooms[room_index - 1],
                rooms[room_index],
                widen_chance=0.0,
            )
            connections.append(
                CorridorConnection(
                    index=len(connections),
                    room_a_index=room_index - 1,
                    room_b_index=room_index,
                    path=path,
                    is_main_path=True,
                )
            )
        self._decorate_rooms(tiles, floor_heights, stair_mask, room_kinds, rooms)
        self._add_side_connections(
            tiles,
            floor_heights,
            stair_mask,
            room_kinds,
            rooms,
            connections,
            room_stages,
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
        final_gate = locked_doors[-1]
        final_connection = connections[layout.progression.gate_plans[-1].connection_index]
        exit_spawn = self._generate_exit_spawn(
            tiles,
            stair_mask,
            rooms,
            spawn,
            [(key.x, key.y) for key in key_spawns],
            set(layout.progression.stage_rooms[-1]),
            final_gate.door_id,
            (final_gate.grid_x, final_gate.grid_y),
        )
        if exit_spawn is None:
            return None
        if not self._validate_progression_layout(
            tiles,
            rooms,
            spawn,
            layout.progression,
            locked_doors,
            key_spawns,
            exit_spawn,
        ):
            return None
        boss_guard_plan = self._build_boss_guard_plan(
            rooms,
            connections,
            final_connection,
            final_gate.door_id,
            (final_gate.grid_x, final_gate.grid_y),
        )
        reserved_positions = [(key.x, key.y) for key in key_spawns]
        loot_spawns = self._generate_loot_spawns(tiles, stair_mask, rooms, spawn, reserved_positions)
        enemy_reserved_positions = [*reserved_positions, *( (loot.x, loot.y) for loot in loot_spawns )]
        if exit_spawn is not None:
            enemy_reserved_positions.append((exit_spawn.x, exit_spawn.y))
        enemy_spawns, guard_enemy_id = self._generate_enemy_spawns(
            tiles,
            stair_mask,
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
                )
                for door in door_spawns
            ]

        return GeneratedMap(
            tiles=tiles,
            floor_heights=floor_heights,
            stair_mask=stair_mask,
            room_kinds=room_kinds,
            loot_spawns=loot_spawns,
            enemy_spawns=enemy_spawns,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            spawn=spawn,
            seed=self.seed,
        )

    def _generate_structured_fallback(self) -> GeneratedMap | None:
        self.rng = random.Random(self.seed ^ 0x5F3759DF)
        tiles = [[1 for _ in range(self.width)] for _ in range(self.height)]
        floor_heights = [[0 for _ in range(self.width)] for _ in range(self.height)]
        stair_mask = [[0 for _ in range(self.width)] for _ in range(self.height)]
        room_kinds = [[-1 for _ in range(self.width)] for _ in range(self.height)]

        rooms = [
            Room(2, 5, 6, 6, "start", 0),
            Room(11, 5, 6, 6, "tech", 0),
            Room(20, 5, 6, 6, "shrine", 0),
            Room(20, 14, 8, 8, "arena", 0),
            Room(11, 15, 6, 6, "cross", 0),
            Room(2, 15, 6, 6, "tech", 0),
            Room(2, 25, 7, 7, "shrine", 0),
            Room(22, 24, 9, 9, "arena", 0),
        ]
        for room in rooms:
            self._carve_room(tiles, floor_heights, room_kinds, room)

        progression = self._plan_progression_layout(rooms)
        if progression is None:
            return None

        connections: list[CorridorConnection] = []
        def append_connection(
            room_a_index: int,
            room_b_index: int,
            segments: list[tuple[str, int, int, int]],
            is_main_path: bool,
            door_candidate: tuple[int, int, str] | None = None,
        ) -> None:
            path: list[tuple[int, int]] = []
            for axis, start, end, fixed in segments:
                if axis == "h":
                    path.extend(self._carve_h_corridor(tiles, start, end, fixed, widen_chance=0.0))
                else:
                    path.extend(self._carve_v_corridor(tiles, start, end, fixed, widen_chance=0.0))
            self._assign_path_heights(path, floor_heights, stair_mask, room_kinds)
            connections.append(
                CorridorConnection(
                    index=len(connections),
                    room_a_index=room_a_index,
                    room_b_index=room_b_index,
                    path=path,
                    is_main_path=is_main_path,
                    door_candidate=door_candidate,
                )
            )

        append_connection(0, 1, [("h", 8, 10, 8)], True)
        append_connection(1, 2, [("h", 17, 19, 8)], True)
        append_connection(2, 3, [("v", 11, 13, 23)], True, door_candidate=(23, 12, "horizontal"))
        append_connection(3, 4, [("h", 17, 19, 18)], True)
        append_connection(4, 5, [("h", 8, 10, 18)], True, door_candidate=(9, 18, "vertical"))
        append_connection(5, 6, [("v", 21, 24, 5)], True)
        append_connection(6, 7, [("h", 9, 21, 28)], True, door_candidate=(20, 28, "vertical"))

        self._decorate_rooms(tiles, floor_heights, stair_mask, room_kinds, rooms)
        append_connection(0, 2, [("v", 11, 12, 14), ("h", 8, 19, 12)], False)

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
            rooms,
            spawn,
            connections,
            progression,
        )
        if key_spawns is None:
            return None
        door_spawns = list(locked_doors)
        exit_spawn = self._generate_exit_spawn(
            tiles,
            stair_mask,
            rooms,
            spawn,
            [(key.x, key.y) for key in key_spawns],
            set(progression.stage_rooms[-1]),
            locked_doors[-1].door_id,
            (locked_doors[-1].grid_x, locked_doors[-1].grid_y),
        )
        if exit_spawn is None:
            return None
        if not self._validate_progression_layout(
            tiles,
            rooms,
            spawn,
            progression,
            locked_doors,
            key_spawns,
            exit_spawn,
        ):
            return None

        loot_spawns = self._generate_loot_spawns(
            tiles,
            stair_mask,
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
                )
                for door in door_spawns
            ]

        return GeneratedMap(
            tiles=tiles,
            floor_heights=floor_heights,
            stair_mask=stair_mask,
            room_kinds=room_kinds,
            loot_spawns=loot_spawns,
            enemy_spawns=enemy_spawns,
            door_spawns=door_spawns,
            key_spawns=key_spawns,
            exit_spawn=exit_spawn,
            spawn=spawn,
            seed=self.seed,
        )

    def _generate_rooms_and_corridors(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
    ) -> LayoutPlan | None:
        rooms: list[Room] = []
        target_rooms = settings.MIN_PROGRESSION_ROOMS

        for _ in range(settings.MAX_ROOMS * 6):
            room = self._random_room(len(rooms))
            if any(room.intersects(other) for other in rooms):
                continue
            self._carve_room(tiles, floor_heights, room_kinds, room)
            rooms.append(room)
            if len(rooms) >= target_rooms:
                break

        if len(rooms) < settings.MIN_PROGRESSION_ROOMS:
            return None

        progression = self._plan_progression_layout(rooms)
        if progression is None:
            return None
        return LayoutPlan(rooms=tuple(rooms), progression=progression)

    def _plan_progression_layout(self, rooms: list[Room]) -> ProgressionLayout | None:
        room_count = len(rooms)
        if room_count < settings.MIN_PROGRESSION_ROOMS:
            return None

        candidate_boundaries: list[tuple[float, tuple[int, int, int]]] = []
        quarter_targets = (
            max(3, room_count // 3),
            max(5, (room_count * 2) // 3),
            max(6, room_count - 2),
        )
        for blue_boundary in range(3, room_count - 3):
            for yellow_boundary in range(blue_boundary + 2, room_count - 1):
                for red_boundary in range(yellow_boundary + 2, room_count):
                    if room_count - red_boundary < 1:
                        continue
                    score = (
                        abs(blue_boundary - quarter_targets[0]) * 1.2
                        + abs(yellow_boundary - quarter_targets[1]) * 1.4
                        + abs(red_boundary - quarter_targets[2]) * 1.6
                        + self.rng.random() * 0.25
                    )
                    candidate_boundaries.append((score, (blue_boundary, yellow_boundary, red_boundary)))
        if not candidate_boundaries:
            return None

        candidate_boundaries.sort(key=lambda item: item[0])
        _, boundaries = candidate_boundaries[0]
        blue_boundary, yellow_boundary, red_boundary = boundaries

        room_stages: list[int] = []
        for room_index in range(room_count):
            if room_index < blue_boundary:
                room_stages.append(0)
            elif room_index < yellow_boundary:
                room_stages.append(1)
            elif room_index < red_boundary:
                room_stages.append(2)
            else:
                room_stages.append(3)

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

        gate_plans = (
            ProgressionGatePlan(
                key_type="blue",
                stage_index=0,
                connection_index=blue_boundary - 1,
                key_room_candidates=tuple(room_index for room_index in stage_rooms[0] if room_index != 0),
                blocked_room_indices=tuple(room_index for room_index, stage in enumerate(room_stages) if stage > 0),
            ),
            ProgressionGatePlan(
                key_type="yellow",
                stage_index=1,
                connection_index=yellow_boundary - 1,
                key_room_candidates=stage_rooms[1],
                blocked_room_indices=tuple(room_index for room_index, stage in enumerate(room_stages) if stage > 1),
            ),
            ProgressionGatePlan(
                key_type="red",
                stage_index=2,
                connection_index=red_boundary - 1,
                key_room_candidates=stage_rooms[2],
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

    def _random_room(self, index: int) -> Room:
        kind = self._room_kind_for_index(index)
        floor_height = 0
        width, height = self._room_dimensions(kind)
        min_x, max_x, min_y, max_y = self._room_bounds_for_index(index, width, height)
        x = self.rng.randint(min_x, max_x)
        y = self.rng.randint(min_y, max_y)
        return Room(x, y, width, height, kind, floor_height)

    def _room_kind_for_index(self, index: int) -> str:
        if index == 0:
            return "start"
        if index == 1:
            return "tech"
        if index == 2:
            return "shrine"
        if index == 3:
            return "arena"
        if index == 4:
            return "cross"
        if index == 5:
            return "tech"
        if index == 6:
            return "shrine"
        return self.rng.choice(("arena", "cross", "storage", "tech"))

    def _room_bounds_for_index(self, index: int, width: int, height: int) -> tuple[int, int, int, int]:
        stage_index = 0
        if index >= 7:
            stage_index = 3
        elif index >= 5:
            stage_index = 2
        elif index >= 3:
            stage_index = 1

        stage_regions = {
            0: (1, max(10, self.width // 2 - 4), 1, max(10, self.height // 2 - 4)),
            1: (max(4, self.width // 4), max(16, self.width - 10), 4, max(16, self.height - 10)),
            2: (max(3, self.width // 5), max(16, self.width - 10), max(10, self.height // 3), self.height - 4),
            3: (max(12, self.width // 2), self.width - 3, max(4, self.height // 5), self.height - 4),
        }
        min_x, max_x, min_y, max_y = stage_regions[stage_index]
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
        room_kinds: list[list[int]],
        room: Room,
    ) -> None:
        kind_index = ROOM_KINDS.index(room.kind)
        for y in range(room.y, room.y + room.height):
            for x in range(room.x, room.x + room.width):
                tiles[y][x] = 0
                floor_heights[y][x] = room.floor_height
                room_kinds[y][x] = kind_index

    def _connect_rooms(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
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

        self._assign_path_heights(path, floor_heights, stair_mask, room_kinds)
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
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
    ) -> None:
        seen: set[tuple[int, int]] = set()
        corridor_kind = ROOM_KINDS.index("tech")
        for x, y in path:
            if (x, y) in seen:
                continue
            seen.add((x, y))
            floor_heights[y][x] = 0
            room_kinds[y][x] = corridor_kind
            stair_mask[y][x] = 0

    def _decorate_rooms(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
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

    def _add_side_connections(
        self,
        tiles: list[list[int]],
        floor_heights: list[list[int]],
        stair_mask: list[list[int]],
        room_kinds: list[list[int]],
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
            if self.rng.random() >= 0.7:
                continue
            path = self._connect_rooms(
                tiles,
                floor_heights,
                stair_mask,
                room_kinds,
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
        rooms: list[Room],
        spawn: tuple[float, float],
        connections: list[CorridorConnection],
        progression: ProgressionLayout,
    ) -> list[KeySpawn] | None:
        key_spawns: list[KeySpawn] = []
        occupied_positions = [spawn]

        for gate_index, gate in enumerate(progression.gate_plans):
            connection = connections[gate.connection_index]
            reachable_before_door = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                {
                    (connections[later_gate.connection_index].door_candidate[0], connections[later_gate.connection_index].door_candidate[1])
                    for later_gate in progression.gate_plans[gate_index:]
                    if connections[later_gate.connection_index].door_candidate is not None
                },
            )

            key_position = None
            for key_room_index in self._ordered_key_rooms(rooms, set(gate.key_room_candidates), connection):
                key_position = self._choose_key_position(
                    rooms[key_room_index],
                    tiles,
                    stair_mask,
                    spawn,
                    occupied_positions,
                    reachable_tiles=reachable_before_door,
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
            if connection.index in locked_connection_indices or connection.is_main_path:
                continue
            connection.door_candidate = self._find_door_candidate(tiles, stair_mask, rooms, connection, spawn)
            if connection.door_candidate is None:
                continue
            door_x, door_y, orientation = connection.door_candidate
            door_world_pos = (door_x + 0.5, door_y + 0.5)
            if any(
                math.dist(door_world_pos, (door.grid_x + 0.5, door.grid_y + 0.5)) < settings.DOOR_MIN_SPACING
                for door in [*locked_doors, *normal_doors]
            ):
                continue
            normal_doors.append(
                DoorSpawn(
                    door_id=f"door-{self.seed}-{len(locked_doors) + len(normal_doors):03d}",
                    grid_x=door_x,
                    grid_y=door_y,
                    orientation=orientation,
                    door_type="normal",
                )
            )
        return normal_doors

    def _validate_progression_layout(
        self,
        tiles: list[list[int]],
        rooms: list[Room],
        spawn: tuple[float, float],
        progression: ProgressionLayout,
        locked_doors: list[DoorSpawn],
        key_spawns: list[KeySpawn],
        exit_spawn: ExitSpawn,
    ) -> bool:
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
                {(door.grid_x, door.grid_y)},
            )
            if self._reachable_room_indices(rooms, blocked_with_only_gate_closed) & set(gate.blocked_room_indices):
                return False

        for gate_index, gate in enumerate(progression.gate_plans):
            current_door = door_by_key[gate.key_type]
            closed_now = {
                (door_by_key[later_gate.key_type].grid_x, door_by_key[later_gate.key_type].grid_y)
                for later_gate in progression.gate_plans[gate_index:]
            }
            reachable_before = self._reachable_tiles_with_closed_positions(tiles, spawn, closed_now)
            key_tile = (int(key_by_type[gate.key_type].x), int(key_by_type[gate.key_type].y))
            if key_tile not in reachable_before:
                return False
            if self._reachable_room_indices(rooms, reachable_before) & set(gate.blocked_room_indices):
                return False

            reachable_after = self._reachable_tiles_with_closed_positions(
                tiles,
                spawn,
                {
                    (door_by_key[later_gate.key_type].grid_x, door_by_key[later_gate.key_type].grid_y)
                    for later_gate in progression.gate_plans[gate_index + 1:]
                },
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
            {(locked_doors[-1].grid_x, locked_doors[-1].grid_y)},
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
        chance = 0.24 + max(0.0, self.difficulty_rating - 1.0) * 0.85
        chance += 0.08 if len(rooms) >= 8 else 0.0
        if self.rng.random() > min(0.62, chance):
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
        rooms: list[Room],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        progression_suffix_rooms: set[int] | None,
        required_door_id: str | None,
        required_door_tile: tuple[int, int] | None,
    ) -> ExitSpawn | None:
        if not rooms:
            return None
        reachable_without_final: set[tuple[int, int]] | None = None
        reachable_with_final: set[tuple[int, int]] | None = None
        final_door_world_pos: tuple[float, float] | None = None
        if required_door_tile is not None:
            reachable_without_final = self._reachable_tiles_with_closed_positions(tiles, spawn, {required_door_tile})
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
                spawn,
                occupied_positions,
                min_spacing=1.65,
            )
            if not candidates:
                candidates = self._fallback_room_positions(room, tiles, stair_mask, spawn, occupied_positions)
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
            if room_a.contains_tile(grid_x, grid_y, padding=1) or room_b.contains_tile(grid_x, grid_y, padding=1):
                continue
            if math.dist((grid_x + 0.5, grid_y + 0.5), spawn) < settings.DOOR_MIN_PLAYER_DISTANCE:
                continue
            orientation = self._door_orientation_at(tiles, grid_x, grid_y)
            if orientation is None:
                continue
            candidates.append((grid_x, grid_y, orientation))

        if not candidates:
            return None
        return candidates[len(candidates) // 2]

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
    ) -> list[int]:
        door_world_pos = (
            connection.door_candidate[0] + 0.5,
            connection.door_candidate[1] + 0.5,
        )
        return sorted(
            room_candidates,
            key=lambda room_index: (
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
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
    ) -> tuple[float, float] | None:
        candidates = self._room_floor_candidates(
            room,
            tiles,
            stair_mask,
            spawn,
            occupied_positions,
            min_spacing=1.45,
            reachable_tiles=reachable_tiles,
            forbidden_tiles=forbidden_tiles,
        )
        if not candidates:
            candidates = self._fallback_room_positions(
                room,
                tiles,
                stair_mask,
                spawn,
                occupied_positions,
                reachable_tiles=reachable_tiles,
                forbidden_tiles=forbidden_tiles,
            )
        if not candidates:
            return None
        candidates.sort(key=lambda pos: math.dist(pos, spawn), reverse=True)
        return candidates[0]

    def _generate_loot_spawns(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
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
            candidates = self._room_floor_candidates(room, tiles, stair_mask, spawn, occupied_positions)
            if not candidates:
                continue

            count_min, count_max = ROOM_LOOT_COUNTS.get(room.kind, (1, 2))
            spawn_count = min(len(candidates), self.rng.randint(count_min, count_max))
            loot_table = ROOM_LOOT_TABLES.get(room.kind, ROOM_LOOT_TABLES["cross"])

            placed = 0
            for x, y in candidates:
                if any(math.dist((x, y), other) < settings.LOOT_MIN_SPACING for other in occupied_positions):
                    continue
                entry = self._weighted_loot_entry(loot_table)
                amount = resolve_pickup_amount(entry.kind, entry.amount)
                pickup_id = f"loot-{self.seed}-{room_index:02d}-{next_id:03d}"
                loot_spawns.append(LootSpawn(pickup_id, x, y, entry.kind, amount))
                occupied_positions.append((x, y))
                next_id += 1
                placed += 1
                if placed >= spawn_count:
                    break

        return loot_spawns

    def _generate_enemy_spawns(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
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
                enemy_type = self._choose_enemy_type(room.kind, room_index, len(rooms), difficulty_tier)
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
            enemy_type = self._choose_enemy_type(room.kind, room_index, len(rooms), difficulty_tier)
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
        if room_index >= room_count - 2:
            target += 1
        if room.kind == "shrine":
            target = max(1, target - 1)
        if guard_enemy_id is not None and boss_guard_plan is not None and room_index == boss_guard_plan.candidate_room_indices[0]:
            target = max(0, target - 1)
        max_target = {
            "arena": 5,
            "cross": 4,
            "tech": 4,
            "shrine": 3,
        }.get(room.kind, 4)
        return min(target, max_target)

    def _enemy_candidates_for_room(
        self,
        room: Room,
        room_index: int,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
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
            spawn,
            occupied_positions,
            min_spacing=extra_spacing,
        )
        if not candidates:
            candidates = self._fallback_room_positions(room, tiles, stair_mask, spawn, occupied_positions)
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
        return (
            nearest_other * 1.85
            + distance_from_spawn * 0.26
            + progress * 1.1
            + (1.0 - room_fill_ratio) * 1.6
            + room_kind_bonus
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
        return min(1.35, max(0.78, kind_bonus * (0.82 + progress * 0.52) * self.difficulty_rating))

    def _choose_boss_position(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
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
                spawn,
                occupied_positions,
                min_spacing=max(2.0, settings.ENEMY_MIN_SPACING + 0.8),
            )
            if not candidates:
                candidates = self._fallback_room_positions(room, tiles, stair_mask, spawn, occupied_positions)
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
        room_kind: str,
        room_index: int,
        room_count: int,
        difficulty_tier: int,
    ) -> str:
        progress = room_index / max(1, room_count - 1)
        roll = self.rng.random()
        weighted_roll = roll / max(0.7, self.difficulty_rating)
        if progress < 0.24:
            return "charger" if weighted_roll < 0.34 else "grunt"
        if progress < 0.58:
            if room_kind in {"arena", "tech", "cross"} and weighted_roll < 0.38:
                return "heavy"
            if difficulty_tier >= 1 and weighted_roll < 0.24:
                return "heavy"
            if weighted_roll < 0.46:
                return "charger"
            return "grunt"
        if room_kind in {"arena", "shrine", "tech", "cross"} and weighted_roll < 0.6:
            return "heavy"
        if difficulty_tier >= 2 and weighted_roll < 0.46:
            return "heavy"
        if weighted_roll < 0.3:
            return "charger"
        return "grunt"

    def _room_floor_candidates(
        self,
        room: Room,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        min_spacing: float | None = None,
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
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
        spawn: tuple[float, float],
        occupied_positions: list[tuple[float, float]],
        reachable_tiles: set[tuple[int, int]] | None = None,
        forbidden_tiles: set[tuple[int, int]] | None = None,
    ) -> list[tuple[float, float]]:
        candidates: list[tuple[float, float]] = []
        for y in range(room.y + 1, room.y + room.height - 1):
            for x in range(room.x + 1, room.x + room.width - 1):
                if tiles[y][x] != 0 or stair_mask[y][x] != 0:
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
        count = self.rng.randint(2, 4)
        for _ in range(count):
            x = self.rng.randint(room.x + 1, room.x + room.width - 2)
            y = self.rng.randint(room.y + 1, room.y + room.height - 2)
            if (x, y) != room.center:
                tiles[y][x] = 1

    def _decorate_arena(self, tiles: list[list[int]], room: Room) -> None:
        corners = (
            (room.x + 1, room.y + 1),
            (room.x + room.width - 2, room.y + 1),
            (room.x + 1, room.y + room.height - 2),
            (room.x + room.width - 2, room.y + room.height - 2),
        )
        for x, y in corners:
            tiles[y][x] = 1

    def _decorate_tech(self, tiles: list[list[int]], room: Room) -> None:
        if room.width < 6:
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
