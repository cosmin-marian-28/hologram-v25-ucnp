"""
Voxel Engine — 3D Model → Point Cloud for Holographic Display
==============================================================
Converts STL/OBJ/PLY meshes into voxel point clouds suitable for
the ultrasonic trapping array.

CONSTRAINTS:
  - Minimum voxel pitch: 4.29mm (λ/2 at 40kHz) — can't place voxels closer
  - Display volume: 6cm radius sphere
  - Max voxels per frame: ~1000 (ultrasound node limit for 256 transducers)
  - Voxels must lie on the acoustic lattice (snapped to λ/2 grid)

PIPELINE:
  1. Load mesh (STL, OBJ, PLY, GLTF — anything trimesh supports)
  2. Normalize to fit display volume
  3. Sample surface → dense point cloud (100k+ points)
  4. Extract texture colors (if available)
  5. Snap to acoustic lattice (λ/2 grid)
  6. Downsample to max voxel count while preserving shape
  7. Output: positions + colors ready for ultrasound controller

RESOLUTION:
  At 4.29mm pitch in a 12cm diameter sphere:
  - ~28 voxels across diameter
  - ~2700 possible grid positions inside sphere
  - At 1000 active voxels: ~37% fill rate
  - Comparable to a 28×28×28 voxel display (decent for shapes, not for text)

  For higher resolution: use 80kHz transducers (λ/2 = 2.14mm, ~11k positions)
  or 200kHz (λ/2 = 0.86mm, ~170k positions). Config is parameterized.
"""

import numpy as np
import trimesh
import math
import yaml
import os
from typing import Tuple, Optional
from PIL import Image


class VoxelEngine:
    """
    Converts 3D meshes to voxel point clouds for holographic display.

    Usage:
        engine = VoxelEngine('config.yaml')

        # Load any supported mesh format
        pts, colors, normals = engine.load_mesh('model.stl')

        # Or load with texture
        pts, colors, normals = engine.load_mesh('model.obj',
                                                 texture='texture.jpg')

        # Get lattice-snapped version for actual hardware
        hw_pts, hw_colors = engine.snap_to_lattice(pts, colors)

        # Get display info
        info = engine.get_resolution_info()
    """

    def __init__(self, config_path: str = 'config.yaml'):
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        dc = cfg['display']
        uc = cfg['ultrasound_array']
        self.display_radius = dc['radius_m']
        self.display_center_y = dc['center_height_m']
        self.max_voxels = dc['max_voxels_per_frame']

        freq_hz = uc['frequency_khz'] * 1000
        speed_of_sound = 343.0
        self.wavelength = speed_of_sound / freq_hz
        self.lattice_pitch = self.wavelength / 2.0

        self.display_center = np.array([0.0, self.display_center_y, 0.0])

        # Dense sampling count (before downsampling)
        self._dense_count = 500000

    def load_mesh(self, mesh_path: str,
                  texture_path: Optional[str] = None,
                  n_points: Optional[int] = None,
                  auto_orient: bool = True) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Load a 3D mesh and convert to colored point cloud.

        Supports: STL, OBJ, PLY, GLTF, 3MF, OFF, and anything trimesh handles.

        Args:
            mesh_path: path to mesh file
            texture_path: optional texture image (for OBJ with UV coords)
            n_points: number of surface samples (default: dense, then downsample)
            auto_orient: if True, auto-detect and fix orientation

        Returns:
            points: (N, 3) float32 positions in display volume
            colors: (N, 3) float32 RGB colors (0-1)
            normals: (N, 3) float32 surface normals
        """
        if n_points is None:
            n_points = self._dense_count

        print(f"[VOXEL] Loading: {mesh_path}")
        mesh = trimesh.load(mesh_path, force='mesh')
        if isinstance(mesh, trimesh.Scene):
            meshes = [g for g in mesh.geometry.values()
                      if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                raise ValueError(f"No geometry found in {mesh_path}")
            mesh = trimesh.util.concatenate(meshes)

        print(f"[VOXEL] Mesh: {len(mesh.vertices)} vertices, "
              f"{len(mesh.faces)} faces")

        # Center and normalize
        mesh.vertices -= mesh.centroid
        scale = np.max(np.abs(mesh.vertices))
        if scale > 0:
            mesh.vertices /= scale
        mesh.vertices *= self.display_radius

        # Auto-orient: detect if model is Z-up and rotate to Y-up
        if auto_orient:
            bbox = mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)
            # If Z extent > Y extent, model is probably Z-up
            if bbox[2] > bbox[1] * 1.2:
                print(f"[VOXEL] Auto-rotating Z-up → Y-up")
                rot = trimesh.transformations.rotation_matrix(
                    -math.pi / 2, [1, 0, 0])
                mesh.apply_transform(rot)
                mesh.vertices -= mesh.centroid
                scale = np.max(np.abs(mesh.vertices))
                if scale > 0:
                    mesh.vertices /= scale
                mesh.vertices *= self.display_radius

        # Offset to display center
        mesh.vertices[:, 1] += self.display_center_y

        # Sample surface
        pts, face_indices = trimesh.sample.sample_surface(mesh, n_points)
        normals = mesh.face_normals[face_indices]

        # Extract colors
        colors = self._extract_colors(mesh, pts, face_indices, texture_path)

        print(f"[VOXEL] Sampled {n_points:,} surface points")
        print(f"[VOXEL] Bounding box: "
              f"X[{pts[:,0].min():.3f}, {pts[:,0].max():.3f}] "
              f"Y[{pts[:,1].min():.3f}, {pts[:,1].max():.3f}] "
              f"Z[{pts[:,2].min():.3f}, {pts[:,2].max():.3f}]")

        return (pts.astype(np.float32),
                colors.astype(np.float32),
                normals.astype(np.float32))

    def _extract_colors(self, mesh, pts, face_indices,
                        texture_path) -> np.ndarray:
        """Extract per-point colors from texture or vertex colors."""
        n = len(pts)
        colors = np.tile([0.7, 0.7, 0.7], (n, 1))  # Default grey

        # Try texture
        if texture_path and os.path.exists(texture_path):
            try:
                tex = np.array(Image.open(texture_path).convert('RGB')) / 255.0
                th, tw = tex.shape[:2]
                if hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None:
                    uv = mesh.visual.uv
                    faces = mesh.faces
                    for i in range(n):
                        fi = face_indices[i]
                        verts = mesh.vertices[faces[fi]]
                        fuv = uv[faces[fi]]
                        v0, v1, v2 = verts
                        p = pts[i]
                        # Barycentric interpolation
                        e1, e2 = v1 - v0, v2 - v0
                        d00 = e1 @ e1
                        d01 = e1 @ e2
                        d11 = e2 @ e2
                        d20 = (p - v0) @ e1
                        d21 = (p - v0) @ e2
                        dn = d00 * d11 - d01 * d01
                        if abs(dn) < 1e-12:
                            uc, vc = fuv[0]
                        else:
                            bv = (d11 * d20 - d01 * d21) / dn
                            bw = (d00 * d21 - d01 * d20) / dn
                            bu = 1 - bv - bw
                            uc = bu * fuv[0, 0] + bv * fuv[1, 0] + bw * fuv[2, 0]
                            vc = bu * fuv[0, 1] + bv * fuv[1, 1] + bw * fuv[2, 1]
                        colors[i] = tex[int(np.clip((1 - vc) * th, 0, th - 1)),
                                        int(np.clip(uc * tw, 0, tw - 1))]
                    print(f"[VOXEL] ✓ Texture colors from {texture_path}")
            except Exception as e:
                print(f"[VOXEL] ⚠ Texture failed: {e}")

        # Try vertex colors
        elif hasattr(mesh.visual, 'vertex_colors') and mesh.visual.vertex_colors is not None:
            vc = mesh.visual.vertex_colors[:, :3] / 255.0
            faces = mesh.faces
            for i in range(n):
                fi = face_indices[i]
                # Average face vertex colors (approximate)
                colors[i] = vc[faces[fi]].mean(axis=0)
            print(f"[VOXEL] ✓ Vertex colors extracted")

        return colors

    def snap_to_lattice(self, points: np.ndarray,
                        colors: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Snap point cloud to the acoustic lattice grid.

        The ultrasound standing wave creates pressure nodes at λ/2 intervals.
        Voxels can only exist at these grid positions. This function:
        1. Quantizes all points to nearest lattice position
        2. Removes duplicates (multiple points → one voxel)
        3. Averages colors for merged points
        4. Downsamples to max_voxels if needed

        Args:
            points: (N, 3) dense point cloud
            colors: (N, 3) per-point colors

        Returns:
            lattice_points: (M, 3) snapped positions (M ≤ max_voxels)
            lattice_colors: (M, 3) averaged colors
        """
        pitch = self.lattice_pitch

        # Quantize to grid
        grid_indices = np.round(
            (points - self.display_center) / pitch
        ).astype(np.int32)

        # Find unique grid cells
        unique_keys = {}
        for i in range(len(grid_indices)):
            key = tuple(grid_indices[i])
            if key not in unique_keys:
                unique_keys[key] = {'colors': [], 'count': 0}
            unique_keys[key]['colors'].append(colors[i])
            unique_keys[key]['count'] += 1

        # Build output arrays
        n_unique = len(unique_keys)
        lattice_pts = np.zeros((n_unique, 3), dtype=np.float32)
        lattice_colors = np.zeros((n_unique, 3), dtype=np.float32)

        for idx, (key, data) in enumerate(unique_keys.items()):
            # Grid position → world position
            lattice_pts[idx] = (np.array(key, dtype=np.float32) * pitch +
                                 self.display_center)
            # Average color
            lattice_colors[idx] = np.mean(data['colors'], axis=0)

        # Filter to display volume
        dists = np.linalg.norm(lattice_pts - self.display_center, axis=1)
        inside = dists <= self.display_radius * 1.05
        lattice_pts = lattice_pts[inside]
        lattice_colors = lattice_colors[inside]

        print(f"[VOXEL] Lattice snap: {len(points):,} points → "
              f"{len(lattice_pts):,} voxels "
              f"(pitch={pitch*1000:.2f}mm)")

        # Downsample if over limit
        if len(lattice_pts) > self.max_voxels:
            indices = np.random.choice(len(lattice_pts), self.max_voxels,
                                        replace=False)
            lattice_pts = lattice_pts[indices]
            lattice_colors = lattice_colors[indices]
            print(f"[VOXEL] Downsampled to {self.max_voxels} voxels")

        return lattice_pts, lattice_colors

    def get_resolution_info(self) -> dict:
        """Return display resolution characteristics."""
        diameter = self.display_radius * 2
        voxels_across = int(diameter / self.lattice_pitch)
        total_positions = int((voxels_across ** 3) * 0.52)  # sphere packing

        return {
            'lattice_pitch_mm': round(self.lattice_pitch * 1000, 2),
            'voxels_across_diameter': voxels_across,
            'total_lattice_positions': total_positions,
            'max_active_voxels': self.max_voxels,
            'fill_rate_pct': round(self.max_voxels / max(total_positions, 1) * 100, 1),
            'display_radius_mm': self.display_radius * 1000,
            'equivalent_resolution': f"~{voxels_across}×{voxels_across}×{voxels_across}",
        }
