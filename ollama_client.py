"""
ollama_client.py - Conversa com o Ollama (IA no próprio PC, no Colab ou no Kaggle).

Antes (até a v0.8.0) o pedido usava a janela de contexto padrão do Ollama (poucos milhares de tokens):
o texto além dela era cortado sem aviso e a IA perdia regras e a ficha da obra. Aqui:
- "num_ctx" configurável (padrão 16384) e "think": false (Qwen3 não gasta tempo "pensando" em voz alta);
- espera maior (GPU grátis é lenta) e o estado do servidor fica guardado por alguns minutos,
  sem testar e "aquecer" o modelo a cada balão;
- escolha de modelo priorizando modelos atuais bons em japonês/coreano/inglês -> português.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request

DEFAULT_NUM_CTX = 16384
DEFAULT_TIMEOUT = 240
STATUS_TTL = 300  # segundos que o resultado de "servidor ligado + modelo escolhido" vale
HEARTBEAT_SECS = 30  # de quanto em quanto tempo o registro avisa que a IA local ainda está trabalhando

# Ordem de preferência para tradução (o nome escolhido em Configurações sempre vence)
PREFERRED_MODELS = ("qwen3", "translategemma", "gemma3", "qwen2.5", "mistral-small", "llama3.1", "gemma2",
                    "dolphin", "llama3", "mistral")
LEGACY_DEFAULT = "dolphin-llama3:latest"
_VISION_HINTS = ("vl", "vision", "llava", "moondream", "minicpm-v")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_status_cache = {}
_cache_lock = threading.Lock()


def num_ctx_from(cfg):
    try:
        return max(2048, min(131072, int((cfg or {}).get("ollama_num_ctx") or DEFAULT_NUM_CTX)))
    except (TypeError, ValueError):
        return DEFAULT_NUM_CTX


def timeout_from(cfg):
    try:
        return max(30, int((cfg or {}).get("ollama_timeout") or DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def pick_model(models, custom_model="", prefer_uncensored=False):
    """Escolhe o modelo de tradução entre os instalados. Ignora modelos só de visão quando há outros."""
    if not models:
        return None
    custom = (custom_model or "").strip().lower()
    if custom == LEGACY_DEFAULT:  # padrão antigo gravado nas configs até a v0.8.0: vale como "automático"
        custom = ""
    if custom:
        for m in models:
            if custom in m.lower():
                return m
    text_models = [m for m in models if not any(h in m.lower() for h in _VISION_HINTS)] or list(models)
    order = PREFERRED_MODELS
    if prefer_uncensored:
        # Modelos "abliterated"/"uncensored" da mesma família vêm antes (o Qwen3 já recusa pouco)
        for m in text_models:
            low = m.lower()
            if any(t in low for t in ("abliterated", "uncensored")) and any(p in low for p in order[:4]):
                return m
    for pref in order:
        for m in text_models:
            if pref in m.lower():
                return m
    return text_models[0]


def list_models(host, timeout=8):
    host = host.rstrip("/")
    with urllib.request.urlopen(urllib.request.Request(f"{host}/api/tags"), timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def _status_key(host, custom_model, prefer_uncensored):
    custom = (custom_model or "").strip().lower()
    # Com o modelo fixo em Configurações, o modo adulto não muda a escolha: um aquecimento só
    return host.rstrip("/"), custom, bool(prefer_uncensored) and not custom


def cached_status(host, custom_model="", prefer_uncensored=False):
    """(ok, modelo) guardado há menos de STATUS_TTL segundos, ou None."""
    key = _status_key(host, custom_model, prefer_uncensored)
    with _cache_lock:
        hit = _status_cache.get(key)
    if hit and time.time() - hit[0] < STATUS_TTL:
        return hit[1], hit[2]
    return None


def remember_status(host, custom_model, prefer_uncensored, ok, model):
    key = _status_key(host, custom_model, prefer_uncensored)
    with _cache_lock:
        _status_cache[key] = (time.time(), ok, model)


def forget_status(host=None):
    with _cache_lock:
        if host is None:
            _status_cache.clear()
        else:
            for k in [k for k in _status_cache if k[0] == host.rstrip("/")]:
                _status_cache.pop(k, None)


def _payload(messages, model, temperature, num_predict, num_ctx):
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": "60m",
        "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": num_ctx},
    }


def _post(host, payload, timeout):
    req = urllib.request.Request(f"{host.rstrip('/')}/api/chat", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        # Ollama antigo não conhece "think": tenta de novo sem ele
        if e.code == 400 and "think" in body.lower() and "think" in payload:
            payload = {k: v for k, v in payload.items() if k != "think"}
            return _post(host, payload, timeout)
        raise


def _open(host, payload, timeout):
    """Abre o pedido em streaming. O tempo de espera vale por trecho recebido, não pela resposta inteira."""
    req = urllib.request.Request(f"{host.rstrip('/')}/api/chat", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        if e.code == 400 and "think" in body.lower() and "think" in payload:
            return _open(host, {k: v for k, v in payload.items() if k != "think"}, timeout)
        raise


def _read_stream(resp):
    """Junta os trechos da resposta. Devolve (texto, último objeto com as estatísticas)."""
    parts, final = [], {}
    with resp:
        for raw in resp:
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("error"):
                raise RuntimeError(f"Ollama: {obj['error']}")
            parts.append((obj.get("message") or {}).get("content", ""))
            final = obj
            if obj.get("done"):
                break
    return "".join(parts), final


def _heartbeat(stop, label, t0):
    while not stop.wait(HEARTBEAT_SECS):
        print(f"    [IA local] {label} ainda trabalhando ({int(time.time() - t0)} s)...", flush=True)


def _summary(label, final, secs):
    n_out = final.get("eval_count") or 0
    dur = (final.get("eval_duration") or 0) / 1e9
    speed = f" a {n_out / dur:.1f} tokens/s" if dur else ""
    return (f"    [IA local] {label} respondeu em {secs:.0f} s (leu {final.get('prompt_eval_count') or 0} tokens, "
            f"escreveu {n_out}{speed}).")


def chat(messages, model, host, temperature=0.0, num_predict=1024, cfg=None, timeout=None, label=""):
    """Resposta de texto do modelo, sem blocos <think>. Com 'label', escreve o andamento no registro."""
    payload = _payload(messages, model, temperature, num_predict, num_ctx_from(cfg))
    payload["stream"] = True
    t0 = time.time()
    stop = threading.Event()
    if label:
        print(f"    [IA local] {label} traduzindo... (sem placa de vídeo pode levar alguns minutos)", flush=True)
        threading.Thread(target=_heartbeat, args=(stop, label, t0), daemon=True).start()
    try:
        content, final = _read_stream(_open(host, payload, timeout or timeout_from(cfg)))
    finally:
        stop.set()
    if label:
        print(_summary(label, final, time.time() - t0), flush=True)
    return _THINK_RE.sub("", content).strip()


def gpu_share(host, model, timeout=5):
    """Parte do modelo (0 a 1) que está na memória da placa de vídeo, ou None se não der para saber."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/ps", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    for m in data.get("models", []):
        if model in (m.get("name"), m.get("model")):
            size = m.get("size") or 0
            return (m.get("size_vram") or 0) / size if size else None
    return None


def describe_placement(model, share):
    """Linha para o registro dizendo se o modelo roda na placa de vídeo ou no processador."""
    if share is None:
        return ""
    if share >= 0.99:
        return f"[+] IA local '{model}' rodando 100% na placa de vídeo."
    cpu = round((1 - share) * 100)
    return (f"[!] IA local '{model}': {cpu}% do modelo ficou no processador, então cada página pode levar minutos. "
            "Feche jogos e programas pesados, ou rode Instalar_IA_Local.bat de novo.")


def speed_test(host, model, cfg=None):
    """Mede a velocidade real (tokens/s) com uma frase curta. Devolve dict com ok, tok_s, segundos e amostra."""
    msgs = [{"role": "user", "content": "Traduza para português do Brasil, só a tradução: "
                                         "\"I told you not to come here alone!\""}]
    t0 = time.time()
    data = _post(host, _payload(msgs, model, 0.0, 48, num_ctx_from(cfg)), timeout_from(cfg))
    secs = time.time() - t0
    n_tok = data.get("eval_count") or 0
    dur_ns = data.get("eval_duration") or 0
    tok_s = (n_tok / (dur_ns / 1e9)) if dur_ns else (n_tok / secs if secs else 0)
    sample = _THINK_RE.sub("", (data.get("message") or {}).get("content", "")).strip()
    return {"ok": bool(sample), "tok_s": round(tok_s, 1), "seconds": round(secs, 1), "sample": sample[:120]}


def describe_speed(tok_s):
    """Frase curta para a tela de Configurações."""
    if tok_s >= 25:
        return "rápida (cerca de 10 s por página)"
    if tok_s >= 10:
        return "boa (cerca de 20 a 40 s por página)"
    if tok_s > 0:
        return "lenta (mais de 1 min por página: use um modelo menor ou GPU)"
    return "sem medida"
