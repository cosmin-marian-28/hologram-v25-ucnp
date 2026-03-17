"""
RGB Laser Controller — Color Modulation for UCNP Emission
==========================================================
Controls the RGB excitation laser + galvo for per-voxel color tuning.

HARDWARE INTERFACE:
  - 3× laser diode drivers (R 638nm, G 520nm, B 450nm) via DAC
  - 2-axis galvo mirror: analog X/Z via DAC
  - Blanking input: TTL signal to cut beam during repositioning

COLOR PHYSICS:
  UCNPs have fixed emission bands determined by their activator ions:
    - Er³⁺: green (540nm) + red (660nm), ratio depends on excitation power
    - Tm³⁺: blue (475nm) + weak UV
    - Ho³⁺: yellow-green (545nm)

  The RGB laser doesn't CREATE the color — it MODULATES which UCNP
  emission band dominates at each voxel by:
  1. Selective excitation: different wavelengths preferentially excite
     different activator ions (Er vs Tm vs Ho)
  2. Power-dependent branching: at high excitation, Er³⁺ shifts from
     green to red emission (three-photon vs two-photon process)
  3. Additive mixing: RGB laser light scattered off the UCNP cloud
     adds to the upconversion emission

  Result: not full sRGB, but a useful gamut covering greens, yellows,
  oranges, reds, and pastel blues. Deep blue and saturated red are weak.

GALVO COORDINATION:
  The RGB galvo must track the VCSEL scan pattern — both aim at the
  same voxel simultaneously. The FPGA synchronizes RGB galvo position
  with the VCSEL series firing.

  Timing per voxel:
    t=0μs     Galvo moves to voxel position
    t=5μs     Galvo settled, VCSEL series begins
    t=6μs     RGB laser fires during/after VCSEL series
    t=6.5μs   RGB laser off, galvo moves to next voxel
"""

import numpy as np
import math
import yaml
from dataclasses import dataclass
from typing import Tuple


@dataclass
class LaserChannel:
    """State of one RGB laser channel."""
    wavelength_nm: int
    max_power_mw: float
    current_power_mw: float = 0.0
    enabled: bool = True
    temperature_c: float = 25.0
    total_on_time_s: float = 0.0


class RGBLaserController:
    """
    Controls RGB laser module for per-voxel color modulation.

    Usage:
        ctrl = RGBLaserController('config.yaml')
        ctrl.initialize()

        # Set color for current voxel
        ctrl.set_color(r=0.8, g=0.3, b=0.1)  # warm orange

        # Aim at target (synchronized with VCSEL galvo)
        ctrl.aim_at(target_xyz)

        # Fire color pulse
        ctrl.fire_pulse(duration_us=0.5)
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        rc = cfg['rgb_laser']
        self.wavelengths = rc['wavelengths_nm']
        self.max_powers = rc['max_power_mw']
        self.galvo_speed_kpps = rc['galvo_speed_kpps']

        fc = cfg['frame']
        self.bowl_radius = fc['bowl_sphere_radius_m']

        # Position: bottom bowl center, pointing upward
        self.position = np.array([0.0, -self.bowl_radius + 0.01, 0.0],
                                  dtype=np.float64)

        self.channels = [
            LaserChannel(wavelength_nm=wl, max_power_mw=pw)
            for wl, pw in zip(self.wavelengths, self.max_powers)
        ]

        self._current_target = np.zeros(3)
        self._current_color = np.array([0.0, 0.0, 0.0])

    def initialize(self):
        """Power-on: enable laser drivers, zero galvo."""
        print(f"[RGB] Initializing 3-channel laser:")
        for ch in self.channels:
            print(f"  {ch.wavelength_nm}nm — max {ch.max_power_mw}mW")
        print(f"[RGB] Galvo speed: {self.galvo_speed_kpps}k points/sec")
        print(f"[RGB] Position: bottom bowl center")
        for ch in self.channels:
            ch.enabled = True
        print(f"[RGB] All channels enabled ✓")

    def set_color(self, r: float, g: float, b: float):
        """
        Set RGB color for the next voxel pulse.

        Args:
            r, g, b: 0.0 to 1.0 intensity for each channel

        Note: actual perceived color is a MIX of:
          - UCNP upconversion emission (green/red/blue from Er/Tm/Ho)
          - RGB laser scatter off the UCNP cloud
          The laser color adds to, not replaces, the upconversion color.
        """
        self._current_color = np.clip([r, g, b], 0.0, 1.0)
        for i, ch in enumerate(self.channels):
            ch.current_power_mw = self._current_color[i] * ch.max_power_mw

    def set_color_from_texture(self, texture_rgb: np.ndarray):
        """
        Set color from a texture sample (0-1 per channel).
        Applies gamma correction for perceptual linearity.
        """
        # Gamma 2.2 → linear for laser drive
        linear = np.clip(texture_rgb, 0, 1) ** 2.2
        self.set_color(linear[0], linear[1], linear[2])

    def aim_at(self, target: np.ndarray):
        """Steer galvo to aim RGB beam at target voxel."""
        self._current_target = np.asarray(target, dtype=np.float64)

    def fire_pulse(self, duration_us: float = 0.5) -> dict:
        """
        Fire RGB laser pulse at current target with current color.

        Args:
            duration_us: pulse duration in microseconds

        Returns:
            dict with color, power, and scatter estimate
        """
        duration_s = duration_us * 1e-6
        total_power_mw = sum(ch.current_power_mw for ch in self.channels
                              if ch.enabled)

        for ch in self.channels:
            if ch.enabled:
                ch.total_on_time_s += duration_s
                ch.temperature_c += ch.current_power_mw * 0.00001

        # Scatter estimate: how much RGB light scatters off UCNP cloud
        # Mie scattering cross-section for 200μm cloud of 30nm particles
        # ~10⁻⁸ of incident light scattered per voxel
        scatter_fraction = 1e-8
        scattered_nw = total_power_mw * 1e6 * scatter_fraction  # mW → nW

        return {
            'target': self._current_target.tolist(),
            'color_rgb': self._current_color.tolist(),
            'power_mw': [ch.current_power_mw for ch in self.channels],
            'total_power_mw': total_power_mw,
            'scattered_nw': scattered_nw,
            'duration_us': duration_us,
        }

    def compute_perceived_color(self, ucnp_emission: np.ndarray,
                                 rgb_scatter: np.ndarray) -> np.ndarray:
        """
        Compute the perceived voxel color as seen by the human eye.

        The final color is a weighted sum of:
        - UCNP upconversion emission (dominant, especially green)
        - RGB laser scatter (additive, for color tuning)

        Args:
            ucnp_emission: [r, g, b] from upconversion (0-1)
            rgb_scatter: [r, g, b] from laser scatter (0-1)

        Returns:
            perceived: [r, g, b] combined color (0-1)
        """
        # Upconversion is typically 5-10× brighter than scatter
        # Weight accordingly
        combined = ucnp_emission * 0.75 + rgb_scatter * 0.25
        return np.clip(combined, 0, 1)

    def get_color_gamut_info(self) -> dict:
        """Return achievable color gamut information."""
        return {
            'primary_emission': {
                'green': '540nm (Er³⁺, dominant)',
                'red': '660nm (Er³⁺, power-dependent)',
                'blue': '475nm (Tm³⁺, weak)',
            },
            'rgb_laser_additive': {
                'red': f'{self.wavelengths[0]}nm, {self.max_powers[0]}mW',
                'green': f'{self.wavelengths[1]}nm, {self.max_powers[1]}mW',
                'blue': f'{self.wavelengths[2]}nm, {self.max_powers[2]}mW',
            },
            'gamut_coverage_srgb_pct': 45,  # Honest estimate
            'best_colors': ['green', 'yellow', 'orange', 'warm white'],
            'weak_colors': ['deep blue', 'saturated red', 'magenta'],
        }

    def shutdown(self):
        """Disable all laser channels, zero galvo."""
        for ch in self.channels:
            ch.enabled = False
            ch.current_power_mw = 0.0
        print(f"[RGB] Shutdown. Total on-time: "
              f"R={self.channels[0].total_on_time_s:.1f}s "
              f"G={self.channels[1].total_on_time_s:.1f}s "
              f"B={self.channels[2].total_on_time_s:.1f}s")
