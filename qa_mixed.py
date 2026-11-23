"""A real local turn runs while another profile returns from an isolated SSH server."""
import json
import os
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import shutil
import subprocess
import sys
import threading
import time
import qa_server as lab
from localharness import agents, python_controller

root=lab.P
cfg=json.loads(lab.CFG.read_text())
code=root/'author-tree'
shutil.copytree(root/'tree',code)
(code/'qa_departure.py').write_text('PROFILE_ONLY = True\n')
assert not (root/'tree/qa_departure.py').exists()
cfg.update(code='author-tree',python=str(root/'runtime/bin/python3'))
lab.dump(lab.CFG,cfg)
raw=lab.raw()
lab.move(raw)
assert lab.check(raw,'cat '+lab.DIR+'/tree/qa_departure.py')=='PROFILE_ONLY = True'
lab.markers(raw)
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
peer=agents.create(root,'Peer')
peer_cfg=agents.read_config(peer.config)
peer_cfg.update(mode='local',setup_complete=True,model=model,telegram={},agent={'name':'Peer'},owner={'name':'QA','room':'Peer'})
agents._write_config(peer.config,peer_cfg)
assert (peer.config.parent/peer_cfg['code']).resolve()==code
# The server is stopped. Its returned settings use only the fixture provider.
with lab.st.connect(raw) as c:
    with c.open_sftp() as ftp:
        remote=lab.DIR+'/helene.json'
        with ftp.open(remote) as f: c_cfg=json.loads(f.read())
        c_cfg.update(telegram={},model={**model,'model':'qa-main'},owner={'name':'QA','room':'Main'},phone={'enabled':False})
        with ftp.open(remote,'w') as f:f.write(json.dumps(c_cfg))
owner=python_controller.Controller(root,lambda *args:None)
def pid(agent):
    return owner.status()['agents'].get(agent,{}).get('pids',{}).get('runner')
def manifests():
    return {p.parent.name:json.loads(p.read_bytes()) for p in (peer.tree/'memory/runs').glob('*/*/manifest.json')}
def command(action,**opts):
    return owner.invoke('server_transfer',{'action':action,'request':json.dumps({**raw,'expected_config':str(lab.CFG),**opts})})
try:
    owner.start()
    assert entered.wait(110),str(owner.error)
    before=pid(peer.id);active=wait(manifests);assert before and len(active)==1 and not pid('main')
    current=next(iter(active))
    scope=command('return-scope');assert scope['ok'] and scope['code_scope']['agents']==[peer.id] and not scope['code_scope']['stopped'],scope.get('message')
    returned=command('return',projects=[],shared_code=None);assert returned['ok'],returned.get('message')
    conf=agents.read_config(lab.CFG)
    data=Path(conf['tree'])
    assert (Path(conf['code'])/'qa_server_only.py').is_file() and not (code/'qa_server_only.py').exists()
    assert (Path(conf['code'])/'qa_departure.py').is_file() and (data/'memory/server-only.txt').is_file()
    assert subprocess.check_output(['git','-C',str(data/'workspace/projects/roundtrip'),'rev-parse','HEAD'],text=True).strip()==json.loads((lab.D/'markers.json').read_text())['project_head']
    assert conf['return_pending'] and not pid('main') and pid(peer.id)==before and not release.is_set()
    outcome=command('resume-returned');assert outcome['ok'],outcome
    assert pid('main') and pid(peer.id)==before
    release.set()
    wait(lambda:manifests().get(current,{}).get('status')=='done')
    assert len(manifests())==1 and pid(peer.id)==before
    lab.record('mixed',{'profile_code_at_server':True,'peer_pid_before':before,'peer_pid_after':pid(peer.id),'same_completed_run':current,'main_pid_after_explicit_resume':pid('main'),'private_code_active':True,'shared_code_untouched':True,'memory_and_git_preserved':True,'global_stop':False})
finally:
    release.set();owner.close();server.shutdown()
