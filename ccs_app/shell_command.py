"""Commande `!` du chat : une commande du shell lancée dans le dossier du projet.

Lancée par `bash -lc` dans son propre groupe de processus (`start_new_session`) : l'arrêt
touche la commande et ses enfants, même ceux laissés en fond après la fin de bash. La sortie
(standard et erreur fusionnées) est gardée jusqu'à `MAX_OUTPUT` caractères, le reste est lu et
jeté pour que la commande n'attende jamais un tube plein. Un processus laissé en fond
(`npm run dev &`) garde la sortie ouverte : la main est rendue `AFTER_EXIT_S` s après la fin de
bash, et la suite de sa sortie est lue et jetée. Sans GTK : `on_done` est rappelé depuis le fil
de lecture, ou par `dispatch(fonction)` si on en donne un (l'interface passe par
`GLib.idle_add`).
"""

import os
import select
import signal
import subprocess
import threading
import time

MAX_OUTPUT = 20000        # caractères gardés
KILL_AFTER_S = 2          # SIGKILL si SIGTERM n'a pas suffi
AFTER_EXIT_S = 2          # bash fini : la main est rendue au plus tard après ce délai
_POLL_S = 0.2
_CHUNK = 65536


class ShellRun:
    def __init__(self, command, cwd, dispatch=None):
        self.command = command
        self.cwd = cwd
        self._dispatch = dispatch
        self._proc = None
        self._stopped = False

    def start(self, on_done):
        """Lance la commande ; `on_done(code, sortie, tronquée)` à la fin. Une commande qui ne
        peut pas démarrer (dossier absent…) finit avec le code 127 et le motif pour sortie."""
        def finish(code, text, truncated):
            if self._dispatch is not None:
                self._dispatch(lambda: on_done(code, text, truncated))
            else:
                on_done(code, text, truncated)

        try:
            self._proc = subprocess.Popen(
                ["bash", "-lc", self.command], cwd=self.cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            threading.Thread(target=finish, args=(127, f"Impossible de lancer la commande : {e}", False),
                             daemon=True).start()
            return
        threading.Thread(target=self._read, args=(self._proc, finish), daemon=True).start()

    def _read(self, proc, finish):
        keep, size, cap = [], 0, MAX_OUTPUT * 4          # octets : jusqu'à 4 par caractère
        fd = proc.stdout.fileno()
        deadline, eof = None, False
        while True:
            if deadline is None and proc.poll() is not None:
                deadline = time.monotonic() + AFTER_EXIT_S
            wait = _POLL_S if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                ready = select.select([fd], [], [], wait)[0]
            except (OSError, ValueError):
                break
            if not ready:
                if deadline is not None and time.monotonic() >= deadline:
                    break           # bash est fini ; un processus en fond garde la sortie ouverte
                continue
            try:
                chunk = os.read(fd, _CHUNK)
            except OSError:
                break
            if not chunk:
                eof = True
                break
            if size < cap:
                keep.append(chunk[:cap - size])
            size += len(chunk)
        code = proc.wait()
        text = b"".join(keep).decode("utf-8", errors="replace")
        truncated = size > cap or len(text) > MAX_OUTPUT
        finish(code, text[:MAX_OUTPUT], truncated)
        try:
            while not eof and os.read(fd, _CHUNK):      # le processus en fond ne bloque jamais
                pass
        except OSError:
            pass
        proc.stdout.close()

    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def stop(self):
        """SIGTERM au groupe de processus, puis SIGKILL après `KILL_AFTER_S` s s'il tourne
        encore ; aussi après la fin de bash, pour les processus qu'il a laissés en fond."""
        proc = self._proc
        if proc is None:
            return
        self._stopped = True
        self._signal(proc, signal.SIGTERM)
        timer = threading.Timer(KILL_AFTER_S, lambda: self._signal(proc, signal.SIGKILL))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _signal(proc, sig):
        try:
            os.killpg(proc.pid, sig)          # le groupe existe tant qu'un de ses processus vit
        except (ProcessLookupError, PermissionError):
            pass
