# -*- coding: utf-8 -*-
"""
studio/job_control.py - Controlador Thread-Safe de Pausa, Retomada e Cancelamento
Permite pausar ou interromper traduções em qualquer etapa preservando o cache.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import threading
import time


class JobCancelledError(BaseException):
    """Exceção dedicada de cancelamento (herda BaseException para atravessar except Exception)."""
    pass


class JobController:
    """Controla o ciclo de execução de uma tarefa ativa (rodando, pausada, cancelada)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._run_event = threading.Event()
        self._run_event.set()
        self._cancel_event = threading.Event()

    def reset(self):
        """Reinicia o controlador para uma nova tarefa."""
        with self._lock:
            self._cancel_event.clear()
            self._run_event.set()

    def pause(self):
        """Pausa a tarefa no próximo ponto de verificação seguro."""
        with self._lock:
            if self._cancel_event.is_set():
                return False
            self._run_event.clear()
            return True

    def resume(self):
        """Retoma a execução de uma tarefa pausada."""
        with self._lock:
            if self._cancel_event.is_set():
                return False
            self._run_event.set()
            return True

    def stop(self):
        """Solicita interrupção segura (desbloqueia imediatamente se estiver pausada)."""
        with self._lock:
            self._cancel_event.set()
            self._run_event.set()
            return True

    def is_paused(self):
        return (not self._run_event.is_set()) and (not self._cancel_event.is_set())

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def checkpoint(self):
        """Ponto de verificação cooperativo chamado entre páginas/etapas."""
        while not self._run_event.is_set():
            if self._cancel_event.is_set():
                raise JobCancelledError("Tradução interrompida pelo usuário.")
            time.sleep(0.25)
        if self._cancel_event.is_set():
            raise JobCancelledError("Tradução interrompida pelo usuário.")
