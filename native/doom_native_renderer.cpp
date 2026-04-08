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
constexpr double kMinProjectionDistance = 0.24;
constexpr double kMinBillboardProjectionDistance = 0.42;
constexpr int kTextureSize = 128;

struct Color {
    uint8_t r;
    uint8_t g;
    uint8_t b;
};

#pragma pack(push, 1)
struct BillboardInstance {
    float x;
    float y;
    float z_offset;
    float projected_scale;
    uint16_t min_width;
    uint16_t min_height;
    uint32_t sprite_index;
};

struct BillboardMeta {
    uint16_t offset_x;
    uint16_t offset_y;
    uint16_t width;
    uint16_t height;
};
#pragma pack(pop)

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

inline Color average_color(const Color& a, const Color& b) {
    return {
        static_cast<uint8_t>((static_cast<int>(a.r) + static_cast<int>(b.r)) / 2),
        static_cast<uint8_t>((static_cast<int>(a.g) + static_cast<int>(b.g)) / 2),
        static_cast<uint8_t>((static_cast<int>(a.b) + static_cast<int>(b.b)) / 2),
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

inline Color sample_texture_rgb(
    const uint8_t* texture_data,
    int texture_index,
    int texture_count,
    int tx,
    int ty
) {
    constexpr Py_ssize_t kTextureBytes = static_cast<Py_ssize_t>(kTextureSize) * kTextureSize * 3;
    const int normalized_index = ((texture_index % texture_count) + texture_count) % texture_count;
    tx &= (kTextureSize - 1);
    ty &= (kTextureSize - 1);
    const Py_ssize_t base = static_cast<Py_ssize_t>(normalized_index) * kTextureBytes;
    const Py_ssize_t pixel = static_cast<Py_ssize_t>((ty * kTextureSize + tx) * 3);
    const uint8_t* src = texture_data + base + pixel;
    return {src[0], src[1], src[2]};
}

inline Color bilinear_sample_texture_rgb(
    const uint8_t* texture_data,
    int texture_index,
    int texture_count,
    double tx,
    double ty
) {
    const double wrapped_x = std::fmod(tx + kTextureSize * 8.0, static_cast<double>(kTextureSize));
    const double wrapped_y = std::fmod(ty + kTextureSize * 8.0, static_cast<double>(kTextureSize));
    const int x0 = static_cast<int>(std::floor(wrapped_x)) & (kTextureSize - 1);
    const int y0 = static_cast<int>(std::floor(wrapped_y)) & (kTextureSize - 1);
    const int x1 = (x0 + 1) & (kTextureSize - 1);
    const int y1 = (y0 + 1) & (kTextureSize - 1);
    const double fx = wrapped_x - std::floor(wrapped_x);
    const double fy = wrapped_y - std::floor(wrapped_y);

    const Color c00 = sample_texture_rgb(texture_data, texture_index, texture_count, x0, y0);
    const Color c10 = sample_texture_rgb(texture_data, texture_index, texture_count, x1, y0);
    const Color c01 = sample_texture_rgb(texture_data, texture_index, texture_count, x0, y1);
    const Color c11 = sample_texture_rgb(texture_data, texture_index, texture_count, x1, y1);
    const Color top = lerp_color(c00, c10, fx);
    const Color bottom = lerp_color(c01, c11, fx);
    return lerp_color(top, bottom, fy);
}

inline void put_pixel(uint8_t* frame, int width, int x, int y, const Color& c) {
    const int idx = (y * width + x) * 3;
    frame[idx] = c.r;
    frame[idx + 1] = c.g;
    frame[idx + 2] = c.b;
}

inline void blend_pixel(uint8_t* frame, int width, int x, int y, uint8_t sr, uint8_t sg, uint8_t sb, uint8_t sa) {
    if (sa == 0) {
        return;
    }
    const int idx = (y * width + x) * 3;
    if (sa >= 250) {
        frame[idx] = sr;
        frame[idx + 1] = sg;
        frame[idx + 2] = sb;
        return;
    }
    const int inv_alpha = 255 - sa;
    frame[idx] = static_cast<uint8_t>((sr * sa + frame[idx] * inv_alpha) / 255);
    frame[idx + 1] = static_cast<uint8_t>((sg * sa + frame[idx + 1] * inv_alpha) / 255);
    frame[idx + 2] = static_cast<uint8_t>((sb * sa + frame[idx + 2] * inv_alpha) / 255);
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

inline int sector_type_at(const uint8_t* sector_types, int map_width, int map_height, int x, int y) {
    if (sector_types == nullptr || x < 0 || y < 0 || x >= map_width || y >= map_height) {
        return 0;
    }
    return sector_types[y * map_width + x];
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

Color wall_texel_from_buffer(const uint8_t* texture_data, Py_ssize_t texture_len, int texture_index, double tx, double ty) {
    constexpr Py_ssize_t kTextureBytes = static_cast<Py_ssize_t>(kTextureSize) * kTextureSize * 3;
    constexpr int kTextureCount = 6;
    if (texture_data == nullptr || texture_len < kTextureBytes * kTextureCount) {
        const int ix = static_cast<int>(std::floor(tx)) & (kTextureSize - 1);
        const int iy = static_cast<int>(std::floor(ty)) & (kTextureSize - 1);
        return wall_texel(texture_index, ix, iy);
    }
    return bilinear_sample_texture_rgb(texture_data, texture_index, kTextureCount, tx, ty);
}

double wall_plane_coordinate(int map_x, int map_y, int side, double ray_dir_x, double ray_dir_y) {
    if (side == 0) {
        return ray_dir_x > 0.0 ? static_cast<double>(map_x) : static_cast<double>(map_x + 1);
    }
    return ray_dir_y > 0.0 ? static_cast<double>(map_y) : static_cast<double>(map_y + 1);
}

double texel_x_for_camera_sample(
    double camera_x,
    double px,
    double py,
    double dir_x,
    double dir_y,
    double plane_x,
    double plane_y,
    int map_x,
    int map_y,
    int side
) {
    const double ray_dir_x = dir_x + plane_x * camera_x;
    const double ray_dir_y = dir_y + plane_y * camera_x;
    double distance = 0.0;
    if (side == 0) {
        if (std::abs(ray_dir_x) < 0.00001) {
            return 0.0;
        }
        const double plane = wall_plane_coordinate(map_x, map_y, side, ray_dir_x, ray_dir_y);
        distance = (plane - px) / ray_dir_x;
    } else {
        if (std::abs(ray_dir_y) < 0.00001) {
            return 0.0;
        }
        const double plane = wall_plane_coordinate(map_x, map_y, side, ray_dir_x, ray_dir_y);
        distance = (plane - py) / ray_dir_y;
    }
    distance = std::max(distance, 0.0001);
    double wall_x = (side == 0) ? (py + distance * ray_dir_y) : (px + distance * ray_dir_x);
    wall_x -= std::floor(wall_x);
    double tex_x = wall_x * kTextureSize;
    if (side == 0 && ray_dir_x > 0.0) {
        tex_x = kTextureSize - tex_x - 1.0;
    }
    if (side == 1 && ray_dir_y < 0.0) {
        tex_x = kTextureSize - tex_x - 1.0;
    }
    return tex_x;
}

double unwrap_texel_sample(double reference, double sample) {
    double delta = sample - reference;
    if (delta > kTextureSize / 2.0) {
        delta -= kTextureSize;
    } else if (delta < -kTextureSize / 2.0) {
        delta += kTextureSize;
    }
    return reference + delta;
}

Color door_texel_from_buffer(const uint8_t* texture_data, Py_ssize_t texture_len, int door_type, double tx, double ty) {
    constexpr Py_ssize_t kTextureBytes = static_cast<Py_ssize_t>(kTextureSize) * kTextureSize * 3;
    constexpr int kTextureCount = 4;
    if (texture_data == nullptr || texture_len < kTextureBytes * kTextureCount) {
        const int ix = static_cast<int>(std::floor(tx)) & (kTextureSize - 1);
        const int iy = static_cast<int>(std::floor(ty)) & (kTextureSize - 1);
        return door_texel(door_type, ix, iy);
    }
    return bilinear_sample_texture_rgb(texture_data, door_type, kTextureCount, tx, ty);
}

Color floor_texel_from_buffer(const uint8_t* texture_data, Py_ssize_t texture_len, int room_kind, int sector_type, bool stair_tile, double tx, double ty) {
    constexpr Py_ssize_t kTextureBytes = static_cast<Py_ssize_t>(kTextureSize) * kTextureSize * 3;
    constexpr int kTextureCount = 6;
    int normalized_index = 0;
    if (stair_tile) {
        normalized_index = 5;
    } else if (sector_type == 1) {
        normalized_index = 4;
    } else {
        normalized_index = ((room_kind % 4) + 4) % 4;
    }
    if (texture_data == nullptr || texture_len < kTextureBytes * kTextureCount) {
        return {0, 0, 0};
    }
    return bilinear_sample_texture_rgb(texture_data, normalized_index, kTextureCount, tx, ty);
}

Color ceiling_texel_from_buffer(const uint8_t* texture_data, Py_ssize_t texture_len, int room_kind, double tx, double ty) {
    constexpr Py_ssize_t kTextureBytes = static_cast<Py_ssize_t>(kTextureSize) * kTextureSize * 3;
    constexpr int kTextureCount = 2;
    const int normalized_index = (room_kind >= 4) ? 1 : 0;
    if (texture_data == nullptr || texture_len < kTextureBytes * kTextureCount) {
        return {0, 0, 0};
    }
    return bilinear_sample_texture_rgb(texture_data, normalized_index, kTextureCount, tx, ty);
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
    const uint8_t* sector_types,
    const uint8_t* floor_texture_data,
    Py_ssize_t floor_texture_len,
    const uint8_t* ceiling_texture_data,
    Py_ssize_t ceiling_texture_len,
    int map_width,
    int map_height
) {
    const double eye_z = player_z + 0.5;
    // Eye height changes during a jump, but the view pitch does not, so the horizon stays fixed.
    const int horizon = height / 2;
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
            const double tex_x = kTextureSize * (floor_x - std::floor(floor_x));
            const double tex_y = kTextureSize * (floor_y - std::floor(floor_y));
            const int tx = static_cast<int>(tex_x) & (kTextureSize - 1);
            const int ty = static_cast<int>(tex_y) & (kTextureSize - 1);
            const int grid_x = static_cast<int>(floor_x);
            const int grid_y = static_cast<int>(floor_y);
            const int level = floor_height_at(floor_heights, map_width, map_height, grid_x, grid_y);
            const int room_kind = room_kind_at(room_kinds, map_width, map_height, grid_x, grid_y);
            const int sector_type = sector_type_at(sector_types, map_width, map_height, grid_x, grid_y);
            const bool stair_tile = is_stair(stair_mask, map_width, map_height, grid_x, grid_y);
            const bool edge_tile = is_edge_tile(tiles, floor_heights, map_width, map_height, grid_x, grid_y);
            Color floor_color = floor_texel(tx, ty, level, room_kind, stair_tile, edge_tile);
            const Color external_floor = floor_texel_from_buffer(
                floor_texture_data,
                floor_texture_len,
                room_kind,
                sector_type,
                stair_tile,
                tex_x,
                tex_y
            );
            if (external_floor.r != 0 || external_floor.g != 0 || external_floor.b != 0) {
                floor_color = external_floor;
                if (sector_type == 1) {
                    floor_color.r = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.r), 18, 255));
                    floor_color.g = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.g) + level * 6 + 18 + (edge_tile ? 8 : 0), 0, 255));
                    floor_color.b = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.b) + level * 4, 0, 255));
                } else {
                    floor_color.r = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.r) + level * 10 + (edge_tile ? 12 : 0), 0, 255));
                    floor_color.g = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.g) + level * 8 + (edge_tile ? 10 : 0), 0, 255));
                    floor_color.b = static_cast<uint8_t>(clamp_value(static_cast<int>(floor_color.b) + level * 6 + (edge_tile ? 6 : 0), 0, 255));
                }
            }

            put_pixel(frame, width, x, y, scale_color(floor_color, shade));
            if (ceiling_y >= 0 && ceiling_y < height) {
                Color ceiling_color = ceiling_texel(tx, ty, level, room_kind);
                const Color external_ceiling = ceiling_texel_from_buffer(ceiling_texture_data, ceiling_texture_len, room_kind, tex_x, tex_y);
                if (external_ceiling.r != 0 || external_ceiling.g != 0 || external_ceiling.b != 0) {
                    ceiling_color = external_ceiling;
                    static constexpr int ceiling_bias[6][3] = {
                        {8, 8, 14},
                        {12, 10, 8},
                        {10, 6, 10},
                        {0, 20, 18},
                        {18, 16, 6},
                        {8, 10, 20},
                    };
                    const int kind = clamp_value(room_kind, 0, 5);
                    ceiling_color.r = static_cast<uint8_t>(clamp_value(static_cast<int>(ceiling_color.r) + level * 4 + ceiling_bias[kind][0], 0, 255));
                    ceiling_color.g = static_cast<uint8_t>(clamp_value(static_cast<int>(ceiling_color.g) + level * 5 + ceiling_bias[kind][1], 0, 255));
                    ceiling_color.b = static_cast<uint8_t>(clamp_value(static_cast<int>(ceiling_color.b) + level * 10 + ceiling_bias[kind][2], 0, 255));
                }
                put_pixel(frame, width, x, ceiling_y, scale_color(ceiling_color, ceil_shade));
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
    const uint8_t* wall_texture_data,
    Py_ssize_t wall_texture_len,
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
        const double projection_distance = std::max(distance, kMinProjectionDistance);
        depth_buffer[column] = static_cast<float>(distance);
        const int wall_top = std::max(0, project_z(height, eye_z, hit_floor + hit_height, projection_distance));
        const int wall_bottom = std::min(height, project_z(height, eye_z, hit_floor, projection_distance));
        if (wall_bottom <= wall_top) {
            continue;
        }

        double wall_x = (side == 0) ? (py + distance * ray_dir_y) : (px + distance * ray_dir_x);
        wall_x -= std::floor(wall_x);
        double tex_x = wall_x * kTextureSize;
        if (side == 0 && ray_dir_x > 0.0) {
            tex_x = kTextureSize - tex_x - 1;
        }
        if (side == 1 && ray_dir_y < 0.0) {
            tex_x = kTextureSize - tex_x - 1;
        }

        const double camera_x_left = 2.0 * static_cast<double>(column) / width - 1.0;
        const double camera_x_right = 2.0 * static_cast<double>(column + 1) / width - 1.0;
        const double tex_x_left = texel_x_for_camera_sample(
            camera_x_left,
            px,
            py,
            dir_x,
            dir_y,
            plane_x,
            plane_y,
            map_x,
            map_y,
            side
        );
        const double tex_x_right = unwrap_texel_sample(
            tex_x_left,
            texel_x_for_camera_sample(
                camera_x_right,
                px,
                py,
                dir_x,
                dir_y,
                plane_x,
                plane_y,
                map_x,
                map_y,
                side
            )
        );
        const double texel_span = std::abs(tex_x_right - tex_x_left);
        const bool use_filtered_column = projection_distance < 1.15 || texel_span > 0.65;

        const double shade = std::max(0.20, 1.0 - distance / kMaxRayDistance) * (side ? 0.74 : 1.0);

        for (int y = wall_top; y < wall_bottom; ++y) {
            const double relative = static_cast<double>(y - wall_top) / std::max(1, wall_bottom - wall_top);
            const double tex_y = std::fmod(relative * hit_height * kTextureSize + kTextureSize * 8.0, static_cast<double>(kTextureSize));
            Color sampled = wall_texel_from_buffer(wall_texture_data, wall_texture_len, texture_index, tex_x, tex_y);
            if (use_filtered_column) {
                const double tex_x_mid_left = tex_x_left + (tex_x_right - tex_x_left) * 0.25;
                const double tex_x_mid_right = tex_x_left + (tex_x_right - tex_x_left) * 0.75;
                const Color left_sample = wall_texel_from_buffer(
                    wall_texture_data,
                    wall_texture_len,
                    texture_index,
                    tex_x_mid_left,
                    tex_y
                );
                const Color right_sample = wall_texel_from_buffer(
                    wall_texture_data,
                    wall_texture_len,
                    texture_index,
                    tex_x_mid_right,
                    tex_y
                );
                sampled = average_color(left_sample, right_sample);
            }
            Color c = scale_color(sampled, shade);
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
    const uint8_t* door_texture_data,
    Py_ssize_t door_texture_len,
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

            const double projection_distance = std::max(distance, kMinProjectionDistance);
            const int wall_top = std::max(0, project_z(height, eye_z, top_z, projection_distance));
            const int wall_bottom = std::min(height, project_z(height, eye_z, bottom_z, projection_distance));
            if (wall_bottom <= wall_top) {
                continue;
            }

            const double tex_x = tex_u * kTextureSize;
            const int draw_height = std::max(1, wall_bottom - wall_top);
            const int shade = std::max(42, 255 - std::min(188, static_cast<int>(distance * 14.0) + shade_bias));
            for (int y = wall_top; y < wall_bottom; ++y) {
                const double relative = static_cast<double>(y - wall_top) / draw_height;
                const double tex_y = clamp_value((lift + relative * visible_height) * kTextureSize, 0.0, static_cast<double>(kTextureSize - 1));
                const Color texel = door_texel_from_buffer(door_texture_data, door_texture_len, door_type, tex_x, tex_y);
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

void draw_billboards(
    uint8_t* frame,
    float* depth_buffer,
    int width,
    int height,
    double px,
    double py,
    double angle,
    double player_z,
    const uint8_t* floor_heights,
    int map_width,
    int map_height,
    const BillboardInstance* instances,
    int instance_count,
    const uint8_t* atlas_data,
    const BillboardMeta* atlas_meta,
    int sprite_count,
    int cell_size
) {
    if (instance_count <= 0 || sprite_count <= 0 || cell_size <= 0) {
        return;
    }

    struct PreparedBillboard {
        double transform_x;
        double transform_y;
        BillboardInstance instance;
    };

    const double eye_z = player_z + 0.5;
    const double dir_x = std::cos(angle);
    const double dir_y = std::sin(angle);
    const double plane_x = -dir_y * kCameraPlaneScale;
    const double plane_y = dir_x * kCameraPlaneScale;
    const double inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y);
    const int atlas_width = cell_size * sprite_count;

    std::vector<PreparedBillboard> visible;
    visible.reserve(instance_count);
    for (int index = 0; index < instance_count; ++index) {
        const BillboardInstance& inst = instances[index];
        const double dx = inst.x - px;
        const double dy = inst.y - py;
        const double transform_x = inv_det * (dir_y * dx - dir_x * dy);
        const double transform_y = inv_det * (-plane_y * dx + plane_x * dy);
        if (transform_y <= 0.05 || transform_y > kMaxRayDistance) {
            continue;
        }
        visible.push_back({transform_x, transform_y, inst});
    }

    std::sort(
        visible.begin(),
        visible.end(),
        [](const PreparedBillboard& a, const PreparedBillboard& b) {
            return a.transform_y > b.transform_y;
        }
    );

    for (const PreparedBillboard& prepared : visible) {
        if (prepared.instance.sprite_index >= static_cast<uint32_t>(sprite_count)) {
            continue;
        }

        const BillboardMeta& meta = atlas_meta[prepared.instance.sprite_index];
        if (meta.width == 0 || meta.height == 0) {
            continue;
        }

        const int grid_x = static_cast<int>(prepared.instance.x);
        const int grid_y = static_cast<int>(prepared.instance.y);
        const double floor_z = floor_height_at(floor_heights, map_width, map_height, grid_x, grid_y) + prepared.instance.z_offset;
        const double projection_distance = std::max(prepared.transform_y, kMinBillboardProjectionDistance);
        const int screen_x = static_cast<int>((width / 2.0) * (1.0 + prepared.transform_x / projection_distance));
        const int sprite_height = std::max(
            static_cast<int>(prepared.instance.min_height),
            static_cast<int>(height / projection_distance * prepared.instance.projected_scale)
        );
        const double aspect = static_cast<double>(meta.width) / std::max(1, static_cast<int>(meta.height));
        const int sprite_width = std::max(
            static_cast<int>(prepared.instance.min_width),
            static_cast<int>(sprite_height * aspect)
        );
        if (sprite_height <= 0 || sprite_width <= 0) {
            continue;
        }

        const int bottom_y = project_z(height, eye_z, floor_z, projection_distance);
        const int top_y = bottom_y - sprite_height;
        const int left_x = screen_x - sprite_width / 2;
        const int right_x = left_x + sprite_width;
        if (right_x <= 0 || left_x >= width) {
            continue;
        }

        const double shade_scale = std::max(0.28, 1.0 - prepared.transform_y / kMaxRayDistance);
        for (int screen_col = std::max(0, left_x); screen_col < std::min(width, right_x); ++screen_col) {
            if (prepared.transform_y >= depth_buffer[screen_col] - 0.015f) {
                continue;
            }
            const double relative_x = static_cast<double>(screen_col - left_x) / std::max(1, sprite_width);
            const int source_x = clamp_value(
                static_cast<int>(meta.offset_x) + static_cast<int>(relative_x * meta.width),
                static_cast<int>(meta.offset_x),
                static_cast<int>(meta.offset_x + meta.width - 1)
            );

            for (int screen_y = std::max(0, top_y); screen_y < std::min(height, bottom_y); ++screen_y) {
                const double relative_y = static_cast<double>(screen_y - top_y) / std::max(1, sprite_height);
                const int source_y = clamp_value(
                    static_cast<int>(meta.offset_y) + static_cast<int>(relative_y * meta.height),
                    static_cast<int>(meta.offset_y),
                    static_cast<int>(meta.offset_y + meta.height - 1)
                );
                const int atlas_index = (source_y * atlas_width + source_x) * 4;
                const uint8_t alpha = atlas_data[atlas_index + 3];
                if (alpha == 0) {
                    continue;
                }
                const uint8_t r = static_cast<uint8_t>(clamp_value(atlas_data[atlas_index] * shade_scale, 0.0, 255.0));
                const uint8_t g = static_cast<uint8_t>(clamp_value(atlas_data[atlas_index + 1] * shade_scale, 0.0, 255.0));
                const uint8_t b = static_cast<uint8_t>(clamp_value(atlas_data[atlas_index + 2] * shade_scale, 0.0, 255.0));
                blend_pixel(frame, width, screen_col, screen_y, r, g, b, alpha);
            }
            depth_buffer[screen_col] = std::min(depth_buffer[screen_col], static_cast<float>(prepared.transform_y));
        }
    }
}

PyObject* render_billboards_into(PyObject*, PyObject* args) {
    PyObject* frame_obj = nullptr;
    PyObject* depth_obj = nullptr;
    PyObject* floor_height_obj = nullptr;
    PyObject* instance_obj = nullptr;
    PyObject* atlas_obj = nullptr;
    PyObject* meta_obj = nullptr;
    int width = 0;
    int height = 0;
    int map_width = 0;
    int map_height = 0;
    int instance_count = 0;
    int sprite_count = 0;
    int cell_size = 0;
    double px = 0.0;
    double py = 0.0;
    double angle = 0.0;
    double player_z = 0.0;

    if (!PyArg_ParseTuple(
            args,
            "OOiiddddOiiOiOOii",
            &frame_obj,
            &depth_obj,
            &width,
            &height,
            &px,
            &py,
            &angle,
            &player_z,
            &floor_height_obj,
            &map_width,
            &map_height,
            &instance_obj,
            &instance_count,
            &atlas_obj,
            &meta_obj,
            &sprite_count,
            &cell_size)) {
        return nullptr;
    }

    Py_buffer frame_view{};
    Py_buffer depth_view{};
    Py_buffer floor_height_view{};
    Py_buffer instance_view{};
    Py_buffer atlas_view{};
    Py_buffer meta_view{};

    if (PyObject_GetBuffer(frame_obj, &frame_view, PyBUF_SIMPLE) < 0) {
        return nullptr;
    }
    if (PyObject_GetBuffer(depth_obj, &depth_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(floor_height_obj, &floor_height_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(instance_obj, &instance_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&floor_height_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(atlas_obj, &atlas_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&instance_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(meta_obj, &meta_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&instance_view);
        PyBuffer_Release(&atlas_view);
        return nullptr;
    }

    const Py_ssize_t frame_needed = static_cast<Py_ssize_t>(width) * height * 3;
    const Py_ssize_t depth_needed = static_cast<Py_ssize_t>(width) * sizeof(float);
    const Py_ssize_t floor_height_needed = static_cast<Py_ssize_t>(map_width) * map_height;
    const Py_ssize_t instance_needed = static_cast<Py_ssize_t>(instance_count) * sizeof(BillboardInstance);
    const Py_ssize_t atlas_needed = static_cast<Py_ssize_t>(sprite_count) * cell_size * cell_size * 4;
    const Py_ssize_t meta_needed = static_cast<Py_ssize_t>(sprite_count) * sizeof(BillboardMeta);
    if (
        frame_view.len < frame_needed ||
        depth_view.len < depth_needed ||
        floor_height_view.len < floor_height_needed ||
        instance_view.len < instance_needed ||
        atlas_view.len < atlas_needed ||
        meta_view.len < meta_needed
    ) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&instance_view);
        PyBuffer_Release(&atlas_view);
        PyBuffer_Release(&meta_view);
        PyErr_SetString(PyExc_ValueError, "render_billboards_into received undersized buffers");
        return nullptr;
    }

    draw_billboards(
        static_cast<uint8_t*>(frame_view.buf),
        static_cast<float*>(depth_view.buf),
        width,
        height,
        px,
        py,
        angle,
        player_z,
        static_cast<const uint8_t*>(floor_height_view.buf),
        map_width,
        map_height,
        static_cast<const BillboardInstance*>(instance_view.buf),
        instance_count,
        static_cast<const uint8_t*>(atlas_view.buf),
        static_cast<const BillboardMeta*>(meta_view.buf),
        sprite_count,
        cell_size
    );

    PyBuffer_Release(&frame_view);
    PyBuffer_Release(&depth_view);
    PyBuffer_Release(&floor_height_view);
    PyBuffer_Release(&instance_view);
    PyBuffer_Release(&atlas_view);
    PyBuffer_Release(&meta_view);
    Py_RETURN_NONE;
}

PyObject* render_into(PyObject*, PyObject* args) {
    PyObject* frame_obj = nullptr;
    PyObject* depth_obj = nullptr;
    PyObject* map_obj = nullptr;
    PyObject* floor_height_obj = nullptr;
    PyObject* stair_obj = nullptr;
    PyObject* room_kind_obj = nullptr;
    PyObject* sector_type_obj = nullptr;
    PyObject* door_obj = nullptr;
    PyObject* wall_texture_obj = Py_None;
    PyObject* floor_texture_obj = Py_None;
    PyObject* ceiling_texture_obj = Py_None;
    PyObject* door_texture_obj = Py_None;
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
            "OOiiddddOOOOOOiiid|OOOO",
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
            &sector_type_obj,
            &door_obj,
            &door_count,
            &map_width,
            &map_height,
            &time_seconds,
            &wall_texture_obj,
            &floor_texture_obj,
            &ceiling_texture_obj,
            &door_texture_obj)) {
        return nullptr;
    }

    Py_buffer frame_view{};
    Py_buffer depth_view{};
    Py_buffer map_view{};
    Py_buffer floor_height_view{};
    Py_buffer stair_view{};
    Py_buffer room_kind_view{};
    Py_buffer sector_type_view{};
    Py_buffer door_view{};
    Py_buffer wall_texture_view{};
    Py_buffer floor_texture_view{};
    Py_buffer ceiling_texture_view{};
    Py_buffer door_texture_view{};
    bool has_wall_texture_buffer = false;
    bool has_floor_texture_buffer = false;
    bool has_ceiling_texture_buffer = false;
    bool has_door_texture_buffer = false;

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
    if (PyObject_GetBuffer(sector_type_obj, &sector_type_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        PyBuffer_Release(&room_kind_view);
        return nullptr;
    }
    if (PyObject_GetBuffer(door_obj, &door_view, PyBUF_SIMPLE) < 0) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        PyBuffer_Release(&room_kind_view);
        PyBuffer_Release(&sector_type_view);
        return nullptr;
    }
    if (wall_texture_obj != Py_None) {
        if (PyObject_GetBuffer(wall_texture_obj, &wall_texture_view, PyBUF_SIMPLE) < 0) {
            PyBuffer_Release(&frame_view);
            PyBuffer_Release(&depth_view);
            PyBuffer_Release(&map_view);
            PyBuffer_Release(&floor_height_view);
            PyBuffer_Release(&stair_view);
            PyBuffer_Release(&room_kind_view);
            PyBuffer_Release(&sector_type_view);
            PyBuffer_Release(&door_view);
            return nullptr;
        }
        has_wall_texture_buffer = true;
    }
    if (floor_texture_obj != Py_None) {
        if (PyObject_GetBuffer(floor_texture_obj, &floor_texture_view, PyBUF_SIMPLE) < 0) {
            PyBuffer_Release(&frame_view);
            PyBuffer_Release(&depth_view);
            PyBuffer_Release(&map_view);
            PyBuffer_Release(&floor_height_view);
            PyBuffer_Release(&stair_view);
            PyBuffer_Release(&room_kind_view);
            PyBuffer_Release(&sector_type_view);
            PyBuffer_Release(&door_view);
            if (has_wall_texture_buffer) {
                PyBuffer_Release(&wall_texture_view);
            }
            return nullptr;
        }
        has_floor_texture_buffer = true;
    }
    if (ceiling_texture_obj != Py_None) {
        if (PyObject_GetBuffer(ceiling_texture_obj, &ceiling_texture_view, PyBUF_SIMPLE) < 0) {
            PyBuffer_Release(&frame_view);
            PyBuffer_Release(&depth_view);
            PyBuffer_Release(&map_view);
            PyBuffer_Release(&floor_height_view);
            PyBuffer_Release(&stair_view);
            PyBuffer_Release(&room_kind_view);
            PyBuffer_Release(&sector_type_view);
            PyBuffer_Release(&door_view);
            if (has_wall_texture_buffer) {
                PyBuffer_Release(&wall_texture_view);
            }
            if (has_floor_texture_buffer) {
                PyBuffer_Release(&floor_texture_view);
            }
            return nullptr;
        }
        has_ceiling_texture_buffer = true;
    }
    if (door_texture_obj != Py_None) {
        if (PyObject_GetBuffer(door_texture_obj, &door_texture_view, PyBUF_SIMPLE) < 0) {
            PyBuffer_Release(&frame_view);
            PyBuffer_Release(&depth_view);
            PyBuffer_Release(&map_view);
            PyBuffer_Release(&floor_height_view);
            PyBuffer_Release(&stair_view);
            PyBuffer_Release(&room_kind_view);
            PyBuffer_Release(&sector_type_view);
            PyBuffer_Release(&door_view);
            if (has_wall_texture_buffer) {
                PyBuffer_Release(&wall_texture_view);
            }
            if (has_floor_texture_buffer) {
                PyBuffer_Release(&floor_texture_view);
            }
            if (has_ceiling_texture_buffer) {
                PyBuffer_Release(&ceiling_texture_view);
            }
            return nullptr;
        }
        has_door_texture_buffer = true;
    }

    const Py_ssize_t frame_needed = static_cast<Py_ssize_t>(width) * height * 3;
    const Py_ssize_t depth_needed = static_cast<Py_ssize_t>(width) * sizeof(float);
    const Py_ssize_t map_needed = static_cast<Py_ssize_t>(map_width) * map_height;
    const Py_ssize_t door_needed = static_cast<Py_ssize_t>(door_count) * 5;
    if (frame_view.len < frame_needed || depth_view.len < depth_needed || map_view.len < map_needed || floor_height_view.len < map_needed ||
        stair_view.len < map_needed || room_kind_view.len < map_needed || sector_type_view.len < map_needed || door_view.len < door_needed) {
        PyBuffer_Release(&frame_view);
        PyBuffer_Release(&depth_view);
        PyBuffer_Release(&map_view);
        PyBuffer_Release(&floor_height_view);
        PyBuffer_Release(&stair_view);
        PyBuffer_Release(&room_kind_view);
        PyBuffer_Release(&sector_type_view);
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
    auto* sector_types = static_cast<const uint8_t*>(sector_type_view.buf);
    auto* doors = static_cast<const uint8_t*>(door_view.buf);

    const uint8_t* floor_texture_data = has_floor_texture_buffer ? static_cast<const uint8_t*>(floor_texture_view.buf) : nullptr;
    const Py_ssize_t floor_texture_len = has_floor_texture_buffer ? floor_texture_view.len : 0;
    const uint8_t* ceiling_texture_data = has_ceiling_texture_buffer ? static_cast<const uint8_t*>(ceiling_texture_view.buf) : nullptr;
    const Py_ssize_t ceiling_texture_len = has_ceiling_texture_buffer ? ceiling_texture_view.len : 0;
    const uint8_t* door_texture_data = has_door_texture_buffer ? static_cast<const uint8_t*>(door_texture_view.buf) : nullptr;
    const Py_ssize_t door_texture_len = has_door_texture_buffer ? door_texture_view.len : 0;

    draw_background(frame, width, height, angle, time_seconds);
    draw_floor_and_ceiling(frame, width, height, px, py, angle, player_z, tiles, floor_heights, stair_mask, room_kinds, sector_types, floor_texture_data, floor_texture_len, ceiling_texture_data, ceiling_texture_len, map_width, map_height);
    const uint8_t* wall_texture_data = has_wall_texture_buffer ? static_cast<const uint8_t*>(wall_texture_view.buf) : nullptr;
    const Py_ssize_t wall_texture_len = has_wall_texture_buffer ? wall_texture_view.len : 0;

    draw_walls(frame, depth_buffer, width, height, px, py, angle, player_z, tiles, floor_heights, stair_mask, room_kinds, wall_texture_data, wall_texture_len, map_width, map_height);
    draw_doors(
        frame,
        depth_buffer,
        width,
        height,
        px,
        py,
        angle,
        player_z,
        floor_heights,
        doors,
        door_texture_data,
        door_texture_len,
        door_count,
        map_width,
        map_height
    );

    PyBuffer_Release(&frame_view);
    PyBuffer_Release(&depth_view);
    PyBuffer_Release(&map_view);
    PyBuffer_Release(&floor_height_view);
    PyBuffer_Release(&stair_view);
    PyBuffer_Release(&room_kind_view);
    PyBuffer_Release(&sector_type_view);
    PyBuffer_Release(&door_view);
    if (has_wall_texture_buffer) {
        PyBuffer_Release(&wall_texture_view);
    }
    if (has_floor_texture_buffer) {
        PyBuffer_Release(&floor_texture_view);
    }
    if (has_ceiling_texture_buffer) {
        PyBuffer_Release(&ceiling_texture_view);
    }
    if (has_door_texture_buffer) {
        PyBuffer_Release(&door_texture_view);
    }
    Py_RETURN_NONE;
}

PyMethodDef module_methods[] = {
    {"render_into", render_into, METH_VARARGS, "Render a Doom-like scene into an RGB framebuffer."},
    {"render_billboards_into", render_billboards_into, METH_VARARGS, "Render billboard sprites into an RGB framebuffer."},
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
