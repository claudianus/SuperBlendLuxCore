"""Projection oracle for DLSS motion transforms.

Retains the previous two matrix products as an independent numerical oracle.
It covers full images, compact masked points, strided guide views, perspective,
orthographic and distant world coordinates; no SDK or renderer is simulated.
"""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('dlss_projection', Path(__file__).parents[1]/'engine/dlss.py')
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)


def reference(points, world_to_camera, camera_to_raster, height, direction=False):
    camera = points @ world_to_camera[:3, :3].T
    if not direction:
        camera += world_to_camera[:3, 3]
    raster = camera @ camera_to_raster[:, :3].T
    if not direction:
        raster += camera_to_raster[:, 3]
    if not np.isfinite(raster).all() or np.any(raster[..., 3] <= 0):
        raise d.DLSSInputError('Invalid reference projection')
    result = raster[..., :2]/raster[..., 3:4]
    result[..., 1] = height-result[..., 1]
    return result


class Projection(unittest.TestCase):
    def test_point_and_direction_oracle_for_strided_and_compact_inputs(self):
        rng = np.random.default_rng(1833)
        rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
        for distant in (False, True):
            origin = np.array([1e6, -2e6, 3e6]) if distant else np.array([3., -5., 2.])
            camera = np.eye(4)
            camera[:3, :3] = rotation
            camera[:3, 3] = -rotation@origin
            local = rng.uniform(-1, 1, (96, 128, 3))
            local[..., 2] = rng.uniform(2, 100, (96, 128))
            world = local@rotation+origin
            guides = np.zeros((96, 128, 32), np.float32)
            guides[..., 12:15] = world
            for points in (world, guides[..., 12:15], world.reshape(-1, 3)[::3]):
                for ortho in (False, True):
                    raster = np.array([[800, 0, 640, 0], [0, 800, 360, 0],
                                       [0, 0, 1, 0], [0, 0, 1, 0]], float)
                    if ortho:
                        raster[:, 2] = [0, 0, 1, 0]
                        raster[:, 3] = [640, 360, 0, 1]
                    actual = d.RendererDLSS._project(points, camera, raster, 720)
                    np.testing.assert_allclose(actual, reference(points, camera, raster, 720),
                                               atol=1e-5, rtol=2e-11)
            directions = local@rotation
            raster = np.array([[800, 0, 640, 0], [0, 800, 360, 0],
                               [0, 0, 1, 0], [0, 0, 1, 0]], float)
            for points in (directions, directions.reshape(-1, 3)[::3]):
                actual = d.RendererDLSS._project_direction(points, camera, raster, 720)
                np.testing.assert_allclose(actual, reference(points, camera, raster, 720, True),
                                           atol=1e-9, rtol=2e-12)

    def test_environment_translation_excluded_and_invalid_projection_rejected(self):
        camera = np.eye(4)
        raster = np.array([[800, 0, 640, 0], [0, 800, 360, 0],
                           [0, 0, 1, 0], [0, 0, 1, 0]], float)
        points = np.array([[.2, .1, 1], [-.3, .2, 2]])
        before = d.RendererDLSS._project_direction(points, camera, raster, 720)
        camera[:3, 3] = [1e9, -2e9, 3e9]
        np.testing.assert_array_equal(before, d.RendererDLSS._project_direction(points, camera, raster, 720))
        for bad in (np.array([[0., 0., 0.]]), np.array([[0., 0., -1.]]), np.array([[np.inf, 1., 1.]])):
            with np.errstate(invalid='ignore', over='ignore'):
                with self.assertRaises(d.DLSSInputError):
                    d.RendererDLSS._project_direction(bad, camera, raster, 720)
        empty = d.RendererDLSS._project(np.empty((0, 3)), np.eye(4), raster, 720)
        self.assertEqual(empty.shape, (0, 2))


if __name__ == '__main__':
    unittest.main()
