# -*- coding: utf-8 -*-
"""
MANGA TRANSLATOR STUDIO - BACKEND SERVER
Servidor local Flask com estética e arquitetura moderna para o app estilo Spotify.
"""

import sys
import os
import re
import json
import time
import shutil
import zipfile
import threading
import io
import urllib.request
import urllib.error
import urllib.parse
import webbrowser
import subprocess
import traceback
import tempfile
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory, Response, redirect
from PIL import Image

# Protege contra execução via pythonw.exe onde sys.stdout e sys.stderr são None
class SafeDummyStream(io.StringIO):
    def write(self, s):
        try:
            return len(s) if s else 0
        except Exception:
            return 0
    def flush(self):
        pass
    def isatty(self):
        return False
    def fileno(self):
        raise io.UnsupportedOperation("fileno")

if sys.stdout is None:
    sys.stdout = SafeDummyStream()
if sys.stderr is None:
    sys.stderr = SafeDummyStream()
if getattr(sys, '__stdout__', None) is None:
    sys.__stdout__ = sys.stdout
if getattr(sys, '__stderr__', None) is None:
    sys.__stderr__ = sys.stderr

try:
    import tqdm.std as _tqdm_std
    _orig_tqdm_init_srv = _tqdm_std.tqdm.__init__
    def _safe_tqdm_init_srv(self, *args, **kwargs):
        if kwargs.get('file') is None:
            kwargs['file'] = sys.stderr if sys.stderr is not None else sys.stdout
        if kwargs.get('file') is None:
            kwargs['file'] = SafeDummyStream()
        return _orig_tqdm_init_srv(self, *args, **kwargs)
    _tqdm_std.tqdm.__init__ = _safe_tqdm_init_srv
except Exception:
    pass

# Inclui diretório principal no path e define como cwd
SYS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(SYS_DIR)
if SYS_DIR not in sys.path:
    sys.path.insert(0, SYS_DIR)

import auto_translate

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Configurações globais e Versão Oficial
try:
    from version import __version__, __version_name__, get_version_info
except Exception:
    __version__ = "0.2.0-beta"
    __version_name__ = "v0.2.0 Beta"

APP_VERSION = __version__
APP_VERSION_NAME = __version_name__

@app.context_processor
def inject_version():
    return {
        "app_version": APP_VERSION_NAME,
        "app_version_code": APP_VERSION
    }

BASE_MANGAS_DIR = r"C:\Users\ja329\OneDrive\Documentos\MANGAS"
THUMB_CACHE_DIR = os.path.join(SYS_DIR, ".thumb_cache")
os.makedirs(THUMB_CACHE_DIR, exist_ok=True)

# Mapeamento para leitura e download web seguro
MANGA_PATH_CACHE = {}

def find_drive_roots():
    """Retorna lista de caminhos raiz do Google Drive encontrados (Linux/Colab e Windows)."""
    candidates = [
        "/content/drive/MyDrive",
        "G:\\Meu Drive",
        "G:\\My Drive",
        os.path.expanduser("~/Google Drive"),
        os.path.expanduser("~/Meu Drive")
    ]
    if os.name == 'nt':
        import string
        for letter in string.ascii_uppercase:
            candidates.append(f"{letter}:\\Meu Drive")
            candidates.append(f"{letter}:\\My Drive")
            
    roots = []
    for c in candidates:
        if os.path.exists(c) and c not in roots:
            roots.append(c)
    return roots

def is_drive_path(p):
    """Verifica se o caminho informado está dentro de um Google Drive montado."""
    if not p:
        return False
    clean = os.path.abspath(p).replace('\\', '/').lower()
    if '/content/drive' in clean:
        return True
    for r in find_drive_roots():
        if os.path.abspath(r).replace('\\', '/').lower() in clean:
            return True
    return False

def _get_pymupdf():
    """Importa PyMuPDF de forma segura (suportando import pymupdf ou import fitz legado)."""
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz
            return fitz
        except ImportError:
            return None

def extract_manga_pdf(pdf_path, target_dir=None):
    """
    Extrai todas as páginas de um mangá/manhwa em PDF para uma pasta de imagens sequenciais (0001.png, 0002.jpg, ...).
    Usa extração nativa sem perdas quando a página for apenas uma imagem escaneada limpa,
    e renderiza em alta resolução (~220 DPI RGB) quando houver texto, rotação ou composição.
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    fitz = _get_pymupdf()
    if fitz is None:
        raise RuntimeError("Biblioteca 'pymupdf' não instalada para leitura de PDF. Execute: pip install pymupdf")

    pdf_path = os.path.abspath(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    if not target_dir:
        target_dir = os.path.join(os.path.dirname(pdf_path), base_name)
    os.makedirs(target_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    try:
        if doc.is_encrypted:
            try:
                doc.authenticate("")
            except Exception:
                pass
            if doc.needs_pass:
                raise ValueError("Este arquivo PDF está protegido por senha.")

        if len(doc) == 0:
            return None

        for idx, page in enumerate(doc):
            out_prefix = f"{idx + 1:04d}"
            saved = False
            try:
                imgs = page.get_images(full=True)
                text = (page.get_text("text") or "").strip()
                # Se for página de scan puro (1 única imagem sem máscara alpha, sem texto e sem rotação)
                if len(imgs) == 1 and imgs[0][1] == 0 and not text and page.rotation == 0:
                    xref = imgs[0][0]
                    page_area = max(abs(page.rect.width * page.rect.height), 1.0)
                    img_rects = page.get_image_rects(xref)
                    covers_page = any(abs(r.width * r.height) / page_area >= 0.85 for r in img_rects)
                    if covers_page:
                        base_img = doc.extract_image(xref)
                        w = base_img.get("width", 0)
                        h = base_img.get("height", 0)
                        ext = (base_img.get("ext") or "").lower()
                        if ext == "jpeg":
                            ext = "jpg"
                        img_bytes = base_img.get("image")
                        if img_bytes and w >= 500 and h >= 500 and ext in ("jpg", "png", "webp"):
                            with Image.open(io.BytesIO(img_bytes)) as im:
                                if im.mode in ("RGB", "L"):
                                    with open(os.path.join(target_dir, f"{out_prefix}.{ext}"), "wb") as out_f:
                                        out_f.write(img_bytes)
                                    saved = True
                                elif im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                                    bg = Image.new("RGB", im.size, (255, 255, 255))
                                    rgba = im.convert("RGBA")
                                    bg.paste(rgba, mask=rgba.split()[3])
                                    bg.save(os.path.join(target_dir, f"{out_prefix}.png"), "PNG")
                                    saved = True
                                else:
                                    im.convert("RGB").save(os.path.join(target_dir, f"{out_prefix}.png"), "PNG")
                                    saved = True
            except Exception:
                saved = False

            if not saved:
                rect = page.rect
                max_dim = max(rect.width, rect.height, 1.0)
                min_dim = min(rect.width, rect.height, 1.0)
                zoom = 220.0 / 72.0
                if min_dim * zoom < 1200:
                    zoom = 1200.0 / min_dim
                if max_dim * zoom > 3200:
                    zoom = 3200.0 / max_dim
                zoom = max(zoom, 1.0)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
                pix.save(os.path.join(target_dir, f"{out_prefix}.png"))
    finally:
        doc.close()

    return target_dir

def extract_manga_archive(archive_path, target_dir=None):
    """
    Descompacta um arquivo .zip, .cbz ou .pdf em target_dir.
    Se todas as imagens estiverem dentro de uma subpasta única descompactada (ZIP/CBZ),
    move todas as imagens para a raiz do target_dir.
    Retorna o caminho final da pasta com as imagens.
    """
    if not archive_path or not os.path.exists(archive_path):
        return None
        
    archive_path = os.path.abspath(archive_path)
    if archive_path.lower().endswith('.pdf'):
        return extract_manga_pdf(archive_path, target_dir)

    base_name = os.path.splitext(os.path.basename(archive_path))[0]
    
    if not target_dir:
        parent_dir = os.path.dirname(archive_path)
        target_dir = os.path.join(parent_dir, base_name)
        
    os.makedirs(target_dir, exist_ok=True)
    
    with zipfile.ZipFile(archive_path, 'r') as z:
        z.extractall(target_dir)
        
    # Organização de subpastas aninhadas (se o ZIP tiver apenas uma subpasta interna com as imagens)
    subdirs = [os.path.join(target_dir, d) for d in os.listdir(target_dir) if os.path.isdir(os.path.join(target_dir, d))]
    root_imgs = [f for f in os.listdir(target_dir) if f.lower().endswith(('.jpg','.jpeg','.png','.webp','.bmp','.gif'))]
    if len(subdirs) == 1 and not root_imgs:
        only_sub = subdirs[0]
        for f in os.listdir(only_sub):
            shutil.move(os.path.join(only_sub, f), os.path.join(target_dir, f))
        try:
            os.rmdir(only_sub)
        except Exception:
            pass
            
    return target_dir

def get_manga_hash(folder_path):
    if not folder_path: return ""
    p = os.path.abspath(folder_path)
    h = str(abs(hash(p)))
    MANGA_PATH_CACHE[h] = p
    return h

# Estado global da tarefa de tradução
job_lock = threading.Lock()
job_state = {
    "status": "idle",       # "idle", "running", "done", "error"
    "manga_name": "",
    "manga_path": "",
    "first_img": "",
    "stage": "",            # "ocr", "translation", "diagram", "done"
    "current_page": 0,
    "total_pages": 0,
    "percentage": 0,
    "message": "Aguardando mangá...",
    "logs": [],
    "result": None,
    "error": None,
    "start_time": 0
}

class StreamCapture(io.StringIO):
    """Intercepta stdout e stderr para transmitir logs em tempo real ao frontend."""
    def __init__(self, original_stream=None, max_lines=300):
        super().__init__()
        self.max_lines = max_lines
        self.original_stream = original_stream

    def write(self, text):
        if text:
            clean_text = str(text)
            if clean_text.strip():
                with job_lock:
                    for line in clean_text.strip().split("\n"):
                        clean = line.strip()
                        if clean and not clean.startswith("\r"):
                            job_state["logs"].append(clean)
                            if len(job_state["logs"]) > self.max_lines:
                                job_state["logs"].pop(0)
        if self.original_stream is not None:
            w_fn = getattr(self.original_stream, 'write', None)
            if callable(w_fn):
                try:
                    w_fn(text)
                except Exception:
                    pass

    def flush(self):
        if self.original_stream is not None:
            f_fn = getattr(self.original_stream, 'flush', None)
            if callable(f_fn):
                try:
                    f_fn()
                except Exception:
                    pass

    def isatty(self):
        return False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/manifest.json")
def manifest():
    return send_from_directory(os.path.join(app.root_path, "static"), "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/x-icon")

def check_single_groq_key(idx, key):
    key = str(key).strip()
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    k_data = {
        "index": idx + 1,
        "masked_key": masked,
        "key": key,
        "ok": True,
        "models": {}
    }
    for m in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        data = json.dumps({"model": m, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                k_data["models"][m] = {
                    "ok": True,
                    "rem_req": int(resp.headers.get("x-ratelimit-remaining-requests", 1000)),
                    "lim_req": int(resp.headers.get("x-ratelimit-limit-requests", 1000)),
                    "rem_tok": int(resp.headers.get("x-ratelimit-remaining-tokens", 8000)),
                    "lim_tok": int(resp.headers.get("x-ratelimit-limit-tokens", 8000)),
                    "rst_req": resp.headers.get("x-ratelimit-reset-requests", "0s"),
                    "rst_tok": resp.headers.get("x-ratelimit-reset-tokens", "0s")
                }
        except urllib.error.HTTPError as e:
            err_text = ""
            try: err_text = e.read().decode("utf-8", errors="ignore")
            except Exception: pass
            is_tpd = "TPD" in err_text or "tokens per day" in err_text.lower()
            k_data["models"][m] = {
                "ok": False,
                "code": e.code,
                "is_daily_limit": is_tpd,
                "msg": "Cota diária de 200k tokens atingida" if is_tpd else f"HTTP {e.code}"
            }
        except Exception as e:
            k_data["models"][m] = {"ok": False, "msg": str(e)}
    return k_data

@app.route("/api/status")
def api_status():
    """Consulta cotas ao vivo de TODAS as chaves cadastradas do Groq, OpenRouter e Ollama."""
    cfg = auto_translate.load_config()
    res = {
        "groq": {
            "configured": False,
            "keys": [],
            "models": {},
            "total_qwen_remaining": 0,
            "total_qwen_limit": 0,
            "active_model": cfg.get("groq_model", "qwen/qwen3.8-27b")
        },
        "openrouter": {"configured": False, "keys": []},
        "gemini": {
            "configured": False,
            "keys": [],
            "active_model": cfg.get("gemini_model", "gemini-2.5-flash")
        },
        "ollama": {"status": "offline", "models": [], "vision_models": []},
        "vision": {
            "provider": cfg.get("vision_provider", "auto"),
            "gemini_model": cfg.get("gemini_model", "gemini-2.5-flash"),
            "groq_vision_model": cfg.get("groq_vision_model", "qwen/qwen3.8-27b"),
            "openrouter_vision_model": cfg.get("openrouter_vision_model", auto_translate.OPENROUTER_DEFAULT_VISION_MODELS[0]),
            "ollama_vision_model": cfg.get("ollama_vision_model", "")
        }
    }
    
    # 1. GROQ POOL (MULTI-CHAVES CONCORRENTES)
    groq_keys = cfg.get("groq_api_keys", [])
    if not groq_keys and cfg.get("groq_api_key"):
        groq_keys = [cfg.get("groq_api_key")]
    
    if groq_keys:
        res["groq"]["configured"] = True
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(groq_keys), 6)) as executor:
            groq_results = list(executor.map(lambda ik: check_single_groq_key(ik[0], ik[1]), enumerate(groq_keys)))
        
        res["groq"]["keys"] = groq_results
        if groq_results:
            res["groq"]["models"] = groq_results[0].get("models", {})
            res["groq"]["masked_key"] = groq_results[0].get("masked_key", "***")
            
        total_rem = sum(k["models"].get("qwen/qwen3.8-27b", {}).get("rem_req", 0) for k in groq_results if k["models"].get("qwen/qwen3.8-27b", {}).get("ok"))
        res["groq"]["total_qwen_remaining"] = total_rem
        res["groq"]["total_qwen_limit"] = len(groq_results) * 1000

    # 2. OPENROUTER
    or_keys = cfg.get("openrouter_api_keys", [])
    if not or_keys and cfg.get("openrouter_api_key"):
        or_keys = [cfg.get("openrouter_api_key")]
    if or_keys:
        res["openrouter"]["configured"] = True
        for idx, k in enumerate(or_keys):
            k_info = {"index": idx + 1, "key": k[:8] + "..." + k[-4:] if len(k) > 12 else "***", "ok": False}
            try:
                req_or = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {k}"})
                with urllib.request.urlopen(req_or, timeout=5) as resp:
                    kdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    free_info = kdata.get("free_model_daily_requests", {})
                    k_info["ok"] = True
                    k_info["free_used"] = free_info.get("used", 0)
                    k_info["free_limit"] = free_info.get("limit", 50)
                    k_info["free_rem"] = free_info.get("remaining", 0)
            except Exception as e:
                k_info["err"] = str(e)
            try:
                req_c = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {k}"})
                with urllib.request.urlopen(req_c, timeout=5) as resp:
                    cdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    k_info["credits"] = float(cdata.get("total_credits", 0))
            except Exception:
                k_info["credits"] = 0.0
            res["openrouter"]["keys"].append(k_info)

    # 3. GOOGLE GEMINI VISION
    gem_keys = [
        str(k).strip() for k in (cfg.get("gemini_api_keys") or [])
        if str(k or "").strip() and not str(k).strip().startswith(("gsk_", "sk-or-"))
    ]
    if not gem_keys and cfg.get("gemini_api_key"):
        sk_g = str(cfg.get("gemini_api_key")).strip()
        if sk_g and not sk_g.startswith(("gsk_", "sk-or-")):
            gem_keys = [sk_g]
    if gem_keys:
        res["gemini"]["configured"] = True
        for idx, k in enumerate(gem_keys):
            k_info = {"index": idx + 1, "key": k[:8] + "..." + k[-4:] if len(k) > 12 else "***", "ok": False}
            try:
                qs = urllib.parse.urlencode({"key": k})
                req_gm = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models?{qs}")
                with urllib.request.urlopen(req_gm, timeout=5) as resp:
                    if resp.status == 200:
                        gm_data = json.loads(resp.read().decode("utf-8"))
                        gm_models = [m.get("name", "") for m in gm_data.get("models", [])]
                        k_info["ok"] = True
                        k_info["models_count"] = len(gm_models)
                        k_info["msg"] = f"Ativa ({len(gm_models)} modelos Gemini disponíveis)"
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    k_info["ok"] = True
                    k_info["rate_limited"] = True
                    k_info["msg"] = "Válida (em pausa breve RPM)"
                else:
                    k_info["msg"] = f"Erro HTTP {e.code}"
            except Exception as e:
                k_info["msg"] = str(e)
            res["gemini"]["keys"].append(k_info)

    # 4. OLLAMA
    ol_host = cfg.get("ollama_host", "http://localhost:11434").rstrip("/")
    try:
        req_ol = urllib.request.Request(f"{ol_host}/api/tags")
        with urllib.request.urlopen(req_ol, timeout=2) as resp:
            if resp.status == 200:
                odata = json.loads(resp.read().decode("utf-8"))
                models_list = [m.get("name") for m in odata.get("models", [])]
                res["ollama"]["status"] = "online"
                res["ollama"]["models"] = models_list
                res["ollama"]["vision_models"] = [m for m in models_list if auto_translate.is_ollama_vision_model_name(m)]
    except Exception:
        res["ollama"]["status"] = "offline"

    res["version"] = APP_VERSION
    res["version_name"] = APP_VERSION_NAME
    return jsonify(res)

@app.route("/api/version")
def api_version():
    """Retorna detalhes da versão da aplicação e arquitetura de IA ativa."""
    return jsonify({
        "version": APP_VERSION,
        "version_name": APP_VERSION_NAME,
        "release": f"Manga Studio {APP_VERSION_NAME}",
        "dual_engine": True,
        "features": [
            "IA Vision Híbrido (Detector Geométrico Local + Gemini / Groq / OpenRouter / Ollama Vision)",
            "OCR Especializado Japonês PP-OCRv6_manga, Coreano PP-OCRv5 & Suporte Nativo a PDF / CBZ / ZIP",
            "Cooperative Dual-Engine (Spatial Cartographer + Narrative Synthesizer)",
            "Delete Manga & Fast Library Management",
            "Persistent User Profile & Auto-Key Sync (Google Drive + Browser)",
            "Automated SemVer Versioning (Grandes, Médios e Pequenos)",
            "Interface Mobile Responsiva (PWA) & Leitor Web Interativo",
            "Hybrid Local/Cloud AI (Groq + OpenRouter + Ollama GPU)"
        ]
    })

@app.route("/api/library")
def api_library():
    """Retorna mangás traduzidos e obras prontas para traduzir, respeitando pastas locais, Google Drive e uploads."""
    cfg = auto_translate.load_config()
    raw_dir = cfg.get("raw_mangas_dir") or BASE_MANGAS_DIR
    trans_dir = cfg.get("translated_mangas_dir") or BASE_MANGAS_DIR
    
    translated = []
    raw = []
    seen_paths = set()
    
    def _scan(folder_path):
        entries = []
        if not folder_path or not os.path.exists(folder_path):
            return entries
        for item in sorted(os.listdir(folder_path)):
            full_p = os.path.abspath(os.path.join(folder_path, item))
            if full_p in seen_paths or item.startswith(".") or item == "_ocr":
                continue

            # 1. Pastas com imagens
            if os.path.isdir(full_p):
                imgs = [f for f in os.listdir(full_p) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                # Se não houver imagens diretas, checa se há subpastas imediatas de capítulos
                if not imgs:
                    subdirs = [os.path.join(full_p, d) for d in os.listdir(full_p) if os.path.isdir(os.path.join(full_p, d)) and not d.startswith(".")]
                    for sub in subdirs:
                        sub_imgs = [f for f in os.listdir(sub) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                        if sub_imgs:
                            imgs = sub_imgs
                            break
                if not imgs:
                    continue
                seen_paths.add(full_p)
                has_reader = os.path.exists(os.path.join(full_p, "leitor.html"))
                cbz_path = full_p.rstrip("/\\") + ".cbz"
                has_cbz = os.path.exists(cbz_path)
                first_img = os.path.join(full_p, sorted(imgs)[0])
                mtime = os.path.getmtime(full_p)
                m_id = get_manga_hash(full_p)
                entry = {
                    "id": m_id,
                    "name": item,
                    "clean_name": item.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                    "path": full_p,
                    "pages": len(imgs),
                    "has_reader": has_reader,
                    "has_cbz": has_cbz,
                    "cbz_path": cbz_path if has_cbz else None,
                    "reader_path": os.path.join(full_p, "leitor.html") if has_reader else None,
                    "reader_url": f"/read/{m_id}/",
                    "mtime": mtime,
                    "first_img": first_img,
                    "is_drive": is_drive_path(full_p),
                    "is_archive": False
                }
                entries.append(entry)

            # 2. Arquivos compactados ou PDF (.zip, .cbz ou .pdf)
            elif os.path.isfile(full_p) and item.lower().endswith(('.zip', '.cbz', '.pdf')):
                # Se já houver uma pasta com o mesmo nome descompactada contendo imagens, evita duplicar
                unpacked_candidate = os.path.splitext(full_p)[0]
                if unpacked_candidate in seen_paths:
                    continue
                if os.path.exists(unpacked_candidate) and os.path.isdir(unpacked_candidate):
                    has_imgs = any(f.lower().endswith(('.jpg','.jpeg','.png','.webp')) for f in os.listdir(unpacked_candidate))
                    if has_imgs:
                        continue

                if item.lower().endswith('.pdf'):
                    fitz = _get_pymupdf()
                    if fitz is None:
                        continue
                    try:
                        doc = fitz.open(full_p)
                        try:
                            num_pages = len(doc)
                        finally:
                            doc.close()
                        if num_pages <= 0:
                            continue
                        seen_paths.add(full_p)
                        mtime = os.path.getmtime(full_p)
                        m_id = get_manga_hash(full_p)
                        clean_n = os.path.splitext(item)[0]
                        entries.append({
                            "id": m_id,
                            "name": clean_n,
                            "clean_name": clean_n.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                            "path": full_p,
                            "pages": num_pages,
                            "has_reader": False,
                            "has_cbz": False,
                            "cbz_path": None,
                            "reader_path": None,
                            "reader_url": None,
                            "mtime": mtime,
                            "first_img": f"{full_p}::page0",
                            "is_drive": is_drive_path(full_p),
                            "is_archive": True,
                            "archive_type": "PDF"
                        })
                    except Exception:
                        pass
                else:
                    try:
                        with zipfile.ZipFile(full_p, 'r') as z:
                            zip_imgs = [info.filename for info in z.infolist() if not info.is_dir() and info.filename.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                            if not zip_imgs:
                                continue
                            zip_imgs.sort()
                            seen_paths.add(full_p)
                            mtime = os.path.getmtime(full_p)
                            m_id = get_manga_hash(full_p)
                            clean_n = os.path.splitext(item)[0]
                            arc_type = "CBZ" if item.lower().endswith(".cbz") else "ZIP"
                            entries.append({
                                "id": m_id,
                                "name": clean_n,
                                "clean_name": clean_n.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                                "path": full_p,
                                "pages": len(zip_imgs),
                                "has_reader": False,
                                "has_cbz": False,
                                "cbz_path": None,
                                "reader_path": None,
                                "reader_url": None,
                                "mtime": mtime,
                                "first_img": f"{full_p}::{zip_imgs[0]}",
                                "is_drive": is_drive_path(full_p),
                                "is_archive": True,
                                "archive_type": arc_type
                            })
                    except Exception:
                        pass

        return entries

    # Pastas de escaneamento de mangás traduzidos
    trans_scan_folders = [trans_dir]
    raw_scan_folders = [raw_dir]
    
    for r in find_drive_roots():
        t_drive = os.path.join(r, "MANGAS [PT-BR]")
        if os.path.exists(t_drive) and t_drive not in trans_scan_folders:
            trans_scan_folders.insert(0, t_drive)
        r_drive = os.path.join(r, "MANGAS")
        if os.path.exists(r_drive) and r_drive not in raw_scan_folders:
            raw_scan_folders.insert(0, r_drive)
            
    if os.path.exists(UPLOAD_DIR):
        if UPLOAD_DIR not in trans_scan_folders:
            trans_scan_folders.append(UPLOAD_DIR)
        if UPLOAD_DIR not in raw_scan_folders:
            raw_scan_folders.append(UPLOAD_DIR)

    for sf in trans_scan_folders:
        for e in _scan(sf):
            if "[PT-BR]" in e["name"] or e["has_reader"]:
                translated.append(e)
            else:
                raw.append(e)

    for rf in raw_scan_folders:
        for e in _scan(rf):
            if not e["has_reader"] and "[PT-BR]" not in e["name"]:
                raw.append(e)
                
    translated.sort(key=lambda x: x["mtime"], reverse=True)
    raw.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"translated": translated, "raw": raw})

@app.route("/api/download_folder")
def api_download_folder():
    """Compacta a pasta traduzida em um arquivo ZIP e envia diretamente para download no navegador."""
    path = request.args.get("path", "").strip('\"\'')
    if not path or not os.path.exists(path):
        return jsonify({"error": "Pasta não encontrada"}), 404
        
    folder_path = os.path.abspath(path)
    if os.path.isfile(folder_path):
        folder_path = os.path.dirname(folder_path)
        
    clean_name = os.path.basename(folder_path)
    zip_dest = os.path.join(tempfile.gettempdir(), f"{clean_name}.zip")
    
    with zipfile.ZipFile(zip_dest, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            if "cache" in root or "__pycache__" in root:
                continue
            for file in files:
                # Inclui apenas imagens traduzidas e leitor para evitar erros de caminho longo (0x80010135) no Windows
                if not file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.html')):
                    continue
                full_f = os.path.join(root, file)
                rel_f = os.path.relpath(full_f, folder_path)
                zipf.write(full_f, arcname=rel_f)
                
    return send_file(zip_dest, as_attachment=True, download_name=f"{clean_name}.zip", mimetype="application/zip")

@app.route("/api/download_cbz")
def api_download_cbz():
    """Envia o arquivo .cbz do mangá traduzido diretamente para download no navegador."""
    path = request.args.get("path", "").strip('\"\'')
    if not path:
        return jsonify({"error": "Caminho não fornecido"}), 400
        
    clean_p = os.path.abspath(path)
    if os.path.isdir(clean_p):
        cbz_candidate = clean_p.rstrip("/\\") + ".cbz"
        if not os.path.exists(cbz_candidate):
            try:
                auto_translate.create_cbz_archive(clean_p, cbz_candidate)
            except Exception as e:
                return jsonify({"error": f"Erro ao criar CBZ: {e}"}), 500
        clean_p = cbz_candidate
    elif not os.path.exists(clean_p):
        alt = clean_p.rstrip("/\\") + ".cbz"
        if os.path.exists(alt):
            clean_p = alt
        else:
            return jsonify({"error": "Arquivo CBZ não encontrado"}), 404
            
    if not os.path.exists(clean_p):
        return jsonify({"error": "Arquivo CBZ não encontrado"}), 404
            
    cbz_name = os.path.basename(clean_p)
    return send_file(clean_p, as_attachment=True, download_name=cbz_name, mimetype="application/vnd.comicbook+zip")

@app.route("/api/reader")
def api_reader():
    """Redireciona para o leitor web imersivo a partir do parâmetro path."""
    path = request.args.get("path", "").strip('\"\'')
    if not path or not os.path.exists(path):
        return "Caminho do mangá não encontrado", 404
        
    folder = os.path.dirname(os.path.abspath(path)) if (os.path.isfile(path) and path.endswith(".html")) else os.path.abspath(path)
    h = get_manga_hash(folder)
    return redirect(f"/read/{h}/")

@app.route("/read/<manga_id>/")
@app.route("/read/<manga_id>/<path:filename>")
def serve_manga_reader(manga_id, filename="leitor.html"):
    """Serve o leitor web interativo diretamente no navegador para qualquer dispositivo."""
    folder = MANGA_PATH_CACHE.get(manga_id)
    if not folder or not os.path.exists(folder):
        return "Mangá não encontrado na memória do servidor. Por favor, volte à biblioteca e clique em Ler.", 404
        
    leitor_p = os.path.join(folder, "leitor.html")
    if filename == "leitor.html":
        needs_refresh = not os.path.exists(leitor_p)
        if not needs_refresh:
            try:
                with open(leitor_p, "r", encoding="utf-8", errors="ignore") as lf:
                    head_txt = lf.read(512)
                if "manga-studio-reader-v2" not in head_txt:
                    needs_refresh = True
            except Exception:
                pass
        if needs_refresh:
            try:
                auto_translate.create_html_reader(folder, os.path.basename(folder))
            except Exception:
                pass
        
    return send_from_directory(folder, filename)

@app.route("/api/thumb")
def api_thumb():
    """Gera miniatura otimizada da capa do mangá (pasta ou arquivo .zip/.cbz/.pdf)."""
    img_path = request.args.get("path", "")
    if not img_path:
        return "", 404
        
    try:
        thumb_name = str(abs(hash(img_path))) + ".jpg"
        thumb_dest = os.path.join(THUMB_CACHE_DIR, thumb_name)
        if not os.path.exists(thumb_dest):
            # Caso 1: Capa de PDF (arquivo.pdf::page0) ou Imagem dentro de ZIP/CBZ (arquivo.zip::inner_img)
            if "::" in img_path:
                arc_p, inner_f = img_path.split("::", 1)
                if not os.path.exists(arc_p):
                    return "", 404
                if arc_p.lower().endswith('.pdf'):
                    fitz = _get_pymupdf()
                    if fitz is None:
                        return "", 404
                    doc = fitz.open(arc_p)
                    try:
                        if len(doc) == 0:
                            return "", 404
                        pix = doc[0].get_pixmap(dpi=96, colorspace=fitz.csRGB, alpha=False)
                        with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
                            im = im.convert("RGB")
                            im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                            im.save(thumb_dest, "JPEG", quality=85)
                    finally:
                        doc.close()
                else:
                    with zipfile.ZipFile(arc_p, 'r') as z:
                        with z.open(inner_f) as zf:
                            with Image.open(io.BytesIO(zf.read())) as im:
                                im = im.convert("RGB")
                                im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                                im.save(thumb_dest, "JPEG", quality=85)
            # Caso 2: Caminho direto de arquivo .pdf
            elif os.path.isfile(img_path) and img_path.lower().endswith('.pdf'):
                fitz = _get_pymupdf()
                if fitz is None:
                    return "", 404
                doc = fitz.open(img_path)
                try:
                    if len(doc) == 0:
                        return "", 404
                    pix = doc[0].get_pixmap(dpi=96, colorspace=fitz.csRGB, alpha=False)
                    with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
                        im = im.convert("RGB")
                        im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                        im.save(thumb_dest, "JPEG", quality=85)
                finally:
                    doc.close()
            # Caso 3: Caminho direto de arquivo .zip ou .cbz
            elif os.path.isfile(img_path) and img_path.lower().endswith(('.zip', '.cbz')):
                with zipfile.ZipFile(img_path, 'r') as z:
                    zip_imgs = [info.filename for info in z.infolist() if not info.is_dir() and info.filename.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                    if not zip_imgs:
                        return "", 404
                    zip_imgs.sort()
                    with z.open(zip_imgs[0]) as zf:
                        with Image.open(io.BytesIO(zf.read())) as im:
                            im = im.convert("RGB")
                            im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                            im.save(thumb_dest, "JPEG", quality=85)
            # Caso 4: Imagem solta no disco
            elif os.path.exists(img_path):
                with Image.open(img_path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                    im.save(thumb_dest, "JPEG", quality=85)
            else:
                return "", 404
        return send_file(thumb_dest, mimetype="image/jpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def pick_folder_native(title="Selecione a Pasta", init_dir=""):
    """Executa a seleção nativa de pastas via subprocesso com Tkinter isolado na thread principal do processo."""
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        f"d = filedialog.askdirectory(title={repr(title)}, initialdir={repr(init_dir)})\n"
        "print(d or '')\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        return proc.stdout.strip()
    except Exception as e:
        print(f"[!] Erro ao abrir seletor de pastas: {e}")
        return ""

UPLOAD_DIR = os.path.join(SYS_DIR, "uploads")
if os.path.exists("/content"):
    UPLOAD_DIR = "/content/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Recebe arquivos de mangá enviados diretamente pelo navegador (pasta de imagens ou ZIP/CBZ)."""
    try:
        # 1. Arquivo ZIP / CBZ / PDF
        if 'zip_file' in request.files:
            file = request.files['zip_file']
            filename = file.filename or "manga_upload.zip"
            ext = os.path.splitext(filename)[1].lower()
            base_name = os.path.splitext(filename)[0]
            base_name = re.sub(r'[\\/*?:"<>|]', "", base_name).strip() or "Manga_Upload"
            target_dir = os.path.join(UPLOAD_DIR, base_name)
            os.makedirs(target_dir, exist_ok=True)
            
            arc_tmp = os.path.join(UPLOAD_DIR, f"tmp_{base_name}{ext or '.zip'}")
            file.save(arc_tmp)
            try:
                res_dir = extract_manga_archive(arc_tmp, target_dir)
                if not res_dir:
                    return jsonify({"success": False, "error": "Nenhuma página válida encontrada no arquivo enviado."}), 400
            finally:
                try:
                    if os.path.exists(arc_tmp):
                        os.remove(arc_tmp)
                except Exception:
                    pass
                
            return jsonify({"success": True, "path": target_dir, "name": base_name})
            
        # 2. Upload de Pasta / Várias Imagens (com suporte a lotes/chunks para evitar limites de timeout e payload)
        files = request.files.getlist("files[]")
        folder_name = request.form.get("folder_name", "Manga_Upload").strip() or "Manga_Upload"
        folder_name = re.sub(r'[\\/*?:"<>|]', "", folder_name).strip() or "Manga_Upload"
        is_last = request.form.get("is_last", "true").lower() in ("true", "1")
        target_dir = os.path.join(UPLOAD_DIR, folder_name)
        os.makedirs(target_dir, exist_ok=True)
        
        saved_count = 0
        for f in files:
            fname = os.path.basename(f.filename)
            if fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
                f.save(os.path.join(target_dir, fname))
                saved_count += 1
                
        total_in_dir = len([x for x in os.listdir(target_dir) if x.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))])
        return jsonify({
            "success": True,
            "path": target_dir,
            "name": folder_name,
            "batch_saved": saved_count,
            "total_saved": total_in_dir,
            "done": is_last
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/drive_folders")
def api_drive_folders():
    """Lista pastas e arquivos zip/cbz de mangás disponíveis no Google Drive."""
    roots = find_drive_roots()
    if not roots:
        return jsonify({"available": False, "folders": []})
        
    folders = []
    seen = set()
    search_dirs = []
    for r in roots:
        manga_sub = os.path.join(r, "MANGAS")
        if os.path.exists(manga_sub):
            search_dirs.append(manga_sub)
        search_dirs.append(r)
        
    for base in search_dirs:
        try:
            for item in sorted(os.listdir(base)):
                p = os.path.abspath(os.path.join(base, item))
                if p in seen or item.startswith(".") or item == "_ocr" or item == "MANGAS [PT-BR]":
                    continue
                # Se for pasta
                if os.path.isdir(p):
                    imgs = [f for f in os.listdir(p) if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                    if imgs:
                        seen.add(p)
                        folders.append({
                            "name": item,
                            "path": p,
                            "pages": len(imgs),
                            "is_archive": False
                        })
                # Se for arquivo .pdf
                elif os.path.isfile(p) and item.lower().endswith('.pdf'):
                    fitz = _get_pymupdf()
                    if fitz is not None:
                        try:
                            doc = fitz.open(p)
                            try:
                                num_pages = len(doc)
                            finally:
                                doc.close()
                            if num_pages > 0:
                                seen.add(p)
                                folders.append({
                                    "name": f"📄 {item}",
                                    "path": p,
                                    "pages": num_pages,
                                    "is_archive": True
                                })
                        except Exception:
                            pass
                # Se for arquivo .zip ou .cbz
                elif os.path.isfile(p) and item.lower().endswith(('.zip', '.cbz')):
                    try:
                        with zipfile.ZipFile(p, 'r') as z:
                            zip_imgs = [info.filename for info in z.infolist() if not info.is_dir() and info.filename.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                            if zip_imgs:
                                seen.add(p)
                                folders.append({
                                    "name": f"📦 {item}",
                                    "path": p,
                                    "pages": len(zip_imgs),
                                    "is_archive": True
                                })
                    except Exception:
                        pass
        except Exception:
            pass
            
    return jsonify({"available": True, "folders": folders})

@app.route("/api/pick_folder", methods=["POST"])
def api_pick_folder():
    """Abre o diálogo nativo do Windows para selecionar a pasta do mangá (quando executado localmente)."""
    if os.name != 'nt':
        return jsonify({"success": False, "is_headless": True})
    cfg = auto_translate.load_config()
    raw_dir = cfg.get("raw_mangas_dir") or BASE_MANGAS_DIR
    init_dir = raw_dir if os.path.exists(raw_dir) else (BASE_MANGAS_DIR if os.path.exists(BASE_MANGAS_DIR) else "C:\\")
    selected_path = pick_folder_native(title="Selecione a Pasta do Mangá Original", init_dir=init_dir)
    
    if selected_path:
        return jsonify({"success": True, "path": selected_path})
    return jsonify({"success": False, "path": ""})

@app.route("/api/pick_path", methods=["POST"])
def api_pick_path():
    """Abre caixa de diálogo do Windows para escolher qualquer pasta de configuração."""
    if os.name != 'nt':
        return jsonify({"success": False, "is_headless": True, "error": "Seletor visual disponível apenas no Windows local. No Colab ou celular, digite o caminho da pasta manualmente."})
    data = request.json or {}
    title = data.get("title", "Selecione a Pasta")
    cfg = auto_translate.load_config()
    init_dir = cfg.get("raw_mangas_dir") or BASE_MANGAS_DIR
    if not os.path.exists(init_dir):
        init_dir = "C:\\"
    selected_path = pick_folder_native(title=title, init_dir=init_dir)
    if selected_path:
        return jsonify({"success": True, "path": selected_path})
    return jsonify({"success": False, "error": "Nenhuma pasta selecionada"})

@app.route("/api/inspect_folder", methods=["POST"])
def api_inspect_folder():
    """Inspeciona pasta informada para contar páginas e detectar idioma. Se for .zip/.cbz, descompacta antes."""
    data = request.json or {}
    p = data.get("path", "").strip('\"\'')
    if not p or not os.path.exists(p):
        return jsonify({"valid": False, "error": "Pasta ou arquivo não encontrado"})
        
    # Se for arquivo .zip, .cbz ou .pdf, descompacta/extrai para pasta correspondente
    if os.path.isfile(p) and p.lower().endswith(('.zip', '.cbz', '.pdf')):
        target_dir = os.path.splitext(p)[0]
        need_extract = True
        if os.path.exists(target_dir) and os.path.isdir(target_dir):
            existing_imgs = [f for f in os.listdir(target_dir) if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
            if existing_imgs:
                need_extract = False
                p = target_dir
        if need_extract:
            try:
                extracted_path = extract_manga_archive(p, target_dir)
                if not extracted_path:
                    return jsonify({"valid": False, "error": "Falha ao extrair páginas do arquivo (ZIP/CBZ/PDF)"})
                p = extracted_path
            except Exception as ex:
                return jsonify({"valid": False, "error": f"Erro ao processar arquivo: {ex}"})

    if not os.path.isdir(p):
        return jsonify({"valid": False, "error": "Caminho inválido"})
        
    imgs = [f for f in os.listdir(p) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not imgs:
        return jsonify({"valid": False, "error": "Nenhuma imagem encontrada na pasta"})
        
    first_img = os.path.join(p, sorted(imgs)[0])
    auto_lang = auto_translate.detect_manga_language_and_engine(p)
    lang_labels = {
        "korean": "Coreano (Manhwa / Webtoon)",
        "rapidocr": "Ocidental / Inglês / Chinês",
        "mokuro": "Japonês (Leitura Vertical)",
        "japanese": "Japonês (Leitura Vertical)",
    }
    
    return jsonify({
        "valid": True,
        "name": os.path.basename(p),
        "path": p,
        "pages": len(imgs),
        "first_img": first_img,
        "detected_engine": auto_lang,
        "detected_label": lang_labels.get(auto_lang, "Automático")
    })

@app.route("/api/drive/extract_all", methods=["POST"])
def api_drive_extract_all():
    """Varre a pasta de MANGAS e descompacta todos os arquivos .zip e .cbz encontrados em subpastas individuais."""
    data = request.json or {}
    folder_path = data.get("path")
    
    if not folder_path:
        for root in find_drive_roots():
            candidate = os.path.join(root, "MANGAS")
            if os.path.exists(candidate):
                folder_path = candidate
                break
                
    if not folder_path:
        cfg = auto_translate.load_config()
        folder_path = cfg.get("raw_mangas_dir") or BASE_MANGAS_DIR
        
    if not folder_path or not os.path.exists(folder_path):
        return jsonify({"success": False, "error": "Pasta de mangás não encontrada"}), 404
        
    archives = [f for f in sorted(os.listdir(folder_path)) if f.lower().endswith(('.zip', '.cbz', '.pdf'))]
    if not archives:
        return jsonify({"success": True, "count": 0, "message": "Nenhum arquivo .zip, .cbz ou .pdf pendente encontrado na pasta."})
        
    extracted_count = 0
    errors = []
    
    for arc in archives:
        arc_path = os.path.join(folder_path, arc)
        target_dir = os.path.splitext(arc_path)[0]
        # Se já existe e tem imagens, não re-extrai para economizar tempo
        if os.path.exists(target_dir) and os.path.isdir(target_dir):
            imgs = [f for f in os.listdir(target_dir) if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
            if imgs:
                continue
        try:
            res = extract_manga_archive(arc_path, target_dir)
            if res:
                extracted_count += 1
        except Exception as e:
            errors.append(f"{arc}: {str(e)}")
            
    return jsonify({
        "success": True,
        "count": extracted_count,
        "total_archives": len(archives),
        "errors": errors,
        "message": f"{extracted_count} obra(s) descompactada(s) com sucesso na pasta MANGAS!" if extracted_count > 0 else "Todas as obras já haviam sido descompactadas!"
    })

@app.route("/api/start", methods=["POST"])
def api_start_translation():
    """Inicia a tradução em background thread com streaming de progresso."""
    global job_state
    data = request.json or {}
    manga_path = data.get("path", "").strip('\"\'')
    if not manga_path or not os.path.exists(manga_path):
        return jsonify({"error": "Caminho do mangá inválido"}), 400
    if os.path.isfile(manga_path) and manga_path.lower().endswith(('.zip', '.cbz', '.pdf')):
        try:
            manga_path = extract_manga_archive(manga_path)
            if not manga_path or not os.path.isdir(manga_path):
                return jsonify({"error": "Falha ao extrair páginas do arquivo"}), 400
        except Exception as ex:
            return jsonify({"error": f"Erro ao processar arquivo: {ex}"}), 400

    first_img = data.get("first_img", "")
    if not first_img and os.path.exists(manga_path):
        imgs = [os.path.join(manga_path, f) for f in os.listdir(manga_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))]
        if imgs:
            import re
            def _nat_key(s):
                return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]
            imgs.sort(key=lambda x: _nat_key(os.path.basename(x)))
            first_img = imgs[0]
        
    with job_lock:
        if job_state["status"] == "running":
            return jsonify({"error": "Já existe uma tradução em andamento!"}), 409
            
        job_state["status"] = "running"
        job_state["manga_name"] = os.path.basename(manga_path)
        job_state["manga_path"] = manga_path
        job_state["first_img"] = first_img
        job_state["stage"] = "ocr"
        job_state["current_page"] = 0
        job_state["total_pages"] = 0
        job_state["percentage"] = 0
        job_state["message"] = "Iniciando motor de OCR e análise..."
        job_state["logs"] = []
        job_state["result"] = None
        job_state["error"] = None
        job_state["start_time"] = time.time()

    ocr_mode = data.get("ocr_mode", "auto")
    is_adult = bool(data.get("is_adult", True))
    force_ocr = bool(data.get("force_ocr", False))
    retranslate = bool(data.get("retranslate", False))
    provider = data.get("provider", "groq")

    def _worker():
        global job_state
        old_stdout = sys.stdout if sys.stdout is not None else SafeDummyStream()
        old_stderr = sys.stderr if sys.stderr is not None else SafeDummyStream()
        capture = StreamCapture(original_stream=old_stdout)
        sys.stdout = capture
        sys.stderr = capture

        def progress_callback(stage, current, total, text, result=None):
            with job_lock:
                job_state["stage"] = stage
                job_state["current_page"] = current
                job_state["total_pages"] = total
                job_state["message"] = text
                if total > 0:
                    pct = int((current / total) * 100)
                    if stage == "ocr":
                        job_state["percentage"] = int(pct * 0.3)
                    elif stage == "translation":
                        job_state["percentage"] = 30 + int(pct * 0.4)
                    elif stage == "diagram":
                        job_state["percentage"] = 70 + int(pct * 0.3)
                    elif stage == "done":
                        job_state["percentage"] = 100
                if result:
                    job_state["result"] = result

        try:
            cfg = auto_translate.load_config({"provider": provider})
            res = auto_translate.process_manga(
                manga_path,
                ocr_mode=ocr_mode,
                force_ocr=force_ocr,
                retranslate=retranslate,
                is_adult=is_adult,
                config=cfg,
                progress_cb=progress_callback
            )
            with job_lock:
                if not res or res is False:
                    job_state["status"] = "error"
                    job_state["error"] = "Falha no processamento do mangá."
                    job_state["message"] = "Erro: O processamento falhou ou nenhuma imagem traduzida foi gerada."
                    job_state["logs"].append("[!] Erro: Nenhuma página traduzida foi salva.")
                else:
                    job_state["status"] = "done"
                    job_state["percentage"] = 100
                    job_state["message"] = "Mangá traduzido e salvo com sucesso!"
                    if isinstance(res, dict):
                        out_p = res.get("output_dir", "")
                        if out_p:
                            m_id = get_manga_hash(out_p)
                            res["id"] = m_id
                            res["reader_url"] = f"/read/{m_id}/"
                        job_state["result"] = res
        except Exception as e:
            err_msg = str(e) or e.__class__.__name__
            tb_msg = traceback.format_exc()
            with job_lock:
                job_state["status"] = "error"
                job_state["error"] = err_msg
                job_state["message"] = f"Erro no processamento: {err_msg}"
                job_state["logs"].append(f"[!] Erro fatal: {err_msg}")
                for tb_line in tb_msg.strip().split("\n"):
                    job_state["logs"].append(tb_line)
        finally:
            sys.stdout = old_stdout if old_stdout is not None else SafeDummyStream()
            sys.stderr = old_stderr if old_stderr is not None else SafeDummyStream()

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"success": True})

@app.route("/api/progress")
def api_progress():
    with job_lock:
        return jsonify(job_state)

@app.route("/api/open_reader", methods=["POST"])
def api_open_reader():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        folder = os.path.dirname(os.path.abspath(path)) if (os.path.isfile(path) and path.endswith(".html")) else os.path.abspath(path)
        m_id = get_manga_hash(folder)
        reader_url = f"/read/{m_id}/"
        if os.name == 'nt' and (request.host.startswith("127.0.0.1") or request.host.startswith("localhost")):
            try:
                webbrowser.open("file://" + os.path.abspath(path))
            except Exception:
                pass
        return jsonify({"success": True, "reader_url": reader_url, "id": m_id})
    return jsonify({"success": False, "error": "Arquivo não encontrado"}), 404

@app.route("/api/launch_app_window", methods=["POST"])
def api_launch_app_window():
    """Abre uma janela de aplicativo dedicada (chromeless app window) usando Chrome ou Edge."""
    try:
        from studio import app_launcher
        app_launcher.launch()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        if hasattr(os, 'startfile'):
            try:
                os.startfile(path)
            except Exception:
                pass
        return jsonify({"success": True, "path": path})
    return jsonify({"success": False, "error": "Pasta não encontrada"}), 404

@app.route("/api/open_cbz", methods=["POST"])
def api_open_cbz():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        if hasattr(os, 'startfile'):
            try:
                os.startfile(path)
            except Exception:
                pass
        return jsonify({"success": True, "path": path})
    return jsonify({"success": False, "error": "Arquivo CBZ não encontrado"}), 404

@app.route("/api/test_key", methods=["POST"])
def api_test_key():
    """Valida chave de API ao vivo consultando a rota oficial da Groq ou OpenRouter."""
    data = request.json or {}
    provider = data.get("provider", "groq").lower()
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"valid": False, "msg": "Chave não informada."})

    if provider == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        test_payload = json.dumps({"model": "qwen/qwen3.8-27b", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode("utf-8")
        req = urllib.request.Request(url, data=test_payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                rem_req = resp.headers.get("x-ratelimit-remaining-requests", "1000")
                rem_tok = resp.headers.get("x-ratelimit-remaining-tokens", "8000")
                return jsonify({"valid": True, "msg": f"Chave Groq 100% Válida! {rem_req}/1000 reqs e {rem_tok} tokens disponíveis."})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return jsonify({"valid": True, "msg": "Chave Groq Válida! (Porém em limite temporário de tokens no momento)."})
            return jsonify({"valid": False, "msg": f"Erro de autenticação Groq (HTTP {e.code}). Verifique a chave."})
        except Exception as e:
            return jsonify({"valid": False, "msg": f"Erro de conexão: {e}"})

    elif provider == "openrouter":
        url = "https://openrouter.ai/api/v1/auth/key"
        headers = {"Authorization": f"Bearer {key}"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                kdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                free_info = kdata.get("free_model_daily_requests", {})
                f_used = free_info.get("used", 0)
                f_limit = free_info.get("limit", 50)
                f_rem = free_info.get("remaining", 0)
                return jsonify({"valid": True, "msg": f"Chave OpenRouter Válida! {f_rem} reqs gratuitas restantes ({f_used}/{f_limit} usadas hoje)."})
        except urllib.error.HTTPError as e:
            return jsonify({"valid": False, "msg": f"Erro HTTP {e.code} no OpenRouter. Chave inválida ou recusada."})
        except Exception as e:
            return jsonify({"valid": False, "msg": f"Erro de conexão: {e}"})

    elif provider == "gemini":
        qs = urllib.parse.urlencode({"key": key})
        url = f"https://generativelanguage.googleapis.com/v1beta/models?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                gm_data = json.loads(resp.read().decode("utf-8"))
                gm_count = len(gm_data.get("models", []))
                return jsonify({"valid": True, "msg": f"Chave Google Gemini Válida! ({gm_count} modelos Vision liberados)."})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return jsonify({"valid": True, "msg": "Chave Gemini Válida! (Porém em limite temporário no momento)."})
            return jsonify({"valid": False, "msg": f"Erro HTTP {e.code} no Google Gemini. Verifique a chave (AIza...)."})
        except Exception as e:
            return jsonify({"valid": False, "msg": f"Erro de conexão Gemini: {e}"})

    return jsonify({"valid": False, "msg": "Provedor desconhecido."})

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    cfg_path = os.path.join(SYS_DIR, "config.json")
    if request.method == "POST":
        new_cfg = request.json or {}
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            extra_paths = [
                r"C:\Users\ja329\tools\manga-translator\config.json",
                os.path.join(r"C:\Users\ja329\.gemini\antigravity\scratch\SKILL-TRADUCAO-MANGA", "config.json")
            ]
            for root in find_drive_roots():
                extra_paths.append(os.path.join(root, ".manga_studio", "config.json"))
                extra_paths.append(os.path.join(root, "MANGAS [PT-BR]", ".config.json"))

            for extra_p in extra_paths:
                try:
                    p_dir = os.path.dirname(extra_p)
                    if os.path.exists(p_dir):
                        with open(extra_p, "w", encoding="utf-8") as ef:
                            json.dump(new_cfg, ef, indent=2, ensure_ascii=False)
                except Exception: pass
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        cfg = auto_translate.load_config()
        # Se as chaves locais estiverem vazias, mas houver perfil salvo no Google Drive:
        if not cfg.get("groq_api_keys") and not cfg.get("groq_api_key"):
            for root in find_drive_roots():
                drive_cfg = os.path.join(root, ".manga_studio", "config.json")
                if os.path.exists(drive_cfg):
                    try:
                        with open(drive_cfg, "r", encoding="utf-8") as df:
                            d_data = json.load(df)
                            cfg.update(d_data)
                            break
                    except Exception: pass
        cfg["app_version"] = APP_VERSION
        cfg["app_version_name"] = APP_VERSION_NAME
        cfg["drive_connected"] = bool(find_drive_roots())
        return jsonify(cfg)

@app.route("/api/delete_manga", methods=["POST"])
def api_delete_manga():
    """Exclui com segurança uma pasta de mangá (enviada ou traduzida) da biblioteca."""
    data = request.json or {}
    raw_path = data.get("path", "").strip('\"\'')
    if not raw_path:
        return jsonify({"success": False, "error": "Caminho não fornecido."}), 400

    abs_p = os.path.abspath(raw_path)
    if not os.path.exists(abs_p):
        return jsonify({"success": False, "error": "Pasta ou arquivo não encontrado."}), 404

    # Proteção de segurança: impede que caminhos críticos do sistema ou raízes sejam apagados
    forbidden_roots = [
        os.path.abspath("/"),
        os.path.abspath("C:\\"),
        os.path.abspath("C:\\Windows"),
        os.path.abspath("C:\\Users"),
        os.path.abspath(SYS_DIR),
        os.path.abspath("/content"),
        os.path.abspath("/content/drive"),
        os.path.abspath("/content/drive/MyDrive"),
        os.path.abspath("/content/manga-translator")
    ]
    for r in find_drive_roots():
        forbidden_roots.append(os.path.abspath(r))
        forbidden_roots.append(os.path.abspath(os.path.join(r, "MANGAS")))
        forbidden_roots.append(os.path.abspath(os.path.join(r, "MANGAS [PT-BR]")))
    for fb in forbidden_roots:
        if abs_p == fb:
            return jsonify({"success": False, "error": "Operação não permitida neste diretório de sistema."}), 403

    try:
        if os.path.isdir(abs_p):
            shutil.rmtree(abs_p)
        elif os.path.isfile(abs_p):
            os.remove(abs_p)

        # Se houver arquivo CBZ associado com o mesmo nome base, remove também
        cbz_cand = abs_p.rstrip("/\\") + ".cbz"
        if os.path.exists(cbz_cand):
            try: os.remove(cbz_cand)
            except Exception: pass

        return jsonify({"success": True, "message": "Obra excluída com sucesso."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/aprendizado", methods=["GET", "POST"])
def api_aprendizado():
    fpath = os.path.join(SYS_DIR, "aprendizado.txt")
    if request.method == "POST":
        content = request.json.get("content", "")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True})
    else:
        content = ""
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        return jsonify({"content": content})

@app.route("/api/glossary", methods=["GET", "POST"])
def api_glossary():
    fpath = os.path.join(SYS_DIR, "glossary.json")
    if request.method == "POST":
        data = request.json.get("data", {})
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True})
    else:
        data = {}
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        return jsonify({"data": data})

@app.route("/api/rate_manga", methods=["POST"])
def api_rate_manga():
    """Recebe a nota do leitor (1 a 5 estrelas) e dispara a auto-auditoria inteligente da IA."""
    data = request.json or {}
    path = data.get("path", "").strip('\"\'')
    rating = int(data.get("rating", 3))
    comment = data.get("comment", "").strip()
    
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": "Caminho do mangá não encontrado."}), 400

    reviews_file = os.path.join(SYS_DIR, "manga_reviews.json")
    reviews = []
    if os.path.exists(reviews_file):
        try:
            with open(reviews_file, "r", encoding="utf-8") as rf:
                reviews = json.load(rf)
        except Exception:
            reviews = []
            
    import datetime
    review_entry = {
        "manga_path": path,
        "manga_name": os.path.basename(path),
        "rating": rating,
        "comment": comment,
        "timestamp": datetime.datetime.now().isoformat()
    }
    reviews.append(review_entry)
    try:
        with open(reviews_file, "w", encoding="utf-8") as rf:
            json.dump(reviews, rf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    audit_report = None
    if rating <= 3 or data.get("force_audit", True):
        try:
            audit_report = auto_translate.audit_manga_translation(path, rating=rating, user_comment=comment)
        except Exception as e:
            audit_report = {"success": False, "error": str(e)}

    return jsonify({
        "success": True,
        "rating": rating,
        "review": review_entry,
        "audit_report": audit_report
    })

@app.route("/api/audit_manga", methods=["POST"])
def api_audit_manga():
    """Audita a integridade de uma obra traduzida e exibe diagnóstico detalhado."""
    data = request.json or {}
    path = data.get("path", "").strip('\"\'')
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": "Caminho do mangá inválido."}), 400
        
    try:
        report = auto_translate.audit_manga_translation(path, rating=data.get("rating"), user_comment=data.get("comment", ""))
        return jsonify({"success": True, "audit_report": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def open_chrome_app(url, port=5050):
    """Abre a janela nativa do Chrome em modo Desktop App (sem barra de URL)."""
    profile_dir = os.path.join(os.environ.get("TEMP", r"C:\Windows\Temp"), "MangaStudioAppProfile")
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    ]
    for cp in chrome_paths:
        if os.path.exists(cp):
            cmd = [
                cp,
                f"--app={url}",
                f"--user-data-dir={profile_dir}",
                "--window-size=1280,820",
                "--window-position=100,60"
            ]
            try:
                subprocess.Popen(cmd)
                return True
            except Exception:
                pass
    webbrowser.open(url)
    return False

def is_server_running(port=5050):
    """Verifica se o backend já está ativo e respondendo na porta."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/config")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False

def kill_existing_on_port(port=5050):
    """Encerra processos anteriores que estejam travando a porta 5050."""
    try:
        import psutil
        curr_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'name']):
            if p.info['pid'] != curr_pid and 'python' in (p.info['name'] or '').lower():
                try:
                    for c in p.net_connections():
                        if c.laddr.port == port:
                            p.kill()
                except Exception:
                    pass
    except Exception:
        pass

if __name__ == "__main__":
    try:
        port = 5050
        url = f"http://127.0.0.1:{port}"

        # Se o servidor já estiver rodando, apenas abre a janela do app sem recriar sockets
        if is_server_running(port):
            open_chrome_app(url, port)
            sys.exit(0)

        # Se a porta estiver presa por processo zumbi, limpa
        kill_existing_on_port(port)
        time.sleep(0.5)

        threading.Timer(1.2, lambda: open_chrome_app(url, port)).start()
        app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    except Exception as e:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
