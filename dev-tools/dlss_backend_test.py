"""Frame-contract tests and optional real CUDA DLSS lifecycle/upscaling tests."""
from pathlib import Path
import ctypes as C
import importlib.util
import sys
import os
import json
import hashlib
import dataclasses
import unittest
import concurrent.futures

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('slc_dlss_backend',ROOT/'engine/dlss.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

def frame(w=128,h=72,id=0,serial=0,scale=1):
    rng=np.random.default_rng(42+id)
    color=np.ones((h,w,4),np.float32)
    color[:,:,:3]=np.array([.3,.4,.8],np.float32)+rng.uniform(-.15,.15,(h,w,3)).astype(np.float32)
    color[:,:,3]=np.linspace(0,1,w,dtype=np.float32)
    diffuse=np.full((h,w,4),.5,np.float32);specular=np.full((h,w,4),.04,np.float32)
    normal=np.zeros((h,w,4),np.float32);normal[:,:,2]=1;normal[:,:,3]=.5
    return m.DLSSFrame(color,np.full((h,w),2,np.float32),diffuse,specular,normal,
        np.zeros((h,w,2),np.float32),np.zeros((h,w,2),np.float32),id,serial,(0.,0.),True,
        output_size=(w*scale,h*scale))

def digest(f):
    return {n:hashlib.sha256(getattr(f,n).tobytes()).hexdigest() for n in
            ['color','depth','diffuse','specular','normal_roughness','motion','specular_motion']}

class Contract(unittest.TestCase):
    def test_surface_guide_gate_and_compression_do_not_touch_inputs(self):
        f=frame()
        guides={'status':np.ones((72,128),np.uint8), 'diffuse':f.diffuse.copy(),
                'specular':f.specular, 'normal_roughness':f.normal_roughness,
                'position_depth':np.full((72,128,4),2,np.float32)}
        original=guides['diffuse'].copy()
        args=dict(render_position=guides['position_depth'][:,:,:3].copy(),
                  motion=f.motion,specular_motion=f.specular_motion,frame_id=0,
                  scene_serial=0,jitter=(0.,0.),independent_samples=True)
        accepted=m.DLSSFrame.from_surface_guides(f.color,guides,**args)
        np.testing.assert_allclose(accepted.diffuse[:,:,:3],1/3,atol=1e-7)
        self.assertTrue(np.array_equal(guides['diffuse'],original))
        self.assertTrue(np.array_equal(accepted.color,f.color))
        for status in (0,2,3):
            guides['status'][0,0]=status
            with self.assertRaises(m.DLSSInputError):m.DLSSFrame.from_surface_guides(f.color,guides,**args)
        guides['status'][0,0]=1
        with self.assertRaises(m.DLSSInputError):
            m.DLSSFrame.from_surface_guides(f.color,guides,**{**args,'specular_motion':None})
        bad_position=args['render_position'].copy();bad_position[0,0,0]+=1
        with self.assertRaisesRegex(m.DLSSInputError,'hit positions'):
            m.DLSSFrame.from_surface_guides(f.color,guides,**{**args,'render_position':bad_position})

    def test_missing_guides_accumulated_samples_nonfinite_and_layout(self):
        f=frame();f.native()
        cases=[{'independent_samples':False},{'specular_motion':None},
               {'color':f.color.astype(np.float64)},{'motion':f.motion[:,::-1]},
               {'jitter':(.6,0.)},{'frame_id':-1},{'depth':np.full((72,128),np.nan,np.float32)}]
        for change in cases:
            with self.subTest(change=list(change)):
                with self.assertRaises(m.DLSSInputError):dataclasses.replace(f,**change).native()
    def test_no_implicit_backend_and_unsupported_platform(self):
        with self.assertRaises(m.DLSSUnavailable):m.CUDADLSS('/tmp','/tmp',library='/does/not/exist.so')

    def test_alpha_outside_unit_interval_is_rejected_without_changing_rgb(self):
        for value in (-.001, 1.001):
            f = frame();f.color[0, 0, 3] = value
            before = digest(f)
            with self.assertRaisesRegex(m.DLSSInputError, 'Alpha'):
                f.native()
            self.assertEqual(before, digest(f))

@unittest.skipUnless(os.environ.get('SLC_DLSS_TEST_LIBRARY'),'real GPU backend not requested')
class CUDA(unittest.TestCase):
    def backend(self,budget=512*1024**2):
        obj=m.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SLC_DLSS_TEST_CACHE'],
                      memory_limit=budget,library=os.environ['SLC_DLSS_TEST_LIBRARY'])
        self.addCleanup(obj.close);return obj
    def test_independent_frames_alpha_input_preservation_workers_and_resize(self):
        b=self.backend();stats=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            for i in range(8):
                f=frame(1280,720,i);before=digest(f)
                result=pool.submit(b.process,f).result(timeout=45)
                self.assertTrue(np.isfinite(result).all());self.assertGreater(float(result[:,:,:3].mean()),.01)
                self.assertTrue(np.array_equal(result[:,:,3],f.color[:,:,3]));self.assertEqual(before,digest(f))
                stats.append(b.stats())
        self.assertEqual(len({s['texture_bytes'] for s in stats}),1)
        self.assertEqual(len({s['host_scratch_bytes'] for s in stats}),1)
        self.assertIsNone(stats[-1]['sdk_private_bytes'])
        full=stats[-1]['texture_bytes']
        for f in [frame(640,360,9),frame(1280,720,10)]:
            self.assertTrue(np.isfinite(b.process(f)).all())
        self.assertEqual(b.stats()['texture_bytes'],full)
        target=Path(os.environ['SLC_DLSS_TEST_OUT']);target.mkdir(parents=True,exist_ok=True)
        np.save(target/'synthetic-native-rgba.npy',result)
        (target/'plateau.json').write_text(json.dumps(stats,indent=2)+'\n')
    def test_upscale_reset_and_independent_histories(self):
        a=self.backend();b=self.backend()
        first=frame(320,180,0,1,2)
        out=a.process(first);self.assertEqual(out.shape,(360,640,4));self.assertTrue(np.isfinite(out).all())
        self.assertTrue(np.all((out[:, :, 3] >= 0) & (out[:, :, 3] <= 1)))
        b.process(frame(320,180,0,0,2))
        f=frame(320,180,0,2,2)
        aa=a.process(f);bb=b.process(f)
        self.assertLess(float(np.max(np.abs(aa-bb))),1e-4)
    def test_native_failure_preserves_output_and_can_recover(self):
        b=self.backend();f=frame();b.process(f)
        for change in [{'frame_id':0},{'frame_id':1,'independent_samples':False}]:
            bad=dataclasses.replace(f,**change)
            n=f.native();n.frame_id=bad.frame_id;n.independent_samples=bad.independent_samples
            out=np.full((72,128,4),-123,np.float32);message=C.create_string_buffer(1024)
            ok=b._lib.slc_dlss_process(b._handle,C.byref(n),out.ctypes.data_as(C.POINTER(C.c_float)),out.size,message,len(message))
            self.assertEqual(ok,0);self.assertTrue(np.all(out==-123));self.assertTrue(message.value)
        n=dataclasses.replace(f,frame_id=1).native();message=C.create_string_buffer(1024)
        ok=b._lib.slc_dlss_process(b._handle,C.byref(n),f.color.ctypes.data_as(C.POINTER(C.c_float)),f.color.size,message,len(message))
        self.assertEqual(ok,0);self.assertIn(b'alias',message.value)
        self.assertTrue(np.isfinite(b.process(dataclasses.replace(f,frame_id=1))).all())
    def test_budget_rejection_and_destroy(self):
        b=self.backend(1024*1024)
        with self.assertRaisesRegex(RuntimeError,'budget'):b.process(frame(1280,720))
        self.assertEqual(b.stats()['texture_bytes'],0)
        b.close();b.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):b.stats()

    def test_native_alpha_rejection_preserves_target_and_allows_retry(self):
        b = self.backend();f = frame();n = f.native()
        out = np.full((72, 128, 4), -123, np.float32)
        message = C.create_string_buffer(1024)
        for value in (-.001, 1.001):
            f.color[0, 0, 3] = value
            ok = b._lib.slc_dlss_process(b._handle, C.byref(n), out.ctypes.data_as(C.POINTER(C.c_float)),
                                       out.size, message, len(message))
            self.assertEqual(ok, 0);self.assertIn(b'Alpha', message.value)
            self.assertTrue(np.all(out == -123));self.assertEqual(b.stats()['frames'], 0)
        f.color[0, 0, 3] = 0.
        self.assertTrue(np.isfinite(b.process(f)).all())

if __name__=='__main__':unittest.main()
