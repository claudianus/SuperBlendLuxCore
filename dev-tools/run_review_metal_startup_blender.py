"""Bounded real-scene GUI + 720p F12 verification with process/RSS receipts."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];WORK=ROOT.parent
BASE=WORK/'test-scenes/validation-2026-10-16/metal-startup'
OUT=WORK/'dev-tools/reviews/2026-10-16/metal-startup'
matrix=OUT/'blender-matrix.json';records=json.loads(matrix.read_text()) if matrix.exists() else []
selected=os.environ.get('SLC_STARTUP_CASES','heavy-cpu,heavy-ocl,render-cpu,render-ocl').split(',')
shared=os.environ.get('SLC_ALLOW_SHARED_VALIDATION')=='1'
for name in selected:
    mode,dev=name.split('-');dev=dev.upper();directory=BASE/name;directory.mkdir(parents=True,exist_ok=True)
    quiet_since=None;wait_started=time.monotonic()
    while True:
        admission=subprocess.run(['ps','-axo','pid,ppid,%cpu,rss,command'],capture_output=True,text=True,check=True).stdout
        busy=[line for line in admission.splitlines() if 'Blender.app/Contents/MacOS/Blender' in line
            or (('MTLCompilerService' in line or 'mds_stores' in line) and float(line.split(None,4)[2])>30)]
        now=time.monotonic()
        # Explicit user override permits concurrent correctness checks.
        # Always exclude those runs from performance comparisons.
        if shared:break
        if busy:quiet_since=None
        elif quiet_since is None:quiet_since=now
        if quiet_since is not None and now-quiet_since>=30:break
        if now-wait_started>int(os.environ.get('SLC_ADMISSION_TIMEOUT','900')):
            raise RuntimeError('no 30-second exclusive admission window')
        time.sleep(2)
    (OUT/(name+'-admission.txt')).write_text(admission)
    blockers=[line for line in admission.splitlines() if 'Blender.app/Contents/MacOS/Blender' in line
        or (('MTLCompilerService' in line or 'mds_stores' in line) and float(line.split(None,4)[2])>30)]
    if blockers and not shared:raise RuntimeError('resource contention: '+str(blockers))
    env={**os.environ,'BLENDER_USER_RESOURCES':str(BASE/'profile'),'DEV':dev,
        'SLC_CANDIDATE_IDENTITY':str(OUT/'candidate-identity.json'),'SUPERLUXCORE_AUDIT_DIR':str(directory),'SLC_BLENDER_MODE':'render'}
    args=['/Applications/Blender.app/Contents/MacOS/Blender','--factory-startup']
    if mode=='heavy':args += ['/Users/modumaru/Downloads/thejunkshopsplashscreen.blend']
    elif mode=='render':args += ['-b']
    if mode=='optional':
        env.update(SLC_REVIEW_MODULE_ROOT=str(BASE/'profile/extensions/.local/lib/python3.13/site-packages'),SLC_REVIEW_OUT=str(OUT))
        args=['python3.13',str(WORK/'SuperLuxCore/dev-tools/review_optional_gpu_test.py')]
    else:
        script={'heavy':'review_heavy_viewport_test.py','viewport':'review_viewport_blender_test.py','render':'review_blender_test.py'}[mode]
        args += ['--python-exit-code','1','--python',str(ROOT/'dev-tools'/script)]
    log_path=OUT/(name+'.log')
    if log_path.exists():log_path.rename(OUT/(name+f'-attempt-{len(records)}.log'))
    result_path=OUT/'optional-gpu.json' if mode=='optional' else directory/({'heavy':'heavy-viewport.json','viewport':'viewport-result.json','render':'review-render.json'}[mode])
    if result_path.exists():result_path.rename(OUT/(name+f'-attempt-{len(records)}.json'))
    print('RUN',name,flush=True);start=time.monotonic();peak=0;reason=None;contention=[]
    with tempfile.TemporaryDirectory(prefix='slc-heavy-blender-') as scratch:
        env['TMPDIR']=scratch
        with log_path.open('w') as log:
            p=subprocess.Popen(args,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while p.poll() is None:
                    snapshot=subprocess.run(['ps','-o','rss=','-p',str(p.pid)],text=True,capture_output=True,check=False)
                    if snapshot.stdout.strip():peak=max(peak,int(snapshot.stdout.strip()))
                    activity=subprocess.run(['ps','-axo','pid,%cpu,command'],text=True,capture_output=True,check=True).stdout
                    for line in activity.splitlines():
                        fields=line.split(None,2)
                        if len(fields)==3 and fields[0].isdigit() and int(fields[0])!=p.pid and ('Blender.app/Contents/MacOS/Blender' in fields[2] or ('mds_stores' in fields[2] and float(fields[1])>30)):
                            contention.append({'seconds':time.monotonic()-start,'process':line})
                    if not shared and any('Blender.app/Contents/MacOS/Blender' in c['process'] for c in contention):
                        reason='external renderer during exclusive validation';break
                    if peak>22*1024*1024:reason='Blender RSS exceeded 22 GiB';break
                    if time.monotonic()-start>(600 if mode=='heavy' else 240):reason='deadline exceeded';break
                    time.sleep(1)
            finally:
                if p.poll() is None:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=8)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                else:p.wait()
        crash=Path(scratch)/'blender.crash.txt'
        if crash.exists():(OUT/(name+f'-crash-{len(records)}.txt')).write_bytes(crash.read_bytes())
    result=json.loads(result_path.read_text()) if result_path.exists() else {}
    complete=all(r.get('status')=='passed' for r in result) and len(result)==3 if isinstance(result,list) else result.get('status','passed')=='passed'
    passed=p.returncode==0 and bool(result) and complete
    row={'case':name,'returncode':p.returncode,'passed':passed,
        'seconds':time.monotonic()-start,'peak_blender_rss_mib':peak/1024,'termination_reason':reason,
        'performance_eligible':passed and not shared and not contention,'shared_validation_authorized':shared,'contention':contention}
    records.append(row);matrix.write_text(json.dumps(records,indent=2)+'\n')
    print({**{k:v for k,v in row.items() if k!='contention'},'contention_samples':len(contention)},flush=True)
