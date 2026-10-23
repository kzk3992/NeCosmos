#!/usr/bin/env python3
"""Stage only production sources/assets. Local analysis artifacts are never copied."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
PUB=ROOT/'public'
SIM=ROOT/'NeCosmos-Simulation'
ASSETS=ROOT/'NeCosmos-Assets'

def copy(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if src.exists(): shutil.copyfile(src,dst)
    elif not dst.exists(): raise FileNotFoundError(src)

for src in sorted((SIM/'src').rglob('*.py')):
    copy(src,PUB/'engine/NeCosmos-Simulation'/src.relative_to(SIM))
for rel in ['species/species.json','terrain/terrain.json','scenarios/climates.json','scenarios/compositions.json','scenarios/frozen.json','scenarios/weather.json']:
    copy(SIM/'configs'/rel,PUB/'engine/NeCosmos-Simulation/configs'/rel)
# Keep the canonical module's read-only Phase 3 metadata path intact in worker FS.
copy(ASSETS/'objects/metadata/cat_tower_01.json',PUB/'engine/NeCosmos-Assets/objects/metadata/cat_tower_01.json')
engine=PUB/'engine'
paths=[str(p.relative_to(engine)) for p in sorted(engine.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and p.name!='manifest.json']
(engine/'manifest.json').write_text(json.dumps({'version':'0.11.0','files':paths},indent=2)+'\n')

catalog_path=PUB/'assets/catalog.json'
if ASSETS.exists():
    objects=[]
    for src in sorted((ASSETS/'objects/metadata').glob('*.json')):
        meta=json.loads(src.read_text())
        dest=PUB/'assets/objects'/meta['model']
        copy(ASSETS/'objects/glb'/meta['model'],dest)
        copy(src,PUB/'assets/metadata'/src.name)
        price=60 if meta['type']=='interactive' else (40 if meta['type']=='environment' else 12)
        objects.append({'id':meta['id'],'name':meta['title'],'title':meta['title'],'model':str(dest.relative_to(PUB)), 'price':price,'metadata':meta})
    cats=[]
    names={'grass':'草ねこ','mogumogu':'もぐもぐねこ','kinoko':'きのこねこ','fuwa':'ふわねこ','chie':'知恵ねこ','tori':'鳥ねこ','sakana':'魚ねこ','slime':'スライムねこ'}
    dirs=['front','front_left','left','back_left','back','back_right','right','front_right']
    for sid,name in names.items():
        prefix=sid+'_cat'
        for direction in dirs:
            filename=prefix+'_'+direction+'.png'
            copy(ASSETS/'renders'/prefix/'48'/filename,PUB/'assets/cats'/prefix/filename)
        cats.append({'id':sid,'name':name,'spriteBase':'assets/cats/'+prefix,'spritePrefix':prefix,'frameMetres':.8,'feetV':1-207.42/256})
    terrains=[]
    for tid in ['flat_meadow','rolling_hills','central_mountain','valley','pond','winding_river']:
        copy(ASSETS/'terrain/glb'/(tid+'.glb'),PUB/'assets/terrain'/(tid+'.glb'))
        copy(ASSETS/'terrain/presets'/(tid+'.json'),PUB/'assets/terrain'/(tid+'.json'))
        terrains.append({'id':tid,'model':'assets/terrain/'+tid+'.glb','preset':'assets/terrain/'+tid+'.json'})
    catalog_path.parent.mkdir(parents=True,exist_ok=True)
    catalog_path.write_text(json.dumps({'version':'0.11.0','units':'metres','objects':objects,'cats':cats,'terrains':terrains},ensure_ascii=False,indent=2)+'\n')
else:
    assert catalog_path.exists(),'Production catalog missing; original source asset folder is optional after staging'

inventory={str(p.relative_to(PUB)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(PUB.rglob('*')) if p.is_file() and p.name not in ('release-manifest.json','.assetsignore') and '__pycache__' not in p.parts and p.suffix!='.pyc'}
assert all(v['bytes']<25*1024*1024 for v in inventory.values()),'Cloudflare single-asset limit exceeded'
(PUB/'release-manifest.json').write_text(json.dumps({'version':'0.11.0','files':inventory},indent=2)+'\n')
print(json.dumps({'files':len(inventory),'bytes':sum(v['bytes'] for v in inventory.values()),'objects':len(json.loads(catalog_path.read_text())['objects']),'cats':len(json.loads(catalog_path.read_text())['cats'])}))
