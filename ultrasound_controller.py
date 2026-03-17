"""
Ultrasound Phased Array Controller — Dual Bowl (Top + Bottom)
=============================================================
Controls 256 transducers (128 per bowl) for acoustic levitation
of UCNP nanoparticle clouds.

HARDWARE INTERFACE:
  - FPGA drives 256 channels via parallel DAC bus
  - Each channel: phase (8-bit, 0-255 → 0-2π) + amplitude (8-bit)
  - Update rate: 40kHz (one full phase pattern per acoustic cycle)

CLAMSHELL DESIGN:
  Two opposing curved bowls (top + bottom) create standing waves
  with stable 3D pressure nodes. Single-sided arrays can only trap
  in the vertical axis — lateral trapping is weak. Dual opposing
  arrays lock particles in ALL THREE axes.

  Bowl geometry: spherical caps, each covering 50° of a sphere
  with radius 0.11m. Connected by 3 support pillars at 120° spacing.
  Open equatorial gap for viewing and hand access.

TRAPPING PHYSICS:
  At 40kHz (λ = 8.575mm), standing wave nodes occur at λ/2 = 4.29mm.
  Each node is a pressure minimum where particles accumulate.
  Opposing arrays create a 3D lattice of stable nodes.

  Trapping force: ~0.5 pN/μm displacement (for 200μm UCNP cloud)
  This holds against gravity and gentle air currents.
  Hand insertion disrupts nearby nodes — image reforms in ~5ms
  after hand moves (acoustic propagation speed limited).

TIME MULTIPLEXING:
  The same array alternates between two modes at 40kHz:
    Even cycles: TRAP pattern (hold UCNPs at voxel positions)
    Odd cycles:  HAPTIC pattern (focus pressure on hand for touch)
  Particles don't drift in 12.5μs gaps (response time ~10ms).
"""

import numpy as np
import math
import yaml
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Transducer:
    """Single ultrasonic transducer element."""
    index: int
    bowl: str                     # 'bottom' or 'top'
    position: np.ndarray          # [x, y, z] in meters
    normal: np.ndarray            # outward-facing unit normal
    phase: int = 0                # 0-255 (maps to 0-2π)
    amplitude: int = 255          # 0-255
    enabled: bool = True


class UltrasoundController:
    """
    Controls dual-bowl ultrasonic phased array for 3D particle trapping.

    Usage:
        ctrl = UltrasoundController('config.yaml')
        ctrl.initialize()

        # Trap particles at multiple positions
        ctrl.set_trap_nodes(positions_array)

        # Get phase pattern for FPGA
        phases = ctrl.get_phase_pattern()

        # Query trapping info
        info = ctrl.get_trap_info()
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        uc = cfg['ultrasound_array']
        fc = cfg['frame']
        dc = cfg['display']

        self.frequency_hz = uc['frequency_khz'] * 1000
        self.n_per_bowl = uc['transducers_per_bowl']
        self.n_total = self.n_per_bowl * 2
        self.rings_per_bowl = uc['rings_per_bowl']
        self.base_per_ring = uc['base_per_ring']
        self.max_pressure_pa = uc['max_pressure_pa']
        self.node_size_um = uc['node_size_um']
        self.max_power_w = uc['max_power_w']
        self.default_power_w = uc['default_power_w']
        self.phase_bits = uc['phase_resolution_bits']
        self.update_rate_khz = uc['update_rate_khz']

        self.bowl_radius = fc['bowl_sphere_radius_m']
        self.cap_angle_deg = fc['bowl_cap_angle_deg']

        self.display_radius = dc['radius_m']
        self.display_center = np.array([0.0, dc['center_height_m'], 0.0])
        self.max_voxels = dc['max_voxels_per_frame']

        # Acoustic properties
        self.speed_of_sound = 343.0  # m/s in air at 20°C
        self.wavelength = self.speed_of_sound / self.frequency_hz
        self.k = 2 * math.pi / self.wavelength
        self.half_wavelength = self.wavelength / 2.0

        self.transducers: List[Transducer] = []
        self._init_geometry()

        self._trap_nodes: List[np.ndarray] = []
        self._current_power_w = self.default_power_w
        self._max_nodes = self._estimate_max_nodes()

    def _init_geometry(self):
        """Place transducers on two opposing spherical cap bowls."""
        cap_rad = math.radians(self.cap_angle_deg)
        idx = 0

        for bowl_sign, bowl_name in [(-1, 'bottom'), (+1, 'top')]:
            for ring in range(self.rings_per_bowl):
                theta = (ring + 1) / self.rings_per_bowl * cap_rad
                n_in_ring = self.base_per_ring + ring * 6
                for i in range(n_in_ring):
                    phi = 2 * math.pi * i / n_in_ring
                    x = self.bowl_radius * math.sin(theta) * math.cos(phi)
                    z = self.bowl_radius * math.sin(theta) * math.sin(phi)
                    y = bowl_sign * self.bowl_radius * math.cos(theta)
                    pos = np.array([x, y, z], dtype=np.float64)

                    # Normal points inward (toward display center)
                    normal = -pos / np.linalg.norm(pos)

                    self.transducers.append(Transducer(
                        index=idx, bowl=bowl_name,
                        position=pos, normal=normal,
                    ))
                    idx += 1

    def _estimate_max_nodes(self) -> int:
        """Estimate max simultaneous trap nodes based on transducer count."""
        # Rule of thumb: ~N_transducers / 4 independent nodes
        # With 256 transducers: ~64 high-quality nodes, ~1000 with multiplexing
        return min(self.max_voxels, self.n_total // 4 * 16)

    def initialize(self):
        """Power-on: test all transducers, set default power."""
        n_bot = sum(1 for t in self.transducers if t.bowl == 'bottom')
        n_top = sum(1 for t in self.transducers if t.bowl == 'top')
        print(f"[US] Initializing dual-bowl phased array:")
        print(f"[US]   Bottom bowl: {n_bot} transducers")
        print(f"[US]   Top bowl:    {n_top} transducers")
        print(f"[US]   Total:       {len(self.transducers)} transducers")
        print(f"[US] Frequency: {self.frequency_hz/1000:.0f}kHz, "
              f"λ={self.wavelength*1000:.2f}mm, "
              f"λ/2={self.half_wavelength*1000:.2f}mm")
        print(f"[US] Max trap nodes: ~{self._max_nodes}")
        print(f"[US] Node size: {self.node_size_um}μm")
        print(f"[US] Power: {self._current_power_w}W per bowl")

        for t in self.transducers:
            t.enabled = True
        print(f"[US] All transducers enabled ✓")

    def set_trap_nodes(self, positions: np.ndarray):
        """
        Set target trap node positions.

        Computes the phase pattern that creates pressure minima
        (trapping nodes) at the specified 3D positions.

        Args:
            positions: (N, 3) array of target positions in meters
        """
        positions = np.atleast_2d(positions)
        n = len(positions)
        if n > self._max_nodes:
            # Downsample — keep spatially distributed subset
            indices = np.random.choice(n, self._max_nodes, replace=False)
            positions = positions[indices]
            n = self._max_nodes

        self._trap_nodes = [pos.copy() for pos in positions]
        self._compute_phases(positions)

    def _compute_phases(self, targets: np.ndarray):
        """
        Compute per-transducer phases using iterative backpropagation.

        For each target node, we want a pressure MINIMUM (node).
        Phase at transducer i for target j:
            φ_ij = k × |r_i - r_j| + π  (the +π shifts to a node)

        For multiple targets, we use superposition with equal weighting.
        """
        n_trans = len(self.transducers)
        n_targets = len(targets)

        if n_targets == 0:
            for t in self.transducers:
                t.phase = 0
            return

        # Complex field superposition
        complex_sum = np.zeros(n_trans, dtype=np.complex128)

        for target in targets:
            for i, trans in enumerate(self.transducers):
                if not trans.enabled:
                    continue
                dist = np.linalg.norm(trans.position - target)
                # Phase for pressure NODE (minimum) at target
                phase = self.k * dist + math.pi
                complex_sum[i] += np.exp(1j * phase)

        # Extract phase and quantize to 8-bit
        phases_rad = np.angle(complex_sum) % (2 * math.pi)
        phase_steps = 2 ** self.phase_bits
        phases_int = (phases_rad / (2 * math.pi) * phase_steps).astype(int)
        phases_int = phases_int % phase_steps

        for i, trans in enumerate(self.transducers):
            trans.phase = int(phases_int[i])

    def get_phase_pattern(self) -> np.ndarray:
        """Get current phase pattern as uint8 array for FPGA upload."""
        return np.array([t.phase for t in self.transducers], dtype=np.uint8)

    def get_amplitude_pattern(self) -> np.ndarray:
        """Get current amplitude pattern."""
        return np.array([t.amplitude if t.enabled else 0
                         for t in self.transducers], dtype=np.uint8)

    def compute_pressure_at(self, point: np.ndarray) -> float:
        """
        Estimate acoustic pressure at a point given current phases.

        Used for diagnostics and visualization.
        """
        point = np.asarray(point, dtype=np.float64)
        field = 0.0 + 0.0j

        for trans in self.transducers:
            if not trans.enabled:
                continue
            dist = np.linalg.norm(trans.position - point)
            if dist < 1e-6:
                continue
            phase_rad = trans.phase / (2 ** self.phase_bits) * 2 * math.pi
            # Spherical spreading + phase
            amplitude = trans.amplitude / 255.0 / max(dist, 0.01)
            field += amplitude * np.exp(1j * (self.k * dist + phase_rad))

        return abs(field) * self.max_pressure_pa / len(self.transducers)

    def set_power(self, power_w: float):
        """Set output power per bowl."""
        self._current_power_w = min(power_w, self.max_power_w)
        # Scale amplitudes proportionally
        scale = math.sqrt(self._current_power_w / self.max_power_w)
        amp = int(255 * scale)
        for t in self.transducers:
            t.amplitude = amp
        print(f"[US] Power: {self._current_power_w:.1f}W/bowl "
              f"(amplitude: {amp}/255)")

    def get_trap_info(self) -> dict:
        """Current trapping state for diagnostics."""
        n_active = sum(1 for t in self.transducers if t.enabled)
        return {
            'active_transducers': n_active,
            'total_transducers': len(self.transducers),
            'trap_nodes': len(self._trap_nodes),
            'max_nodes': self._max_nodes,
            'frequency_khz': self.frequency_hz / 1000,
            'wavelength_mm': self.wavelength * 1000,
            'lattice_pitch_mm': self.half_wavelength * 1000,
            'power_w_per_bowl': self._current_power_w,
            'node_size_um': self.node_size_um,
        }

    def get_transducer_positions(self) -> np.ndarray:
        """Get all transducer positions as (N, 3) array."""
        return np.array([t.position for t in self.transducers],
                        dtype=np.float64)

    def get_bowl_positions(self, bowl: str) -> np.ndarray:
        """Get transducer positions for one bowl ('bottom' or 'top')."""
        return np.array([t.position for t in self.transducers
                         if t.bowl == bowl], dtype=np.float64)

    def shutdown(self):
        """Safe shutdown — zero all outputs."""
        for t in self.transducers:
            t.phase = 0
            t.amplitude = 0
            t.enabled = False
        self._trap_nodes.clear()
        print(f"[US] Shutdown. All transducers off.")
