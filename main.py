#!/usr/bin/env python3
"""
V25 Hologram — Main Orchestrator
=================================
Ties all hardware controllers together and runs the display loop.

STARTUP SEQUENCE:
  1. Load config
  2. Initialize all controllers
  3. Run calibration
  4. Load mesh → voxel point cloud
  5. Prime UCNP reservoir (initial nebulize burst)
  6. Enter main display loop:
     a. Update ultrasound trap nodes for current frame's voxels
     b. For each voxel: aim VCSELs → fire series → fire RGB color
     c. Check hand → update haptics
     d. Monitor reservoir → replenish if needed
     e. Update stats

USAGE:
  python main.py                          # Default: sphere demo
  python main.py --mesh model.obj         # Custom mesh
  python main.py --mesh cat.obj --texture cat.jpg
  python main.py --simulate               # Launch OpenGL simulator
"""

import argparse
import time
import sys
import os
import yaml
import numpy as np

# Add parent dir so we can run from inside hologram_v25/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vcsel_controller import VCSELController
from ultrasound_controller import UltrasoundController
from ucnp_reservoir import UCNPReservoir
from rgb_laser_controller import RGBLaserController
from haptics_controller import HapticsController
from voxel_engine import VoxelEngine
from calibration import Calibrator


class HologramSystem:
    """
    Main orchestrator for the V25 UCNP hologram.

    Coordinates all hardware subsystems to display a 3D holographic image
    using upconversion nanoparticles trapped by ultrasonic levitation
    and excited by VCSEL series firing.
    """

    def __init__(self, config_path: str = 'config.yaml'):
        self.config_path = config_path
        with open(config_path, 'r') as f:
            self.cfg = yaml.safe_load(f)

        self.vcsel = VCSELController(config_path)
        self.ultrasound = UltrasoundController(config_path)
        self.reservoir = UCNPReservoir(config_path)
        self.rgb = RGBLaserController(config_path)
        self.haptics = HapticsController(config_path)
        self.voxel_engine = VoxelEngine(config_path)
        self.calibrator = Calibrator(config_path)

        self.target_fps = self.cfg['display']['target_fps']
        self.max_voxels = self.cfg['display']['max_voxels_per_frame']

        # Runtime state
        self._running = False
        self._frame_count = 0
        self._start_time = 0.0
        self._active_ucnps = 0.0
        self._target_ucnps = 1e7  # 10⁷ for 1000 voxels

        # Current display data
        self._voxel_positions = None
        self._voxel_colors = None
        self._lattice_positions = None
        self._lattice_colors = None

    def initialize(self):
        """Power on all subsystems."""
        print("╔══════════════════════════════════════════════════╗")
        print("║  V25 UCNP UPCONVERSION HOLOGRAM — INITIALIZING  ║")
        print("╚══════════════════════════════════════════════════╝")
        print()

        self.vcsel.initialize()
        self.ultrasound.initialize()
        self.reservoir.initialize()
        self.rgb.initialize()
        self.haptics.initialize()

        print()
        res_info = self.voxel_engine.get_resolution_info()
        print(f"[SYSTEM] Display resolution: {res_info['equivalent_resolution']} "
              f"({res_info['lattice_pitch_mm']}mm pitch)")
        print(f"[SYSTEM] Max active voxels: {res_info['max_active_voxels']}")
        print(f"[SYSTEM] Target FPS: {self.target_fps}")
        print()

    def calibrate(self):
        """Run full hardware calibration."""
        self.calibrator.run_full_calibration(
            self.vcsel, self.ultrasound, self.rgb, self.reservoir
        )
        print()

    def load_mesh(self, mesh_path: str, texture_path: str = None):
        """Load a 3D model and prepare voxel data."""
        pts, colors, normals = self.voxel_engine.load_mesh(
            mesh_path, texture_path
        )
        self._voxel_positions = pts
        self._voxel_colors = colors

        # Snap to acoustic lattice
        self._lattice_positions, self._lattice_colors = \
            self.voxel_engine.snap_to_lattice(pts, colors)

        print(f"[SYSTEM] Loaded: {mesh_path}")
        print(f"[SYSTEM] Dense points: {len(pts):,}")
        print(f"[SYSTEM] Lattice voxels: {len(self._lattice_positions):,}")

    def load_sphere(self, n_points: int = 500000):
        """Generate a test sphere."""
        print("[SYSTEM] Generating test sphere...")
        r = self.voxel_engine.display_radius
        cy = self.voxel_engine.display_center_y

        phi = np.random.uniform(0, 2 * np.pi, n_points)
        ct = np.random.uniform(-1, 1, n_points)
        st = np.sqrt(1 - ct ** 2)
        pts = np.column_stack([
            r * st * np.cos(phi),
            r * st * np.sin(phi) + cy,
            r * ct,
        ]).astype(np.float32)

        # Rainbow colors
        hue = phi / (2 * np.pi)
        colors = np.zeros((n_points, 3), dtype=np.float32)
        h6 = hue * 6
        sec = h6.astype(int) % 6
        f = h6 - np.floor(h6)
        v = np.ones(n_points)
        sat = 0.7
        p = v * (1 - sat)
        q = v * (1 - sat * f)
        t = v * (1 - sat * (1 - f))
        for i in range(6):
            m = sec == i
            if i == 0:   colors[m] = np.column_stack([v, t, p])[m]
            elif i == 1: colors[m] = np.column_stack([q, v, p])[m]
            elif i == 2: colors[m] = np.column_stack([p, v, t])[m]
            elif i == 3: colors[m] = np.column_stack([p, q, v])[m]
            elif i == 4: colors[m] = np.column_stack([t, p, v])[m]
            elif i == 5: colors[m] = np.column_stack([v, p, q])[m]

        self._voxel_positions = pts
        self._voxel_colors = colors
        self._lattice_positions, self._lattice_colors = \
            self.voxel_engine.snap_to_lattice(pts, colors)
        print(f"[SYSTEM] Sphere: {len(self._lattice_positions)} lattice voxels")

    def prime_reservoir(self):
        """Initial UCNP release into display volume."""
        print("[SYSTEM] Priming UCNP reservoir...")
        result = self.reservoir.nebulize_burst(duration_ms=500)
        self._active_ucnps = result['particles_released']
        print(f"[SYSTEM] Released {self._active_ucnps:.2e} UCNPs into volume")
        print(f"[SYSTEM] Reservoir: {result['reservoir_remaining_pct']:.4f}% remaining")

    def run_frame(self) -> dict:
        """
        Execute one display frame.

        This is the core loop that coordinates all hardware:
        1. Set ultrasound trap pattern for current voxels
        2. For each voxel batch: aim + fire VCSEL series + RGB color
        3. Check hand for haptics
        4. Monitor reservoir

        Returns:
            dict with frame stats
        """
        if self._lattice_positions is None:
            return {'error': 'No mesh loaded'}

        frame_start = time.perf_counter()
        self._frame_count += 1
        dt = 1.0 / self.target_fps

        voxels = self._lattice_positions
        colors = self._lattice_colors
        n_voxels = len(voxels)

        # 1. Update ultrasound trap nodes
        self.ultrasound.set_trap_nodes(voxels)

        # 2. VCSEL series scan through voxels
        #    In real hardware, FPGA handles this at ~30k voxels/sec
        #    Here we simulate the per-voxel sequence
        total_emission_nw = 0.0
        voxels_scanned = min(n_voxels, self.max_voxels)

        for i in range(0, voxels_scanned, 50):
            # Batch aim + fire (FPGA does this in parallel groups)
            batch_end = min(i + 50, voxels_scanned)
            for j in range(i, batch_end):
                self.vcsel.aim_at(voxels[j])
                self.vcsel.wait_for_settle()
                result = self.vcsel.fire_series()
                total_emission_nw += result['upconversion_nw']

                # RGB color for this voxel
                self.rgb.set_color_from_texture(colors[j])
                self.rgb.aim_at(voxels[j])
                self.rgb.fire_pulse(duration_us=0.5)

        # 3. Haptics
        hand = self.haptics.detect_hand(dt)
        haptic_info = self.haptics.get_haptic_feedback_info()
        if hand.in_volume and hand.fingertip is not None:
            self.haptics.set_haptic_point(hand.fingertip, pressure_pa=150)

        # 4. Reservoir monitoring
        res_update = self.reservoir.update(dt, self._active_ucnps)
        self._active_ucnps = res_update['active_count']
        if self.reservoir.needs_replenish(self._active_ucnps):
            burst = self.reservoir.nebulize_burst(duration_ms=50)
            self._active_ucnps += burst['particles_released']

        # 5. Thermal check
        thermal = self.vcsel.get_thermal_status()

        frame_time = time.perf_counter() - frame_start

        return {
            'frame': self._frame_count,
            'voxels_scanned': voxels_scanned,
            'total_emission_nw': total_emission_nw,
            'avg_emission_per_voxel_nw': total_emission_nw / max(voxels_scanned, 1),
            'active_ucnps': self._active_ucnps,
            'reservoir_pct': res_update['reservoir_pct'],
            'hand_detected': haptic_info['hand_detected'],
            'frame_time_ms': frame_time * 1000,
            'fps_actual': 1.0 / max(frame_time, 1e-6),
        }

    def run_headless(self, n_frames: int = 100):
        """Run N frames without visualization (for testing/benchmarking)."""
        self._start_time = time.perf_counter()
        self._running = True

        print(f"\n[SYSTEM] Running {n_frames} frames headless...")
        for i in range(n_frames):
            if not self._running:
                break
            stats = self.run_frame()
            if i % 10 == 0:
                print(f"  Frame {stats['frame']:4d} | "
                      f"{stats['voxels_scanned']} voxels | "
                      f"{stats['total_emission_nw']:.1f}nW total | "
                      f"{stats['frame_time_ms']:.1f}ms | "
                      f"reservoir {stats['reservoir_pct']:.4f}%")

        runtime = time.perf_counter() - self._start_time
        print(f"\n[SYSTEM] Done. {n_frames} frames in {runtime:.2f}s "
              f"({n_frames/runtime:.1f} fps)")

    def get_system_stats(self) -> dict:
        """Full system status."""
        runtime = time.perf_counter() - self._start_time if self._start_time else 0
        return {
            'runtime_sec': runtime,
            'frames': self._frame_count,
            'vcsel_thermal': self.vcsel.get_thermal_status(),
            'ultrasound': self.ultrasound.get_trap_info(),
            'reservoir': self.reservoir.get_stats(runtime),
            'haptics': self.haptics.get_haptic_feedback_info(),
            'resolution': self.voxel_engine.get_resolution_info(),
        }

    def shutdown(self):
        """Safe shutdown of all subsystems."""
        self._running = False
        print("\n[SYSTEM] Shutting down...")
        self.vcsel.shutdown()
        self.ultrasound.shutdown()
        self.reservoir.shutdown()
        self.rgb.shutdown()
        self.haptics.shutdown()
        print("[SYSTEM] All systems off ✓")


def main():
    parser = argparse.ArgumentParser(
        description='V25 UCNP Upconversion Hologram System')
    parser.add_argument('--config', default='config.yaml',
                        help='Path to config.yaml')
    parser.add_argument('--mesh', default=None,
                        help='Path to STL/OBJ/PLY mesh file')
    parser.add_argument('--texture', default=None,
                        help='Path to texture image')
    parser.add_argument('--simulate', action='store_true',
                        help='Launch OpenGL simulator')
    parser.add_argument('--frames', type=int, default=100,
                        help='Number of headless frames to run')
    parser.add_argument('--touch', action='store_true',
                        help='Enable touch simulation demo')
    args = parser.parse_args()

    # Resolve config path
    config_path = args.config
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')

    system = HologramSystem(config_path)
    system.initialize()
    system.calibrate()

    # Load content
    if args.mesh:
        system.load_mesh(args.mesh, args.texture)
    else:
        system.load_sphere()

    system.prime_reservoir()

    if args.touch:
        system.haptics.enable_simulation(True)

    if args.simulate:
        # Launch OpenGL simulator
        from simulator import HologramSimulator
        sim = HologramSimulator(system)
        sim.run()
    else:
        # Headless mode
        system.run_headless(args.frames)
        stats = system.get_system_stats()
        print(f"\n[STATS] Resolution: {stats['resolution']['equivalent_resolution']}")
        print(f"[STATS] Reservoir: {stats['reservoir']['reservoir_pct']:.4f}% remaining")
        print(f"[STATS] UCNP cost so far: ${stats['reservoir']['cost_usd']:.8f}")

    system.shutdown()


if __name__ == '__main__':
    main()
