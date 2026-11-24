from pathlib import Path
import subprocess as sp, os, json, urllib.request, time, platform
d=Path(__file__).resolve().parent;root=d/'desktop';out=d/'evidence';out.mkdir(exist_ok=True)
assert platform.machine()=='aarch64'
cfg=json.loads((root/'server/helene.server.json').read_bytes())
cfg.update(agent={'name':'Window QA'},owner={'name':'QA','room':'Window QA'},phone={'enabled':False},telegram={},relay={'enabled':False})
cfg['model'].update(model='',key='',base_url='http://127.0.0.1:9')
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
    return v.get('kind')=='serverboot' and all(any(r.get('id')==role and r.get('alive') for r in v['children']) for role in ('channel','runner'))
try:
    sp.run([*compose,'up','-d','--build','helene'],cwd=root,env=env,check=True)
    # A real boot error must be reported immediately and remain diagnosable.
    print('native image',sp.check_output(['docker','image','inspect','nativearm-helene','--format','{{.Architecture}}'],text=True).strip(),flush=True)
    wait(alive)
    who=api('state')['desk']['version'];assert who=='2.9.2' and ctl('status')['stopped'] is False
    api('panic',{});wait(lambda:ctl('status')['stopped'])
    sp.run(['docker','restart','nativearm'],check=True,stdout=sp.DEVNULL)
    assert wait(lambda:ctl('status')['stopped'])
    assert ctl('resume')['stopped'] is False
    wait(alive)
    (out/'result.json').write_text(json.dumps(dict(arch=platform.machine(),server=who,stop_survived_container_restart=True,explicit_resume=True,channel_and_runner=True)))
except BaseException:
    print(sp.check_output(['docker','inspect','nativearm','--format','{{json .State}} {{json .Mounts}}'],text=True),flush=True)
    logs=sp.run(['docker','logs','--tail','70','nativearm'],capture_output=True,text=True)
    for line in (logs.stdout+logs.stderr).splitlines():
        if not any(word in line.lower() for word in ('token','bearer','password','/api/','?key=')):print(line)
    raise
finally:
    sp.run([*compose,'down'],cwd=root,env=env,check=False)
