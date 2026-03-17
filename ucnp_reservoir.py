"""
UCNP Reservoir & Nebulizer Controller
======================================
Manages the upconversion nanoparticle aerosol supply.

HARDWARE INTERFACE:
  - Piezo mesh nebulizer: PWM drive signal (frequency, duty cycle)
  - Fluid level sensor: capacitive (analog read)
  - Temperature sensor: thermistor in reservoir (I2C)

UCNP PROPERTIES:
  Material: NaYF4 co-doped with Yb³⁺ (sensitizer) + Er³⁺/Tm³⁺/Ho³⁺ (activators)
  Diameter: ~30nm (monodisperse, oleic acid capped)
  Density: 4200 kg/m³
  Suspension medium: ethanol + PEG surfactant
  Concentration: 0.01% w/v (0.1 mg/mL)

  The nebulizer creates ~3μm aerosol droplets, each containing ~10³ UCNPs.
  Droplets evaporate in ~10ms, leaving bare UCNP clusters floating in air.
  Ultrasound array then traps these clusters at pressure nodes.

CONSUMPTION MODEL:
  UCNPs are TRAPPED and REUSED — not consumed per voxel.
  Loss mechanisms:
    - Brownian drift out of trap: ~0.05%/hr
    - Convection currents: ~0.03%/hr
    - Settling (gravity wins over weak traps at edges): ~0.02%/hr
    Total loss: ~0.1%/hr of active particles
  
  Reservoir holds 100,000× the active particle count.
  Nebulizer runs in short bursts to replenish losses.
  Continuous nebulization NOT needed — only top-up every few minutes.
"""

import math
import yaml
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ReservoirState:
    """Current state of the UCNP reservoir."""
    volume_ml: float              # Current fluid volume
    initial_volume_ml: float
    particle_count: float         # Total UCNPs in reservoir
    initial_particle_count: float
    temperature_c: float = 22.0
    nebulizer_on: bool = False
    nebulizer_duty_pct: float = 0.0
    total_dispensed_particles: float = 0.0
    total_dispensed_volume_ul: float = 0.0


class UCNPReservoir:
    """
    Controls UCNP aerosol reservoir and piezo nebulizer.

    Usage:
        res = UCNPReservoir('config.yaml')
        res.initialize()

        # Check if display volume needs replenishment
        if res.needs_replenish(active_particle_count):
            res.nebulize_burst(duration_ms=100)

        # Monitor consumption
        stats = res.get_stats(runtime_sec)
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        rc = cfg['ucnp_reservoir']
        self.volume_ml = rc['volume_ml']
        self.concentration = rc['concentration_wv_pct'] / 100.0  # fraction
        self.particle_diameter_nm = rc['particle_diameter_nm']
        self.particle_density = rc['particle_density_kg_m3']
        self.loss_rate_per_hour = rc['loss_rate_per_hour']

        self.composition = rc['composition']
        neb = rc['nebulizer']
        self.droplet_diameter_um = neb['droplet_diameter_um']
        self.flow_rate_ul_per_min = neb['flow_rate_ul_per_min']

        # Compute particle properties
        r_m = self.particle_diameter_nm * 0.5e-9
        self.particle_volume_m3 = (4 / 3) * math.pi * r_m ** 3
        self.particle_mass_kg = self.particle_volume_m3 * self.particle_density

        # Total particles in reservoir
        # concentration = mass_particles / volume_fluid
        # mass_particles = concentration × volume × density_fluid
        mass_ucnp_kg = self.concentration * self.volume_ml * 1e-3  # approx
        self.total_particles = mass_ucnp_kg / self.particle_mass_kg

        # Particles per nebulizer droplet
        droplet_r = self.droplet_diameter_um * 0.5e-6
        droplet_vol = (4 / 3) * math.pi * droplet_r ** 3
        # Volume fraction of UCNPs in suspension
        vol_fraction = self.concentration * 1000 / self.particle_density
        self.particles_per_droplet = (droplet_vol * vol_fraction /
                                       self.particle_volume_m3)

        # Droplets per second at full flow
        droplet_vol_ul = droplet_vol * 1e9  # m³ to μL
        self.droplets_per_sec = (self.flow_rate_ul_per_min / 60.0 /
                                  max(droplet_vol_ul, 1e-15))

        self.state = ReservoirState(
            volume_ml=self.volume_ml,
            initial_volume_ml=self.volume_ml,
            particle_count=self.total_particles,
            initial_particle_count=self.total_particles,
        )

        self._last_nebulize_time = 0.0

    def initialize(self):
        """Power-on: check fluid level, prime nebulizer."""
        print(f"[UCNP] Reservoir: {self.volume_ml}mL at "
              f"{self.concentration*100:.3f}% w/v")
        print(f"[UCNP] Particle count: {self.total_particles:.2e} "
              f"({self.particle_diameter_nm}nm NaYF4)")
        print(f"[UCNP] Composition: "
              f"Er {self.composition['green_er_pct']}% (green+red), "
              f"Tm {self.composition['blue_tm_pct']}% (blue), "
              f"Ho {self.composition['yellow_ho_pct']}% (yellow)")
        print(f"[UCNP] Nebulizer: {self.droplet_diameter_um}μm droplets, "
              f"~{self.particles_per_droplet:.0f} UCNPs/droplet")
        print(f"[UCNP] Loss rate: {self.loss_rate_per_hour*100:.1f}%/hr "
              f"(drift + settling)")
        runtime_h = 1.0 / self.loss_rate_per_hour
        print(f"[UCNP] Estimated refill interval: ~{runtime_h:,.0f} hours")
        print(f"[UCNP] Reservoir ready ✓")

    def needs_replenish(self, active_count: float,
                        target_count: float = 1e7) -> bool:
        """
        Check if the display volume needs more UCNPs.

        Args:
            active_count: current number of UCNPs in display volume
            target_count: desired number (default 10⁷ for 1000 voxels)

        Returns:
            True if active_count < 80% of target
        """
        return active_count < target_count * 0.80

    def nebulize_burst(self, duration_ms: float = 100) -> dict:
        """
        Run nebulizer for a short burst to release UCNPs into display volume.

        In real hardware: drive piezo mesh at 100kHz for duration_ms.
        Droplets are ejected upward, evaporate, UCNPs get caught by
        ultrasound traps.

        Args:
            duration_ms: burst duration in milliseconds

        Returns:
            dict with particles released, volume consumed
        """
        duration_s = duration_ms / 1000.0
        droplets = self.droplets_per_sec * duration_s
        particles_released = droplets * self.particles_per_droplet
        volume_consumed_ul = (self.flow_rate_ul_per_min / 60.0 *
                               duration_s * 1000)  # μL

        # Update reservoir state
        self.state.particle_count -= particles_released
        self.state.volume_ml -= volume_consumed_ul / 1000.0
        self.state.total_dispensed_particles += particles_released
        self.state.total_dispensed_volume_ul += volume_consumed_ul
        self.state.nebulizer_on = True
        self._last_nebulize_time = time.perf_counter()

        return {
            'particles_released': particles_released,
            'volume_consumed_ul': volume_consumed_ul,
            'droplets': droplets,
            'reservoir_remaining_pct': (self.state.volume_ml /
                                         self.state.initial_volume_ml * 100),
        }

    def update(self, dt_sec: float, active_count: float) -> dict:
        """
        Update reservoir state for elapsed time.
        Call once per frame.

        Args:
            dt_sec: time since last update
            active_count: UCNPs currently in display volume

        Returns:
            dict with current stats
        """
        # Particle loss from display volume
        loss = active_count * self.loss_rate_per_hour * dt_sec / 3600.0

        # Nebulizer auto-off after burst
        if (self.state.nebulizer_on and
                time.perf_counter() - self._last_nebulize_time > 0.1):
            self.state.nebulizer_on = False

        return {
            'particles_lost': loss,
            'active_count': active_count - loss,
            'reservoir_ml': self.state.volume_ml,
            'reservoir_pct': (self.state.volume_ml /
                               self.state.initial_volume_ml * 100),
            'nebulizer_on': self.state.nebulizer_on,
        }

    def get_stats(self, runtime_sec: float) -> dict:
        """Full consumption statistics."""
        runtime_h = runtime_sec / 3600.0
        remaining_pct = (self.state.volume_ml /
                          self.state.initial_volume_ml * 100)
        est_total_runtime_h = 1.0 / max(self.loss_rate_per_hour, 1e-10)

        mass_dispensed_ug = (self.state.total_dispensed_particles *
                              self.particle_mass_kg * 1e9)
        cost_per_gram = 5.0  # USD at scale
        cost_so_far = mass_dispensed_ug * 1e-6 * cost_per_gram

        return {
            'runtime_hours': runtime_h,
            'reservoir_ml': round(self.state.volume_ml, 4),
            'reservoir_pct': round(remaining_pct, 4),
            'particles_dispensed': self.state.total_dispensed_particles,
            'volume_dispensed_ul': round(self.state.total_dispensed_volume_ul, 3),
            'mass_dispensed_ug': round(mass_dispensed_ug, 6),
            'cost_usd': round(cost_so_far, 8),
            'est_refill_hours': est_total_runtime_h,
            'composition': self.composition,
        }

    def get_fluid_level(self) -> float:
        """Read fluid level sensor. Returns mL remaining."""
        return self.state.volume_ml

    def shutdown(self):
        """Stop nebulizer, safe state."""
        self.state.nebulizer_on = False
        print(f"[UCNP] Shutdown. Dispensed: "
              f"{self.state.total_dispensed_particles:.2e} particles, "
              f"{self.state.total_dispensed_volume_ul:.1f}μL fluid")
