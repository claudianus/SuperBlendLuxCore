"""Ownership regression: failed/inactivated reconstruction must release scratch.

Real native and stock-Blender gates are separate. These deterministic failure
injections verify resource lifetime and the lossless producer release contract.
"""
import ast
import gc
import os
from pathlib import Path
import types
import unittest
import weakref
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('SLC_FINAL_SOURCE',ROOT/'engine/dlss_final.py'))


class Backend:
    def __init__(self):self.closed=False;self.close_fault=False
    def close(self):
        self.closed=True
        if self.close_fault:raise RuntimeError('injected close failure')


class Consumer:
    def __init__(self,backend):self.backend=backend;self.last_reset=True;self._previous=None
    def reset(self):self._previous=None
    def process(self,packet):return np.ones_like(packet['color'])


class Pipeline:
    def __init__(self):self.fail=False
    def process(self,packet,image,reset=False):
        if self.fail:raise RuntimeError('injected presentation failure')
        return image.copy()


class Session:
    def __init__(self):
        w,h=map(int,os.environ.get('SLC_CLEANUP_SIZE','5,4').split(','))
        self.alpha=np.full((h,w),.5,np.float32);self.rgb=np.full((h,w,3),.25,np.float32)
        self.refs=[];self.released=False;self.acks=[];self.stats=0
    def GetDenoisingFrame(self,*args):return {'lossless_delivery':True,'image_pipeline_accumulated':True,'accumulated_eye_samples':1,'scene_epoch':1,'frame_id':1,'color':np.ones((*self.alpha.shape,4),np.float32)}
    def GetFilm(self):return self
    def HasOutput(self,kind):return kind=='ALPHA'
    def GetOutputFloat(self,kind,buffer,*args):
        np.copyto(buffer,self.alpha if kind=='ALPHA' else self.rgb);self.refs.append(weakref.ref(buffer))
    def UpdateStats(self):self.stats+=1
    def AcknowledgeDenoisingFrame(self,packet,keep_lossless=True):self.acks.append(keep_lossless)
    def ReleaseDenoisingFrameDelivery(self):self.released=True


def controller():
    node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='FinalDLSS')
    env={'np':np,'RendererDLSS':Consumer,'DLSSInputError':ValueError,
         'pysuperluxcore':types.SimpleNamespace(DenoisingImagePipeline=Pipeline,FilmOutputType=types.SimpleNamespace(ALPHA='ALPHA',RGB='RGB'))}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),env)
    return env['FinalDLSS'](Backend(),transparent=True)


class Cleanup(unittest.TestCase):
    def assert_scratch_released(self,c,s):
        gc.collect()
        self.assertIsNone(c.result)
        self.assertIsNone(c._alpha)
        self.assertIsNone(c._raw_color)
        self.assertTrue(s.refs)
        self.assertTrue(all(ref() is None for ref in s.refs),'Native film read scratch remains owned after fallback')
        np.testing.assert_array_equal(s.alpha,.5)
        np.testing.assert_array_equal(s.rgb,.25)

    def test_presentation_failure_releases_alpha_and_raw_scratch_before_fallback(self):
        c=controller();s=Session();c.pipeline.fail=True
        self.assertTrue(c.poll(s))
        self.assertIn('presentation failure',c.failed)
        self.assert_scratch_released(c,s)
        self.assertEqual(s.acks,[False]);self.assertTrue(c.backend.closed)

    def test_invalidate_releases_scratch_and_unparks_the_raw_producer(self):
        c=controller();s=Session();c.poll(s)
        self.assertTrue(all(ref() is not None for ref in s.refs))
        c.invalidate(s,'settings changed')
        self.assert_scratch_released(c,s)
        self.assertTrue(s.released)

    def test_close_failure_still_drops_python_images(self):
        c=controller();s=Session();c.poll(s);c.backend.close_fault=True
        with self.assertRaisesRegex(RuntimeError,'close failure'):c.close()
        self.assert_scratch_released(c,s)

    def test_invalidate_close_failure_still_unparks_producer(self):
        c=controller();s=Session();c.poll(s);c.backend.close_fault=True
        with self.assertRaisesRegex(RuntimeError,'close failure'):c.invalidate(s,'settings changed')
        self.assert_scratch_released(c,s)
        self.assertTrue(s.released,'Lossless producer remained parked after invalidation')


if __name__=='__main__':unittest.main(verbosity=2)
