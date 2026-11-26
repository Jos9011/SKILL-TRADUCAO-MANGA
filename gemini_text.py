"""
gemini_text.py - Google Gemini como TRADUTOR de texto (até a v0.8.0 ele só lia imagens).

O plano grátis do Gemini Flash-Lite aceita pedidos grandes (centenas de milhares de tokens por minuto),
então cabe o capítulo inteiro num pedido só: a IA lê a história toda e gasta poucos pedidos da cota.
Recusa por conteúdo (+18) NÃO queima a chave: só aquele pedido volta para o caminho normal.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import time
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
DEFAULT_TEXT_MODEL = "gemini-3.1-flash-lite"
SAFETY_OFF = [{"category": c, "threshold": "BLOCK_NONE"} for c in (
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT", "HARM_CATEGORY_CIVIC_INTEGRITY")]
BLOCK_REASONS = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "OTHER")


class GeminiBlocked(Exception):
    """O Gemini recusou ESTE conteúdo (ex.: +18). A chave continua boa."""


class GeminiQuotaExhausted(Exception):
    """Todas as chaves Gemini sem cota ou inválidas."""


def key_pool(cfg):
    raw = list((cfg or {}).get("gemini_api_keys") or [])
    single = (cfg or {}).get("gemini_api_key")
    if single and single not in raw:
        raw.insert(0, single)
    return [str(k).strip() for k in raw if str(k or "").strip() and not str(k).strip().startswith(("gsk_", "sk-or-"))]


def text_model(cfg):
    return str((cfg or {}).get("gemini_text_model") or (cfg or {}).get("gemini_model") or DEFAULT_TEXT_MODEL).strip()


def to_gemini_payload(messages, max_tokens=8192, temperature=0.2, json_mode=True):
    """Mensagens no formato OpenAI -> corpo do generateContent (system vira systemInstruction)."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    contents = []
    for m in messages:
        if m.get("role") == "system":
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": str(m.get("content", ""))}]})
    gen_cfg = {"temperature": temperature, "maxOutputTokens": int(max_tokens)}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    body = {"contents": contents, "safetySettings": SAFETY_OFF, "generationConfig": gen_cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def parse_response(data):
    """Texto da resposta; GeminiBlocked se o conteúdo foi recusado."""
    fb = data.get("promptFeedback") or {}
    if fb.get("blockReason"):
        raise GeminiBlocked(f"pedido recusado ({fb.get('blockReason')})")
    cands = data.get("candidates") or []
    if not cands:
        raise GeminiBlocked("sem resposta (conteúdo recusado)")
    reason = str(cands[0].get("finishReason", "")).upper()
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if reason in BLOCK_REASONS and not text:
        raise GeminiBlocked(f"resposta recusada ({reason})")
    if not text:
        raise RuntimeError("Gemini devolveu resposta vazia")
    return text


def _http_error(e):
    body = ""
    try:
        body = e.read().decode("utf-8", errors="ignore")
    except Exception:
        pass
    return e.code, body.lower()


def chat(messages, cfg, state=None, max_tokens=8192, temperature=0.2, json_mode=True, timeout=180, opener=None,
         sleep=time.sleep):
    """Traduz com o Gemini, trocando de chave quando uma acaba. `state` (dict) guarda as chaves esgotadas
    durante o capítulo. Levanta GeminiBlocked (conteúdo) ou GeminiQuotaExhausted (sem chaves)."""
    state = state if state is not None else {}
    exhausted = state.setdefault("gemini_text_exhausted", set())
    keys = key_pool(cfg)
    model = text_model(cfg)
    open_fn = opener or urllib.request.urlopen
    body = json.dumps(to_gemini_payload(messages, max_tokens, temperature, json_mode)).encode("utf-8")
    last = "nenhuma chave Gemini cadastrada"
    for idx, key in enumerate(keys):
        if idx in exhausted:
            continue
        for attempt in range(2):  # 2ª tentativa só depois de um limite POR MINUTO
            req = urllib.request.Request(API_URL.format(model=model, key=key), data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with open_fn(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                state["gemini_text_last_key"] = idx
                return parse_response(data)
            except urllib.error.HTTPError as e:
                code, low = _http_error(e)
                if code == 400 and "json" in low and json_mode:
                    return chat(messages, cfg, state, max_tokens, temperature, False, timeout, opener, sleep)
                if code == 429 and attempt == 0 and not ("per day" in low or "daily" in low or "perday" in low):
                    sleep(30)
                    continue
                if code in (401, 403) or (code == 400 and "api key" in low):
                    last = f"chave {idx + 1} inválida"
                elif code == 429:
                    last = f"chave {idx + 1} sem cota hoje"
                elif code == 404:
                    raise RuntimeError(f"modelo '{model}' não existe para esta chave")
                else:
                    last = f"erro HTTP {code}"
                exhausted.add(idx)
                break
    raise GeminiQuotaExhausted(f"Gemini indisponível: {last}")


def has_quota(cfg, state=None):
    state = state or {}
    exhausted = state.get("gemini_text_exhausted", set())
    return any(i not in exhausted for i in range(len(key_pool(cfg))))
