#!/usr/bin/env python3
"""
V25 Hologram — OpenGL Simulator
================================
Interactive 3D visualization of the clamshell UCNP hologram system.

RENDERS:
  - Clamshell hardware: two curved bowls (top + bottom), 3 support pillars
  - VCSELs on both bowl rims (4 bottom + 4 top, offset 45°)
  - RGB laser at bottom bowl center
  - Nebulizer nozzle
  - Ultrasound field visualization (standing wave nodes)
  - UCNP upconversion hologram (multi-layer glow)
  - VCSEL series firing animation (slow-mo mode)
  - Touch interaction demo (simulated hand + haptic waves)
  - Consumption stats overlay

Controls:
  Left-drag/Arrows — Orbit camera
  Right-drag       — Pan camera
  Scroll/W/E       — Zoom
  D                — Cycle lighting (dark room / night / indoor daylight)
  L                — Toggle VCSEL beam visibility
  U                — Toggle ultrasound field visualization
  B                — Toggle hardware chassis
  C                — Cycle color mode
  P                — Cycle VCSEL series power
  T                — Toggle touch interaction demo
  S                — Slow-mo scan mode
  M                — Toggle consumption stats overlay
  +/-              — Adjust scan speed
  1-3              — Switch object
  R                — Reset camera
  SPACE            — Pause
  ESC/Q            — Quit
"""

import numpy as np
import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WINDOW_W, WINDOW_H = 1280, 900
FPS = 60

# UCNP emission colors
UCNP_GREEN = np.array([0.30, 0.92, 0.40], dtype=np.float32)
UCNP_RED = np.array([0.90, 0.25, 0.15], dtype=np.float32)
UCNP_BLUE = np.array([0.20, 0.35, 0.95], dtype=np.float32)
UCNP_WARM = np.array([0.70, 0.80, 0.45], dtype=np.float32)

POWER_LEVELS = [
    (2,  0.5,  "8×2μJ series — gentle, dark room"),
    (5,  1.0,  "8×5μJ series — standard indoor"),
    (12, 1.8,  "8×12μJ series — bright, indoor daylight"),
    (20, 2.5,  "8×20μJ series — max, vivid daylight"),
]


# ── Drawing primitives ──

def _cube(h):
    glBegin(GL_QUADS)
    for face in [[(-h,-h,-h),(h,-h,-h),(h,h,-h),(-h,h,-h)],
                 [(-h,-h,h),(h,-h,h),(h,h,h),(-h,h,h)],
                 [(-h,-h,-h),(-h,-h,h),(-h,h,h),(-h,h,-h)],
                 [(h,-h,-h),(h,-h,h),(h,h,h),(h,h,-h)],
                 [(-h,h,-h),(h,h,-h),(h,h,h),(-h,h,h)],
                 [(-h,-h,-h),(h,-h,-h),(h,-h,h),(-h,-h,h)]]:
        for v in face:
            glVertex3f(*v)
    glEnd()


def _draw_ring(cx, cy, cz, radius, segments, r, g, b, a, lw=1.5):
    glColor4f(r, g, b, a)
    glLineWidth(lw)
    glBegin(GL_LINE_LOOP)
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        glVertex3f(cx + radius * math.cos(angle), cy,
                   cz + radius * math.sin(angle))
    glEnd()


def _draw_disc(cx, cy, cz, radius, segments, r, g, b, a):
    glColor4f(r, g, b, a)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(cx, cy, cz)
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        glVertex3f(cx + radius * math.cos(angle), cy,
                   cz + radius * math.sin(angle))
    glEnd()


def _pts_array(pts, rgba, n, sz):
    glPointSize(sz)
    glEnableClientState(GL_VERTEX_ARRAY)
    glEnableClientState(GL_COLOR_ARRAY)
    glVertexPointer(3, GL_FLOAT, 0, pts[:n].tobytes())
    glColorPointer(4, GL_FLOAT, 0, rgba[:n].tobytes())
    glDrawArrays(GL_POINTS, 0, n)
    glDisableClientState(GL_VERTEX_ARRAY)
    glDisableClientState(GL_COLOR_ARRAY)


class HologramSimulator:
    """
    OpenGL interactive simulator for the V25 clamshell hologram.

    Renders the full hardware (dual bowls, pillars, VCSELs, transducers)
    and the UCNP upconversion hologram with proper physics visualization.
    """

    def __init__(self, system=None):
        self.system = system
        if system:
            cfg = system.cfg
        else:
            import yaml
            config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f)

        fc = cfg['frame']
        dc = cfg['display']
        vc = cfg['vcsel_array']

        self.bowl_radius = fc['bowl_sphere_radius_m']
        self.cap_angle_deg = fc['bowl_cap_angle_deg']
        self.pillar_count = fc['pillar_count']
        self.display_radius = dc['radius_m']
        self.display_center_y = dc['center_height_m']
        self.display_center = np.array([0.0, self.display_center_y, 0.0])

        self.n_vcsel_bottom = vc['count_bottom']
        self.n_vcsel_top = vc['count_top']
        self.n_vcsels = vc['total']
        self.vcsel_tilt = vc['tilt_inward_deg']

        # Precompute geometry
        self._build_hardware_geometry()

        # Display data
        self.pts = None
        self.colors = None
        self.n_points = 0

    def _build_hardware_geometry(self):
        """Precompute VCSEL positions, transducer positions, pillar coords."""
        cap_rad = math.radians(self.cap_angle_deg)
        rim_r = self.bowl_radius * math.sin(cap_rad)
        rim_y = self.bowl_radius * math.cos(cap_rad)

        # VCSEL positions on bowl rims
        self.vcsel_positions = []
        self.vcsel_bowls = []
        for i in range(self.n_vcsel_bottom):
            angle = 2 * math.pi * i / self.n_vcsel_bottom
            x = rim_r * math.cos(angle)
            z = rim_r * math.sin(angle)
            self.vcsel_positions.append(np.array([x, -rim_y, z]))
            self.vcsel_bowls.append('bottom')
        for i in range(self.n_vcsel_top):
            angle = 2 * math.pi * i / self.n_vcsel_top + math.pi / self.n_vcsel_top
            x = rim_r * math.cos(angle)
            z = rim_r * math.sin(angle)
            self.vcsel_positions.append(np.array([x, rim_y, z]))
            self.vcsel_bowls.append('top')

        # Transducer positions (for visualization — sparse subset)
        self.trans_bot = []
        self.trans_top = []
        rings = 5
        base_per = 10
        for ring in range(rings):
            theta = (ring + 1) / rings * cap_rad
            n_in = base_per + ring * 6
            for i in range(n_in):
                phi = 2 * math.pi * i / n_in
                x = self.bowl_radius * math.sin(theta) * math.cos(phi)
                z = self.bowl_radius * math.sin(theta) * math.sin(phi)
                y_b = -self.bowl_radius * math.cos(theta)
                y_t = self.bowl_radius * math.cos(theta)
                self.trans_bot.append(np.array([x, y_b, z]))
                self.trans_top.append(np.array([x, y_t, z]))

        # Pillar positions
        self.pillar_angles = [2 * math.pi * i / self.pillar_count
                              for i in range(self.pillar_count)]
        self.rim_r = rim_r
        self.rim_y = rim_y

        # RGB laser position (bottom bowl center)
        self.rgb_pos = np.array([0.0, -self.bowl_radius + 0.01, 0.0])
        # Nebulizer nozzle
        self.neb_pos = np.array([0.015, -self.bowl_radius + 0.015, 0.0])

    def _load_display_data(self):
        """Get point cloud data from system or generate default."""
        if self.system and self.system._voxel_positions is not None:
            self.pts = self.system._voxel_positions.copy()
            self.colors = self.system._voxel_colors.copy()
            # Offset to display center if needed
            self.pts[:, 1] += self.display_center_y
        else:
            # Generate sphere
            n = 500000
            phi = np.random.uniform(0, 2 * np.pi, n)
            ct = np.random.uniform(-1, 1, n)
            st = np.sqrt(1 - ct ** 2)
            r = self.display_radius
            self.pts = np.column_stack([
                r * st * np.cos(phi),
                r * st * np.sin(phi) + self.display_center_y,
                r * ct,
            ]).astype(np.float32)
            # Rainbow
            hue = phi / (2 * np.pi)
            self.colors = np.zeros((n, 3), dtype=np.float32)
            h6 = hue * 6
            sec = h6.astype(int) % 6
            f = h6 - np.floor(h6)
            v = np.ones(n); sa = 0.7
            p = v * (1 - sa); q = v * (1 - sa * f); t = v * (1 - sa * (1 - f))
            for i in range(6):
                m = sec == i
                if i == 0:   self.colors[m] = np.column_stack([v, t, p])[m]
                elif i == 1: self.colors[m] = np.column_stack([q, v, p])[m]
                elif i == 2: self.colors[m] = np.column_stack([p, v, t])[m]
                elif i == 3: self.colors[m] = np.column_stack([p, q, v])[m]
                elif i == 4: self.colors[m] = np.column_stack([t, p, v])[m]
                elif i == 5: self.colors[m] = np.column_stack([v, p, q])[m]

        self.n_points = len(self.pts)

        # Try loading cat model
        self.objects = {}
        cat_obj = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               '12221_Cat_v1_l3.obj')
        cat_tex = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               'Cat_diffuse.jpg')
        if os.path.exists(cat_obj):
            try:
                from voxel_engine import VoxelEngine
                ve = VoxelEngine(os.path.join(os.path.dirname(__file__),
                                              'config.yaml'))
                cpts, ccols, _ = ve.load_mesh(cat_obj,
                                               cat_tex if os.path.exists(cat_tex) else None,
                                               n_points=500000)
                self.objects['Cat'] = (cpts, ccols)
            except Exception as e:
                print(f"[SIM] Cat load failed: {e}")

        self.objects['Sphere'] = (self.pts.copy(), self.colors.copy())
        self.obj_names = list(self.objects.keys())
        self.obj_idx = 0
        self._set_object(self.obj_names[0])

    def _set_object(self, name):
        if name in self.objects:
            self.pts, self.colors = self.objects[name]
            self.n_points = len(self.pts)

    # ── Hardware rendering ──

    def _draw_bowl(self, pole_sign, alpha):
        """Draw one spherical cap bowl with transducer dots."""
        R = self.bowl_radius
        cap_rad = math.radians(self.cap_angle_deg)
        n_rings = 12
        n_segs = 32

        # Bowl surface
        glColor4f(0.06, 0.08, 0.12, alpha)
        for ring in range(n_rings):
            t0 = ring / n_rings * cap_rad
            t1 = (ring + 1) / n_rings * cap_rad
            glBegin(GL_QUAD_STRIP)
            for seg in range(n_segs + 1):
                phi = 2 * math.pi * seg / n_segs
                for theta in [t0, t1]:
                    x = R * math.sin(theta) * math.cos(phi)
                    z = R * math.sin(theta) * math.sin(phi)
                    y = pole_sign * R * math.cos(theta)
                    glVertex3f(x, y, z)
            glEnd()

        # Bowl rim accent
        glColor4f(0.18, 0.22, 0.32, alpha + 0.15)
        glLineWidth(1.8)
        glBegin(GL_LINE_LOOP)
        for seg in range(n_segs):
            phi = 2 * math.pi * seg / n_segs
            x = R * math.sin(cap_rad) * math.cos(phi)
            z = R * math.sin(cap_rad) * math.sin(phi)
            y = pole_sign * R * math.cos(cap_rad)
            glVertex3f(x, y, z)
        glEnd()

        # Transducer dots
        trans = self.trans_bot if pole_sign < 0 else self.trans_top
        glPointSize(2.5)
        glBegin(GL_POINTS)
        for t in trans:
            glColor4f(0.22, 0.28, 0.40, alpha + 0.1)
            glVertex3f(t[0], t[1], t[2])
        glEnd()

    def _draw_chassis(self, show_base):
        """Draw full clamshell hardware."""
        if not show_base:
            return

        # Bottom bowl (more opaque — it's the base)
        self._draw_bowl(-1, 0.55)
        # Top bowl (more transparent for visibility)
        self._draw_bowl(+1, 0.30)

        # Support pillars (3 at 120° on the rim)
        glColor4f(0.14, 0.14, 0.18, 0.6)
        glLineWidth(3.0)
        for angle in self.pillar_angles:
            x = self.rim_r * math.cos(angle)
            z = self.rim_r * math.sin(angle)
            glBegin(GL_LINES)
            glVertex3f(x, -self.rim_y, z)
            glVertex3f(x, self.rim_y, z)
            glEnd()
            # Pillar caps (small cubes at top and bottom)
            for y_sign in [-1, 1]:
                glPushMatrix()
                glTranslatef(x, y_sign * self.rim_y, z)
                glColor4f(0.18, 0.18, 0.22, 0.8)
                _cube(0.005)
                glPopMatrix()

        # VCSELs on both rims
        for i, (pos, bowl) in enumerate(zip(self.vcsel_positions,
                                             self.vcsel_bowls)):
            glPushMatrix()
            glTranslatef(pos[0], pos[1], pos[2])
            # VCSEL housing
            glColor4f(0.22, 0.22, 0.26, 1.0)
            _cube(0.006)
            # IR lens (dark red tint for 980nm)
            lens_y = 0.005 if bowl == 'bottom' else -0.005
            glTranslatef(0, lens_y, 0)
            glColor4f(0.28, 0.08, 0.08, 0.9)
            _cube(0.003)
            glPopMatrix()

        # RGB laser at bottom bowl center
        glPushMatrix()
        glTranslatef(self.rgb_pos[0], self.rgb_pos[1], self.rgb_pos[2])
        glColor4f(0.15, 0.15, 0.22, 1.0)
        _cube(0.005)
        glTranslatef(0, 0.006, 0)
        glColor4f(0.3, 0.3, 0.4, 0.8)
        _cube(0.003)
        glPopMatrix()

        # Nebulizer nozzle
        glPushMatrix()
        glTranslatef(self.neb_pos[0], self.neb_pos[1], self.neb_pos[2])
        glColor4f(0.20, 0.20, 0.15, 1.0)
        _cube(0.004)
        glTranslatef(0, 0.005, 0)
        glColor4f(0.30, 0.28, 0.20, 0.9)
        _cube(0.002)
        glPopMatrix()

    # ── Visualization effects ──

    def _draw_ultrasound_field(self, target, show_us, time_val):
        """Ultrasonic standing wave nodes as pulsing shells."""
        if not show_us:
            return
        glLineWidth(0.8)
        cy = self.display_center_y
        for shell in range(3):
            r = self.display_radius * (0.4 + shell * 0.3)
            pulse = 0.5 + 0.5 * math.sin(time_val * 15.0 + shell * 1.5)
            alpha = 0.04 + 0.03 * pulse
            glColor4f(0.3, 0.5, 0.8, alpha)
            # Horizontal ring
            glBegin(GL_LINE_LOOP)
            for i in range(48):
                a = 2 * math.pi * i / 48
                glVertex3f(r * math.cos(a), cy, r * math.sin(a))
            glEnd()
            # Vertical rings
            for a_deg in [0, 90]:
                a = math.radians(a_deg)
                glBegin(GL_LINE_LOOP)
                for i in range(48):
                    p = 2 * math.pi * i / 48
                    glVertex3f(r * math.sin(p) * math.cos(a),
                               cy + r * math.cos(p),
                               r * math.sin(p) * math.sin(a))
                glEnd()

        # Convergence lines from transducers (sparse)
        glLineWidth(0.6)
        for trans_list in [self.trans_bot, self.trans_top]:
            for i in range(0, len(trans_list), 8):
                pos = trans_list[i]
                glBegin(GL_LINES)
                glColor4f(0.2, 0.3, 0.6, 0.015)
                glVertex3f(pos[0], pos[1], pos[2])
                glColor4f(0.3, 0.5, 0.8, 0.04)
                glVertex3f(target[0], target[1], target[2])
                glEnd()

    def _draw_vcsel_beams_volume(self, show_laser):
        """All 8 VCSEL beams converging at display center."""
        if not show_laser:
            return
        glLineWidth(1.0)
        cx, cy, cz = 0.0, self.display_center_y, 0.0
        for pos in self.vcsel_positions:
            glBegin(GL_LINES)
            glColor4f(0.5, 0.08, 0.08, 0.03)
            glVertex3f(pos[0], pos[1], pos[2])
            glColor4f(0.6, 0.12, 0.12, 0.10)
            glVertex3f(cx, cy, cz)
            glEnd()

    def _draw_vcsel_beams_series(self, target, show_laser, voxel_color,
                                  series_phase):
        """Slow-mo: VCSELs fire alternating B/T, one at a time."""
        if not show_laser:
            return
        active = int(series_phase * self.n_vcsels) % self.n_vcsels

        for i, pos in enumerate(self.vcsel_positions):
            if i == active:
                glLineWidth(2.0)
                glBegin(GL_LINES)
                glColor4f(0.8, 0.1, 0.1, 0.10)
                glVertex3f(pos[0], pos[1], pos[2])
                glColor4f(1.0, 0.2, 0.15, 0.40)
                glVertex3f(target[0], target[1], target[2])
                glEnd()
            elif i < active:
                fade = 1.0 - (active - i) / self.n_vcsels
                glLineWidth(1.0)
                glBegin(GL_LINES)
                glColor4f(0.5, 0.08, 0.08, 0.02 * fade)
                glVertex3f(pos[0], pos[1], pos[2])
                glColor4f(0.6, 0.12, 0.12, 0.08 * fade)
                glVertex3f(target[0], target[1], target[2])
                glEnd()

        # RGB color beams from bottom
        glLineWidth(1.0)
        rgb_c = [(0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.1, 0.9)]
        for vi in range(3):
            r, g, b = rgb_c[vi]
            intensity = voxel_color[vi] * 0.12
            glBegin(GL_LINES)
            glColor4f(r, g, b, intensity * 0.3)
            glVertex3f(self.rgb_pos[0], self.rgb_pos[1], self.rgb_pos[2])
            glColor4f(r, g, b, intensity)
            glVertex3f(target[0], target[1], target[2])
            glEnd()

        # Upconversion buildup flash
        buildup = (active + 1) / self.n_vcsels
        flash_size = 4.0 + buildup * 6.0
        glPointSize(flash_size)
        glBegin(GL_POINTS)
        glColor4f(UCNP_GREEN[0] * buildup, UCNP_GREEN[1] * buildup,
                  UCNP_GREEN[2] * buildup, 0.3 + 0.6 * buildup)
        glVertex3f(target[0], target[1], target[2])
        glEnd()

    def _draw_ucnp_mist(self, show_us, time_val):
        """Faint ambient UCNP particles in display volume."""
        if not show_us:
            return
        rng = np.random.RandomState(77)
        glPointSize(1.5)
        glBegin(GL_POINTS)
        for i in range(40):
            theta = rng.uniform(0, 2 * math.pi)
            phi = rng.uniform(-1, 1)
            r = self.display_radius * rng.uniform(0.2, 0.95)
            sp = math.sqrt(1 - phi * phi)
            x = r * sp * math.cos(theta)
            y = r * phi + self.display_center_y
            z = r * sp * math.sin(theta)
            drift = math.sin(time_val * 0.5 + i * 0.7) * 0.002
            glColor4f(0.4, 0.5, 0.35, 0.06 + 0.03 * math.sin(time_val + i))
            glVertex3f(x + drift, y, z)
        glEnd()

    def _draw_touch_demo(self, show_touch, time_val):
        """Simulated hand with haptic feedback waves."""
        if not show_touch:
            return
        phase = (math.sin(time_val * 0.8) + 1) / 2
        fx = 0.08 * (1 - phase)
        fy = self.display_center_y - 0.02
        fz = 0.0

        glColor4f(0.65, 0.50, 0.42, 0.6)
        glPushMatrix()
        glTranslatef(fx, fy, fz)
        _cube(0.008)
        glTranslatef(-0.012, 0, 0)
        glColor4f(0.60, 0.48, 0.40, 0.7)
        _cube(0.006)
        glPopMatrix()

        if phase > 0.3:
            glLineWidth(1.0)
            for w in range(3):
                wr = 0.005 + w * 0.004 + math.sin(time_val * 12 + w) * 0.002
                alpha = 0.15 * (1 - w / 3)
                glColor4f(0.4, 0.6, 0.9, alpha)
                glBegin(GL_LINE_LOOP)
                for i in range(16):
                    a = 2 * math.pi * i / 16
                    glVertex3f(fx - 0.012 + wr * math.cos(a),
                               fy + wr * math.sin(a), fz)
                glEnd()

    # ── Environment ──

    def _draw_daylight_room(self):
        """Realistic indoor room with window, desk, walls, sunlight."""
        floor_y = -self.bowl_radius - 0.02
        ceil_y = 0.45
        wall_l = -0.55   # left
        wall_r = 0.55    # right
        wall_b = -0.50   # back
        wall_f = 0.50    # front (behind camera usually)

        # ── Floor — wood-tone desk surface ──
        # Desk top (where the device sits)
        glColor4f(0.42, 0.30, 0.20, 0.92)
        glBegin(GL_QUADS)
        glVertex3f(-0.35, floor_y, -0.30)
        glVertex3f(0.35, floor_y, -0.30)
        glVertex3f(0.35, floor_y, 0.30)
        glVertex3f(-0.35, floor_y, 0.30)
        glEnd()
        # Desk edge bevel
        glColor4f(0.35, 0.24, 0.16, 0.85)
        desk_th = 0.008
        glBegin(GL_QUADS)
        # Front edge
        glVertex3f(-0.35, floor_y, 0.30)
        glVertex3f(0.35, floor_y, 0.30)
        glVertex3f(0.35, floor_y - desk_th, 0.30)
        glVertex3f(-0.35, floor_y - desk_th, 0.30)
        # Right edge
        glVertex3f(0.35, floor_y, -0.30)
        glVertex3f(0.35, floor_y, 0.30)
        glVertex3f(0.35, floor_y - desk_th, 0.30)
        glVertex3f(0.35, floor_y - desk_th, -0.30)
        # Left edge
        glVertex3f(-0.35, floor_y, -0.30)
        glVertex3f(-0.35, floor_y, 0.30)
        glVertex3f(-0.35, floor_y - desk_th, 0.30)
        glVertex3f(-0.35, floor_y - desk_th, -0.30)
        glEnd()

        # Room floor below desk
        glColor4f(0.52, 0.42, 0.32, 0.5)
        glBegin(GL_QUADS)
        glVertex3f(wall_l, floor_y - desk_th - 0.001, wall_b)
        glVertex3f(wall_r, floor_y - desk_th - 0.001, wall_b)
        glVertex3f(wall_r, floor_y - desk_th - 0.001, wall_f)
        glVertex3f(wall_l, floor_y - desk_th - 0.001, wall_f)
        glEnd()

        # ── Back wall — light grey with warm sunlight tint ──
        glBegin(GL_QUADS)
        # Lower part (shadow)
        glColor4f(0.62, 0.60, 0.58, 0.85)
        glVertex3f(wall_l, floor_y - desk_th, wall_b)
        glVertex3f(wall_r, floor_y - desk_th, wall_b)
        # Upper part (sunlight wash)
        glColor4f(0.78, 0.75, 0.68, 0.85)
        glVertex3f(wall_r, ceil_y, wall_b)
        glVertex3f(wall_l, ceil_y, wall_b)
        glEnd()

        # ── Side walls ──
        for xs, sign in [(wall_l, -1), (wall_r, 1)]:
            glBegin(GL_QUADS)
            glColor4f(0.60, 0.58, 0.55, 0.55)
            glVertex3f(xs, floor_y - desk_th, wall_b)
            glVertex3f(xs, floor_y - desk_th, wall_f)
            glColor4f(0.72, 0.70, 0.65, 0.55)
            glVertex3f(xs, ceil_y, wall_f)
            glVertex3f(xs, ceil_y, wall_b)
            glEnd()

        # ── Ceiling ──
        glColor4f(0.82, 0.80, 0.78, 0.4)
        glBegin(GL_QUADS)
        glVertex3f(wall_l, ceil_y, wall_b)
        glVertex3f(wall_r, ceil_y, wall_b)
        glVertex3f(wall_r, ceil_y, wall_f)
        glVertex3f(wall_l, ceil_y, wall_f)
        glEnd()

        # ── Window on back wall (right side) — bright daylight source ──
        win_l = 0.10
        win_r = 0.42
        win_b_y = 0.05
        win_t_y = 0.35
        win_z = wall_b + 0.001

        # Window glass — bright sky
        glBegin(GL_QUADS)
        glColor4f(0.72, 0.82, 0.95, 0.90)
        glVertex3f(win_l, win_b_y, win_z)
        glVertex3f(win_r, win_b_y, win_z)
        glColor4f(0.85, 0.90, 0.98, 0.90)
        glVertex3f(win_r, win_t_y, win_z)
        glVertex3f(win_l, win_t_y, win_z)
        glEnd()

        # Window frame
        glColor4f(0.35, 0.33, 0.30, 0.9)
        glLineWidth(2.5)
        glBegin(GL_LINE_LOOP)
        glVertex3f(win_l, win_b_y, win_z + 0.001)
        glVertex3f(win_r, win_b_y, win_z + 0.001)
        glVertex3f(win_r, win_t_y, win_z + 0.001)
        glVertex3f(win_l, win_t_y, win_z + 0.001)
        glEnd()
        # Cross bars
        glBegin(GL_LINES)
        mid_x = (win_l + win_r) / 2
        mid_y = (win_b_y + win_t_y) / 2
        glVertex3f(mid_x, win_b_y, win_z + 0.001)
        glVertex3f(mid_x, win_t_y, win_z + 0.001)
        glVertex3f(win_l, mid_y, win_z + 0.001)
        glVertex3f(win_r, mid_y, win_z + 0.001)
        glEnd()

        # ── Sunlight patch on desk (light coming through window) ──
        glColor4f(0.90, 0.85, 0.65, 0.18)
        glBegin(GL_QUADS)
        glVertex3f(0.05, floor_y + 0.001, -0.15)
        glVertex3f(0.32, floor_y + 0.001, -0.15)
        glVertex3f(0.28, floor_y + 0.001, 0.10)
        glVertex3f(0.02, floor_y + 0.001, 0.10)
        glEnd()

        # ── Sunlight rays from window (subtle volumetric hint) ──
        glLineWidth(1.0)
        for i in range(5):
            t = i / 4.0
            wx = win_l + t * (win_r - win_l)
            wy = win_t_y - 0.05
            # Ray from window to desk
            dx = wx - 0.08
            dy = floor_y + 0.001
            glBegin(GL_LINES)
            glColor4f(1.0, 0.95, 0.75, 0.04)
            glVertex3f(wx, wy, wall_b + 0.002)
            glColor4f(1.0, 0.95, 0.75, 0.01)
            glVertex3f(dx, dy, -0.05)
            glEnd()

        # ── Baseboard trim ──
        glColor4f(0.40, 0.38, 0.35, 0.6)
        glLineWidth(1.5)
        glBegin(GL_LINES)
        glVertex3f(wall_l, floor_y - desk_th, wall_b)
        glVertex3f(wall_r, floor_y - desk_th, wall_b)
        glEnd()

    def _draw_floor(self, daymode):
        if daymode == 2:
            self._draw_daylight_room()
            return
        y = -self.bowl_radius - 0.02
        if daymode == 1: glColor4f(0.06, 0.07, 0.10, 0.5)
        else:            glColor4f(0.08, 0.08, 0.10, 0.4)
        glBegin(GL_QUADS)
        glVertex3f(-0.3, y, -0.3); glVertex3f(0.3, y, -0.3)
        glVertex3f(0.3, y, 0.3);   glVertex3f(-0.3, y, 0.3)
        glEnd()
        if daymode == 1: glColor4f(0.08, 0.09, 0.14, 0.3)
        else:            glColor4f(0.12, 0.12, 0.16, 0.3)
        glBegin(GL_LINES)
        for i in range(21):
            x = -0.3 + i * 0.03
            glVertex3f(x, y + 0.0001, -0.3); glVertex3f(x, y + 0.0001, 0.3)
            glVertex3f(-0.3, y + 0.0001, x);  glVertex3f(0.3, y + 0.0001, x)
        glEnd()

    def _draw_night_env(self):
        floor_y = -self.bowl_radius - 0.02
        glColor4f(0.04, 0.04, 0.06, 0.3)
        glBegin(GL_QUADS)
        glVertex3f(-0.4, floor_y, -0.35); glVertex3f(0.4, floor_y, -0.35)
        glVertex3f(0.4, 0.30, -0.35);     glVertex3f(-0.4, 0.30, -0.35)
        glEnd()
        for xs in [-1, 1]:
            glColor4f(0.035, 0.035, 0.05, 0.2)
            glBegin(GL_QUADS)
            glVertex3f(xs*0.4, floor_y, -0.35); glVertex3f(xs*0.4, floor_y, 0.35)
            glVertex3f(xs*0.4, 0.30, 0.35);     glVertex3f(xs*0.4, 0.30, -0.35)
            glEnd()

    def _draw_outdoor_night(self):
        glBegin(GL_QUADS)
        glColor4f(0.05, 0.06, 0.10, 0.6)
        glVertex3f(-1.0, -0.1, -0.8); glVertex3f(1.0, -0.1, -0.8)
        glColor4f(0.02, 0.02, 0.06, 0.6)
        glVertex3f(1.0, 0.6, -0.8);   glVertex3f(-1.0, 0.6, -0.8)
        glEnd()
        glPushMatrix()
        glTranslatef(0.25, 0.35, -0.7)
        glColor4f(0.7, 0.7, 0.6, 0.4); glPointSize(12.0)
        glBegin(GL_POINTS); glVertex3f(0, 0, 0); glEnd()
        glColor4f(0.3, 0.3, 0.25, 0.1); glPointSize(30.0)
        glBegin(GL_POINTS); glVertex3f(0, 0, 0); glEnd()
        glPopMatrix()

    def _draw_volume_wire(self):
        glColor4f(0.15, 0.25, 0.35, 0.06)
        glLineWidth(1.0)
        cy = self.display_center_y
        for lat in range(0, 180, 30):
            glBegin(GL_LINE_LOOP)
            phi = math.radians(lat)
            r = self.display_radius * math.sin(phi)
            y = self.display_radius * math.cos(phi) + cy
            for i in range(64):
                a = 2 * math.pi * i / 64
                glVertex3f(r * math.cos(a), y, r * math.sin(a))
            glEnd()
        for lon in range(0, 360, 45):
            glBegin(GL_LINE_STRIP)
            a = math.radians(lon)
            for i in range(65):
                p = math.pi * i / 64
                glVertex3f(self.display_radius * math.sin(p) * math.cos(a),
                           self.display_radius * math.cos(p) + cy,
                           self.display_radius * math.sin(p) * math.sin(a))
            glEnd()

    # ── Hologram rendering ──

    def _draw_hologram_solid(self, pts, colors, n, daymode, cmode, plevel):
        """Render UCNP upconversion voxels with multi-layer glow."""
        c = colors[:n]
        p = pts[:n].astype(np.float32)
        _, bmult_base, _ = POWER_LEVELS[plevel]
        bmult = bmult_base

        if daymode == 2:
            # Indoor daylight — ambient IR boost
            ambient = 1.4
            dm = bmult * 0.38 * ambient
            if cmode == 0:
                gc = np.tile(UCNP_GREEN, (n, 1)) * 0.7 + np.tile(UCNP_RED, (n, 1)) * 0.15
                outer = np.column_stack([np.clip(gc * 0.25 * dm, 0, 1),
                                         np.full(n, min(0.16 * dm, 0.45))]).astype(np.float32)
                mid = np.column_stack([np.clip(gc * 0.45 * dm, 0, 1),
                                       np.full(n, min(0.28 * dm, 0.55))]).astype(np.float32)
                core = np.column_stack([np.clip(gc * 0.65 * dm, 0, 1),
                                        np.full(n, min(0.40 * dm, 0.65))]).astype(np.float32)
            else:
                blend = 0.30 if cmode == 1 else 0.40
                gc_add = UCNP_GREEN * (0.12 if cmode == 1 else 0.0) * dm
                outer = np.column_stack([np.clip(c * blend * dm + gc_add, 0, 1),
                                         np.full(n, min(0.14 * dm, 0.40))]).astype(np.float32)
                mid = np.column_stack([np.clip(c * (blend + 0.08) * dm + gc_add * 0.8, 0, 1),
                                       np.full(n, min(0.24 * dm, 0.50))]).astype(np.float32)
                core = np.column_stack([np.clip(c * (blend + 0.12) * dm + gc_add * 0.5, 0, 1),
                                        np.full(n, min(0.34 * dm, 0.58))]).astype(np.float32)
            _pts_array(p, outer, n, 3.5)
            _pts_array(p, mid, n, 2.2)
            _pts_array(p, core, n, 1.4)

        elif daymode == 1:
            # Night outdoor
            nm = min(bmult * 0.80, 3.8)
            if cmode == 0:
                gc = np.tile(UCNP_GREEN, (n, 1)) * 0.75 + np.tile(UCNP_RED, (n, 1)) * 0.12
                outer = np.column_stack([np.clip(gc * 0.35 * nm, 0, 1),
                                         np.full(n, min(0.22 * nm, 0.68))]).astype(np.float32)
                mid = np.column_stack([np.clip(gc * 0.58 * nm, 0, 1),
                                       np.full(n, min(0.45 * nm, 0.82))]).astype(np.float32)
                core = np.column_stack([np.clip(gc * 0.80 * nm, 0, 1),
                                        np.full(n, min(0.65 * nm, 0.92))]).astype(np.float32)
            else:
                blend = 0.38 if cmode == 1 else 0.52
                gc_add = np.tile(UCNP_GREEN * 0.15 * nm, (n, 1)) if cmode == 1 else 0
                outer = np.column_stack([np.clip(c * blend * nm + gc_add, 0, 1),
                                         np.full(n, min(0.20 * nm, 0.65))]).astype(np.float32)
                mid = np.column_stack([np.clip(c * (blend - 0.03) * nm + np.tile(UCNP_WARM * 0.22 * nm, (n, 1)) if cmode == 1 else c * 0.48 * nm, 0, 1),
                                       np.full(n, min(0.42 * nm, 0.80))]).astype(np.float32)
                core = np.column_stack([np.clip(c * (blend - 0.10) * nm + np.tile(UCNP_GREEN * 0.30 * nm, (n, 1)) if cmode == 1 else c * 0.58 * nm, 0, 1),
                                        np.full(n, min(0.60 * nm, 0.88))]).astype(np.float32)
            _pts_array(p, outer, n, 4.2)
            _pts_array(p, mid, n, 2.6)
            _pts_array(p, core, n, 1.5)

        else:
            # Dark room — vivid
            dm = min(bmult * 1.05, 4.2)
            pt_extra = (bmult - 1.0) * 0.2
            if cmode == 0:
                gc = np.tile(UCNP_GREEN, (n, 1)) * 0.80 + np.tile(UCNP_RED, (n, 1)) * 0.10
                outer = np.column_stack([np.clip(gc * 0.48 * dm, 0, 1),
                                         np.full(n, min(0.36 * dm, 0.90))]).astype(np.float32)
                mid = np.column_stack([np.clip(gc * 0.72 * dm, 0, 1),
                                       np.full(n, min(0.62 * dm, 0.95))]).astype(np.float32)
                core = np.column_stack([np.clip(gc * 0.92 * dm, 0, 1),
                                        np.full(n, min(0.80 * dm, 0.98))]).astype(np.float32)
            elif cmode == 1:
                outer = np.column_stack([np.clip(c * 0.48 * dm + np.tile(UCNP_GREEN * 0.15 * dm, (n, 1)), 0, 1),
                                         np.full(n, min(0.34 * dm, 0.88))]).astype(np.float32)
                mid = np.column_stack([np.clip(c * 0.40 * dm + np.tile(UCNP_WARM * 0.25 * dm, (n, 1)), 0, 1),
                                       np.full(n, min(0.60 * dm, 0.94))]).astype(np.float32)
                core = np.column_stack([np.clip(c * 0.30 * dm + np.tile(UCNP_GREEN * 0.38 * dm, (n, 1)), 0, 1),
                                        np.full(n, min(0.78 * dm, 0.97))]).astype(np.float32)
            else:
                outer = np.column_stack([np.clip(c * 0.62 * dm, 0, 1),
                                         np.full(n, min(0.38 * dm, 0.90))]).astype(np.float32)
                mid = np.column_stack([np.clip(c * 0.55 * dm + np.tile(UCNP_GREEN * 0.06 * dm, (n, 1)), 0, 1),
                                       np.full(n, min(0.62 * dm, 0.95))]).astype(np.float32)
                core = np.column_stack([np.clip(c * 0.68 * dm, 0, 1),
                                        np.full(n, min(0.80 * dm, 0.97))]).astype(np.float32)
            _pts_array(p, outer, n, 4.6 + pt_extra)
            _pts_array(p, mid, n, 2.8 + pt_extra * 0.5)
            _pts_array(p, core, n, 1.6)

    def _draw_hologram_scanning(self, pts, colors, ages, frame, pov,
                                 daymode, cmode):
        """Slow-mo scan with persistence of vision."""
        age = frame - ages
        lit = (ages > 0) & (age < pov)
        idx = np.where(lit)[0]
        n = len(idx)
        if n == 0:
            return
        lp = pts[idx]; lc = colors[idx]
        fresh = np.clip(1.0 - age[idx].astype(np.float32) / pov, 0, 1)

        if daymode == 2:   alpha = fresh * 0.28; cm = 0.38
        elif daymode == 1: alpha = fresh * 0.68; cm = 0.82
        else:              alpha = fresh * 0.88; cm = 1.0

        if cmode == 0:
            gc = UCNP_GREEN * 0.80 + UCNP_RED * 0.10
            c = np.tile(gc * cm, (n, 1))
        elif cmode == 1:
            c = np.clip(lc * 0.40 * cm + np.tile(UCNP_GREEN * 0.30 * cm, (n, 1)), 0, 1)
        else:
            c = np.clip(lc * 0.60 * cm + np.tile(UCNP_GREEN * 0.08 * cm, (n, 1)), 0, 1)

        outer = np.column_stack([c * 0.5 * fresh[:, None],
                                 alpha * 0.35]).astype(np.float32)
        core = np.column_stack([c * fresh[:, None],
                                alpha * 0.82]).astype(np.float32)
        p = lp.astype(np.float32)
        _pts_array(p, outer, n, 4.0)
        _pts_array(p, core, n, 1.8)

    # ── HUD ──

    def _make_hud_tex(self, font, lines, daylight):
        fg = (30, 30, 30) if daylight else (140, 200, 160)
        bg = (200, 200, 200, 180) if daylight else (8, 12, 8, 180)
        surfs = [font.render(l, True, fg) for l in lines]
        w = max(s.get_width() for s in surfs) + 20
        h = sum(s.get_height() for s in surfs) + 16
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill(bg)
        y = 8
        for s in surfs:
            surf.blit(s, (10, y)); y += s.get_height()
        data = pygame.image.tostring(surf, "RGBA", True)
        tid = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tid)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        return tid, w, h

    def _draw_hud(self, font, st, ntot, runtime_sec):
        mode = "SLOW-MO (series firing)" if st['slow'] else "SOLID (human eye)"
        cnames = ["UPCONVERSION (green+red)", "RGB TUNED (hybrid)", "MAX COLOR"]
        _, _, pdesc = POWER_LEVELS[st['plevel']]
        dnames = ["DARK ROOM", "NIGHT OUTDOOR", "INDOOR DAYLIGHT"]
        ambient = " +40% ambient IR boost" if st['day'] == 2 else ""
        n_trans = len(self.trans_bot) + len(self.trans_top)

        if st['slow']:
            lit = int(np.sum((st['ages'] > 0) &
                             (st['frame'] - st['ages'] < st['pov'])))
            info = (f"Lit: {lit:,}  Rate: {st['rate']:,}/frame | "
                    f"Series: 8 VCSELs × 100ns = 800ns per voxel")
        else:
            info = (f"{ntot:,} voxels | UCNP upconversion + "
                    f"ultrasonic levitation{ambient}")

        lines = [
            f"V25 UCNP Clamshell Hologram | {st['obj']} | {mode}",
            f"Color: {cnames[st['cmode']]} | {pdesc}",
            f"Hardware: dual bowls (top+bottom) | {n_trans} US transducers "
            f"+ {self.n_vcsels} VCSELs + RGB",
            info,
            f"[D] {dnames[st['day']]}  [L]aser: {'on' if st['beams'] else 'off'}  "
            f"[U] US: {'on' if st['us_vis'] else 'off'}  "
            f"[B]ase: {'on' if st['base'] else 'off'}  "
            f"[T]ouch: {'on' if st['touch'] else 'off'}",
        ]

        if st['show_stats']:
            plevel = st['plevel']
            pulse_uj = POWER_LEVELS[plevel][0]
            power_mult = pulse_uj / 5.0
            active = 1e7
            vcsel_w = pulse_uj * 1e-6 * 8 * 30000
            us_w = 2.0 + power_mult * 1.5
            total_w = vcsel_w + us_w + 0.5
            lines += [
                f"UCNPs: 10M active (trapped) | Reservoir: 1T particles (1mL)",
                f"Loss: 0.1%/hr drift | Refill: ~1,000h | "
                f"Power: {total_w:.1f}W total",
            ]

        lines.append(
            f"[C]olor [P]ower [S]low-mo [M]stats [T]ouch "
            f"[+/-]speed [1-3]obj [R]eset [Q]uit"
        )

        tid, tw, th = self._make_hud_tex(font, lines, st['day'] == 2)
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
        glOrtho(0, WINDOW_W, 0, WINDOW_H, -1, 1)
        glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tid)
        glColor4f(1, 1, 1, 1)
        x, y = 8, WINDOW_H - th - 8
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(x, y)
        glTexCoord2f(1, 0); glVertex2f(x + tw, y)
        glTexCoord2f(1, 1); glVertex2f(x + tw, y + th)
        glTexCoord2f(0, 1); glVertex2f(x, y + th)
        glEnd()
        glDisable(GL_TEXTURE_2D)
        glDeleteTextures([tid])
        glPopMatrix()
        glMatrixMode(GL_PROJECTION); glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

    # ── Main loop ──

    def run(self):
        """Launch the interactive OpenGL simulator."""
        pygame.init()
        pygame.font.init()
        font = pygame.font.SysFont("monospace", 14)
        pygame.display.set_mode((WINDOW_W, WINDOW_H), DOUBLEBUF | OPENGL)
        pygame.display.set_caption(
            "V25 UCNP Clamshell Hologram — Touch + Daylight")

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_POINT_SMOOTH)
        glHint(GL_POINT_SMOOTH_HINT, GL_NICEST)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, WINDOW_W / WINDOW_H, 0.001, 10.0)
        glMatrixMode(GL_MODELVIEW)

        print("[SIM] Loading display data...")
        self._load_display_data()
        print(f"[SIM] Objects: {self.obj_names}")
        print(f"[SIM] Points: {self.n_points:,}")

        st = {
            'day': 0, 'beams': True, 'us_vis': True, 'base': True,
            'slow': False, 'paused': False, 'touch': False,
            'rate': 2000, 'cursor': 0, 'frame': 0, 'pov': 50,
            'obj': self.obj_names[0],
            'ages': np.zeros(self.n_points, dtype=np.int32),
            'cmode': 1, 'plevel': 2, 'show_stats': True,
        }

        # Camera — angled to show clamshell from the side
        cd, cy, cp = 0.40, 25.0, 12.0
        cpx, cpy = 0.0, self.display_center_y * 0.3
        clock = pygame.time.Clock()
        ml = mr = False
        lx = ly = 0
        start_time = pygame.time.get_ticks()
        time_val = 0.0
        series_phase = 0.0

        running = True
        while running:
            dt = clock.get_time() / 1000.0
            time_val += dt
            series_phase = (series_phase + dt * 5.0) % 1.0

            for ev in pygame.event.get():
                if ev.type == QUIT:
                    running = False
                elif ev.type == KEYDOWN:
                    if ev.key in (K_ESCAPE, K_q):
                        running = False
                    elif ev.key == K_d:
                        st['day'] = (st['day'] + 1) % 3
                    elif ev.key == K_l:
                        st['beams'] = not st['beams']
                    elif ev.key == K_u:
                        st['us_vis'] = not st['us_vis']
                    elif ev.key == K_b:
                        st['base'] = not st['base']
                    elif ev.key == K_t:
                        st['touch'] = not st['touch']
                    elif ev.key == K_s:
                        st['slow'] = not st['slow']
                        if not st['slow']:
                            st['ages'][:] = 0
                            st['cursor'] = 0
                            st['frame'] = 0
                    elif ev.key == K_c:
                        st['cmode'] = (st['cmode'] + 1) % 3
                    elif ev.key == K_p:
                        st['plevel'] = (st['plevel'] + 1) % len(POWER_LEVELS)
                    elif ev.key == K_m:
                        st['show_stats'] = not st['show_stats']
                    elif ev.key == K_SPACE:
                        st['paused'] = not st['paused']
                    elif ev.key == K_r:
                        cd, cy, cp = 0.40, 25.0, 12.0
                        cpx, cpy = 0.0, self.display_center_y * 0.3
                    elif ev.key in (K_PLUS, K_EQUALS):
                        st['rate'] = min(st['rate'] + 500, self.n_points)
                    elif ev.key == K_MINUS:
                        st['rate'] = max(1, st['rate'] - 500)
                    elif ev.key == K_1 and 'Cat' in self.obj_names:
                        self.obj_idx = self.obj_names.index('Cat')
                        self._set_object('Cat')
                        st['obj'] = 'Cat'
                        st['ages'] = np.zeros(self.n_points, dtype=np.int32)
                        st['cursor'] = 0; st['frame'] = 0
                    elif ev.key == K_2:
                        self._set_object('Sphere')
                        st['obj'] = 'Sphere'
                        st['ages'] = np.zeros(self.n_points, dtype=np.int32)
                        st['cursor'] = 0; st['frame'] = 0
                    elif ev.key == K_3:
                        self.obj_idx = (self.obj_idx + 1) % len(self.obj_names)
                        name = self.obj_names[self.obj_idx]
                        self._set_object(name)
                        st['obj'] = name
                        st['ages'] = np.zeros(self.n_points, dtype=np.int32)
                        st['cursor'] = 0; st['frame'] = 0
                elif ev.type == MOUSEBUTTONDOWN:
                    if ev.button == 1:   ml = True; lx, ly = ev.pos
                    elif ev.button == 3: mr = True; lx, ly = ev.pos
                    elif ev.button == 4: cd = max(0.08, cd - 0.02)
                    elif ev.button == 5: cd = min(2.0, cd + 0.02)
                elif ev.type == MOUSEBUTTONUP:
                    if ev.button == 1:   ml = False
                    elif ev.button == 3: mr = False
                elif ev.type == MOUSEMOTION:
                    mx, my = ev.pos
                    dx, dy = mx - lx, my - ly
                    btns = pygame.mouse.get_pressed()
                    if ml or btns[0]:
                        cy += dx * 0.4
                        cp = max(-89, min(89, cp + dy * 0.4))
                    if mr or btns[1] or btns[2]:
                        cpx -= dx * 0.0003
                        cpy += dy * 0.0003
                    lx, ly = mx, my
                elif ev.type == MOUSEWHEEL:
                    cd = max(0.08, min(2.0, cd - ev.y * 0.03))

            keys = pygame.key.get_pressed()
            if keys[K_LEFT]:  cy -= 1.5
            if keys[K_RIGHT]: cy += 1.5
            if keys[K_UP]:    cp = max(-89, cp - 1.0)
            if keys[K_DOWN]:  cp = min(89, cp + 1.0)
            if keys[K_w]:     cd = max(0.08, cd - 0.005)
            if keys[K_e]:     cd = min(2.0, cd + 0.005)

            nt = self.n_points
            runtime_sec = (pygame.time.get_ticks() - start_time) / 1000.0

            # Clear
            if st['day'] == 2:   glClearColor(0.78, 0.82, 0.90, 1.0)
            elif st['day'] == 1: glClearColor(0.025, 0.025, 0.055, 1.0)
            else:                glClearColor(0.02, 0.02, 0.035, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            # Camera
            glLoadIdentity()
            ex = cd * math.cos(math.radians(cp)) * math.sin(math.radians(cy))
            ey = cd * math.sin(math.radians(cp))
            ez = cd * math.cos(math.radians(cp)) * math.cos(math.radians(cy))
            gluLookAt(ex + cpx, ey + cpy, ez, cpx, cpy, 0, 0, 1, 0)

            # Environment
            if st['day'] == 1:   self._draw_outdoor_night()
            elif st['day'] == 0: self._draw_night_env()
            self._draw_floor(st['day'])

            # Hardware
            self._draw_chassis(st['base'])
            self._draw_volume_wire()
            self._draw_ucnp_mist(st['us_vis'], time_val)
            self._draw_touch_demo(st['touch'], time_val)

            # Hologram
            if st['slow']:
                if not st['paused']:
                    st['frame'] += 1
                    cur = st['cursor']
                    for j in range(st['rate']):
                        st['ages'][(cur + j) % nt] = st['frame']
                    st['cursor'] = (cur + st['rate']) % nt
                tidx = st['cursor'] % nt
                target = self.pts[tidx]
                self._draw_ultrasound_field(target, st['us_vis'], time_val)
                self._draw_vcsel_beams_series(
                    target, st['beams'], self.colors[tidx], series_phase)
                self._draw_hologram_scanning(
                    self.pts, self.colors, st['ages'], st['frame'],
                    st['pov'], st['day'], st['cmode'])
            else:
                self._draw_ultrasound_field(
                    self.display_center, st['us_vis'], time_val)
                self._draw_vcsel_beams_volume(st['beams'])
                self._draw_hologram_solid(
                    self.pts, self.colors, nt, st['day'],
                    st['cmode'], st['plevel'])

            # HUD
            glDisable(GL_DEPTH_TEST)
            self._draw_hud(font, st, nt, runtime_sec)
            glEnable(GL_DEPTH_TEST)

            pygame.display.flip()
            clock.tick(FPS)

        pygame.quit()


# Allow running simulator standalone
if __name__ == '__main__':
    sim = HologramSimulator()
    sim.run()
