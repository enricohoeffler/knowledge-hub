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
from smb_storage import SMBStorage, Conflict

ROOT = Path(os.environ.get('KH_ROOT', '/fixtures')).resolve()
POLICY = Path(os.environ.get('KH_POLICY', '/policy.json'))
PORT = int(os.environ.get('PORT', '8099'))
HOST = os.environ.get('HOST', '127.0.0.1')
INGRESS_ONLY = os.environ.get('KH_INGRESS_ONLY') == 'yes'
SMB_OPTIONS = os.environ.get('KH_SMB_OPTIONS')
SMB = SMBStorage(json.loads(Path(SMB_OPTIONS).read_text(encoding='utf-8'))) if SMB_OPTIONS else None
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
if SMB and EXCLUSIONS_FILE.exists():
    excluded_data = json.loads(EXCLUSIONS_FILE.read_text(encoding='utf-8'))
    if not isinstance(excluded_data, list) or not all(valid_path(p) and p.casefold() != 'index.md' for p in excluded_data):
        raise SystemExit('Invalid exclusion list')
    excluded = set(excluded_data)

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
    global allowed
    if SMB:
        extensions = {'.md', '.png', '.jpg', '.jpeg', '.gif', '.webp'}
        discovered = SMB.list_files()
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
        for name, contents in data.items():
            target = docs.joinpath(*name.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        internal = docs / 'kh-internal'
        internal.mkdir()
        shutil.copyfile(Path(__file__).with_name('layout.css'), internal / 'layout.css')
        config = base / 'mkdocs.yml'
        shutil.copyfile(Path(__file__).with_name('mkdocs-template.yml'), config)
        subprocess.run(['mkdocs', 'build', '--config-file', str(config)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        output = base / 'site'
        files = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file() and not p.is_symlink()}
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
    while True:
        time.sleep(5)
        try:
            refresh()
        except Exception:
            # Never log filenames or content. The last complete generation remains available.
            pass

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
            return self.obj(200, {'excluded': items, 'available': available})
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
                if not valid_path(name) or name.casefold() == 'index.md' or action not in ('exclude', 'restore'):
                    raise ValueError()
                global source_ok
                with lock:
                    items = set(excluded)
                    if action == 'exclude':
                        if name not in allowed: raise ValueError()
                        items.add(name)
                    else:
                        if name not in items: raise ValueError()
                        items.remove(name)
                    persist_exclusions(items)
                    excluded.clear()
                    excluded.update(items)
                    source_ok = False
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
<div hidden><select id="page"></select><div id="header-actions" class="kh-header-actions"><button id="theme" class="kh-theme" type="button" aria-label="Dunkelmodus einschalten">◐ Dunkel</button></div><section id="dock" class="kh-editor"><button id="open" class="primary">✎ Bearbeiten</button><p id="msg" class="kh-status" role="status"></p><section id="editpanel" hidden><strong id="edit-title" class="kh-editor-title">Markdown bearbeiten</strong><textarea id="editor" aria-label="Markdown bearbeiten" spellcheck="false"></textarea><div class="kh-editor-actions"><button id="save" class="primary">Speichern</button><button id="restore">Letzte Sicherung laden</button><button id="close">Editor schließen</button></div></section><details id="exclusions" hidden><summary>Ausgeschlossene Dateien verwalten</summary><p>Neue Markdown-Dateien und unterstützte Bilder sind sichtbar, bis sie hier ausgeschlossen werden. Die Startseite kann nicht ausgeschlossen werden.</p><label for="exclude-page">Datei auswählen</label><select id="exclude-page"></select><button id="exclude-add" type="button">Datei ausschließen</button><ul id="exclude-list"></ul><p id="exclude-msg" role="status"></p></details><p class="kh-updated">Letzte Aktualisierung: <span id="time">–</span></p></section></div><main class="workspace"><iframe title="Leseansicht" src="site/index.html" sandbox="allow-scripts allow-same-origin"></iframe></main>
<style>html,body{height:100%;margin:0}.workspace{height:100%;padding:0}.workspace iframe{height:100%;min-height:0;border:0;border-radius:0}</style>
<script>
let revision='',opened='',current='',baseline='',saving=false,loadSeq=0,editorDocument=null; const page=document.querySelector('#page'),frame=document.querySelector('iframe'); let editor=document.querySelector('#editor'),msg=document.querySelector('#msg'),themeButton=document.querySelector('#theme'),dock=document.querySelector('#dock'),headerActions=document.querySelector('#header-actions'),panel=document.querySelector('#editpanel'),openButton=document.querySelector('#open'),editTitle=document.querySelector('#edit-title'),timeLabel=document.querySelector('#time'),saveButton=document.querySelector('#save'),restoreButton=document.querySelector('#restore'),closeButton=document.querySelector('#close');
let theme='light';try{theme=localStorage.getItem('kh-theme')||'light'}catch(e){} if(!['light','dark'].includes(theme))theme='light';
function applyTheme(){document.documentElement.dataset.theme=theme;themeButton.textContent=theme==='dark'?'☀ Hell':'◐ Dunkel';themeButton.setAttribute('aria-label',theme==='dark'?'Hellmodus einschalten':'Dunkelmodus einschalten');try{frame.contentDocument.body.dataset.mdColorScheme=theme==='dark'?'slate':'default'}catch(e){}}
function guardNavigation(doc){if(doc.__khGuard)return;doc.__khGuard=true;doc.addEventListener('click',event=>{if(event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;const link=event.target.closest?.('a[href]');if(!link||link.target&&link.target!=='_self'||link.hasAttribute('download'))return;const destination=new URL(link.href,doc.location.href),here=new URL(doc.location.href);if(destination.origin===here.origin&&destination.pathname===here.pathname&&destination.search===here.search)return;if(!panel.hidden&&opened&&(saving||editor.value!==baseline)){event.preventDefault();event.stopImmediatePropagation();if(saving){msg.textContent='Bitte warten, bis das Speichern abgeschlossen ist.';return}if(!confirm('Es gibt ungespeicherte Änderungen in '+opened+'. Seite wechseln und Änderungen verwerfen?'))return;loadSeq++;opened='';revision='';baseline='';editor.value='';panel.hidden=true;msg.textContent='';frame.src=destination.href}},true)}
function mountControls(doc,article,header){if(editorDocument===doc)return;const oldValue=editor.value,wasHidden=panel.hidden,oldMessage=msg.textContent,oldTitle=editTitle.textContent,oldTime=timeLabel.textContent;const newDock=doc.importNode(dock,true),newActions=doc.importNode(headerActions,true);dock=newDock;headerActions=newActions;editor=dock.querySelector('#editor');msg=dock.querySelector('#msg');panel=dock.querySelector('#editpanel');openButton=dock.querySelector('#open');editTitle=dock.querySelector('#edit-title');timeLabel=dock.querySelector('#time');saveButton=dock.querySelector('#save');restoreButton=dock.querySelector('#restore');closeButton=dock.querySelector('#close');themeButton=headerActions.querySelector('#theme');editor.value=oldValue;panel.hidden=wasHidden;msg.textContent=oldMessage;editTitle.textContent=oldTitle;timeLabel.textContent=oldTime;saveButton.disabled=saving;article.append(dock);header.append(headerActions);editorDocument=doc;bindControls()}
function syncPage(){try{const url=new URL(frame.contentWindow.location.href),base=new URL('site/',location.href);if(url.origin!==base.origin||!url.pathname.startsWith(base.pathname))throw Error();const doc=frame.contentDocument,article=doc.querySelector('.md-content__inner'),header=doc.querySelector('.md-header__inner');if(!article||!header)throw Error();mountControls(doc,article,header);guardNavigation(doc);const name=decodeURIComponent(url.pathname.slice(base.pathname.length)).replace(/\\.html$/,'.md');current=Array.from(page.options).some(o=>o.value===name)?name:'';page.value=current;openButton.disabled=!current;loadSeq++;if(opened&&current!==opened&&!panel.hidden)followPage()}catch(e){current='';page.value='';openButton.disabled=true}applyTheme()}
frame.onload=syncPage;fetch('api/pages').then(r=>r.json()).then(x=>{timeLabel.textContent=x.built_at||'noch nicht erfolgreich'; x.pages.forEach(p=>{let o=document.createElement('option');o.value=p;o.textContent=p;page.append(o)});syncPage()});applyTheme();
page.onchange=()=>{current=page.value;frame.src='site/'+page.value.replace(/\\.md$/,'.html')};
async function loadPage(target){const seq=++loadSeq,oldOpened=opened,oldValue=editor.value;try{const r=await fetch('api/file?path='+encodeURIComponent(target));const x=await r.json();if(seq!==loadSeq||current!==target)return;if(!r.ok){msg.textContent=x.error;return}if(opened!==oldOpened||editor.value!==oldValue){msg.textContent='Ihr Entwurf bleibt erhalten. Bitte erneut auf Bearbeiten klicken.';return}editor.value=x.content;baseline=x.content;revision=x.revision;opened=target;editTitle.textContent='Bearbeiten: '+opened;panel.hidden=false;msg.textContent='Geöffnet: '+opened}catch(e){msg.textContent='Seite konnte nicht geöffnet werden.'}}
function followPage(){if(!current||saving||editor.value!==baseline){msg.textContent='Ansicht gewechselt. Ihr Entwurf für '+opened+' bleibt geöffnet. Kehren Sie zum Speichern zurück.';return}loadPage(current)}
function bindExclusions(){const box=dock.querySelector('#exclusions');if(!box)return;const select=box.querySelector('#exclude-page'),list=box.querySelector('#exclude-list'),status=box.querySelector('#exclude-msg'),add=box.querySelector('#exclude-add');
async function render(){try{const r=await fetch('api/exclusions');if(!r.ok)return;const x=await r.json();box.hidden=false;select.replaceChildren();x.available.filter(name=>name.toLowerCase()!=='index.md').forEach(name=>{const option=box.ownerDocument.createElement('option');option.value=name;option.textContent=name;select.append(option)});if(current&&current.toLowerCase()!=='index.md')select.value=current;add.disabled=!select.value;list.replaceChildren();x.excluded.forEach(name=>{const li=box.ownerDocument.createElement('li'),button=box.ownerDocument.createElement('button');li.append(box.ownerDocument.createTextNode(name+' '));button.type='button';button.textContent='Wieder anzeigen';button.onclick=()=>change(name,'restore');li.append(button);list.append(li)})}catch(e){status.textContent='Ausschlussliste konnte nicht geladen werden.'}}
async function change(path,action){if(saving||(!panel.hidden&&editor.value!==baseline)){status.textContent='Bitte Änderungen zuerst speichern oder verwerfen.';return}try{const r=await fetch('api/exclusions',{method:'POST',headers:{'Content-Type':'application/json','X-Knowledge-Hub':'1'},body:JSON.stringify({path,action})}),x=await r.json();status.textContent=x.message||x.error;if(!r.ok)return;const pages=await(await fetch('api/pages')).json();page.replaceChildren();pages.pages.forEach(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;page.append(o)});opened='';baseline='';revision='';panel.hidden=true;frame.src='site/'+(pages.pages.includes(current)?current:'index.md').replace(/\\.md$/,'.html')}catch(e){status.textContent='Ausschlussliste konnte nicht geändert werden.'}}
add.onclick=()=>{if(select.value)change(select.value,'exclude')};box.ontoggle=()=>{if(box.open)render()};render()}
function bindControls(){bindExclusions();themeButton.onclick=()=>{theme=theme==='dark'?'light':'dark';try{localStorage.setItem('kh-theme',theme)}catch(e){}applyTheme()};
openButton.onclick=()=>{if(!current||saving)return;const dirty=!panel.hidden&&editor.value!==baseline;if(dirty&&!confirm('Den aktuellen Entwurf durch die gewählte Seite ersetzen?'))return;loadPage(current)};
closeButton.onclick=()=>{if(editor.value===baseline||confirm('Editor schließen? Ungespeicherte Änderungen bleiben nur bis zum Neuladen im Editor.'))panel.hidden=true};
saveButton.onclick=async()=>{if(saving)return;if(!opened||page.value!==opened){msg.textContent='Kehren Sie zum Speichern zur bearbeiteten Seite zurück.';return}const target=opened,content=editor.value,oldRevision=revision;saving=true;saveButton.disabled=true;try{const r=await fetch('api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:target,revision:oldRevision,content})}); const x=await r.json();msg.textContent=x.message||x.error;if(r.ok&&opened===target){revision=x.revision;baseline=content;if(current===target)frame.src='site/'+target.replace(/\\.md$/,'.html');}}catch(e){msg.textContent='Verbindung unterbrochen. Ihr Entwurf bleibt im Editor.'}finally{saving=false;saveButton.disabled=false;if(current!==opened&&!panel.hidden)followPage()}};
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
