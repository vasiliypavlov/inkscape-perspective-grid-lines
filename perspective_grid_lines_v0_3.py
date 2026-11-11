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


def get_homography_matrix(quad):
    x0, y0 = quad[0]
    x1, y1 = quad[1]
    x2, y2 = quad[2]
    x3, y3 = quad[3]

    dx1 = x1 - x2
    dx2 = x3 - x2
    dx3 = x0 - x1 + x2 - x3
    dy1 = y1 - y2
    dy2 = y3 - y2
    dy3 = y0 - y1 + y2 - y3

    if abs(dx3) < 1e-9 and abs(dy3) < 1e-9:
        return [
            x1 - x0, x3 - x0, x0,
            y1 - y0, y3 - y0, y0,
            0.0, 0.0, 1.0,
        ]

    det = dx1 * dy2 - dx2 * dy1
    if abs(det) < 1e-12:
        return None

    a31 = (dx3 * dy2 - dx2 * dy3) / det
    a32 = (dx1 * dy3 - dx3 * dy1) / det
    a33 = 1.0
    a11 = x1 - x0 + a31 * x1
    a12 = x3 - x0 + a32 * x3
    a13 = x0
    a21 = y1 - y0 + a31 * y1
    a22 = y3 - y0 + a32 * y3
    a23 = y0
    return [a11, a12, a13, a21, a22, a23, a31, a32, a33]


def project_point(H, u, v):
    w = H[6] * u + H[7] * v + H[8]
    if abs(w) < 1e-12:
        return None
    x = (H[0] * u + H[1] * v + H[2]) / w
    y = (H[3] * u + H[4] * v + H[5]) / w
    return (x, y)


class PerspectiveGrid(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--show_rays", type=inkex.Boolean, default=True)
        pars.add_argument("--ray_count", type=int, default=3)
        pars.add_argument("--show_grid", type=inkex.Boolean, default=False)
        pars.add_argument("--grid_x", type=int, default=4)
        pars.add_argument("--grid_y", type=int, default=4)

        pars.add_argument("--show_within_perspective", type=inkex.Boolean, default=True)
        pars.add_argument("--show_to_page_edge", type=inkex.Boolean, default=False)

        pars.add_argument("--show_floor", type=inkex.Boolean, default=False)
        pars.add_argument("--show_ceiling", type=inkex.Boolean, default=False)
        pars.add_argument("--show_left_wall", type=inkex.Boolean, default=False)
        pars.add_argument("--show_right_wall", type=inkex.Boolean, default=False)
        pars.add_argument("--show_front_wall", type=inkex.Boolean, default=False)
        pars.add_argument("--show_back_wall", type=inkex.Boolean, default=False)

    def get_color(self, elem):
        style = elem.style
        color = style.get("stroke", "none")
        if color in ("none", None, ""):
            color = style.get("fill", "#000000")
        return normalized_color(color)

    def get_center(self, elem):
        bbox = elem.bounding_box()
        if bbox is None:
            raise inkex.AbortExtension("Object has no bounding box.")
        return (float(bbox.center_x), float(bbox.center_y))

    def _selection_objects(self):
        selection = list(self.svg.selection)
        count = len(selection)
        if count not in (3, 5, 7):
            raise inkex.AbortExtension("Select exactly 3, 5 or 7 markers.")
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
        if len(vp_objects) != 3:
            raise inkex.AbortExtension(
                f"_get_three_vp_markers expects 3 objects, got {len(vp_objects)}."
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
                "Cannot identify 3 vanishing points. Two must share horizon, third between in X."
            )
        return valid[0]

    def _analyze_mode_3(self, objects):
        left, right, third = self._get_three_vp_markers(objects)
        vps = {
            "VP1": {"center": left["center"], "color": left["color"]},
            "VP2": {"center": right["center"], "color": right["color"]},
            "VP3": {"center": third["center"], "color": third["color"]},
        }
        return vps, None, 'mode3'

    def _analyze_mode_5(self, objects):
        groups = self._group_by_color(objects)
        pair_groups = [g for g in groups.values() if len(g) == 2]
        unique_groups = [g for g in groups.values() if len(g) == 1]

        if len(pair_groups) != 1 or len(unique_groups) != 3:
            raise inkex.AbortExtension(
                f"5 markers: need 1 pair + 3 unique VPs."
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

    def _analyze_mode_7_classic(self, objects):
        groups = self._group_by_color(objects)
        pair_groups = [g for g in groups.values() if len(g) == 2]
        unique_groups = [g for g in groups.values() if len(g) == 1]

        if len(pair_groups) != 2 or len(unique_groups) != 3:
            raise inkex.AbortExtension(
                f"7 markers (classic): need 2 pairs + 3 unique VPs."
            )

        unique_objs = [g[0] for g in unique_groups]
        left, right, third = self._get_three_vp_markers(unique_objs)

        vps = {
            "VP1": {"center": left["center"], "color": left["color"]},
            "VP2": {"center": right["center"], "color": right["color"]},
            "VP3": {"center": third["center"], "color": third["color"]},
        }

        h_group = next(
            (pg for pg in pair_groups
             if abs(pg[0]["center"][1] - pg[1]["center"][1]) <= HORIZON_TOLERANCE),
            None,
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

    def _analyze_mode_7_reverse(self, objects):
        groups = self._group_by_color(objects)
        unique_groups = [g for g in groups.values() if len(g) == 1]
        four_groups = [g for g in groups.values() if len(g) == 4]

        if len(unique_groups) != 3 or len(four_groups) != 1:
            raise inkex.AbortExtension(
                "Reverse engineering: need 4 same-color points + 3 unique VPs."
            )

        unique_objs = [g[0] for g in unique_groups]
        four_pts = [o["center"] for o in four_groups[0]]

        cx = sum(p[0] for p in four_pts) / 4.0
        cy = sum(p[1] for p in four_pts) / 4.0
        quad = sorted(four_pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

        vpA = intersect_lines(quad[0], quad[1], quad[2], quad[3])
        vpB = intersect_lines(quad[1], quad[2], quad[3], quad[0])

        if vpA is None or vpB is None:
            raise inkex.AbortExtension("Reverse: opposite edges of quad are parallel.")

        if vpA[0] <= vpB[0]:
            vp_left, vp_right = vpA, vpB
        else:
            vp_left, vp_right = vpB, vpA

        u_sorted = sorted(unique_objs, key=lambda o: o["center"][0])
        u_left, u_mid, u_right = u_sorted[0], u_sorted[1], u_sorted[2]
        u_pts = [u["center"] for u in u_sorted]

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
            raise inkex.AbortExtension("Reverse: could not compute VP3.")

        vps = {
            "VP1": {"center": vp_left, "color": u_left["color"]},
            "VP2": {"center": vp_right, "color": u_right["color"]},
            "VP3": {"center": best_vp3, "color": u_mid["color"]},
        }
        bounds = (four_pts + u_pts, u_pts, four_pts)
        return vps, bounds, 'mode7_reverse'

    def _analyze_mode_7(self, objects):
        groups = self._group_by_color(objects)
        sizes = sorted([len(g) for g in groups.values()], reverse=True)
        if sizes == [4, 1, 1, 1]:
            return self._analyze_mode_7_reverse(objects)
        if sizes == [2, 2, 1, 1, 1]:
            return self._analyze_mode_7_classic(objects)
        raise inkex.AbortExtension(f"7 markers: unrecognized composition {sizes}.")

    def analyze_selection(self):
        objects = self._selection_objects()
        count = len(objects)
        if count == 3:
            return self._analyze_mode_3(objects)
        elif count == 5:
            return self._analyze_mode_5(objects)
        elif count == 7:
            return self._analyze_mode_7(objects)
        raise inkex.AbortExtension("Unsupported marker count.")

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

    def _draw_mode7_reverse(self, g_rays, vps, bounds, count, rect):
        all_target_pts, u_pts, four_pts = bounds
        vp1, vp2, vp3 = vps["VP1"], vps["VP2"], vps["VP3"]

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

        def draw_floor_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Floor_Rays_{vp_key}")
            group.set("label", f"Floor — {vp_key}")
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

        def draw_ceiling_rays(vp_key):
            vp = vps[vp_key]
            ox, oy = vp["center"]
            group = inkex.Group(id=f"Ceiling_Rays_{vp_key}")
            group.set("label", f"Ceiling — {vp_key}")
            g_rays.add(group)
            angles = [self._angle_between((ox, oy), pt) for pt in u_pts]
            unique_angles = []
            for a in sorted(angles):
                if not unique_angles or abs((a - unique_angles[-1] + 180.0) % 360.0 - 180.0) > 0.5:
                    unique_angles.append(a)
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

        for vp_key in ("VP1", "VP2", "VP3"):
            draw_floor_rays(vp_key)
            draw_ceiling_rays(vp_key)

    def draw_rays(self, layer, vps, bounds, mode_type):
        if not self.options.show_rays:
            return
        count = int(self.options.ray_count)
        if count < 1 or count > RAY_COUNT_MAX:
            raise inkex.AbortExtension(f"Ray count must be 1–{RAY_COUNT_MAX}.")

        all_key_pts = [vps[k]["center"] for k in vps]
        if bounds and mode_type == 'mode7_reverse':
            all_key_pts.extend(bounds[0])

        rect = self._page_rect(extra_points=all_key_pts)
        g_rays = inkex.Group(id="Perspective_Rays")
        layer.add(g_rays)

        if mode_type == 'mode7_reverse':
            self._draw_mode7_reverse(g_rays, vps, bounds, count, rect)
            return

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
            bp1, bp2, bp3, bp4 = bounds
            a1 = self._angle_between(vp1["center"], bp1)
            a2 = self._angle_between(vp1["center"], bp2)
            b1 = self._angle_between(vp2["center"], bp1)
            b2 = self._angle_between(vp2["center"], bp2)
            make_fan("VP1", self._interpolate_angles(a1, a2, count))
            make_fan("VP2", self._interpolate_angles(b1, b2, count))

            if bp3 is not None and bp4 is not None:
                c1 = self._angle_between(vp3["center"], bp3)
                c2 = self._angle_between(vp3["center"], bp4)
                delta_v = (c2 - c1 + 180.0) % 360.0 - 180.0
                if abs(delta_v) < 1.0:
                    c1 = self._angle_between(vp3["center"], bp1)
                    c2 = self._angle_between(vp3["center"], bp2)
                make_fan("VP3", self._interpolate_angles(c1, c2, count))
            else:
                c1 = self._angle_between(vp3["center"], bp1)
                c2 = self._angle_between(vp3["center"], bp2)
                make_fan("VP3", self._interpolate_angles(c1, c2, count))

    # ============================================================
    # UNIFIED PERSPECTIVE GRID — по алгоритму пользователя
    # ============================================================
    def _build_perspective_grid(self, subgroup, vp1, vp2, bottom_pt, gx, gy, extend_edges, rect):
        """
        Within the lines of perspective:
            target_left = target_right = bottom_pt
        To the edge of the page:
            target_left  = (rect[0], rect[3])  # bottom-left page corner
            target_right = (rect[2], rect[3])  # bottom-right page corner
        """
        if extend_edges:
            target_left  = (rect[0], rect[3])
            target_right = (rect[2], rect[3])
        else:
            target_left  = bottom_pt
            target_right = bottom_pt

        # Divide VP1 → target_left into gx segments → L[0..gx]
        L = []
        for i in range(gx + 1):
            t = i / gx
            L.append((
                vp1[0] + (target_left[0] - vp1[0]) * t,
                vp1[1] + (target_left[1] - vp1[1]) * t,
            ))

        # Divide VP2 → target_right into gy segments → R[0..gy]
        R = []
        for j in range(gy + 1):
            t = j / gy
            R.append((
                vp2[0] + (target_right[0] - vp2[0]) * t,
                vp2[1] + (target_right[1] - vp2[1]) * t,
            ))

        # Nodes = intersections of L[i]→VP2 with R[j]→VP1
        nodes = {}
        for i in range(gx + 1):
            for j in range(gy + 1):
                if i == 0:
                    nodes[(i, j)] = vp1
                elif j == 0:
                    nodes[(i, j)] = vp2
                else:
                    nodes[(i, j)] = intersect_lines(L[i], vp2, R[j], vp1)

        # Draw trapezoid cells
        for i in range(gx):
            for j in range(gy):
                corners = [
                    nodes.get((i, j)),
                    nodes.get((i + 1, j)),
                    nodes.get((i + 1, j + 1)),
                    nodes.get((i, j + 1)),
                ]
                if any(c is None for c in corners):
                    continue

                # Skip degenerate cells (too small area or duplicate vertices)
                min_dist = min(
                    distance(corners[0], corners[1]),
                    distance(corners[1], corners[2]),
                    distance(corners[2], corners[3]),
                    distance(corners[3], corners[0]),
                )
                if min_dist < 1.0:
                    continue

                d = (
                    f"M {corners[0][0]:.4f},{corners[0][1]:.4f} "
                    f"L {corners[1][0]:.4f},{corners[1][1]:.4f} "
                    f"L {corners[2][0]:.4f},{corners[2][1]:.4f} "
                    f"L {corners[3][0]:.4f},{corners[3][1]:.4f} Z"
                )
                cell = inkex.PathElement(d=d)
                cell.set("class", "grid-cell")
                cell.set("style", "fill:none;stroke:#333333;stroke-width:0.5;")
                cell.set("id", f"{subgroup.get('id')}_cell_{i}_{j}")
                subgroup.add(cell)

    # ============================================================
    # Bounded surfaces (homography, unchanged)
    # ============================================================
    def _orient_quad_for_grid(self, quad_pts, vp1, vp2):
        cx = sum(p[0] for p in quad_pts) / 4.0
        cy = sum(p[1] for p in quad_pts) / 4.0
        pts = sorted(quad_pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        for shift in range(4):
            p0 = pts[shift]
            p1 = pts[(shift + 1) % 4]
            p2 = pts[(shift + 2) % 4]
            p3 = pts[(shift + 3) % 4]
            int_01_32 = intersect_lines(p0, p1, p3, p2)
            if int_01_32:
                d_vp2 = math.hypot(int_01_32[0] - vp2[0], int_01_32[1] - vp2[1])
                d_vp1 = math.hypot(int_01_32[0] - vp1[0], int_01_32[1] - vp1[1])
                if d_vp2 < d_vp1:
                    if p0[0] <= p1[0]:
                        return [p0, p1, p2, p3]
                    else:
                        return [p1, p0, p3, p2]
        return pts

    def _get_bounded_quads(self, vps, bounds, mode_type):
        vp1 = vps["VP1"]["center"]
        vp2 = vps["VP2"]["center"]
        y_hor = (vp1[1] + vp2[1]) / 2.0
        rect = self._page_rect([vp1, vp2, vps["VP3"]["center"]])

        floor_quad = None
        ceiling_quad = None

        if mode_type == "mode7_reverse":
            all_target_pts, u_pts, four_pts = bounds
            floor_quad = self._orient_quad_for_grid(four_pts, vp1, vp2)
            u_back = intersect_lines(vp2, u_pts[0], vp1, u_pts[2])
            if not u_back:
                u_back = (
                    (u_pts[0][0] + u_pts[2][0]) - u_pts[1][0],
                    (u_pts[0][1] + u_pts[2][1]) - u_pts[1][1],
                )
            ceil_pts = [u_pts[0], u_pts[1], u_pts[2], u_back]
            ceiling_quad = self._orient_quad_for_grid(ceil_pts, vp1, vp2)

        elif mode_type in ("mode5", "mode7_legacy"):
            bp1, bp2, bp3, bp4 = bounds
            p14 = intersect_lines(vp1, bp1, vp2, bp2)
            p23 = intersect_lines(vp1, bp2, vp2, bp1)
            if not p14 or not p23:
                return {}
            base_sector = [bp1, p14, bp2, p23]
            floor_quad = self._orient_quad_for_grid(base_sector, vp1, vp2)

            if bp3 is not None and bp4 is not None and (bp3[1] < y_hor or bp4[1] < y_hor):
                c14 = intersect_lines(vp1, bp3, vp2, bp4)
                c23 = intersect_lines(vp1, bp4, vp2, bp3)
                if c14 and c23:
                    ceiling_quad = self._orient_quad_for_grid([bp3, c14, bp4, c23], vp1, vp2)
                else:
                    sym = [(p[0], 2.0 * y_hor - p[1]) for p in base_sector]
                    ceiling_quad = self._orient_quad_for_grid(sym, vp1, vp2)
            else:
                sym = [(p[0], 2.0 * y_hor - p[1]) for p in base_sector]
                ceiling_quad = self._orient_quad_for_grid(sym, vp1, vp2)

        else:
            dx = vp2[0] - vp1[0]
            x1 = vp1[0] + 0.35 * dx
            x2 = vp1[0] + 0.65 * dx
            delta_y = max(80.0, 0.4 * abs(rect[3] - y_hor))

            yf = y_hor + delta_y
            b1, b2 = (x1, yf), (x2, yf)
            p14 = intersect_lines(vp1, b1, vp2, b2)
            p23 = intersect_lines(vp1, b2, vp2, b1)
            if not p14 or not p23:
                return {}
            floor_quad = self._orient_quad_for_grid([b1, p14, b2, p23], vp1, vp2)

            yc = y_hor - delta_y
            b1, b2 = (x1, yc), (x2, yc)
            p14 = intersect_lines(vp1, b1, vp2, b2)
            p23 = intersect_lines(vp1, b2, vp2, b1)
            if not p14 or not p23:
                return {}
            ceiling_quad = self._orient_quad_for_grid([b1, p14, b2, p23], vp1, vp2)

        quads = {}
        if floor_quad is not None:
            quads["floor"] = floor_quad
        if ceiling_quad is not None:
            quads["ceiling"] = ceiling_quad

        if floor_quad is not None and ceiling_quad is not None:
            NL_f, NR_f, FR_f, FL_f = floor_quad
            NL_c, NR_c, FR_c, FL_c = ceiling_quad
            quads["left_wall"] = [NL_f, FL_f, FL_c, NL_c]
            quads["right_wall"] = [NR_f, FR_f, FR_c, NR_c]
            quads["front_wall"] = [NL_f, NR_f, NR_c, NL_c]
            quads["back_wall"] = [FL_f, FR_f, FR_c, FL_c]

        return quads

    def _build_quad_grid(self, subgroup, H, prefix, gx, gy):
        for i in range(gx):
            for j in range(gy):
                u0, u1 = i / gx, (i + 1) / gx
                v0, v1 = j / gy, (j + 1) / gy
                p1 = project_point(H, u0, v0)
                p2 = project_point(H, u1, v0)
                p3 = project_point(H, u1, v1)
                p4 = project_point(H, u0, v1)
                if p1 is None or p2 is None or p3 is None or p4 is None:
                    continue
                d = (
                    f"M {p1[0]:.4f},{p1[1]:.4f} "
                    f"L {p2[0]:.4f},{p2[1]:.4f} "
                    f"L {p3[0]:.4f},{p3[1]:.4f} "
                    f"L {p4[0]:.4f},{p4[1]:.4f} Z"
                )
                cell = inkex.PathElement(d=d)
                cell.set("class", "grid-cell")
                cell.set("style", "fill:none;stroke:#333333;stroke-width:0.5;")
                cell.set("id", f"{prefix}_cell_{i}_{j}")
                subgroup.add(cell)

    def _get_bottom_anchor(self, vps, bounds, mode_type, rect):
        """Точка, до которой тянутся "линии перспективы" — это якорь для деления."""
        vp1 = vps["VP1"]["center"]
        vp2 = vps["VP2"]["center"]
        cx = (vp1[0] + vp2[0]) / 2.0

        if mode_type == "mode7_reverse" and bounds:
            _, _, four_pts = bounds
            return max(four_pts, key=lambda p: p[1])

        if mode_type in ("mode5", "mode7_legacy") and bounds:
            # Для mode5/mode7 - берём саму нижнюю точку из bound-маркеров
            candidates = [p for p in bounds if p is not None]
            if candidates:
                return max(candidates, key=lambda p: p[1])

        return (cx, rect[3])

    def _generate_grid(self, vps, bounds, mode_type):
        gx = int(self.options.grid_x)
        gy = int(self.options.grid_y)
        if gx < 1 or gy < 1:
            raise inkex.AbortExtension("Grid segments must be at least 1.")

        rect = self._page_rect()
        g_grid = inkex.Group(id="Perspective_Grid")

        vp1 = vps["VP1"]["center"]
        vp2 = vps["VP2"]["center"]
        bottom_pt = self._get_bottom_anchor(vps, bounds, mode_type, rect)

        # 1. Within the lines of perspective
        if self.options.show_within_perspective:
            subgroup = inkex.Group(id="Grid_WithinPerspective")
            g_grid.add(subgroup)
            self._build_perspective_grid(
                subgroup, vp1, vp2, bottom_pt, gx, gy,
                extend_edges=False, rect=rect
            )

        # 2. To the edge of the page
        if self.options.show_to_page_edge:
            subgroup = inkex.Group(id="Grid_ToTheEdgeOfPage")
            g_grid.add(subgroup)
            self._build_perspective_grid(
                subgroup, vp1, vp2, bottom_pt, gx, gy,
                extend_edges=True, rect=rect
            )

        # 3. Bounded surfaces (homography)
        quads = self._get_bounded_quads(vps, bounds, mode_type)
        surface_map = {
            "show_floor": ("floor", "Grid_Floor"),
            "show_ceiling": ("ceiling", "Grid_Ceiling"),
            "show_left_wall": ("left_wall", "Grid_LeftWall"),
            "show_right_wall": ("right_wall", "Grid_RightWall"),
            "show_front_wall": ("front_wall", "Grid_FrontWall"),
            "show_back_wall": ("back_wall", "Grid_BackWall"),
        }
        for opt_name, (surf_key, group_id) in surface_map.items():
            if getattr(self.options, opt_name, False) and surf_key in quads:
                quad = quads[surf_key]
                H = get_homography_matrix(quad)
                if H is not None:
                    subgroup = inkex.Group(id=group_id)
                    g_grid.add(subgroup)
                    self._build_quad_grid(subgroup, H, group_id, gx, gy)

        return g_grid if len(g_grid) > 0 else None

    def effect(self):
        vps, bounds, mode_type = self.analyze_selection()
        layer = self.svg.get_current_layer()

        old_rays = self.svg.getElementById("Perspective_Rays")
        if self.options.show_rays:
            temporary_rays_layer = inkex.Group()
            self.draw_rays(temporary_rays_layer, vps, bounds, mode_type)
            new_rays_group = temporary_rays_layer[0] if len(temporary_rays_layer) else None
            if new_rays_group is not None:
                layer.add(new_rays_group)
            if old_rays is not None and old_rays is not new_rays_group and old_rays.getparent() is not None:
                old_rays.getparent().remove(old_rays)
        else:
            if old_rays is not None and old_rays.getparent() is not None:
                old_rays.getparent().remove(old_rays)

        old_grid = self.svg.getElementById("Perspective_Grid")
        if self.options.show_grid:
            grid_group = self._generate_grid(vps, bounds, mode_type)
            if grid_group is not None:
                layer.add(grid_group)
            if old_grid is not None and old_grid is not grid_group and old_grid.getparent() is not None:
                old_grid.getparent().remove(old_grid)
        else:
            if old_grid is not None and old_grid.getparent() is not None:
                old_grid.getparent().remove(old_grid)


if __name__ == "__main__":
    PerspectiveGrid().run()