# -*- coding: utf-8 -*-
"""
MANGA TRANSLATOR STUDIO - BACKEND SERVER
Servidor local Flask com estética e arquitetura moderna para o app estilo Spotify.
"""

import sys
import os
import json
import time
import threading
import io
import urllib.request
import webbrowser
import subprocess
import traceback
from flask import Flask, render_template, jsonify, request, send_file, Response
from PIL import Image

# Protege contra execução via pythonw.exe onde sys.stdout e sys.stderr são None
class SafeDummyStream(io.StringIO):
    def write(self, s):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = SafeDummyStream()
if sys.stderr is None:
    sys.stderr = SafeDummyStream()

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

# Configurações globais
BASE_MANGAS_DIR = r"C:\Users\ja329\OneDrive\Documentos\MANGAS"
THUMB_CACHE_DIR = os.path.join(SYS_DIR, ".thumb_cache")
os.makedirs(THUMB_CACHE_DIR, exist_ok=True)

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
        if self.original_stream is not None and hasattr(self.original_stream, 'write'):
            try:
                self.original_stream.write(text)
            except Exception:
                pass

    def flush(self):
        if self.original_stream is not None and hasattr(self.original_stream, 'flush'):
            try:
                self.original_stream.flush()
            except Exception:
                pass

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    """Consulta cotas ao vivo do Groq, OpenRouter e Ollama."""
    cfg = auto_translate.load_config()
    res = {
        "groq": {"configured": False, "models": {}},
        "openrouter": {"configured": False, "keys": []},
        "ollama": {"status": "offline", "models": []}
    }
    
    # 1. GROQ
    groq_key = cfg.get("groq_api_key", "").strip()
    if groq_key:
        res["groq"]["configured"] = True
        res["groq"]["masked_key"] = groq_key[:8] + "..." + groq_key[-4:] if len(groq_key) > 12 else "***"
        res["groq"]["active_model"] = cfg.get("groq_model", "qwen/qwen3.8-27b")
        
        for m in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
            data = json.dumps({"model": m, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res["groq"]["models"][m] = {
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
                res["groq"]["models"][m] = {
                    "ok": False,
                    "code": e.code,
                    "is_daily_limit": is_tpd,
                    "msg": "Cota diária de 200k tokens atingida" if is_tpd else f"HTTP {e.code}"
                }
            except Exception as e:
                res["groq"]["models"][m] = {"ok": False, "msg": str(e)}

    # 2. OPENROUTER
    or_keys = cfg.get("openrouter_api_keys", [])
    if not or_keys and cfg.get("openrouter_api_key"):
        or_keys = [cfg.get("openrouter_api_key")]
    if or_keys:
        res["openrouter"]["configured"] = True
        for k in or_keys:
            k_info = {"key": k[:8] + "..." + k[-4:] if len(k) > 12 else "***", "ok": False}
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

    # 3. OLLAMA
    ol_host = cfg.get("ollama_host", "http://localhost:11434").rstrip("/")
    try:
        req_ol = urllib.request.Request(f"{ol_host}/api/tags")
        with urllib.request.urlopen(req_ol, timeout=2) as resp:
            if resp.status == 200:
                odata = json.loads(resp.read().decode("utf-8"))
                res["ollama"]["status"] = "online"
                res["ollama"]["models"] = [m.get("name") for m in odata.get("models", [])]
    except Exception:
        res["ollama"]["status"] = "offline"

    return jsonify(res)

@app.route("/api/library")
def api_library():
    """Retorna mangás traduzidos e obras prontas para traduzir."""
    translated = []
    raw = []
    if os.path.exists(BASE_MANGAS_DIR):
        for item in sorted(os.listdir(BASE_MANGAS_DIR)):
            full_p = os.path.join(BASE_MANGAS_DIR, item)
            if not os.path.isdir(full_p) or item.startswith(".") or item == "_ocr":
                continue
                
            # Conta imagens
            imgs = [f for f in os.listdir(full_p) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
            if not imgs:
                continue
                
            has_reader = os.path.exists(os.path.join(full_p, "leitor.html"))
            cbz_path = full_p.rstrip("/\\") + ".cbz"
            has_cbz = os.path.exists(cbz_path)
            
            first_img = os.path.join(full_p, sorted(imgs)[0])
            mtime = os.path.getmtime(full_p)
            
            entry = {
                "name": item,
                "clean_name": item.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                "path": full_p,
                "pages": len(imgs),
                "has_reader": has_reader,
                "has_cbz": has_cbz,
                "cbz_path": cbz_path if has_cbz else None,
                "reader_path": os.path.join(full_p, "leitor.html") if has_reader else None,
                "mtime": mtime,
                "first_img": first_img
            }
            
            if "[PT-BR]" in item or has_reader:
                translated.append(entry)
            else:
                raw.append(entry)
                
    translated.sort(key=lambda x: x["mtime"], reverse=True)
    raw.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"translated": translated, "raw": raw})

@app.route("/api/thumb")
def api_thumb():
    """Gera miniatura otimizada da capa do mangá."""
    img_path = request.args.get("path", "")
    if not img_path or not os.path.exists(img_path):
        return "", 404
        
    try:
        # Cria hash ou nome para cache
        thumb_name = str(abs(hash(img_path))) + ".jpg"
        thumb_dest = os.path.join(THUMB_CACHE_DIR, thumb_name)
        if not os.path.exists(thumb_dest):
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                im.thumbnail((320, 460), Image.Resampling.LANCZOS)
                im.save(thumb_dest, "JPEG", quality=85)
        return send_file(thumb_dest, mimetype="image/jpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/pick_folder", methods=["POST"])
def api_pick_folder():
    """Abre o diálogo nativo do Windows para selecionar a pasta do mangá."""
    selected_path = ""
    def _ask():
        nonlocal selected_path
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path = filedialog.askdirectory(
            initialdir=BASE_MANGAS_DIR if os.path.exists(BASE_MANGAS_DIR) else "C:\\",
            title="Selecione a Pasta do Mangá ou Manhwa"
        )
        root.destroy()
        
    t = threading.Thread(target=_ask)
    t.start()
    t.join()
    
    if selected_path:
        return jsonify({"success": True, "path": selected_path})
    return jsonify({"success": False, "path": ""})

@app.route("/api/inspect_folder", methods=["POST"])
def api_inspect_folder():
    """Inspeciona pasta informada para contar páginas e detectar idioma."""
    data = request.json or {}
    p = data.get("path", "").strip('\"\'')
    if not p or not os.path.exists(p) or not os.path.isdir(p):
        return jsonify({"valid": False, "error": "Pasta não encontrada"})
        
    imgs = [f for f in os.listdir(p) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not imgs:
        return jsonify({"valid": False, "error": "Nenhuma imagem encontrada na pasta"})
        
    first_img = os.path.join(p, sorted(imgs)[0])
    auto_lang = auto_translate.detect_manga_language_and_engine(p)
    lang_labels = {
        "korean": "Coreano (Manhwa / Webtoon)",
        "rapidocr": "Ocidental / Inglês / Chinês",
        "mokuro": "Japonês (Leitura Vertical)"
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

@app.route("/api/start", methods=["POST"])
def api_start_translation():
    """Inicia a tradução em background thread com streaming de progresso."""
    global job_state
    data = request.json or {}
    manga_path = data.get("path", "").strip('\"\'')
    if not manga_path or not os.path.exists(manga_path):
        return jsonify({"error": "Caminho do mangá inválido"}), 400

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
        capture = StreamCapture(original_stream=sys.stdout)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
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
                job_state["status"] = "done"
                job_state["percentage"] = 100
                job_state["message"] = "Mangá traduzido e salvo com sucesso!"
                if isinstance(res, dict):
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
        webbrowser.open("file://" + os.path.abspath(path))
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Arquivo não encontrado"}), 404

@app.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        os.startfile(path)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Pasta não encontrada"}), 404

@app.route("/api/open_cbz", methods=["POST"])
def api_open_cbz():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        os.startfile(path)
        return jsonify({"success": True})
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

    return jsonify({"valid": False, "msg": "Provedor desconhecido."})

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    cfg_path = os.path.join(SYS_DIR, "config.json")
    if request.method == "POST":
        new_cfg = request.json or {}
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            for extra_p in [
                r"C:\Users\ja329\tools\manga-translator\config.json",
                os.path.join(r"C:\Users\ja329\.gemini\antigravity\scratch\SKILL-TRADUCAO-MANGA", "config.json")
            ]:
                if os.path.exists(os.path.dirname(extra_p)):
                    try:
                        with open(extra_p, "w", encoding="utf-8") as ef:
                            json.dump(new_cfg, ef, indent=2, ensure_ascii=False)
                    except Exception: pass
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify(auto_translate.load_config())

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
