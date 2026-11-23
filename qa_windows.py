from pathlib import Path
import sys, os, time, json, threading, shutil, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
d=Path(__file__).resolve().parent
root=d/'desktop'
if not (root/'app').exists():
    with zipfile.ZipFile(d/'windows.zip') as archive:
        for row in archive.infolist():
            n=row.filename.removeprefix('Helene/')
            if row.is_dir() or not (n.startswith(('app/','tree/','server/','runtime/')) or n in ('requirements.txt','helene-build.json','python-app.json')): continue
            target=root/n
            assert target.resolve().is_relative_to(root)
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(row) as f,target.open('wb') as out:shutil.copyfileobj(f,out)
    shutil.copytree(d/'candidate',root/'app',dirs_exist_ok=True)
if Path(sys.executable).resolve() != (root/'runtime/python.exe').resolve():
    import subprocess
    sys.exit(subprocess.call([str(root/'runtime/python.exe'),'-B',str(Path(__file__).resolve())]))
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
            if not release.wait(280):
                self.send_error(503);return
        reply={'id':'qa','object':'chat.completion','model':req.get('model'),'choices':[{'index':0,'message':{'role':'assistant','content':'Hello from the local test.'},'finish_reason':'stop'}]}
        if req.get('stream'):
            chunks=[{'id':'qa','object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':reason}]} for delta,reason in [({'role':'assistant','content':'Hello from the local test.'},None),({},'stop')]]
            body=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode();mime='text/event-stream'
        else:body=json.dumps(reply).encode();mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

def wait(fn,timeout=160):
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
cfg=dict(mode='remote',base='http://127.0.0.1:9',tree='data',code='tree',port=29781,python=str(root/'runtime/python.exe'),app='app/deskapp.py',runner='app/localharness/runner.py',
         agent={'name':'QA main'},owner={'name':'QA','room':'Main'},telegram={},model={**model,'model':'qa-main'},relay={'enabled':False},voice={'enabled':False},phone={'enabled':False},setup_complete=True,read_dotenv=False)
dump(cfgpath,cfg)
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
dump(root/'data/memory/.state/server-transfer.json',row)
owner=python_controller.Controller(root,lambda *args: None)
def pid(agent):
    return owner.status()['agents'].get(agent,{}).get('pids',{}).get('runner')
def manifests():
    return {p.parent.name:json.loads(p.read_bytes()) for p in (peer.tree/'memory/runs').glob('*/*/manifest.json')}
def command(action,**opts):
    return owner.invoke('server_transfer',{'action':action,'request':json.dumps({**raw,'expected_config':str(cfgpath),**opts})})
try:
    owner.start()
    assert entered.wait(130),str(owner.error)
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
    release.set();wait(lambda: manifests().get(runid,{}).get('status')=='done')
    assert len(manifests())==1 and pid(peer.id)==before
    dump(d/'windows.json',dict(peer_pid_before=before,peer_pid_after=pid(peer.id),main_pid=pid('main'),completed_run=runid,profile_resume=True,shared_unchanged=True,transport='staged snapshot'))
finally:
    release.set();owner.close();server.shutdown()
