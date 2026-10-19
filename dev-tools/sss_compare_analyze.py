"""Linear/raw convergence against independent, model-specific references."""
import argparse
import json
from pathlib import Path
import numpy as np

ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True)
ap.add_argument('--references',type=Path)
ap.add_argument('--allow-legacy-conditions',action='store_true',help='Analyze historical non-v2 settings explicitly; not an unclamped/unregularized comparison')
a=ap.parse_args();root=a.evidence.resolve();reference_root=(a.references or root).resolve()
references={engine:np.load(reference_root/directory/'linear.npy').astype(np.float64)
            for engine,directory in [('SUPERLUXCORE','reference-native-prelim'),('CYCLES','reference-cycles')]}
def require_contract(record,source):
    if a.allow_legacy_conditions:return
    if record.get('comparison_contract')!='sss-unregularized-v2':
        ap.error('Input lacks the unregularized-v2 contract: '+str(source)+
                 '. Use --allow-legacy-conditions only for historical analysis.')
    if not record.get('authored_scene_sha256'):
        ap.error('Authored scene fingerprint is missing: '+str(source))
    controls=record.get('raw_controls',{})
    if controls.get('denoising') is not False or controls.get('adaptive_sampling') is not False:
        ap.error('Raw sample controls are missing/enabled: '+str(source))
    if record['engine']=='SUPERLUXCORE':
        values=record.get('native_fidelity',{})
        keys=['path.regularization.sigma','path.regularization.halflife','path.filterglossy',
              'path.clamping.cycles.direct','path.clamping.cycles.indirect','path.clamping.variance.maxvalue']
    else:
        values=record.get('cycles_fidelity',{})
        keys=['filter_glossy','clamp_direct','clamp_indirect','fast_gi','denoising','adaptive_sampling']
    if record['engine']=='CYCLES' and any(values.get(key) is not True for key in ['caustics_reflective','caustics_refractive']):
        ap.error('Cycles caustic paths disabled/missing: '+str(source))
    if any(key not in values or values[key]!=0 for key in keys):
        ap.error('Blur/clamp/fidelity controls are missing/enabled: '+str(source))

if not a.allow_legacy_conditions:
    for directory in ['reference-native-prelim','reference-cycles']:
        record=json.loads((reference_root/directory/'result.json').read_text())
        require_contract(record,reference_root/directory/'result.json')
native_meta=json.loads((reference_root/'reference-native-prelim/result.json').read_text())
cycles_meta=json.loads((reference_root/'reference-cycles/result.json').read_text())
if not a.allow_legacy_conditions and native_meta['authored_scene_sha256']!=cycles_meta['authored_scene_sha256']:
    ap.error('Reference authored scenes differ')
regions=np.load(reference_root/'regions.npy' if (reference_root/'regions.npy').exists() else reference_root/'quality-new-64-s17/regions.npy')
masks={'whole':regions>=0,'bulk':(regions>0)&(regions<=3),'thin':regions>3,'sss':regions>0}
rows={}
for record_path in root.glob('*/result.json'):
    record=json.loads(record_path.read_text());image_path=record_path.with_name('linear.npy')
    if not image_path.exists() or record.get('spectral') or record.get('engine') not in references:continue
    image=np.load(image_path).astype(np.float64)
    if image.shape!=references[record['engine']].shape:continue
    require_contract(record,record_path)
    if not a.allow_legacy_conditions and record['authored_scene_sha256']!=native_meta['authored_scene_sha256']:
        ap.error('Authored scene differs from reference: '+str(record_path))
    reference=references[record['engine']]
    rows[record_path.parent.name]=dict(seconds=record['seconds'],spp=record['spp'],seed=record['seed'],
        engine=record['engine'],native_sha256=record['native_sha256'],
        regions={name:dict(rmse=float(np.sqrt(np.mean((image[mask]-reference[mask])**2))),
                          relative_rmse=float(np.sqrt(np.mean((image[mask]-reference[mask])**2)/
                                                    np.mean(reference[mask]**2))))
                 for name,mask in masks.items()})
spectral={}
for prefix,spp in [('spectral-base',64),('spectral-near-time-base',81),('spectral-thick-quality',100)]:
    directories=[root/f'{prefix}-{spp}-s{seed}' for seed in (17,53,97)]
    if prefix=='spectral-base':directories[0]=root/'wheel-spectral'
    if not all((p/'linear.npy').exists() for p in directories):continue
    images=np.stack([np.load(p/'linear.npy').astype(np.float64) for p in directories])
    spectral[prefix]=dict(spp=spp,seeds=[17,53,97],
        seconds=[json.loads((p/'result.json').read_text())['seconds'] for p in directories],
        regions={name:dict(interseed_variance=float(images[:,mask].var(axis=0,ddof=1).mean()),
                          mean_rgb=images[:,mask].mean(axis=(0,1)).tolist()) for name,mask in masks.items()})
native_reference=json.loads((reference_root/'reference-native-prelim/result.json').read_text())
cycles_reference=json.loads((reference_root/'reference-cycles/result.json').read_text())
result=dict(reference_contract={'native_requested_seed':native_reference['seed'],
    'native_effective_legacy_sequence':131 if a.allow_legacy_conditions else None,
    'cycles_seed':cycles_reference['seed'],'spp':native_reference['spp'],'finite_reference_has_noise':True,
    'models':'OpenPBR refractive bulk vs Cycles nonlocal BSSRDF; each uses its own reference',
    'timings':'Shared workstation. Functional/overlapped runs are not performance ratios.',
    'comparison_contract':'legacy-conditions' if a.allow_legacy_conditions else 'sss-unregularized-v2'},
    rgb=rows,spectral=spectral)
(root/'convergence.json').write_text(json.dumps(result,indent=2))
for name in ['quality-new-64-s17','quality-local-rr-256-s17','quality-new-256-s17',
             'guided-thick-quality-100-s17','final-time-rgb-base-a','final-time-rgb-guide-a']:
    if name in rows:print(name,rows[name]['seconds'],rows[name]['regions']['sss']['rmse'])
