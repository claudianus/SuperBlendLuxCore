"""Reject measured images that cannot support the raw SSS comparison claim."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import numpy as np

analyzer=Path(__file__).with_name('sss_compare_analyze.py')
native=dict(comparison_contract='sss-unregularized-v2',authored_scene_sha256='same-scene',
            raw_controls=dict(denoising=False,adaptive_sampling=False),engine='SUPERLUXCORE',
            native_fidelity={k:0. for k in ['path.regularization.sigma','path.regularization.halflife',
                'path.filterglossy','path.clamping.cycles.direct','path.clamping.cycles.indirect','path.clamping.variance.maxvalue']},
            spectral=False,seconds=1.,spp=4096,seed=181,native_sha256='test-library')
cycles=copy.deepcopy(native);cycles['engine']='CYCLES';del cycles['native_fidelity']
cycles['cycles_fidelity']=dict(filter_glossy=0.,clamp_direct=0.,clamp_indirect=0.,fast_gi=False,
                              denoising=False,adaptive_sampling=False,caustics_reflective=True,caustics_refractive=True)
cases=[('valid',None,True),('legacy-contract',lambda r:r.pop('comparison_contract'),False),
       ('missing-scene',lambda r:r.pop('authored_scene_sha256'),False),
       ('changed-scene',lambda r:r.update(authored_scene_sha256='other-scene'),False),
       ('native-blur',lambda r:r['native_fidelity'].update({'path.regularization.sigma':.03}),False),
       ('native-clamp',lambda r:r['native_fidelity'].update({'path.clamping.cycles.indirect':10.}),False),
       ('denoised',lambda r:r['raw_controls'].update(denoising=True),False),
       ('adaptive',lambda r:r['raw_controls'].update(adaptive_sampling=True),False)]
with tempfile.TemporaryDirectory(prefix='sss-contract-') as folder:
    root=Path(folder)
    np.save(root/'regions.npy',np.array([[0,1],[2,4]],np.uint8))
    for name,record in [('reference-native-prelim',native),('reference-cycles',cycles),('candidate',native)]:
        d=root/name;d.mkdir();np.save(d/'linear.npy',np.ones((2,2,3),np.float32))
        (d/'result.json').write_text(json.dumps(record))
    def run(name,expected,allow_legacy=False):
        command=[sys.executable,str(analyzer),'--evidence',str(root)]
        if allow_legacy:command.append('--allow-legacy-conditions')
        result=subprocess.run(command,capture_output=True,text=True,timeout=20)
        assert (result.returncode==0)==expected,(name,result.stderr)
        print(name,'PASS',flush=True)
    for name,mutate,expected in cases:
        r=copy.deepcopy(native)
        if mutate:mutate(r)
        (root/'candidate/result.json').write_text(json.dumps(r));run(name,expected)
    (root/'candidate/result.json').write_text(json.dumps(native))
    for key,value in [('filter_glossy',1.),('clamp_indirect',10.),('caustics_refractive',False)]:
        r=copy.deepcopy(cycles);r['cycles_fidelity'][key]=value
        (root/'reference-cycles/result.json').write_text(json.dumps(r));run('cycles-'+key,False)
    run('explicit-historical-analysis',True,allow_legacy=True)
print('12 comparison contract checks passed')
