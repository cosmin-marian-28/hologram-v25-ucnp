"""
VCSEL Array Controller — 8× 980nm IR Pulsed Lasers (4 bottom + 4 top)
======================================================================
Controls the series firing sequence for upconversion excitation.

HARDWARE INTERFACE:
  - SPI bus to FPGA → 8 individual VCSEL driver channels
  - Each channel: enable, pulse energy (DAC), trigger timing
  - Per-VCSEL galvo mirror: 2-axis analog steering via DAC

CLAMSHELL LAYOUT:
  4 VCSELs on the bottom bowl rim, 4 on the top bowl rim.
  Top ring is offset 45° from bottom for full volume coverage.
  All beams converge inward toward the display center.

  Bottom VCSELs fire upward+inward. Top fire downward+inward.
  This gives crossing angles of ~70-110° at the focal point —
  much better than single-sided (~30-55° at top of volume).

SERIES FIRING PROTOCOL:
  VCSELs fire sequentially, not simultaneously. Each 100ns pulse adds
  energy to the UCNP cloud at the focal point. After 8 sequential hits
  (~1μs total), population inversion in Er³⁺/Tm³⁺ activators triggers
  visible upconversion emission.

  Why series, not parallel:
  - Parallel: all 8 beams arrive at once. Energy spreads across the
    UCNP cloud volume. Each particle gets 1/N of the photons.
    Upconversion scales as I² (two-photon process) → parallel gives
    (P/N)² × N = P²/N efficiency. WORSE with more lasers.
  - Series: each pulse hits the SAME particles sequentially. Energy
    stacks in the metastable Yb³⁺ state (lifetime ~1ms >> 1μs series).
    After 8 hits, each particle has absorbed 8× more photons.
    Upconversion: (8P)² = 64P². MUCH better.

TIMING DIAGRAM (one voxel):
  t=0ns     VCSEL B0 fires (bottom, 100ns pulse)
  t=125ns   VCSEL T0 fires (top, 100ns pulse)
  t=250ns   VCSEL B1 fires (bottom)
  t=375ns   VCSEL T1 fires (top)
  ...alternating bottom/top for uniform illumination...
  t=875ns   VCSEL T3 fires (top)
  t=1000ns  Series complete → upconversion emission peaks
  t=1005ns  Galvo mirrors start moving to next voxel
  t=6000ns  Galvo settled → next voxel series begins

  Alternating bottom/top ensures the UCNP cloud is hit from both
  hemispheres each series, preventing shadowing artifacts.
"""

import numpy as np
import math
import yaml
import time
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VCSELState:
    """State of a single VCSEL module."""
    index: int
    bowl: str                     # 'bottom' or 'top'
    position: np.ndarray          # [x, y, z] in meters
    direction: np.ndarray         # Unit vector, beam direction
    enabled: bool = True
    pulse_energy_uj: float = 12.0
    temperature_c: float = 25.0
    total_pulses: int = 0
    total_energy_j: float = 0.0


@dataclass
class GalvoState:
    """Per-VCSEL galvo mirror state."""
    angle_x_deg: float = 0.0
    angle_z_deg: float = 0.0
    settling: bool = False
    settle_start_time: float = 0.0


class VCSELController:
    """
    Controls 8 VCSELs (4 bottom rim + 4 top rim) for series firing.

    Usage:
        ctrl = VCSELController('config.yaml')
        ctrl.initialize()
        ctrl.aim_at(target_xyz)
        ctrl.wait_for_settle()
        result = ctrl.fire_series(pulse_energy_uj=12)
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        vc = cfg['vcsel_array']
        fc = cfg['frame']
        self.n_bottom = vc['count_bottom']
        self.n_top = vc['count_top']
        self.count = vc['total']
        self.wavelength_nm = vc['wavelength_nm']
        self.tilt_inward_deg = vc['tilt_inward_deg']
        self.pulse_duration_ns = vc['pulse_duration_ns']
        self.series_gap_ns = vc['series_gap_ns']
        self.series_total_us = vc['series_total_us']
        self.max_pulse_uj = vc['max_pulse_energy_uj']
        self.default_pulse_uj = vc['default_pulse_energy_uj']
        self.rep_rate_khz = vc['repetition_rate_khz']
        self.galvo_settling_us = vc['galvo_settling_us']

        self.bowl_radius = fc['bowl_sphere_radius_m']
        self.cap_angle_deg = fc['bowl_cap_angle_deg']

        self.vcsels: List[VCSELState] = []
        self.galvos: List[GalvoState] = []
        self._init_geometry()

        self._current_target = np.zeros(3)
        self._series_log: List[dict] = []
        self.aim_offset = np.zeros(3)
        self.energy_calibration = np.ones(self.count)

    def _init_geometry(self):
        """Compute VCSEL positions on top + bottom bowl rims."""
        cap_rad = math.radians(self.cap_angle_deg)
        rim_r = self.bowl_radius * math.sin(cap_rad)
        rim_y = self.bowl_radius * math.cos(cap_rad)

        # Bottom ring: 4 VCSELs on bottom bowl rim
        for i in range(self.n_bottom):
            angle = 2 * math.pi * i / self.n_bottom
            x = rim_r * math.cos(angle)
            z = rim_r * math.sin(angle)
            y = -rim_y  # Below center
            pos = np.array([x, y, z], dtype=np.float64)

            # Direction: inward + upward (toward display center)
            to_center = -pos / np.linalg.norm(pos)
            # Tilt further inward from bowl surface normal
            tilt = math.radians(self.tilt_inward_deg)
            up = np.array([0, 1, 0], dtype=np.float64)
            direction = to_center * math.cos(tilt) + up * math.sin(tilt)
            direction /= np.linalg.norm(direction)

            self.vcsels.append(VCSELState(
                index=i, bowl='bottom', position=pos, direction=direction,
                pulse_energy_uj=self.default_pulse_uj,
            ))
            self.galvos.append(GalvoState())

        # Top ring: 4 VCSELs, offset 45° from bottom
        for i in range(self.n_top):
            angle = 2 * math.pi * i / self.n_top + math.pi / self.n_top
            x = rim_r * math.cos(angle)
            z = rim_r * math.sin(angle)
            y = rim_y  # Above center
            pos = np.array([x, y, z], dtype=np.float64)

            to_center = -pos / np.linalg.norm(pos)
            down = np.array([0, -1, 0], dtype=np.float64)
            tilt = math.radians(self.tilt_inward_deg)
            direction = to_center * math.cos(tilt) + down * math.sin(tilt)
            direction /= np.linalg.norm(direction)

            self.vcsels.append(VCSELState(
                index=self.n_bottom + i, bowl='top', position=pos,
                direction=direction, pulse_energy_uj=self.default_pulse_uj,
            ))
            self.galvos.append(GalvoState())

    def initialize(self):
        """Power-on sequence."""
        print(f"[VCSEL] Initializing {self.count}× {self.wavelength_nm}nm "
              f"({self.n_bottom} bottom + {self.n_top} top)")
        cap = self.cap_angle_deg
        print(f"[VCSEL] Bowl rim at {cap}° cap angle, "
              f"tilt inward {self.tilt_inward_deg}°")
        print(f"[VCSEL] Series: alternating B/T, "
              f"{self.pulse_duration_ns}ns pulses, "
              f"{self.series_gap_ns}ns gaps")
        for v in self.vcsels:
            v.enabled = True
            v.temperature_c = 25.0
        print(f"[VCSEL] All {self.count} channels enabled ✓")

    def aim_at(self, target: np.ndarray):
        """Steer all galvo mirrors to converge at target point."""
        target = np.asarray(target, dtype=np.float64) + self.aim_offset
        self._current_target = target.copy()

        for i, (vcsel, galvo) in enumerate(zip(self.vcsels, self.galvos)):
            # Compute required beam direction from VCSEL position to target
            beam = target - vcsel.position
            beam_norm = beam / np.linalg.norm(beam)

            # Galvo angles relative to VCSEL's default direction
            default = vcsel.direction
            # Decompose into horizontal and vertical deflection
            cross_h = np.cross(default, np.array([0, 1, 0]))
            if np.linalg.norm(cross_h) > 1e-10:
                cross_h /= np.linalg.norm(cross_h)
            cross_v = np.cross(default, cross_h)

            galvo.angle_x_deg = math.degrees(np.dot(beam_norm - default, cross_h))
            galvo.angle_z_deg = math.degrees(np.dot(beam_norm - default, cross_v))
            galvo.settling = True
            galvo.settle_start_time = time.perf_counter()

    def wait_for_settle(self) -> float:
        """Wait for all galvo mirrors to settle."""
        for g in self.galvos:
            g.settling = False
        return self.galvo_settling_us

    def fire_series(self, pulse_energy_uj: Optional[float] = None) -> dict:
        """
        Execute one complete series firing sequence at current target.

        Fires alternating bottom/top VCSELs for uniform illumination.
        Returns upconversion emission estimate.
        """
        if pulse_energy_uj is None:
            pulse_energy_uj = self.default_pulse_uj
        pulse_energy_uj = min(pulse_energy_uj, self.max_pulse_uj)

        # Build alternating B/T firing order
        bottom = [v for v in self.vcsels if v.bowl == 'bottom' and v.enabled]
        top = [v for v in self.vcsels if v.bowl == 'top' and v.enabled]
        firing_order = []
        for i in range(max(len(bottom), len(top))):
            if i < len(bottom):
                firing_order.append(bottom[i])
            if i < len(top):
                firing_order.append(top[i])

        series_timing = []
        total_energy = 0.0
        t_ns = 0

        for vcsel in firing_order:
            actual_energy = pulse_energy_uj * self.energy_calibration[vcsel.index]
            series_timing.append({
                'vcsel': vcsel.index,
                'bowl': vcsel.bowl,
                'fire_time_ns': t_ns,
                'energy_uj': actual_energy,
                'position': vcsel.position.tolist(),
            })
            vcsel.total_pulses += 1
            vcsel.total_energy_j += actual_energy * 1e-6
            total_energy += actual_energy
            vcsel.temperature_c += actual_energy * 0.0001
            t_ns += self.pulse_duration_ns + self.series_gap_ns

        # Upconversion emission: I² scaling for two-photon process
        n_hits = len(series_timing)
        avg_energy = total_energy / max(n_hits, 1)
        upconversion_nw = (n_hits * avg_energy) ** 2 * 0.0008

        result = {
            'target': self._current_target.tolist(),
            'total_energy_uj': total_energy,
            'upconversion_nw': upconversion_nw,
            'series_timing': series_timing,
            'duration_ns': t_ns,
            'n_hits': n_hits,
            'firing_pattern': 'alternating_BT',
        }
        self._series_log.append(result)
        return result

    def set_pulse_energy(self, energy_uj: float):
        """Set pulse energy for all VCSELs."""
        energy_uj = max(0.5, min(energy_uj, self.max_pulse_uj))
        self.default_pulse_uj = energy_uj
        for v in self.vcsels:
            v.pulse_energy_uj = energy_uj
        print(f"[VCSEL] Pulse energy: {energy_uj}μJ × {self.count} VCSELs")

    def get_thermal_status(self) -> List[dict]:
        """Read junction temperatures. Shutdown if >85°C."""
        status = []
        for v in self.vcsels:
            v.temperature_c = max(25.0, v.temperature_c - 0.0005)
            ok = v.temperature_c < 85.0
            if not ok and v.enabled:
                v.enabled = False
                print(f"[VCSEL] ⚠ {v.bowl}[{v.index}] DISABLED — "
                      f"thermal ({v.temperature_c:.1f}°C)")
            status.append({
                'index': v.index, 'bowl': v.bowl,
                'temp_c': round(v.temperature_c, 1),
                'enabled': v.enabled, 'ok': ok,
            })
        return status

    def get_beam_intersection(self, target: np.ndarray) -> dict:
        """Compute beam geometry at target. Used by calibration."""
        target = np.asarray(target, dtype=np.float64)
        angles = []
        for v in self.vcsels:
            beam = target - v.position
            beam /= np.linalg.norm(beam)
            cos_a = abs(np.dot(beam, np.array([0, 1, 0])))
            angles.append(math.degrees(math.acos(min(cos_a, 1.0))))
        return {
            'target': target.tolist(),
            'beam_angles_from_vertical_deg': angles,
            'mean_crossing_angle_deg': np.mean(angles),
            'spot_quality': min(1.0, np.min(angles) / 25.0),
        }

    def shutdown(self):
        """Safe shutdown."""
        for v in self.vcsels:
            v.enabled = False
        total = sum(v.total_pulses for v in self.vcsels)
        print(f"[VCSEL] Shutdown. Total pulses fired: {total:,}")
