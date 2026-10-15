"""Calculs lourds dans des processus séparés : PyMuPDF garde le GIL pendant ses appels
(OCR, compression, conversion), un simple thread figerait l'interface. Progression et
annulation immédiate (les processus sont arrêtés). Sans Qt : `task` est tout objet ayant
`.cancelled` et `.emit_partial()` (ui.workers.Task)."""

from __future__ import annotations

import multiprocessing
import os
import time
from collections.abc import Callable, Iterable
from typing import Any

from pdfmanager.core.document import Cancelled

POLL = 0.05  # s, réactivité de l'annulation


def _pool(workers: int):
    # spawn partout : identique sous Linux et Windows, et sûr avec des threads Qt actifs
    return multiprocessing.get_context("spawn").Pool(workers)


def parallel_map(task, fn: Callable[[Any], Any], items: Iterable[Any], total: int, *,
                 workers: int | None = None, label: str = "") -> list[Any]:
    """[fn(x) for x in items], calculé par plusieurs processus. `items` est consommé au
    fur et à mesure (deux tâches d'avance par processus) : des images de pages
    volumineuses ne sont pas toutes en mémoire. `fn` : fonction de module (picklable)."""
    workers = max(1, min(workers or (os.cpu_count() or 2) - 1, total, 6))
    results: list[Any] = [None] * total
    pending: dict[int, Any] = {}
    source = iter(enumerate(items))
    done = 0
    with _pool(workers) as pool:  # sortie du bloc : processus arrêtés (terminate)
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < 2 * workers:
                try:
                    i, item = next(source)
                except StopIteration:
                    exhausted = True
                    break
                pending[i] = pool.apply_async(fn, (item,))
            for i, r in list(pending.items()):
                if r.ready():
                    results[i] = r.get()  # relève l'exception du processus, le cas échéant
                    del pending[i]
                    done += 1
                    task.emit_partial((done, total, label))
            if task.cancelled:
                raise Cancelled
            time.sleep(POLL)
    return results


def run_in_process(task, fn: Callable[..., Any], *args: Any) -> Any:
    """fn(*args) dans un processus ; l'annulation l'arrête net."""
    with _pool(1) as pool:
        r = pool.apply_async(fn, args)
        while not r.ready():
            if task.cancelled:
                raise Cancelled
            time.sleep(POLL)
        return r.get()
