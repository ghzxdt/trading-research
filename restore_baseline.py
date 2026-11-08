"""Preview a code/report rollback, or --apply after preserving the current version.

Data and append-only paper logs are preserved. The untouched original backup can
also be viewed with START_ORIGINAL.cmd without changing any code.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,shutil,zipfile

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');a=p.parse_args()
    manifest=json.loads((ROOT/'baseline_manifest.json').read_text(encoding='utf-8'))
    source=(ROOT/'backups'/manifest['snapshot_name']).resolve()
    assert source.is_relative_to(ROOT/'backups')
    targets=[]
    for name,meta in manifest['files'].items():
        rel=Path(name)
        if rel.parts[0]=='data':continue
        target=(ROOT/rel).resolve()
        if not target.is_relative_to(ROOT):raise ValueError('Unsafe manifest path')
        original=source/rel
        if hashlib.sha256(original.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Original backup changed: '+name)
        targets.append((original,target))
    print(f'Verified original backup. Would restore {len(targets)} code/document/report files. Current data and paper logs stay in place.')
    if not a.apply:
        print('Preview only. Use --apply to perform rollback.');return
    archive=ROOT/'backups'/('before_rollback_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in ROOT.rglob('*'):
            if f.is_file() and not any(part in {'.venv','backups','__pycache__'} or part.startswith('.output-') for part in f.relative_to(ROOT).parts):z.write(f,f.relative_to(ROOT))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Pre-rollback archive verification failed')
    for original,target in targets:
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    print('Rollback completed. Previous corrected version saved at',archive)

if __name__=='__main__':main()
