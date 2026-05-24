"""Smoke tests that run outside Blender against the built wheel."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("hair_sim_physx._core")
from hair_sim_physx import _core  # noqa: E402


def test_solver_roundtrip() -> None:
    solver = _core.HairSolver()
    cfg = _core.SolverConfig()
    cfg.timestep = 1.0 / 60.0
    cfg.use_gpu  = False
    cfg.gravity  = (0.0, 0.0, -9.81)
    assert solver.initialize(cfg)

    strand_count, ppstrand = 4, 8
    pts = np.zeros((strand_count, ppstrand, 3), dtype=np.float32)
    pts[..., 2] = np.linspace(0.0, 1.0, ppstrand)[None, :]
    solver.set_strands(strand_count, ppstrand, pts)

    solver.step(cfg.timestep)
    out = solver.get_points()
    assert out.shape == (strand_count, ppstrand, 3)
    # gravity moved Z down a tiny bit
    assert out[..., 2].mean() < pts[..., 2].mean()
