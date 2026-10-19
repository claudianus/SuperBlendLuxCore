"""Execute production view_draw error recovery with the real worker/owner lock.

Native Stop/reader calls are modeled. This checks Python ownership/ordering,
not actual GPU crash resolution. The source can be an exact frozen release.
"""
import argparse,ast,contextlib,hashlib,io,json,threading,time,traceback,weakref
from collections import deque
from pathlib import Path
from types import SimpleNamespace as NS

class OwnerLock:
    def __init__(self):self.lock=threading.Lock();self.owner=None
    def acquire(self,*a,**kw):
        acquired=self.lock.acquire(*a,**kw)
        if acquired:self.owner=threading.get_ident()
        return acquired
    def release(self):self.owner=None;self.lock.release()
    def __enter__(self):self.acquire();return self
    def __exit__(self,*args):self.release()

def main():
    parser=argparse.ArgumentParser();root=Path(__file__).resolve().parents[1]
    parser.add_argument('--source',type=Path,default=root/'engine/base.py');parser.add_argument('--worker-source',type=Path,default=root/'engine/session_worker.py');parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    worker_tree=ast.parse(a.worker_source.read_text());worker_node=next(n for n in worker_tree.body if isinstance(n,ast.ClassDef) and n.name=='SessionWorker')
    env=dict(threading=threading,deque=deque,weakref=weakref,time=time,traceback=traceback)
    exec(compile(ast.Module(body=[worker_node],type_ignores=[]),str(a.worker_source),'exec'),env);Worker=env['SessionWorker']
    base=ast.parse(a.source.read_text());cls=next(n for n in base.body if isinstance(n,ast.ClassDef) and n.name=='SuperLuxCoreRenderEngine');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='view_draw')
    draw=NS(view_draw=lambda *args:None);scope=dict(viewport=draw)
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(a.source),'exec'),scope)
    class Engine:
        view_draw=scope['view_draw']
        def update_stats(self,*args):self.errors.append(args)
    records=[]
    for case in ['readback_busy','OIDN_busy','scene_edit_busy','worker_idle','no_error','legacy_started','legacy_stopped']:
        lock=OwnerLock();engine=Engine();engine.session_lock=lock;engine.errors=[];engine.exporter=object();worker=None;reader=None;release=threading.Event();entered=threading.Event();stops=[];violations=[]
        class Session:
            def __init__(self):self.started=case!='legacy_stopped'
            def IsStarted(self):return self.started
            def Stop(self):
                stops.append(dict(thread=threading.current_thread().name,owner=lock.owner))
                if worker is not None and lock.owner!=threading.get_ident():violations.append('Stop bypassed the session owner lock')
                self.started=False
        session=Session();engine.session=session
        if not case.startswith('legacy'):
            worker=Worker(engine);engine.session_worker=worker;worker.session=session
        else:engine.session_worker=None
        def read():
            with lock:
                entered.set();assert release.wait(3),'Reader release deadline'
        try:
            if case.endswith('_busy'):
                reader=threading.Thread(target=read,name='Blocked-'+case);reader.start();assert entered.wait(2)
            def render(*unused):
                if case!='no_error':raise RuntimeError('Injected viewport draw failure')
            draw.view_draw=render
            before=time.monotonic()
            with contextlib.redirect_stderr(io.StringIO()):engine.view_draw(None,None)
            elapsed=time.monotonic()-before
            healthy_session_preserved=engine.session is session and engine.exporter is not None and not stops
            returned_while_owner_busy=reader is not None and not release.is_set()
            release.set()
            if reader is not None:reader.join(2);assert not reader.is_alive()
            if worker is not None:
                deadline=time.monotonic()+2
                while case!='no_error' and (worker.session is not None or engine.session is not None) and time.monotonic()<deadline:time.sleep(.002)
                worker.shutdown();worker._thread.join(2);assert not worker._thread.is_alive()
            before_shutdown=[s for s in stops] if case!='no_error' else []
            checks=dict(no_stop_outside_owner_lock=not violations,
                        worker_owns_recovery_stop=worker is None or case=='no_error' or len(before_shutdown)==1 and all(s['thread']=='SuperLuxCoreSessionWorker' for s in before_shutdown),
                        clears_failed_session=case=='no_error' or engine.session is None,
                        clears_failed_exporter=case=='no_error' or engine.exporter is None,
                        preserves_error_message=case=='no_error' and not engine.errors or case!='no_error' and engine.errors==[('Error: ','Injected viewport draw failure')],
                        returns_without_waiting_for_busy_owner=not case.endswith('_busy') or returned_while_owner_busy)
            if case=='no_error':checks['healthy_draw_does_not_stop_or_discard']=healthy_session_preserved
            if case=='legacy_started':checks['legacy_stop_preserved']=len(stops)==1
            if case=='legacy_stopped':checks['stopped_legacy_no_native_stop']=not stops
            records.append(dict(case=case,passed=all(checks.values()),checks=checks,stops=stops,violations=violations,UI_call_seconds_diagnostic_only=elapsed))
        finally:
            release.set()
            if reader is not None:reader.join(2)
            if worker is not None:worker.shutdown();worker._thread.join(2)
    result=dict(passed=all(r['passed'] for r in records),records=records,source_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest(),worker_source_sha256=hashlib.sha256(a.worker_source.read_bytes()).hexdigest(),test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),control_stop_records_include_final_supervised_shutdown=True,scope='Exact production draw recovery and SessionWorker with deterministic modeled reader/OIDN/edit/Stop; no native GPU or tester-crash acceptance')
    a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)

if __name__=='__main__':main()
