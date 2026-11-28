"""Read-only LUMI diagnostic. Python 3.9+. Run with --online for registry audits and browser tooling."""
import hashlib
import argparse, ast, concurrent.futures, datetime, functools, http.server, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading
P=pathlib.Path
ap=argparse.ArgumentParser(); ap.add_argument('--root',default=r'C:\LUMI'); ap.add_argument('--miniapp'); ap.add_argument('--online',action='store_true'); a=ap.parse_args()
root=P(a.root).resolve(); report=P.home()/'LUMI_CHECK_REPORT.txt'; results=[]
def record(name,status,detail=''):
    line=f'{status:5} | {name} | {detail}'; results.append(line); print(line,flush=True)
def run(cmd,cwd,timeout=120,env=None):
    try:
        p=subprocess.run([str(x) for x in cmd],cwd=cwd,env=env or clean,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout,encoding='utf-8',errors='replace')
        return p.returncode,p.stdout
    except subprocess.TimeoutExpired:return 124,''
    except OSError:return 127,''
def result(name,code):record(name,'PASS' if code==0 else 'SKIP' if code==127 else 'FAIL',f'exit={code}')
# No inherited bot, API, registry or cloud credentials in test subprocesses.
clean={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','TMPDIR','USERPROFILE','HOME','LOCALAPPDATA','APPDATA','SYSTEMDRIVE','PROGRAMFILES','PROGRAMFILES(X86)','NUMBER_OF_PROCESSORS','OS','LANG','LC_ALL'}}
clean.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PIP_CONFIG_FILE=os.devnull,NPM_CONFIG_USERCONFIG=os.devnull,NPM_CONFIG_GLOBALCONFIG=os.devnull,NPM_CONFIG_IGNORE_SCRIPTS='true',CI='true')
if not root.is_dir():sys.exit('LUMI folder not found')
options=[root/'02_MINI_APP',root/'LUMI_GENESIS_6_CORE',root/'LUMI_CORE_6_1_FIX',root/'cloudflare',root/'LUMI_GENESIS_4']
mini=P(a.miniapp).resolve() if a.miniapp else next((p for p in options if (p/'public'/'index.html').is_file()),None)
if not mini or not (mini/'public'/'index.html').is_file():sys.exit('Mini App not found; supply --miniapp PATH')
record('Selected Mini App','INFO',mini.name); record('Python','INFO',sys.version.split()[0])
# Scan source files only. No raw matches or filenames in report.
patterns=[re.compile(x,re.I) for x in [r'\b\d{7,12}:[A-Za-z0-9_-]{30,}\b',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'\b(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_-]{20,}',r'\b(?:BOT_TOKEN|TELEGRAM_BOT_TOKEN|CLOUDFLARE_API_TOKEN|API_SECRET|ADMIN_SECRET)\s*[:=]\s*[\"\'][A-Za-z0-9_:\-]{20,}[\"\']']]
allowed={'.py','.js','.mjs','.cjs','.ts','.html','.css','.json','.jsonc','.toml','.sql','.md','.txt','.yaml','.yml','.ps1','.bat','.cmd','.svg','.webp','.png','.jpg','.jpeg','.glb','.gltf','.woff','.woff2'}
def safe(p):return p.is_file() and not p.is_symlink() and p.suffix.lower() in allowed and not re.search(r'(?i)^\.(env|dev\.vars)|(?:token|secret|credential|password|backup|dump|private)',p.name) and p.stat().st_size<=50*1024*1024
def copytree(src,dst):
    if not src.is_dir():return
    for folder,dirs,files in os.walk(src,followlinks=False):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d not in {'node_modules','__pycache__','logs','uploads','backups','sessions','userdata'} and not (P(folder)/d).is_symlink()]
        for f in files:
            p=P(folder)/f
            if safe(p):q=dst/p.relative_to(src);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
botroot=root/'01_BOT' if (root/'01_BOT'/'bot.py').is_file() else root
with tempfile.TemporaryDirectory(prefix='lumi-check-') as tmp:
    t=P(tmp); b=t/'bot'; m=t/'mini'; b.mkdir();m.mkdir()
    for p in botroot.iterdir():
        if safe(p) and (p.name=='bot.py' or p.name.startswith(('lumi_','test_')) and p.suffix=='.py' or p.name=='requirements.txt'):shutil.copyfile(p,b/p.name)
    for d in ('heroes','pets'):copytree(botroot/d,b/d)
    for f in ('welcome.png',):
        if safe(botroot/f):shutil.copyfile(botroot/f,b/f)
    for d in ('public','src','tests','migrations'):copytree(mini/d,m/d)
    for f in ('package.json','package-lock.json','wrangler.jsonc'):
        if safe(mini/f):shutil.copyfile(mini/f,m/f)
    count=hits=0
    for p in [*b.rglob('*'),*m.rglob('*')]:
        if p.is_file() and p.suffix.lower() in {'.py','.js','.json','.jsonc','.html','.txt','.toml','.sql','.md','.css'}:
            count+=1; s=p.read_text(encoding='utf-8-sig',errors='replace');hits+=int(any(r.search(s) for r in patterns))
    record('Source secret patterns','FAIL' if hits else 'PASS',f'files={count}; suspicious files={hits}; heuristic only')
    for name in ('bot.py','lumi_admin.py','lumi_operations.py','lumi_daily.py','lumi_referrals.py','lumi_friend_quest.py'):
        record('Required '+name,'PASS' if (b/name).is_file() else 'FAIL')
    py=list(b.glob('*.py')); errors=0
    for p in py:
        try:ast.parse(p.read_text(encoding='utf-8-sig'))
        except (SyntaxError,UnicodeError):errors+=1
    record('Python syntax','FAIL' if errors else 'PASS',f'files={len(py)}; errors={errors}')
    # Only bundled offline tests, each in a temporary working directory. Never run bot.py itself.
    tests=sorted(b.glob('test_*.py'))
    if not tests:record('Python offline tests','SKIP','none found')
    for p in tests:
        c,output=run([sys.executable,p.name],b,45)
        errors=re.findall(r'(?m)^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))(?::|$)',output)
        record('Python '+p.name,'PASS' if c==0 else 'SKIP' if c==127 else 'FAIL',f'exit={c}'+(' ; error type='+errors[-1] if c and errors else ''))
    node=shutil.which('node'); npm=shutil.which('npm.cmd') or shutil.which('npm')
    if node:
        js=[p for p in m.rglob('*.js')]; bad=sum(run([node,'--check',p],m,20)[0]!=0 for p in js); record('JavaScript syntax','FAIL' if bad else 'PASS',f'files={len(js)}; errors={bad}')
        files=sorted((m/'tests').glob('*.test.js')); c,out=run([node,'--test',*files],m,120) if files else (127,''); summary='; '.join(re.findall(r'^# (?:tests|pass|fail|skipped) \d+',out,re.M));record('Worker tests','PASS' if c==0 else 'SKIP' if c==127 else 'FAIL',summary or f'exit={c}')
    else:record('Node tests','SKIP','Node missing')
    c,_=run([sys.executable,'-m','pip','check'],b,60);result('Installed Python dependency consistency',c)
    req=b/'requirements.txt';record('requirements.txt','PASS' if req.is_file() else 'FAIL','presence only')
    # External registry checks are optional. No bot secrets or source sent. npm audit sends dependency metadata.
    tools=t/'tools'; tools.mkdir()
    if a.online:
        if npm and (m/'package-lock.json').is_file():
            c,o=run([npm,'audit','--json','--package-lock-only','--ignore-scripts','--registry=https://registry.npmjs.org/'],m,120)
            try:
                data=json.loads(o); v=data['metadata']['vulnerabilities'];record('npm vulnerability audit','FAIL' if v.get('total',0) else 'PASS',','.join(f'{k}={v[k]}' for k in ('low','moderate','high','critical','total') if k in v))
            except Exception:record('npm vulnerability audit','SKIP',f'no usable registry response; exit={c}')
        else:record('npm vulnerability audit','SKIP','npm or lockfile missing')
        c,_=run([sys.executable,'-m','pip','--isolated','install','--disable-pip-version-check','--no-input','--index-url','https://pypi.org/simple','--target',tools,'pip-audit','playwright'],t,240)
        record('Temporary diagnostic tools','PASS' if c==0 else 'SKIP',f'exit={c}')
        if c==0:
            audit_env=dict(clean,PYTHONPATH=str(tools)); c,o=run([sys.executable,'-m','pip_audit','--format','json','--progress-spinner','off'],b,180,audit_env)
            try:
                data=json.loads(o); deps=data['dependencies']; n=sum(len(d.get('vulns',[])) for d in deps); skipped=sum(bool(d.get('skip_reason')) for d in deps);record('Installed Python vulnerability audit','FAIL' if n else 'SKIP' if skipped or c else 'PASS',f'findings={n}; skipped packages={skipped}; installed environment only')
            except Exception:record('Installed Python vulnerability audit','SKIP',f'exit={c}')
    else:record('Registry vulnerability audits','SKIP','use --online')
    # Browser test on loopback only; do not visit Telegram or the deployed API.
    sys.path.insert(0,str(tools))
    try:
        from playwright.sync_api import sync_playwright
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(m/'public')));threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=None
                for channel in ('chrome','msedge'):
                    try:browser=pw.chromium.launch(channel=channel,headless=True);break
                    except Exception:pass
                if not browser:raise RuntimeError('browser unavailable')
                for width,height in [(390,844),(360,640),(1280,800)]:
                    page=browser.new_page(viewport={'width':width,'height':height}); errs=[]; page.on('pageerror',lambda e:errs.append(1));page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                    try:
                        page.goto(base+'/',wait_until='domcontentloaded',timeout=20000);page.wait_for_timeout(1200)
                        def check(name,fn):
                            try:ok=bool(fn());record(f'UI {width} {name}','PASS' if ok else 'FAIL')
                            except Exception:record(f'UI {width} {name}','FAIL','interaction failed')
                        if page.locator('#welcome-enter').is_visible():page.locator('#welcome-enter').click(timeout=5000)
                        check('home',lambda:page.locator('#home').is_visible())
                        initial_url=page.url
                        check('collection stays inside Mini App',lambda:(page.locator('#open-collection').click(timeout=5000),page.locator('#heroes').is_visible() and page.url==initial_url and page.locator('#heroes a').count()==0 and len(page.context.pages)==1)[1])
                        check('21 heroes',lambda:page.locator('#hero-text-list button, #hero-grid button').count()==21)
                        cards=page.locator('#hero-text-list button, #hero-grid button')
                        check('hero detail',lambda:(cards.first.click(timeout=5000),page.locator('#hero-detail').is_visible())[1]);page.keyboard.press('Escape')
                        filters=page.locator('#gallery-filters button, #rank-filter button')
                        check('rank filter',lambda:(filters.nth(1).click(timeout=5000),0<cards.count()<21)[1])
                        def skins():
                            detail=page.locator('#heroes details');
                            if detail.count() and not detail.evaluate('(e)=>e.open'):detail.locator('summary').click(timeout=5000)
                            buttons=page.locator('#skin-list button');
                            if buttons.count()!=6:return False
                            hashes=set()
                            for i in range(6):
                                buttons.nth(i).click(timeout=5000)
                                if buttons.nth(i).get_attribute('aria-pressed')!='true':return False
                                image=page.locator('#skin-drop img')
                                image.evaluate('(e)=>e.decode()',timeout=5000)
                                if not image.is_visible():return False
                                hashes.add(hashlib.sha256(image.screenshot(timeout=5000,animations='disabled')).hexdigest())
                            return len(hashes)==6
                        check('six distinct rendered skin illustrations',skins)
                        check('games navigation',lambda:(page.locator('#tab-morning').click(timeout=5000),page.locator('#morning').is_visible())[1])
                        check('duel navigation',lambda:(page.locator('#tab-duel').click(timeout=5000),page.locator('#duel').is_visible())[1])
                        check('no horizontal overflow',lambda:page.evaluate('document.documentElement.scrollWidth <= innerWidth+2'))
                        check('WebGL capability',lambda:page.evaluate('!!document.createElement("canvas").getContext("webgl2") || !!document.createElement("canvas").getContext("webgl")'))
                        record(f'UI {width} uncaught JS errors','FAIL' if errs else 'PASS',f'count={len(errs)}')
                    except Exception:record(f'UI {width}','FAIL','page or interaction unavailable')
                    finally:page.close()
                browser.close()
        finally:server.shutdown();server.server_close()
    except Exception:record('Browser automation','SKIP','Playwright or installed Chrome/Edge unavailable; use --online')
    record('Production Telegram, D1, payments, visual quality, actual device FPS','SKIP','requires separate staging/manual verification')
    record('Skin geometry and clipping','SKIP','illustration comparison does not certify 3D geometry or clipping')
    counts={s:sum(x.startswith(s.ljust(5)+' |') for x in results) for s in ('PASS','FAIL','SKIP')}
    record('Release decision','INFO','NOT CERTIFIED; '+str(counts))
    report.write_text('LUMI LOCAL CHECK\n'+datetime.datetime.now().isoformat(timespec='seconds')+'\n'+'\n'.join(results)+'\n',encoding='utf-8-sig')
print('REPORT: '+str(report))
