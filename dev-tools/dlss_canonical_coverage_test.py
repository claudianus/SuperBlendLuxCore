"""Consumer contracts for immutable renderer target coverage and holdout RGB.

A deliberately wrong neural alpha represents the observed vendor failure.
Native renderer/stock Blender tests separately prove the producer/camera/AOVs.
"""
from pathlib import Path
import importlib.util
import sys
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('canonical_coverage',Path(__file__).parents[1]/'engine/dlss.py')
d=importlib.util.module_from_spec(spec);sys.modules[spec.name]=d;spec.loader.exec_module(d)


class Backend:
    def __init__(self):self.calls=0
    def process(self,frame):
        self.calls+=1
        w,h=frame.output_size or frame.color.shape[1::-1]
        result=np.full((h,w,4),.7,np.float32);result[:,:,3]=.80228543
        return result


def packet():
    g=np.zeros((32,32,32),np.float32);g[:,:,3]=1;g[:,:,7]=1;g[:,:,10]=1;g[:,:,15]=2;g[:,:,19]=2
    return {'source':'renderer_gpu','version':1,'guide_version':2,'complete':True,'independent_samples':True,
            'motion_camera_compatible':True,'frame_id':1,'scene_epoch':1,'jitter':(0.,0.),
            'color':np.ones((32,32,4),np.float32),'guides':g,'sample_count':np.ones((32,32),np.uint32),
            'world_to_camera':np.eye(4),'camera_to_raster':np.eye(4)}


class Coverage(unittest.TestCase):
    def test_actual_target_alpha_replaces_failed_neural_alpha_without_touching_raw(self):
        p=packet();alpha=np.tile(np.linspace(0,1,64,dtype=np.float32),(64,1));mask=np.zeros((64,64),np.uint8)
        p.update(target_size=(64,64),target_alpha=alpha,target_holdout=mask,coverage_source='renderer_full_resolution',input_reduction=2)
        original={n:p[n].copy() for n in ['color','guides','sample_count','target_alpha','target_holdout']}
        b=Backend();out=d.RendererDLSS(b).process(p)
        np.testing.assert_array_equal(out[:,:,3],alpha);np.testing.assert_array_equal(out[:,:,:3],np.float32(.7))
        self.assertEqual(b.calls,1)
        for n,value in original.items():np.testing.assert_array_equal(p[n],value)

    def test_holdout_preserves_accumulated_background_radiance_at_a_jittered_edge(self):
        p=packet();alpha=np.zeros((64,64),np.float32);mask=np.zeros((64,64),np.uint8);mask[8,9]=1
        rgb=np.zeros((64,64,3),np.float32);rgb[8,9]=(.1,.2,.3)
        p.update(target_size=(64,64),target_alpha=alpha,target_holdout=mask,target_holdout_rgb=rgb,
                 coverage_source='renderer_full_resolution',input_reduction=2,image_pipeline_accumulated=True)
        out=d.RendererDLSS(Backend()).process(p)
        np.testing.assert_array_equal(out[8,9,:3],rgb[8,9]);self.assertEqual(out[8,9,3],0)
        np.testing.assert_array_equal(out[0,0,:3],np.float32(.7))

    def test_native_holdout_is_exact_but_legacy_upscale_cannot_invent_its_target_mask(self):
        p=packet();p['guides'][3,4,7]=5;p['color'][3,4]=0
        b=Backend();out=d.RendererDLSS(b).process(p);np.testing.assert_array_equal(out[3,4],0)
        b=Backend()
        with self.assertRaisesRegex(d.DLSSInputError,'target coverage'):
            d.RendererDLSS(b).process(p,output_size=(64,64))
        self.assertEqual(b.calls,0)

    def test_invalid_canonical_coverage_is_rejected_before_inference_and_history_reset(self):
        for change in ['shape','alpha','mask','rgb','raster']:
            p=packet();p.update(target_size=(64,64),target_alpha=np.ones((64,64),np.float32),
                target_holdout=np.zeros((64,64),np.uint8),coverage_source='renderer_full_resolution')
            if change=='shape':p['target_alpha']=p['target_alpha'][:16]
            if change=='alpha':p['target_alpha'][0,0]=1.01
            if change=='mask':p['target_holdout'][0,0]=2
            if change=='rgb':p['target_holdout'][0,0]=1
            b=Backend();consumer=d.RendererDLSS(b)
            with self.assertRaises(d.DLSSInputError):consumer.process(p,output_size=(128,128) if change=='raster' else None)
            self.assertEqual(b.calls,0);self.assertIsNone(consumer._previous)


if __name__=='__main__':unittest.main(verbosity=2)
