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
        for attempt in range(64):
            self.rng = random.Random(self.seed + attempt * 7919)
            generated = self._generate_once()
            locked_count = sum(1 for door in generated.door_spawns if door.door_type != "normal")
            if locked_count > best_locked_count:
                best_map = generated
                best_locked_count = locked_count
            if locked_count >= 1 and generated.exit_spawn is not None and generated.exit_spawn.required_door_id is not None:
                return generated
        return best_map if best_map is not None else self._generate_once()

    def _generate_once(self) -> GeneratedMap:
        tiles = [[1 for _ in range(self.width)] for _ in range(self.height)]
        floor_heights = [[0 for _ in range(self.width)] for _ in range(self.height)]
        stair_mask = [[0 for _ in range(self.width)] for _ in range(self.height)]
        room_kinds = [[-1 for _ in range(self.width)] for _ in range(self.height)]
        rooms: list[Room] = []
        connections: list[CorridorConnection] = []

        for _ in range(settings.MAX_ROOMS * 3):
            room = self._random_room(len(rooms))
            if any(room.intersects(other) for other in rooms):
                continue
            self._carve_room(tiles, floor_heights, room_kinds, room)
            if rooms:
                path = self._connect_rooms(tiles, floor_heights, stair_mask, room_kinds, rooms[-1], room)
                connections.append(
                    CorridorConnection(
                        index=len(connections),
                        room_a_index=len(rooms) - 1,
                        room_b_index=len(rooms),
                        path=path,
                        is_main_path=True,
                    )
                )
            rooms.append(room)
            if len(rooms) >= settings.MAX_ROOMS:
                break

        if not rooms:
            fallback = Room(4, 4, self.width - 8, self.height - 8, "start", 0)
            self._carve_room(tiles, floor_heights, room_kinds, fallback)
            rooms.append(fallback)

        self._decorate_rooms(tiles, floor_heights, stair_mask, room_kinds, rooms)
        self._add_side_connections(tiles, floor_heights, stair_mask, room_kinds, rooms, connections)

        spawn_x, spawn_y = rooms[0].center
        spawn = (spawn_x + 0.5, spawn_y + 0.5)
        door_spawns, key_spawns, exit_spawn, boss_guard_plan = self._generate_doors_and_keys(
            tiles,
            stair_mask,
            rooms,
            connections,
            spawn,
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

    def _random_room(self, index: int) -> Room:
        kind = "start" if index == 0 else self.rng.choice(ROOM_KINDS[1:])
        floor_height = 0
        width, height = self._room_dimensions(kind)
        x = self.rng.randint(1, self.width - width - 2)
        y = self.rng.randint(1, self.height - height - 2)
        return Room(x, y, width, height, kind, floor_height)

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
    ) -> list[tuple[int, int]]:
        ax, ay = a.center
        bx, by = b.center
        if self.rng.random() < 0.5:
            path = self._carve_h_corridor(tiles, ax, bx, ay)
            path.extend(self._carve_v_corridor(tiles, ay, by, bx))
        else:
            path = self._carve_v_corridor(tiles, ay, by, ax)
            path.extend(self._carve_h_corridor(tiles, ax, bx, by))

        self._assign_path_heights(path, floor_heights, stair_mask, room_kinds)
        return path

    def _carve_h_corridor(self, tiles: list[list[int]], x1: int, x2: int, y: int) -> list[tuple[int, int]]:
        carved: list[tuple[int, int]] = []
        for x in range(min(x1, x2), max(x1, x2) + 1):
            tiles[y][x] = 0
            carved.append((x, y))
            if y + 1 < self.height - 1 and self.rng.random() < 0.08:
                tiles[y + 1][x] = 0
                carved.append((x, y + 1))
        return carved

    def _carve_v_corridor(self, tiles: list[list[int]], y1: int, y2: int, x: int) -> list[tuple[int, int]]:
        carved: list[tuple[int, int]] = []
        for y in range(min(y1, y2), max(y1, y2) + 1):
            tiles[y][x] = 0
            carved.append((x, y))
            if x + 1 < self.width - 1 and self.rng.random() < 0.08:
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
    ) -> None:
        if len(rooms) < 4:
            return

        candidate_pairs: list[tuple[int, float, int, int]] = []
        for index, room in enumerate(rooms[:-2]):
            for other_index in range(index + 2, len(rooms)):
                other = rooms[other_index]
                ax, ay = room.center
                bx, by = other.center
                distance = abs(ax - bx) + abs(ay - by)
                candidate_pairs.append((distance, self.rng.random(), index, other_index))

        candidate_pairs.sort(key=lambda item: (item[0], item[1]))
        extra_links = 0
        target_links = min(3, len(rooms) // 3)
        for _, _, room_a_index, room_b_index in candidate_pairs:
            if extra_links >= target_links:
                break
            if self.rng.random() < 0.55:
                path = self._connect_rooms(
                    tiles,
                    floor_heights,
                    stair_mask,
                    room_kinds,
                    rooms[room_a_index],
                    rooms[room_b_index],
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
                extra_links += 1

    def _generate_doors_and_keys(
        self,
        tiles: list[list[int]],
        stair_mask: list[list[int]],
        rooms: list[Room],
        connections: list[CorridorConnection],
        spawn: tuple[float, float],
    ) -> tuple[list[DoorSpawn], list[KeySpawn], ExitSpawn | None, BossGuardPlan | None]:
        if len(rooms) < 3:
            return ([], [], None, None)

        for connection in connections:
            connection.door_candidate = self._find_door_candidate(tiles, stair_mask, rooms, connection, spawn)

        bridge_indices = self._find_bridge_indices(len(rooms), connections)
        locked_chain = self._build_locked_progression_chain(tiles, rooms, connections, bridge_indices, spawn)

        door_spawns: list[DoorSpawn] = []
        key_spawns: list[KeySpawn] = []
        occupied_positions = [spawn]
        used_locked_indices: set[int] = set()
        progression_suffix_rooms: set[int] | None = None
        final_required_door_id: str | None = None
        final_required_door_tile: tuple[int, int] | None = None
        final_connection: CorridorConnection | None = None

        staged_doors: list[DoorSpawn] = []
        staged_keys: list[KeySpawn] = []
        staged_occupied_positions = occupied_positions[:]

        for chain_index, (key_type, connection, key_room_candidates) in enumerate(locked_chain):
            if not key_room_candidates:
                return ([], [], None, None)
            reachable_before_door = self._reachable_tiles_for_progression(tiles, spawn, locked_chain, chain_index)
            forbidden_before_previous: set[tuple[int, int]] | None = None
            if chain_index > 0:
                forbidden_before_previous = self._reachable_tiles_for_progression(tiles, spawn, locked_chain, chain_index - 1)
            key_position = None
            for key_room_index in self._ordered_key_rooms(rooms, key_room_candidates, connection):
                key_position = self._choose_key_position(
                    rooms[key_room_index],
                    tiles,
                    stair_mask,
                    spawn,
                    staged_occupied_positions,
                    reachable_tiles=reachable_before_door,
                    forbidden_tiles=forbidden_before_previous,
                )
                if key_position is not None:
                    break
            if key_position is None:
                return ([], [], None, None)

            door_x, door_y, orientation = connection.door_candidate
            door_id = f"door-{self.seed}-{len(door_spawns) + len(staged_doors):03d}"
            staged_doors.append(
                DoorSpawn(
                    door_id=door_id,
                    grid_x=door_x,
                    grid_y=door_y,
                    orientation=orientation,
                    door_type=locked_door_type_for_key(key_type),
                )
            )
            staged_keys.append(
                KeySpawn(
                    key_id=f"key-{self.seed}-{key_type}",
                    key_type=key_type,
                    x=key_position[0],
                    y=key_position[1],
                )
            )
            staged_occupied_positions.append(key_position)
            used_locked_indices.add(connection.index)
            progression_suffix_rooms = set(range(len(rooms))) - self._reachable_rooms(
                len(rooms),
                connections,
                0,
                skip_connection_index=connection.index,
            )
            final_required_door_id = door_id
            final_required_door_tile = (door_x, door_y)
            final_connection = connection

        door_spawns.extend(staged_doors)
        key_spawns.extend(staged_keys)
        occupied_positions = staged_occupied_positions

        remaining_candidates = [
            connection
            for connection in connections
            if connection.index in bridge_indices
            and connection.index not in used_locked_indices
            and connection.door_candidate is not None
        ]
        remaining_candidates.sort(key=lambda connection: (not connection.is_main_path, connection.room_b_index))
        normal_target = min(2, len(remaining_candidates))

        for connection in remaining_candidates:
            if len([door for door in door_spawns if door.door_type == "normal"]) >= normal_target:
                break
            door_x, door_y, orientation = connection.door_candidate
            door_world_pos = (door_x + 0.5, door_y + 0.5)
            if math.dist(door_world_pos, spawn) < settings.DOOR_MIN_PLAYER_DISTANCE:
                continue
            if any(math.dist(door_world_pos, (door.grid_x + 0.5, door.grid_y + 0.5)) < settings.DOOR_MIN_SPACING for door in door_spawns):
                continue
            door_id = f"door-{self.seed}-{len(door_spawns):03d}"
            door_spawns.append(
                DoorSpawn(
                    door_id=door_id,
                    grid_x=door_x,
                    grid_y=door_y,
                    orientation=orientation,
                    door_type="normal",
                )
            )

        exit_spawn = self._generate_exit_spawn(
            tiles,
            stair_mask,
            rooms,
            spawn,
            occupied_positions,
            progression_suffix_rooms,
            final_required_door_id,
            final_required_door_tile,
        )
        boss_guard_plan = self._build_boss_guard_plan(
            rooms,
            connections,
            final_connection,
            final_required_door_id,
            final_required_door_tile,
        )
        return (door_spawns, key_spawns, exit_spawn, boss_guard_plan)

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
                next_index += 1

        for room_index, room in enumerate(rooms):
            if room_index == 0:
                continue
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
            if not candidates:
                continue

            room_area = room.width * room.height
            density_bonus = 1 if room.kind in {"arena", "cross"} else 0
            difficulty_scale = self._room_difficulty_scale(room.kind, room_index, len(rooms))
            spawn_budget = room_area / max(12.0, 18.0 - difficulty_scale * 3.0)
            spawn_count = max(1, min(len(candidates), int(round(spawn_budget)) + density_bonus))
            if room.kind == "shrine":
                spawn_count = max(1, spawn_count - 1)
            if room_area >= 70:
                spawn_count += 1
            if room_index >= len(rooms) - 2:
                spawn_count += 1
            if room.kind == "arena" and difficulty_scale > 1.0:
                spawn_count += 1
            if guard_enemy_id is not None and boss_guard_plan is not None and room_index == boss_guard_plan.candidate_room_indices[0]:
                spawn_count = max(0, spawn_count - 1)
            spawn_count = min(len(candidates), spawn_count)

            candidates.sort(key=lambda pos: math.dist(pos, spawn), reverse=True)
            placed = 0
            for x, y in candidates:
                if math.dist((x, y), spawn) < settings.ENEMY_MIN_PLAYER_DISTANCE:
                    continue
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
                next_index += 1
                placed += 1
                if placed >= spawn_count:
                    break

        return enemy_spawns, guard_enemy_id

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
        if progress < 0.28:
            return "charger" if weighted_roll < 0.24 else "grunt"
        if progress < 0.62:
            if room_kind == "arena" and weighted_roll < 0.22:
                return "heavy"
            if weighted_roll < 0.32:
                return "charger"
            return "grunt"
        if room_kind in {"arena", "shrine"} and weighted_roll < 0.4:
            return "heavy"
        if difficulty_tier >= 2 and weighted_roll < 0.28:
            return "heavy"
        if weighted_roll < 0.38:
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
