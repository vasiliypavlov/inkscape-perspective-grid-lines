#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import itertools
import inkex

EPSILON = 1e-9
HORIZON_TOLERANCE = 10.0
PARALLEL_SINE_TOLERANCE = 1e-7
RAY_COUNT_MAX = 50

def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]

def distance(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def intersect_lines(p1, p2, p3, p4):
    r = (p2[0] - p1[0], p2[1] - p1[1])
    s = (p4[0] - p3[0], p4[1] - p3[1])
    lr = math.hypot(*r)
    ls = math.hypot(*s)
    if lr < EPSILON or ls < EPSILON:
        return None
    denom = cross2(r, s)
    if abs(denom) / (lr * ls) < PARALLEL_SINE_TOLERANCE:
        return None
    qmp = (p3[0] - p1[0], p3[1] - p1[1])
    t = cross2(qmp, s) / denom
    return (p1[0] + t * r[0], p1[1] + t * r[1])

def normalized_color(value):
    if value is None:
        return "none"
    return str(value).strip().lower()

class PerspectiveGrid(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--show_rays", type=inkex.Boolean, default=True)
        pars.add_argument("--ray_count", type=int, default=3)

    def get_color(self, elem):
        style = elem.style
        color = style.get("stroke", "none")
        if color in ("none", None, ""):
            color = style.get("fill", "#000000")
        return normalized_color(color)

    def get_center(self, elem):
        bbox = elem.bounding_box()
        if bbox is None:
            raise inkex.AbortExtension("Ошибка: Объект не имеет Bounding Box.")
        return (float(bbox.center_x), float(bbox.center_y))

    def _selection_objects(self):
        selection = list(self.svg.selection)
        count = len(selection)
        if count not in (3, 5, 7):
            raise inkex.AbortExtension("Ошибка: выберите ровно 3, 5 или 7 маркеров.")
        return [
            {"elem": el, "center": self.get_center(el), "color": self.get_color(el)}
            for el in selection
        ]

    @staticmethod
    def _group_by_color(objects):
        groups = {}
        for obj in objects:
            groups.setdefault(obj["color"], []).append(obj)
        return groups

    def _get_three_vp_markers(self, vp_objects):
        """Находит 3 точки схода среди ровно 3 объектов."""
        if len(vp_objects) != 3:
            raise inkex.AbortExtension(
                f"_get_three_vp_markers требует ровно 3 объекта, получено {len(vp_objects)}."
            )
        horizontal_pairs = []
        for i in range(3):
            for j in range(i + 1, 3):
                a, b = vp_objects[i], vp_objects[j]
                if abs(a["center"][1] - b["center"][1]) <= HORIZON_TOLERANCE:
                    left, right = sorted((a, b), key=lambda o: o["center"][0])
                    horizontal_pairs.append((left, right))

        valid = []
        for left, right in horizontal_pairs:
            remaining = [o for o in vp_objects if o is not left and o is not right]
            if len(remaining) != 1:
                continue
            third = remaining[0]
            x1, x2 = left["center"][0], right["center"][0]
            if x1 < third["center"][0] < x2:
                if abs(third["center"][1] - (left["center"][1] + right["center"][1]) / 2) > HORIZON_TOLERANCE:
                    valid.append((left, right, third))

        if len(valid) != 1:
            raise inkex.AbortExtension(
                "Ошибка: не удалось однозначно определить 3 точки схода. "
                "Убедитесь, что 2 из 3 VP лежат на одной горизонтали, а 3-я — между ними по X."
            )
        return valid[0]

    # ============================================================
    # РЕЖИМ 3 ТОЧЕК
    # ============================================================
    def _analyze_mode_3(self, objects):
        left, right, third = self._get_three_vp_markers(objects)
        vps = {
            "VP1": {"center": left["center"], "color": left["color"]},
            "VP2": {"center": right["center"], "color": right["color"]},
            "VP3": {"center": third["center"], "color": third["color"]},
        }
        return vps, None, 'mode3'

    # ============================================================
    # РЕЖИМ 5 ТОЧЕК: 3 VP + 1 пара ограничителей
    # ============================================================
    def _analyze_mode_5(self, objects):
        groups = self._group_by_color(objects)
        pair_groups = [g for g in groups.values() if len(g) == 2]
        unique_groups = [g for g in groups.values() if len(g) == 1]

        if len(pair_groups) != 1 or len(unique_groups) != 3:
            sizes = sorted([len(g) for g in groups.values()], reverse=True)
            raise inkex.AbortExtension(
                f"5 точек: нужен 1 парный цвет (ограничители) + 3 уникальных (VP). "
                f"Найдено: {sizes}"
            )

        unique_objs = [g[0] for g in unique_groups]
        left, right, third = self._get_three_vp_markers(unique_objs)

        vps = {
            "VP1": {"center": left["center"], "color": left["color"]},
            "VP2": {"center": right["center"], "color": right["color"]},
            "VP3": {"center": third["center"], "color": third["color"]},
        }
        lim = pair_groups[0]
        bounds = (lim[0]["center"], lim[1]["center"], None, None)
        return vps, bounds, 'mode5'

    # ============================================================
    # КЛАССИЧЕСКИЙ РЕЖИМ 7 ТОЧЕК: 3 VP + 2 пары ограничителей
    # ============================================================
    def _analyze_mode_7_classic(self, objects):
        groups = self._group_by_color(objects)
        pair_groups = [g for g in groups.values() if len(g) == 2]
        unique_groups = [g for g in groups.values() if len(g) == 1]

        if len(pair_groups) != 2 or len(unique_groups) != 3:
            sizes = sorted([len(g) for g in groups.values()], reverse=True)
            raise inkex.AbortExtension(
                f"7 точек (классический): нужно 2 пары + 3 уникальных. Найдено: {sizes}"
            )

        unique_objs = [g[0] for g in unique_groups]
        left, right, third = self._get_three_vp_markers(unique_objs)

        vps = {
            "VP1": {"center": left["center"], "color": left["color"]},
            "VP2": {"center": right["center"], "color": right["color"]},
            "VP3": {"center": third["center"], "color": third["color"]},
        }

        # Ищем горизонтальную пару (по допуску). Если не нашли - берем первую.
        h_group = next(
            (pg for pg in pair_groups
             if abs(pg[0]["center"][1] - pg[1]["center"][1]) <= HORIZON_TOLERANCE),
            None
        )
        if h_group is None:
            h_group = pair_groups[0]
        v_group = next((pg for pg in pair_groups if pg is not h_group), None)
        if v_group is None:
            v_group = pair_groups[1]

        bounds = (
            h_group[0]["center"], h_group[1]["center"],
            v_group[0]["center"], v_group[1]["center"],
        )
        return vps, bounds, 'mode7_legacy'

    # ============================================================
    # ОБРАТНЫЙ ИНЖИНИРИНГ: 3 VP (уникальные) + 4 точки одного цвета
    # ============================================================
    def _analyze_mode_7_reverse(self, objects):
        groups = self._group_by_color(objects)
        unique_groups = [g for g in groups.values() if len(g) == 1]
        four_groups = [g for g in groups.values() if len(g) == 4]

        if len(unique_groups) != 3 or len(four_groups) != 1:
            raise inkex.AbortExtension(
                "Обратный инжиниринг: нужно 4 точки одного цвета + 3 уникальные."
            )

        unique_objs = [g[0] for g in unique_groups]
        four_pts = [o["center"] for o in four_groups[0]]

        # 1. VP1 и VP2 из 4 точек плоскости объекта
        cx = sum(p[0] for p in four_pts) / 4.0
        cy = sum(p[1] for p in four_pts) / 4.0
        quad = sorted(four_pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

        vpA = intersect_lines(quad[0], quad[1], quad[2], quad[3])
        vpB = intersect_lines(quad[1], quad[2], quad[3], quad[0])

        if vpA is None or vpB is None:
            raise inkex.AbortExtension(
                "Обратный инжиниринг: противоположные ребра четырехугольника параллельны."
            )

        if vpA[0] <= vpB[0]:
            vp_left, vp_right = vpA, vpB
        else:
            vp_left, vp_right = vpB, vpA

        # 2. Роли 3 уникальных точек по X
        u_sorted = sorted(unique_objs, key=lambda o: o["center"][0])
        u_left, u_mid, u_right = u_sorted[0], u_sorted[1], u_sorted[2]
        u_pts = [u["center"] for u in u_sorted]

        # 3. VP3 — пересечение ребер через 3 из 4 точек
        best_err = float("inf")
        best_vp3 = None

        for subset in itertools.combinations(four_pts, 3):
            s_sorted = sorted(subset, key=lambda p: p[0])
            p0, p1, p2 = s_sorted
            u0, u1, u2 = u_pts

            v0 = (u0[0] - p0[0], u0[1] - p0[1])
            v1 = (u1[0] - p1[0], u1[1] - p1[1])
            v2 = (u2[0] - p2[0], u2[1] - p2[1])

            if (v0[0] * v1[0] + v0[1] * v1[1] <= 0) or (v1[0] * v2[0] + v1[1] * v2[1] <= 0):
                continue

            int01 = intersect_lines(p0, u0, p1, u1)
            int12 = intersect_lines(p1, u1, p2, u2)
            int02 = intersect_lines(p0, u0, p2, u2)

            if not int01 or not int12 or not int02:
                continue

            cand = (
                (int01[0] + int12[0] + int02[0]) / 3.0,
                (int01[1] + int12[1] + int02[1]) / 3.0,
            )

            v_to = (cand[0] - p0[0], cand[1] - p0[1])
            if v0[0] * v_to[0] + v0[1] * v_to[1] <= 0:
                continue

            err = distance(int01, int12) + distance(int12, int02) + distance(int02, int01)
            if err < best_err:
                best_err = err
                best_vp3 = cand

        if best_vp3 is None:
            for subset in itertools.combinations(four_pts, 3):
                s_sorted = sorted(subset, key=lambda p: p[0])
                p0, p1, p2 = s_sorted
                u0, u1, u2 = u_pts
                int01 = intersect_lines(p0, u0, p1, u1)
                if int01:
                    best_vp3 = int01
                    break

        if best_vp3 is None:
            raise inkex.AbortExtension(
                "Обратный инжиниринг: не удалось вычислить VP3."
            )

        vps = {
            "VP1": {"center": vp_left, "color": u_left["color"]},
            "VP2": {"center": vp_right, "color": u_right["color"]},
            "VP3": {"center": best_vp3, "color": u_mid["color"]},
        }
        bounds = (four_pts, u_pts, four_pts)
        return vps, bounds, 'mode7_reverse'

    # ============================================================
    # ДИСПЕТЧЕР 7 ТОЧЕК
    # ============================================================
    def _analyze_mode_7(self, objects):
        groups = self._group_by_color(objects)
        sizes = sorted([len(g) for g in groups.values()], reverse=True)

        # Обратный инжиниринг: 4 одинаковых + 3 уникальных
        if sizes == [4, 1, 1, 1]:
            return self._analyze_mode_7_reverse(objects)

        # Классический: 2 пары + 3 уникальных
        if sizes == [2, 2, 1, 1, 1]:
            return self._analyze_mode_7_classic(objects)

        color_info = "; ".join(f"{c}×{len(g)}" for c, g in groups.items())
        raise inkex.AbortExtension(
            f"7 точек: не удалось распознать режим.\n"
            f"Состав: {sizes}\n"
            f"Цвета: {color_info}\n"
            f"Нужно:\n"
            f"  • [4,1,1,1] — обратный инжиниринг\n"
            f"  • [2,2,1,1,1] — классический"
        )

    def analyze_selection(self):
        objects = self._selection_objects()
        count = len(objects)
        if count == 3:
            return self._analyze_mode_3(objects)
        elif count == 5:
            return self._analyze_mode_5(objects)
        elif count == 7:
            return self._analyze_mode_7(objects)
        raise inkex.AbortExtension("Неподдерживаемое количество маркеров.")

    def _page_rect(self, extra_points=None):
        try:
            page = self.svg.get_page_bbox()
            rect = [float(page.left), float(page.top),
                    float(page.left + page.width), float(page.top + page.height)]
        except Exception:
            rect = [0.0, 0.0,
                    float(self.svg.viewport_width), float(self.svg.viewport_height)]
        if extra_points:
            margin = 50.0
            for pt in extra_points:
                rect[0] = min(rect[0], pt[0] - margin)
                rect[1] = min(rect[1], pt[1] - margin)
                rect[2] = max(rect[2], pt[0] + margin)
                rect[3] = max(rect[3], pt[1] + margin)
        return tuple(rect)

    @staticmethod
    def _ray_exit_parameter(x0, y0, dx, dy, rect):
        xmin, ymin, xmax, ymax = rect
        t_min, t_max = float("-inf"), float("inf")
        for origin, direction, lower, upper in ((x0, dx, xmin, xmax), (y0, dy, ymin, ymax)):
            if abs(direction) < EPSILON:
                if origin < lower or origin > upper:
                    return None
                continue
            t1 = (lower - origin) / direction
            t2 = (upper - origin) / direction
            t_min = max(t_min, min(t1, t2))
            t_max = min(t_max, max(t1, t2))
        if t_max < max(t_min, 0.0) or not math.isfinite(t_max):
            return None
        return t_max

    @staticmethod
    def _angle_between(origin, point):
        return math.degrees(math.atan2(point[1] - origin[1], point[0] - origin[0]))

    @staticmethod
    def _interpolate_angles(start, end, count):
        delta = (end - start + 180.0) % 360.0 - 180.0
        if delta < 0:
            start, end = end, start
            delta = -delta
        if count == 1:
            return [start + delta / 2.0]
        return [start + delta * i / (count - 1) for i in range(count)]

    # ============================================================
    # ОТРИСОВКА: ОБРАТНЫЙ ИНЖИНИРИНГ (отдельный метод)
    # ============================================================
    def _draw_mode7_reverse(self, g_rays, vps, bounds, count, rect):
        all_target_pts, u_pts, four_pts = bounds
        vp1, vp2, vp3 = vps["VP1"], vps["VP2"], vps["VP3"]

        # 1. Линия горизонта
        ox1, oy1 = vp1["center"]
        ox2, oy2 = vp2["center"]
        h_dx, h_dy = ox2 - ox1, oy2 - oy1
        if math.hypot(h_dx, h_dy) > EPSILON:
            h_group = inkex.Group(id="Horizon_Line_Group")
            g_rays.add(h_group)
            t_fwd = self._ray_exit_parameter(ox1, oy1, h_dx, h_dy, rect)
            t_bwd = self._ray_exit_parameter(ox1, oy1, -h_dx, -h_dy, rect)
            if t_fwd is not None and t_bwd is not None:
                hx1, hy1 = ox1 - h_dx * t_bwd, oy1 - h_dy * t_bwd
                hx2, hy2 = ox1 + h_dx * t_fwd, oy1 + h_dy * t_fwd
                h_path = inkex.PathElement(d=f"M {hx1:.4f},{hy1:.4f} L {hx2:.4f},{hy2:.4f}")
                h_path.set("style", "fill:none;stroke:#888888;stroke-width:1;opacity:0.7;")
                h_path.set("id", "Horizon_Line")
                h_group.add(h_path)

        # 2. Маркеры точек схода
        markers = inkex.Group(id="Vanishing_Points_Markers")
        g_rays.add(markers)
        for vp_key in ("VP1", "VP2", "VP3"):
            vp = vps[vp_key]
            vx, vy = vp["center"]
            dot = inkex.PathElement(
                d=f"M {vx-4:.4f},{vy:.4f} A 4 4 0 1 0 {vx+4:.4f},{vy:.4f} "
                  f"A 4 4 0 1 0 {vx-4:.4f},{vy:.4f} Z"
            )
            dot.set("style", f"fill:{vp['color']};stroke:#ffffff;stroke-width:1.5;")
            dot.set("id", f"Marker_{vp_key}")
            markers.add(dot)

        # 3. Лучи к 4 точкам пола (нижняя группа, отдельно для каждой VP)
        def draw_floor_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Floor_Rays_{vp_key}")
            group.set("label", f"Пол — {vp_key}")
            g_rays.add(group)

            for index, pt in enumerate(four_pts, 1):
                angle = self._angle_between((ox, oy), pt)
                rad = math.radians(angle)
                dx, dy = math.cos(rad), math.sin(rad)
                t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                if t is None:
                    continue
                ex, ey = ox + dx * t, oy + dy * t
                path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:1.5;opacity:0.85;")
                path.set("id", f"Floor_Rays_{vp_key}_{index}")
                group.add(path)

        # 4. Лучи к 3 уникальным точкам (верхняя группа)
        def draw_ceiling_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Ceiling_Rays_{vp_key}")
            group.set("label", f"Верх — {vp_key}")
            g_rays.add(group)

            angles = [self._angle_between((ox, oy), pt) for pt in u_pts]
            unique_angles = []
            for a in sorted(angles):
                if not unique_angles or abs((a - unique_angles[-1] + 180.0) % 360.0 - 180.0) > 0.5:
                    unique_angles.append(a)

            # 3 обязательных луча к каждой уникальной точке
            for index, angle in enumerate(unique_angles, 1):
                rad = math.radians(angle)
                dx, dy = math.cos(rad), math.sin(rad)
                t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                if t is None:
                    continue
                ex, ey = ox + dx * t, oy + dy * t
                path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:1.5;opacity:0.85;")
                path.set("id", f"Ceiling_Rays_{vp_key}_{index}")
                group.add(path)

            # Дополнительные лучи веера, если ray_count > 3
            if count > 3:
                fan_angles = self._interpolate_angles(min(angles), max(angles), count - 3)
                fan_idx = 1
                for angle in fan_angles:
                    if any(abs((angle - ua + 180.0) % 360.0 - 180.0) < 0.3 for ua in unique_angles):
                        continue
                    rad = math.radians(angle)
                    dx, dy = math.cos(rad), math.sin(rad)
                    t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                    if t is None:
                        continue
                    ex, ey = ox + dx * t, oy + dy * t
                    path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                    path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:0.75;opacity:0.4;")
                    path.set("id", f"Ceiling_Rays_{vp_key}_fan_{fan_idx}")
                    group.add(path)
                    fan_idx += 1

        # Строим лучи для всех трёх точек схода
        for vp_key in ("VP1", "VP2", "VP3"):
            draw_floor_rays(vp_key)
            draw_ceiling_rays(vp_key)

        # 3. Перспективные линии от каждой VP
        def draw_vp_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Rays_{vp_key}")
            g_rays.add(group)

            angles = [self._angle_between((ox, oy), pt) for pt in all_target_pts]

            unique_angles = []
            for a in sorted(angles):
                if not unique_angles or abs((a - unique_angles[-1] + 180.0) % 360.0 - 180.0) > 0.5:
                    unique_angles.append(a)

            # Толстые лучи через все 7 целей (включая 4 точки пола)
            for index, angle in enumerate(unique_angles, 1):
                rad = math.radians(angle)
                dx, dy = math.cos(rad), math.sin(rad)
                t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                if t is None:
                    continue
                ex, ey = ox + dx * t, oy + dy * t
                path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:1.5;opacity:0.85;")
                path.set("id", f"Rays_{vp_key}_key_ray_{index}")
                group.add(path)

            # Тонкие промежуточные лучи веера, если count > 1
            if count > 1:
                min_a = min(angles)
                max_a = max(angles)
                fan_angles = self._interpolate_angles(min_a, max_a, count)
                fan_idx = 1
                for angle in fan_angles:
                    if any(abs((angle - ua + 180.0) % 360.0 - 180.0) < 0.3 for ua in unique_angles):
                        continue
                    rad = math.radians(angle)
                    dx, dy = math.cos(rad), math.sin(rad)
                    t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                    if t is None:
                        continue
                    ex, ey = ox + dx * t, oy + dy * t
                    path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                    path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:0.75;opacity:0.4;")
                    path.set("id", f"Rays_{vp_key}_fan_ray_{fan_idx}")
                    group.add(path)
                    fan_idx += 1

        draw_vp_rays("VP1")
        draw_vp_rays("VP2")
        draw_vp_rays("VP3")

        # Лучи
        def draw_vp_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Rays_{vp_key}")
            g_rays.add(group)

            angles = [self._angle_between((ox, oy), pt) for pt in all_target_pts]
            unique_angles = []
            for a in sorted(angles):
                if not unique_angles or abs((a - unique_angles[-1] + 180.0) % 360.0 - 180.0) > 0.5:
                    unique_angles.append(a)

            for idx, angle in enumerate(unique_angles, 1):
                rad = math.radians(angle)
                dx, dy = math.cos(rad), math.sin(rad)
                t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                if t is None:
                    continue
                ex, ey = ox + dx * t, oy + dy * t
                path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:1.5;opacity:0.85;")
                path.set("id", f"Rays_{vp_key}_key_ray_{idx}")
                group.add(path)

            if count > 1:
                fan_angles = self._interpolate_angles(min(angles), max(angles), count)
                fan_idx = 1
                for angle in fan_angles:
                    if any(abs((angle - ua + 180.0) % 360.0 - 180.0) < 0.3 for ua in unique_angles):
                        continue
                    rad = math.radians(angle)
                    dx, dy = math.cos(rad), math.sin(rad)
                    t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                    if t is None:
                        continue
                    ex, ey = ox + dx * t, oy + dy * t
                    path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                    path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:0.75;opacity:0.4;")
                    path.set("id", f"Rays_{vp_key}_fan_ray_{fan_idx}")
                    group.add(path)
                    fan_idx += 1

        draw_vp_rays("VP1")
        draw_vp_rays("VP2")
        draw_vp_rays("VP3")

    # ============================================================
    # ОТРИСОВКА: ОБЩИЙ ДИСПЕТЧЕР
    # ============================================================
    def draw_rays(self, layer, vps, bounds, mode_type):
        if not self.options.show_rays:
            return
        count = int(self.options.ray_count)
        if count < 1 or count > RAY_COUNT_MAX:
            raise inkex.AbortExtension(f"Количество лучей должно быть 1–{RAY_COUNT_MAX}.")

        all_key_pts = [vps[k]["center"] for k in vps]
        if bounds and mode_type == 'mode7_reverse':
            all_key_pts.extend(bounds[0])

        rect = self._page_rect(extra_points=all_key_pts)
        g_rays = inkex.Group(id="Perspective_Rays")
        layer.add(g_rays)

        # Отдельный метод для обратного инжиниринга
        if mode_type == 'mode7_reverse':
            self._draw_mode7_reverse(g_rays, vps, bounds, count, rect)
            return

        # Классические режимы (3, 5, 7-legacy)
        def make_fan(vp_key, angles):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Rays_{vp_key}")
            g_rays.add(group)
            for idx, angle in enumerate(angles, 1):
                rad = math.radians(angle)
                dx, dy = math.cos(rad), math.sin(rad)
                t = self._ray_exit_parameter(ox, oy, dx, dy, rect)
                if t is None:
                    continue
                ex, ey = ox + dx * t, oy + dy * t
                path = inkex.PathElement(d=f"M {ox:.4f},{oy:.4f} L {ex:.4f},{ey:.4f}")
                path.set("style", f"fill:none;stroke:{vp['color']};stroke-width:1;opacity:0.6;")
                path.set("id", f"Rays_{vp_key}_ray_{idx}")
                group.add(path)

        vp1, vp2, vp3 = vps["VP1"], vps["VP2"], vps["VP3"]

        if mode_type == 'mode3':
            a12 = self._angle_between(vp1["center"], vp2["center"])
            a13 = self._angle_between(vp1["center"], vp3["center"])
            a21 = self._angle_between(vp2["center"], vp1["center"])
            a23 = self._angle_between(vp2["center"], vp3["center"])
            a31 = self._angle_between(vp3["center"], vp1["center"])
            a32 = self._angle_between(vp3["center"], vp2["center"])
            make_fan("VP1", self._interpolate_angles(a12, a13, count))
            make_fan("VP2", self._interpolate_angles(a21, a23, count))
            make_fan("VP3", self._interpolate_angles(a31, a32, count))
        else:
            # Классические режимы 5 и 7 точек
            bp1, bp2, bp3, bp4 = bounds
            a1 = self._angle_between(vp1["center"], bp1)
            a2 = self._angle_between(vp1["center"], bp2)
            b1 = self._angle_between(vp2["center"], bp1)
            b2 = self._angle_between(vp2["center"], bp2)
            make_fan("VP1", self._interpolate_angles(a1, a2, count))
            make_fan("VP2", self._interpolate_angles(b1, b2, count))

            # Режим 7 точек: есть вертикальные ограничители bp3, bp4
            if bp3 is not None and bp4 is not None:
                c1 = self._angle_between(vp3["center"], bp3)
                c2 = self._angle_between(vp3["center"], bp4)

                # Проверяем, дают ли эти точки угловое раскрытие
                delta_v = (c2 - c1 + 180.0) % 360.0 - 180.0
                if abs(delta_v) < 1.0:
                    # Вертикальные ограничители на одной оси — берём горизонтальные
                    c1 = self._angle_between(vp3["center"], bp1)
                    c2 = self._angle_between(vp3["center"], bp2)

                make_fan("VP3", self._interpolate_angles(c1, c2, count))

            # Режим 5 точек: вертикальных ограничителей нет, используем горизонтальные
            else:
                c1 = self._angle_between(vp3["center"], bp1)
                c2 = self._angle_between(vp3["center"], bp2)
                make_fan("VP3", self._interpolate_angles(c1, c2, count))

    def effect(self):
        vps, bounds, mode_type = self.analyze_selection()
        layer = self.svg.get_current_layer()
        temporary_layer = inkex.Group()
        self.draw_rays(temporary_layer, vps, bounds, mode_type)
        new_group = temporary_layer[0] if len(temporary_layer) else None
        old = self.svg.getElementById("Perspective_Rays")
        if new_group is not None:
            layer.add(new_group)
        if old is not None and old is not new_group and old.getparent() is not None:
            old.getparent().remove(old)

if __name__ == "__main__":
    PerspectiveGrid().run()