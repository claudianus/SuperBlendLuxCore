"""Actual GPU full-raster transport, exact neural subgrid and canonical coverage.

Raw target RGBA is compared with a matched native control, then real NGX output
is checked before/after the coverage boundary. This is not a speed/convergence
claim: full-resolution raw tracing continues and the neural input alone shrinks.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,sys
import numpy as np


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


def sha(a):return hashlib.sha256(a.tobytes()).hexdigest()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--case',choices=['opaque','cutout','glass','null','background','holdout','holdout-edge'],required=True);p.add_argument('--native-only',action='store_true');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    here=Path(__file__).parent;coverage=module('canonical_ref',here/'dlss_coverage_reference_test.py');view=module('canonical_view',here/'dlss_image_pipeline_test.py');d=module('canonical_backend',Path(os.environ['SLC_DLSS_TEST_ADDON'])/'engine/dlss.py')
    material='opaque' if args.case=='background' else 'holdout' if args.case=='holdout-edge' else args.case
    background=args.case=='background';base_fixture=coverage.fixture
    def fixture():
        scene=base_fixture(material,background)
        if args.case=='holdout-edge':
            scene.UpdateObjectTransformation('wall',[.02,0,0,0, 0,1,0,0, 0,0,.02,0, 0,0,0,1])
        return scene,None,None
    view.m.fixture=fixture;view.s.Init();size=(384,216)
    config='renderengine.seed=131\nrtpath.denoisingframes.haltspp=1\nrtpath.denoisingframes.lossless=1\nscene.epsilon.min=0.00001\nscene.epsilon.max=0.1\npath.shadowterminator=chiang\nopencl.task.count=8192\npathocl.wavefront=off\n'
    control,raw_control=view.render_frame(config,capture=True,size=size)
    frame,raw=view.render_frame(config+'rtpath.denoisingframes.input.reduction=2\n',capture=True,size=size)
    assert frame['accumulated_eye_samples']==control['accumulated_eye_samples']==1
    np.savez_compressed(args.out/'producer-diagnostic.npz',source=frame['color'],target_raw=raw,control=raw_control,target_alpha=frame.get('target_alpha'),jitter=np.asarray(frame['jitter']))
    np.testing.assert_array_equal(raw,raw_control)
    assert frame['color'].shape==(108,192,4) and frame['target_size']==size
    np.testing.assert_array_equal(frame['color'],raw[1::2,1::2])
    np.testing.assert_array_equal(frame['target_alpha'],raw[:,:,3])
    assert not frame['target_alpha'].flags.writeable and not frame['target_holdout'].flags.writeable
    assert frame['input_reduction']==2 and frame['coverage_source']=='renderer_full_resolution'
    np.testing.assert_array_equal(view.s.DenoisingImagePipeline().process(frame),raw)
    projection_error=None
    if args.case in ['opaque','holdout','glass']:
        xyz=frame['guides'][:,:,12:15];f=size[0]/(2*np.tan(np.deg2rad(45)/2));h,w=frame['color'].shape[:2]
        yy,xx=np.meshgrid(np.arange(h)+.5+frame['jitter'][1],np.arange(w)+.5+frame['jitter'][0],indexing='ij')
        px=(size[0]/2+f*xyz[:,:,0]/(xyz[:,:,1]+5))/2;py=(size[1]/2+f*xyz[:,:,2]/(xyz[:,:,1]+5))/2
        projection_error=float(max(np.abs(px-xx).max(),np.abs(py-yy).max()));assert projection_error<1e-3,projection_error
    if args.native_only:
        report={'case':args.case,'native_sha256':hashlib.file_digest(view.m.native_path().open('rb'),'sha256').hexdigest(),'device':os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU'),'source_size':[192,108],'target_size':size,'raw_control_bit_exact':True,'source_subgrid_bit_exact':True,'target_alpha_bit_exact':True,'native_imagepipeline_bit_exact':True,'source_projection_max_pixels':projection_error,'guide_status':np.unique(frame['guides'][:,:,7]).tolist(),'target_holdout_pixels':int(np.count_nonzero(frame['target_holdout'])),'scope':'Actual native producer and canonical presentation; no NVIDIA inference on this device.'}
        (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True);raise SystemExit(0)
    names=['color','guides','sample_count','target_alpha','target_holdout'];names += ['target_holdout_rgb'] if 'target_holdout_rgb' in frame else []
    before={n:sha(frame[n]) for n in names}
    class Observed(d.CUDADLSS):
        def process(self,packet):
            result=super().process(packet);self.vendor=result.copy();return result
    with Observed(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SUPERLUXCORE_DLSS_CACHE'],library=os.environ['SLC_DLSS_TEST_LIBRARY']) as b:
        image=d.RendererDLSS(b).process(frame)
        np.testing.assert_array_equal(image[:,:,3],raw[:,:,3])
        mask=frame['target_holdout']!=0
        if np.any(mask):np.testing.assert_array_equal(image[:,:,:3][mask],frame['target_holdout_rgb'][mask])
        np.testing.assert_array_equal(image[:,:,:3][~mask],b.vendor[:,:,:3][~mask])
        output=view.s.DenoisingImagePipeline().process(frame,image)
        np.testing.assert_array_equal(output,image)
        # Native pipeline also enforces its owned alpha if a caller supplies
        # the original wrong SDK alpha instead of the corrected consumer image.
        direct=view.s.DenoisingImagePipeline().process(frame,b.vendor)
        np.testing.assert_array_equal(direct[:,:,3],raw[:,:,3])
        assert all(sha(frame[n])==v for n,v in before.items())
        report={'case':args.case,'native_sha256':hashlib.file_digest(view.m.native_path().open('rb'),'sha256').hexdigest(),'source_size':[192,108],'target_size':size,'raw_control_bit_exact':True,'source_subgrid_bit_exact':True,'target_alpha_bit_exact':True,'source_projection_max_pixels':projection_error,'guide_status':np.unique(frame['guides'][:,:,7]).tolist(),'target_holdout_pixels':int(mask.sum()),'vendor_alpha_max_error':float(np.max(np.abs(b.vendor[:,:,3]-raw[:,:,3]))),'resolved_alpha_max_error':float(np.max(np.abs(image[:,:,3]-raw[:,:,3]))),'nonholdout_vendor_rgb_bit_exact':True,'inputs_unchanged':True,'stats':b.stats(),'scope':__doc__}
        np.savez_compressed(args.out/'pixels.npz',source=frame['color'],target_raw=raw,output=image,vendor=b.vendor,holdout=frame['target_holdout'],jitter=np.asarray(frame['jitter']))
        (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
