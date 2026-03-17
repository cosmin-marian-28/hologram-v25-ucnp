"""
V25 UCNP Upconversion Hologram — Modular Hardware Controller Package
=====================================================================
Clamshell design: dual ultrasonic bowls (top + bottom) with VCSEL
series excitation of upconversion nanoparticles.

Modules:
  vcsel_controller      — 8× 980nm IR pulsed lasers (4 bottom + 4 top)
  ultrasound_controller — 256 transducer dual-bowl phased array
  ucnp_reservoir        — Nanoparticle aerosol supply + nebulizer
  rgb_laser_controller  — RGB color modulation
  haptics_controller    — Mid-air touch feedback
  voxel_engine          — STL/OBJ → point cloud conversion
  calibration           — Hardware alignment routines
  main                  — Orchestrator (ties everything together)
  simulator             — OpenGL visualization
"""
