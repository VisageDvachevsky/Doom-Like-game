#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kTau = 6.28318530717958647692;
constexpr double kFov = 70.0 * kPi / 180.0;
constexpr double kCameraPlaneScale = 0.7002075382097097;  // tan(70deg / 2)
constexpr double kMaxRayDistance = 32.0;
constexpr int kTextureSize = 64;

struct Color {
    uint8_t r;
    uint8_t g;
    uint8_t b;
};

template <typename T>
inline T clamp_value(T value, T low, T high) {
    return std::min(high, std::max(low, value));
}

inline Color lerp_color(const Color& a, const Color& b, double t) {
    t = clamp_value(t, 0.0, 1.0);
    return {
        static_cast<uint8_t>(a.r + (b.r - a.r) * t),
        static_cast<uint8_t>(a.g + (b.g - a.g) * t),
        static_cast<uint8_t>(a.b + (b.b - a.b) * t),
    };
}

inline Color scale_color(const Color& c, double s) {
    s = std::max(0.0, s);
    return {
        static_cast<uint8_t>(clamp_value(c.r * s, 0.0, 255.0)),
        static_cast<uint8_t>(clamp_value(c.g * s, 0.0, 255.0)),
        static_cast<uint8_t>(clamp_value(c.b * s, 0.0, 255.0)),
    };
}

inline Color darken(const Color& c, int amount) {
    return {
        static_cast<uint8_t>(std::max(0, static_cast<int>(c.r) - amount)),
        static_cast<uint8_t>(std::max(0, static_cast<int>(c.g) - amount)),
        static_cast<uint8_t>(std::max(0, static_cast<int>(c.b) - amount)),
    };
}

inline void put_pixel(uint8_t* frame, int width, int x, int y, const Color& c) {
    const int idx = (y * width + x) * 3;
    frame[idx] = c.r;
    frame[idx + 1] = c.g;
    frame[idx + 2] = c.b;
}

inline bool is_wall(const uint8_t* tiles, int map_width, int map_height, int x, int y) {
    if (x < 0 || y < 0 || x >= map_width || y >= map_height) {
        return true;
    }
    return tiles[y * map_width + x] != 0;
}

inline int floor_height_at(const uint8_t* floor_heights, int map_width, int map_height, int x, int y) {
    if (x < 0 || y < 0 || x >= map_width || y >= map_height) {
        return 0;
    }
    return floor_heights[y * map_width + x];
}

inline bool is_stair(const uint8_t* stair_mask, int map_width, int map_height, int x, int y) {
    if (x < 0 || y < 0 || x >= map_width || y >= map_height) {
        return false;
    }
    return stair_mask[y * map_width + x] != 0;
}

inline int room_kind_at(const uint8_t* room_kinds, int map_width, int map_height, int x, int y) {
    if (x < 0 || y < 0 || x >= map_width || y >= map_height) {
        return 0;
    }
    return room_kinds[y * map_width + x];
}

Color door_texel(int door_type, int tx, int ty) {
    tx &= (kTextureSize - 1);
    ty &= (kTextureSize - 1);

    Color base{98, 90, 82};
    Color accent{196, 182, 132};
    switch (door_type) {
        case 1:
            base = {62, 78, 112};
            accent = {82, 168, 255};
            break;
        case 2:
            base = {118, 96, 44};
            accent = {252, 220, 92};
            break;
        case 3:
            base = {110, 62, 60};
            accent = {255, 104, 92};
            break;
        default:
            break;
    }

    Color dark = darken(base, 28);
    Color light{
        static_cast<uint8_t>(clamp_value(static_cast<int>(base.r) + 36, 0, 255)),
        static_cast<uint8_t>(clamp_value(static_cast<int>(base.g) + 36, 0, 255)),
        static_cast<uint8_t>(clamp_value(static_cast<int>(base.b) + 36, 0, 255)),
    };
    Color c = (((tx / 8) % 2) == 0) ? light : dark;
    if (tx < 6 || tx >= 58 || ty < 6 || ty >= 58) {
        c = dark;
    }
    if (tx >= 24 && tx < 40 && ty >= 8 && ty < 56) {
        c = accent;
    }
    if (tx >= 28 && tx < 36 && ty >= 14 && ty < 50) {
        c = light;
    }
    if (std::abs(tx - 31) <= 1 && std::abs(ty - 32) < 6) {
        c = dark;
    }
    if (ty >= 12 && ty < 54 && (ty % 10) == 0 && tx >= 10 && tx < 54) {
        c = dark;
    }
    return c;
}

inline bool is_edge_tile(const uint8_t* tiles, const uint8_t* floor_heights, int map_width, int map_height, int x, int y) {
    if (x < 0 || y < 0 || x >= map_width || y >= map_height || tiles[y * map_width + x] != 0) {
        return false;
    }
    const int level = floor_heights[y * map_width + x];
    const int offsets[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
    for (const auto& offset : offsets) {
        const int nx = x + offset[0];
        const int ny = y + offset[1];
        if (nx < 0 || ny < 0 || nx >= map_width || ny >= map_height) {
            continue;
        }
        if (tiles[ny * map_width + nx] == 0 && floor_heights[ny * map_width + nx] != level) {
            return true;
        }
    }
    return false;
}

inline int wall_texture_index(int map_x, int map_y, int room_kind) {
    static constexpr int start_palette[] = {1, 4};
    static constexpr int storage_palette[] = {5, 0};
    static constexpr int arena_palette[] = {0, 3};
    static constexpr int tech_palette[] = {1, 4, 2};
    static constexpr int shrine_palette[] = {3, 1};
    static constexpr int cross_palette[] = {2, 5, 0};

    const int pick = (map_x * 11 + map_y * 7);
    switch (room_kind) {
        case 0: return start_palette[pick % 2];
        case 1: return storage_palette[pick % 2];
        case 2: return arena_palette[pick % 2];
        case 3: return tech_palette[pick % 3];
        case 4: return shrine_palette[pick % 2];
        case 5: return cross_palette[pick % 3];
        default: return pick % 6;
    }
}

Color wall_texel(int texture_index, int tx, int ty) {
    tx &= (kTextureSize - 1);
    ty &= (kTextureSize - 1);

    switch (texture_index % 6) {
        case 0: {
            Color c{112, 44, 36};
            if (ty % 16 < 2 || ((tx + ((ty / 16) % 2) * 8) % 16) < 2) {
                c = {150, 76, 60};
            }
            if (tx < 4 || tx > 59 || ty < 4 || ty > 59) {
                c = {64, 22, 18};
            }
            return c;
        }
        case 1: {
            int tone = 86 + (tx % 16) * 2;
            Color c{
                static_cast<uint8_t>(tone),
                static_cast<uint8_t>(tone + 6),
                static_cast<uint8_t>(tone + 18),
            };
            if (ty % 16 < 3) {
                c = {62, 66, 80};
            }
            if (tx >= 18 && tx < 46 && ty >= 8 && ty < 56) {
                c = {34, 40, 56};
                if (tx >= 28 && tx < 36 && ty >= 12 && ty < 52) {
                    c = {58, 188, 150};
                }
            }
            return c;
        }
        case 2: {
            int wave = static_cast<int>(std::sin(ty * 0.34) * 8.0);
            Color c{52, 92, 48};
            if (((ty + wave) % 6) < 2) {
                c = {84, 152, 68};
            }
            if (tx % 12 < 3) {
                c = {34, 68, 32};
            }
            if ((ty >= 10 && ty < 20) || (ty >= 44 && ty < 54)) {
                c = (ty % 10 < 4) ? Color{206, 178, 64} : Color{42, 40, 26};
            }
            return c;
        }
        case 3: {
            Color c{98, 88, 74};
            if (ty % 12 < 2) {
                c = {70, 60, 48};
            }
            if (((tx + ty) % 16) < 2) {
                c = {122, 110, 96};
            }
            if (tx > 29 && tx < 35) {
                c = ((ty % 10) < 2) ? Color{32, 54, 62} : Color{122, 198, 220};
            }
            return c;
        }
        case 4: {
            Color c{46, 54, 62};
            if (tx < 4 || tx >= 60 || ty < 4 || ty >= 60) {
                c = {28, 34, 38};
            } else if (((ty - 12) % 8) < 3 && tx > 13 && tx < 52) {
                if (tx < 30) {
                    c = (((ty / 8) % 2) == 0) ? Color{72, 198, 120} : Color{46, 126, 86};
                } else {
                    c = {182, 146, 84};
                }
            }
            return c;
        }
        default: {
            Color c{86, 62, 34};
            if (((tx + ty / 2) % 12) < 6) {
                c = {120, 88, 46};
            }
            if (tx >= 18 && tx < 30) {
                c = (tx >= 21 && tx < 27) ? Color{180, 170, 90} : Color{34, 26, 22};
            }
            return c;
        }
    }
}

Color floor_texel(int tx, int ty, int level, int room_kind, bool stair_tile, bool edge_tile) {
    tx &= (kTextureSize - 1);
    ty &= (kTextureSize - 1);
    Color c{58, 32, 18};
    if (stair_tile) {
        c = (((ty / 8) % 2) == 0) ? Color{92, 64, 28} : Color{58, 36, 18};
        if ((ty % 8) == 0) {
            c = {142, 110, 58};
        }
        if (tx % 16 == 0) {
            c = {48, 30, 18};
        }
    } else {
        if (ty % 16 < 2) {
            c = {90, 52, 26};
        }
        if (((tx * 5 + ty) % 32) < 2) {
            c = {74, 40, 20};
        }
        if ((tx % 16 >= 6 && tx % 16 < 16) && (ty % 16 >= 6 && ty % 16 < 10)) {
            c = {126, 82, 42};
        }
        if (tx % 32 < 3) {
            c = {34, 18, 12};
        }
    }
    static constexpr int floor_bias[6][3] = {
        {8, 12, 10},
        {26, 12, 4},
        {18, 6, 4},
        {2, 18, 14},
        {26, 20, 8},
        {10, 8, 18},
    };
    const int kind = clamp_value(room_kind, 0, 5);
    c.r = static_cast<uint8_t>(clamp_value(static_cast<int>(c.r) + level * 10 + floor_bias[kind][0] + (edge_tile ? 12 : 0), 0, 255));
    c.g = static_cast<uint8_t>(clamp_value(static_cast<int>(c.g) + level * 8 + floor_bias[kind][1] + (edge_tile ? 10 : 0), 0, 255));
    c.b = static_cast<uint8_t>(clamp_value(static_cast<int>(c.b) + level * 6 + floor_bias[kind][2] + (edge_tile ? 6 : 0), 0, 255));
    return c;
}

Color ceiling_texel(int tx, int ty, int level, int room_kind) {
    tx &= (kTextureSize - 1);
    ty &= (kTextureSize - 1);
    Color c{26, 30, 40};
    if (ty % 16 < 2 || tx % 16 < 2) {
        c = {44, 50, 64};
    }
    if ((std::abs((tx % 16) - 8) < 2) && (std::abs((ty % 16) - 8) < 2)) {
        c = {84, 196, 156};
    }
    if ((ty >= 28 && ty < 36) || (ty >= 60 - 36 && ty < 60 - 28)) {
        if (tx > 14 && tx < 50) {
            c = {70, 78, 98};
        }
    }
    static constexpr int ceiling_bias[6][3] = {
        {8, 8, 14},
        {12, 10, 8},
        {10, 6, 10},
        {0, 20, 18},
        {18, 16, 6},
        {8, 10, 20},
    };
    const int kind = clamp_value(room_kind, 0, 5);
    c.r = static_cast<uint8_t>(clamp_value(static_cast<int>(c.r) + level * 4 + ceiling_bias[kind][0], 0, 255));
    c.g = static_cast<uint8_t>(clamp_value(static_cast<int>(c.g) + level * 5 + ceiling_bias[kind][1], 0, 255));
    c.b = static_cast<uint8_t>(clamp_value(static_cast<int>(c.b) + level * 10 + ceiling_bias[kind][2], 0, 255));
    return c;
}

void draw_background(uint8_t* frame, int width, int height, double angle, double time_seconds) {
    const int half = height / 2;
    const int sky_width = width * 3;
    const int offset = static_cast<int>((std::fmod(angle + kTau, kTau) / kTau) * (sky_width - width));

    std::vector<int> skyline(sky_width);
    for (int x = 0; x < sky_width; ++x) {
        skyline[x] = height / 2 - 26 - ((x / 23) % 7) * 4 - ((x / 81) % 3) * 6;
    }

    for (int y = 0; y < half; ++y) {
        const double t = static_cast<double>(y) / std::max(1, half - 1);
        Color base = lerp_color({10, 14, 28}, {54, 24, 40}, t);
        for (int x = 0; x < width; ++x) {
            const int sky_x = (x + offset) % sky_width;
            Color c = base;
            if (y >= skyline[sky_x]) {
                c = {14, 18, 24};
                if (((x + y + sky_x) % 19) == 0 && y > skyline[sky_x] + 4) {
                    c = {84, 210, 116};
                }
            }
            put_pixel(frame, width, x, y, c);
        }
    }

    const int pulse = static_cast<int>((std::sin(time_seconds * 0.9) + 1.0) * 0.5 * 22.0);
    for (int y = half - 10; y < half + 14 && y >= 0 && y < height; ++y) {
        int alpha = 18 + pulse - std::abs(y - half) * 2;
        alpha = std::max(0, alpha);
        const double glow = alpha / 255.0;
        for (int x = 0; x < width; ++x) {
            const int idx = (y * width + x) * 3;
            frame[idx] = static_cast<uint8_t>(clamp_value(frame[idx] + 118.0 * glow, 0.0, 255.0));
            frame[idx + 1] = static_cast<uint8_t>(clamp_value(frame[idx + 1] + 214.0 * glow, 0.0, 255.0));
            frame[idx + 2] = static_cast<uint8_t>(clamp_value(frame[idx + 2] + 140.0 * glow, 0.0, 255.0));
        }
    }
}

int project_z(int height, double eye_z, double world_z, double distance) {
    return static_cast<int>(height / 2 + (eye_z - world_z) * (height / distance));
}

void draw_floor_and_ceiling(
    uint8_t* frame,
    int width,
    int height,
    double px,
    double py,
    double angle,
    double player_z,
    const uint8_t* tiles,
    const uint8_t* floor_heights,
    const uint8_t* stair_mask,
    const uint8_t* room_kinds,
    int map_width,
    int map_height
) {
    const double eye_z = player_z + 0.5;
    const int horizon = static_cast<int>(height / 2 + player_z * height * 0.085);
    const double dir_x = std::cos(angle);
    const double dir_y = std::sin(angle);
    const double plane_x = -dir_y * kCameraPlaneScale;
    const double plane_y = dir_x * kCameraPlaneScale;
    const double ray_dir_x0 = dir_x - plane_x;
    const double ray_dir_y0 = dir_y - plane_y;
    const double ray_dir_x1 = dir_x + plane_x;
    const double ray_dir_y1 = dir_y + plane_y;

    for (int y = std::max(horizon + 2, 0); y < height; ++y) {
        const int row = y - horizon;
        const double row_distance = (eye_z * height) / row;
        const double step_x = row_distance * (ray_dir_x1 - ray_dir_x0) / width;
        const double step_y = row_distance * (ray_dir_y1 - ray_dir_y0) / width;

        double floor_x = px + row_distance * ray_dir_x0;
        double floor_y = py + row_distance * ray_dir_y0;
        const double shade = std::max(0.18, 1.0 - row_distance / (kMaxRayDistance * 0.8));
        const double ceil_shade = shade * 0.82 + 0.18;
        const int ceiling_y = horizon - row;

        for (int x = 0; x < width; ++x) {
            const int tx = static_cast<int>(kTextureSize * (floor_x - std::floor(floor_x))) & (kTextureSize - 1);
            const int ty = static_cast<int>(kTextureSize * (floor_y - std::floor(floor_y))) & (kTextureSize - 1);
            const int grid_x = static_cast<int>(floor_x);
            const int grid_y = static_cast<int>(floor_y);
            const int level = floor_height_at(floor_heights, map_width, map_height, grid_x, grid_y);
            const int room_kind = room_kind_at(room_kinds, map_width, map_height, grid_x, grid_y);
            const bool stair_tile = is_stair(stair_mask, map_width, map_height, grid_x, grid_y);
            const bool edge_tile = is_edge_tile(tiles, floor_heights, map_width, map_height, grid_x, grid_y);

            put_pixel(frame, width, x, y, scale_color(floor_texel(tx, ty, level, room_kind, stair_tile, edge_tile), shade));
            if (ceiling_y >= 0 && ceiling_y < height) {
                put_pixel(frame, width, x, ceiling_y, scale_color(ceiling_texel(tx, ty, level, room_kind), ceil_shade));
            }

            floor_x += step_x;
            floor_y += step_y;
        }
    }
}

void draw_walls(
    uint8_t* frame,
    float* depth_buffer,
    int width,
    int height,
    double px,
    double py,
    double angle,
    double player_z,
    const uint8_t* tiles,
    const uint8_t* floor_heights,
    const uint8_t* stair_mask,
    const uint8_t* room_kinds,
    int map_width,
    int map_height
) {
    const double dir_x = std::cos(angle);
    const double dir_y = std::sin(angle);
    const double plane_x = -dir_y * kCameraPlaneScale;
    const double plane_y = dir_x * kCameraPlaneScale;
    const double eye_z = player_z + 0.5;

    for (int column = 0; column < width; ++column) {
        depth_buffer[column] = static_cast<float>(kMaxRayDistance);
        const double camera_x = 2.0 * column / width - 1.0;
        const double ray_dir_x = dir_x + plane_x * camera_x;
        const double ray_dir_y = dir_y + plane_y * camera_x;

        int map_x = static_cast<int>(px);
        int map_y = static_cast<int>(py);
        int prev_floor = floor_height_at(floor_heights, map_width, map_height, map_x, map_y);

        const double delta_dist_x = ray_dir_x == 0.0 ? 1e30 : std::abs(1.0 / ray_dir_x);
        const double delta_dist_y = ray_dir_y == 0.0 ? 1e30 : std::abs(1.0 / ray_dir_y);

        int step_x = 1;
        int step_y = 1;
        double side_dist_x;
        double side_dist_y;

        if (ray_dir_x < 0.0) {
            step_x = -1;
            side_dist_x = (px - map_x) * delta_dist_x;
        } else {
            side_dist_x = (map_x + 1.0 - px) * delta_dist_x;
        }

        if (ray_dir_y < 0.0) {
            step_y = -1;
            side_dist_y = (py - map_y) * delta_dist_y;
        } else {
            side_dist_y = (map_y + 1.0 - py) * delta_dist_y;
        }

        bool hit = false;
        int side = 0;
        double distance = kMaxRayDistance;
        double hit_floor = static_cast<double>(prev_floor);
        double hit_height = 1.0;
        int texture_index = 0;
        bool height_face = false;

        for (int steps = 0; steps < map_width * map_height; ++steps) {
            if (side_dist_x < side_dist_y) {
                side_dist_x += delta_dist_x;
                map_x += step_x;
                side = 0;
            } else {
                side_dist_y += delta_dist_y;
                map_y += step_y;
                side = 1;
            }

            if (is_wall(tiles, map_width, map_height, map_x, map_y)) {
                hit = true;
                hit_floor = static_cast<double>(prev_floor);
                hit_height = 1.0;
                texture_index = wall_texture_index(map_x, map_y, room_kind_at(room_kinds, map_width, map_height, map_x, map_y));
                distance = (side == 0) ? (side_dist_x - delta_dist_x) : (side_dist_y - delta_dist_y);
                break;
            }

            const int next_floor = floor_height_at(floor_heights, map_width, map_height, map_x, map_y);
            if (next_floor != prev_floor) {
                hit = true;
                hit_floor = static_cast<double>(std::min(prev_floor, next_floor));
                hit_height = static_cast<double>(std::abs(next_floor - prev_floor));
                height_face = true;
                if (is_stair(stair_mask, map_width, map_height, map_x, map_y)) {
                    texture_index = 5;
                } else {
                    texture_index = (next_floor > prev_floor) ? 3 : 0;
                }
                distance = (side == 0) ? (side_dist_x - delta_dist_x) : (side_dist_y - delta_dist_y);
                break;
            }
            prev_floor = next_floor;

            if (std::min(side_dist_x, side_dist_y) > kMaxRayDistance) {
                break;
            }
        }

        if (!hit) {
            continue;
        }

        distance = std::max(distance, 0.0001);
        depth_buffer[column] = static_cast<float>(distance);
        const int wall_top = std::max(0, project_z(height, eye_z, hit_floor + hit_height, distance));
        const int wall_bottom = std::min(height, project_z(height, eye_z, hit_floor, distance));
        if (wall_bottom <= wall_top) {
            continue;
        }

        double wall_x = (side == 0) ? (py + distance * ray_dir_y) : (px + distance * ray_dir_x);
        wall_x -= std::floor(wall_x);
        int tex_x = static_cast<int>(wall_x * kTextureSize);
        if (side == 0 && ray_dir_x > 0.0) {
            tex_x = kTextureSize - tex_x - 1;
        }
        if (side == 1 && ray_dir_y < 0.0) {
            tex_x = kTextureSize - tex_x - 1;
        }

        const double shade = std::max(0.20, 1.0 - distance / kMaxRayDistance) * (side ? 0.74 : 1.0);

        for (int y = wall_top; y < wall_bottom; ++y) {
            const double relative = static_cast<double>(y - wall_top) / std::max(1, wall_bottom - wall_top);
            const int tex_y = static_cast<int>(relative * hit_height * kTextureSize) & (kTextureSize - 1);
            Color c = scale_color(wall_texel(texture_index, tex_x, tex_y), shade);
            const int darkness = std::min(170, static_cast<int>(distance * 10.0));
            c = darken(c, darkness);
            if (height_face && y - wall_top < 2) {
                c.r = static_cast<uint8_t>(clamp_value(static_cast<int>(c.r) + (texture_index == 5 ? 42 : 28), 0, 255));
                c.g = static_cast<uint8_t>(clamp_value(static_cast<int>(c.g) + (texture_index == 5 ? 34 : 26), 0, 255));
                c.b = static_cast<uint8_t>(clamp_value(static_cast<int>(c.b) + (texture_index == 5 ? 12 : 18), 0, 255));
            }
            put_pixel(frame, width, column, y, c);
        }
    }
}

void draw_doors(
    uint8_t* frame,
    float* depth_buffer,
    int width,
    int height,
    double px,
    double py,
    double angle,
    double player_z,
    const uint8_t* floor_heights,
    const uint8_t* door_data,
    int door_count,
    int map_width,
    int map_height
) {
    const double eye_z = player_z + 0.5;
    const double dir_x = std::cos(angle);
    const double dir_y = std::sin(angle);
    const double plane_x = -dir_y * kCameraPlaneScale;
    const double plane_y = dir_x * kCameraPlaneScale;
    const double inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y);

    for (int door_index = 0; door_index < door_count; ++door_index) {
        const uint8_t* door = door_data + door_index * 5;
        const int grid_x = door[0];
        const int grid_y = door[1];
        const bool vertical = door[2] != 0;
        const int door_type = door[3];
        const double lift = door[4] / 255.0;
        const double visible_height = std::max(0.02, 1.0 - lift);
        const double floor_z = floor_height_at(floor_heights, map_width, map_height, grid_x, grid_y);
        const double bottom_z = floor_z + lift;
        const double top_z = floor_z + 1.0;

        double endpoints[2][2];
        if (vertical) {
            endpoints[0][0] = grid_x + 0.5;
            endpoints[0][1] = grid_y;
            endpoints[1][0] = grid_x + 0.5;
            endpoints[1][1] = grid_y + 1.0;
        } else {
            endpoints[0][0] = grid_x;
            endpoints[0][1] = grid_y + 0.5;
            endpoints[1][0] = grid_x + 1.0;
            endpoints[1][1] = grid_y + 0.5;
        }

        double projected[2];
        int projected_count = 0;
        for (const auto& endpoint : endpoints) {
            const double dx = endpoint[0] - px;
            const double dy = endpoint[1] - py;
            const double transform_x = inv_det * (dir_y * dx - dir_x * dy);
            const double transform_y = inv_det * (-plane_y * dx + plane_x * dy);
            if (transform_y <= 0.05) {
                continue;
            }
            projected[projected_count++] = (width / 2.0) * (1.0 + transform_x / transform_y);
        }

        double range_min = 0.0;
        double range_max = 0.0;
        if (projected_count == 0) {
            const double center_x = grid_x + 0.5;
            const double center_y = grid_y + 0.5;
            const double dx = center_x - px;
            const double dy = center_y - py;
            const double transform_x = inv_det * (dir_y * dx - dir_x * dy);
            const double transform_y = inv_det * (-plane_y * dx + plane_x * dy);
            if (transform_y <= 0.05) {
                continue;
            }
            const double center_column = (width / 2.0) * (1.0 + transform_x / transform_y);
            const int half_width = std::max(6, static_cast<int>(width / transform_y * 0.32));
            range_min = center_column - half_width;
            range_max = center_column + half_width;
        } else {
            range_min = *std::min_element(projected, projected + projected_count);
            range_max = *std::max_element(projected, projected + projected_count);
        }

        const int column_start = std::max(0, static_cast<int>(range_min) - 2);
        const int column_end = std::min(width, static_cast<int>(range_max) + 3);
        if (column_end <= column_start) {
            continue;
        }

        const int shade_bias = vertical ? 18 : 32;
        for (int column = column_start; column < column_end; ++column) {
            const double camera_x = 2.0 * column / width - 1.0;
            const double ray_dir_x = dir_x + plane_x * camera_x;
            const double ray_dir_y = dir_y + plane_y * camera_x;

            double distance = 0.0;
            double tex_u = 0.0;
            if (vertical) {
                if (std::abs(ray_dir_x) < 0.00001) {
                    continue;
                }
                const double door_x = grid_x + 0.5;
                distance = (door_x - px) / ray_dir_x;
                if (distance <= 0.0001 || distance >= depth_buffer[column]) {
                    continue;
                }
                const double hit_y = py + ray_dir_y * distance;
                if (hit_y < grid_y || hit_y > grid_y + 1.0) {
                    continue;
                }
                tex_u = hit_y - grid_y;
            } else {
                if (std::abs(ray_dir_y) < 0.00001) {
                    continue;
                }
                const double door_y = grid_y + 0.5;
                distance = (door_y - py) / ray_dir_y;
                if (distance <= 0.0001 || distance >= depth_buffer[column]) {
                    continue;
                }
                const double hit_x = px + ray_dir_x * distance;
                if (hit_x < grid_x || hit_x > grid_x + 1.0) {
                    continue;
                }
                tex_u = hit_x - grid_x;
            }

            const int wall_top = std::max(0, project_z(height, eye_z, top_z, distance));
            const int wall_bottom = std::min(height, project_z(height, eye_z, bottom_z, distance));
            if (wall_bottom <= wall_top) {
                continue;
            }

            const int tex_x = clamp_value(static_cast<int>(tex_u * kTextureSize), 0, kTextureSize - 1);
            const int draw_height = std::max(1, wall_bottom - wall_top);
            const int shade = std::max(42, 255 - std::min(188, static_cast<int>(distance * 14.0) + shade_bias));
            for (int y = wall_top; y < wall_bottom; ++y) {
                const double relative = static_cast<double>(y - wall_top) / draw_height;
                const int tex_y = clamp_value(static_cast<int>((lift + relative * visible_height) * kTextureSize), 0, kTextureSize - 1);
                const Color texel = door_texel(door_type, tex_x, tex_y);
                const Color lit{
                    static_cast<uint8_t>(texel.r * shade / 255),
                    static_cast<uint8_t>(texel.g * shade / 255),
                    static_cast<uint8_t>(texel.b * shade / 255),
                };
                put_pixel(frame, width, column, y, lit);
            }
            depth_buffer[column] = static_cast<float>(distance);
        }
    }
}

PyObject* render_into(PyObject*, PyObject* args) {
    PyObject* frame_obj = nullptr;
    PyObject* depth_obj = nullptr;
    PyObject* map_obj = nullptr;
    PyObject* floor_height_obj = nullptr;
    PyObject* stair_obj = nullptr;
    PyObject* room_kind_obj = nullptr;
    PyObject* door_obj = nullptr;
    int width = 0;
    int height = 0;
    int door_count = 0;
    int map_width = 0;
    int map_height = 0;
    double px = 0.0;
    double py = 0.0;
    double angle = 0.0;
    double player_z = 0.0;
    double time_seconds = 0.0;

    if (!PyArg_ParseTuple(
            args,
            "OOiiddddOOOOOiiid",
            &frame_obj,
            &depth_obj,
            &width,
            &height,
            &px,
            &py,
            &angle,
            &player_z,
            &map_obj,
            &floor_height_obj,
            &stair_obj,
            &room_kind_obj,
            &door_obj,
            &door_count,
            &map_width,
            &map_height,
            &time_seconds)) {
        return nullptr;
    }

    Py_buffer frame_view{};
    Py_buffer depth_view{};
    Py_buffer map_view{};
    Py_buffer floor_height_view{};
    Py_buffer stair_view{};
    Py_buffer room_kind_view{};
    Py_buffer door_view{};

    if (PyObject_GetBuffer(frame_obj, &frame_view, PyBUF_WRITABLE) < 0) {
        return nullptr;
    }
    if (PyObject_GetBuffer(depth_obj, &depth_view, PyBUF_WRITABLE) < 0) {
        PyBuffer_Release(&frame_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(map_obj, &map_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(floor_height_obj, &floor_height_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(stair_obj, &stair_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(room_kind_obj, &room_kind_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(door_obj, &door_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        PyBuffer_Release(&room_kind_view);
        return nullptr;
    }

    const Py_ssize_t frame_needed = static_cast<Py_ssize_t>(width) * height * 3;
    const Py_ssize_t depth_needed = static_cast<Py_ssize_t>(width) * sizeof(float);
    const Py_ssize_t map_needed = static_cast<Py_ssize_t>(map_width) * map_height;
    const Py_ssize_t door_needed = static_cast<Py_ssize_t>(door_count) * 5;
    if (frame_view.len < frame_needed || depth_view.len < depth_needed || map_view.len < map_needed || floor_height_view.len < map_needed ||
        stair_view.len < map_needed || room_kind_view.len < map_needed || door_view.len < door_needed) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        PyBuffer_Release(&room_kind_view);
        PyBuffer_Release(&door_view);
        PyErr_SetString(PyExc_ValueError, "buffer smaller than expected");
        return nullptr;
    }

    auto* frame = static_cast<uint8_t*>(frame_view.buf);
    auto* depth_buffer = static_cast<float*>(depth_view.buf);
    auto* tiles = static_cast<const uint8_t*>(map_view.buf);
    auto* floor_heights = static_cast<const uint8_t*>(floor_height_view.buf);
    auto* stair_mask = static_cast<const uint8_t*>(stair_view.buf);
    auto* room_kinds = static_cast<const uint8_t*>(room_kind_view.buf);
    auto* doors = static_cast<const uint8_t*>(door_view.buf);

    draw_background(frame, width, height, angle, time_seconds);
    draw_floor_and_ceiling(frame, width, height, px, py, angle, player_z, tiles, floor_heights, stair_mask, room_kinds, map_width, map_height);
    draw_walls(frame, depth_buffer, width, height, px, py, angle, player_z, tiles, floor_heights, stair_mask, room_kinds, map_width, map_height);
    draw_doors(frame, depth_buffer, width, height, px, py, angle, player_z, floor_heights, doors, door_count, map_width, map_height);

    PyBuffer_Release(&frame_view);
    PyBuffer_Release(&depth_view);
    PyBuffer_Release(&map_view);
    PyBuffer_Release(&floor_height_view);
    PyBuffer_Release(&stair_view);
    PyBuffer_Release(&room_kind_view);
    PyBuffer_Release(&door_view);
    Py_RETURN_NONE;
}

PyMethodDef module_methods[] = {
    {"render_into", render_into, METH_VARARGS, "Render a Doom-like scene into an RGB framebuffer."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    "doom_native_renderer",
    "Native renderer for Doom-like scene drawing.",
    -1,
    module_methods,
};

}  // namespace

PyMODINIT_FUNC PyInit_doom_native_renderer(void) {
    return PyModule_Create(&module_def);
}
