import json,subprocess,tarfile,io
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');sel=Path('docs/validation/semantic-navigation/openshift-ai/S1/replay-selection.json');image=json.loads(Path('docs/validation/semantic-navigation/openshift-ai/S1/gate-result.json').read_text())['runtime_image']
def run(*args,**kw):return subprocess.run([oc,'-n','semantic-model-serving',*args],check=True,**kw)
files=[Path('scripts/semantic-navigation/freeze_serving_replay.py'),sel]+[Path(x['repo_path']) for x in json.loads(sel.read_text())['frames'] if 'repo_path' in x]
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w') as tar:
 for f in files:tar.add(f,arcname=str(f))
run('exec','sam3-g0-reservation','--','mkdir','-p','/dev/shm/g1/tmp')
run('exec','-i','sam3-g0-reservation','--','tar','xf','-','-C','/dev/shm/g1',input=buf.getvalue())
with (e/'freeze-local.log').open('w') as out:
 run('exec','sam3-g0-reservation','--','env','TMPDIR=/dev/shm/g1/tmp','HOME=/dev/shm/g1/tmp','XDG_CACHE_HOME=/dev/shm/g1/tmp','/opt/sam3-venv/bin/python','/dev/shm/g1/scripts/semantic-navigation/freeze_serving_replay.py','--selection','/dev/shm/g1/'+str(sel),'--model-manifest','/app/model-manifest.json','--model-dir','/models','--build-identity','/app/build-identity.json','--runtime-image-digest',image.split('@')[1],'--output','/dev/shm/g1/frozen',stdout=out,stderr=subprocess.STDOUT)
run('cp','sam3-g0-reservation:/dev/shm/g1/frozen',str(e/'frozen'))
print((e/'freeze-local.log').read_text()[-1600:])
