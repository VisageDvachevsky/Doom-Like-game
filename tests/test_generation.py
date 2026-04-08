from __future__ import annotations

import math
import os
import unittest
from collections import deque
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from doomgame.game import DoomGame
from doomgame.enemies import ENEMY_DEFINITIONS
from doomgame.loot import get_pickup_definition
from doomgame.mapgen import MapGenerator
from doomgame.progression import CampaignSequenceDirector
from doomgame.world import World


class DifficultyGenerationTests(unittest.TestCase):
    def _reachable_tiles(
        self,
        tiles: list[list[int]],
        spawn: tuple[float, float],
        blocked: set[tuple[int, int]],
    ) -> set[tuple[int, int]]:
        start = (int(spawn[0]), int(spawn[1]))
        queue = deque([start])
        visited = {start}
        width = len(tiles[0])
        height = len(tiles)
        while queue:
            grid_x, grid_y = queue.popleft()
            for offset_x, offset_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                next_x = grid_x + offset_x
                next_y = grid_y + offset_y
                if not (0 <= next_x < width and 0 <= next_y < height):
                    continue
                if (next_x, next_y) in visited or (next_x, next_y) in blocked:
                    continue
                if tiles[next_y][next_x] != 0:
                    continue
                visited.add((next_x, next_y))
                queue.append((next_x, next_y))
        return visited

    def test_rerolls_change_layout_shape(self) -> None:
        signatures = {
            tuple(tuple(row) for row in MapGenerator(seed=seed, difficulty_id="medium", runtime_pressure_bias=1.0).generate().tiles)
            for seed in range(1200, 1206)
        }
        self.assertGreater(len(signatures), 1)

    def test_same_seed_is_deterministic_per_difficulty(self) -> None:
        generated_a = MapGenerator(seed=12345, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        generated_b = MapGenerator(seed=12345, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        self.assertEqual(generated_a.tiles, generated_b.tiles)
        self.assertEqual(generated_a.floor_heights, generated_b.floor_heights)
        self.assertEqual(generated_a.ceiling_heights, generated_b.ceiling_heights)
        self.assertEqual(generated_a.sector_types, generated_b.sector_types)
        self.assertEqual(generated_a.room_metadata, generated_b.room_metadata)
        self.assertEqual(generated_a.enemy_spawns, generated_b.enemy_spawns)
        self.assertEqual(generated_a.trigger_spawns, generated_b.trigger_spawns)

    def test_progression_invariants_hold_for_all_difficulties(self) -> None:
        for difficulty_id in ("easy", "medium", "hard"):
            generated = MapGenerator(seed=20260407, difficulty_id=difficulty_id, runtime_pressure_bias=1.0).generate()
            locked_doors = [door for door in generated.door_spawns if door.door_type != "normal"]
            self.assertEqual(3, len(generated.key_spawns), difficulty_id)
            self.assertEqual(3, len(locked_doors), difficulty_id)
            self.assertTrue(generated.validation_report.valid, difficulty_id)
            self.assertIsNotNone(generated.exit_spawn, difficulty_id)
            self.assertIsNotNone(generated.exit_spawn.required_door_id, difficulty_id)

    def test_higher_difficulties_raise_enemy_pressure(self) -> None:
        easy = MapGenerator(seed=424242, difficulty_id="easy", runtime_pressure_bias=1.0).generate()
        medium = MapGenerator(seed=424242, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        hard = MapGenerator(seed=424242, difficulty_id="hard", runtime_pressure_bias=1.0).generate()

        self.assertLess(len(easy.enemy_spawns), len(medium.enemy_spawns))
        self.assertLess(len(medium.enemy_spawns), len(hard.enemy_spawns))
        self.assertLess(easy.quality_report.encounter_pressure_score, medium.quality_report.encounter_pressure_score)
        self.assertLess(medium.quality_report.encounter_pressure_score, hard.quality_report.encounter_pressure_score)

    def test_hard_uses_more_hazard_pressure_than_easy(self) -> None:
        acid_tiles_easy = 0
        acid_tiles_hard = 0
        for seed in range(900, 906):
            easy = MapGenerator(seed=seed, difficulty_id="easy", runtime_pressure_bias=1.0).generate()
            hard = MapGenerator(seed=seed, difficulty_id="hard", runtime_pressure_bias=1.0).generate()
            acid_tiles_easy += sum(cell == 1 for row in easy.sector_types for cell in row)
            acid_tiles_hard += sum(cell == 1 for row in hard.sector_types for cell in row)
        self.assertGreater(acid_tiles_hard, acid_tiles_easy)

    def test_easy_provides_more_total_resource_value_than_hard(self) -> None:
        easy = MapGenerator(seed=777, difficulty_id="easy", runtime_pressure_bias=1.0).generate()
        hard = MapGenerator(seed=777, difficulty_id="hard", runtime_pressure_bias=1.0).generate()

        easy_value = sum(loot.amount for loot in easy.loot_spawns) + sum(secret.reward_amount for secret in easy.secret_spawns)
        hard_value = sum(loot.amount for loot in hard.loot_spawns) + sum(secret.reward_amount for secret in hard.secret_spawns)
        self.assertGreater(easy_value, hard_value)

    def test_difficulty_ammo_economy_is_more_evenly_tuned(self) -> None:
        def ammo_profile(difficulty_id: str) -> tuple[float, float]:
            required_shots: list[float] = []
            placed_ammo: list[float] = []
            expected_drop_ammo: list[float] = []
            for seed in range(200, 206):
                generated = MapGenerator(seed=seed, difficulty_id=difficulty_id, runtime_pressure_bias=1.0).generate()
                required_shots.append(
                    sum((ENEMY_DEFINITIONS[enemy.enemy_type].max_hp + 23) // 24 for enemy in generated.enemy_spawns)
                )
                placed = 32
                expected_drops = 0.0
                for loot in generated.loot_spawns:
                    definition = get_pickup_definition(loot.kind)
                    if definition.effect.stat == "ammo":
                        placed += loot.amount
                for enemy in generated.enemy_spawns:
                    for drop in ENEMY_DEFINITIONS[enemy.enemy_type].drops:
                        definition = get_pickup_definition(drop.kind)
                        if definition.effect.stat == "ammo":
                            expected_drops += drop.amount * drop.chance
                placed_ammo.append(placed)
                expected_drop_ammo.append(expected_drops)
            placed_ratio = sum(placed_ammo) / sum(required_shots)
            total_ratio = (sum(placed_ammo) + sum(expected_drop_ammo)) / sum(required_shots)
            return placed_ratio, total_ratio

        easy_placed, easy_total = ammo_profile("easy")
        medium_placed, medium_total = ammo_profile("medium")
        hard_placed, hard_total = ammo_profile("hard")

        self.assertGreater(easy_placed, medium_placed)
        self.assertGreater(medium_placed, hard_placed)
        self.assertGreater(easy_total, medium_total)
        self.assertGreater(medium_total, hard_total)
        self.assertGreaterEqual(easy_total, 1.5)
        self.assertGreaterEqual(medium_total, 1.12)
        self.assertLessEqual(medium_total, 1.32)
        self.assertGreaterEqual(hard_total, 0.98)
        self.assertLessEqual(hard_total, 1.08)

    def test_key_ambushes_spawn_in_neighboring_rooms_not_on_top_of_key(self) -> None:
        generated = MapGenerator(seed=20260411, difficulty_id="hard", runtime_pressure_bias=1.0).generate()
        enemy_by_id = {enemy.enemy_id: enemy for enemy in generated.enemy_spawns}
        adjacency: dict[int, set[int]] = {}
        for edge in generated.route_plan.edges:
            adjacency.setdefault(edge.room_a_index, set()).add(edge.room_b_index)
            adjacency.setdefault(edge.room_b_index, set()).add(edge.room_a_index)

        def room_distance(start: int, target: int) -> int | None:
            queue = deque([(start, 0)])
            visited = {start}
            while queue:
                room_index, depth = queue.popleft()
                if room_index == target:
                    return depth
                for neighbor in adjacency.get(room_index, ()):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
            return None

        key_room_by_trigger = {trigger.trigger_id: trigger.room_index for trigger in generated.trigger_spawns if trigger.trigger_type == "pickup"}
        for event in generated.encounter_events:
            if event.trigger_type != "pickup":
                continue
            key_room_index = key_room_by_trigger[event.trigger_ref]
            self.assertTrue(event.target_enemy_ids)
            for enemy_id in event.target_enemy_ids:
                enemy_room_index = enemy_by_id[enemy_id].room_index
                self.assertNotEqual(key_room_index, enemy_room_index)
                distance = room_distance(key_room_index, enemy_room_index)
                self.assertIn(distance, {1, 2})

    def test_dormant_event_enemies_are_hidden_until_triggered(self) -> None:
        generated = MapGenerator(seed=20260407, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        world = World.from_generated_map(generated)

        dormant_enemy_ids = {enemy.enemy_id for enemy in world.enemies if not enemy.active}
        self.assertTrue(dormant_enemy_ids)

        visible_before = {enemy.enemy_id for enemy in world.active_enemies(include_corpses=True)}
        self.assertTrue(dormant_enemy_ids.isdisjoint(visible_before))

        world.handle_key_pickup("blue")

        visible_after = {enemy.enemy_id for enemy in world.active_enemies(include_corpses=True)}
        self.assertTrue(dormant_enemy_ids & visible_after)

    def test_locked_door_does_not_open_without_required_key(self) -> None:
        generated = MapGenerator(seed=102, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        world = World.from_generated_map(generated)

        yellow_door = next(door for door in world.doors if door.door_type == "yellow_locked")
        player_x = yellow_door.grid_x - 0.65
        player_y = yellow_door.grid_y + 0.5
        interacted_door, message, opened = world.interact_with_door(player_x, player_y, 0.0, set())

        self.assertIsNotNone(interacted_door)
        self.assertEqual("yellow_locked", interacted_door.door_type)
        self.assertFalse(opened)
        self.assertEqual("locked", interacted_door.state)
        self.assertEqual("YELLOW DOOR - KEY REQUIRED", message)

    def test_keys_spawn_in_area_reachable_before_their_gate(self) -> None:
        generated = MapGenerator(seed=20260408, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        key_order = ("blue", "yellow", "red")
        door_by_key = {
            door.door_type.removesuffix("_locked"): door
            for door in generated.door_spawns
            if door.door_type.endswith("_locked")
        }
        key_by_type = {key.key_type: key for key in generated.key_spawns}

        for gate_index, key_type in enumerate(key_order):
            blocked = {
                (door_by_key[later_key].grid_x, door_by_key[later_key].grid_y)
                for later_key in key_order[gate_index:]
            }
            reachable = self._reachable_tiles(generated.tiles, generated.spawn, blocked)
            key = key_by_type[key_type]
            self.assertIn((int(key.x), int(key.y)), reachable, key_type)
            self.assertNotEqual(1, generated.sector_types[int(key.y)][int(key.x)], key_type)

    def test_blue_key_is_not_placed_next_to_blue_door(self) -> None:
        for difficulty_id in ("easy", "medium"):
            distances: list[float] = []
            for seed in range(100, 106):
                generated = MapGenerator(seed=seed, difficulty_id=difficulty_id, runtime_pressure_bias=1.0).generate()
                blue_door = next(door for door in generated.door_spawns if door.door_type == "blue_locked")
                blue_key = next(key for key in generated.key_spawns if key.key_type == "blue")
                distances.append(
                    math.dist(
                        (blue_door.grid_x + 0.5, blue_door.grid_y + 0.5),
                        (blue_key.x, blue_key.y),
                    )
                )
            self.assertGreater(sum(distances) / len(distances), 10.0, difficulty_id)

    def test_future_keys_are_not_clustered_around_previous_locked_doors(self) -> None:
        key_order = ("blue", "yellow", "red")
        for difficulty_id in ("easy", "medium", "hard"):
            min_distances: dict[str, list[float]] = {"yellow": [], "red": []}
            for seed in range(100, 110):
                generated = MapGenerator(seed=seed, difficulty_id=difficulty_id, runtime_pressure_bias=1.0).generate()
                door_by_key = {
                    door.door_type.removesuffix("_locked"): (door.grid_x + 0.5, door.grid_y + 0.5)
                    for door in generated.door_spawns
                    if door.door_type.endswith("_locked")
                }
                key_by_type = {key.key_type: (key.x, key.y) for key in generated.key_spawns}
                for key_index, key_type in enumerate(key_order):
                    if key_type == "blue":
                        continue
                    prior_doors = key_order[:key_index]
                    nearest = min(
                        math.dist(key_by_type[key_type], door_by_key[prior_key])
                        for prior_key in prior_doors
                    )
                    min_distances[key_type].append(nearest)
            self.assertGreater(sum(min_distances["yellow"]) / len(min_distances["yellow"]), 6.0, difficulty_id)
            self.assertGreater(sum(min_distances["red"]) / len(min_distances["red"]), 6.0, difficulty_id)

    def test_phase_one_spatial_beats_exist_in_generated_maps(self) -> None:
        generated = MapGenerator(seed=20260409, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        self.assertGreaterEqual(generated.validation_report.hazard_room_count, 1)
        self.assertGreaterEqual(generated.validation_report.bridge_crossing_count, 1)
        self.assertGreater(generated.validation_report.vertical_variety_score, 0.0)
        self.assertGreater(generated.validation_report.silhouette_variety_score, 0.0)

    def test_bridge_tiles_do_not_create_step_spikes(self) -> None:
        generated = MapGenerator(seed=20260409, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        for y, row in enumerate(generated.sector_types):
            for x, sector in enumerate(row):
                if sector != 2:
                    continue
                self.assertEqual(generated.floor_heights[y][x], 0)

    def test_acid_sector_applies_environmental_damage(self) -> None:
        generated = MapGenerator(seed=20260409, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
        acid_tile = next(
            (x, y)
            for y, row in enumerate(generated.sector_types)
            for x, cell in enumerate(row)
            if cell == 1
        )
        world = World.from_generated_map(generated)
        player = SimpleNamespace(x=acid_tile[0] + 0.5, y=acid_tile[1] + 0.5)
        damage_events: list[tuple[int, str]] = []
        for _ in range(10):
            world._update_environmental_hazards(0.2, player, lambda amount, source: damage_events.append((amount, source)), None)
        self.assertTrue(damage_events)
        self.assertTrue(all(source == "acid" for _, source in damage_events))

    def test_rerolls_now_cover_multiple_shape_families(self) -> None:
        shape_sets = []
        for seed in range(1200, 1206):
            generated = MapGenerator(seed=seed, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
            shape_sets.append({room.shape_family for room in generated.room_metadata})
        self.assertTrue(any(len(shape_set) >= 3 for shape_set in shape_sets))

    def test_rerolls_vary_spatial_archetypes_more_than_single_profile(self) -> None:
        archetype_sets = []
        for seed in range(1200, 1206):
            generated = MapGenerator(seed=seed, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
            archetype_sets.append({room.spatial_archetype for room in generated.room_metadata})
        self.assertTrue(any(len(archetype_set) >= 5 for archetype_set in archetype_sets))

    def test_rerolls_include_taller_rooms_and_new_hazard_layouts(self) -> None:
        tallest_ceiling = 0
        seen_hazard_layout = False
        for seed in range(1400, 1410):
            generated = MapGenerator(seed=seed, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
            tallest_ceiling = max(tallest_ceiling, max(room.ceiling_height for room in generated.room_metadata))
            seen_hazard_layout = seen_hazard_layout or any(
                room.spatial_archetype in {"acid_ring_room", "toxic_canals_room"}
                for room in generated.room_metadata
            )
        self.assertGreaterEqual(tallest_ceiling, 4)
        self.assertTrue(seen_hazard_layout)

    def test_rerolls_cover_multiple_macro_footprints(self) -> None:
        signatures = set()
        for seed in range(1300, 1308):
            generated = MapGenerator(seed=seed, difficulty_id="medium", runtime_pressure_bias=1.0).generate()
            signatures.add(
                (
                    generated.macro_layout_type,
                    generated.route_plan.vista_room_indices,
                    generated.route_plan.return_room_indices,
                    tuple((room.room_index, room.role, room.room_kind) for room in generated.room_metadata),
                )
            )
        self.assertGreaterEqual(len(signatures), 3)


class DifficultyMenuTests(unittest.TestCase):
    def tearDown(self) -> None:
        pygame.quit()

    def test_game_starts_in_difficulty_menu(self) -> None:
        game = DoomGame()
        self.assertTrue(game.awaiting_difficulty_selection)
        self.assertEqual("medium", game.difficulty_id)
        game.audio.stop()
        game.music.stop()

    def test_selected_difficulty_persists_across_reset(self) -> None:
        game = DoomGame()
        game._begin_run_with_difficulty("hard")
        self.assertFalse(game.awaiting_difficulty_selection)
        self.assertEqual("hard", game.difficulty_id)
        first_seed = game.world.seed
        game._reset_level(first_seed + 1, reroll_stats=False)
        self.assertEqual("hard", game.difficulty_id)
        self.assertEqual("hard", game.world.difficulty_id)
        game.audio.stop()
        game.music.stop()

    def test_portal_on_level_one_loads_level_two(self) -> None:
        game = DoomGame()
        game.start_run("medium", run_seed=4242)
        exit_zone = game.world.exit_zone
        self.assertIsNotNone(exit_zone)
        required_door = next(door for door in game.world.doors if door.door_id == exit_zone.required_door_id)
        required_door.unlock()
        required_door.begin_open()
        required_door.update(1.0)
        game.player.x = exit_zone.x
        game.player.y = exit_zone.y
        game._check_level_exit()
        game._update(1.0)
        self.assertEqual(2, game.run_state.current_level_index)
        self.assertEqual(2, game.world.level_index)
        self.assertFalse(game.campaign_complete)
        game.audio.stop()
        game.music.stop()

    def test_difficulty_persists_across_campaign_levels(self) -> None:
        game = DoomGame()
        game.start_run("hard", run_seed=9012)
        game.advance_to_next_level()
        self.assertEqual("hard", game.difficulty_id)
        self.assertEqual("hard", game.world.difficulty_id)
        game.audio.stop()
        game.music.stop()

    def test_keys_do_not_carry_over_between_levels(self) -> None:
        game = DoomGame()
        game.start_run("medium", run_seed=7788)
        game.keys_owned.update({"blue", "yellow", "red"})
        game.advance_to_next_level()
        self.assertEqual(set(), game.keys_owned)
        game.audio.stop()
        game.music.stop()

    def test_health_armor_and_ammo_carry_over_between_levels(self) -> None:
        game = DoomGame()
        game.start_run("medium", run_seed=5566)
        game.health = 63
        game.armor = 87
        game.ammo = 21
        game.ammo_pools["SHEL"] = 21
        game.advance_to_next_level()
        self.assertEqual(63, game.health)
        self.assertEqual(87, game.armor)
        self.assertEqual(21, game.ammo)
        self.assertEqual(21, game.ammo_pools["SHEL"])
        game.audio.stop()
        game.music.stop()

    def test_final_campaign_level_terminates_run(self) -> None:
        game = DoomGame()
        game.start_run("medium", run_seed=4433)
        for _ in range(4):
            game.advance_to_next_level()
        self.assertEqual(5, game.run_state.current_level_index)
        game.advance_to_next_level()
        self.assertTrue(game.campaign_complete)
        self.assertEqual(5, len(game.run_state.completed_levels))
        game.audio.stop()
        game.music.stop()

    def test_restart_current_level_after_death_keeps_same_level_seed(self) -> None:
        game = DoomGame()
        game.start_run("medium", run_seed=1357)
        original_seed = game.world.per_level_seed
        game.health = 44
        game.armor = 12
        game.ammo = 17
        game.level_start_snapshot = {
            "health": 44,
            "armor": 12,
            "ammo": 17,
            "ammo_pools": dict(game.ammo_pools),
        }
        game.restart_current_level_after_death()
        self.assertEqual(original_seed, game.world.per_level_seed)
        self.assertEqual(44, game.health)
        self.assertEqual(12, game.armor)
        self.assertEqual(17, game.ammo)
        game.audio.stop()
        game.music.stop()


class CampaignGenerationTests(unittest.TestCase):
    def test_same_run_seed_reproduces_same_full_sequence(self) -> None:
        director = CampaignSequenceDirector()
        run_a = director.build_run_state("medium", 123456)
        run_b = director.build_run_state("medium", 123456)
        sequence_a = []
        sequence_b = []
        for level_index in range(1, director.total_level_count + 1):
            request_a = director.build_generation_request(run_a, level_index)
            request_b = director.build_generation_request(run_b, level_index)
            generated_a = MapGenerator(generation_request=request_a, runtime_pressure_bias=1.0).generate()
            generated_b = MapGenerator(generation_request=request_b, runtime_pressure_bias=1.0).generate()
            sequence_a.append((generated_a.per_level_seed, generated_a.macro_signature, generated_a.level_archetype_id))
            sequence_b.append((generated_b.per_level_seed, generated_b.macro_signature, generated_b.level_archetype_id))
        self.assertEqual(sequence_a, sequence_b)

    def test_campaign_levels_have_distinct_skeletons_and_signatures(self) -> None:
        director = CampaignSequenceDirector()
        run_state = director.build_run_state("medium", 8888)
        generated_levels = [
            MapGenerator(
                generation_request=director.build_generation_request(run_state, level_index),
                runtime_pressure_bias=1.0,
            ).generate()
            for level_index in range(1, director.total_level_count + 1)
        ]
        skeletons = [generated.skeleton_profile_id for generated in generated_levels]
        signatures = [generated.macro_signature for generated in generated_levels]
        self.assertEqual(len(skeletons), len(set(skeletons)))
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_later_campaign_levels_keep_progression_valid(self) -> None:
        director = CampaignSequenceDirector()
        run_state = director.build_run_state("hard", 9999)
        for level_index in range(1, director.total_level_count + 1):
            generated = MapGenerator(
                generation_request=director.build_generation_request(run_state, level_index),
                runtime_pressure_bias=1.0,
            ).generate()
            self.assertTrue(generated.validation_report.valid, level_index)
            self.assertGreater(generated.quality_report.level_identity_score, 2.4, level_index)


if __name__ == "__main__":
    unittest.main()
