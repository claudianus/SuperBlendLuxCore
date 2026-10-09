"""외부 Cycles 제작 장면을 수정 없이 불러와 720p RGB 비교 증거를 저장한다."""
import argparse
import json
from pathlib import Path
import time
import bpy
import numpy as np
parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--samples',type=int,default=128)
import sys
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);args.output.mkdir(parents=True,exist_ok=True)
try:bpy.context.scene.render.engine='SUPERLUXCORE'
except TypeError:bpy.ops.preferences.addon_enable(module='superluxcore')
results=[]
for path in sorted(args.source.glob('*/*.blend')):
    bpy.ops.wm.open_mainfile(filepath=str(path));s=bpy.context.scene
    s.render.resolution_x=1280;s.render.resolution_y=720;s.render.resolution_percentage=100
    s.cycles.samples=args.samples;s.cycles.use_denoising=False;s.cycles.sample_clamp_direct=0;s.cycles.sample_clamp_indirect=0
    images={}
    for engine in ('CYCLES','SUPERLUXCORE'):
        s.render.engine=engine
        if engine=='SUPERLUXCORE':
            bpy.ops.superluxcore.import_cycles_settings();cfg=s.superluxcore;cfg.config.engine='PATH';cfg.config.device='OCL';cfg.config.spectral_enable=False
            cfg.config.path.use_clamping=False;cfg.config.path.auto_clamping=False;cfg.denoiser.enabled=False
            cfg.halt.enable=True;cfg.halt.use_time=False;cfg.halt.use_noise_thresh=False;cfg.halt.use_samples=True;cfg.halt.samples=args.samples
            s.camera.data.superluxcore.imagepipeline.tonemapper.enabled=False
        s.render.image_settings.file_format='OPEN_EXR';s.render.image_settings.color_depth='32';s.render.filepath=str(args.output/(path.stem+'_'+engine+'.exr'))
        start=time.monotonic();bpy.ops.render.render(write_still=True);elapsed=time.monotonic()-start
        im=bpy.data.images.load(s.render.filepath,check_existing=False);rgb=np.array(im.pixels[:],dtype=np.float32).reshape(720,1280,4)[...,:3];bpy.data.images.remove(im)
        assert np.isfinite(rgb).all(),(path.stem,engine,'비유한 픽셀')
        images[engine]=rgb
        s.render.image_settings.file_format='PNG';s.render.image_settings.color_depth='8';bpy.data.images['Render Result'].save_render(str(args.output/(path.stem+'_'+engine+'.png')),scene=s)
        print('제작 장면 렌더',path.stem,engine,elapsed,flush=True)
    cy=images['CYCLES'];lx=images['SUPERLUXCORE'];lum=np.array((.2126,.7152,.0722));cyl=cy@lum;lxl=lx@lum
    record={'scene':path.stem,'samples':args.samples,'resolution':[1280,720],'cycles_luminance':float(cyl.mean()),'superluxcore_luminance':float(lxl.mean()),'ratio':float(lxl.mean()/max(cyl.mean(),1e-12)),'normalized_rmse':float(np.sqrt(np.mean((lx-cy)**2))/max(np.sqrt(np.mean(cy**2)),1e-12))}
    results.append(record);(args.output/'metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');print('제작 장면 비교',json.dumps(record,ensure_ascii=False),flush=True)
print('제작 장면',len(results),'쌍 저장 완료',flush=True)
