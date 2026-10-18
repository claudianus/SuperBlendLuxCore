"""Linear/raw convergence against independent, model-specific references."""
import argparse
import json
from pathlib import Path
import numpy as np

ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True)
ap.add_argument('--references',type=Path)
a=ap.parse_args();root=a.evidence.resolve();reference_root=(a.references or root).resolve()
references={engine:np.load(reference_root/directory/'linear.npy').astype(np.float64)
            for engine,directory in [('SUPERLUXCORE','reference-native-prelim'),('CYCLES','reference-cycles')]}
regions=np.load(reference_root/'quality-new-64-s17/regions.npy')
masks={'whole':regions>=0,'bulk':(regions>0)&(regions<=3),'thin':regions>3,'sss':regions>0}
rows={}
for record_path in root.glob('*/result.json'):
    record=json.loads(record_path.read_text());image_path=record_path.with_name('linear.npy')
    if not image_path.exists() or record.get('spectral') or record.get('engine') not in references:continue
    image=np.load(image_path).astype(np.float64)
    if image.shape!=references[record['engine']].shape:continue
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
result=dict(reference_contract={'native_requested_seed':181,'native_effective_legacy_sequence':131,
    'cycles_seed':181,'spp':4096,'finite_reference_has_noise':True,
    'models':'OpenPBR refractive bulk vs Cycles nonlocal BSSRDF; each uses its own reference',
    'timings':'Shared workstation. Functional/overlapped runs are not performance ratios.'},
    rgb=rows,spectral=spectral)
(root/'convergence.json').write_text(json.dumps(result,indent=2))
for name in ['quality-new-64-s17','quality-local-rr-256-s17','quality-new-256-s17',
             'guided-thick-quality-100-s17','final-time-rgb-base-a','final-time-rgb-guide-a']:
    if name in rows:print(name,rows[name]['seconds'],rows[name]['regions']['sss']['rmse'])
