from pathlib import Path
from unittest.mock import patch
import json,qa_server as lab
a=lab.raw()
target={**lab.DEST,'directory':lab.DIR+'-fresh','project':lab.DEST['project']+'-fresh','container':lab.DEST['container']+'-fresh','port':29784}
a.update(deployment=target,telegram={'bot_token':'123456789:'+'A'*35,'owner_id':123456},agent_name='QA empty')
cfg=lab.D/'fresh-client/helene.json'
if not cfg.exists():lab.dump(cfg,{'tree':'data'})
template=lab.si.server_config
def offline(*args):
    cfg=template(*args);cfg['phone']={'enabled':False};cfg['telegram']={};cfg['model'].update(base_url='http://127.0.0.1:9',key='',model='');return cfg
with patch.object(lab.si,'server_config',side_effect=offline):
    result=lab.si.install_new(a,cfg,lab.P)
assert result['ok'] and result['version']=='2.9.2'
with lab.st.connect(a) as c:
    facts=lab.si.check_channel(c,target['directory'],target['port'],'2.9.2')
lab.record('fresh',{'version':result['version'],'arch':result['arch'],'supervisor':facts['/api/supervisor']['kind'],'channel_ready':lab.si.channel_ready(facts,'2.9.2'),'connected_to_telegram':False})
