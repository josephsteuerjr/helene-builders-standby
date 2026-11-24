from pathlib import Path
import subprocess as sp, os, json, urllib.request, time, platform, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
d=Path(__file__).resolve().parent;root=d/'desktop';out=d/'evidence';out.mkdir(exist_ok=True)
assert platform.machine()=='aarch64'
cfg=json.loads((root/'server/helene.server.json').read_bytes())
cfg.update(agent={'name':'Window QA'},owner={'name':'QA','room':'Window QA'},phone={'enabled':False},telegram={},relay={'enabled':False})
class Provider(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if req.get('stream'):
            obj={'id':'qa','object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant','content':'Hello'},'finish_reason':'stop'}]}
            data=('data: '+json.dumps(obj)+'\n\ndata: [DONE]\n\n').encode(); mime='text/event-stream'
        else:
            data=json.dumps({'id':'qa','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':'Hello'},'finish_reason':'stop'}]}).encode()
            mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
gateway=json.loads(sp.check_output(['docker','network','inspect','bridge']))[0]['IPAM']['Config'][0]['Gateway']
provider=ThreadingHTTPServer((gateway,0),Provider)
threading.Thread(target=provider.serve_forever,daemon=True).start()
cfg['model']=dict(framework='openai',provider_id='compatible',api_mode='chat_completions',model='qa-arm',key='fixture',base_url=f'http://host.docker.internal:{provider.server_port}/v1')

(root/'helene.json').write_text(json.dumps(cfg),encoding='utf8')
env={**os.environ,'HELENE_PROJECT':'nativearm','HELENE_CONTAINER':'nativearm','HELENE_PORT':'29783'}
compose=['docker','compose','-f','server/docker-compose.yml']
def ctl(action):
    return json.loads(sp.check_output(['docker','exec','-u','0','nativearm','python','server/emergency_stop.py',action,'--tree','/opt/helene/data']))
def api(path,body=None):
    key=sp.check_output(['docker','exec','nativearm','cat','/opt/helene/data/.serverboot/desk-token'],text=True,stderr=sp.DEVNULL).strip()
    req=urllib.request.Request('http://127.0.0.1:29783/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=6))
def wait(fn,limit=140):
    until=time.monotonic()+limit;last=''
    while time.monotonic()<until:
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError,sp.CalledProcessError) as e:last=type(e).__name__
        time.sleep(.8)
    raise AssertionError('Timed out '+last)
def alive():
    v=api('supervisor')
    roles={r['id']:r for r in v.get('children',[]) if r.get('alive')}
    if v.get('kind')!='serverboot' or not {'channel','runner'}<=roles.keys():return False
    receipt=sp.run(['docker','exec','-u','0','nativearm','cat','/opt/helene/data/memory/.control/desk_inbox/.reader.json'],capture_output=True,text=True)
    if receipt.returncode:return False
    reader=json.loads(receipt.stdout)
    return reader['pid'] if reader.get('pid')==roles['runner'].get('pid') and 0<=time.time()-reader['at']<30 else False
try:
    sp.run([*compose,'up','-d','--build','helene'],cwd=root,env=env,check=True)
    # A real boot error must be reported immediately and remain diagnosable.
    print('native image',sp.check_output(['docker','image','inspect','nativearm-helene','--format','{{.Architecture}}'],text=True).strip(),flush=True)
    first=wait(alive)
    who=api('state')['desk']['version'];assert who=='2.9.2' and ctl('status')['stopped'] is False
    api('panic',{});wait(lambda:ctl('status')['stopped'])
    sp.run(['docker','restart','nativearm'],check=True,stdout=sp.DEVNULL)
    assert wait(lambda:ctl('status')['stopped'])
    assert ctl('resume')['stopped'] is False
    resumed=wait(alive)
    (out/'result.json').write_text(json.dumps(dict(arch=platform.machine(),server=who,stop_survived_container_restart=True,explicit_resume=True,channel_and_runner=True,first_reader_pid=first,resumed_reader_pid=resumed)))
except BaseException:
    print(sp.check_output(['docker','inspect','nativearm','--format','{{json .State}} {{json .Mounts}}'],text=True),flush=True)
    logs=sp.run(['docker','logs','--tail','70','nativearm'],capture_output=True,text=True)
    for line in (logs.stdout+logs.stderr).splitlines():
        if not any(word in line.lower() for word in ('token','bearer','password','/api/','?key=')):print(line)
    for name in ('runner.log','deskapp.log'):
        res=sp.run(['docker','exec','-u','0','nativearm','tail','-30','/opt/helene/data/'+name],capture_output=True,text=True)
        for line in res.stdout.splitlines():
            if not any(term in line.lower() for term in ('token','bearer','api_key','password','?key=')):print(line)
    raise
finally:
    provider.shutdown()
    sp.run([*compose,'down'],cwd=root,env=env,check=False)
