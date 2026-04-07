from __future__ import annotations

import math
from pathlib import Path
from array import array
import struct
import pygame

from doomgame import settings
from doomgame.doors import KEY_DEFINITIONS, DOOR_DEFINITIONS, WorldDoor
from doomgame.enemies import ENEMY_DEFINITIONS
from doomgame.loot import PICKUP_DEFINITIONS
from doomgame.player import Player
from doomgame.world import World

try:
    from doomgame import doom_native_renderer
except ImportError:
    doom_native_renderer = None

NATIVE_DOOR_TYPE_INDEX = {
    "normal": 0,
    "blue_locked": 1,
    "yellow_locked": 2,
    "red_locked": 3,
}


class Raycaster:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.camera_plane_scale = math.tan(settings.FOV / 2.0)
        self.native_renderer = doom_native_renderer
        self.framebuffer = bytearray(self.width * self.height * 3)
        self.native_depth_buffer = array("f", [settings.MAX_RAY_DISTANCE]) * self.width
        self.native_surface = pygame.image.frombuffer(self.framebuffer, (self.width, self.height), "RGB")
        self.map_width = 0
        self.map_height = 0
        self.map_bytes = b""
        self.floor_height_bytes = b""
        self.stair_bytes = b""
        self.room_kind_bytes = b""
        self.native_door_buffer = bytearray()
        self.depth_buffer = [settings.MAX_RAY_DISTANCE for _ in range(self.width)]
        self.sprite_depth_buffer = [settings.MAX_RAY_DISTANCE for _ in range(self.width)]
        self.texture_size = settings.TEXTURE_SIZE
        self.wall_textures = self._build_wall_textures()
        self.native_wall_texture_bytes = self._build_native_wall_texture_bytes()
        self.floor_textures = self._build_floor_textures()
        self.native_floor_texture_bytes = self._build_native_floor_texture_bytes()
        self.ceiling_textures = self._build_ceiling_textures()
        self.native_ceiling_texture_bytes = self._build_native_ceiling_texture_bytes()
        self.background = self._build_background()
        self.sky_strip = self._build_sky_strip()
        self.vignette = self._build_vignette()
        self.floor_texture = self._build_floor_texture()
        self.stair_texture = self._build_stair_texture()
        self.ceiling_texture = self._build_ceiling_texture()
        self.horizon_glow = pygame.Surface((self.width, 48), pygame.SRCALPHA)
        self.horizon_glow.fill((118, 214, 140, 255))
        self.weapon_frames = self._load_weapon_frames()
        self.weapon_idle_frame = self._load_weapon_idle_frame()
        self.scaled_weapon_frames = self._prepare_weapon_frames()
        self.scaled_weapon_idle_frame = self._prepare_single_weapon_frame(self.weapon_idle_frame)
        self.pickup_sprites = self._build_pickup_sprites()
        self.door_textures = self._build_door_textures()
        self.exit_sprite = self._make_exit_sprite()
        self.enemy_sprites = self._build_enemy_sprites()
        self.scaled_sprite_cache: dict[tuple[int, int, int], pygame.Surface] = {}
        self.outline_cache: dict[tuple[int, int, int, int], pygame.Surface] = {}
        self.glow_cache: dict[tuple[int, int, int, int, int, int], pygame.Surface] = {}
        (
            self.native_enemy_atlas_bytes,
            self.native_enemy_meta_bytes,
            self.native_enemy_surface_indices,
            self.native_enemy_sprite_count,
            self.native_enemy_cell_size,
        ) = self._build_native_billboard_resources(projectiles=False)
        (
            self.native_projectile_atlas_bytes,
            self.native_projectile_meta_bytes,
            self.native_projectile_surface_indices,
            self.native_projectile_sprite_count,
            self.native_projectile_cell_size,
        ) = self._build_native_billboard_resources(projectiles=True)

    def set_world(self, world: World) -> None:
        self.map_width = world.width
        self.map_height = world.height
        flat_tiles = bytearray(self.map_width * self.map_height)
        flat_heights = bytearray(self.map_width * self.map_height)
        flat_stairs = bytearray(self.map_width * self.map_height)
        flat_kinds = bytearray(self.map_width * self.map_height)
        idx = 0
        for y, row in enumerate(world.tiles):
            for x, tile in enumerate(row):
                flat_tiles[idx] = tile
                flat_heights[idx] = world.floor_heights[y][x]
                flat_stairs[idx] = world.stair_mask[y][x]
                flat_kinds[idx] = max(0, world.room_kinds[y][x])
                idx += 1
        self.map_bytes = bytes(flat_tiles)
        self.floor_height_bytes = bytes(flat_heights)
        self.stair_bytes = bytes(flat_stairs)
        self.room_kind_bytes = bytes(flat_kinds)

    def render(
        self,
        surface: pygame.Surface,
        world: World,
        player: Player,
        time_seconds: float,
        walk_time: float,
        move_amount: float,
        weapon_frame: int = 0,
        muzzle_flash: float = 0.0,
        recoil: float = 0.0,
    ) -> None:
        if self.native_renderer is not None and self.map_bytes:
            self._build_native_door_buffer(world)
            self.native_renderer.render_into(
                self.framebuffer,
                self.native_depth_buffer,
                self.width,
                self.height,
                player.x,
                player.y,
                player.angle,
                player.z,
                self.map_bytes,
                self.floor_height_bytes,
                self.stair_bytes,
                self.room_kind_bytes,
                self.native_door_buffer,
                len(self.native_door_buffer) // 5,
                self.map_width,
                self.map_height,
                time_seconds,
                self.native_wall_texture_bytes,
                self.native_floor_texture_bytes,
                self.native_ceiling_texture_bytes,
            )
            self.depth_buffer = self.native_depth_buffer
            self.sprite_depth_buffer = array("f", self.depth_buffer)
            self._draw_exit_marker(self.native_surface, world, player, time_seconds)
            self._draw_pickups(self.native_surface, world, player, time_seconds)
            if (
                hasattr(self.native_renderer, "render_billboards_into")
                and self.native_enemy_atlas_bytes
                and self.native_enemy_sprite_count > 0
            ):
                enemy_buffer, enemy_count = self._build_native_enemy_instance_buffer(world, player, time_seconds)
                if enemy_count > 0:
                    self.native_renderer.render_billboards_into(
                        self.framebuffer,
                        self.sprite_depth_buffer,
                        self.width,
                        self.height,
                        player.x,
                        player.y,
                        player.angle,
                        player.z,
                        self.floor_height_bytes,
                        self.map_width,
                        self.map_height,
                        enemy_buffer,
                        enemy_count,
                        self.native_enemy_atlas_bytes,
                        self.native_enemy_meta_bytes,
                        self.native_enemy_sprite_count,
                        self.native_enemy_cell_size,
                    )
            else:
                self._draw_enemies(self.native_surface, world, player, time_seconds)
            if (
                hasattr(self.native_renderer, "render_billboards_into")
                and self.native_projectile_atlas_bytes
                and self.native_projectile_sprite_count > 0
            ):
                projectile_buffer, projectile_count = self._build_native_projectile_instance_buffer(world)
                if projectile_count > 0:
                    self.native_renderer.render_billboards_into(
                        self.framebuffer,
                        self.sprite_depth_buffer,
                        self.width,
                        self.height,
                        player.x,
                        player.y,
                        player.angle,
                        player.z,
                        self.floor_height_bytes,
                        self.map_width,
                        self.map_height,
                        projectile_buffer,
                        projectile_count,
                        self.native_projectile_atlas_bytes,
                        self.native_projectile_meta_bytes,
                        self.native_projectile_sprite_count,
                        self.native_projectile_cell_size,
                    )
            else:
                self._draw_enemy_projectiles(self.native_surface, world, player, time_seconds)
            surface.blit(self.native_surface, (0, 0))
        else:
            self._draw_background(surface, player.angle, time_seconds)
            self._draw_floor_and_ceiling(surface, world, player)
            self._draw_walls(surface, world, player)
            self._draw_doors(surface, world, player)
            self.sprite_depth_buffer = array("f", self.depth_buffer)
            self._draw_exit_marker(surface, world, player, time_seconds)
            self._draw_pickups(surface, world, player, time_seconds)
            self._draw_enemies(surface, world, player, time_seconds)
            self._draw_enemy_projectiles(surface, world, player, time_seconds)
        surface.blit(self.vignette, (0, 0))
        self._draw_weapon(surface, time_seconds, walk_time, move_amount, weapon_frame, muzzle_flash, recoil)

    def _build_native_door_buffer(self, world: World) -> None:
        self.native_door_buffer = bytearray()
        for door in world.doors:
            if door.is_open:
                continue
            self.native_door_buffer.extend(
                (
                    door.grid_x & 0xFF,
                    door.grid_y & 0xFF,
                    1 if door.orientation == "vertical" else 0,
                    NATIVE_DOOR_TYPE_INDEX.get(door.door_type, 0),
                    min(255, max(0, int(door.current_lift() * 255.0))),
                )
            )

    def _draw_background(self, surface: pygame.Surface, player_angle: float, time_seconds: float) -> None:
        surface.blit(self.background, (0, 0))
        sky_offset = int((player_angle / math.tau) * (self.sky_strip.get_width() - self.width))
        sky_offset %= max(1, self.sky_strip.get_width() - self.width)
        surface.blit(self.sky_strip, (0, 0), area=(sky_offset, 0, self.width, self.height // 2 + 24))

        pulse = int((math.sin(time_seconds * 0.9) + 1.0) * 0.5 * 22)
        self.horizon_glow.set_alpha(18 + pulse)
        surface.blit(self.horizon_glow, (0, self.height // 2 - 18))

    def _draw_floor_and_ceiling(self, surface: pygame.Surface, world: World, player: Player) -> None:
        eye_z = player.z + 0.5
        horizon = int(self.height // 2 + player.z * self.height * 0.085)
        stride = settings.FLOORCAST_STRIDE

        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale

        ray_dir_x0 = dir_x - plane_x
        ray_dir_y0 = dir_y - plane_y
        ray_dir_x1 = dir_x + plane_x
        ray_dir_y1 = dir_y + plane_y

        for screen_y in range(max(horizon + 2, 0), self.height, stride):
            row_from_horizon = screen_y - horizon
            if row_from_horizon <= 0:
                continue

            row_distance = (eye_z * self.height) / row_from_horizon
            step_x = row_distance * (ray_dir_x1 - ray_dir_x0) / self.width
            step_y = row_distance * (ray_dir_y1 - ray_dir_y0) / self.width

            floor_x = player.x + row_distance * ray_dir_x0
            floor_y = player.y + row_distance * ray_dir_y0

            shade = max(0.18, 1.0 - row_distance / (settings.MAX_RAY_DISTANCE * 0.8))

            for screen_x in range(0, self.width, stride):
                tex_floor_x = int(self.texture_size * (floor_x - math.floor(floor_x))) & (self.texture_size - 1)
                tex_floor_y = int(self.texture_size * (floor_y - math.floor(floor_y))) & (self.texture_size - 1)

                floor_color, ceiling_color = self._sample_floor_and_ceiling(
                    world,
                    floor_x,
                    floor_y,
                    tex_floor_x,
                    tex_floor_y,
                )

                lit_floor = tuple(max(0, min(255, int(channel * shade))) for channel in floor_color[:3])
                lit_ceiling = tuple(
                    max(0, min(255, int(channel * (shade * 0.82 + 0.18)))) for channel in ceiling_color[:3]
                )

                surface.fill(lit_floor, (screen_x, screen_y, stride, stride))
                ceiling_y = horizon - row_from_horizon
                surface.fill(lit_ceiling, (screen_x, ceiling_y, stride, stride))

                floor_x += step_x * stride
                floor_y += step_y * stride

    def _draw_walls(self, surface: pygame.Surface, world: World, player: Player) -> None:
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        eye_z = player.z + 0.5

        for column in range(0, self.width, settings.RAYCAST_STRIDE):
            camera_x = 2.0 * column / self.width - 1.0
            ray_dir_x = dir_x + plane_x * camera_x
            ray_dir_y = dir_y + plane_y * camera_x

            map_x = int(player.x)
            map_y = int(player.y)
            prev_floor = world.get_floor_height_at(map_x, map_y)

            delta_dist_x = abs(1.0 / ray_dir_x) if ray_dir_x else float("inf")
            delta_dist_y = abs(1.0 / ray_dir_y) if ray_dir_y else float("inf")

            if ray_dir_x < 0:
                step_x = -1
                side_dist_x = (player.x - map_x) * delta_dist_x
            else:
                step_x = 1
                side_dist_x = (map_x + 1.0 - player.x) * delta_dist_x

            if ray_dir_y < 0:
                step_y = -1
                side_dist_y = (player.y - map_y) * delta_dist_y
            else:
                step_y = 1
                side_dist_y = (map_y + 1.0 - player.y) * delta_dist_y

            hit = False
            side = 0
            distance = settings.MAX_RAY_DISTANCE
            hit_floor = prev_floor
            hit_height = 1.0
            texture_index = 0
            height_face = False
            steps = 0
            max_steps = world.width * world.height

            while not hit and steps < max_steps:
                steps += 1
                if side_dist_x < side_dist_y:
                    side_dist_x += delta_dist_x
                    map_x += step_x
                    side = 0
                else:
                    side_dist_y += delta_dist_y
                    map_y += step_y
                    side = 1

                if world.is_wall(map_x, map_y):
                    hit = True
                    hit_floor = prev_floor
                    hit_height = 1.0
                    room_kind = 0
                    if 0 <= map_x < world.width and 0 <= map_y < world.height:
                        room_kind = max(0, world.room_kinds[map_y][map_x])
                    texture_index = self._texture_index(map_x, map_y, room_kind)
                    if side == 0:
                        distance = side_dist_x - delta_dist_x
                    else:
                        distance = side_dist_y - delta_dist_y
                else:
                    next_floor = world.get_floor_height_at(map_x, map_y)
                    if next_floor != prev_floor:
                        hit = True
                        hit_floor = min(prev_floor, next_floor)
                        hit_height = abs(next_floor - prev_floor)
                        height_face = True
                        if world.is_stair_at(map_x, map_y) or world.is_stair_at(int(player.x), int(player.y)):
                            texture_index = 5
                        else:
                            texture_index = 3 if next_floor > prev_floor else 0
                        if side == 0:
                            distance = side_dist_x - delta_dist_x
                        else:
                            distance = side_dist_y - delta_dist_y
                    prev_floor = next_floor

                if min(side_dist_x, side_dist_y) > settings.MAX_RAY_DISTANCE:
                    break

            if not hit:
                self.depth_buffer[column] = settings.MAX_RAY_DISTANCE
                continue

            distance = max(distance, 0.0001)
            self.depth_buffer[column] = distance
            wall_top = max(0, self._project_z(eye_z, hit_floor + hit_height, distance))
            wall_bottom = min(self.height, self._project_z(eye_z, hit_floor, distance))
            if wall_bottom <= wall_top:
                continue

            texture = self.wall_textures[texture_index]
            wall_x = player.y + distance * ray_dir_y if side == 0 else player.x + distance * ray_dir_x
            wall_x -= math.floor(wall_x)
            tex_x = int(wall_x * self.texture_size)

            if side == 0 and ray_dir_x > 0:
                tex_x = self.texture_size - tex_x - 1
            if side == 1 and ray_dir_y < 0:
                tex_x = self.texture_size - tex_x - 1

            tex_x = max(0, min(self.texture_size - 1, tex_x))
            draw_height = max(1, wall_bottom - wall_top)
            shade = max(28, 255 - min(220, min(170, int(distance * 12)) + min(120, int(distance * 7) + (36 if side else 0))))
            texels_per_unit = self.texture_size / max(0.001, hit_height)

            for screen_y in range(wall_top, wall_bottom):
                relative = (screen_y - wall_top) / draw_height
                tex_y = int(relative * hit_height * texels_per_unit) & (self.texture_size - 1)
                texel = texture.get_at((tex_x, tex_y))
                lit = (
                    texel.r * shade // 255,
                    texel.g * shade // 255,
                    texel.b * shade // 255,
                )
                surface.fill(lit, (column, screen_y, settings.RAYCAST_STRIDE, 1))
            if height_face:
                trim = (192, 176, 118) if texture_index == 5 else (148, 146, 138)
                surface.fill(trim, (column, wall_top, settings.RAYCAST_STRIDE, min(2, draw_height)))

    def _texture_index(self, map_x: int, map_y: int, room_kind: int = 0) -> int:
        room_palettes = {
            0: (1, 4),      # start
            1: (5, 0),      # storage
            2: (0, 3),      # arena
            3: (1, 4, 2),   # tech
            4: (3, 1),      # shrine
            5: (2, 5, 0),   # cross
        }
        palette = room_palettes.get(room_kind, (0, 1, 2, 3, 4, 5))
        return palette[(map_x * 11 + map_y * 7) % len(palette)]

    def _draw_weapon(
        self,
        surface: pygame.Surface,
        time_seconds: float,
        walk_time: float,
        move_amount: float,
        weapon_frame: int,
        muzzle_flash: float,
        recoil: float,
    ) -> None:
        sway_x = math.sin(walk_time * 0.9) * 9 * move_amount
        bob = math.sin(walk_time * 1.8) * 7 * move_amount + math.sin(time_seconds * 0.8) * 1.5
        recoil_breath = math.sin(time_seconds * 0.55) * 2
        kick_y = recoil * 12.0
        center_x = int(self.width // 2 + sway_x - recoil * 1.5)
        base_y = int(self.height - 142 + bob + recoil_breath + kick_y)
        if not self.scaled_weapon_frames:
            fallback = pygame.Rect(center_x - 120, base_y + 28, 240, 96)
            pygame.draw.rect(surface, (48, 40, 44), fallback, border_radius=18)
            return

        frame_index = max(0, min(len(self.scaled_weapon_frames) - 1, weapon_frame))
        weapon_surface = self.scaled_weapon_frames[frame_index]
        if weapon_frame == 0 and self.scaled_weapon_idle_frame is not None:
            weapon_surface = self.scaled_weapon_idle_frame
        sprite_rect = weapon_surface.get_rect(midbottom=(center_x + 2, self.height + 8 + int(bob * 0.1) + int(kick_y)))
        surface.blit(weapon_surface, sprite_rect)

    def _draw_doors(self, surface: pygame.Surface, world: World, player: Player) -> None:
        eye_z = player.z + 0.5
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)

        for door in world.doors:
            if door.is_open:
                continue
            texture = self.door_textures.get(door.door_type)
            if texture is None:
                continue
            projected_range = self._project_door_column_range(
                door,
                player.x,
                player.y,
                dir_x,
                dir_y,
                plane_x,
                plane_y,
                inv_det,
            )
            if projected_range is None:
                continue
            column_start, column_end = projected_range
            floor_z = world.get_floor_height_at(door.grid_x, door.grid_y)
            lift = door.current_lift()
            visible_height = max(0.02, 1.0 - lift)
            bottom_z = floor_z + lift
            top_z = floor_z + 1.0
            shade_bias = 18 if door.orientation == "vertical" else 32

            for column in range(column_start, column_end, settings.RAYCAST_STRIDE):
                camera_x = 2.0 * column / self.width - 1.0
                ray_dir_x = dir_x + plane_x * camera_x
                ray_dir_y = dir_y + plane_y * camera_x
                hit = self._door_ray_intersection(door, player.x, player.y, ray_dir_x, ray_dir_y)
                if hit is None:
                    continue
                distance, tex_u = hit
                if distance <= 0.0001 or distance >= self.depth_buffer[column]:
                    continue

                wall_top = max(0, self._project_z(eye_z, top_z, distance))
                wall_bottom = min(self.height, self._project_z(eye_z, bottom_z, distance))
                if wall_bottom <= wall_top:
                    continue

                tex_x = min(self.texture_size - 1, max(0, int(tex_u * self.texture_size)))
                draw_height = max(1, wall_bottom - wall_top)
                shade = max(42, 255 - min(188, int(distance * 14) + shade_bias))
                for screen_y in range(wall_top, wall_bottom):
                    relative = (screen_y - wall_top) / draw_height
                    tex_y = int((lift + relative * visible_height) * self.texture_size)
                    tex_y = min(self.texture_size - 1, max(0, tex_y))
                    texel = texture.get_at((tex_x, tex_y))
                    lit = (
                        texel.r * shade // 255,
                        texel.g * shade // 255,
                        texel.b * shade // 255,
                    )
                    surface.fill(lit, (column, screen_y, settings.RAYCAST_STRIDE, 1))
                self.depth_buffer[column] = distance

    def _project_door_column_range(
        self,
        door: WorldDoor,
        player_x: float,
        player_y: float,
        dir_x: float,
        dir_y: float,
        plane_x: float,
        plane_y: float,
        inv_det: float,
    ) -> tuple[int, int] | None:
        endpoints = (
            ((door.grid_x + 0.5), door.grid_y),
            ((door.grid_x + 0.5), door.grid_y + 1.0),
        ) if door.orientation == "vertical" else (
            (door.grid_x, door.grid_y + 0.5),
            (door.grid_x + 1.0, door.grid_y + 0.5),
        )

        columns: list[float] = []
        for world_x, world_y in endpoints:
            dx = world_x - player_x
            dy = world_y - player_y
            transform_x = inv_det * (dir_y * dx - dir_x * dy)
            transform_y = inv_det * (-plane_y * dx + plane_x * dy)
            if transform_y <= 0.05:
                continue
            columns.append((self.width / 2) * (1 + transform_x / transform_y))

        if not columns:
            center_x, center_y = door.center
            dx = center_x - player_x
            dy = center_y - player_y
            transform_x = inv_det * (dir_y * dx - dir_x * dy)
            transform_y = inv_det * (-plane_y * dx + plane_x * dy)
            if transform_y <= 0.05:
                return None
            center_column = (self.width / 2) * (1 + transform_x / transform_y)
            half_width = max(6, int(self.width / transform_y * 0.32))
            columns = [center_column - half_width, center_column + half_width]

        start = max(0, int(min(columns)) - 2)
        end = min(self.width, int(max(columns)) + 3)
        if end <= start:
            return None
        return (start, end)

    def _door_ray_intersection(
        self,
        door: WorldDoor,
        player_x: float,
        player_y: float,
        ray_dir_x: float,
        ray_dir_y: float,
    ) -> tuple[float, float] | None:
        if door.orientation == "vertical":
            if abs(ray_dir_x) < 0.00001:
                return None
            door_x = door.grid_x + 0.5
            distance = (door_x - player_x) / ray_dir_x
            if distance <= 0.0:
                return None
            hit_y = player_y + ray_dir_y * distance
            if not (door.grid_y <= hit_y <= door.grid_y + 1.0):
                return None
            return (distance, hit_y - door.grid_y)

        if abs(ray_dir_y) < 0.00001:
            return None
        door_y = door.grid_y + 0.5
        distance = (door_y - player_y) / ray_dir_y
        if distance <= 0.0:
            return None
        hit_x = player_x + ray_dir_x * distance
        if not (door.grid_x <= hit_x <= door.grid_x + 1.0):
            return None
        return (distance, hit_x - door.grid_x)

    def _draw_pickups(
        self,
        surface: pygame.Surface,
        world: World,
        player: Player,
        time_seconds: float,
    ) -> None:
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
        eye_z = player.z + 0.5

        visible: list[tuple[float, float, float, object]] = []
        for pickup in [*world.active_loot(), *world.active_keys(), *world.active_switches(), *world.visible_secrets()]:
            dx = pickup.x - player.x
            dy = pickup.y - player.y
            distance = math.hypot(dx, dy)
            if distance < 0.1 or distance > settings.MAX_RAY_DISTANCE:
                continue

            transform_x = inv_det * (dir_y * dx - dir_x * dy)
            transform_y = inv_det * (-plane_y * dx + plane_x * dy)
            if transform_y <= 0.1:
                continue
            visible.append((transform_y, transform_x, distance, pickup))

        for transform_y, transform_x, distance, pickup in sorted(
            visible,
            key=lambda item: (item[0], item[2], item[1]),
            reverse=True,
        ):
            sprite = self.pickup_sprites.get(pickup.sprite_kind)
            if sprite is None:
                continue
            if hasattr(pickup, "definition"):
                definition = pickup.definition
                bob_phase = getattr(pickup, "bob_phase", 0.0)
                pickup_scale = getattr(pickup, "scale", definition.visual.world_scale)
                hover_height = definition.visual.hover_height
                glow_color = definition.visual.glow_color
            else:
                bob_phase = 0.0
                pickup_scale = 0.82
                hover_height = 0.22 if pickup.sprite_kind.startswith("switch") else 0.16
                glow_color = (116, 224, 168) if pickup.sprite_kind.startswith("switch") else (188, 162, 92)
            bob = math.sin(time_seconds * 2.8 + bob_phase) * 0.055
            floor_z = world.get_floor_height(pickup.x, pickup.y) + hover_height + bob
            screen_x = int((self.width / 2) * (1 + transform_x / transform_y))
            sprite_height = max(18, int(self.height / transform_y * (0.84 * pickup_scale)))
            sprite_width = max(10, int(sprite_height * sprite.get_width() / max(1, sprite.get_height())))
            scaled = self._get_scaled_sprite(sprite, sprite_width, sprite_height)
            bottom_y = self._project_z(eye_z, floor_z, transform_y)
            sprite_rect = scaled.get_rect(midbottom=(screen_x, bottom_y))
            if sprite_rect.right < 0 or sprite_rect.left > self.width:
                continue

            visible_columns = self._visible_sprite_columns(sprite_rect, scaled.get_width(), transform_y)
            if not visible_columns:
                continue

            glow_rect = sprite_rect.inflate(14, 10)
            glow = self._make_pickup_glow(glow_rect.size, glow_color, distance)
            outline = pygame.mask.from_surface(scaled).to_surface(
                setcolor=(255, 244, 210, 120),
                unsetcolor=(0, 0, 0, 0),
            )
            glow_border = max(0, (glow.get_width() - scaled.get_width()) // 2)
            self._blit_columns(
                surface,
                glow,
                glow_rect,
                visible_columns,
                target_dx=glow_rect.left - sprite_rect.left,
                source_dx=glow_border,
            )

            for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                outline_rect = sprite_rect.move(offset_x, offset_y)
                self._blit_columns(surface, outline, outline_rect, visible_columns, target_dx=offset_x)

            self._blit_columns(surface, scaled, sprite_rect, visible_columns, write_depth=True, depth=transform_y)

    def _draw_enemies(
        self,
        surface: pygame.Surface,
        world: World,
        player: Player,
        time_seconds: float,
    ) -> None:
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
        eye_z = player.z + 0.5

        visible: list[tuple[float, float, float, object]] = []
        for enemy in world.active_enemies(include_corpses=True):
            dx = enemy.x - player.x
            dy = enemy.y - player.y
            distance = math.hypot(dx, dy)
            if distance < 0.12 or distance > settings.MAX_RAY_DISTANCE:
                continue
            transform_x = inv_det * (dir_y * dx - dir_x * dy)
            transform_y = inv_det * (-plane_y * dx + plane_x * dy)
            if transform_y <= 0.1:
                continue
            visible.append((transform_y, transform_x, distance, enemy))

        for transform_y, transform_x, distance, enemy in sorted(visible, reverse=True):
            sprite = self._enemy_sprite(enemy, player_distance=distance)
            if sprite is None:
                continue
            visual = enemy.definition.visual
            floor_z = world.get_floor_height(enemy.x, enemy.y)
            if enemy.dead:
                floor_z += 0.06
            else:
                floor_z += 0.02 + math.sin(time_seconds * 3.2 + enemy.room_index * 0.7) * 0.012
            screen_x = int((self.width / 2) * (1 + transform_x / transform_y))
            sprite_height = max(24, int(self.height / transform_y * (visual.height_scale * visual.sprite_scale)))
            sprite_width = max(16, int(sprite_height * sprite.get_width() / max(1, sprite.get_height())))
            scaled = pygame.transform.smoothscale(sprite, (sprite_width, sprite_height))
            bottom_y = self._project_z(eye_z, floor_z, transform_y)
            sprite_rect = scaled.get_rect(midbottom=(screen_x, bottom_y))
            if sprite_rect.right < 0 or sprite_rect.left > self.width:
                continue

            visible_columns = self._visible_sprite_columns(sprite_rect, scaled.get_width(), transform_y)
            if not visible_columns:
                continue

            if not enemy.dead:
                glow_rect = sprite_rect.inflate(18, 12)
                glow = self._make_pickup_glow(glow_rect.size, visual.glow_color, distance + 2.0)
                glow_border = max(0, (glow.get_width() - scaled.get_width()) // 2)
                self._blit_columns(
                    surface,
                    glow,
                    glow_rect,
                    visible_columns,
                    target_dx=glow_rect.left - sprite_rect.left,
                    source_dx=glow_border,
                )

            outline_alpha = 110 if enemy.dead else 138
            outline_color = (38, 24, 18, outline_alpha)
            outline = self._get_outline_surface(scaled, outline_alpha)
            for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                self._blit_columns(surface, outline, sprite_rect.move(offset_x, offset_y), visible_columns, target_dx=offset_x)

            self._blit_columns(surface, scaled, sprite_rect, visible_columns, write_depth=True, depth=transform_y)

    def _draw_enemy_projectiles(
        self,
        surface: pygame.Surface,
        world: World,
        player: Player,
        time_seconds: float,
    ) -> None:
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
        eye_z = player.z + 0.5

        visible: list[tuple[float, float, float, object]] = []
        for projectile in world.active_enemy_projectiles():
            dx = projectile.x - player.x
            dy = projectile.y - player.y
            distance = math.hypot(dx, dy)
            if distance < 0.08 or distance > settings.MAX_RAY_DISTANCE:
                continue
            transform_x = inv_det * (dir_y * dx - dir_x * dy)
            transform_y = inv_det * (-plane_y * dx + plane_x * dy)
            if transform_y <= 0.08:
                continue
            visible.append((transform_y, transform_x, distance, projectile))

        for transform_y, transform_x, distance, projectile in sorted(visible, reverse=True):
            sprite = self._projectile_sprite(projectile)
            if sprite is None:
                continue
            owner_visual = ENEMY_DEFINITIONS[projectile.owner_type].visual
            screen_x = int((self.width / 2) * (1 + transform_x / transform_y))
            small_projectile = projectile.owner_type in {"grunt", "heavy"}
            base_scale = 0.14 if small_projectile else 0.6
            min_size = 4 if small_projectile else 10
            sprite_height = max(min_size, int(self.height / transform_y * base_scale))
            sprite_width = max(min_size, int(sprite_height * sprite.get_width() / max(1, sprite.get_height())))
            scaled = self._get_scaled_sprite(sprite, sprite_width, sprite_height)
            floor_z = world.get_floor_height(projectile.x, projectile.y) + 0.34 + math.sin(projectile.bob_phase) * 0.04
            bottom_y = self._project_z(eye_z, floor_z, transform_y)
            sprite_rect = scaled.get_rect(center=(screen_x, bottom_y - sprite_height // 2))
            if sprite_rect.right < 0 or sprite_rect.left > self.width:
                continue
            visible_columns = self._visible_sprite_columns(sprite_rect, scaled.get_width(), transform_y)
            if not visible_columns:
                continue
            trail_rect = sprite_rect.inflate(18, 12)
            glow = self._make_pickup_glow(trail_rect.size, owner_visual.projectile_color, max(0.5, distance * 0.7))
            glow_border = max(0, (glow.get_width() - scaled.get_width()) // 2)
            self._blit_columns(
                surface,
                glow,
                trail_rect,
                visible_columns,
                target_dx=trail_rect.left - sprite_rect.left,
                source_dx=glow_border,
            )
            self._blit_columns(surface, scaled, sprite_rect, visible_columns, write_depth=True, depth=transform_y)

    def _draw_exit_marker(
        self,
        surface: pygame.Surface,
        world: World,
        player: Player,
        time_seconds: float,
    ) -> None:
        if world.exit_zone is None or self.exit_sprite is None:
            return
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
        dx = world.exit_zone.x - player.x
        dy = world.exit_zone.y - player.y
        distance = math.hypot(dx, dy)
        if distance < 0.1 or distance > settings.MAX_RAY_DISTANCE:
            return
        transform_x = inv_det * (dir_y * dx - dir_x * dy)
        transform_y = inv_det * (-plane_y * dx + plane_x * dy)
        if transform_y <= 0.1:
            return

        pulse = 0.78 + (0.22 if world.is_exit_active() else 0.08) * (math.sin(time_seconds * 4.2) * 0.5 + 0.5)
        floor_z = world.get_floor_height(world.exit_zone.x, world.exit_zone.y) + 0.05
        screen_x = int((self.width / 2) * (1 + transform_x / transform_y))
        sprite_height = max(20, int(self.height / transform_y * pulse))
        sprite_width = max(20, int(sprite_height * self.exit_sprite.get_width() / max(1, self.exit_sprite.get_height())))
        scaled = self._get_scaled_sprite(self.exit_sprite, sprite_width, sprite_height)
        bottom_y = self._project_z(player.z + 0.5, floor_z, transform_y)
        sprite_rect = scaled.get_rect(midbottom=(screen_x, bottom_y))
        if sprite_rect.right < 0 or sprite_rect.left > self.width:
            return
        visible_columns = self._visible_sprite_columns(sprite_rect, scaled.get_width(), transform_y)
        if not visible_columns:
            return
        glow_color = (120, 255, 168) if world.is_exit_active() else (82, 126, 104)
        glow_rect = sprite_rect.inflate(20, 12)
        glow = self._make_pickup_glow(glow_rect.size, glow_color, distance)
        glow_border = max(0, (glow.get_width() - scaled.get_width()) // 2)
        self._blit_columns(
            surface,
            glow,
            glow_rect,
            visible_columns,
            target_dx=glow_rect.left - sprite_rect.left,
            source_dx=glow_border,
        )
        self._blit_columns(surface, scaled, sprite_rect, visible_columns)

    def _visible_sprite_columns(
        self,
        sprite_rect: pygame.Rect,
        source_width: int,
        depth: float,
    ) -> list[tuple[int, int]]:
        visible_columns: list[tuple[int, int]] = []
        start_x = max(0, sprite_rect.left)
        end_x = min(self.width, sprite_rect.right)
        for screen_col in range(start_x, end_x):
            if depth >= self.sprite_depth_buffer[screen_col] - 0.015:
                continue
            relative = (screen_col - sprite_rect.left) / max(1, sprite_rect.width)
            source_col = min(source_width - 1, max(0, int(relative * source_width)))
            visible_columns.append((screen_col, source_col))
        return visible_columns

    def _blit_columns(
        self,
        surface: pygame.Surface,
        sprite: pygame.Surface,
        target_rect: pygame.Rect,
        visible_columns: list[tuple[int, int]],
        target_dx: int = 0,
        source_dx: int = 0,
        write_depth: bool = False,
        depth: float | None = None,
    ) -> None:
        for screen_col, source_col in visible_columns:
            target_x = screen_col + target_dx
            if not (0 <= target_x < self.width):
                continue
            source_x = min(sprite.get_width() - 1, max(0, source_col + source_dx))
            surface.blit(sprite, (target_x, target_rect.top), area=(source_x, 0, 1, sprite.get_height()))
            if write_depth and depth is not None and 0 <= screen_col < len(self.sprite_depth_buffer):
                self.sprite_depth_buffer[screen_col] = min(self.sprite_depth_buffer[screen_col], depth)

    def _make_pickup_glow(
        self,
        size: tuple[int, int],
        glow_color: tuple[int, int, int],
        distance: float,
    ) -> pygame.Surface:
        width, height = size
        if width <= 0 or height <= 0:
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        distance_bucket = max(1, int(distance * 2.0))
        cache_key = (width, height, glow_color[0], glow_color[1], glow_color[2], distance_bucket)
        cached = self.glow_cache.get(cache_key)
        if cached is not None:
            return cached
        glow = pygame.Surface(size, pygame.SRCALPHA)
        alpha = max(24, 86 - int(distance * 4.0))
        pygame.draw.ellipse(glow, (*glow_color, alpha), glow.get_rect())
        inner = glow.get_rect().inflate(-max(4, size[0] // 4), -max(4, size[1] // 4))
        pygame.draw.ellipse(glow, (*glow_color, max(0, alpha - 18)), inner)
        if len(self.glow_cache) > 512:
            self.glow_cache.clear()
        self.glow_cache[cache_key] = glow
        return glow

    def _quantize_sprite_size(self, width: int, height: int) -> tuple[int, int]:
        max_dim = max(width, height)
        step = 4 if max_dim >= 96 else 2
        quantized_width = max(1, int(round(width / step) * step))
        quantized_height = max(1, int(round(height / step) * step))
        return quantized_width, quantized_height

    def _get_scaled_sprite(self, sprite: pygame.Surface, width: int, height: int) -> pygame.Surface:
        width, height = self._quantize_sprite_size(width, height)
        cache_key = (id(sprite), width, height)
        cached = self.scaled_sprite_cache.get(cache_key)
        if cached is not None:
            return cached
        scaled = pygame.transform.scale(sprite, (width, height)).convert_alpha()
        if len(self.scaled_sprite_cache) > 1024:
            self.scaled_sprite_cache.clear()
            self.outline_cache.clear()
        self.scaled_sprite_cache[cache_key] = scaled
        return scaled

    def _get_outline_surface(self, sprite: pygame.Surface, alpha: int) -> pygame.Surface:
        cache_key = (id(sprite), sprite.get_width(), sprite.get_height(), alpha)
        cached = self.outline_cache.get(cache_key)
        if cached is not None:
            return cached
        outline = pygame.mask.from_surface(sprite).to_surface(
            setcolor=(38, 24, 18, alpha),
            unsetcolor=(0, 0, 0, 0),
        )
        if len(self.outline_cache) > 1024:
            self.outline_cache.clear()
        self.outline_cache[cache_key] = outline
        return outline

    def _build_native_billboard_resources(
        self,
        projectiles: bool,
    ) -> tuple[bytes, bytes, dict[int, int], int, int]:
        cell_size = 128 if not projectiles else 64
        atlas_surfaces: list[pygame.Surface] = []
        surface_indices: dict[int, int] = {}
        for sprite_sets in self.enemy_sprites.values():
            state_names = ("projectile",) if projectiles else ("idle", "alert", "walk", "attack", "pain", "dead")
            for state_name in state_names:
                for sprite in sprite_sets.get(state_name, []):
                    if sprite is None:
                        continue
                    sprite_id = id(sprite)
                    if sprite_id in surface_indices:
                        continue
                    surface_indices[sprite_id] = len(atlas_surfaces)
                    atlas_surfaces.append(sprite)
        if not atlas_surfaces:
            return b"", b"", {}, 0, cell_size

        atlas = pygame.Surface((cell_size * len(atlas_surfaces), cell_size), pygame.SRCALPHA)
        meta = array("H")
        for index, sprite in enumerate(atlas_surfaces):
            source_width = sprite.get_width()
            source_height = sprite.get_height()
            fit_scale = min(1.0, min(cell_size / max(1, source_width), cell_size / max(1, source_height)))
            fitted_width = max(1, min(cell_size, int(source_width * fit_scale)))
            fitted_height = max(1, min(cell_size, int(source_height * fit_scale)))
            prepared = sprite
            if fitted_width != source_width or fitted_height != source_height:
                prepared = pygame.transform.smoothscale(sprite, (fitted_width, fitted_height)).convert_alpha()
            offset_x = index * cell_size + (cell_size - fitted_width) // 2
            offset_y = cell_size - fitted_height
            atlas.blit(prepared, (offset_x, offset_y))
            meta.extend((offset_x, offset_y, fitted_width, fitted_height))
        return (
            pygame.image.tostring(atlas, "RGBA"),
            meta.tobytes(),
            surface_indices,
            len(atlas_surfaces),
            cell_size,
        )

    def _build_native_enemy_instance_buffer(
        self,
        world: World,
        player: Player,
        time_seconds: float,
    ) -> tuple[bytes, int]:
        instances = bytearray()
        count = 0
        for enemy in world.active_enemies(include_corpses=True):
            distance = math.hypot(enemy.x - player.x, enemy.y - player.y)
            sprite = self._enemy_sprite(enemy, player_distance=distance)
            if sprite is None:
                continue
            sprite_index = self.native_enemy_surface_indices.get(id(sprite))
            if sprite_index is None:
                continue
            visual = enemy.definition.visual
            z_offset = 0.06 if enemy.dead else 0.02 + math.sin(time_seconds * 3.2 + enemy.room_index * 0.7) * 0.012
            projected_scale = visual.height_scale * visual.sprite_scale
            instances.extend(
                struct.pack(
                    "<ffffHHI",
                    enemy.x,
                    enemy.y,
                    z_offset,
                    projected_scale,
                    16,
                    24,
                    sprite_index,
                )
            )
            count += 1
        return bytes(instances), count

    def _build_native_projectile_instance_buffer(self, world: World) -> tuple[bytes, int]:
        instances = bytearray()
        count = 0
        for projectile in world.active_enemy_projectiles():
            sprite = self._projectile_sprite(projectile)
            if sprite is None:
                continue
            sprite_index = self.native_projectile_surface_indices.get(id(sprite))
            if sprite_index is None:
                continue
            small_projectile = projectile.owner_type in {"grunt", "heavy"}
            base_scale = 0.14 if small_projectile else 0.6
            min_size = 4 if small_projectile else 10
            z_offset = 0.34 + math.sin(projectile.bob_phase) * 0.04
            instances.extend(
                struct.pack(
                    "<ffffHHI",
                    projectile.x,
                    projectile.y,
                    z_offset,
                    base_scale,
                    min_size,
                    min_size,
                    sprite_index,
                )
            )
            count += 1
        return bytes(instances), count

    def _build_depth_buffer(self, world: World, player: Player) -> list[float]:
        depth_buffer = [settings.MAX_RAY_DISTANCE for _ in range(self.width)]
        dir_x = math.cos(player.angle)
        dir_y = math.sin(player.angle)
        plane_x = -dir_y * self.camera_plane_scale
        plane_y = dir_x * self.camera_plane_scale

        for column in range(self.width):
            camera_x = 2.0 * column / self.width - 1.0
            ray_dir_x = dir_x + plane_x * camera_x
            ray_dir_y = dir_y + plane_y * camera_x

            map_x = int(player.x)
            map_y = int(player.y)

            delta_dist_x = abs(1.0 / ray_dir_x) if ray_dir_x else float("inf")
            delta_dist_y = abs(1.0 / ray_dir_y) if ray_dir_y else float("inf")

            if ray_dir_x < 0:
                step_x = -1
                side_dist_x = (player.x - map_x) * delta_dist_x
            else:
                step_x = 1
                side_dist_x = (map_x + 1.0 - player.x) * delta_dist_x

            if ray_dir_y < 0:
                step_y = -1
                side_dist_y = (player.y - map_y) * delta_dist_y
            else:
                step_y = 1
                side_dist_y = (map_y + 1.0 - player.y) * delta_dist_y

            distance = settings.MAX_RAY_DISTANCE
            for _ in range(world.width * world.height):
                if side_dist_x < side_dist_y:
                    side_dist_x += delta_dist_x
                    map_x += step_x
                    side = 0
                else:
                    side_dist_y += delta_dist_y
                    map_y += step_y
                    side = 1

                if world.is_wall(map_x, map_y):
                    distance = (side_dist_x - delta_dist_x) if side == 0 else (side_dist_y - delta_dist_y)
                    break
                if min(side_dist_x, side_dist_y) > settings.MAX_RAY_DISTANCE:
                    break

            depth_buffer[column] = max(0.0001, distance)
        return depth_buffer

    def _load_weapon_frames(self) -> list[pygame.Surface]:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        frames: list[pygame.Surface] = []
        for index in range(1, 6):
            sprite_path = assets_dir / f"weapon_shotgun_{index}.png"
            if not sprite_path.exists():
                continue
            raw = pygame.image.load(str(sprite_path)).convert_alpha()
            bounds = raw.get_bounding_rect()
            frame = raw if bounds.width <= 0 or bounds.height <= 0 else raw.subsurface(bounds).copy()
            frames.append(frame)
        return frames

    def _load_weapon_idle_frame(self) -> pygame.Surface | None:
        return self._load_trimmed_asset("weapon_shotgun_idle.png")

    def _load_trimmed_asset(self, asset_name: str) -> pygame.Surface | None:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        sprite_path = assets_dir / asset_name
        if not sprite_path.exists():
            return None
        raw = pygame.image.load(str(sprite_path)).convert_alpha()
        bounds = raw.get_bounding_rect()
        return raw if bounds.width <= 0 or bounds.height <= 0 else raw.subsurface(bounds).copy()

    def _prepare_weapon_frames(self) -> list[pygame.Surface]:
        if not self.weapon_frames:
            return []
        scaled_frames: list[pygame.Surface] = []
        for frame in self.weapon_frames:
            prepared = self._prepare_single_weapon_frame(frame)
            if prepared is not None:
                scaled_frames.append(prepared)
        return scaled_frames

    def _prepare_single_weapon_frame(
        self,
        frame: pygame.Surface | None,
        scale_multiplier: float = 1.0,
    ) -> pygame.Surface | None:
        if frame is None:
            return None
        scale = self.width / 820 * scale_multiplier
        sprite_width = max(1, int(frame.get_width() * scale))
        sprite_height = max(1, int(frame.get_height() * scale))
        return pygame.transform.smoothscale(frame, (sprite_width, sprite_height)).convert_alpha()

    def _build_pickup_sprites(self) -> dict[str, pygame.Surface]:
        sprites = {
            "shells": self._make_shell_sprite((188, 54, 46), 22, 28),
            "shell_box": self._make_shell_box_sprite(),
            "stimpack": self._make_med_sprite((70, 208, 120), small=True),
            "medkit": self._make_med_sprite((198, 236, 208), small=False),
            "armor_bonus": self._make_armor_bonus_sprite(),
            "green_armor": self._make_armor_sprite(),
            "switch_off": self._make_switch_sprite(active=False),
            "switch_on": self._make_switch_sprite(active=True),
            "secret": self._make_secret_sprite(),
        }
        for key_type, definition in KEY_DEFINITIONS.items():
            sprites[f"{key_type}_key"] = self._make_key_sprite(
                definition.visual.sprite_primary,
                definition.visual.sprite_secondary,
            )
        return sprites

    def _build_enemy_sprites(self) -> dict[str, dict[str, list[pygame.Surface]]]:
        sprites: dict[str, dict[str, list[pygame.Surface]]] = {}
        for enemy_type, definition in ENEMY_DEFINITIONS.items():
            external_sprites = self._load_external_enemy_sprites(enemy_type)
            if external_sprites is not None:
                sprites[enemy_type] = external_sprites
                continue
            visual = definition.visual
            sprites[enemy_type] = {
                "idle": [
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "idle", frame=0, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "idle", frame=1, is_dead=False),
                ],
                "alert": [
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "alert", frame=0, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "alert", frame=1, is_dead=False),
                ],
                "walk": [
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "walk", frame=0, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "walk", frame=1, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "walk", frame=2, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "walk", frame=3, is_dead=False),
                ],
                "attack": [
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "attack", frame=0, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "attack", frame=1, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "attack", frame=2, is_dead=False),
                ],
                "pain": [
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "pain", frame=0, is_dead=False),
                    self._make_enemy_sprite(enemy_type, visual.base_color, visual.accent_color, "pain", frame=1, is_dead=False),
                ],
                "dead": [
                    self._make_enemy_sprite(enemy_type, visual.corpse_color, visual.accent_color, "dead", frame=0, is_dead=True),
                    self._make_enemy_sprite(enemy_type, visual.corpse_color, visual.accent_color, "dead", frame=1, is_dead=True),
                ],
                "projectile": [
                    self._make_projectile_sprite(visual.projectile_color, visual.accent_color, frame=0),
                    self._make_projectile_sprite(visual.projectile_color, visual.accent_color, frame=1),
                ],
            }
        return sprites

    def _load_external_enemy_sprites(self, enemy_type: str) -> dict[str, list[pygame.Surface]] | None:
        if enemy_type == "charger":
            idle = self._load_sprite_asset(f"{enemy_type}_idle.png")
            walk_close = self._load_sprite_asset(f"{enemy_type}_walk_01.png")
            walk_far = self._load_sprite_asset(f"{enemy_type}_walk_02.png")
            attack = self._load_sprite_asset(f"{enemy_type}_attack.png")
            dead = self._load_sprite_asset(f"{enemy_type}_dead.png")

            if idle is None or walk_close is None or walk_far is None or attack is None or dead is None:
                return None

            return {
                "idle": [idle],
                "alert": [idle],
                "walk": [walk_close, walk_far],
                "attack": [attack],
                "pain": [idle],
                "dead": [dead],
                "projectile": [],
            }

        if enemy_type == "grunt":
            idle = self._load_sprite_asset(f"{enemy_type}_idle.png")
            walk_01 = self._load_sprite_asset(f"{enemy_type}_walk_01.png")
            walk_02 = self._load_sprite_asset(f"{enemy_type}_walk_02.png")
            attack = self._load_sprite_asset(f"{enemy_type}_attack.png")
            dead = self._load_sprite_asset(f"{enemy_type}_dead.png")
            projectile = self._load_sprite_asset(f"{enemy_type}_projectile.png")

            if idle is None or walk_01 is None or walk_02 is None or attack is None or dead is None:
                return None

            return {
                "idle": [idle],
                "alert": [idle],
                "walk": [walk_01, walk_02],
                "attack": [attack],
                "pain": [idle],
                "dead": [dead],
                "projectile": [projectile] if projectile is not None else [],
            }

        if enemy_type == "heavy":
            idle = self._load_sprite_asset(f"{enemy_type}_idle.png")
            walk_01 = self._load_sprite_asset(f"{enemy_type}_walk_01.png")
            walk_02 = self._load_sprite_asset(f"{enemy_type}_walk_02.png")
            attack = self._load_sprite_asset(f"{enemy_type}_attack.png")
            dead = self._load_sprite_asset(f"{enemy_type}_dead.png")
            projectile = self._load_sprite_asset(f"{enemy_type}_projectile.png")

            if idle is None or walk_01 is None or walk_02 is None or attack is None or dead is None:
                return None

            return {
                "idle": [idle],
                "alert": [idle],
                "walk": [walk_01, walk_02],
                "attack": [attack],
                "pain": [idle],
                "dead": [dead],
                "projectile": [projectile] if projectile is not None else [],
            }

        if enemy_type == "warden":
            idle = self._load_sprite_asset(f"{enemy_type}_idle.png")
            walk_01 = self._load_sprite_asset(f"{enemy_type}_walk_01.png")
            walk_02 = self._load_sprite_asset(f"{enemy_type}_walk_02.png")
            attack = self._load_sprite_asset(f"{enemy_type}_attack.png")
            dead = self._load_sprite_asset(f"{enemy_type}_dead.png")
            projectile = self._load_sprite_asset(f"{enemy_type}_projectile.png")

            if idle is None or walk_01 is None or walk_02 is None or attack is None or dead is None:
                return None

            return {
                "idle": [idle],
                "alert": [idle],
                "walk": [walk_01, walk_02],
                "attack": [attack],
                "pain": [idle],
                "dead": [dead],
                "projectile": [projectile] if projectile is not None else [],
            }

        return None

    def _load_sprite_asset(self, asset_name: str) -> pygame.Surface | None:
        path = Path(__file__).resolve().parent.parent / "assets" / asset_name
        if not path.exists():
            return None
        return pygame.image.load(str(path)).convert_alpha()

    def _build_door_textures(self) -> dict[str, pygame.Surface]:
        textures: dict[str, pygame.Surface] = {}
        for door_type, definition in DOOR_DEFINITIONS.items():
            textures[door_type] = self._make_door_texture(
                definition.visual.base_color,
                definition.visual.accent_color,
            )
        return textures

    def _make_door_texture(
        self,
        base_color: tuple[int, int, int],
        accent_color: tuple[int, int, int],
    ) -> pygame.Surface:
        size = self.texture_size
        door = pygame.Surface((size, size))
        door.fill(base_color)
        dark = tuple(max(0, channel - 28) for channel in base_color)
        light = tuple(min(255, channel + 36) for channel in base_color)
        for x in range(0, size, 8):
            pygame.draw.line(door, dark if (x // 8) % 2 else light, (x, 0), (x, size))
        pygame.draw.rect(door, dark, (6, 6, size - 12, size - 12), 3)
        pygame.draw.rect(door, accent_color, (size // 2 - 8, 8, 16, size - 16), border_radius=3)
        pygame.draw.rect(door, light, (size // 2 - 4, 14, 8, size - 28), border_radius=2)
        pygame.draw.rect(door, dark, (size // 2 - 1, size // 2 - 6, 2, 12))
        for y in range(12, size - 12, 10):
            pygame.draw.line(door, dark, (10, y), (size - 10, y), 1)
        return door

    def _make_key_sprite(
        self,
        primary: tuple[int, int, int],
        secondary: tuple[int, int, int],
    ) -> pygame.Surface:
        sprite = pygame.Surface((26, 28), pygame.SRCALPHA)
        pygame.draw.circle(sprite, secondary, (8, 10), 6, 2)
        pygame.draw.rect(sprite, primary, (8, 8, 13, 4), border_radius=2)
        pygame.draw.rect(sprite, primary, (16, 10, 3, 11), border_radius=1)
        pygame.draw.rect(sprite, secondary, (17, 14, 6, 2), border_radius=1)
        pygame.draw.rect(sprite, secondary, (17, 18, 4, 2), border_radius=1)
        pygame.draw.circle(sprite, secondary, (8, 10), 2)
        pygame.draw.rect(sprite, (44, 36, 28), (8, 8, 13, 4), 1, border_radius=2)
        return sprite

    def _make_exit_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((34, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(sprite, (72, 168, 112, 110), (1, 4, 32, 12))
        pygame.draw.ellipse(sprite, (180, 255, 214, 180), (6, 7, 22, 6))
        pygame.draw.ellipse(sprite, (34, 72, 52, 180), (0, 3, 34, 12), 2)
        return sprite

    def _make_switch_sprite(self, active: bool) -> pygame.Surface:
        sprite = pygame.Surface((26, 30), pygame.SRCALPHA)
        frame = (66, 74, 84) if not active else (58, 108, 82)
        panel = (192, 178, 132) if not active else (166, 238, 184)
        lamp = (218, 112, 84) if not active else (122, 255, 176)
        pygame.draw.rect(sprite, frame, (3, 3, 20, 24), border_radius=4)
        pygame.draw.rect(sprite, (28, 20, 18), (5, 5, 16, 20), border_radius=3)
        pygame.draw.rect(sprite, panel, (8, 8, 10, 4), border_radius=1)
        pygame.draw.rect(sprite, panel, (8, 14, 10, 4), border_radius=1)
        pygame.draw.circle(sprite, lamp, (13, 22), 4)
        pygame.draw.rect(sprite, (36, 28, 24), (3, 3, 20, 24), 2, border_radius=4)
        return sprite

    def _make_secret_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.polygon(sprite, (184, 156, 86), [(12, 2), (22, 12), (12, 22), (2, 12)])
        pygame.draw.polygon(sprite, (248, 226, 144), [(12, 4), (20, 12), (12, 20), (4, 12)], 2)
        pygame.draw.circle(sprite, (94, 42, 18), (12, 12), 3)
        return sprite

    def _enemy_sprite(self, enemy, player_distance: float | None = None) -> pygame.Surface | None:
        sprite_sets = self.enemy_sprites.get(enemy.enemy_type)
        if sprite_sets is None:
            return None
        state = enemy.sprite_state()
        frames = sprite_sets.get(state) or sprite_sets["idle"]
        if enemy.enemy_type == "charger" and not enemy.dead and player_distance is not None:
            if state == "attack":
                return sprite_sets["attack"][0]
            if state in {"walk", "alert"} and len(frames) >= 2:
                close_threshold = enemy.definition.attack_range + settings.PLAYER_RADIUS + 0.28
                return frames[0] if player_distance <= close_threshold else frames[1]
        return frames[enemy.sprite_frame() % len(frames)]

    def _projectile_sprite(self, projectile) -> pygame.Surface | None:
        sprite_sets = self.enemy_sprites.get(projectile.owner_type)
        if sprite_sets is None:
            return None
        frames = sprite_sets.get("projectile")
        if not frames:
            return None
        return frames[int(projectile.animation_timer * 10.0) % len(frames)]

    def _make_enemy_sprite(
        self,
        enemy_type: str,
        base_color: tuple[int, int, int],
        accent_color: tuple[int, int, int],
        state: str,
        frame: int,
        is_dead: bool,
    ) -> pygame.Surface:
        width = 48 if enemy_type == "warden" else 40
        height = 66 if enemy_type == "warden" and not is_dead else (56 if not is_dead else 26)
        sprite = pygame.Surface((width, height), pygame.SRCALPHA)
        dark = tuple(max(0, channel - 44) for channel in base_color)
        light = tuple(min(255, channel + 42) for channel in base_color)
        accent_light = tuple(min(255, channel + 40) for channel in accent_color)

        if is_dead:
            body_w = 36 if enemy_type == "warden" else 28
            pygame.draw.ellipse(sprite, dark, ((width - body_w) // 2 - 2, height - 14, body_w + 4, 10))
            pygame.draw.ellipse(sprite, base_color, ((width - body_w) // 2, height - 16, body_w, 11))
            pygame.draw.rect(sprite, accent_color, (width // 2 - 8, height - 15, 16, 4), border_radius=2)
            pygame.draw.line(sprite, accent_light, (width // 2 - 10, height - 12), (width // 2 + 10, height - 12), 1)
            return sprite

        walk_offsets = (-2, -1, 1, 2)
        bob = walk_offsets[frame % len(walk_offsets)] if state == "walk" else 0
        arm_swing = (-5, -1, 2, 6)[frame % 4] if state == "walk" else 0
        torso_w = 24 if enemy_type == "warden" else 20
        torso_h = 30 if enemy_type == "warden" else 24
        head_w = 18 if enemy_type == "warden" else 16
        head_h = 16 if enemy_type == "warden" else 14
        if state == "attack":
            bob = -1 if frame == 0 else 1
            arm_swing = 2 + frame * 3
        if state == "pain":
            bob = 2 + frame
            arm_swing = -5
        if state == "alert":
            bob = -1 if frame == 0 else 0

        body_rect = pygame.Rect((width - torso_w) // 2, 18 + bob, torso_w, torso_h)
        head_rect = pygame.Rect((width - head_w) // 2, 4 + bob, head_w, head_h)
        pygame.draw.ellipse(sprite, dark, body_rect.move(0, 2))
        pygame.draw.ellipse(sprite, base_color, body_rect)
        pygame.draw.ellipse(sprite, light, head_rect)
        pygame.draw.ellipse(sprite, dark, head_rect, 2)
        pygame.draw.rect(sprite, accent_color, (width // 2 - 7, body_rect.y + 7, 14, 7), border_radius=2)
        pygame.draw.rect(sprite, accent_light, (width // 2 - 4, body_rect.y + 10, 8, 2), border_radius=1)
        pygame.draw.rect(sprite, dark, (head_rect.x + 3, head_rect.y + 5, 3, 2), border_radius=1)
        pygame.draw.rect(sprite, dark, (head_rect.right - 6, head_rect.y + 5, 3, 2), border_radius=1)
        pygame.draw.rect(sprite, dark, (head_rect.x + 2, head_rect.bottom - 4, head_rect.width - 4, 2), border_radius=1)

        left_arm = [
            (body_rect.x, body_rect.y + 7),
            (body_rect.x - 7 + arm_swing, body_rect.y + 15),
            (body_rect.x - 4 + arm_swing, body_rect.y + 20),
            (body_rect.x + 4, body_rect.y + 11),
        ]
        right_arm = [
            (body_rect.right, body_rect.y + 7),
            (body_rect.right + 7 - arm_swing, body_rect.y + 15),
            (body_rect.right + 4 - arm_swing, body_rect.y + 20),
            (body_rect.right - 4, body_rect.y + 11),
        ]
        pygame.draw.polygon(sprite, base_color, left_arm)
        pygame.draw.polygon(sprite, base_color, right_arm)
        pygame.draw.polygon(sprite, dark, left_arm, 1)
        pygame.draw.polygon(sprite, dark, right_arm, 1)

        leg_shift = (-3, -1, 2, 4)[frame % 4] if state == "walk" else 0
        left_leg_x = width // 2 - 6
        right_leg_x = width // 2 + 6
        pygame.draw.polygon(sprite, dark, [(left_leg_x, body_rect.bottom - 1), (left_leg_x - 4 + leg_shift, height - 2), (left_leg_x + leg_shift, height - 2), (left_leg_x + 3, body_rect.bottom + 1)])
        pygame.draw.polygon(sprite, dark, [(right_leg_x, body_rect.bottom - 1), (right_leg_x - 4 - leg_shift, height - 2), (right_leg_x - leg_shift, height - 2), (right_leg_x + 3, body_rect.bottom + 1)])
        if state == "attack":
            muzzle_x = body_rect.right + 4 if ENEMY_DEFINITIONS[enemy_type].attack_kind == "projectile" else body_rect.right
            pygame.draw.rect(sprite, accent_light, (muzzle_x - 3, body_rect.y + 9 + frame, 8, 5), border_radius=2)
            if frame >= 1 and ENEMY_DEFINITIONS[enemy_type].attack_kind == "projectile":
                pygame.draw.circle(sprite, accent_light, (muzzle_x + 5, body_rect.y + 11), 4 if frame == 2 else 3)
        elif state == "alert":
            pygame.draw.circle(sprite, accent_light, (body_rect.right + 4, body_rect.y + 11), 3)
        elif state == "pain":
            flash = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
            flash.fill((255, 212, 188, 48))
            sprite.blit(flash, (0, 0))
        if enemy_type == "warden":
            pygame.draw.rect(sprite, accent_color, (width // 2 - 12, body_rect.y + 2, 24, 4), border_radius=2)
            pygame.draw.rect(sprite, dark, (width // 2 - 14, body_rect.y + 1, 28, 6), 1, border_radius=2)
        return sprite

    def _make_projectile_sprite(
        self,
        projectile_color: tuple[int, int, int],
        accent_color: tuple[int, int, int],
        frame: int,
    ) -> pygame.Surface:
        size = 18 if frame == 0 else 20
        sprite = pygame.Surface((size, size), pygame.SRCALPHA)
        core = tuple(min(255, channel + 34) for channel in projectile_color)
        outer_alpha = 110 if frame == 0 else 88
        pygame.draw.circle(sprite, (*projectile_color, outer_alpha), (size // 2, size // 2), size // 2 - 1)
        pygame.draw.circle(sprite, (*core, 220), (size // 2, size // 2), max(3, size // 2 - 5))
        pygame.draw.circle(sprite, (*accent_color, 140), (size // 2, size // 2), max(2, size // 2 - 8))
        return sprite

    def _make_shell_sprite(self, color: tuple[int, int, int], width: int, height: int) -> pygame.Surface:
        sprite = pygame.Surface((width, height), pygame.SRCALPHA)
        for idx in range(2):
            shell = pygame.Rect(2 + idx * 9, 3 + idx * 2, 7, height - 7)
            pygame.draw.rect(sprite, color, shell, border_radius=3)
            pygame.draw.rect(sprite, (242, 196, 120), (shell.x, shell.bottom - 5, shell.width, 5), border_radius=2)
            pygame.draw.rect(sprite, (56, 26, 18), shell, 1, border_radius=3)
        pygame.draw.rect(sprite, (72, 40, 28), (0, height - 3, width, 3), border_radius=1)
        return sprite

    def _make_shell_box_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((28, 24), pygame.SRCALPHA)
        pygame.draw.rect(sprite, (154, 62, 40), (4, 5, 20, 15), border_radius=3)
        pygame.draw.rect(sprite, (232, 182, 90), (4, 14, 20, 5), border_radius=2)
        pygame.draw.rect(sprite, (70, 30, 18), (4, 5, 20, 15), 2, border_radius=3)
        pygame.draw.rect(sprite, (236, 210, 150), (8, 8, 12, 4), border_radius=1)
        pygame.draw.line(sprite, (72, 40, 24), (6, 5), (22, 5), 1)
        return sprite

    def _make_med_sprite(self, cross_color: tuple[int, int, int], small: bool) -> pygame.Surface:
        size = 24 if small else 30
        sprite = pygame.Surface((size, size), pygame.SRCALPHA)
        body = pygame.Rect(4, 4, size - 8, size - 8)
        pygame.draw.rect(sprite, (216, 220, 214) if not small else (146, 156, 150), body, border_radius=4)
        pygame.draw.rect(sprite, (70, 72, 66), body, 2, border_radius=4)
        pygame.draw.rect(sprite, cross_color, (size // 2 - 3, 7, 6, size - 14), border_radius=2)
        pygame.draw.rect(sprite, cross_color, (7, size // 2 - 3, size - 14, 6), border_radius=2)
        return sprite

    def _make_armor_bonus_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(sprite, (76, 164, 220), (12, 12), 9)
        pygame.draw.circle(sprite, (214, 236, 248), (12, 12), 9, 2)
        pygame.draw.rect(sprite, (236, 244, 250), (11, 7, 2, 10))
        pygame.draw.rect(sprite, (236, 244, 250), (7, 11, 10, 2))
        pygame.draw.circle(sprite, (28, 68, 108), (12, 12), 5, 1)
        return sprite

    def _make_armor_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((28, 30), pygame.SRCALPHA)
        pygame.draw.polygon(
            sprite,
            (58, 152, 104),
            [(14, 2), (24, 8), (22, 25), (14, 28), (6, 25), (4, 8)],
        )
        pygame.draw.polygon(
            sprite,
            (196, 234, 210),
            [(14, 2), (24, 8), (22, 25), (14, 28), (6, 25), (4, 8)],
            2,
        )
        pygame.draw.rect(sprite, (32, 92, 64), (11, 8, 6, 14), border_radius=2)
        pygame.draw.rect(sprite, (86, 206, 136), (9, 11, 10, 4), border_radius=2)
        return sprite

    def _project_z(self, eye_z: float, world_z: float, distance: float) -> int:
        return int(self.height // 2 + (eye_z - world_z) * (self.height / distance))

    def _sample_floor_and_ceiling(
        self,
        world: World,
        world_x: float,
        world_y: float,
        tex_x: int,
        tex_y: int,
    ) -> tuple[pygame.Color, pygame.Color]:
        grid_x = int(world_x)
        grid_y = int(world_y)
        if grid_x < 0 or grid_y < 0 or grid_x >= world.width or grid_y >= world.height:
            return self.floor_texture.get_at((tex_x, tex_y)), self.ceiling_texture.get_at((tex_x, tex_y))

        floor_surface = self.stair_texture if world.is_stair_at(grid_x, grid_y) else self.floor_texture
        floor_color = floor_surface.get_at((tex_x, tex_y))
        ceiling_color = self.ceiling_texture.get_at((tex_x, tex_y))
        room_kind = max(0, world.room_kinds[grid_y][grid_x])
        level = world.floor_heights[grid_y][grid_x]
        ceiling_height = world.get_ceiling_height_at(grid_x, grid_y)
        sector_type = world.get_sector_type_at(grid_x, grid_y)
        edge_tile = False
        for nx, ny in ((grid_x + 1, grid_y), (grid_x - 1, grid_y), (grid_x, grid_y + 1), (grid_x, grid_y - 1)):
            if 0 <= nx < world.width and 0 <= ny < world.height and not world.is_wall(nx, ny):
                if world.floor_heights[ny][nx] != level:
                    edge_tile = True
                    break
        floor_bias = (
            (8, 12, 10),    # start
            (26, 12, 4),    # storage
            (18, 6, 4),     # arena
            (2, 18, 14),    # tech
            (26, 20, 8),    # shrine
            (10, 8, 18),    # cross
        )[min(room_kind, 5)]
        ceiling_bias = (
            (8, 8, 14),
            (12, 10, 8),
            (10, 6, 10),
            (0, 20, 18),
            (18, 16, 6),
            (8, 10, 20),
        )[min(room_kind, 5)]
        floor_tint = (
            min(255, floor_color.r + level * 10 + floor_bias[0] + (12 if edge_tile else 0)),
            min(255, floor_color.g + level * 8 + floor_bias[1] + (10 if edge_tile else 0)),
            min(255, floor_color.b + level * 6 + floor_bias[2] + (6 if edge_tile else 0)),
        )
        ceiling_tint = (
            min(255, ceiling_color.r + level * 4 + ceiling_bias[0] + max(0, ceiling_height - 1) * 6),
            min(255, ceiling_color.g + level * 5 + ceiling_bias[1] + max(0, ceiling_height - 1) * 10),
            min(255, ceiling_color.b + level * 10 + ceiling_bias[2] + max(0, ceiling_height - 1) * 16),
        )
        if sector_type == 1:
            floor_tint = (
                max(18, floor_tint[0] // 2),
                min(255, floor_tint[1] + 56),
                max(22, floor_tint[2] // 2),
            )
        elif sector_type == 2:
            floor_tint = (
                min(255, floor_tint[0] + 34),
                min(255, floor_tint[1] + 28),
                min(255, floor_tint[2] + 10),
            )
        return pygame.Color(*floor_tint), pygame.Color(*ceiling_tint)


    def _build_background(self) -> pygame.Surface:
        background = pygame.Surface((self.width, self.height))
        half = self.height // 2

        for y in range(half):
            t = y / max(1, half - 1)
            color = self._lerp_color((10, 14, 28), (54, 24, 40), t)
            pygame.draw.line(background, color, (0, y), (self.width, y))

        for y in range(half, self.height):
            t = (y - half) / max(1, half - 1)
            base = self._lerp_color((70, 38, 24), (18, 12, 12), t)
            pygame.draw.line(background, base, (0, y), (self.width, y))

        vanishing_y = half - 22
        for x in range(-self.width // 3, self.width + self.width // 3, 72):
            pygame.draw.line(background, (42, 20, 16), (self.width // 2, vanishing_y), (x, self.height), 2)
            pygame.draw.line(background, (78, 44, 26), (self.width // 2, vanishing_y + 6), (x + 20, self.height), 1)

        horizon_line = half + 8
        band = 18.0
        while horizon_line < self.height:
            band += 9.5
            horizon_line += int(band)
            alpha = max(10, 96 - int((horizon_line - half) * 0.18))
            line = pygame.Surface((self.width, 3), pygame.SRCALPHA)
            line.fill((16, 8, 8, alpha))
            background.blit(line, (0, horizon_line))

        for y in range(half + 22, self.height, 46):
            pygame.draw.rect(background, (30, 16, 14), (0, y, self.width, 4))
            for x in range(24, self.width, 118):
                pygame.draw.rect(background, (92, 54, 28), (x, y - 2, 38, 7), border_radius=2)

        ceiling_overlay = pygame.Surface((self.width, half + 24), pygame.SRCALPHA)
        for y in range(0, half, 34):
            alpha = max(18, 74 - y // 6)
            pygame.draw.rect(ceiling_overlay, (16, 22, 34, alpha), (0, y, self.width, 8))
            for x in range(18, self.width, 132):
                pygame.draw.rect(ceiling_overlay, (24, 120, 90, alpha // 2), (x, y + 2, 28, 4), border_radius=2)
        background.blit(ceiling_overlay, (0, 0))
        return background

    def _build_sky_strip(self) -> pygame.Surface:
        width = self.width * 3
        height = self.height // 2 + 24
        sky = pygame.Surface((width, height), pygame.SRCALPHA)

        for y in range(height):
            t = y / max(1, height - 1)
            color = self._lerp_color((8, 14, 30), (92, 30, 34), t)
            pygame.draw.line(sky, color, (0, y), (width, y))

        for x in range(0, width, 180):
            tower_height = 42 + (x // 37) % 110
            tower_color = (18 + (x // 29) % 18, 20 + (x // 17) % 18, 26 + (x // 13) % 18)
            rect = pygame.Rect(x, height - tower_height - 18, 74 + (x // 53) % 48, tower_height)
            pygame.draw.rect(sky, tower_color, rect)
            pygame.draw.rect(sky, (0, 0, 0, 40), rect, 2)
            for light_y in range(rect.top + 10, rect.bottom - 6, 14):
                for light_x in range(rect.left + 6, rect.right - 8, 14):
                    glow = 90 if (light_x + light_y + x) % 3 == 0 else 36
                    pygame.draw.rect(sky, (84, 210, 116, glow), (light_x, light_y, 6, 3), border_radius=1)

        ridge = []
        for x in range(0, width + 80, 80):
            ridge.append((x, height - 42 - ((x // 80) % 3) * 10))
        ridge.extend([(width, height), (0, height)])
        pygame.draw.polygon(sky, (14, 18, 24), ridge)

        haze = pygame.Surface((width, 88), pygame.SRCALPHA)
        for y in range(88):
            alpha = max(0, 92 - y)
            pygame.draw.line(haze, (106, 210, 128, alpha), (0, y), (width, y))
        sky.blit(haze, (0, height - 64))
        return sky

    def _build_vignette(self) -> pygame.Surface:
        vignette = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        layers = (
            (0, 0, self.width, self.height, 18),
            (20, 16, self.width - 40, self.height - 32, 26),
            (42, 34, self.width - 84, self.height - 68, 36),
        )
        for rect in layers:
            x, y, w, h, alpha = rect
            pygame.draw.rect(vignette, (0, 0, 0, alpha), (x, y, w, h), border_radius=18, width=30)
        return vignette

    def _build_wall_textures(self) -> list[pygame.Surface]:
        external_names = [
            "wall_01_hell_brick.png",
            "wall_02_corrupted_metal.png",
            "wall_03_occult_stone.png",
            "wall_04_bone_fortress.png",
            "wall_05_tech_hell_panel.png",
        ]
        external_textures: list[pygame.Surface] = []
        for name in external_names:
            texture = self._load_texture_asset(name)
            if texture is not None:
                external_textures.append(texture)
        if len(external_textures) == len(external_names):
            return external_textures

        size = self.texture_size
        textures = []

        brick = pygame.Surface((size, size))
        brick.fill((112, 44, 36))
        for y in range(0, size, 16):
            offset = 8 if (y // 16) % 2 else 0
            pygame.draw.line(brick, (74, 26, 22), (0, y), (size, y), 2)
            for x in range(-offset, size, 16):
                pygame.draw.line(brick, (150, 76, 60), (x + offset, y), (x + offset, y + 16), 2)
        for x in range(0, size, 8):
            pygame.draw.line(brick, (126, 62, 48), (x, 0), (x, size), 1)
        pygame.draw.rect(brick, (64, 22, 18), (6, 6, size - 12, size - 12), 3)
        for x in range(10, size - 10, 14):
            pygame.draw.circle(brick, (168, 86, 62), (x, size - 10), 2)
        textures.append(brick)

        steel = pygame.Surface((size, size))
        steel.fill((80, 86, 102))
        for x in range(0, size, 8):
            tone = 88 + (x % 16) * 3
            pygame.draw.line(steel, (tone, tone + 6, tone + 16), (x, 0), (x, size))
        for y in range(0, size, 16):
            pygame.draw.rect(steel, (62, 66, 80), (0, y, size, 3))
            for x in range(4, size, 16):
                pygame.draw.circle(steel, (150, 154, 170), (x, y + 1), 2)
        pygame.draw.rect(steel, (34, 40, 56), (18, 8, 28, size - 16), border_radius=6)
        pygame.draw.rect(steel, (58, 188, 150), (28, 12, 8, size - 24), border_radius=3)
        pygame.draw.rect(steel, (164, 174, 184), (18, 8, 28, size - 16), 2, border_radius=6)
        textures.append(steel)

        toxic = pygame.Surface((size, size))
        toxic.fill((52, 92, 48))
        for y in range(0, size, 6):
            wave = int(math.sin(y * 0.34) * 8)
            pygame.draw.line(toxic, (84, 152, 68), (0, y), (size, y + wave % 3))
        for x in range(0, size, 12):
            pygame.draw.line(toxic, (34, 68, 32), (x, 0), (x + 5, size), 3)
        pygame.draw.rect(toxic, (42, 40, 26), (6, 10, size - 12, 10))
        pygame.draw.rect(toxic, (206, 178, 64), (6, 13, size - 12, 4))
        pygame.draw.rect(toxic, (42, 40, 26), (6, size - 20, size - 12, 10))
        pygame.draw.rect(toxic, (206, 178, 64), (6, size - 17, size - 12, 4))
        textures.append(toxic)

        stone = pygame.Surface((size, size))
        stone.fill((98, 88, 74))
        for y in range(0, size, 12):
            pygame.draw.line(stone, (70, 60, 48), (0, y), (size, y), 2)
        for x in range(0, size, 10):
            pygame.draw.line(stone, (122, 110, 96), (x, 0), (x + 10, size), 2)
        for x in range(8, size, 16):
            for y in range(8, size, 16):
                pygame.draw.rect(stone, (84, 74, 62), (x, y, 6, 6))
        pygame.draw.rect(stone, (48, 42, 38), (14, 14, size - 28, size - 28), 2)
        pygame.draw.line(stone, (122, 198, 220), (size // 2, 16), (size // 2, size - 16), 3)
        for y in range(18, size - 18, 10):
            pygame.draw.line(stone, (32, 54, 62), (size // 2 - 10, y), (size // 2 + 10, y), 1)
        textures.append(stone)

        computer = pygame.Surface((size, size))
        computer.fill((46, 54, 62))
        pygame.draw.rect(computer, (28, 34, 38), (4, 4, size - 8, size - 8), border_radius=6)
        pygame.draw.rect(computer, (18, 28, 24), (10, 10, size - 20, size - 20), border_radius=5)
        for y in range(12, size - 12, 8):
            color = (72, 198, 120) if (y // 8) % 2 == 0 else (46, 126, 86)
            pygame.draw.rect(computer, color, (14, y, 16, 3), border_radius=1)
            pygame.draw.rect(computer, (182, 146, 84), (36, y, 14, 3), border_radius=1)
        for x in (8, size - 8):
            for y in (8, size - 8):
                pygame.draw.circle(computer, (160, 164, 170), (x, y), 2)
        textures.append(computer)

        industrial = pygame.Surface((size, size))
        industrial.fill((86, 62, 34))
        for x in range(-size, size * 2, 12):
            pygame.draw.line(industrial, (120, 88, 46), (x, 0), (x + size // 2, size), 6)
            pygame.draw.line(industrial, (30, 24, 18), (x, 0), (x + size // 2, size), 1)
        pygame.draw.rect(industrial, (34, 26, 22), (18, 0, 12, size))
        pygame.draw.rect(industrial, (180, 170, 90), (21, 0, 6, size))
        textures.append(industrial)

        return textures

    def _load_texture_asset(self, asset_name: str) -> pygame.Surface | None:
        path = Path(__file__).resolve().parent.parent / "assets" / asset_name
        if not path.exists():
            return None
        image = pygame.image.load(str(path)).convert()
        if image.get_width() != self.texture_size or image.get_height() != self.texture_size:
            image = pygame.transform.smoothscale(image, (self.texture_size, self.texture_size))
        return image

    def _build_native_wall_texture_bytes(self) -> bytes:
        textures = list(self.wall_textures[:6])
        if not textures:
            return b""
        while len(textures) < 6:
            textures.append(textures[-1])
        return b"".join(pygame.image.tostring(texture, "RGB") for texture in textures)

    def _build_floor_textures(self) -> list[pygame.Surface]:
        external_names = [
            "floor_01_blood_stone.png",
            "floor_02_hell_metal_grate.png",
            "floor_03_occult_tiles.png",
            "floor_04_corrupted_flesh_metal.png",
        ]
        textures: list[pygame.Surface] = []
        for name in external_names:
            texture = self._load_texture_asset(name)
            if texture is not None:
                textures.append(texture)
        return textures

    def _build_native_floor_texture_bytes(self) -> bytes:
        textures = list(self.floor_textures[:4])
        if not textures:
            return b""
        while len(textures) < 4:
            textures.append(textures[-1])
        return b"".join(pygame.image.tostring(texture, "RGB") for texture in textures)

    def _build_ceiling_textures(self) -> list[pygame.Surface]:
        external_names = [
            "ceiling_01_dark_tech.png",
            "ceiling_02_hell_vault.png",
        ]
        textures: list[pygame.Surface] = []
        for name in external_names:
            texture = self._load_texture_asset(name)
            if texture is not None:
                textures.append(texture)
        return textures

    def _build_native_ceiling_texture_bytes(self) -> bytes:
        textures = list(self.ceiling_textures[:2])
        if not textures:
            return b""
        while len(textures) < 2:
            textures.append(textures[-1])
        return b"".join(pygame.image.tostring(texture, "RGB") for texture in textures)

    def _build_floor_texture(self) -> pygame.Surface:
        size = self.texture_size
        floor = pygame.Surface((size, size))
        floor.fill((58, 32, 18))

        for y in range(0, size, 16):
            pygame.draw.line(floor, (90, 52, 26), (0, y), (size, y), 2)
        for x in range(0, size, 10):
            pygame.draw.line(floor, (74, 40, 20), (x, 0), (x + 6, size), 1)

        for y in range(6, size, 16):
            for x in range(6, size, 16):
                pygame.draw.rect(floor, (126, 82, 42), (x, y, 10, 4), border_radius=2)
                pygame.draw.rect(floor, (40, 24, 18), (x, y + 1, 10, 1), border_radius=1)

        for x in range(0, size, 32):
            pygame.draw.rect(floor, (34, 18, 12), (x, 0, 3, size))
        return floor

    def _build_stair_texture(self) -> pygame.Surface:
        size = self.texture_size
        stair = pygame.Surface((size, size))
        stair.fill((72, 46, 22))

        for y in range(0, size, 8):
            tone = 92 if (y // 8) % 2 == 0 else 58
            pygame.draw.rect(stair, (tone, tone // 2 + 18, 28), (0, y, size, 6))
            pygame.draw.line(stair, (142, 110, 58), (0, y), (size, y), 1)
        for x in range(0, size, 16):
            pygame.draw.line(stair, (48, 30, 18), (x, 0), (x, size), 1)
        for y in range(4, size, 16):
            pygame.draw.rect(stair, (168, 132, 72), (6, y, size - 12, 3), border_radius=1)
        return stair

    def _build_ceiling_texture(self) -> pygame.Surface:
        size = self.texture_size
        ceiling = pygame.Surface((size, size))
        ceiling.fill((26, 30, 40))

        for y in range(0, size, 16):
            pygame.draw.line(ceiling, (44, 50, 64), (0, y), (size, y), 2)
        for x in range(0, size, 16):
            pygame.draw.line(ceiling, (38, 44, 58), (x, 0), (x, size), 2)

        for y in range(8, size, 16):
            for x in range(8, size, 16):
                pygame.draw.rect(ceiling, (18, 22, 28), (x - 5, y - 5, 10, 10), border_radius=2)
                pygame.draw.rect(ceiling, (84, 196, 156), (x - 1, y - 1, 2, 2), border_radius=1)

        pygame.draw.rect(ceiling, (70, 78, 98), (14, 28, size - 28, 8), border_radius=3)
        pygame.draw.rect(ceiling, (70, 78, 98), (14, size - 36, size - 28, 8), border_radius=3)
        return ceiling

    def _lerp_color(
        self,
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        t: float,
    ) -> tuple[int, int, int]:
        return tuple(int(a + (b - a) * t) for a, b in zip(start, end))
