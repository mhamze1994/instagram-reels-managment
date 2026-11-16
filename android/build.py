"""Build without Gradle/network; uses Unity's existing Android build tools. No Unity project changes."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
UNITY = Path(os.environ.get('UNITY_ANDROID', r'C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Data\PlaybackEngines\AndroidPlayer'))
JAVA = UNITY / 'OpenJDK' / 'bin'
TOOLS = UNITY / 'SDK' / 'build-tools' / '36.0.0'
ANDROID = UNITY / 'SDK' / 'platforms' / 'android-36' / 'android.jar'
OUT = ROOT / 'build'
OUT.mkdir(exist_ok=True)
for p in ['classes', 'dex', 'generated', 'compiled']:
    (OUT / p).mkdir(exist_ok=True)
env = dict(os.environ, JAVA_HOME=str(JAVA.parent))
env['PATH'] = str(JAVA) + os.pathsep + env.get('PATH', '')

def run(*args):
    subprocess.run([str(x) for x in args], check=True, env=env, cwd=ROOT)

(ROOT / 'res' / 'drawable').mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT.parent / 'static' / 'icon-512.png', ROOT / 'res' / 'drawable' / 'icon.png')
resources = OUT / 'resources.zip'
run(TOOLS / 'aapt2.exe', 'compile', '--dir', ROOT / 'res', '-o', resources)
base = OUT / 'base.apk'
run(TOOLS / 'aapt2.exe', 'link', '-I', ANDROID, '--manifest', ROOT / 'AndroidManifest.xml', '--java', OUT / 'generated', '-o', base, resources)
sources = sorted((ROOT / 'src').rglob('*.java')) + sorted((OUT / 'generated').rglob('*.java'))
argfile = OUT / 'javac.args'
argfile.write_text('\n'.join('"' + str(x).replace('\\', '/') + '"' for x in sources), encoding='utf-8')
run(JAVA / 'javac.exe', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-bootclasspath', ANDROID, '-d', OUT / 'classes', '@' + str(argfile))
classes_jar = OUT / 'classes.jar'
with zipfile.ZipFile(classes_jar, 'w') as archive:
    for path in (OUT / 'classes').rglob('*.class'):
        archive.write(path, path.relative_to(OUT / 'classes').as_posix())
run(JAVA / 'java.exe', '-cp', TOOLS / 'lib' / 'd8.jar', 'com.android.tools.r8.D8', '--min-api', '26', '--lib', ANDROID, '--output', OUT / 'dex', classes_jar)
unsigned = OUT / 'unsigned.apk'
shutil.copy2(base, unsigned)
with zipfile.ZipFile(unsigned, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in (OUT / 'dex').glob('classes*.dex'):
        archive.write(path, path.name)
aligned = OUT / 'aligned.apk'
run(TOOLS / 'zipalign.exe', '-f', '4', unsigned, aligned)
key = ROOT / '.local-signing.p12'
if not key.exists():
    # Development distribution key only. Do not commit it or include it in the server release.
    run(JAVA / 'keytool.exe', '-genkeypair', '-keystore', key, '-storetype', 'PKCS12', '-storepass', 'android',
        '-keypass', 'android', '-alias', 'quiz-studio-dev', '-dname', 'CN=Quiz Studio Development',
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650', '-noprompt')
apk = ROOT / 'Quiz-Studio.apk'
run(JAVA / 'java.exe', '-jar', TOOLS / 'lib' / 'apksigner.jar', 'sign', '--ks', key, '--ks-pass', 'pass:android',
    '--ks-key-alias', 'quiz-studio-dev', '--out', apk, aligned)
run(JAVA / 'java.exe', '-jar', TOOLS / 'lib' / 'apksigner.jar', 'verify', '--verbose', apk)
print('APK:', apk)
print('SHA256:', hashlib.sha256(apk.read_bytes()).hexdigest())
