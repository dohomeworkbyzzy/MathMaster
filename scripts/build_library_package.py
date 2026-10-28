"""Build a portable question-bank data ZIP from a reviewed import plan, without learner data or credentials."""
import argparse,hashlib,json,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'packaging/windows'))
import library_update as lib

def build(plan_path,uploads,output,required_program_version=None):
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    # Keep only shared-bank content, never operational paths or private provider state.
    plan={k:plan[k] for k in ('papers','questions')}
    assets=set()
    for p in plan['papers']:
        if p['filename']:assets.add(p['filename'])
    for q in plan['questions']:assets.update(q['images']+q['spec'].get('reference_images',[]))
    encoded=json.dumps(plan,ensure_ascii=False).encode()
    files={'plan.json':hashlib.sha256(encoded).hexdigest()}
    for name in sorted(assets):
        lib.safe_name(name)
        source=uploads/name
        if not source.resolve().is_relative_to(uploads.resolve()) or not source.is_file():raise ValueError('缺少附件 '+name)
        files['uploads/'+name]=lib.digest(source)
    lib.validate_plan(plan,files)
    signature=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:12]
    manifest={'format':1,'product':lib.PRODUCT,'version':'library-'+signature,'created_at':datetime.now(timezone.utc).isoformat(),'papers':len(plan['papers']),'questions':len(plan['questions']),'files':files}
    if required_program_version:manifest['required_program_version']=required_program_version
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2));z.writestr('plan.json',encoded)
        for name in sorted(assets):z.write(uploads/name,'uploads/'+name)
    with zipfile.ZipFile(output) as z:lib.read_manifest(z);assert z.testzip() is None
    output.with_suffix(output.suffix+'.sha256').write_text(lib.digest(output)+'  '+output.name+'\n',encoding='ascii')
    return {k:v for k,v in manifest.items() if k!='files'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--required-program-version');p.add_argument('--plan',required=True,type=Path);p.add_argument('--uploads',default=ROOT/'data/uploads',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    print(json.dumps(build(a.plan,a.uploads,a.output,a.required_program_version),ensure_ascii=False))
