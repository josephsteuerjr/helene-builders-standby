from pathlib import Path
import subprocess, platform, datetime
import sys, os, time, json, threading, shutil, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
d=Path(__file__).resolve().parent
root=d/'desktop'
out=d/'evidence';out.mkdir(exist_ok=True)
exe=root/('runtime/python.exe' if os.name=='nt' else 'runtime/bin/python3')
assert platform.machine().lower() in {'windows':{'amd64','x86_64'},'mac-arm':{'arm64'},'mac-intel':{'x86_64'},'debian':{'x86_64'},'fedora':{'x86_64'}}[sys.argv[1]]
sys.path[:0]=[str(root/'app'),str(root/'app/localharness')]
from localharness import agents, carry_payload, python_controller, server_return as back
def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf8')
entered=threading.Event()
release=threading.Event()
class Provider(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        req=json.loads(self.rfile.read(int(self.headers['content-length'])))
        if req.get('model')=='qa-peer':
            entered.set()
            if not release.wait(530):
                self.send_error(503);return
        reply={'id':'qa','object':'chat.completion','model':req.get('model'),'choices':[{'index':0,'message':{'role':'assistant','content':'Hello from the local test.'},'finish_reason':'stop'}]}
        if req.get('stream'):
            chunks=[{'id':'qa','object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':reason}]} for delta,reason in [({'role':'assistant','content':'Hello from the local test.'},None),({},'stop')]]
            body=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode();mime='text/event-stream'
        else:body=json.dumps(reply).encode();mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

def wait(fn,timeout=180):
    until=time.monotonic()+timeout
    last=''
    while time.monotonic()<until:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError,RuntimeError) as err:last=str(err)
        time.sleep(.25)
    raise RuntimeError('Condition did not converge: '+last)

server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
threading.Thread(target=server.serve_forever,daemon=True).start()
model=dict(key='fixture',provider_id='compatible',framework='openai',api_mode='chat_completions',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='qa-peer')

cfgpath=root/'helene.json'
cfg=dict(mode='remote',base='http://127.0.0.1:9',tree=str(d/'primary-data'),code='tree',port=29781,python=str(exe),app='app/deskapp.py',runner='app/localharness/runner.py',
         agent={'name':'QA main'},owner={'name':'QA','room':'Main'},telegram={},model={**model,'model':'qa-main'},relay={'enabled':False},voice={'enabled':False},phone={'enabled':False},setup_complete=True,read_dotenv=False)
dump(cfgpath,cfg)
from localharness import first_start
dump(first_start.receipt(root),{'format':first_start.FORMAT,'state':'completed','data':cfg['tree'],'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
dump(d/'primary-data/memory/.control/profile-identity.json',{'agent_name':'QA main'})

peer=agents.create(root,'Peer')
cfg_peer=agents.read_config(peer.config)
cfg_peer.update(mode='local',setup_complete=True,telegram={},agent={'name':'Peer'},owner={'name':'QA','room':'Peer'},model=model)
agents._write_config(peer.config,cfg_peer)
remote=d/'fixture'
for name in ('code','app','data/memory','base/tree','base/app'):(remote/name).mkdir(parents=True,exist_ok=True)
(remote/'code/qa_server_only.py').write_text('STAND = True')
(remote/'data/memory/server-only.txt').write_text('Remote memory')
rid='23341234abcd1234'
folder=back.places(cfgpath,rid)['payload']
folder.mkdir(parents=True,exist_ok=True)
archive=folder/'payload.zip'
payload=carry_payload.create(archive,{n:remote/n for n in ('data','code','app','base')},metadata={'version':'2.9.2','config':cfg,'git':[]})
deploy={'directory':'/srv/helene-qa','project':'helene','container':'helene','port':8094}
raw={'host':'localhost','port':22,'login':'qa','deployment':deploy}
row={'id':'1'*24,'phase':'ready','archive_sha':'cd'*32,'destination':['localhost',22,'qa'],'fingerprint':'SHA256:fixture','version':'2.9.2','deployment':deploy,
     'return':{'phase':'downloaded','id':rid,'projects':[],'remote':{'sha256':payload['sha256'],'bytes':archive.stat().st_size,'version':'2.9.2','archive':'/srv/snapshot.zip','exclusions':[]}}}
dump(d/'primary-data/memory/.state/server-transfer.json',row)
from localharness import session_host
windows=[]
def launch(phase):
    log=(out/(phase+'-window.log')).open('wb')
    process=subprocess.Popen([str(exe),'-Bu',str(d/'ui_window.py'),phase],stdout=log,stderr=subprocess.STDOUT)
    log.close();windows.append(process)
    return process
def observation(phase,kind):
    path=out/(phase+'-'+kind+'.json')
    def state():
        failure=out/(phase+'-error.json')
        if failure.exists():raise AssertionError(failure.read_text(encoding='utf8'))
        if path.is_file():return json.loads(path.read_text(encoding='utf8'))
        if windows[-1].poll() is not None:raise AssertionError('window exited '+str(windows[-1].returncode))
    return wait(state)
def close_view(proc):
    from localharness.migration_windows import request_python_exit
    request_python_exit(root,proc.pid,observer_only=True)
    assert proc.wait(timeout=30)==0
first=launch('first')
owner=None
def pid(agent):
    return owner.status()['agents'].get(agent,{}).get('pids',{}).get('runner')
def manifests():
    return {p.parent.name:json.loads(p.read_bytes()) for p in (peer.tree/'memory/runs').glob('*/*/manifest.json')}
def command(action,**opts):
    return owner.invoke('server_transfer',{'action':action,'request':json.dumps({**raw,'expected_config':str(cfgpath),**opts})})
try:
    observation('first','opened')
    owner=session_host.attach(root,lambda *args:None)
    generation=owner.descriptor['generation']
    if not entered.wait(25):
        st=owner.status().get('agents',{}).get(peer.id,{})
        print('Peer before model', {k:st.get(k) for k in ('pids','roles','problems','startup')},flush=True)
        for log in peer.tree.glob('*.log'):
            lines=log.read_text(encoding='utf8',errors='replace')[-6500:].splitlines()
            safe=[line for line in lines if not any(term in line.lower() for term in ('bearer','token','password','api_key','api-key','secret='))]
            (out/('peer-'+log.name)).write_text('\n'.join(safe),encoding='utf8')
        if not entered.wait(80):
            raise AssertionError('Peer did not enter the local provider')
    before=pid(peer.id); active=wait(manifests)
    assert before and len(active)==1 and not pid('main')
    runid=next(iter(active))
    assert back.code_scope(cfgpath,root)['agents']==[peer.id]
    result=command('return',projects=[],shared_code=None)
    assert result['ok'] and result['restart']=='profile',result
    cfg=agents.read_config(cfgpath)
    assert (Path(cfg['code'])/'qa_server_only.py').is_file() and not (root/'tree/qa_server_only.py').exists()
    assert (Path(cfg['tree'])/'memory/server-only.txt').is_file() and cfg['return_pending']
    assert not pid('main') and pid(peer.id)==before
    result=command('resume-returned')
    assert result['ok'] and pid('main') and pid(peer.id)==before
    (out/'main-ready').touch()
    observation('first','selected')
    from deskd import control
    initial_main=pid('main')
    control.ask(Path(cfg['tree']),'runner')
    wait(lambda:pid('main') and pid('main')!=initial_main)
    assert pid(peer.id)==before and not release.is_set()
    close_view(first)
    assert pid(peer.id)==before
    second=launch('second')
    observation('second','opened');observation('second','selected')
    assert session_host.read(session_host.control_path(root))['generation']==generation
    assert len(manifests())==1 and pid(peer.id)==before
    linux=sys.platform.startswith('linux')
    linux_receipt={}
    if linux:
        from localharness import session_exit
        def managed_window():
            for line in subprocess.check_output(['wmctrl','-lp'],text=True).splitlines():
                fields=line.split(None,4)
                if len(fields)==5 and fields[2]==str(second.pid) and fields[4]=='Hélène':
                    return fields[0]
        xid=wait(managed_window)
        def iconic():
            text=subprocess.check_output(['xprop','-id',xid,'WM_STATE','_NET_WM_STATE'],text=True)
            return 'Iconic' in text and '_NET_WM_STATE_HIDDEN' in text and '_NET_WM_STATE_SKIP_TASKBAR' not in text
        def restore():
            subprocess.run(['wmctrl','-ia',xid],check=True)
            wait(lambda:'Normal' in subprocess.check_output(['xprop','-id',xid,'WM_STATE'],text=True))
            assert managed_window()==xid and second.poll() is None
        def still_running():
            assert pid(peer.id)==before and pid('main')==final_main_before
            assert owner.status()['session']['generation']==generation
            assert not session_exit.requested(root) and managed_window()==xid
        final_main_before=pid('main')
        (out/'minimize-active').touch()
        wait(iconic);still_running();restore()
        subprocess.run(['xdotool','key','alt+F4'],check=True)
        wait(iconic);still_running()
        linux_receipt=dict(xid=xid,window_pid=second.pid,first_close_iconic=True,
                           alt_f4_iconic=True,listed_in_taskbar=True,session_generation_unchanged=True)
    release.set();wait(lambda: manifests().get(runid,{}).get('status')=='done')
    if linux:
        assert iconic()
        still_running()
        restore()
        linux_receipt['completed_while_minimized']=runid
        linux_receipt['restored_same_window']=True
    assert len(manifests())==1 and pid(peer.id)==before
    after=pid(peer.id)
    final_main=pid('main')
    owner.invoke('owner_control',{'action':'panic'})
    wait(lambda:not pid(peer.id) and not pid('main'),60)
    owner.invoke('owner_control',{'action':'resume'})
    wait(lambda:pid(peer.id) and pid('main'))
    (out/('quit-explicit' if linux else 'close-real')).touch()
    def visible_win():
        import ctypes
        types=ctypes.wintypes
        user=ctypes.windll.user32
        shown=[]
        @ctypes.WINFUNCTYPE(types.BOOL,types.HWND,types.LPARAM)
        def inspect(hwnd,unused):
            pid=types.DWORD()
            user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==second.pid and user.IsWindowVisible(hwnd):
                title=ctypes.create_unicode_buffer(256)
                user.GetWindowTextW(hwnd,title,256)
                if title.value=='Hélène':shown.append(hwnd)
            return True
        user.EnumWindows(inspect,0)
        return bool(shown)
    if os.name=='nt':
        import ctypes.wintypes
        wait(lambda:not visible_win(),45)
    else:assert second.wait(timeout=60)==0
    if sys.platform.startswith('linux'):
        wait(lambda:session_host.process_state(owner.descriptor) in ('changed','absent'),60)
        closed='minimized to taskbar; explicit Quit exited session'
    else:
        assert owner.status()['session']['generation']==generation
        closed='hidden in tray' if second.poll() is None else 'view detached'
        if second.poll() is None:close_view(second)
        owner.shutdown(owner_exit=True)
        wait(lambda:session_host.process_state(owner.descriptor) in ('changed','absent'),60)
    from localharness import session_exit
    assert session_exit.requested(root)
    owner=None
    dump(out/'result.json',dict(**linux_receipt,titlebar_close=closed,owner_exit_verified=True,peer_pid_before=before,peer_pid_after=after,main_pid=final_main,old_main_pid=initial_main,targeted_restart=True,global_stop_resume=True,completed_run=runid,profile_resume=True,shared_unchanged=True,target=sys.argv[1],arch=platform.machine(),transport='staged snapshot',reopened_same_session=True,switched_both_profiles=True))
finally:
    release.set()
    for proc in windows:
        if proc.poll() is None:
            try:close_view(proc)
            except Exception:proc.terminate();proc.wait(timeout=10)
    if owner:owner.shutdown(owner_exit=True)
    server.shutdown()
