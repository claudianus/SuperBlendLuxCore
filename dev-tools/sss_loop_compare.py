"""Run an explicit SSS experiment plan sequentially in an isolated Blender profile.

Plan entries: label, package, spp, seed, engine, spectral, fastloop, guiding.
Native packages and the profile must be explicitly prepared. Preserve raw evidence;
reap the owned process group on timeout/error, never mutate the user's profile.
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
ap.add_argument('--plan',type=Path,required=True)
ap.add_argument('--threads',type=int,default=4)
ap.add_argument('--timeout',type=int,default=600)
ap.add_argument('--admission-wait',type=float,default=0)
a=ap.parse_args();evidence=a.evidence.resolve();profile=evidence/'isolated-profile'
root=Path(__file__).resolve().parents[2]
assert profile.is_dir(),profile
plan=json.loads(a.plan.read_text());runs=[]
for entry in plan:
    label=entry['label'];assert Path(label).name==label
    output=evidence/label;assert not output.exists(),output
    admitted_at=time.monotonic();deadline=admitted_at+max(0,a.admission_wait)
    while True:
        inventory=subprocess.run(['ps','-axo','pid,ppid,pcpu,rss,comm'],capture_output=True,text=True,timeout=5)
        assert inventory.returncode==0,'Resource admission unavailable'
        active=[line.strip() for line in inventory.stdout.splitlines()[1:]
                if line.rstrip().endswith('/Blender')]
        if not active:break
        assert time.monotonic()<deadline,active
        time.sleep(min(1,max(.01,deadline-time.monotonic())))
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('SUPERLUXCORE_SSS_','SLC_SSS_')):del env[key]
    env.update(BLENDER_USER_RESOURCES=str(profile),BLENDER_USER_CONFIG=str(profile/'config'),
        BLENDER_USER_EXTENSIONS=str(profile/'extensions'),SLC_SSS_OUT=str(output),
        SLC_SSS_NATIVE_ROOT=str(evidence/entry['package']),SLC_SSS_ENGINE=entry.get('engine','SUPERLUXCORE'),
        SLC_SSS_SIZE='320,180',SLC_SSS_THREADS=str(a.threads),SLC_SSS_SAMPLES=str(entry['spp']),
        SLC_SSS_SEED=str(entry.get('seed',17)),SLC_SSS_SPECTRAL=str(int(entry.get('spectral',False))))
    for field,key in [('fastloop','SLC_SSS_FASTLOOP'),('guiding','SLC_SSS_GUIDING')]:
        if field in entry:env[key]=str(int(entry[field]))
    for key,value in entry.get('diagnostics',{}).items():
        assert key.startswith('SUPERLUXCORE_SSS_');env[key]=str(value)
    started=time.monotonic()
    with (evidence/(label+'.log')).open('w') as log:
        process=subprocess.Popen(['/Applications/Blender.app/Contents/MacOS/Blender','-b','--factory-startup',
            '--python-exit-code','1','--python',str(Path(__file__).with_name('sss_matched_benchmark.py'))],
            cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:code=process.wait(timeout=a.timeout)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
    assert code==0,(label,code)
    result=json.loads((output/'result.json').read_text())
    runs.append(dict(plan=entry,result=result,process_wall_seconds=time.monotonic()-started,
        child_pid=process.pid,child_reaped=True,admission_wait_seconds=started-admitted_at,admission=inventory.stdout,
        performance_scope='Shared workstation; sequential owned renders; render wall includes prep/EXR'))
    (evidence/(a.plan.stem+'-runs.json')).write_text(json.dumps(runs,indent=2))
    print(label,result['seconds'],flush=True)
