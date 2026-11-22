"""Knowledge Hub synthetic-only prototype. Never use this with real data."""
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit
from urllib.request import Request, urlopen
from smb_storage import SMBStorage, Conflict

ROOT = Path(os.environ.get('KH_ROOT', '/fixtures')).resolve()
POLICY = Path(os.environ.get('KH_POLICY', '/policy.json'))
PORT = int(os.environ.get('PORT', '8099'))
HOST = os.environ.get('HOST', '127.0.0.1')
INGRESS_ONLY = os.environ.get('KH_INGRESS_ONLY') == 'yes'
SMB_OPTIONS = os.environ.get('KH_SMB_OPTIONS')
app_options = json.loads(Path(SMB_OPTIONS).read_text(encoding='utf-8')) if SMB_OPTIONS else {}
SMB = SMBStorage(app_options) if SMB_OPTIONS else None
if os.environ.get('KH_SYNTHETIC_ONLY') != 'yes':
    raise SystemExit('Prototype disabled: set KH_SYNTHETIC_ONLY=yes for synthetic fixtures only')
allowed = json.loads(POLICY.read_text(encoding='utf-8'))['files']
if not isinstance(allowed, list) or len(allowed) != len(set(allowed)):
    raise SystemExit('Invalid allowlist')
lock = threading.RLock()
site = {}
built_at = None
snapshot = None
backups = {}
source_ok = False

def valid_path(s):
    if not isinstance(s, str) or not s or '\\' in s or '\x00' in s:
        return False
    p = PurePosixPath(s)
    return not p.is_absolute() and all(x not in ('', '.', '..') and not x.startswith('.') for x in s.split('/'))

if not all(valid_path(p) for p in allowed):
    raise SystemExit('Invalid allowlist path')
if any(p == 'kh-internal' or p.startswith('kh-internal/') for p in allowed):
    raise SystemExit('Reserved internal path')
allowed = frozenset(allowed)
EXCLUSIONS_FILE = Path(os.environ.get('KH_EXCLUSIONS_FILE', '/data/excluded-files.json'))
excluded = set()
directories = set()

def validated_exclusions(value):
    if not isinstance(value, list) or not all(valid_path(p) and p.casefold() != 'index.md' for p in value):
        raise ValueError('Invalid exclusion list')
    return set(value)

def sync_supervisor(items):
    if os.environ.get('KH_TEST_NO_SUPERVISOR') == 'yes':
        return
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        raise OSError('Supervisor is unavailable')
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    try:
        with urlopen(Request('http://supervisor/addons/self/info', headers=headers), timeout=10) as response:
            result = json.load(response)
        options = result['data']['options']
        if not isinstance(options, dict): raise ValueError()
        options['excluded_paths'] = sorted(items, key=str.casefold)
        body = json.dumps({'options': options}, ensure_ascii=False).encode('utf-8')
        with urlopen(Request('http://supervisor/addons/self/options', data=body, headers=headers), timeout=10) as response:
            if json.load(response).get('result') != 'ok': raise ValueError()
    except Exception as exc:
        raise OSError('Cannot update Supervisor configuration') from exc

def is_excluded(name):
    key = name.casefold()
    return any(key == item.casefold() or key.startswith(item.casefold() + '/') for item in excluded)

def persist_exclusions(items):
    EXCLUSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = EXCLUSIONS_FILE.with_name(EXCLUSIONS_FILE.name + '.tmp')
    try:
        tmp.write_text(json.dumps(sorted(items), ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, EXCLUSIONS_FILE)
    finally:
        tmp.unlink(missing_ok=True)

if SMB:
    try:
        excluded = validated_exclusions(app_options.get('excluded_paths', []))
        marker = EXCLUSIONS_FILE.with_name(EXCLUSIONS_FILE.name + '.migrated')
        if not marker.exists():
            legacy = validated_exclusions(json.loads(EXCLUSIONS_FILE.read_text(encoding='utf-8'))) if EXCLUSIONS_FILE.exists() else set()
            if legacy - excluded:
                excluded.update(legacy)
                sync_supervisor(excluded)
            persist_exclusions(excluded)
            marker.write_text('1', encoding='ascii')
    except (ValueError, OSError, json.JSONDecodeError):
        raise SystemExit('Unable to load or migrate exclusion configuration')

def file_path(name):
    if not valid_path(name) or name not in allowed:
        raise FileNotFoundError('not available')
    current = ROOT
    for part in name.split('/'):
        current = current / part
        if current.is_symlink():
            raise FileNotFoundError('not available')
    if not current.is_file() or not current.resolve().is_relative_to(ROOT):
        raise FileNotFoundError('not available')
    return current

def read(name):
    if SMB:
        if not valid_path(name) or name not in allowed:
            raise FileNotFoundError('not available')
        return SMB.read(name)
    return file_path(name).read_bytes()

def digest(b):
    return hashlib.sha256(b).hexdigest()

def collect():
    global allowed, directories
    if SMB:
        extensions = {'.md', '.png', '.jpg', '.jpeg', '.gif', '.webp'}
        discovered, discovered_dirs = SMB.list_files()
        directories = {p for p in discovered_dirs if valid_path(p) and not is_excluded(p)}
        selected = [p for p in discovered if valid_path(p) and not p.startswith('kh-internal/')
                    and Path(p).suffix.lower() in extensions and not is_excluded(p)]
        if len({p.casefold() for p in selected}) != len(selected):
            raise OSError('Ambiguous SMB filenames')
        allowed = frozenset(selected)
    return {name: read(name) for name in sorted(allowed)}

def build(data):
    # The generator receives only the explicit selection, never the source tree.
    with tempfile.TemporaryDirectory(prefix='knowledge-hub-') as temp:
        base = Path(temp)
        docs = base / 'docs'
        docs.mkdir()
        # MkDocs silently discards README.md when an index.md exists in the
        # same directory. Give READMEs a temporary, unambiguous source name.
        readmes = {name for name in data if PurePosixPath(name).name.casefold() == 'readme.md'}
        staged_names = {}
        for name in readmes:
            staged = 'kh-readme-' + hashlib.sha256(name.encode()).hexdigest()[:16] + '.md'
            while str(PurePosixPath(name).with_name(staged)) in data:
                staged = 'kh-' + staged
            staged_names[name] = staged
        for name, contents in data.items():
            staged = str(PurePosixPath(name).with_name(staged_names[name])) if name in readmes else name
            target = docs.joinpath(*staged.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        # Provide an in-memory landing page without creating a source file.
        if not (docs / 'index.md').exists():
            (docs / 'index.md').write_text('# Knowledge Hub\n\nWähle eine Seite in der Navigation.\n', encoding='utf-8')
        internal = docs / 'kh-internal'
        internal.mkdir()
        shutil.copyfile(Path(__file__).with_name('layout.css'), internal / 'layout.css')
        config = base / 'mkdocs.yml'
        shutil.copyfile(Path(__file__).with_name('mkdocs-template.yml'), config)
        subprocess.run(['mkdocs', 'build', '--config-file', str(config)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        output = base / 'site'
        files = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file() and not p.is_symlink()}
        for name in readmes:
            staged_html = staged_names[name][:-3] + '.html'
            staged_path = str(PurePosixPath(name).with_name(staged_html))
            output_path = name[:-3] + '.html'
            if staged_path not in files or output_path in files:
                raise ValueError('Build incomplete')
            files[output_path] = files.pop(staged_path)
        # Navigation and the search index refer to the temporary file name.
        for path, contents in files.items():
            if path.endswith(('.html', '.json')):
                for name in readmes:
                    contents = contents.replace((staged_names[name][:-3] + '.html').encode(), (PurePosixPath(name).name[:-3] + '.html').encode())
                files[path] = contents
        if 'index.html' not in files or 'search/search_index.json' not in files:
            raise ValueError('Build incomplete')
        for name in data:
            if name.endswith('.md') and name[:-3] + '.html' not in files:
                raise ValueError('Build incomplete')
        return files

def refresh():
    global site, built_at, snapshot, source_ok
    with lock:
        previous_allowed = allowed
        try:
            data = collect()
        except OSError:
            source_ok = False
            raise
        state = {k: digest(v) for k, v in data.items()}
        if state == snapshot:
            source_ok = True
            return False
        if SMB and not previous_allowed.issubset(allowed):
            source_ok = False
        candidate = build(data)
        # Discard a build made from a source that changed during generation.
        try:
            current = collect()
        except OSError:
            source_ok = False
            raise
        if {k: digest(v) for k, v in current.items()} != state:
            raise RuntimeError('Source changed during build')
        site, snapshot, built_at = candidate, state, time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        source_ok = True
        return True

def poll():
    previous_error = None
    while True:
        time.sleep(5)
        try:
            refresh()
            previous_error = None
        except Exception as exc:
            # Never log filenames or content. The last complete generation remains available.
            root = exc
            while root.__cause__:
                root = root.__cause__
            diagnostic = type(exc).__name__ + '/' + type(root).__name__
            if diagnostic != previous_error:
                print('Testquelle/Aktualisierung fehlgeschlagen: ' + diagnostic, flush=True)
                previous_error = diagnostic

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, code, body, kind='text/plain; charset=utf-8'):
        if isinstance(body, str): body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def obj(self, code, data):
        self.respond(code, json.dumps(data, ensure_ascii=False), 'application/json; charset=utf-8')

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == '/':
            return self.respond(200, UI, 'text/html; charset=utf-8')
        if path.path == '/api/pages':
            return self.obj(200, {'pages': sorted(p for p in allowed if p.endswith('.md')), 'built_at': built_at, 'source_ok': source_ok})
        if path.path == '/api/exclusions' and SMB:
            with lock:
                items = sorted(excluded, key=str.casefold)
                available = sorted(allowed, key=str.casefold)
                folders = sorted(directories, key=str.casefold)
            return self.obj(200, {'excluded': items, 'available': available, 'directories': folders})
        if path.path == '/api/backup':
            name = parse_qs(path.query).get('path', [''])[0]
            with lock: data = backups.get(name) if name in allowed else None
            if data is None: return self.obj(404, {'error': 'Keine Sicherung verfügbar.'})
            return self.obj(200, {'content': data.decode('utf-8')})
        if path.path == '/api/file':
            try:
                name = parse_qs(path.query).get('path', [''])[0]
                if not name.endswith('.md'): raise FileNotFoundError()
                data = read(name)
                return self.obj(200, {'content': data.decode('utf-8'), 'revision': digest(data)})
            except (OSError, UnicodeError):
                return self.obj(404, {'error': 'Seite nicht verfügbar.'})
        if path.path.startswith('/site/'):
            name = unquote(path.path[len('/site/'):]) or 'index.html'
            if not valid_path(name): return self.respond(404, 'Seite nicht verfügbar.')
            with lock:
                if not source_ok: return self.respond(503, 'Quelle nicht verfügbar.')
                data = site.get(name)
            if data is None: return self.respond(404, 'Seite nicht verfügbar oder nicht freigegeben.')
            return self.respond(200, data, mimetypes.guess_type(name)[0] or 'application/octet-stream')
        return self.respond(404, 'Seite nicht verfügbar.')

    def do_POST(self):
        if self.path == '/api/exclusions' and SMB:
            if self.headers.get('X-Knowledge-Hub') != '1' or self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
                return self.obj(403, {'error': 'Anfrage nicht zugelassen.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length < 8192: raise ValueError()
                payload = json.loads(self.rfile.read(length))
                name, action = payload['path'], payload['action']
                if not valid_path(name) or name.casefold() == 'index.md' or action != 'exclude':
                    raise ValueError()
                global source_ok
                with lock:
                    items = set(excluded)
                    if name not in allowed and name not in directories: raise ValueError()
                    items.add(name)
                    source_ok = False
                    sync_supervisor(items)
                    persist_exclusions(items)
                    excluded.clear()
                    excluded.update(items)
                    try:
                        refresh()
                    except Exception:
                        return self.obj(503, {'error': 'Liste gespeichert; Ansicht konnte nicht aktualisiert werden.'})
                return self.obj(200, {'message': 'Ausschlussliste aktualisiert.', 'excluded': sorted(excluded)})
            except (OSError, ValueError, KeyError, TypeError):
                return self.obj(400, {'error': 'Ausschlussliste konnte nicht geändert werden.'})
        if self.path != '/api/save': return self.obj(404, {'error': 'Nicht verfügbar.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 2_000_000: raise ValueError()
            payload = json.loads(self.rfile.read(length))
            name, revision, content = payload['path'], payload['revision'], payload['content']
            if not name.endswith('.md') or not isinstance(content, str): raise ValueError()
            with lock:
                old = read(name)
                if digest(old) != revision:
                    return self.obj(409, {'error': 'Die Datei wurde zwischenzeitlich geändert. Ihr Entwurf bleibt im Editor. Kopieren Sie ihn vor dem erneuten Laden und vergleichen Sie beide Fassungen.'})
                # Prototype only: another SMB writer can race this check and the replace.
                backups[name] = old
                if SMB:
                    try:
                        SMB.write(name, content.encode('utf-8'), revision, digest)
                    except Conflict:
                        return self.obj(409, {'error': 'Die Datei wurde zwischenzeitlich geändert. Ihr Entwurf bleibt im Editor.'})
                else:
                    target = file_path(name)
                    tmp = target.parent / ('.kh-' + os.urandom(12).hex())
                    try:
                        tmp.write_bytes(content.encode('utf-8'))
                        os.replace(tmp, target)
                    finally:
                        tmp.unlink(missing_ok=True)
                try:
                    refresh()
                    return self.obj(200, {'message': 'Gespeichert und Ansicht aktualisiert.', 'revision': digest(content.encode('utf-8'))})
                except Exception:
                    return self.obj(200, {'message': 'Gespeichert, aber die Ansicht konnte nicht aktualisiert werden.', 'revision': digest(content.encode('utf-8'))})
        except (ValueError, TypeError, KeyError, OSError, UnicodeError):
            return self.obj(400, {'error': 'Speichern fehlgeschlagen. Ihr Entwurf bleibt im Editor.'})

UI = '''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Knowledge Hub – Test</title>
<style>
:root{color-scheme:light;--ink:#18312f;--muted:#667b76;--line:#dce7e2;--accent:#176c59;--soft:#f0f6f2}
:root[data-theme="dark"]{color-scheme:dark;--ink:#e3eee8;--muted:#abc0b6;--line:#40574d;--accent:#50b58d;--soft:#263a32}
*{box-sizing:border-box}html,body{height:100%;margin:0}body{font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:#f1f5f2;display:flex;flex-direction:column}
header{background:#fff;border-bottom:1px solid var(--line);padding:14px 20px 12px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;align-items:center;gap:10px;min-width:0}.brand-icon{width:37px;height:37px;display:grid;place-items:center;border-radius:12px;background:#dff1e7;color:var(--accent);flex:none}.brand-icon svg{width:21px;height:21px}.brand h1{font-size:16px;letter-spacing:-.025em;line-height:1.2;margin:0}.brand p{font-size:11px;color:var(--muted);margin:2px 0 0}.badge{font-size:10px;letter-spacing:.055em;text-transform:uppercase;font-weight:700;color:#597269;background:var(--soft);border:1px solid #e0ebe4;padding:5px 8px;border-radius:100px;white-space:nowrap}
.toolbar{margin-top:13px;display:flex;align-items:end;gap:9px}.field{flex:1;min-width:0}.field label{display:block;font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:var(--muted);margin-bottom:5px}.updated{font-size:11px;color:var(--muted);margin:7px 0 0}select,button{font:inherit;border-radius:9px;min-height:37px}select{width:100%;padding:0 32px 0 11px;border:1px solid #d3e0da;background:#f8fbf9;color:var(--ink)}button{cursor:pointer;padding:0 13px;border:1px solid #d4e2db;color:var(--ink);background:white;font-weight:600}button:hover{background:#edf6f0}button:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #9ed7bb;outline-offset:2px}.primary{background:var(--accent);border-color:var(--accent);color:white}.primary:hover{background:#115543}.edit-icon{margin-right:5px}
#msg{white-space:pre-wrap;margin:10px 0 0;padding:8px 10px;background:#edf6f0;border-radius:8px;font-size:12px}#msg:empty{display:none}#editpanel{background:#fff;padding:12px 20px 14px;border-bottom:1px solid var(--line)}#editpanel[hidden]{display:none}.editor-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;font-size:12px;font-weight:700}.editor-top span{font-size:11px;color:var(--muted);font-weight:400}textarea{display:block;width:100%;height:25vh;min-height:115px;padding:12px;border:1px solid #cfddd6;border-radius:10px;background:#f9fbfa;color:#253d35;resize:vertical;font:13px/1.55 ui-monospace,Consolas,monospace}.editor-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.editor-actions button{font-size:12px}.workspace{flex:1;min-height:0;padding:10px 12px 12px}.workspace iframe{display:block;width:100%;height:100%;min-height:160px;background:white;border:1px solid var(--line);border-radius:12px;box-shadow:0 3px 16px #173c2a0b}@media(max-width:520px){header{padding:10px 12px}.badge{display:none}.toolbar{margin-top:9px}.workspace{padding:7px}.brand p{display:none}#editpanel{padding:10px 12px}}
:root[data-theme="dark"] body{background:#101b17}:root[data-theme="dark"] header,:root[data-theme="dark"] #editpanel{background:#192821}:root[data-theme="dark"] select,:root[data-theme="dark"] textarea{background:#21342b;color:var(--ink);border-color:#40574d}:root[data-theme="dark"] button:not(.primary){background:#263a32;border-color:#40574d;color:var(--ink)}:root[data-theme="dark"] .primary{background:#50b58d;border-color:#50b58d;color:#10271b}:root[data-theme="dark"] .brand-icon{background:#284a3b;color:#8cdbb2}:root[data-theme="dark"] #msg{background:#294437}:root[data-theme="dark"] .workspace iframe{background:#202c26}.top-actions{display:flex;align-items:center;gap:8px}#theme{min-height:32px;font-size:12px;padding:0 10px}.editor-top strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
<div hidden><select id="page"></select><section id="dock" class="kh-editor"><div class="kh-editor-toolbar"><button id="open" class="primary">✎ Bearbeiten</button><button id="exclude-file" class="kh-hide" type="button" hidden title="Aktuelle Datei ausblenden" aria-label="Aktuelle Datei ausblenden"><span aria-hidden="true">−</span> Datei</button><button id="exclude-folder" class="kh-hide" type="button" hidden title="Aktuellen Ordner ausblenden" aria-label="Aktuellen Ordner ausblenden"><span aria-hidden="true">−</span> Ordner</button></div><p id="msg" class="kh-status" role="status"></p><section id="editpanel" hidden><strong id="edit-title" class="kh-editor-title">Markdown bearbeiten</strong><textarea id="editor" aria-label="Markdown bearbeiten" spellcheck="false"></textarea><div class="kh-editor-actions"><button id="save" class="primary">Speichern</button><button id="restore">Letzte Sicherung laden</button><button id="close">Editor schließen</button></div></section><p class="kh-updated">Letzte Aktualisierung: <span id="time">–</span></p></section></div><main class="workspace"><iframe title="Leseansicht" src="site/index.html" sandbox="allow-scripts allow-same-origin"></iframe><div id="loading" class="loading" role="status" aria-live="polite" hidden><span class="spinner" aria-hidden="true"></span><span>Seite wird geladen …</span></div></main>
<style>html,body{height:100%;margin:0}.workspace{height:100%;padding:0;position:relative}.workspace iframe{height:100%;min-height:0;border:0;border-radius:0}.workspace iframe.pending{position:absolute;inset:0;visibility:hidden}.loading{position:absolute;right:1rem;top:1rem;z-index:10;display:flex;align-items:center;gap:.5rem;padding:.55rem .8rem;border-radius:.5rem;background:var(--kh-card,#fff);color:var(--kh-text,#222);box-shadow:0 2px 10px #0003;font:14px sans-serif}:root[data-theme="dark"] .loading{background:#1c1c1c;color:#e8e8e8}.loading[hidden]{display:none}.spinner{width:16px;height:16px;border:2px solid #90a4ae;border-top-color:#03a9f4;border-radius:50%;animation:spin .7s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>
<script>
let revision='',opened='',current='',baseline='',saving=false,loadSeq=0,editorDocument=null; const page=document.querySelector('#page'); let frame=document.querySelector('iframe'); let editor=document.querySelector('#editor'),msg=document.querySelector('#msg'),dock=document.querySelector('#dock'),panel=document.querySelector('#editpanel'),openButton=document.querySelector('#open'),editTitle=document.querySelector('#edit-title'),timeLabel=document.querySelector('#time'),saveButton=document.querySelector('#save'),restoreButton=document.querySelector('#restore'),closeButton=document.querySelector('#close');
function colorMode(value){let s=value.trim().toLowerCase(),r,g,b;if(/^#[0-9a-f]{3}$/.test(s)){r=parseInt(s[1]+s[1],16);g=parseInt(s[2]+s[2],16);b=parseInt(s[3]+s[3],16)}else if(/^#[0-9a-f]{6}([0-9a-f]{2})?$/.test(s)){r=parseInt(s.slice(1,3),16);g=parseInt(s.slice(3,5),16);b=parseInt(s.slice(5,7),16)}else{const m=s.match(/^rgba?[(] *([0-9]+)[, ]+([0-9]+)[, ]+([0-9]+)/);if(!m)return null;[r,g,b]=m.slice(1,4).map(Number)}return (r*299+g*587+b*114)/1000<128?'dark':'light'}
function themeMode(){try{const parent=window.parent;if(parent!==window){const root=parent.document.documentElement,host=parent.document.querySelector('home-assistant');if(host){const value=typeof parent.getComputedStyle==='function'?parent.getComputedStyle(root).getPropertyValue('--primary-background-color'):'';const mode=colorMode(value);if(mode)return mode;const hass=host.hass,selected=hass?.selectedTheme?.dark;if(typeof selected==='boolean')return selected?'dark':'light';const dark=hass?.themes?.darkMode;if(typeof dark==='boolean')return dark?'dark':'light'}}}catch(e){}try{return window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}catch(e){return 'light'}}
function applyTheme(){const theme=themeMode();document.documentElement.dataset.theme=theme;try{frame.contentDocument.body.dataset.mdColorScheme=theme==='dark'?'slate':'default'}catch(e){}}
if(typeof setInterval==='function')setInterval(applyTheme,1500);
let navigationSeq=0,pendingFrame=null;
async function navigateTo(target){
 const seq=++navigationSeq,loading=document.querySelector('#loading');
 if(pendingFrame){pendingFrame.remove();pendingFrame=null}loading.hidden=false;
 try{
  const response=await fetch(target);if(!response.ok)throw Error('page unavailable');if(seq!==navigationSeq)return;
  const next=document.createElement('iframe');next.className='pending';next.title='Leseansicht';next.setAttribute('sandbox','allow-scripts allow-same-origin');pendingFrame=next;
  next.onload=()=>{if(seq!==navigationSeq){next.remove();return}const previous=frame;frame=next;pendingFrame=null;syncPage();next.className='';previous.remove();loading.hidden=true};
  next.onerror=()=>{if(seq===navigationSeq){pendingFrame=null;next.remove();loading.hidden=true;msg.textContent='Seite konnte nicht geladen werden.'}};
  next.src=target;document.querySelector('.workspace').append(next);
 }catch(e){if(seq===navigationSeq){loading.hidden=true;msg.textContent='Seite konnte nicht geladen werden.'}}
}
function guardNavigation(doc){if(doc.__khGuard)return;doc.__khGuard=true;doc.addEventListener('click',event=>{if(event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;const link=event.target.closest?.('a[href]');if(!link||link.target&&link.target!=='_self'||link.hasAttribute('download'))return;const destination=new URL(link.href,doc.location.href),here=new URL(doc.location.href),base=new URL('site/',location.href);if(destination.origin===here.origin&&destination.pathname===here.pathname&&destination.search===here.search)return;if(destination.origin!==base.origin||!destination.pathname.startsWith(base.pathname)||!destination.pathname.endsWith('.html'))return;event.preventDefault();event.stopImmediatePropagation();if(!panel.hidden&&opened&&(saving||editor.value!==baseline)){if(saving){msg.textContent='Bitte warten, bis das Speichern abgeschlossen ist.';return}if(!confirm('Es gibt ungespeicherte Änderungen in '+opened+'. Seite wechseln und Änderungen verwerfen?'))return;loadSeq++;opened='';revision='';baseline='';editor.value='';panel.hidden=true;msg.textContent=''}navigateTo(destination.href)},true)}
function bindCompactSearch(doc){if(doc.__khSearch)return;doc.__khSearch=true;const input=doc.querySelector('.md-search__input');if(input){input.placeholder='Suchen';input.setAttribute('aria-label','Suchen')}doc.addEventListener('focusin',event=>{if(!event.target.matches?.('.md-search__input'))return;const toggle=doc.querySelector('[data-md-toggle="search"]');if(toggle&&!toggle.checked)doc.querySelector('label[for="__search"]')?.click()})}
function hideNavigationHeading(doc){const base=new URL('site/index.html',location.href);doc.querySelectorAll?.('.md-nav--primary > .md-nav__list > .md-nav__item > a').forEach(link=>{if(link.textContent.trim()==='Knowledge Hub'&&new URL(link.href,doc.location.href).pathname===base.pathname)link.parentElement.classList.add('kh-home-link')})}
function mountControls(doc,article){if(editorDocument===doc)return;const oldValue=editor.value,wasHidden=panel.hidden,oldMessage=msg.textContent,oldTitle=editTitle.textContent,oldTime=timeLabel.textContent;dock=doc.importNode(dock,true);editor=dock.querySelector('#editor');msg=dock.querySelector('#msg');panel=dock.querySelector('#editpanel');openButton=dock.querySelector('#open');editTitle=dock.querySelector('#edit-title');timeLabel=dock.querySelector('#time');saveButton=dock.querySelector('#save');restoreButton=dock.querySelector('#restore');closeButton=dock.querySelector('#close');editor.value=oldValue;panel.hidden=wasHidden;msg.textContent=oldMessage;editTitle.textContent=oldTitle;timeLabel.textContent=oldTime;saveButton.disabled=saving;article.append(dock);editorDocument=doc;bindControls()}
function syncPage(){try{const url=new URL(frame.contentWindow.location.href),base=new URL('site/',location.href);if(url.origin!==base.origin||!url.pathname.startsWith(base.pathname))throw Error();const doc=frame.contentDocument,article=doc.querySelector('.md-content__inner');if(!article)throw Error();mountControls(doc,article);guardNavigation(doc);bindCompactSearch(doc);hideNavigationHeading(doc);const name=decodeURIComponent(url.pathname.slice(base.pathname.length)).replace(/\\.html$/,'.md');current=Array.from(page.options).some(o=>o.value===name)?name:'';page.value=current;openButton.disabled=!current;updateHideControls();loadSeq++;if(opened&&current!==opened&&!panel.hidden)followPage()}catch(e){current='';page.value='';openButton.disabled=true}applyTheme()}
frame.onload=syncPage;fetch('api/pages').then(r=>r.json()).then(x=>{timeLabel.textContent=x.built_at||'noch nicht erfolgreich'; x.pages.forEach(p=>{let o=document.createElement('option');o.value=p;o.textContent=p;page.append(o)});syncPage()});applyTheme();
page.onchange=()=>{current=page.value;navigateTo('site/'+page.value.replace(/\\.md$/,'.html'))};
async function loadPage(target){const seq=++loadSeq,oldOpened=opened,oldValue=editor.value;try{const r=await fetch('api/file?path='+encodeURIComponent(target));const x=await r.json();if(seq!==loadSeq||current!==target)return;if(!r.ok){msg.textContent=x.error;return}if(opened!==oldOpened||editor.value!==oldValue){msg.textContent='Ihr Entwurf bleibt erhalten. Bitte erneut auf Bearbeiten klicken.';return}editor.value=x.content;baseline=x.content;revision=x.revision;opened=target;editTitle.textContent='Bearbeiten: '+opened;panel.hidden=false;msg.textContent='Geöffnet: '+opened}catch(e){msg.textContent='Seite konnte nicht geöffnet werden.'}}
function followPage(){if(!current||saving||editor.value!==baseline){msg.textContent='Ansicht gewechselt. Ihr Entwurf für '+opened+' bleibt geöffnet. Kehren Sie zum Speichern zurück.';return}loadPage(current)}
let exclusionsEnabled=false;
function updateHideControls(){const file=dock.querySelector('#exclude-file'),folder=dock.querySelector('#exclude-folder');if(!file||!folder)return;const path=current.includes('/')?current.slice(0,current.lastIndexOf('/')):'';file.hidden=!exclusionsEnabled||!current||current.toLowerCase()==='index.md';folder.hidden=!exclusionsEnabled||!path;file.title='Datei ausblenden: '+current;folder.title='Ordner einschließlich Unterordner ausblenden: '+path}
async function excludeCurrent(path,isFolder){if(!path||saving||(!panel.hidden&&editor.value!==baseline)){msg.textContent='Bitte Änderungen zuerst speichern oder verwerfen.';return}if(!confirm((isFolder?'Ordner mit allen Unterordnern':'Datei')+' ausblenden: '+path+'? Wiederanzeigen ist in der App-Konfiguration möglich.'))return;try{const r=await fetch('api/exclusions',{method:'POST',headers:{'Content-Type':'application/json','X-Knowledge-Hub':'1'},body:JSON.stringify({path,action:'exclude'})}),x=await r.json();msg.textContent=x.message||x.error;if(!r.ok)return;const pages=await(await fetch('api/pages')).json();page.replaceChildren();pages.pages.forEach(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;page.append(o)});opened='';baseline='';revision='';panel.hidden=true;navigateTo('site/index.html')}catch(e){msg.textContent='Ausblenden fehlgeschlagen.'}}
function bindControls(){const file=dock.querySelector('#exclude-file'),folder=dock.querySelector('#exclude-folder');if(file&&folder){file.onclick=()=>excludeCurrent(current,false);folder.onclick=()=>excludeCurrent(current.slice(0,current.lastIndexOf('/')),true);fetch('api/exclusions').then(r=>{exclusionsEnabled=r.ok;updateHideControls()}).catch(()=>{exclusionsEnabled=false;updateHideControls()})}
openButton.onclick=()=>{if(!current||saving)return;const dirty=!panel.hidden&&editor.value!==baseline;if(dirty&&!confirm('Den aktuellen Entwurf durch die gewählte Seite ersetzen?'))return;loadPage(current)};
closeButton.onclick=()=>{if(editor.value===baseline||confirm('Editor schließen? Ungespeicherte Änderungen bleiben nur bis zum Neuladen im Editor.'))panel.hidden=true};
saveButton.onclick=async()=>{if(saving)return;if(!opened||page.value!==opened){msg.textContent='Kehren Sie zum Speichern zur bearbeiteten Seite zurück.';return}const target=opened,content=editor.value,oldRevision=revision;saving=true;saveButton.disabled=true;try{const r=await fetch('api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:target,revision:oldRevision,content})}); const x=await r.json();msg.textContent=x.message||x.error;if(r.ok&&opened===target){revision=x.revision;baseline=content;if(current===target)navigateTo('site/'+target.replace(/\\.md$/,'.html'));}}catch(e){msg.textContent='Verbindung unterbrochen. Ihr Entwurf bleibt im Editor.'}finally{saving=false;saveButton.disabled=false;if(current!==opened&&!panel.hidden)followPage()}};
restoreButton.onclick=async()=>{if(!opened||page.value!==opened){msg.textContent='Bitte zuerst die gewählte Seite öffnen.';return}if(!confirm('Den aktuellen Entwurf im Editor durch die letzte Sicherung ersetzen?'))return;try{const r=await fetch('api/backup?path='+encodeURIComponent(opened));const x=await r.json();if(r.ok){editor.value=x.content;msg.textContent='Sicherung geladen. Zum Wiederherstellen speichern; Konfliktprüfung bleibt aktiv.'}else msg.textContent=x.error}catch(e){msg.textContent='Sicherung konnte nicht geladen werden.'}};}
</script></html>'''

class Server(ThreadingHTTPServer):
    def verify_request(self, request, client_address):
        return not INGRESS_ONLY or client_address[0] == '172.30.32.2'

if __name__ == '__main__':
    try: refresh()
    except Exception: pass
    threading.Thread(target=poll, daemon=True).start()
    Server((HOST, PORT), Handler).serve_forever()
