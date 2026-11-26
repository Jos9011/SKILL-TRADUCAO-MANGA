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
import uuid
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
if SYS_DIR not in sys.path:
    sys.path.insert(0, SYS_DIR)
import app_paths  # código x dados: no .exe os dados ficam em %APPDATA%\MangaStudio
if app_paths.FROZEN:  # no .exe, __file__ deste módulo não fica dentro de "studio/"
    SYS_DIR = app_paths.CODE_DIR
DATA_DIR = app_paths.DATA_DIR
os.makedirs(DATA_DIR, exist_ok=True)
os.chdir(DATA_DIR)
STUDIO_DIR = os.path.join(SYS_DIR, "studio") if app_paths.FROZEN else os.path.dirname(os.path.abspath(__file__))
if STUDIO_DIR not in sys.path:
    sys.path.insert(0, STUDIO_DIR)

import auto_translate
import drive_helper
import job_control

job_ctrl = job_control.JobController()

TEMPLATE_DIR = os.path.join(STUDIO_DIR, "templates")
STATIC_DIR = os.path.join(STUDIO_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Configurações globais e Versão Oficial
try:
    from version import __version__, __version_name__, get_version_info
except Exception:
    __version__ = "0.8.2-beta"
    __version_name__ = "v0.8.2 Beta"

APP_VERSION = __version__
APP_VERSION_NAME = __version_name__

# =====================================================================
# 🔐 CONTROLE DE ACESSO
# Quando MANGA_STUDIO_TOKEN está definido (ex: Colab + túnel Cloudflare),
# toda requisição precisa do token (via ?token=, header X-Studio-Token ou cookie).
# Sem token definido, o servidor só aceita acesso local direto (127.0.0.1)
# e recusa requisições que chegam por túneis públicos.
# =====================================================================
import hmac
ACCESS_TOKEN = os.environ.get("MANGA_STUDIO_TOKEN", "").strip()
TOKEN_COOKIE = "ms_token"
_PUBLIC_PATHS = ("/manifest.json", "/sw.js", "/static/", "/favicon")
_TUNNEL_HEADERS = ("Cf-Ray", "Cf-Connecting-Ip", "X-Forwarded-For", "Ngrok-Trace-Id")

def _token_ok(candidate):
    return bool(candidate) and bool(ACCESS_TOKEN) and hmac.compare_digest(str(candidate), ACCESS_TOKEN)

@app.before_request
def _require_access_token():
    if request.path.startswith(_PUBLIC_PATHS):
        return None
    if not ACCESS_TOKEN:
        # Sem token: bloqueia qualquer acesso vindo de proxy/túnel público
        if any(h in request.headers for h in _TUNNEL_HEADERS) or request.remote_addr not in ("127.0.0.1", "::1"):
            return Response("Acesso remoto bloqueado: defina MANGA_STUDIO_TOKEN para usar o Studio fora deste computador.", status=403)
        return None
    cand = request.args.get("token") or request.headers.get("X-Studio-Token") or request.cookies.get(TOKEN_COOKIE)
    if not _token_ok(cand):
        return Response("Acesso negado: abra o link completo com ?token=... exibido no Colab.", status=401)
    return None

@app.after_request
def _persist_access_token(resp):
    if _token_ok(request.args.get("token")):
        resp.set_cookie(TOKEN_COOKIE, ACCESS_TOKEN, httponly=True, samesite="Strict", secure=request.is_secure, max_age=60 * 60 * 24 * 7)
    return resp

def _allowed_roots():
    """Pastas onde o Studio pode ler, baixar ou apagar obras."""
    roots = [BASE_MANGAS_DIR, globals().get("UPLOAD_DIR")]
    try:
        cfg = auto_translate.load_config()
        roots += [cfg.get("raw_mangas_dir"), cfg.get("translated_mangas_dir")]
    except Exception:
        pass
    try:
        for r in drive_helper.find_drive_roots():
            raw_dirs, trans_dirs = drive_helper.find_manga_directories(r)
            roots += list(raw_dirs or []) + list(trans_dirs or [])
            roots += [os.path.join(r, "MANGAS"), os.path.join(r, "MANGAS [PT-BR]")]
    except Exception:
        pass
    # Pastas do trabalho atual (entrada escolhida pelo usuário e saída gerada)
    try:
        with job_lock:
            if job_state.get("manga_path"):
                roots.append(os.path.dirname(os.path.abspath(job_state["manga_path"])))
            res = job_state.get("result") or {}
            if isinstance(res, dict) and res.get("output_dir"):
                roots.append(os.path.dirname(os.path.abspath(res["output_dir"])))
    except Exception:
        pass
    out = []
    for r in roots:
        if r and os.path.isdir(r):
            rp = os.path.realpath(r)
            if rp not in out:
                out.append(rp)
    return out

def is_path_allowed(path, allow_root_itself=False):
    """True se `path` estiver DENTRO de uma das pastas de mangás permitidas."""
    if not path:
        return False
    try:
        rp = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    for root in _allowed_roots():
        try:
            if os.path.commonpath([rp, root]) == root and (allow_root_itself or rp != root):
                return True
        except ValueError:
            continue  # drives diferentes no Windows
    return False

def _forbidden():
    return jsonify({"success": False, "error": "Caminho fora das pastas de mangás permitidas."}), 403

@app.context_processor
def inject_version():
    return {
        "app_version": APP_VERSION_NAME,
        "app_version_code": APP_VERSION
    }

BASE_MANGAS_DIR = r"C:\Users\ja329\OneDrive\Documentos\MANGAS"
THUMB_CACHE_DIR = os.path.join(DATA_DIR, ".thumb_cache")
os.makedirs(THUMB_CACHE_DIR, exist_ok=True)

# Mapeamento para leitura e download web seguro
MANGA_PATH_CACHE = {}

def find_drive_roots():
    """Retorna lista de caminhos raiz do Google Drive encontrados (Linux/Colab e Windows)."""
    return drive_helper.find_drive_roots()

def is_drive_path(p):
    """Verifica se o caminho informado está dentro de um Google Drive montado."""
    return drive_helper.is_drive_path(p)

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
    return send_from_directory(STATIC_DIR, "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def service_worker():
    return send_from_directory(STATIC_DIR, "sw.js", mimetype="application/javascript")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(STATIC_DIR, "favicon.ico", mimetype="image/x-icon")

def check_single_groq_key(idx, key, models_to_check=None, deep=False):
    key = str(key).strip()
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    models = []
    for m in (models_to_check or ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]):
        m_s = str(m or "").strip()
        if m_s and m_s not in models:
            models.append(m_s)

    k_data = {
        "index": idx + 1,
        "masked_key": masked,
        "key": key,
        "ok": False,
        "models": {}
    }

    for m in models:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        payload = {"model": m, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        m_low = m.lower()
        if "qwen3" in m_low:
            payload["reasoning_effort"] = "none"
        elif "gpt-oss" in m_low:
            payload["reasoning_effort"] = "low"

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                try:
                    raw_res = json.loads(resp.read().decode("utf-8"))
                    used_tok = int((raw_res.get("usage") or {}).get("total_tokens", 12) or 12)
                except Exception:
                    used_tok = 12
                auto_translate.record_groq_response_headers(key, m, resp.headers, used_tokens=used_tok, source="ping")

            probe_ok = True
            probe_msg = None
            if deep:
                probe_ok, probe_msg, snap = auto_translate.probe_groq_page_capacity(
                    key, m, target_tokens=1950, force=False, cache_ttl=180
                )
            else:
                snap = auto_translate.get_groq_quota_snapshot(key, m)

            is_daily = bool(snap.get("tpd_exhausted") or snap.get("rpd_exhausted"))
            page_ready = bool(snap.get("page_ready", True)) and probe_ok and not is_daily
            k_data["models"][m] = {
                "ok": page_ready and not snap.get("auth_error"),
                "ping_ok": True,
                "page_ready": page_ready,
                "rem_req": snap.get("rem_req"),
                "lim_req": snap.get("lim_req"),
                "rem_tok": snap.get("rem_tok"),
                "lim_tok": snap.get("lim_tok"),
                "rst_req": snap.get("rst_req"),
                "rst_tok": snap.get("rst_tok"),
                "tpd_limit": snap.get("tpd_limit"),
                "tpd_used": snap.get("tpd_used"),
                "tpd_remaining": snap.get("tpd_remaining"),
                "tpd_reset_sec": snap.get("tpd_reset_sec", 0.0),
                "tpd_exhausted": bool(snap.get("tpd_exhausted")),
                "rpd_exhausted": bool(snap.get("rpd_exhausted")),
                "tpm_limited": bool(snap.get("tpm_limited")),
                "is_daily_limit": is_daily,
                "limit_type": "TPD" if snap.get("tpd_exhausted") else ("RPD" if snap.get("rpd_exhausted") else None),
                "msg": probe_msg if (deep and not probe_ok and probe_msg) else snap.get("status_reason", "Pronta")
            }
        except urllib.error.HTTPError as e:
            err_text = ""
            try:
                err_text = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            details = auto_translate.record_groq_error(key, m, e.code, err_text, e.headers) or auto_translate.parse_groq_rate_limit_details(err_text, e.headers, e.code)
            snap = auto_translate.get_groq_quota_snapshot(key, m)
            is_daily = bool(details.get("is_daily") or snap.get("tpd_exhausted") or snap.get("rpd_exhausted"))
            wait_str = auto_translate._format_duration_pt(details.get("retry_after") or 0)
            err_msg = snap.get("status_reason")
            if not err_msg or err_msg == "Pronta para páginas reais":
                err_msg = f"Cota diária {details.get('limit_type', 'TPD')} atingida (~{wait_str})" if is_daily else f"HTTP {e.code}"
            k_data["models"][m] = {
                "ok": False,
                "ping_ok": False,
                "page_ready": False,
                "code": e.code,
                "auth_error": e.code in (401, 403),
                "is_daily_limit": is_daily,
                "limit_type": details.get("limit_type"),
                "retry_after": details.get("retry_after", 0.0),
                "rem_req": snap.get("rem_req"),
                "lim_req": snap.get("lim_req"),
                "rem_tok": snap.get("rem_tok"),
                "lim_tok": snap.get("lim_tok"),
                "tpd_limit": snap.get("tpd_limit") or details.get("limit"),
                "tpd_used": snap.get("tpd_used") or details.get("used"),
                "tpd_remaining": snap.get("tpd_remaining") if snap.get("tpd_remaining") is not None else details.get("remaining"),
                "tpd_reset_sec": snap.get("tpd_reset_sec", 0.0),
                "tpd_exhausted": bool(snap.get("tpd_exhausted") or details.get("limit_type") == "TPD"),
                "rpd_exhausted": bool(snap.get("rpd_exhausted") or details.get("limit_type") == "RPD"),
                "msg": err_msg
            }
        except Exception as e:
            k_data["models"][m] = {
                "ok": False,
                "ping_ok": False,
                "page_ready": False,
                "rem_req": None,
                "lim_req": None,
                "rem_tok": None,
                "lim_tok": None,
                "msg": f"Erro de conexão: {e}"
            }

    k_data["ok"] = any(md.get("ok") and md.get("page_ready", True) for md in k_data["models"].values())
    if models:
        k_data["active_model_ok"] = bool(k_data["models"].get(models[0], {}).get("ok"))
    k_data["any_daily_limit"] = bool(k_data["models"]) and all(
        md.get("is_daily_limit") for md in k_data["models"].values()
    )
    return k_data

@app.route("/api/status")
def api_status():
    """Consulta cotas reais (RPD, TPM, TPD estimado/verificado, créditos líquidos e erros 429 em runtime)."""
    cfg = auto_translate.load_config()
    deep = str(request.args.get("deep", "")).strip().lower() in ("1", "true", "yes")
    active_groq_model = cfg.get("groq_model", "qwen/qwen3.8-27b")
    fb_groq_model = cfg.get("groq_fallback_model", "openai/gpt-oss-120b")
    active_gem_model = cfg.get("gemini_model", "gemini-2.5-flash")

    res = {
        "groq": {
            "configured": False,
            "keys": [],
            "models": {},
            "total_qwen_remaining": 0,
            "total_qwen_limit": 0,
            "total_active_remaining": 0,
            "total_active_limit": 0,
            "ready_keys_count": 0,
            "any_model_ready_keys": 0,
            "deep_checked": deep,
            "active_model": active_groq_model,
            "fallback_model": fb_groq_model
        },
        "openrouter": {"configured": False, "keys": []},
        "gemini": {
            "configured": False,
            "keys": [],
            "active_model": active_gem_model,
            "deep_checked": deep
        },
        "ollama": {"status": "offline", "models": [], "vision_models": []},
        "vision": {
            "provider": cfg.get("vision_provider", "auto"),
            "gemini_model": active_gem_model,
            "groq_vision_model": cfg.get("groq_vision_model", "qwen/qwen3.8-27b"),
            "openrouter_vision_model": cfg.get("openrouter_vision_model", auto_translate.OPENROUTER_DEFAULT_VISION_MODELS[0]),
            "ollama_vision_model": cfg.get("ollama_vision_model", "")
        },
        "runtime_warnings": []
    }

    # 1. GROQ POOL (MULTI-CHAVES CONCORRENTES)
    groq_keys = list(cfg.get("groq_api_keys", []) or [])
    if not groq_keys and cfg.get("groq_api_key"):
        groq_keys = [cfg.get("groq_api_key")]

    if groq_keys:
        res["groq"]["configured"] = True
        models_to_check = []
        for cm in (active_groq_model, fb_groq_model, "qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            if cm and cm not in models_to_check:
                models_to_check.append(cm)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(groq_keys), 6)) as executor:
            groq_results = list(executor.map(
                lambda ik: check_single_groq_key(ik[0], ik[1], models_to_check=models_to_check, deep=deep),
                enumerate(groq_keys)
            ))

        res["groq"]["keys"] = groq_results
        if groq_results:
            res["groq"]["models"] = groq_results[0].get("models", {})
            res["groq"]["masked_key"] = groq_results[0].get("masked_key", "***")

        total_act_rem = 0
        total_act_lim = 0
        ready_act_keys = 0
        any_ready_keys = 0
        total_qwen_rem = 0
        total_qwen_lim = 0

        for k_item in groq_results:
            if k_item.get("ok"):
                any_ready_keys += 1
            m_act = k_item.get("models", {}).get(active_groq_model, {})
            if not m_act.get("auth_error"):
                if m_act.get("lim_req") is not None:
                    total_act_lim += int(m_act.get("lim_req") or 0)
                elif m_act.get("ok") or m_act.get("is_daily_limit"):
                    total_act_lim += 1000
            if m_act.get("ok") and m_act.get("page_ready", True):
                ready_act_keys += 1
                if m_act.get("rem_req") is not None:
                    total_act_rem += int(m_act.get("rem_req") or 0)

            m_qw = k_item.get("models", {}).get("qwen/qwen3.8-27b") or m_act
            if not m_qw.get("auth_error"):
                if m_qw.get("lim_req") is not None:
                    total_qwen_lim += int(m_qw.get("lim_req") or 0)
                elif m_qw.get("ok") or m_qw.get("is_daily_limit"):
                    total_qwen_lim += 1000
            if m_qw.get("ok") and m_qw.get("page_ready", True) and m_qw.get("rem_req") is not None:
                total_qwen_rem += int(m_qw.get("rem_req") or 0)

        res["groq"]["total_active_remaining"] = total_act_rem
        res["groq"]["total_active_limit"] = total_act_lim
        res["groq"]["ready_keys_count"] = ready_act_keys
        res["groq"]["any_model_ready_keys"] = any_ready_keys
        res["groq"]["total_qwen_remaining"] = total_qwen_rem
        res["groq"]["total_qwen_limit"] = total_qwen_lim

    # 2. OPENROUTER
    or_keys = list(cfg.get("openrouter_api_keys", []) or [])
    if not or_keys and cfg.get("openrouter_api_key"):
        or_keys = [cfg.get("openrouter_api_key")]
    if or_keys:
        res["openrouter"]["configured"] = True
        for idx, k in enumerate(or_keys):
            k_s = str(k or "").strip()
            k_info = {
                "index": idx + 1,
                "key": k_s[:8] + "..." + k_s[-4:] if len(k_s) > 12 else "***",
                "ok": False,
                "credits": 0.0,
                "total_credits": 0.0,
                "total_usage": 0.0,
                "is_free_tier": True,
                "has_free_quota_details": False,
                "daily_exhausted": False,
                "upstream_limited_model": None,
                "runtime_warning": None
            }
            try:
                req_or = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {k_s}"})
                with urllib.request.urlopen(req_or, timeout=5) as resp:
                    kdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    k_info["ok"] = True
                    k_info["is_free_tier"] = bool(kdata.get("is_free_tier", True))
                    free_info = kdata.get("free_model_daily_requests")
                    if isinstance(free_info, dict) and ("limit" in free_info or "remaining" in free_info):
                        k_info["has_free_quota_details"] = True
                        f_lim = int(free_info.get("limit", 50) or 50)
                        f_used = int(free_info.get("used", 0) or 0)
                        f_rem = int(free_info.get("remaining", max(0, f_lim - f_used)) or 0)
                        k_info["free_used"] = f_used
                        k_info["free_limit"] = f_lim
                        k_info["free_rem"] = f_rem
            except urllib.error.HTTPError as e:
                k_info["err"] = f"HTTP {e.code}"
                if e.code in (401, 403):
                    auto_translate.record_openrouter_error(k_s, "", e.code, k_info["err"])
            except Exception as e:
                k_info["err"] = str(e)

            try:
                req_c = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {k_s}"})
                with urllib.request.urlopen(req_c, timeout=5) as resp:
                    cdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    t_cred = float(cdata.get("total_credits", 0) or 0)
                    t_use = float(cdata.get("total_usage", 0) or 0)
                    k_info["total_credits"] = t_cred
                    k_info["total_usage"] = t_use
                    k_info["credits"] = max(0.0, t_cred - t_use)
            except Exception:
                pass

            snap_or = auto_translate.get_openrouter_quota_snapshot(k_s)
            if snap_or.get("daily_exhausted") or (
                k_info["has_free_quota_details"] and k_info.get("free_rem", 1) <= 0 and k_info["credits"] <= 0.01
            ):
                k_info["daily_exhausted"] = True
                k_info["ok"] = False
                k_info["runtime_warning"] = snap_or.get("last_error") or "Cota diária :free esgotada hoje (sem saldo pago)"
            elif snap_or.get("upstream_429_model"):
                k_info["upstream_limited_model"] = snap_or.get("upstream_429_model")
                k_info["runtime_warning"] = snap_or.get("last_error")
            elif snap_or.get("auth_error"):
                k_info["ok"] = False
                k_info["runtime_warning"] = snap_or.get("last_error")

            if k_info["ok"]:
                auto_translate.record_openrouter_status(k_s, {
                    "credits": k_info["credits"],
                    "is_free_tier": k_info["is_free_tier"],
                    "free_rem": k_info.get("free_rem"),
                    "free_limit": k_info.get("free_limit"),
                    "free_used": k_info.get("free_used")
                })
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
            k_info = {
                "index": idx + 1,
                "key": k[:8] + "..." + k[-4:] if len(k) > 12 else "***",
                "ok": False,
                "quota_exhausted": False,
                "rate_limited": False,
                "quota_reset_sec": 0.0
            }
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
                err_b = ""
                try:
                    err_b = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                if e.code == 429:
                    auto_translate.record_gemini_error(k, active_gem_model, 429, err_b)
                    k_info["ok"] = False
                    k_info["rate_limited"] = True
                    k_info["quota_exhausted"] = True
                    k_info["msg"] = "Cota Gemini atingida (HTTP 429)"
                else:
                    if e.code in (401, 403):
                        auto_translate.record_gemini_error(k, active_gem_model, e.code, err_b)
                    k_info["msg"] = f"Erro HTTP {e.code}"
            except Exception as e:
                k_info["msg"] = str(e)

            if deep and k_info["ok"] and active_gem_model:
                qs = urllib.parse.urlencode({"key": k})
                g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_gem_model}:generateContent?{qs}"
                g_payload = json.dumps({
                    "contents": [{"parts": [{"text": "ok"}]}],
                    "generationConfig": {"maxOutputTokens": 1, "temperature": 0.0}
                }).encode("utf-8")
                g_req = urllib.request.Request(g_url, data=g_payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(g_req, timeout=8) as g_resp:
                        if g_resp.status == 200:
                            auto_translate.record_gemini_status(k, model_name=active_gem_model, ok=True, msg=f"Sondagem Vision OK ({active_gem_model})")
                except urllib.error.HTTPError as ge:
                    g_body = ""
                    try:
                        g_body = ge.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                    if ge.code == 429:
                        auto_translate.record_gemini_error(k, active_gem_model, 429, g_body)
                    elif ge.code in (401, 403):
                        auto_translate.record_gemini_error(k, active_gem_model, ge.code, g_body)
                        k_info["ok"] = False
                        k_info["msg"] = f"Chave sem autorização (HTTP {ge.code})"

            snap_gem = auto_translate.get_gemini_quota_snapshot(k)
            if snap_gem.get("quota_exhausted") and snap_gem.get("quota_reset_sec", 0.0) > 0:
                k_info["ok"] = False
                k_info["quota_exhausted"] = True
                k_info["rate_limited"] = True
                k_info["quota_is_daily"] = bool(snap_gem.get("quota_is_daily"))
                k_info["quota_reset_sec"] = snap_gem.get("quota_reset_sec", 0.0)
                k_info["msg"] = snap_gem.get("last_msg") or "Cota Gemini atingida na última execução (429)"
            elif snap_gem.get("auth_error"):
                k_info["ok"] = False
                k_info["msg"] = snap_gem.get("last_msg") or k_info.get("msg", "Chave inválida")

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

    res["runtime_warnings"] = auto_translate.get_recent_quota_events()
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
    raw_dir = cfg.get("raw_mangas_dir")
    trans_dir = cfg.get("translated_mangas_dir")

    # Sanitização: Ignora caminhos Windows (ex: C:\...) quando rodando no Linux / Google Colab
    if os.name != "nt":
        if raw_dir and re.match(r"^[a-zA-Z]:", str(raw_dir)):
            raw_dir = None
        if trans_dir and re.match(r"^[a-zA-Z]:", str(trans_dir)):
            trans_dir = None

    if not raw_dir or not os.path.exists(raw_dir):
        raw_dir = BASE_MANGAS_DIR if (os.name == "nt" and os.path.exists(BASE_MANGAS_DIR)) else None
    if not trans_dir or not os.path.exists(trans_dir):
        trans_dir = BASE_MANGAS_DIR if (os.name == "nt" and os.path.exists(BASE_MANGAS_DIR)) else None

    translated = []
    raw = []
    seen_paths = set()

    trans_scan_folders = [trans_dir] if trans_dir else []
    raw_scan_folders = [raw_dir] if raw_dir else []

    roots = drive_helper.find_drive_roots()
    for r in roots:
        raw_m_dirs, trans_m_dirs = drive_helper.find_manga_directories(r)
        for td in trans_m_dirs:
            if td not in trans_scan_folders:
                trans_scan_folders.insert(0, td)
        for rd in raw_m_dirs:
            if rd not in raw_scan_folders:
                raw_scan_folders.insert(0, rd)

        # Se não foram encontradas subpastas nomeadas, escaneia a própria raiz do Drive
        if not raw_m_dirs and not trans_m_dirs:
            if r not in raw_scan_folders:
                raw_scan_folders.append(r)

    if os.path.exists(UPLOAD_DIR):
        if UPLOAD_DIR not in trans_scan_folders:
            trans_scan_folders.append(UPLOAD_DIR)
        if UPLOAD_DIR not in raw_scan_folders:
            raw_scan_folders.append(UPLOAD_DIR)

    for sf in trans_scan_folders:
        for e in drive_helper.scan_folder_for_mangas(sf, seen_paths, MANGA_PATH_CACHE, _get_pymupdf):
            if "[PT-BR]" in e["name"] or e["has_reader"]:
                translated.append(e)
            else:
                raw.append(e)

    for rf in raw_scan_folders:
        for e in drive_helper.scan_folder_for_mangas(rf, seen_paths, MANGA_PATH_CACHE, _get_pymupdf):
            if not e["has_reader"] and "[PT-BR]" not in e["name"]:
                raw.append(e)

    translated = drive_helper.deduplicate_entries(translated)
    raw = drive_helper.deduplicate_entries(raw)
    translated.sort(key=lambda x: x["mtime"], reverse=True)
    raw.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"translated": translated, "raw": raw})

@app.route("/api/download_folder")
def api_download_folder():
    """Compacta a pasta traduzida em um arquivo ZIP e envia diretamente para download no navegador."""
    path = request.args.get("path", "").strip('\"\'')
    if not path or not os.path.exists(path):
        return jsonify({"error": "Pasta não encontrada"}), 404
    if not is_path_allowed(path):
        return _forbidden()

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
    if not is_path_allowed(path):
        return _forbidden()

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
    if not is_path_allowed(path):
        return _forbidden()

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
    if os.path.isfile(img_path) and not img_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.zip', '.cbz', '.pdf')):
        return "", 400
    # Acesso remoto (token ativo): só miniaturas das pastas de mangás
    if ACCESS_TOKEN and not is_path_allowed(img_path):
        return "", 403

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
                logo_p = os.path.join(STATIC_DIR, "logo.png")
                if os.path.exists(logo_p):
                    return send_file(logo_p, mimetype="image/png")
                return "", 404
        return send_file(thumb_dest, mimetype="image/jpeg")
    except Exception:
        logo_p = os.path.join(STATIC_DIR, "logo.png")
        if os.path.exists(logo_p):
            return send_file(logo_p, mimetype="image/png")
        return "", 404

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
        if app_paths.FROZEN:
            # No .exe, sys.executable é o próprio programa: ele abre o seletor com --pick-folder
            # (manga_studio_app.py) e grava a escolha num arquivo, porque sem console não há stdout
            out_file = os.path.join(tempfile.gettempdir(), f"manga_studio_pick_{uuid.uuid4().hex}.txt")
            subprocess.run([sys.executable, "--pick-folder", title, init_dir or "", out_file], timeout=300)
            try:
                with open(out_file, encoding="utf-8") as f:
                    return f.read().strip()
            finally:
                if os.path.exists(out_file):
                    os.remove(out_file)
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        return proc.stdout.strip()
    except Exception as e:
        print(f"[!] Erro ao abrir seletor de pastas: {e}")
        return ""

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
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
    """Lista pastas e arquivos zip/cbz de mangás disponíveis no Google Drive com suporte a capítulos e variações."""
    roots = drive_helper.find_drive_roots()
    if not roots:
        return jsonify({"available": False, "folders": []})

    folders = []
    seen = set()
    search_dirs = []

    for r in roots:
        raw_dirs, trans_dirs = drive_helper.find_manga_directories(r)
        search_dirs.extend(raw_dirs)
        search_dirs.extend(trans_dirs)
        search_dirs.append(r)

    for base in search_dirs:
        for e in drive_helper.scan_folder_for_mangas(base, seen, MANGA_PATH_CACHE, _get_pymupdf):
            if e["path"] in search_dirs:
                continue
            folders.append({
                "name": e["name"],
                "path": e["path"],
                "pages": e["pages"],
                "is_archive": e.get("is_archive", False)
            })

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
            raw_dirs, _ = drive_helper.find_manga_directories(root)
            if raw_dirs:
                folder_path = raw_dirs[0]
                break
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
        if job_state["status"] in ("running", "paused"):
            return jsonify({"error": "Já existe uma tradução em andamento ou pausada!"}), 409

        job_ctrl.reset()
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
    provider = data.get("provider", "auto")
    colorize = bool(data.get("colorize", False))
    colorize_only = bool(data.get("colorize_only", False))
    color_reference = data.get("reference") or data.get("color_reference") or None

    def _worker():
        global job_state
        old_stdout = sys.stdout if sys.stdout is not None else SafeDummyStream()
        old_stderr = sys.stderr if sys.stderr is not None else SafeDummyStream()
        capture = StreamCapture(original_stream=old_stdout)
        sys.stdout = capture
        sys.stderr = capture

        def progress_callback(stage, current, total, text, result=None):
            job_ctrl.checkpoint()
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
                    elif stage == "colorize":
                        job_state["percentage"] = int(pct * 0.95) if colorize_only else 70 + int(pct * 0.25)
                    elif stage == "done":
                        job_state["percentage"] = 100
                if result:
                    job_state["result"] = result

        try:
            if colorize_only:
                import manga_colorizer
                res = manga_colorizer.colorize_manga_folder(
                    manga_path,
                    progress_cb=progress_callback,
                    reference=color_reference
                )
                with job_lock:
                    if not res or not res.get("success"):
                        job_state["status"] = "error"
                        job_state["error"] = "Falha ao colorir páginas do mangá."
                        job_state["message"] = "Erro: Nenhuma página colorida foi gerada."
                    else:
                        job_state["status"] = "done"
                        job_state["percentage"] = 100
                        out_p = res.get("output_dir", "")
                        if out_p:
                            m_id = get_manga_hash(out_p)
                            res["id"] = m_id
                            res["reader_url"] = f"/read/{m_id}/"
                        job_state["message"] = f"Mangá colorizado com sucesso ({res.get('total_pages', 0)} páginas) em {res.get('elapsed_seconds', 0)}s!"
                        job_state["result"] = res
                return

            cfg = auto_translate.load_config({"provider": provider})
            res = auto_translate.process_manga(
                manga_path,
                ocr_mode=ocr_mode,
                force_ocr=force_ocr,
                retranslate=retranslate,
                is_adult=is_adult,
                config=cfg,
                progress_cb=progress_callback,
                colorize=colorize,
                color_reference=color_reference
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
                    fb_cnt = int(res.get("fallback_bubbles_count", 0) or 0) if isinstance(res, dict) else 0
                    if fb_cnt > 0:
                        job_state["message"] = f"Concluído com fallback em {fb_cnt} fala(s) (cota/limite de IA atingido)."
                    else:
                        job_state["message"] = "Mangá traduzido e salvo com sucesso!"
                    if isinstance(res, dict):
                        out_p = res.get("output_dir", "")
                        if out_p:
                            m_id = get_manga_hash(out_p)
                            res["id"] = m_id
                            res["reader_url"] = f"/read/{m_id}/"
                        job_state["result"] = res
        except job_control.JobCancelledError:
            with job_lock:
                job_state["status"] = "cancelled"
                job_state["stage"] = "cancelled"
                job_state["message"] = "Tradução interrompida pelo usuário (progresso salvo no cache)."
                job_state["logs"].append("⏹️ Tradução encerrada com segurança. O cache já traduzido foi preservado!")
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

@app.route("/api/job/pause", methods=["POST"])
def api_job_pause():
    """Pausa a tradução em andamento no próximo ponto seguro."""
    with job_lock:
        if job_state["status"] != "running":
            return jsonify({"success": False, "error": "Nenhuma tradução ativa para pausar."}), 400
        job_ctrl.pause()
        job_state["status"] = "paused"
        job_state["message"] = "⏸️ Tradução pausada pelo usuário."
        job_state["logs"].append("⏸️ Pausa solicitada — aguardando retomar ou parar...")
    return jsonify({"success": True, "status": "paused"})

@app.route("/api/job/resume", methods=["POST"])
def api_job_resume():
    """Retoma uma tradução pausada."""
    with job_lock:
        if job_state["status"] != "paused":
            return jsonify({"success": False, "error": "A tradução não está pausada."}), 400
        job_ctrl.resume()
        job_state["status"] = "running"
        job_state["message"] = "▶️ Tradução retomada..."
        job_state["logs"].append("▶️ Tradução retomada pelo usuário.")
    return jsonify({"success": True, "status": "running"})

@app.route("/api/job/stop", methods=["POST"])
def api_job_stop():
    """Interrompe a tradução com segurança preservando o cache já traduzido."""
    with job_lock:
        if job_state["status"] not in ("running", "paused"):
            return jsonify({"success": False, "error": "Nenhuma tradução ativa para parar."}), 400
        job_ctrl.stop()
        job_state["message"] = "⏹️ Interrompendo tradução com segurança..."
        job_state["logs"].append("⏹️ Cancelamento solicitado — salvando cache e encerrando...")
    return jsonify({"success": True, "status": "stopping"})

@app.route("/api/colorize", methods=["POST"])
def api_colorize():
    """Endpoint direto para colorizar páginas de uma obra sem tradução."""
    return api_start_translation()

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
    """Valida chave de API ao vivo com diagnóstico realista de TPD/RPD/TPM, saldo líquido e cota Gemini 429."""
    data = request.json or {}
    provider = data.get("provider", "groq").lower()
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"valid": False, "msg": "Chave não informada."})

    cfg = auto_translate.load_config()
    deep = bool(data.get("deep", True))

    if provider == "groq":
        test_model = str(data.get("model") or cfg.get("groq_model") or "qwen/qwen3.8-27b").strip()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        ping_body = {"model": test_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        m_low = test_model.lower()
        if "qwen3" in m_low:
            ping_body["reasoning_effort"] = "none"
        elif "gpt-oss" in m_low:
            ping_body["reasoning_effort"] = "low"
        req = urllib.request.Request(url, data=json.dumps(ping_body).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                try:
                    raw_res = json.loads(resp.read().decode("utf-8"))
                    used_tok = int((raw_res.get("usage") or {}).get("total_tokens", 12) or 12)
                except Exception:
                    used_tok = 12
                auto_translate.record_groq_response_headers(key, test_model, resp.headers, used_tokens=used_tok, source="ping")

            if deep:
                ok_probe, probe_msg, snap = auto_translate.probe_groq_page_capacity(
                    key, test_model, target_tokens=1950, force=True
                )
            else:
                snap = auto_translate.get_groq_quota_snapshot(key, test_model)
                ok_probe = bool(snap.get("page_ready", True) and not snap.get("tpd_exhausted") and not snap.get("rpd_exhausted"))
                probe_msg = snap.get("status_reason", "Chave pronta")

            rem_req = snap.get("rem_req")
            lim_req = snap.get("lim_req")
            rem_tok = snap.get("rem_tok")
            tpd_exhausted = bool(snap.get("tpd_exhausted"))
            rpd_exhausted = bool(snap.get("rpd_exhausted"))
            if not ok_probe or tpd_exhausted or rpd_exhausted:
                return jsonify({
                    "valid": False,
                    "is_daily_limit": True,
                    "tpd_exhausted": tpd_exhausted,
                    "rpd_exhausted": rpd_exhausted,
                    "snapshot": snap,
                    "msg": f"Ping OK, porém BLOQUEADA para páginas reais no modelo '{test_model}': {probe_msg}"
                })
            r_str = f"{rem_req}/{lim_req}" if rem_req is not None and lim_req is not None else "OK"
            t_str = f"{rem_tok}" if rem_tok is not None else "OK"
            return jsonify({
                "valid": True,
                "snapshot": snap,
                "msg": f"Chave Groq 100% Operacional ({test_model})! {r_str} reqs/dia | {t_str} TPM | {probe_msg}"
            })
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            finally:
                try:
                    e.close()
                except Exception:
                    pass
            details = auto_translate.record_groq_error(key, test_model, e.code, err_body, e.headers) or auto_translate.parse_groq_rate_limit_details(err_body, e.headers, e.code)
            snap = auto_translate.get_groq_quota_snapshot(key, test_model)
            if e.code == 429:
                wait_txt = auto_translate._format_duration_pt(details.get("retry_after") or 0)
                if details.get("is_daily"):
                    return jsonify({
                        "valid": False,
                        "is_daily_limit": True,
                        "tpd_exhausted": details.get("limit_type") == "TPD",
                        "rpd_exhausted": details.get("limit_type") == "RPD",
                        "snapshot": snap,
                        "msg": f"Chave válida, porém cota diária {details.get('limit_type', 'TPD')} ESGOTADA em '{test_model}' (usados {details.get('used') or '?'}/{details.get('limit') or '?'}; libera em ~{wait_txt})."
                    })
                return jsonify({
                    "valid": True,
                    "rate_limited": True,
                    "snapshot": snap,
                    "msg": f"Chave Groq Válida! (Em pausa breve de {details.get('limit_type', 'TPM')}: libera em ~{wait_txt})."
                })
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
            net_creds = 0.0
            try:
                req_c = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers=headers)
                with urllib.request.urlopen(req_c, timeout=6) as c_resp:
                    cdata = json.loads(c_resp.read().decode("utf-8")).get("data", {})
                    net_creds = max(0.0, float(cdata.get("total_credits", 0) or 0) - float(cdata.get("total_usage", 0) or 0))
            except Exception:
                pass

            is_free_tier = bool(kdata.get("is_free_tier", True))
            free_info = kdata.get("free_model_daily_requests")
            snap_or = auto_translate.get_openrouter_quota_snapshot(key)

            if isinstance(free_info, dict) and ("limit" in free_info or "remaining" in free_info):
                f_lim = int(free_info.get("limit", 50) or 50)
                f_used = int(free_info.get("used", 0) or 0)
                f_rem = int(free_info.get("remaining", max(0, f_lim - f_used)) or 0)
                if f_rem <= 0 and net_creds <= 0.01:
                    return jsonify({
                        "valid": False,
                        "daily_exhausted": True,
                        "msg": f"Chave OpenRouter Free esgotou a cota diária ({f_used}/{f_lim} reqs :free usadas hoje; saldo $0.00 USD)."
                    })
                return jsonify({
                    "valid": True,
                    "msg": f"Chave OpenRouter Válida! Saldo líquido: ${net_creds:.2f} USD | {f_rem}/{f_lim} reqs :free restantes hoje."
                })

            if snap_or.get("daily_exhausted") and net_creds <= 0.01:
                return jsonify({
                    "valid": False,
                    "daily_exhausted": True,
                    "msg": f"Chave OpenRouter sem saldo (${net_creds:.2f} USD) e com cota diária :free atingida na última execução."
                })

            if net_creds > 0.01:
                return jsonify({
                    "valid": True,
                    "msg": f"Chave OpenRouter Paga Válida! Saldo líquido disponível: ${net_creds:.2f} USD."
                })
            tier_txt = "Free Tier (~50 reqs/dia em modelos :free)" if is_free_tier else "Saldo $0.00 USD"
            return jsonify({
                "valid": True,
                "msg": f"Chave OpenRouter Válida! Conta {tier_txt} | Saldo líquido: ${net_creds:.2f} USD (fila :free compartilhada)."
            })
        except urllib.error.HTTPError as e:
            return jsonify({"valid": False, "msg": f"Erro HTTP {e.code} no OpenRouter. Chave inválida ou recusada."})
        except Exception as e:
            return jsonify({"valid": False, "msg": f"Erro de conexão: {e}"})

    elif provider == "gemini":
        test_model = str(data.get("model") or cfg.get("gemini_model") or "gemini-3.1-flash-lite").strip()
        qs = urllib.parse.urlencode({"key": key})
        url = f"https://generativelanguage.googleapis.com/v1beta/models?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                gm_data = json.loads(resp.read().decode("utf-8"))
                gm_count = len(gm_data.get("models", []))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return jsonify({"valid": False, "quota_exhausted": True, "msg": "Cota Gemini atingida (HTTP 429)."})
            return jsonify({"valid": False, "msg": f"Erro HTTP {e.code} no Google Gemini. Verifique a chave (AIza...)."})
        except Exception as e:
            return jsonify({"valid": False, "msg": f"Erro de conexão Gemini: {e}"})

        if deep and test_model:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{test_model}:generateContent?{qs}"
            g_payload = json.dumps({
                "contents": [{"parts": [{"text": "ok"}]}],
                "generationConfig": {"maxOutputTokens": 1, "temperature": 0.0}
            }).encode("utf-8")
            g_req = urllib.request.Request(g_url, data=g_payload, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(g_req, timeout=10) as g_resp:
                    if g_resp.status == 200:
                        auto_translate.record_gemini_status(key, model_name=test_model, ok=True, msg=f"Sondagem OK ({test_model})")
                        return jsonify({"valid": True, "msg": f"Chave Google Gemini 100% Operacional em '{test_model}' ({gm_count} modelos liberados)."})
            except urllib.error.HTTPError as ge:
                g_body = ""
                try:
                    g_body = ge.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                finally:
                    try:
                        ge.close()
                    except Exception:
                        pass
                if ge.code == 429:
                    auto_translate.record_gemini_error(key, test_model, 429, g_body)
                    snap_g = auto_translate.get_gemini_quota_snapshot(key)
                    return jsonify({
                        "valid": False,
                        "quota_exhausted": True,
                        "msg": f"Chave reconhecida ({gm_count} modelos), porém COTA 429 ATINGIDA em '{test_model}' ({snap_g.get('last_msg') or 'limite excedido'})."
                    })
                if ge.code in (401, 403):
                    auto_translate.record_gemini_error(key, test_model, ge.code, g_body)
                    return jsonify({"valid": False, "msg": f"Chave Gemini sem permissão (HTTP {ge.code})."})

        snap_g = auto_translate.get_gemini_quota_snapshot(key)
        if snap_g.get("quota_exhausted") and snap_g.get("quota_reset_sec", 0.0) > 0:
            return jsonify({
                "valid": False,
                "quota_exhausted": True,
                "msg": f"Chave reconhecida ({gm_count} modelos), porém cota 429 registrada recentemente ({snap_g.get('last_msg')})."
            })
        return jsonify({"valid": True, "msg": f"Chave Google Gemini Válida! ({gm_count} modelos Vision liberados)."})

    return jsonify({"valid": False, "msg": "Provedor desconhecido."})

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    cfg_path = os.path.join(DATA_DIR, "config.json")
    if request.method == "POST":
        new_cfg = request.json or {}
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            # Espelha o perfil apenas no Google Drive (Colab), nunca em pastas fixas de outra máquina
            extra_paths = []
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
    # Só apaga obras DENTRO das pastas de mangás (nunca a própria pasta raiz)
    if not is_path_allowed(abs_p):
        return _forbidden()

    # Proteção de segurança: impede que caminhos críticos do sistema ou raízes sejam apagados
    forbidden_roots = [
        os.path.abspath("/"),
        os.path.abspath("C:\\"),
        os.path.abspath("C:\\Windows"),
        os.path.abspath("C:\\Users"),
        os.path.abspath(SYS_DIR),
        os.path.abspath(DATA_DIR),
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

@app.route("/api/dataset/export", methods=["POST"])
def api_dataset_export():
    """Exporta o histórico de traduções validadas para dataset_manga_ptbr.jsonl (ShareGPT/Alpaca) para fine-tuning."""
    try:
        import dataset_exporter
        fmt = (request.json or {}).get("format", "sharegpt")
        res = dataset_exporter.export_training_dataset(format_type=fmt)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "total_pairs": 0})

@app.route("/api/aprendizado", methods=["GET", "POST"])
def api_aprendizado():
    fpath = os.path.join(DATA_DIR, "aprendizado.txt")
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
    fpath = os.path.join(DATA_DIR, "glossary.json")
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

    reviews_file = os.path.join(DATA_DIR, "manga_reviews.json")
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
            if p.info['pid'] != curr_pid and any(n in (p.info['name'] or '').lower() for n in ('python', 'mangastudio')):
                try:
                    for c in p.net_connections():
                        if c.laddr.port == port:
                            p.kill()
                except Exception:
                    pass
    except Exception:
        pass

@app.route("/api/test_ollama", methods=["POST"])
def api_test_ollama():
    """Testa o endereço do Ollama digitado em Configurações: modelos, modelo escolhido e velocidade real."""
    import ollama_client
    data = request.get_json(silent=True) or {}
    cfg = auto_translate.load_config()
    host = (data.get("host") or cfg.get("ollama_host") or "http://localhost:11434").strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "O endereço precisa começar com http:// ou https://"}), 400
    cfg = dict(cfg, ollama_num_ctx=data.get("num_ctx") or cfg.get("ollama_num_ctx"))
    try:
        models = ollama_client.list_models(host)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Nenhum servidor respondendo: {e}"})
    if not models:
        return jsonify({"ok": False, "models": [], "error": "Servidor ligado, mas sem modelos baixados (ollama pull ...)."})
    model = ollama_client.pick_model(models, data.get("model") or cfg.get("ollama_model", ""), True)
    try:
        speed = ollama_client.speed_test(host, model, cfg)
    except Exception as e:
        return jsonify({"ok": False, "models": models, "model": model, "error": f"O modelo não respondeu: {e}"})
    ollama_client.forget_status(host)
    speed["speed_label"] = ollama_client.describe_speed(speed["tok_s"])
    return jsonify(dict(speed, models=models, model=model, host=host))


def _is_local_request():
    return request.remote_addr in ("127.0.0.1", "::1") and not any(h in request.headers for h in _TUNNEL_HEADERS)


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Encerra o servidor (botão "Encerrar Manga Studio"). Só no próprio computador e sem tradução rodando."""
    if not _is_local_request():
        return jsonify({"success": False, "error": "Só pode ser encerrado no próprio computador."}), 403
    with job_lock:
        running = job_state.get("status") in ("running", "paused")
    if running and not (request.get_json(silent=True) or {}).get("force"):
        return jsonify({"success": False, "running": True, "error": "Há uma tradução em andamento."}), 409
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return jsonify({"success": True})


def run_desktop(port=5050):
    """Sobe o servidor local e abre a janela do app (usado pelo .bat e pelo .exe)."""
    url = f"http://127.0.0.1:{port}"
    # Se o servidor já estiver rodando, apenas abre a janela do app sem recriar sockets
    if is_server_running(port):
        open_chrome_app(url, port)
        return
    kill_existing_on_port(port)
    time.sleep(0.5)
    threading.Timer(1.2, lambda: open_chrome_app(url, port)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    try:
        run_desktop(5050)
    except Exception as e:
        with open(os.path.join(DATA_DIR, "crash.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
