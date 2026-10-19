"""Analytical camera/virtual-point/environment motion and v2 metadata gates."""
import importlib.util
from pathlib import Path
import sys,unittest
import numpy as np

spec=importlib.util.spec_from_file_location('path_history',Path(__file__).with_name('dlss_renderer_history_test.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

def packet(i=1,x=0):
    p=m.packet(i,x=x);p['guide_version']=2
    g=p['guides'];g[:,:,19]=2;g[:,:,4:7]=.5
    # First surface z=2; its reflected virtual point is z=4.
    g[:,:,26]=4;g[:,:,27]=1;g[:,:,31]=1
    return p

class Motion(unittest.TestCase):
    def test_diffuse_only_path_does_not_reset_for_irrelevant_virtual_point(self):
        backend=m.Backend();history=m.m.RendererDLSS(backend)
        a=packet();a['guides'][:,:,4:7]=0;a['guides'][:,:,26]=-4
        history.process(a)
        b=packet(2,x=1);b['guides'][:,:,4:7]=0;b['guides'][:,:,26]=-4
        history.process(b)
        self.assertFalse(backend.frames[-1].reset)
        np.testing.assert_array_equal(backend.frames[-1].motion[:,:,0],8)
        np.testing.assert_array_equal(backend.frames[-1].specular_motion,0)

    def test_reflected_virtual_point_uses_its_own_depth(self):
        backend=m.Backend();history=m.m.RendererDLSS(backend)
        a=packet();before=a['guides'].copy();history.process(a)
        history.process(packet(12,x=1))
        self.assertFalse(backend.frames[-1].reset)
        np.testing.assert_array_equal(backend.frames[-1].motion[:,:,0],8)
        np.testing.assert_array_equal(backend.frames[-1].specular_motion[:,:,0],4)
        np.testing.assert_array_equal(a['guides'],before)

    def test_environment_translation_is_zero_and_rotation_has_motion(self):
        backend=m.Backend();history=m.m.RendererDLSS(backend)
        a=packet();a['guides'][:,:,27]=2;a['guides'][:,:,26]=1
        history.process(a)
        b=packet(2,x=100);b['guides'][:,:,27]=2;b['guides'][:,:,26]=1
        history.process(b);np.testing.assert_array_equal(backend.frames[-1].motion,0)
        b=packet(3,x=100);b['guides'][:,:,27]=2;b['guides'][:,:,26]=1
        angle=.1;c,s=np.cos(angle),np.sin(angle)
        b['world_to_camera'][:3,:3]=[[c,0,s],[0,1,0],[-s,0,c]]
        history.process(b)
        np.testing.assert_allclose(backend.frames[-1].motion[:,:,0],-16*np.tan(angle),atol=1e-6)
        self.assertFalse(backend.frames[-1].reset)

    def test_reflected_environment_motion_excludes_translation(self):
        backend=m.Backend();history=m.m.RendererDLSS(backend)
        a=packet();a['guides'][:,:,27]=3;a['guides'][:,:,26]=1
        history.process(a)
        b=packet(2,x=1);b['guides'][:,:,27]=3;b['guides'][:,:,26]=1
        history.process(b)
        np.testing.assert_array_equal(backend.frames[-1].motion[:,:,0],8)
        np.testing.assert_array_equal(backend.frames[-1].specular_motion,0)

    def test_incomplete_unknown_and_unsupported_path_metadata_rejected(self):
        for index,value in ((19,0),(23,1),(27,4),(31,3),(7,2)):
            p=packet();p['guides'][0,0,index]=value
            with self.assertRaises(m.m.DLSSInputError):m.m.RendererDLSS(m.Backend()).process(p)
        p=packet();p['guide_version']=3
        with self.assertRaises(m.m.DLSSInputError):m.m.RendererDLSS(m.Backend()).process(p)

if __name__=='__main__':unittest.main()
