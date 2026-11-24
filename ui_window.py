"""Run the ordinary desktop entry, observing controls in its own native renderer."""
import sys, os, json, time, traceback, subprocess, threading
from pathlib import Path
D=Path(__file__).resolve().parent
root=D/'desktop'
sys.path[:0]=[str(root/'app'), str(root/'app/localharness')]
import python_app, webview
phase=sys.argv[1]
out=D/'evidence';out.mkdir(exist_ok=True)
def dump(name,v):
    (out/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def wait(fn,seconds=120):
    deadline=time.monotonic()+seconds
    last=None
    while time.monotonic()<deadline:
        try:
            value=fn()
            if value:return value
        except Exception as exc:last=type(exc).__name__
        time.sleep(.23)
    raise AssertionError('Window observation timed out '+str(last))
def screenshot(name):
    file=out/(name+'.png')
    if sys.platform=='darwin':cmd=['screencapture','-x',str(file)]
    elif sys.platform=='win32':
        ps="Add-Type -AssemblyName System.Drawing;Add-Type -AssemblyName System.Windows.Forms;$r=[Windows.Forms.Screen]::PrimaryScreen.Bounds;$b=New-Object Drawing.Bitmap $r.Width,$r.Height;$g=[Drawing.Graphics]::FromImage($b);$g.CopyFromScreen($r.Location,[Drawing.Point]::Empty,$r.Size);$b.Save($args[0],[Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$b.Dispose()"
        script=D/'screen.ps1';script.write_text(ps,encoding='utf-8')
        cmd=['powershell','-NoProfile','-File',str(script),str(file)]
    else:cmd=['import','-window','root',str(file)]
    result=subprocess.run(cmd,capture_output=True,timeout=15)
    return file.stat().st_size if file.is_file() else 0
def drive():
    w=webview.windows[0]
    def ev(script):return w.evaluate_js(script)
    def selected(i):
        return ev("Boolean(document.querySelector('.agent-row.is-current[data-id="+i+"]') && document.querySelector('#app:not([hidden])'))")
    try:
        initial='peer' if phase=='first' else 'main'
        wait(lambda:selected(initial))
        def open_menu():
            ev("""(()=>{let b=document.querySelector('.agent-current'); if(!b.getClientRects().length || b.getBoundingClientRect().right<8){document.querySelector('#toggle-rail')?.click()} if(b.getAttribute('aria-expanded')!=='true')b.click();return true})()""")
        def switch(identity):
            open_menu()
            wait(lambda:ev("Boolean(document.querySelector('.agent-row[data-id="+identity+"]').getClientRects().length)"))
            ev("document.querySelector('.agent-row[data-id="+identity+"]').click();true")
            wait(lambda:selected(identity))
        open_menu()
        proof={'phase':phase,'platform':sys.platform,'pid':os.getpid(),'initial':initial,'renderer':ev('navigator.userAgent'),
               'title':ev('document.title'),'width':ev('innerWidth'),'height':ev('innerHeight'),
               'menu':ev("Array.from(document.querySelectorAll('.agent-row'),n=>n.dataset.id)"),'screen_bytes':screenshot(phase)}
        assert set(proof['menu'])=={'main','peer'} and proof['width']>200 and proof['height']>200,proof
        dump(phase+'-opened',proof)
        if phase=='first':wait(lambda:(out/'main-ready').is_file(),210);switch('main')
        else:switch('peer');switch('main')
        dump(phase+'-selected',{'final':'main','pid':os.getpid()})
        if phase=='second':
            if sys.platform.startswith('linux'):
                wait(lambda:(out/'minimize-active').is_file(),180)
                label=ev("document.querySelector('button[data-win=close]').getAttribute('aria-label')")
                assert label==ev("document.querySelector('button[data-win=minimize]').getAttribute('aria-label')")
                ev("setTimeout(()=>document.querySelector('button[data-win=close]').click(),50);true")
                wait(lambda:(out/'quit-explicit').is_file(),180)
                ev("document.querySelector('button[data-view=settings]').click();true")
                wait(lambda:ev("Boolean(document.querySelector('.settings-tab[data-group=app]'))"))
                ev("document.querySelector('.settings-tab[data-group=app]').click();true")
                wait(lambda:ev("Boolean(document.querySelector('[data-action=quit-application]')?.getClientRects().length)"))
                ev("document.querySelector('[data-action=quit-application]').scrollIntoView({block:'center'});true")
                dump('quit-control',{'label':ev("document.querySelector('[data-action=quit-application]').textContent"),'close_label':label,'screen_bytes':screenshot('explicit-quit')})
                ev("setTimeout(()=>document.querySelector('[data-action=quit-application]').click(),50);true")
                return
            wait(lambda:(out/'close-real').is_file(),180)
            assert ev("Boolean(document.querySelector('button[data-win=close]').getClientRects().length)")
            # Allow the JavaScript invocation to finish before its view is disposed.
            ev("setTimeout(()=>document.querySelector('button[data-win=close]').click(),50);true")

    except BaseException:
        try:
            dump(phase+'-error',{'error':traceback.format_exc(),'body':ev("(document.body?.innerText||'').slice(0,1000)"),'title':ev('document.title')})
        except BaseException:dump(phase+'-error',{'error':traceback.format_exc()})
        print('Native DOM test failed',flush=True)
    # Parent retires this observer using the standard window-control endpoint.
start=webview.start
def instrument(*args,**kwargs):
    return start(drive,*args,**kwargs)
webview.start=instrument
sys.exit(python_app._main(['--root',str(root),'--agent','peer' if phase=='first' else 'main']))
