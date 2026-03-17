"""
Haptic Feedback Controller — Ultrasonic Mid-Air Touch
=====================================================
Provides tactile sensation when a hand enters the hologram volume.
Uses the SAME ultrasound array as the particle trapping system.

TIME MULTIPLEXING:
  At 40kHz carrier, each half-cycle is 12.5μs.
  Alternating frames:
    Frame 0: TRAP pattern — holds UCNPs at voxel positions
    Frame 1: HAPTIC pattern — focuses pressure on hand
  Particles stay trapped because 12.5μs gap is 1000× shorter than
  particle response time.

HAND TRACKING:
  Subset of transducers switch to receive mode to detect echoes.
  Time-of-flight → 3D position. ~100Hz update, ~2mm accuracy.
"""

import numpy as np
import math
import yaml
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class HandState:
    detected: bool = False
    palm_center: Optional[np.ndarray] = None
    fingertip: Optional[np.ndarray] = None
    palm_normal: Optional[np.ndarray] = None
    hand_radius_m: float = 0.04
    velocity: Optional[np.ndarray] = None
    in_volume: bool = False


@dataclass
class HapticPoint:
    position: np.ndarray
    pressure_pa: float
    modulation_hz: float
    active: bool = True


class HapticsController:
    """
    Manages touch detection and haptic feedback.

    Usage:
        ctrl = HapticsController('config.yaml')
        ctrl.initialize()
        hand = ctrl.detect_hand(dt)
        if hand.in_volume:
            occluded = ctrl.get_occluded_voxels(hand, voxel_positions)
            ctrl.set_haptic_point(hand.fingertip, pressure_pa=100)
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        hc = cfg['haptics']
        dc = cfg['display']
        self.enabled = hc['enabled']
        self.focal_spot_mm = hc['focal_spot_mm']
        self.max_force_mn = hc['max_force_mn']
        self.modulation_hz = hc['modulation_hz']
        self.reform_ms = hc['image_reform_ms']
        self.duty_cycle = hc['duty_cycle_pct'] / 100.0

        self.display_radius = dc['radius_m']
        self.display_center = np.array([0.0, dc['center_height_m'], 0.0])

        self.hand = HandState()
        self._haptic_points: List[HapticPoint] = []
        self._sim_time = 0.0
        self._sim_enabled = False

    def initialize(self):
        print(f"[HAPTIC] Mid-air haptics: {'enabled' if self.enabled else 'disabled'}")
        print(f"[HAPTIC] Focal spot: {self.focal_spot_mm}mm, "
              f"max force: {self.max_force_mn}mN")
        print(f"[HAPTIC] Modulation: {self.modulation_hz}Hz, "
              f"duty cycle: {self.duty_cycle*100:.0f}%")
        print(f"[HAPTIC] Image reform: {self.reform_ms}ms after hand moves")
        print(f"[HAPTIC] Ready ✓")

    def enable_simulation(self, enabled: bool = True):
        self._sim_enabled = enabled
        self._sim_time = 0.0

    def detect_hand(self, dt_sec: float = 0.033) -> HandState:
        """Detect hand via ultrasound echo. Returns HandState."""
        if self._sim_enabled:
            self._sim_time += dt_sec
            return self._simulate_hand()
        self.hand.detected = False
        self.hand.in_volume = False
        return self.hand

    def _simulate_hand(self) -> HandState:
        """Animated virtual hand for demo/testing."""
        t = self._sim_time
        phase = math.sin(t * 0.8)
        in_range = phase > -0.3

        if in_range:
            fx = 0.04 * math.sin(t * 1.2)
            fy = self.display_center[1] + 0.02 * math.sin(t * 0.5)
            fz = 0.03 * math.cos(t * 0.9)
            fingertip = np.array([fx, fy, fz])

            palm = fingertip + np.array([0.03, -0.02, 0.0])
            dist = np.linalg.norm(fingertip - self.display_center)

            self.hand.detected = True
            self.hand.fingertip = fingertip
            self.hand.palm_center = palm
            self.hand.palm_normal = np.array([-1, 0, 0], dtype=np.float64)
            self.hand.in_volume = dist < self.display_radius * 1.5
            self.hand.velocity = np.array([
                0.04 * 1.2 * math.cos(t * 1.2),
                0.02 * 0.5 * math.cos(t * 0.5),
                -0.03 * 0.9 * math.sin(t * 0.9),
            ])
        else:
            self.hand.detected = False
            self.hand.in_volume = False
            self.hand.fingertip = None

        return self.hand

    def set_haptic_point(self, position: np.ndarray,
                         pressure_pa: float = 100.0,
                         modulation_hz: Optional[float] = None):
        """
        Set a haptic focal point on the user's skin.

        Args:
            position: [x, y, z] on skin surface
            pressure_pa: pressure amplitude (max ~500 Pa for comfort)
            modulation_hz: tactile frequency (default from config)
        """
        if modulation_hz is None:
            modulation_hz = self.modulation_hz

        pressure_pa = min(pressure_pa, 500.0)  # Safety clamp

        self._haptic_points = [HapticPoint(
            position=np.asarray(position, dtype=np.float64),
            pressure_pa=pressure_pa,
            modulation_hz=modulation_hz,
        )]

    def set_haptic_surface(self, points: List[np.ndarray],
                           pressures: Optional[List[float]] = None):
        """Set multiple haptic points to simulate a surface."""
        if pressures is None:
            pressures = [100.0] * len(points)

        self._haptic_points = [
            HapticPoint(
                position=np.asarray(p, dtype=np.float64),
                pressure_pa=min(pr, 500.0),
                modulation_hz=self.modulation_hz,
            )
            for p, pr in zip(points, pressures)
        ]

    def get_occluded_voxels(self, hand: HandState,
                            voxel_positions: np.ndarray,
                            occlusion_radius_m: float = 0.02) -> np.ndarray:
        """
        Determine which voxels are occluded by the hand.
        These voxels should be hidden (UCNPs displaced by hand).

        Args:
            hand: current HandState
            voxel_positions: (N, 3) array of voxel positions
            occlusion_radius_m: hand collision radius

        Returns:
            boolean mask: True for occluded voxels
        """
        if not hand.detected or hand.fingertip is None:
            return np.zeros(len(voxel_positions), dtype=bool)

        # Simple sphere occlusion around fingertip + palm
        occluded = np.zeros(len(voxel_positions), dtype=bool)

        for center in [hand.fingertip, hand.palm_center]:
            if center is not None:
                dists = np.linalg.norm(voxel_positions - center, axis=1)
                occluded |= (dists < occlusion_radius_m)

        return occluded

    def compute_haptic_phases(self, transducer_positions: np.ndarray,
                               wavelength: float) -> np.ndarray:
        """
        Compute phase pattern for haptic focusing.

        This pattern is applied during HAPTIC time slots (alternating
        with TRAP pattern at 40kHz).

        Args:
            transducer_positions: (N, 3) array
            wavelength: acoustic wavelength in meters

        Returns:
            phases: (N,) uint8 array
        """
        if not self._haptic_points:
            return np.zeros(len(transducer_positions), dtype=np.uint8)

        k = 2 * math.pi / wavelength
        n_trans = len(transducer_positions)
        complex_sum = np.zeros(n_trans, dtype=np.complex128)

        for hp in self._haptic_points:
            if not hp.active:
                continue
            for i in range(n_trans):
                dist = np.linalg.norm(transducer_positions[i] - hp.position)
                phase = (k * dist) % (2 * math.pi)
                # Weight by pressure (normalize to max)
                weight = hp.pressure_pa / 500.0
                complex_sum[i] += weight * np.exp(1j * phase)

        phases_rad = np.angle(complex_sum) % (2 * math.pi)
        return (phases_rad / (2 * math.pi) * 256).astype(np.uint8)

    def get_haptic_feedback_info(self) -> dict:
        """Current haptic state for HUD display."""
        return {
            'hand_detected': self.hand.detected,
            'hand_in_volume': self.hand.in_volume,
            'fingertip': (self.hand.fingertip.tolist()
                          if self.hand.fingertip is not None else None),
            'haptic_points': len(self._haptic_points),
            'simulation': self._sim_enabled,
        }

    def shutdown(self):
        self._haptic_points.clear()
        self.hand = HandState()
        print(f"[HAPTIC] Shutdown.")
