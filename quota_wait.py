"""
quota_wait.py - Quando TODAS as IAs ficam sem cota, esperar e continuar em vez de traduzir literal.

Até a v0.8.0 o sistema caía no Google Tradutor, que traduz fala por fala sem contexto
("palavras só traduzidas, não adaptadas"). Agora, no modo "wait" (padrão), a tradução pausa,
avisa na tela e tenta de novo a cada INTERVAL segundos. O botão Parar/Pausar continua valendo
(o aviso passa pelo progress_cb, que consulta o controle da tarefa). Depois de MAX_HOURS sem cota,
cai no Google para não travar para sempre. config.json: "quota_fallback": "wait" | "google".
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import math
import time

INTERVAL = 600      # 10 minutos entre tentativas
MAX_HOURS = 12.0
STEP = 30           # de quanto em quanto tempo o aviso é atualizado (e o botão Parar é conferido)
RECHECK_SECS = 300  # IA marcada "sem cota" volta a ser tentada depois de 5 min (o Groq libera aos poucos)
_EXHAUSTION_KEYS = ("exhausted_engines", "exhausted_groq_keys", "exhausted_groq_models", "gemini_text_exhausted",
                    "openrouter_exhausted_keys", "exhausted_keys")


def mode(cfg):
    return "google" if str((cfg or {}).get("quota_fallback", "wait")).lower() == "google" else "wait"


def has_any_engine(cfg):
    """Só faz sentido esperar se existe alguma IA configurada (chave ou servidor Ollama)."""
    cfg = cfg or {}
    keys = (cfg.get("groq_api_keys") or cfg.get("groq_api_key") or cfg.get("openrouter_api_keys")
            or cfg.get("openrouter_api_key") or cfg.get("gemini_api_keys") or cfg.get("gemini_api_key"))
    host = str(cfg.get("ollama_host", "") or "")
    remote_ollama = host and "localhost" not in host and "127.0.0.1" not in host
    return bool(keys or remote_ollama)


def should_wait(cfg, engine_opts):
    if mode(cfg) != "wait" or not has_any_engine(cfg):
        return False
    started = engine_opts.get("_quota_wait_started")
    return started is None or (time.time() - started) < MAX_HOURS * 3600


def reset_engines(engine_opts, forget_local=True):
    """Libera as IAs marcadas como esgotadas para a próxima tentativa (as que ainda estiverem sem cota
    respondem 429 de novo em um pedido e voltam a ser marcadas). Chaves recusadas (401/403) continuam fora."""
    for key in _EXHAUSTION_KEYS:
        val = engine_opts.get(key)
        if isinstance(val, (set, list, dict)):
            val.clear()
    bad_keys = engine_opts.get("groq_auth_failed")
    if bad_keys:
        engine_opts.setdefault("exhausted_groq_keys", set()).update(bad_keys)
    engine_opts.get("groq_model_cooldowns", {}).clear()
    engine_opts.pop("_google_announced", None)
    engine_opts.pop("_exhausted_since", None)
    if forget_local:
        try:
            import ollama_client
            ollama_client.forget_status()
        except Exception:
            pass


def _has_exhaustion(engine_opts):
    bad = engine_opts.get("groq_auth_failed") or set()
    for key in _EXHAUSTION_KEYS:
        val = engine_opts.get(key)
        if key == "exhausted_groq_keys" and val:
            val = set(val) - set(bad)
        if val:
            return True
    return False


def maybe_recheck(engine_opts, now=None):
    """Sem isto, uma IA marcada "sem cota" ficava fora até o fim do capítulo. Com a IA local ligada,
    a espera de cota (que limpa as marcas) nunca acontecia e todo o resto ia para a IA local, lenta,
    enquanto as chaves já tinham cota de novo. Devolve True quando liberou as IAs para nova tentativa."""
    now = time.time() if now is None else now
    if not _has_exhaustion(engine_opts):
        engine_opts.pop("_exhausted_since", None)
        return False
    since = engine_opts.setdefault("_exhausted_since", now)
    if now - since < RECHECK_SECS:
        return False
    reset_engines(engine_opts, forget_local=False)
    print(f"\n[*] Passaram {RECHECK_SECS // 60} min: conferindo de novo as chaves de IA marcadas sem cota...")
    return True


def wait_for_quota(engine_opts, reasons="", sleep=time.sleep, interval=INTERVAL, step=STEP):
    """Espera `interval` segundos avisando na tela; levanta a exceção do botão Parar se ele for usado.
    Depois libera as IAs para nova tentativa. Devolve o total de esperas feitas."""
    engine_opts.setdefault("_quota_wait_started", time.time())
    waits = engine_opts.get("_quota_waits", 0) + 1
    engine_opts["_quota_waits"] = waits
    hook = engine_opts.get("_progress_hook")
    if waits == 1:
        print(f"\n[*] Cotas de IA esgotadas ({reasons or 'todas as IAs'}). Esperando para continuar com contexto, "
              f"em vez de traduzir literal. (Configurações > Tradução muda isso.)")
    remaining = interval
    while remaining > 0:
        if hook:
            hook(f"Cotas de IA esgotadas: tentando de novo em {math.ceil(remaining / 60)} min. "
                 f"Pode Parar e continuar depois, nada se perde.")
        chunk = min(step, remaining)
        sleep(chunk)
        remaining -= chunk
    reset_engines(engine_opts)
    print(f"[*] Tentando as IAs de novo (espera {waits}).")
    return waits
