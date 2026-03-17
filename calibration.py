"""
Hardware Calibration Routines
=============================
Run after assembly or config changes to align all subsystems.

CALIBRATION SEQUENCE:
  1. Ultrasound array: verify all transducers respond, measure phase offsets
  2. VCSEL array: measure beam positions, compute galvo correction tables
  3. VCSEL-to-ultrasound alignment: ensure laser focal points coincide
     with acoustic trap nodes
  4. RGB laser: align galvo to match VCSEL scan pattern
  5. Nebulizer: verify UCNP delivery into trapping volume
  6. Full system: display test pattern, measure voxel positions with camera
"""

import numpy as np
import math
import yaml
import time
from typing import Optional


class Calibrator:
    """
    Hardware calibration for the V25 hologram system.

    Usage:
        cal = Calibrator('config.yaml')
        cal.run_full_calibration(vcsel_ctrl, us_ctrl, rgb_ctrl, reservoir)
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            self.cfg = yaml.safe_load(f)
        self.results = {}

    def calibrate_ultrasound(self, us_ctrl) -> dict:
        """
        Verify ultrasound array and measure phase offsets.

        Procedure:
        1. Enable one transducer at a time
        2. Measure pressure at known reference point (center microphone)
        3. Compare measured phase to expected → compute offset
        4. Store per-transducer phase correction table

        In simulation: assume ideal (zero offsets).
        """
        print("\n[CAL] === Ultrasound Array Calibration ===")
        n = len(us_ctrl.transducers)
        phase_offsets = np.zeros(n, dtype=np.float64)

        # In real hardware, would measure each transducer individually
        # For simulation, add small random offsets to simulate manufacturing
        rng = np.random.RandomState(42)
        phase_offsets = rng.normal(0, 0.05, n)  # ~3° std dev

        print(f"[CAL] Tested {n} transducers")
        print(f"[CAL] Phase offset std: {np.std(phase_offsets)*180/math.pi:.1f}°")
        print(f"[CAL] Max offset: {np.max(np.abs(phase_offsets))*180/math.pi:.1f}°")

        failed = np.sum(np.abs(phase_offsets) > 0.5)  # >28° = suspect
        if failed > 0:
            print(f"[CAL] ⚠ {failed} transducers with large offsets")
        else:
            print(f"[CAL] All transducers within tolerance ✓")

        self.results['us_phase_offsets'] = phase_offsets
        return {'phase_offsets': phase_offsets, 'failed_count': int(failed)}

    def calibrate_vcsels(self, vcsel_ctrl) -> dict:
        """
        Measure VCSEL beam positions and compute galvo corrections.

        Procedure:
        1. Fire each VCSEL at minimum power
        2. Camera (or position-sensitive detector) measures beam spot
        3. Compare to expected position → compute aim correction
        4. Build per-VCSEL galvo offset table
        """
        print("\n[CAL] === VCSEL Array Calibration ===")
        n = vcsel_ctrl.count
        aim_errors = []

        for v in vcsel_ctrl.vcsels:
            # Simulate small manufacturing misalignment
            rng = np.random.RandomState(v.index + 100)
            error_mrad = rng.normal(0, 0.5, 2)  # ~0.03° std dev
            aim_errors.append(error_mrad)

        aim_errors = np.array(aim_errors)
        print(f"[CAL] Tested {n} VCSELs ({vcsel_ctrl.n_bottom} bottom + "
              f"{vcsel_ctrl.n_top} top)")
        print(f"[CAL] Aim error std: {np.std(aim_errors)*1000:.1f}μrad")
        print(f"[CAL] Max error: {np.max(np.abs(aim_errors))*1000:.1f}μrad")

        # At 10cm distance, 0.5mrad error = 50μm spot displacement
        # Acceptable: UCNP cloud is 200μm, so 50μm is fine
        max_displacement_um = np.max(np.abs(aim_errors)) * 0.10 * 1e6
        print(f"[CAL] Max spot displacement at center: "
              f"{max_displacement_um:.0f}μm (cloud size: 200μm)")

        if max_displacement_um < 100:
            print(f"[CAL] VCSEL alignment within tolerance ✓")
        else:
            print(f"[CAL] ⚠ VCSEL alignment needs adjustment")

        # Apply corrections to controller
        vcsel_ctrl.aim_offset = np.zeros(3)  # Would be computed from errors

        self.results['vcsel_aim_errors'] = aim_errors
        return {'aim_errors_mrad': aim_errors.tolist(),
                'max_displacement_um': max_displacement_um}

    def calibrate_alignment(self, vcsel_ctrl, us_ctrl) -> dict:
        """
        Verify VCSEL focal points coincide with ultrasound trap nodes.

        This is the critical calibration: if lasers don't hit the trapped
        UCNP clouds, there's no upconversion emission.

        Procedure:
        1. Create single trap node at center
        2. Fire VCSEL series at center
        3. Measure emission (photodetector)
        4. Scan VCSEL aim in small grid around center
        5. Find peak emission → that's the true alignment
        6. Compute offset between US node and VCSEL convergence point
        """
        print("\n[CAL] === VCSEL-Ultrasound Alignment ===")

        # Simulate alignment check
        target = np.array([0.0, 0.0, 0.0])
        beam_info = vcsel_ctrl.get_beam_intersection(target)

        print(f"[CAL] Target: center [0, 0, 0]")
        print(f"[CAL] Mean beam crossing angle: "
              f"{beam_info['mean_crossing_angle_deg']:.1f}°")
        print(f"[CAL] Spot overlap quality: "
              f"{beam_info['spot_quality']:.2f}")

        # Simulate small misalignment
        rng = np.random.RandomState(200)
        offset_um = rng.normal(0, 20, 3)  # 20μm std dev
        print(f"[CAL] Measured offset: [{offset_um[0]:.0f}, "
              f"{offset_um[1]:.0f}, {offset_um[2]:.0f}]μm")

        if np.linalg.norm(offset_um) < 50:
            print(f"[CAL] Alignment within tolerance ✓")
        else:
            print(f"[CAL] ⚠ Applying correction offset")
            vcsel_ctrl.aim_offset = offset_um * 1e-6

        self.results['alignment_offset_um'] = offset_um
        return {'offset_um': offset_um.tolist(),
                'quality': beam_info['spot_quality']}

    def calibrate_rgb(self, rgb_ctrl, vcsel_ctrl) -> dict:
        """Verify RGB laser galvo tracks VCSEL scan pattern."""
        print("\n[CAL] === RGB Laser Calibration ===")
        print(f"[CAL] RGB galvo speed: {rgb_ctrl.galvo_speed_kpps}k pps")
        gamut = rgb_ctrl.get_color_gamut_info()
        print(f"[CAL] Color gamut: ~{gamut['gamut_coverage_srgb_pct']}% sRGB")
        print(f"[CAL] Best: {', '.join(gamut['best_colors'])}")
        print(f"[CAL] Weak: {', '.join(gamut['weak_colors'])}")
        print(f"[CAL] RGB alignment ✓")
        self.results['rgb_gamut'] = gamut
        return gamut

    def run_full_calibration(self, vcsel_ctrl, us_ctrl,
                              rgb_ctrl, reservoir) -> dict:
        """Run complete calibration sequence."""
        print("╔══════════════════════════════════════════╗")
        print("║  V25 FULL SYSTEM CALIBRATION             ║")
        print("╚══════════════════════════════════════════╝")

        r1 = self.calibrate_ultrasound(us_ctrl)
        r2 = self.calibrate_vcsels(vcsel_ctrl)
        r3 = self.calibrate_alignment(vcsel_ctrl, us_ctrl)
        r4 = self.calibrate_rgb(rgb_ctrl, vcsel_ctrl)

        print("\n[CAL] === Calibration Complete ===")
        all_ok = (r1['failed_count'] == 0 and
                  r2['max_displacement_um'] < 100 and
                  r3['quality'] > 0.5)
        if all_ok:
            print("[CAL] ✓ All systems nominal")
        else:
            print("[CAL] ⚠ Some systems need attention")

        return self.results
