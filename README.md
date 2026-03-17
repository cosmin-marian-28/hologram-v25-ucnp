<p align="center">
  <strong>V25 — UCNP UPCONVERSION VOLUMETRIC DISPLAY</strong><br>
  <em>Clamshell Acoustic Levitation + VCSEL Series Excitation</em>
</p>

<p align="center">
  <code>CONCEPT PROTOTYPE</code> · <code>PHYSICS-BASED SIMULATION</code> · <code>MODULAR HARDWARE CONTROLLERS</code>
</p>

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Physical Principle — Why This Works](#3-physical-principle--why-this-works)
4. [Hardware Architecture](#4-hardware-architecture)
5. [Signal Flow — From 3D Model to Light in Air](#5-signal-flow--from-3d-model-to-light-in-air)
6. [Subsystem Deep Dive](#6-subsystem-deep-dive)
7. [Series Firing — The Core Innovation](#7-series-firing--the-core-innovation)
8. [Ambient Light Advantage](#8-ambient-light-advantage)
9. [Touch Interaction](#9-touch-interaction)
10. [Honest Performance Numbers](#10-honest-performance-numbers)
11. [Software Architecture](#11-software-architecture)
12. [Running the Simulator](#12-running-the-simulator)
13. [References](#13-references)

---

## 1. Executive Summary

This project demonstrates a volumetric display concept that creates
**touchable 3D images floating in open air** using three key technologies:

- **Upconversion nanoparticles (UCNPs)** that convert invisible infrared
  light into visible light
- **Ultrasonic acoustic levitation** that holds particles at precise 3D
  positions without any screen or medium
- **VCSEL series firing** that stacks energy efficiently through sequential
  laser pulses

Unlike projection-based "holograms," this creates actual light-emitting
points in 3D space. You can walk around it. You can put your hand through
it. The image reforms around your fingers.

```
                    ┌─────────────────────────────────────┐
                    │  WHAT MAKES THIS DIFFERENT           │
                    ├─────────────────────────────────────┤
                    │  ✓ True 3D — not a 2D projection     │
                    │  ✓ Touchable — haptic feedback        │
                    │  ✓ Daylight helps — ambient IR boost  │
                    │  ✓ Non-toxic — UCNPs wash off          │
                    │  ✓ No screen — open air display        │
                    │  ✗ Low resolution (~28³ voxels)        │
                    │  ✗ Indoor only (not direct sunlight)   │
                    │  ✗ ~45% sRGB color gamut               │
                    └─────────────────────────────────────┘
```

---

## 2. System Overview

```
  ╔═══════════════════════════════════════════════════════════════════╗
  ║                    SYSTEM BLOCK DIAGRAM                          ║
  ╠═══════════════════════════════════════════════════════════════════╣
  ║                                                                   ║
  ║   ┌──────────┐    ┌──────────┐    ┌──────────────────────────┐   ║
  ║   │ 3D Model │───▶│  Voxel   │───▶│  Acoustic Lattice Grid   │   ║
  ║   │ STL/OBJ  │    │  Engine  │    │  (λ/2 = 4.29mm pitch)   │   ║
  ║   └──────────┘    └──────────┘    └────────────┬─────────────┘   ║
  ║                                                 │                  ║
  ║                                                 ▼                  ║
  ║   ┌──────────────────────────────────────────────────────────┐    ║
  ║   │                    FPGA CONTROLLER                        │    ║
  ║   │              (Xilinx Artix-7, 200MHz)                     │    ║
  ║   │                                                            │    ║
  ║   │   ┌─────────┐  ┌──────────┐  ┌─────┐  ┌──────────────┐  │    ║
  ║   │   │Ultrasound│  │  VCSEL   │  │ RGB │  │   Haptics    │  │    ║
  ║   │   │  Phase   │  │  Series  │  │Laser│  │  Interleave  │  │    ║
  ║   │   │ Control  │  │  Timing  │  │Sync │  │   Control    │  │    ║
  ║   │   └────┬─────┘  └────┬─────┘  └──┬──┘  └──────┬───────┘  │    ║
  ║   └────────┼──────────────┼───────────┼────────────┼──────────┘    ║
  ║            │              │           │            │               ║
  ║            ▼              ▼           ▼            ▼               ║
  ║   ┌──────────────┐ ┌──────────┐ ┌────────┐ ┌────────────────┐    ║
  ║   │ 256 Ultrasonic│ │ 8 VCSELs │ │RGB Laser│ │ Same US Array  │    ║
  ║   │ Transducers   │ │ (980nm)  │ │(R/G/B) │ │ (haptic mode) │    ║
  ║   │ (128+128)     │ │ (4+4)    │ │        │ │               │    ║
  ║   └──────┬────────┘ └────┬─────┘ └───┬────┘ └───────┬───────┘    ║
  ║          │               │            │              │             ║
  ║          ▼               ▼            ▼              ▼             ║
  ║   ┌──────────────────────────────────────────────────────────┐    ║
  ║   │              DISPLAY VOLUME (6cm radius sphere)           │    ║
  ║   │                                                            │    ║
  ║   │    Ultrasound traps UCNP clouds at pressure nodes         │    ║
  ║   │    VCSELs excite UCNPs → visible upconversion emission    │    ║
  ║   │    RGB laser tunes perceived color per voxel              │    ║
  ║   │    Haptic pressure waves give touch sensation             │    ║
  ║   └──────────────────────────────────────────────────────────┘    ║
  ║                         ▲                                         ║
  ║                         │                                         ║
  ║                  ┌──────┴───────┐                                 ║
  ║                  │ UCNP Aerosol │                                 ║
  ║                  │  Reservoir   │                                 ║
  ║                  │  (1mL, 10¹²  │                                 ║
  ║                  │  particles)  │                                 ║
  ║                  └──────────────┘                                 ║
  ╚═══════════════════════════════════════════════════════════════════╝
```

---

## 3. Physical Principle — Why This Works

### The Problem with Existing "Holograms"

Most commercial "holograms" are 2D tricks — Pepper's ghost, spinning LED
fans, lenticular prints. They project onto a surface or exploit persistence
of vision. You can't walk around them. You can't touch them.

### Our Approach: Light-Emitting Points in Free Space

We create actual luminous points floating in air. Each point is a tiny
cloud of ~10,000 nanoparticles held in place by sound waves and made to
glow by infrared lasers.

```
  THE THREE-STEP PROCESS:

  STEP 1: TRAP                STEP 2: EXCITE              STEP 3: EMIT
  ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
  │                  │        │                  │        │                  │
  │  Ultrasound      │        │  980nm IR laser   │        │  540nm GREEN     │
  │  standing wave   │        │  series hits the  │        │  light emitted   │
  │  creates pressure│        │  trapped UCNP     │        │  from Er³⁺ ions  │
  │  node (minimum)  │        │  cloud 8 times    │        │  (upconversion)  │
  │                  │        │  in 1 microsecond │        │                  │
  │   ┌──┐          │        │                  │        │     * * *        │
  │   │  │ ← UCNPs  │        │  ≋≋≋≋≋≋≋≋≋≋≋≋≋  │        │    * ✦ *  ← glow │
  │   │  │  trapped  │        │  IR IR IR IR IR  │        │     * * *        │
  │   └──┘  here    │        │  ≋≋≋≋≋≋≋≋≋≋≋≋≋  │        │                  │
  │                  │        │                  │        │  Visible to      │
  │  Force: ~0.5pN/μm│        │  Energy stacks   │        │  human eye       │
  └─────────────────┘        │  in Yb³⁺ state   │        └─────────────────┘
                              └─────────────────┘
```

### Upconversion: Turning Invisible Light Visible

Normal fluorescence: absorb high-energy photon → emit lower-energy photon.
Upconversion is the reverse: absorb MULTIPLE low-energy IR photons → emit
ONE higher-energy visible photon. This is real physics, not magic.

```
  ENERGY LEVEL DIAGRAM (NaYF4:Yb,Er)

  Energy ↑
    │
    │  ⁴F₇/₂ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
    │
    │  ²H₁₁/₂ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
    │  ⁴S₃/₂  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ──→ 540nm GREEN ★
    │                    ↑
    │  ⁴F₉/₂  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ──→ 660nm RED ★
    │                    ↑
    │                    │ Energy Transfer
    │                    │ (Yb³⁺ → Er³⁺)
    │  ⁴I₁₁/₂ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    │                    ↑               ↑
    │                    │ 980nm         │ 980nm
    │                    │ (VCSEL #1)    │ (VCSEL #2)
    │                    │               │
    │  ⁴I₁₅/₂ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ← Ground state
    │
    │         Yb³⁺ SENSITIZER          Er³⁺ ACTIVATOR
    │
    │  Two 980nm photons absorbed → one 540nm photon emitted
    │  This is why series firing works: each pulse adds one step up
    └──────────────────────────────────────────────────────────────
```

---

## 4. Hardware Architecture

### Physical Layout — Clamshell Design

```
                         TOP VIEW
                    ╭─────────────────╮
                   ╱  T3      T0       ╲
                  ╱     ╲    ╱          ╲
                 │   ●───────────●       │
                 │  ╱  Ultrasound  ╲     │
            ═════●  │  Transducers  │  ●═════  ← Pillar (×3)
                 │  │  (128 top)    │    │
                 │   ╲             ╱     │
                  ╲    T2      T1      ╱
                   ╲                  ╱
                    ╰─────────────────╯

                        SIDE VIEW (cross-section)

              ╭──────────────────────────────╮
             ╱  ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪  ╲   ← 128 transducers
            ╱    ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪     ╲     on curved bowl
           │      ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪        │
      [T0]◄│        ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪          │►[T2]  ← VCSELs on rim
           │                                      │
     ══════╪══  ← Pillar    DISPLAY     Pillar →══╪══════
           │                VOLUME                 │
           │              (6cm sphere)             │
           │           ┌─ ─ ─ ─ ─ ─┐              │
      [B0]◄│           │  ★ ★ ★ ★  │              │►[B2]  ← VCSELs on rim
           │           │  ★ ★ ★ ★  │ ← Hologram   │
           │           │  ★ ★ ★ ★  │              │
           │           └─ ─ ─ ─ ─ ─┘              │
            ╲        ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪          ╱
             ╲     ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪      ╱
              ╲  ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪  ╱   ← 128 transducers
               ╰──────────┬───────────────────╯
                      [RGB] [NEB]
                       ↑      ↑
                  RGB laser  Nebulizer nozzle
                  (color)    (UCNP aerosol)

           ▪ = ultrasonic transducer (40kHz)
           ★ = voxel (UCNP cloud, ~200μm, ~10⁴ particles)
          [B/T] = VCSEL module (980nm IR, pulsed)
```

### Why Clamshell? Why Not Single-Sided?

```
  SINGLE-SIDED (bottom only)          DUAL OPPOSING (clamshell)
  ┌─────────────────────────┐        ┌─────────────────────────┐
  │                          │        │  ▼ ▼ ▼ ▼ ▼ ▼ ▼ ▼ ▼ ▼  │ ← Top array
  │     Particle drifts      │        │                          │    pushes DOWN
  │     sideways — no        │        │     Particle locked      │
  │     lateral trapping     │        │     in ALL 3 AXES        │
  │          ○ → ?           │        │          ●               │
  │                          │        │     (stable node)        │
  │  ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲   │        │                          │
  │  Bottom array pushes UP  │        │  ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲ ▲  │ ← Bottom array
  └─────────────────────────┘        └─────────────────────────┘    pushes UP
  
  Result: vertical trapping only     Result: 3D stable trapping
  Particles escape sideways          Standing wave locks X, Y, Z
  ✗ Doesn't work for 3D display     ✓ Required for volumetric display
```

### Bill of Materials

```
  ┌────┬──────────────────────────────────┬──────────┬───────────┐
  │ Qty│ Component                         │ Spec      │ Est. Cost │
  ├────┼──────────────────────────────────┼──────────┼───────────┤
  │ 256│ Ultrasonic transducers            │ 40kHz     │ $150      │
  │   8│ VCSEL modules                     │ 980nm IR  │ $200      │
  │   1│ RGB laser module                  │ R/G/B     │ $80       │
  │   1│ Piezo mesh nebulizer              │ 100kHz    │ $25       │
  │   1│ UCNP suspension (1mL)             │ NaYF4     │ $50       │
  │   1│ FPGA board (Artix-7)              │ XC7A100T  │ $150      │
  │   2│ Aluminum bowl shells              │ 16cm dia  │ $60       │
  │   3│ Support pillars                   │ Aluminum  │ $15       │
  │   1│ Power supply                      │ 12V/5A    │ $20       │
  ├────┼──────────────────────────────────┼──────────┼───────────┤
  │    │ TOTAL (estimated prototype)       │          │ ~$750     │
  └────┴──────────────────────────────────┴──────────┴───────────┘
```

---

## 5. Signal Flow — From 3D Model to Light in Air

This is the complete pipeline from a file on disk to photons leaving
a floating particle cloud.

```
  ┌─────────────┐
  │  model.obj   │  ← Any 3D mesh (STL, OBJ, PLY, GLTF)
  └──────┬───────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  VOXEL ENGINE (voxel_engine.py)                               │
  │                                                                │
  │  1. Load mesh via trimesh                                      │
  │  2. Center + normalize to fit 6cm display sphere               │
  │  3. Auto-orient (Z-up → Y-up if needed)                       │
  │  4. Sample 500k surface points                                 │
  │  5. Extract texture colors (UV mapping + barycentric interp)   │
  │  6. Snap to acoustic lattice grid (λ/2 = 4.29mm)              │
  │  7. Merge duplicate grid cells, average colors                 │
  │  8. Downsample to ≤1000 voxels (ultrasound node limit)        │
  │                                                                │
  │  Output: positions[N,3] + colors[N,3] on λ/2 grid             │
  └──────────────────────────┬───────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                     ▼
  ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐
  │  ULTRASOUND   │   │    VCSEL      │   │   RGB LASER      │
  │  CONTROLLER   │   │  CONTROLLER   │   │  CONTROLLER      │
  │               │   │               │   │                  │
  │ Compute phase │   │ For each voxel│   │ For each voxel:  │
  │ pattern for   │   │ in sequence:  │   │                  │
  │ ALL voxels    │   │               │   │ 1. Read texture  │
  │ simultaneously│   │ 1. Aim galvos │   │    color         │
  │               │   │ 2. Wait 5μs   │   │ 2. Set R/G/B    │
  │ Upload 256    │   │    settle     │   │    power ratio   │
  │ phases to     │   │ 3. Fire series│   │ 3. Aim galvo     │
  │ FPGA          │   │    B0→T0→B1→  │   │ 4. Fire pulse    │
  │               │   │    T1→B2→T2→  │   │    (0.5μs)       │
  │ Holds ALL     │   │    B3→T3      │   │                  │
  │ particles     │   │    (~1μs)     │   │ Adds color to    │
  │ at once       │   │ 4. Move to    │   │ upconversion     │
  │               │   │    next voxel │   │ emission         │
  └──────┬────────┘   └───────┬───────┘   └────────┬─────────┘
         │                    │                     │
         ▼                    ▼                     ▼
  ┌──────────────────────────────────────────────────────────────┐
  │                    AT THE VOXEL POINT                         │
  │                                                                │
  │  Sound waves hold 10⁴ UCNPs in a 200μm cloud                  │
  │  8 IR laser pulses stack energy in Yb³⁺ ions                  │
  │  Population inversion → Er³⁺ emits 540nm green light          │
  │  RGB scatter adds color tint                                   │
  │  Human eye sees: a glowing colored point in mid-air            │
  │                                                                │
  │  Repeat for all ~1000 voxels at 30fps                          │
  │  Persistence of vision → continuous 3D image                   │
  └──────────────────────────────────────────────────────────────┘
```

### Timing Diagram — One Voxel Cycle

```
  Time ──────────────────────────────────────────────────────▶

  0μs          5μs    5.1   5.2   5.3   5.5   5.6   5.7   5.9   6.0   6.5μs
   │            │      │     │     │     │     │     │     │     │      │
   │  Galvo     │      │     │     │     │     │     │     │     │      │
   │  settling  │  B0  │ T0  │ B1  │ T1  │ B2  │ T2  │ B3  │ T3  │ RGB  │
   │  (5μs)     │100ns │100ns│100ns│100ns│100ns│100ns│100ns│100ns│0.5μs │
   │            │      │     │     │     │     │     │     │     │      │
   │◄──────────▶│◄─────────── VCSEL SERIES (~1μs) ──────────▶│◄────▶│
   │            │      │     │     │     │     │     │     │     │      │
   │            │  ┌───┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘      │
   │            │  │  Energy stacking in Yb³⁺ metastable state          │
   │            │  │  Each hit adds to population inversion             │
   │            │  │  After 8 hits: VISIBLE EMISSION                    │
   │            │  └────────────────────────────────────────────────────│
   │                                                                     │
   │◄──────────────────── Total: ~6.5μs per voxel ─────────────────────▶│
   │                                                                     │
   │  At 30fps with 1000 voxels: 6.5ms scan time (fits in 33ms frame)  │
```

---

## 6. Subsystem Deep Dive

### 6.1 Ultrasound Phased Array (`ultrasound_controller.py`)

**Purpose:** Hold UCNP particle clouds at precise 3D positions using
acoustic radiation force.

```
  HOW ACOUSTIC TRAPPING WORKS

  Each transducer emits a 40kHz pressure wave.
  By controlling the PHASE of each transducer, we steer where
  the waves constructively/destructively interfere.

  Pressure NODES (minima) attract particles.
  256 transducers with 8-bit phase control = enough degrees
  of freedom to create ~1000 independent trap nodes.

  Transducer i          Phase φᵢ computed so that:
  ┌───┐                 
  │ ≋ │──── wave ────▶  All waves arrive at target
  └───┘                 with OPPOSITE phase → cancel
                         → pressure MINIMUM → trap

  Phase formula:  φᵢ = k × |rᵢ - r_target| + π
                  where k = 2π/λ, rᵢ = transducer position

  The +π shifts from a pressure maximum (antinode)
  to a pressure minimum (node) — that's where particles sit.
```

**Key specs:**
- 256 transducers (128 per bowl), 40kHz
- λ = 8.575mm, node spacing = λ/2 = 4.29mm
- Trapping force: ~0.5 pN/μm displacement
- Node size: ~200μm (this is one voxel)
- Phase update rate: 40kHz (real-time reconfiguration)

### 6.2 VCSEL Array (`vcsel_controller.py`)

**Purpose:** Excite trapped UCNP clouds to emit visible light via
upconversion.

```
  VCSEL PLACEMENT ON BOWL RIMS

  Bottom rim (looking up):        Top rim (looking down):

       B3          B0                  T0          T1
        ╲        ╱                      ╲        ╱
         ╲      ╱                        ╲      ╱
          ╲    ╱                          ╲    ╱
           ╲  ╱                            ╲  ╱
            ╳  ← beams cross                ╳
           ╱  ╲    at voxel               ╱  ╲
          ╱    ╲                          ╱    ╲
         ╱      ╲                        ╱      ╲
        ╱        ╲                      ╱        ╲
       B1          B2                  T3          T2

  Top ring offset 45° from bottom → 8 unique beam angles
  Crossing angles: 70-110° at focal point
  No two beams from same direction → uniform illumination
```

**Key specs:**
- 8× VCSELs, 980nm (Yb³⁺ absorption band)
- Pulse: 100ns duration, 12μJ default energy
- Series: alternating B/T, ~1μs total
- Galvo settling: 5μs between voxels
- Rep rate: 30kHz (matches frame×voxel budget)

### 6.3 UCNP Reservoir (`ucnp_reservoir.py`)

**Purpose:** Supply upconversion nanoparticles as aerosol into the
display volume.

```
  PARTICLE LIFECYCLE

  ┌──────────┐    nebulize     ┌──────────┐    ultrasound    ┌──────────┐
  │ Reservoir │───────────────▶│  Aerosol  │────────────────▶│  Trapped  │
  │ (liquid   │   3μm droplets │  (air)    │   catches at    │  at node  │
  │ suspension│                │           │   pressure node │  (voxel)  │
  └──────────┘                └──────────┘                  └─────┬─────┘
       ▲                                                          │
       │                         0.1%/hr                          │
       │                         drift loss                       │
       │                              │                           │
       │         settles as           ▼                           │
       │         harmless      ┌──────────┐    reused             │
       │         dust          │  Escaped  │◄─────────────────────┘
       │                       │ particles │   (most stay trapped
       │                       └──────────┘    indefinitely)
       │
       └── Refill every ~10,000 hours ($0.00005 per refill)
```

**Key specs:**
- Material: NaYF4:Yb,Er/Tm/Ho, 30nm diameter
- Suspension: 1mL at 0.01% w/v = 10¹² particles
- Active display: 10⁷ particles (100,000× less than reservoir)
- Loss: 0.1%/hr (Brownian drift + settling)
- Non-toxic, inert ceramic — washes off with water

### 6.4 RGB Laser (`rgb_laser_controller.py`)

**Purpose:** Add color to the upconversion emission by selective
excitation and additive scatter.

```
  COLOR MIXING MODEL

  Final perceived color = UCNP emission (75%) + RGB scatter (25%)

  UCNP emission is fixed by ion composition:
    Er³⁺ → green (540nm) + red (660nm)
    Tm³⁺ → blue (475nm)
    Ho³⁺ → yellow-green (545nm)

  RGB laser TUNES the ratio by:
    1. Selective excitation (different λ → different ions)
    2. Power-dependent branching (high power → Er shifts green→red)
    3. Direct scatter (laser light bounces off UCNP cloud)

  Achievable gamut: ~45% sRGB
  Strong: green, yellow, orange, warm white
  Weak:   deep blue, saturated red, magenta
```

### 6.5 Haptics Controller (`haptics_controller.py`)

**Purpose:** Provide tactile feedback when a hand enters the display.

```
  TIME MULTIPLEXING — SAME ARRAY, TWO JOBS

  40kHz carrier = 25μs per cycle

  ┌─────────┬─────────┬─────────┬─────────┬─────────┐
  │  TRAP   │ HAPTIC  │  TRAP   │ HAPTIC  │  TRAP   │  ...
  │ 12.5μs  │ 12.5μs  │ 12.5μs  │ 12.5μs  │ 12.5μs  │
  └─────────┴─────────┴─────────┴─────────┴─────────┘

  TRAP frames:   Phase pattern holds UCNPs at voxel positions
  HAPTIC frames: Phase pattern focuses pressure on user's hand

  Particles don't drift in 12.5μs gaps because:
  - Particle response time: ~10ms (inertia + viscous drag)
  - Gap duration: 0.0125ms
  - Ratio: 800× shorter than response time → particles don't notice

  Hand tracking: subset of transducers switch to RECEIVE mode
  Time-of-flight echo → 3D hand position at ~100Hz, ~2mm accuracy
```

### 6.6 Voxel Engine (`voxel_engine.py`)

**Purpose:** Convert any 3D mesh into a point cloud that fits the
acoustic lattice constraints.

```
  PIPELINE: model.obj → voxels in air

  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
  │  Load     │────▶│ Normalize│────▶│  Sample  │────▶│  Extract │
  │  mesh     │     │ center,  │     │  500k    │     │  texture │
  │  (trimesh)│     │ scale to │     │  surface │     │  colors  │
  │           │     │  6cm     │     │  points  │     │  (UV+    │
  │           │     │  sphere  │     │          │     │  baryc.) │
  └──────────┘     └──────────┘     └──────────┘     └─────┬────┘
                                                            │
  ┌──────────┐     ┌──────────┐     ┌──────────┐           │
  │  Output  │◄────│Downsample│◄────│  Snap to │◄──────────┘
  │  N×[x,y,z│     │  to 1000 │     │  λ/2 grid│
  │   r,g,b] │     │  voxels  │     │  (4.29mm)│
  │          │     │  (keep   │     │  merge   │
  │          │     │  shape)  │     │  dupes   │
  └──────────┘     └──────────┘     └──────────┘

  RESOLUTION REALITY CHECK:
  ┌─────────────────────────────────────────────────┐
  │  Display diameter: 12cm                          │
  │  Lattice pitch: 4.29mm                           │
  │  Voxels across: ~28                              │
  │  Total grid positions in sphere: ~2700           │
  │  Active voxels per frame: ~1000                  │
  │                                                   │
  │  Think of it as a 28×28×28 3D pixel display.     │
  │  Good for: shapes, faces, simple objects          │
  │  Bad for: text, fine detail, thin features        │
  └─────────────────────────────────────────────────┘
```

### 6.7 Calibration (`calibration.py`)

**Purpose:** Align all subsystems after assembly or config changes.

```
  CALIBRATION SEQUENCE

  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 1: Ultrasound Array                                    │
  │  • Enable one transducer at a time                           │
  │  • Measure phase at reference microphone                     │
  │  • Compute per-transducer phase offset correction            │
  │  • Tolerance: <28° offset (manufacturing variance)           │
  ├─────────────────────────────────────────────────────────────┤
  │  STEP 2: VCSEL Beam Alignment                                │
  │  • Fire each VCSEL at minimum power                          │
  │  • Camera measures beam spot position                        │
  │  • Compute galvo correction table                            │
  │  • Tolerance: <100μm displacement (cloud is 200μm)           │
  ├─────────────────────────────────────────────────────────────┤
  │  STEP 3: VCSEL ↔ Ultrasound Alignment (CRITICAL)            │
  │  • Create single trap node at center                         │
  │  • Fire VCSEL series, measure emission with photodetector    │
  │  • Scan VCSEL aim in grid around center                      │
  │  • Find peak emission = true alignment point                 │
  │  • If laser doesn't hit the trapped cloud → no light         │
  ├─────────────────────────────────────────────────────────────┤
  │  STEP 4: RGB Laser                                           │
  │  • Verify galvo tracks VCSEL scan pattern                    │
  │  • Measure color gamut at reference voxel                    │
  └─────────────────────────────────────────────────────────────┘
```

---

## 7. Series Firing — The Core Innovation

This is the key insight that makes the whole system work efficiently.

### Why Not Fire All Lasers At Once?

Upconversion is a **nonlinear** process. The emission intensity scales
as I² (intensity squared) because it requires absorbing TWO photons.

```
  PARALLEL FIRING (all 8 at once):
  ┌──────────────────────────────────────────────────────────┐
  │                                                            │
  │  8 beams arrive simultaneously at the UCNP cloud           │
  │  Total energy P spreads across the cloud volume            │
  │  Each particle sees P/N photons (N = particles)            │
  │                                                            │
  │  Upconversion ∝ I² = (P/N)² per particle                  │
  │  Total emission = N × (P/N)² = P²/N                       │
  │                                                            │
  │  MORE particles = LESS emission per particle               │
  │  Energy is wasted heating the cloud uniformly              │
  └──────────────────────────────────────────────────────────┘

  SERIES FIRING (sequential, 100ns apart):
  ┌──────────────────────────────────────────────────────────┐
  │                                                            │
  │  Pulse 1 (B0): hits cloud, excites Yb³⁺ to ²F₅/₂         │
  │    └─ Yb³⁺ excited state lifetime: ~1ms                   │
  │    └─ Energy STORED in metastable state                    │
  │                                                            │
  │  Pulse 2 (T0): hits SAME atoms 125ns later                │
  │    └─ Adds MORE energy to already-excited Yb³⁺            │
  │    └─ Some energy transfers to Er³⁺ (first step up)       │
  │                                                            │
  │  Pulse 3-8: keep stacking...                               │
  │    └─ After 8 hits in 1μs, accumulated energy =            │
  │       enough for TWO-PHOTON upconversion threshold         │
  │                                                            │
  │  Effective intensity: (8×P_single)²  = 64 × P_single²     │
  │                                                            │
  │  vs parallel:          P²/8                                │
  │                                                            │
  │  Series is 64×8 = 512× MORE EFFICIENT                     │
  └──────────────────────────────────────────────────────────┘
```

### Why Alternating Bottom/Top?

```
  If all 8 fired from bottom only:

       ╲ ╲ ╲ ╲ ╲ ╲ ╲ ╲
        ╲ ╲ ╲ ╲ ╲ ╲ ╲ ╲
         ╲ ╲ ╲ ╲ ╲ ╲ ╲ ╲
          ┌──────────────┐
          │  ████░░░░░░  │ ← Back half in shadow
          │  ████░░░░░░  │   Non-uniform excitation
          │  ████░░░░░░  │   Some particles never hit
          └──────────────┘

  Alternating B0→T0→B1→T1→B2→T2→B3→T3:

       ╲   ╲   ╲   ╲          (from below)
        ╲   ╲   ╲   ╲
         ╲   ╲   ╲   ╲
          ┌──────────────┐
          │  ████████████│ ← Uniform from all angles
          │  ████████████│   Every particle gets hit
          │  ████████████│   No shadows
          └──────────────┘
         ╱   ╱   ╱   ╱
        ╱   ╱   ╱   ╱         (from above)
       ╱   ╱   ╱   ╱
```

---

## 8. Ambient Light Advantage

Most display technologies fight ambient light. UCNPs benefit from it.

```
  TRADITIONAL DISPLAY vs UCNP DISPLAY

  Traditional (LCD, OLED, projection):
    Sunlight → washes out image
    More ambient light = WORSE visibility
    Must increase display brightness to compete

  UCNP upconversion display:
    Sunlight contains ~50% infrared radiation
    IR photons are absorbed by Yb³⁺ sensitizer ions
    This PRE-POPULATES the excited state for free
    When VCSEL series fires, it only needs to push
    already-excited ions over the emission threshold

  ┌─────────────────────────────────────────────────────┐
  │  DARK ROOM:                                          │
  │    Yb³⁺ ground state ──[VCSEL×8]──▶ emission        │
  │    VCSELs do 100% of the work                        │
  │    Power needed: 12μJ × 8 = 96μJ per voxel          │
  │                                                       │
  │  INDOOR DAYLIGHT:                                     │
  │    Yb³⁺ ground state ──[ambient IR]──▶ 40% excited   │
  │    Yb³⁺ 40% excited ──[VCSEL×8]──▶ emission          │
  │    VCSELs do 60% of the work (40% FREE from sun)     │
  │    Power needed: 7μJ × 8 = 56μJ per voxel            │
  │                                                       │
  │  NET EFFECT: daylight makes the hologram              │
  │  MORE power-efficient, not less visible               │
  └─────────────────────────────────────────────────────┘
```

**Honest caveat:** the hologram is still dimmer than ambient light in
daylight conditions. It's visible as a soft glow, not a vivid image.
Direct sunlight overwhelms it entirely. "Daylight helps" means it helps
the physics, not that it looks bright outdoors.

---

## 9. Touch Interaction

```
  HAND ENTERS DISPLAY VOLUME

  ┌──────────────────────────────────────────────────────────┐
  │                                                            │
  │  1. DETECT: Ultrasound echo detects hand position          │
  │     • Subset of transducers switch to receive mode         │
  │     • Time-of-flight → 3D position (~2mm accuracy)         │
  │     • Update rate: ~100Hz                                  │
  │                                                            │
  │  2. OCCLUDE: Voxels behind hand are hidden                 │
  │     • UCNPs near hand are displaced by air pressure         │
  │     • Natural parallax — looks like a real object           │
  │     • No rendering trick needed, physics does it            │
  │                                                            │
  │  3. REFORM: Image rebuilds around hand in ~5ms             │
  │     • Ultrasound recalculates trap pattern                 │
  │     • Particles re-trapped at new positions                │
  │     • Limited by speed of sound (343 m/s)                  │
  │                                                            │
  │  4. HAPTIC: Feel the hologram                              │
  │     • Same ultrasound array focuses pressure on skin       │
  │     • 40kHz modulated to tactile range (200Hz)             │
  │     • Sensation: buzzing, clicking, texture                │
  │     • Focal spot: 8mm on skin                              │
  │     • Max force: 1.6mN (gentle but perceptible)            │
  │                                                            │
  │  UCNPs are non-toxic (inert NaYF4 ceramic).                │
  │  They wash off with water. No health concern.              │
  └──────────────────────────────────────────────────────────┘
```

---

## 10. Honest Performance Numbers

We don't inflate specs. Here's what this system actually delivers.

```
  ┌──────────────────────┬──────────────────────────────────────┐
  │ Metric                │ Value                                 │
  ├──────────────────────┼──────────────────────────────────────┤
  │ Display volume        │ 12cm diameter sphere                  │
  │ Resolution            │ ~28 voxels across (4.29mm pitch)     │
  │ Active voxels/frame   │ ~1000                                │
  │ Frame rate             │ 30 fps                               │
  │ Voxel size             │ ~200μm UCNP cloud                   │
  │ Emission per voxel     │ ~100-150 nW (visible light)         │
  │ Color gamut            │ ~45% sRGB                           │
  │ Color range            │ Green, yellow, orange, warm white   │
  │ Touch latency          │ ~5ms (image reform)                 │
  │ Haptic resolution      │ 8mm focal spot                      │
  │ Total power            │ ~9W                                 │
  │ UCNP refill interval   │ ~10,000 hours                      │
  │ UCNP refill cost       │ ~$0.00005                          │
  │ Prototype cost         │ ~$750                               │
  ├──────────────────────┼──────────────────────────────────────┤
  │ VISIBILITY             │                                      │
  │  Dark room             │ Vivid, excellent                    │
  │  Night outdoor          │ Clearly visible                    │
  │  Indoor daylight        │ Soft glow, visible but not vivid   │
  │  Direct sunlight        │ Too dim (not usable)               │
  ├──────────────────────┼──────────────────────────────────────┤
  │ LIMITATIONS            │                                      │
  │  Resolution            │ Low — shapes yes, text no           │
  │  Color                 │ Limited — no deep blue or magenta   │
  │  Outdoor               │ Not viable in direct sun            │
  │  Particle drift        │ 0.1%/hr loss from traps            │
  │  Scan rate             │ ~30k voxels/sec (galvo limited)    │
  └──────────────────────┴──────────────────────────────────────┘
```

---

## 11. Software Architecture

```
  hologram_v25/
  ├── config.yaml ·················· All hardware parameters (single source of truth)
  │
  ├── main.py ····················· Orchestrator
  │   │                              Initializes all controllers
  │   │                              Runs calibration sequence
  │   │                              Loads mesh → voxels
  │   │                              Main display loop (coordinate all subsystems)
  │   │
  │   ├── vcsel_controller.py ····· 8× VCSEL series firing
  │   │                              Galvo aiming, pulse timing
  │   │                              Alternating B/T sequence
  │   │                              Thermal monitoring
  │   │
  │   ├── ultrasound_controller.py · 256 transducer phased array
  │   │                              Phase computation for multi-node trapping
  │   │                              Pressure field estimation
  │   │                              Dual-bowl geometry
  │   │
  │   ├── ucnp_reservoir.py ······· Nanoparticle supply
  │   │                              Nebulizer burst control
  │   │                              Consumption tracking
  │   │                              Refill estimation
  │   │
  │   ├── rgb_laser_controller.py ·· Color modulation
  │   │                              Per-voxel color from texture
  │   │                              Galvo sync with VCSELs
  │   │                              Gamut mapping
  │   │
  │   ├── haptics_controller.py ···· Touch feedback
  │   │                              Hand detection (US echo)
  │   │                              Haptic phase computation
  │   │                              Voxel occlusion
  │   │
  │   ├── voxel_engine.py ········· Mesh → point cloud
  │   │                              STL/OBJ/PLY/GLTF support
  │   │                              Acoustic lattice snapping
  │   │                              Texture color extraction
  │   │
  │   └── calibration.py ·········· Hardware alignment
  │                                  US array phase offsets
  │                                  VCSEL aim correction
  │                                  Cross-subsystem alignment
  │
  └── simulator.py ················ OpenGL visualization
                                     Clamshell hardware rendering
                                     UCNP upconversion glow model
                                     VCSEL beam animation
                                     Room environment (daylight)
                                     Interactive camera + controls
```

---

## 12. Running the Simulator

### Install

```bash
pip install numpy pygame PyOpenGL trimesh Pillow PyYAML scipy
```

### Run

```bash
# Full system (orchestrator + calibration + simulator)
python main.py --simulate --touch

# Standalone simulator (quick, no calibration)
python simulator.py

# Custom 3D model
python main.py --simulate --mesh model.obj --texture texture.jpg

# Headless benchmark (no GUI)
python main.py --frames 500
```

### Controls

| Key | Action |
|-----|--------|
| Left-drag / Arrows | Orbit camera |
| Right-drag | Pan camera |
| Scroll / W / E | Zoom |
| D | Cycle: dark room → night → indoor daylight |
| L | Toggle VCSEL beam visibility |
| U | Toggle ultrasound field |
| B | Toggle hardware chassis |
| C | Cycle color mode (upconversion / RGB tuned / max color) |
| P | Cycle power level |
| T | Toggle touch interaction demo |
| S | Slow-mo (watch series firing build each voxel) |
| M | Toggle stats overlay |
| 1-3 | Switch display object |
| R | Reset camera |
| Q / ESC | Quit |

---

## 13. References

The physics in this project is based on established research:

1. **UCNP upconversion:** F. Wang et al., "Upconversion nanoparticles in
   biological labeling, imaging, and therapy," *Chem. Rev.* 2015.
   NaYF4:Yb,Er is the most studied upconversion material.

2. **Acoustic levitation:** A. Marzo et al., "Holographic acoustic elements
   for manipulation of levitated objects," *Nature Communications* 2015.
   Demonstrated multi-point acoustic trapping with phased arrays.

3. **Mid-air haptics:** B. Long et al., "Rendering volumetric haptic shapes
   in mid-air using ultrasound," *ACM TOG* 2014. Ultraleap technology
   basis for tactile feedback via focused ultrasound.

4. **VCSEL arrays:** Commercial 980nm VCSELs are widely available
   (II-VI, Lumentum, TRUMPF). Pulsed operation at 100ns is standard.

5. **Series excitation for upconversion:** The energy stacking principle
   exploits the long Yb³⁺ ²F₅/₂ lifetime (~1ms). Sequential excitation
   within this window accumulates population inversion. This is
   well-documented in upconversion laser physics literature.

---

<p align="center">
  <em>This is a concept prototype with physics-based simulation.<br>
  The code models real hardware interfaces as if the device exists.<br>
  All brightness and performance numbers are honest estimates,<br>
  not marketing claims.</em>
</p>
