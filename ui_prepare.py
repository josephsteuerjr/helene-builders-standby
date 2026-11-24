"""Assemble the native acceptance fixture from the released platform package."""
from pathlib import Path
import shutil, zipfile, hashlib, sys, os, platform
D=Path(__file__).resolve().parent
target=sys.argv[1]
names={'windows':'','mac-arm':'-macos-arm64','mac-intel':'-macos-x86_64','debian':'-linux-x86_64','fedora':'-fedora-x86_64','server-arm':'-server-linux-arm64'}
name='Helene-2.9.2'+names[target]+'.zip'
digest=next(line.split()[0] for line in (D/'fixture-sha256.txt').read_text().splitlines() if line.split()[-1]==name)
archive=D/'fixture.zip'
with archive.open('rb') as f:
    checksum=hashlib.sha256()
    for chunk in iter(lambda:f.read(1<<20),b''): checksum.update(chunk)
assert checksum.hexdigest()==digest
root=D/'desktop'
with zipfile.ZipFile(archive) as z:
    for row in z.infolist():
        n=row.filename.removeprefix('Helene/')
        if n.startswith(('verification/','verification-tools/')) or row.is_dir(): continue
        out=root/n
        assert out.resolve().is_relative_to(root)
        out.parent.mkdir(parents=True,exist_ok=True)
        with z.open(row) as src,out.open('wb') as dst:shutil.copyfileobj(src,dst)
        if os.name!='nt':out.chmod((row.external_attr>>16)&0o777 or 0o644)
shutil.copytree(D/'candidate',root/'app',dirs_exist_ok=True)
print(target,name,digest,platform.machine(),flush=True)
