"""Fetch locked upstream sources and apply reviewable product patches. No deployment."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def git(directory,*args,check=True):
    return subprocess.run(['git','-C',str(directory),*args],check=check,capture_output=True,text=True,encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Only verify local commits and applied patches; no network or edits')
    args=parser.parse_args()
    lock=json.loads((ROOT/'sources.lock.json').read_text(encoding='utf-8'))
    for name,spec in lock['sources'].items():
        directory=ROOT/spec['directory']
        if not (directory/'.git').exists():
            if args.check: raise SystemExit(f'{name}: missing checkout; run without --check')
            if directory.exists() and any(directory.iterdir()):raise SystemExit(f'{name}: refusing to overwrite non-Git directory')
            directory.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','clone','--no-checkout','--filter=blob:none',spec['url'],str(directory)],check=True)
            git(directory,'checkout','--detach',spec['commit'])
        current=git(directory,'rev-parse','HEAD').stdout.strip()
        if current!=spec['commit']:
            if args.check or git(directory,'status','--porcelain').stdout.strip():
                raise SystemExit(f'{name}: wrong revision; preserve your changes before switching')
            git(directory,'fetch','--depth','1','origin',spec['commit'])
            git(directory,'checkout','--detach',spec['commit'])
        for patch_name in spec['patches']:
            patch=str(ROOT/patch_name)
            if git(directory,'apply','--reverse','--check',patch,check=False).returncode==0:
                continue
            if args.check:raise SystemExit(f'{name}: patch missing or modified: {patch_name}')
            git(directory,'apply','--check',patch)
            git(directory,'apply',patch)
        print(f'{name}: locked commit and product patches OK ({spec["commit"][:12]})')

if __name__=='__main__':main()
