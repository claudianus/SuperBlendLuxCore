"""History contract tests: delivered-frame motion, failed evaluation and reset."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('dlss_history', Path(__file__).parents[1]/'engine/dlss.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def packet(frame_id=1, x=0, epoch=1, size=32):
    guides = np.zeros((size, size, 32), np.float32)
    guides[:, :, :3] = .5
    guides[:, :, 3] = 1
    guides[:, :, 7] = 1
    guides[:, :, 10] = 1
    guides[:, :, 14:16] = 2
    world_to_camera = np.eye(4)
    world_to_camera[0, 3] = -x
    camera_to_raster = np.array([[16, 0, size/2, 0], [0, 16, size/2, 0],
                                 [0, 0, 1, 0], [0, 0, 1, 0]], float)
    return dict(source='renderer_gpu', version=1, complete=True, independent_samples=True,
                motion_camera_compatible=True,
                frame_id=frame_id, scene_epoch=epoch, jitter=(.1, -.2),
                color=np.ones((size, size, 4), np.float32), guides=guides,
                sample_count=np.ones((size, size), np.uint32),
                world_to_camera=world_to_camera, camera_to_raster=camera_to_raster)


class Backend:
    def __init__(self):
        self.frames = []
        self.fail = False

    def process(self, frame):
        if self.fail:
            raise RuntimeError('evaluation failed')
        frame.native()
        self.frames.append(frame)
        return frame.color.copy()


class History(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.history = m.RendererDLSS(self.backend)

    def test_ngx_jitter_returns_traced_samples_to_unjittered_pixel_centres(self):
        centres = np.array([8.5, 17.5])
        for frame_id, jitter in enumerate(((.25, -.125), (-.5, .5), (0., 0.)), 1):
            p = packet(frame_id)
            p['jitter'] = jitter
            color, guides = p['color'].copy(), p['guides'].copy()
            self.history.process(p)
            frame = self.backend.frames[-1]
            # Native filmX/Y = pixel + .5 + ray displacement. NGX's
            # compensation must bring that actual sample back to its centre.
            traced = centres + np.asarray(jitter)
            np.testing.assert_array_equal(traced + frame.jitter, centres)
            self.assertEqual(p['jitter'], jitter)
            np.testing.assert_array_equal(p['color'], color)
            np.testing.assert_array_equal(p['guides'], guides)

    def test_motion_bridges_delivered_frames_and_preserves_input(self):
        a = packet()
        before = a['guides'].copy()
        self.history.process(a)
        b = packet(10, x=1)  # The renderer published eight skipped frames.
        self.history.process(b)
        self.assertTrue(self.backend.frames[0].reset)
        self.assertFalse(self.backend.frames[1].reset)
        np.testing.assert_array_equal(self.backend.frames[1].motion[:, :, 0], 8)
        np.testing.assert_array_equal(self.backend.frames[1].motion[:, :, 1], 0)
        np.testing.assert_array_equal(a['guides'], before)
        np.testing.assert_allclose(self.backend.frames[0].diffuse[:, :, :3], 1/3)
        # Jitter is a camera-sample offset, not a motion-vector delta.
        b = packet(11, x=1)
        b['jitter'] = (-.3, .4)
        self.history.process(b)
        np.testing.assert_array_equal(self.backend.frames[-1].motion, 0)

    def test_failed_evaluation_epoch_resize_and_explicit_cut_reset(self):
        self.history.process(packet())
        self.backend.fail = True
        with self.assertRaises(RuntimeError):
            self.history.process(packet(2, x=1))
        self.backend.fail = False
        self.history.process(packet(3, x=2))
        self.assertTrue(self.backend.frames[-1].reset)
        for p, kwargs in [(packet(4, epoch=2), {}), (packet(5, epoch=2, size=48), {}),
                          (packet(6, epoch=2, size=48), {'reset': True})]:
            self.history.process(p, **kwargs)
            self.assertTrue(self.backend.frames[-1].reset)

    def test_incomplete_duplicate_and_reflection_motion_are_rejected(self):
        for change in ('count', 'status', 'source', 'version', 'camera'):
            p = packet()
            if change == 'count': p['sample_count'][0, 0] = 2
            elif change == 'status': p['guides'][0, 0, 7] = 3
            elif change == 'source': p['source'] = 'host_retrace'
            elif change == 'camera': p['motion_camera_compatible'] = False
            else: p['version'] = 2
            with self.assertRaises(m.DLSSInputError): self.history.process(p)
        self.assertEqual(len(self.backend.frames), 0)
        self.history.process(packet())
        with self.assertRaises(m.DLSSInputError): self.history.process(packet())
        reflective = packet(2)
        reflective['guides'][:, :, 4:7] = .1
        self.history.process(reflective)
        moving = packet(3, x=1)
        moving['guides'][:, :, 4:7] = .1
        with self.assertRaisesRegex(m.DLSSInputError, 'reflection-motion'):
            self.history.process(moving)
        self.assertEqual(len(self.backend.frames), 2)


if __name__ == '__main__':
    unittest.main()
