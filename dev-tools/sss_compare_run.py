"""Sequential stock-Blender CPU SSS controls with owned-child cleanup.

ABBA uses seed 131: the old tile sampler ignored the requested engine seed
and always used this legacy sequence. Quality runs accept independent seeds,
scrambled by the repaired sampler. No denoising, clamping or adaptive sampling.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ap=argparse.ArgumentParser()
ap.add_argument('--evidence',type=Path,required=True)
ap.add_argument('--mode',choices=['abba','quality','guided-grid','guided-quality','candidate-quality','production-time','cycles-quality'],required=True)
ap.add_argument('--threads',type=int,default=4)
ap.add_argument('--samples',type=int,nargs='+',default=[64,256])
ap.add_argument('--seeds',type=int,nargs='+',default=[17])
ap.add_argument('--timeout',type=int,default=600)
ap.add_argument('--guided-package',default='guided-grid-package')
ap.add_argument('--candidate-package',default='candidate-package')
ap.add_argument('--label-prefix',default='guided-quality')
ap.add_argument('--spectral',action='store_true')
a=ap.parse_args()
root=Path(__file__).resolve().parents[2]
evidence=a.evidence.resolve()
benchmark=Path(__file__).with_name('sss_matched_benchmark.py')
blender='/Applications/Blender.app/Contents/MacOS/Blender'
profile=evidence/'isolated-profile'
assert profile.is_dir(),profile

def processes():
    result=subprocess.run(['ps','-axo','pid,ppid,pcpu,rss,comm'],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,'Process admission unavailable'
    rows=[]
    for line in result.stdout.splitlines()[1:]:
        pid,ppid,cpu,rss,command=line.split(None,4)
        rows.append(dict(pid=int(pid),ppid=int(ppid),cpu=float(cpu),rss_kib=int(rss),command=command))
    return rows

plan=[]
if a.mode=='abba':
    plan=[('before-a','baseline',64,131,False),('after-a','candidate',64,131,False),
          ('after-b','candidate',64,131,False),('before-b','baseline',64,131,False)]
elif a.mode=='guided-grid':
    plan=[(f'guided-grid-c{c}-f{f}-s17',f'guided-{c}-{f}',64,17,False)
          for c,f in [(.1,.99),(.1,.5),(.5,.99)]]
elif a.mode=='guided-quality':
    plan=[(f'{a.label_prefix}-{spp}-s{seed}','guided-0.1-0.99',spp,seed,False)
          for spp in a.samples for seed in a.seeds]
elif a.mode=='candidate-quality':
    plan=[(f'{a.label_prefix}-{spp}-s{seed}','candidate',spp,seed,False)
          for spp in a.samples for seed in a.seeds]
elif a.mode=='cycles-quality':
    plan=[(f'{a.label_prefix}-{spp}-s{seed}','cycles',spp,seed,False)
          for spp in a.samples for seed in a.seeds]
elif a.mode=='production-time':
    base=81 if a.spectral else 64
    plan=[(a.label_prefix+'-base-a','prod-classic',base,17,False),
          (a.label_prefix+'-guide-a','prod-guide',100,17,False),
          (a.label_prefix+'-guide-b','prod-guide',100,17,False),
          (a.label_prefix+'-base-b','prod-classic',base,17,False)]
else:
    for spp in a.samples:
        for seed in a.seeds:
            plan.extend([(f'quality-new-{spp}-s{seed}','candidate',spp,seed,False),
                         (f'quality-local-rr-{spp}-s{seed}','candidate',spp,seed,True),
                         (f'quality-cycles-{spp}-s{seed}','cycles',spp,seed,False)])
rows=[]
for label,variant,spp,seed,legacy in plan:
    output=evidence/label
    assert not output.exists(),f'Refusing to replace completed evidence: {output}'
    admitted=processes()
    foreign=[p for p in admitted if p['command'].endswith('/Blender')]
    assert not foreign, f'Another Blender render is active: {foreign}'
    environment=os.environ.copy()
    for key in list(environment):
        if key.startswith('SUPERLUXCORE_SSS_'):del environment[key]
    environment.update(BLENDER_USER_RESOURCES=str(profile),SLC_SSS_OUT=str(output),
        BLENDER_USER_CONFIG=str(profile/'config'),BLENDER_USER_EXTENSIONS=str(profile/'extensions'),
        SLC_SSS_NATIVE_ROOT=str(evidence/('production-package' if variant.startswith('prod-') else
                                        a.guided_package if variant.startswith('guided-') else
                                        'baseline-package' if variant=='baseline' else a.candidate_package)),
        SLC_SSS_ENGINE='CYCLES' if variant=='cycles' else 'SUPERLUXCORE',
        SLC_SSS_SIZE='320,180',SLC_SSS_SAMPLES=str(spp),SLC_SSS_THREADS=str(a.threads),
        SLC_SSS_SPECTRAL='1' if a.spectral else '0',SLC_SSS_SEED=str(seed))
    if legacy:environment['SUPERLUXCORE_SSS_LEGACY_RR']='1'
    if variant.startswith('prod-'):environment['SLC_SSS_GUIDING']='0' if variant=='prod-classic' else '1'
    if variant.startswith('guided-'):
        _,classic,forward=variant.split('-')
        environment.update(SUPERLUXCORE_SSS_DWIVEDI='1',SUPERLUXCORE_SSS_DWIVEDI_CLASSIC=classic,
                           SUPERLUXCORE_SSS_DWIVEDI_FORWARD=forward)
    started=time.monotonic()
    with (evidence/(label+'.log')).open('w') as log:
        process=subprocess.Popen([blender,'-b','--factory-startup','--python-exit-code','1','--python',str(benchmark)],
            cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            code=process.wait(timeout=a.timeout)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
    assert code==0,(label,code)
    result=json.loads((output/'result.json').read_text())
    result.update(label=label,process_wall_seconds=time.monotonic()-started,
                  admission=admitted,host_scope='shared workstation; not dedicated hardware')
    rows.append(result)
    receipt_prefix=a.label_prefix if a.mode in ('guided-quality','candidate-quality','production-time','cycles-quality') else a.mode
    (evidence/(receipt_prefix+'-'+str(a.samples[0])+'-s'+str(a.seeds[0])+'-runs.json')).write_text(json.dumps(rows,indent=2))
    print(label,result['seconds'],flush=True)
