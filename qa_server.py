"""2.9.2 server operations, isolated Linux destination and synthetic Windows profile."""
import contextlib, hashlib, http.client, importlib.util, json, os, shlex, sys, time, zipfile
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

D = Path(__file__).resolve().parent
ROOT = D
P = D/'desktop'
OLD = D/'2.8.14'
CFG = P/'helene.json'
DEST = {'directory':'/opt/helene-qa-300-2411-a9db','project':'helene-qa-300-2411-a9db','container':'helene-qa-300-2411-a9db','port':29783}
DIR=DEST['directory']
PROG=P
sys.path[:0]=[str(PROG/'app'),str(PROG/'app/localharness')]

def record(name,value):
    (D/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,flush=True)
def dump(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def clean_extract(path,out):
    if (out/'extraction-ok').exists():return
    with zipfile.ZipFile(path) as z:
        for x in z.infolist():
            n=x.filename.removeprefix('Helene/')
            if not (n.startswith(('server/','tree/','app/')) or n in ('requirements.txt','helene-build.json','helene-relay','code-upstream.json','app-upstream.json','code-upstream.zip','app-upstream.zip')) or x.is_dir(): continue
            dest=out/n;assert dest.resolve().is_relative_to(out)
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(x))
    (out/'extraction-ok').touch()
def setup():
    clean_extract(D/'Helene-2.8.14.zip',OLD)
    clean_extract(D/'Helene-2.9.2.zip',P)
    if not CFG.exists():
        cfg={'mode':'local','tree':'data','code':'tree','port':29781,'app':'app/deskapp.py','runner':'app/localharness/runner.py','agent':{'name':'QA 300'},'model':{'base_url':'http://127.0.0.1:9','model':'','key':''},'telegram':{'owner_id':'123456','bot_token':'000000:synthetic_offline'},'relay':{'enabled':False},'voice':{'enabled':False,'speak':False},'phone':{'enabled':False},'installed':{'version':'2.8.14'},'setup_complete':True,'read_dotenv':False}
        dump(CFG,cfg)
        p=P/'data/memory/before.txt';p.parent.mkdir(parents=True);p.write_bytes(b'Before the server move.\n')
setup()
from localharness import server_transfer as st, server_install as si, server_return as sr
def raw():
    import base64
    blob=base64.b64decode((D/'ssh'/'host.pub').read_text().split()[1])
    pin='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    return dict(host='127.0.0.1',login='root',port=29690,key_path=str(D/'ssh/client'),fingerprint=pin,confirmed_host=True,deployment=DEST)
def http(client,endpoint,key):
    conn=http.client.HTTPConnection('127.0.0.1',DEST['port'],timeout=8)
    conn.sock=client.get_transport().open_channel('direct-tcpip',('127.0.0.1',DEST['port']),('127.0.0.1',0))
    try:
        conn.request('GET',endpoint,headers={'Authorization':'Bearer '+key})
        resp=conn.getresponse();assert resp.status==200,resp.status;return json.load(resp)
    finally: conn.close()
def proof(c):
    key=st.execute(c,'cat '+DIR+'/data/.serverboot/desk-token')[1].strip()
    return {k:http(c,'/api/'+k,key) for k in ('state','supervisor','panic')}
def report_facts(f):
    return dict(version=f['state']['desk']['version'],supervisor=f['supervisor']['kind'],alive=f['supervisor']['alive'],stopped=f['panic']['stopped'])
def check(raw_,cmd):
    with st.connect(raw_) as c:return st.execute(c,cmd)[1].strip()
def move(raw_):
    # Local Stop lives only inside the test directory. Use the existing SSH connection
    # for the channel in place of publishing a phone tunnel or contacting Telegram.
    stop=D/'stand.stop';stop.touch()
    original=st.execute
    def execute(c,command,*args,**kwargs):
        command=command.replace('HELENE_AUTOMATIC_CONNECTION=1','HELENE_AUTOMATIC_CONNECTION=0')
        return original(c,command,*args,**kwargs)
    with st.connect(raw_) as owner:
        def read(req):return http(owner,urlsplit(req.full_url).path,req.get_header('Authorization').split(' ',1)[1])
        with patch.object(st.owner_stop,'seed_file',return_value=stop),patch.object(st,'execute',execute),patch.object(st.remote_locator,'locate',return_value='http://127.0.0.1'),patch.object(st.remote_locator,'read',side_effect=read):
            result=st.run(raw_,CFG,OLD)
        facts=report_facts(proof(owner))
    assert result['ok'] and result['stopped'] and facts['version']=='2.8.14'
    cfg=json.loads(CFG.read_text(encoding='utf-8-sig'));cfg.update(mode='remote',base=result['base'],key=result['key'],server_locator=result['server_locator']);dump(CFG,cfg)
    assert check(raw_,'cat '+DIR+'/data/memory/before.txt')=='Before the server move.'
    record('transfer',dict(**facts,phase=st.saved_transfer(CFG)['phase'],memory_equal=True,telegram_discovery='replaced by SSH to loopback',desktop_controller='2.9.2',deployed_program='2.8.14',stop_fixture=True))
def markers(raw_):
    from base64 import b64encode
    script="""from pathlib import Path
import subprocess,sys
root=Path(sys.argv[1]); assert (root/'.window-transfer.json').exists()
p=root/'data/memory/server-only.txt';p.write_bytes(b'Server-only memory.\\n')
g=root/'data/workspace/projects/roundtrip';g.mkdir(parents=True,exist_ok=True)
git=lambda *args: subprocess.check_output(['git','-c','user.name=QA','-c','user.email=qa@localhost','-c','safe.directory='+str(g),'-C',str(g),*args],text=True).strip()
git('init','-q');(g/'proof.txt').write_bytes(b'Server-only project.\\n');git('add','proof.txt');git('commit','-qm','server QA') if git('status','--porcelain') else None
(root/'tree/qa_server_only.py').write_text('QA_RETURN = True\\n')
print(git('rev-parse','HEAD'))
"""
    head=check(raw_,'python3 -c '+shlex.quote(script)+' '+DIR);record('markers',dict(project_head=head))
def update(raw_):
    result=si.update(raw_,P)
    with st.connect(raw_) as c:f=report_facts(proof(c))
    record('update',dict(api=result,live=f));assert result['ok'] and f['version']=='2.9.2' and f['stopped']
    assert check(raw_,'cat '+DIR+'/data/memory/server-only.txt')=='Server-only memory.'
def back(raw_):
    import subprocess
    r=sr.scope(raw_,CFG,P)
    print('scope',r.keys(),flush=True)
    with patch.object(st.owner_stop,'seed_file',return_value=D/'stand.stop'):
        result=sr.run(raw_,CFG,P)
    cfg=json.loads(CFG.read_text(encoding='utf-8-sig'));data=Path(cfg['tree']);proj=data/'workspace/projects/roundtrip'
    head=subprocess.check_output(['git','-C',str(proj),'rev-parse','HEAD'],text=True).strip()
    assert cfg['mode']=='local' and head==json.loads((D/'markers.json').read_text())['project_head']
    codepaths=[Path(result['home'])/'tree/qa_server_only.py',P/'tree/qa_server_only.py']
    stored=[str(p) for p in [*codepaths,*Path(result['home']).rglob('qa_server_only.py')] if p.is_file() and p.read_bytes()==b'QA_RETURN = True\n']
    assert stored and (data/'memory/server-only.txt').read_bytes()==b'Server-only memory.\n' and (data/'memory/before.txt').read_bytes()==b'Before the server move.\n'
    states=check(raw_,"docker inspect -f '{{.State.Running}} {{.HostConfig.RestartPolicy.Name}}' "+DEST['container']+' '+DEST['container']+'-updater').splitlines()
    assert states==['false no','false no'],states
    record('return',dict(phase=result['phase'],data=str(data),live_git=head,old_memory=True,new_memory=True,author_code=stored,containers=states))
if __name__=='__main__':
    stage=sys.argv[1];setup();a=raw()
    if stage=='move':move(a)
    elif stage=='markers':markers(a)
    elif stage=='update':update(a)
    elif stage=='back':back(a)
