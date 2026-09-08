"""Download Linux wheels matching the repository lockfile, on the local machine."""
from pathlib import Path
from packaging.markers import default_environment
from packaging.requirements import Requirement
import subprocess
import sys

cache=Path(__file__).resolve().parent/'.cache'
environment=default_environment()
environment.update(sys_platform='linux', os_name='posix', platform_system='Linux',
                   platform_machine='x86_64', python_version='3.12', python_full_version='3.12.3',
                   platform_release='6.8.0', implementation_name='cpython', extra='')
raw=(cache/'requirements-all.txt').read_text().replace('\\\n',' ')
lines=[]
for line in raw.splitlines():
    line=line.strip()
    if not line or line.startswith('#'): continue
    requirement=Requirement(line.split('--hash=')[0].strip())
    if requirement.marker and not requirement.marker.evaluate(environment): continue
    hashes=' '.join('--hash='+h for h in line.split('--hash=')[1:])
    lines.append(requirement.name+str(requirement.specifier)+' '+hashes)
requirements=cache/'requirements-linux.txt'
requirements.write_text('\n'.join(lines)+'\n',encoding='utf-8')
wheels=cache/'wheels'
wheels.mkdir(exist_ok=True)
args=[sys.executable,'-m','pip','download','--disable-pip-version-check','--only-binary=:all:',
      '--no-deps','--require-hashes','--python-version','3.12','--implementation','cp',
      '--abi','cp312','--abi','abi3','--abi','none']
for platform in ('manylinux_2_39_x86_64','manylinux_2_38_x86_64','manylinux_2_35_x86_64',
                 'manylinux_2_34_x86_64','manylinux_2_31_x86_64','manylinux_2_28_x86_64',
                 'manylinux_2_27_x86_64','manylinux_2_24_x86_64','manylinux_2_17_x86_64',
                 'manylinux2014_x86_64','manylinux2010_x86_64','manylinux1_x86_64','linux_x86_64'):
    args+=['--platform',platform]
args+=['-r',str(requirements),'-d',str(wheels)]
raise SystemExit(subprocess.run(args).returncode)
