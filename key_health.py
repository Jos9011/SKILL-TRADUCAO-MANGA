"""
key_health.py - Separa "a chave ficou sem cota" de "a rede ou o servidor falhou agora".

Até a v0.8.5, qualquer erro numa chave Groq (demora de 45 s, 503 de servidor cheio, um 400 qualquer)
fazia o roteador marcar a chave como "sem cota". Com o Groq instável, todas as chaves caíam de uma
vez, o resto do capítulo ia para o Google literal e a tela de Cotas continuava mostrando saldo.
Agora só 429 de limite diário e 401/403 tiram a chave da fila; o resto deixa a chave de lado por
alguns segundos e ela volta a ser usada.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import socket
import time
import urllib.error

KEY_COOLDOWN = 20.0       # segundos que uma chave fica de lado depois de uma falha passageira
MODEL_COOLDOWN = 15.0     # idem para chave:modelo
MAX_TRANSIENT_MODELS = 2  # depois de 2 modelos com falha passageira na mesma chave, passa para a próxima
SHORT_WAIT = 60           # espera curta quando as chaves só falharam por instabilidade
MAX_SHORT_WAITS = 3

_MODEL_GONE = ("model_not_found", "model not found", "does not exist", "decommissioned",
               "no longer supported", "invalid model", "not a valid model", "unknown model")


class GroqTransientError(RuntimeError):
    """Falha passageira (rede, timeout, 5xx, resposta estranha). A chave continua com cota."""

    def __init__(self, message, retry_after=KEY_COOLDOWN):
        super().__init__(message)
        self.retry_after = float(retry_after)


def is_model_gone(http_code, body=""):
    """Só 404 ou uma mensagem clara de modelo inexistente/desativado conta como modelo indisponível."""
    if int(http_code or 0) == 404:
        return True
    low = str(body or "").lower()
    return int(http_code or 0) == 400 and any(tok in low for tok in _MODEL_GONE)


def is_timeout(exc):
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(exc).lower()


def is_transient(exc):
    """Erros que não dizem nada sobre a cota: rede, timeout, 5xx e códigos inesperados."""
    if isinstance(exc, GroqTransientError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code in (408, 409, 425, 498)
    return isinstance(exc, (urllib.error.URLError, OSError, ValueError, TimeoutError)) or is_timeout(exc)


def bench_key(engine_opts, key, secs=KEY_COOLDOWN, now=None):
    if engine_opts is None or not key:
        return
    now = time.time() if now is None else now
    engine_opts.setdefault("groq_key_cooldowns", {})[str(key).strip()] = now + float(secs)


def is_benched(engine_opts, key, now=None):
    now = time.time() if now is None else now
    until = (engine_opts or {}).get("groq_key_cooldowns", {}).get(str(key or "").strip(), 0.0)
    return until > now


def benched_wait(engine_opts, keys, now=None):
    """Quanto falta para a primeira das chaves sair do descanso (0 se alguma já está livre)."""
    now = time.time() if now is None else now
    cds = (engine_opts or {}).get("groq_key_cooldowns", {})
    waits = [max(0.0, cds.get(str(k).strip(), 0.0) - now) for k in keys]
    return min(waits) if waits else 0.0


def can_short_wait(engine_opts):
    """Espera curta (1 min) quando só houve instabilidade, no máximo MAX_SHORT_WAITS vezes seguidas."""
    return int((engine_opts or {}).get("_short_waits", 0)) < MAX_SHORT_WAITS


def note_short_wait(engine_opts):
    engine_opts["_short_waits"] = int(engine_opts.get("_short_waits", 0)) + 1


def note_success(engine_opts):
    if engine_opts is not None:
        engine_opts.pop("_short_waits", None)
