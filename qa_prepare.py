from pathlib import Path
import shutil,zipfile
d=Path(__file__).resolve().parent
root=d/'desktop'
with zipfile.ZipFile(d/'linux.zip') as z:
    for row in z.infolist():
        n=row.filename.removeprefix('Helene/')
        if row.is_dir() or not (n.startswith(('app/','tree/','server/','runtime/')) or n in ('helene-build.json','requirements.txt','python-app.json')):continue
        if '/PySide6/' in n or n.startswith(('runtime/include/','runtime/share/')) or n in ('runtime/bin/python','runtime/bin/python3.14'):continue
        target=root/n
        assert target.resolve().is_relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True)
        with z.open(row) as a,target.open('wb') as b:shutil.copyfileobj(a,b)
        target.chmod((row.external_attr>>16)&0o777 or 0o644)
for name in ('python','python3.14'):(root/'runtime/bin'/name).symlink_to('python3')
shutil.copytree(d/'candidate',root/'app',dirs_exist_ok=True)
(root/'extraction-ok').touch()
