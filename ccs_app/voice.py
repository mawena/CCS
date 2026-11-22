"""Vocal au bureau (phase 35) : lecture à voix haute des réponses par speech-dispatcher (`spd-say`)
et dictée par Whisper en local (`faster-whisper`, facultatif). Rien ne quitte la machine.

- `speech_text(markdown)` : le texte à lire d'une réponse (sans code, marques ni adresses).
- `Speaker` : une lecture à la fois ; `speak()` la remplace, `stop()` la coupe.
- `Recorder` : enregistre le micro dans un WAV 16 kHz mono (`pw-record`, `parecord` ou `arecord`).
- `transcribe(path)` : le texte dicté, par Whisper (modèle chargé une fois, gardé ensuite).
"""

import importlib.util
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading

LANG = "fr"
MODEL = os.environ.get("CCS_WHISPER_MODEL", "small")    # tiny, base, small, medium…

_CODE = re.compile(r"```.*?(```|\Z)", re.S)
_SUBS = (
    (re.compile(r"`([^`\n]*)`"), r"\1"),
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"https?://\S+"), "lien"),
    (re.compile(r"^\s{0,3}#{1,6}\s+", re.M), ""),
    (re.compile(r"^\s{0,3}>\s?", re.M), ""),
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),
    (re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.M), ""),
    (re.compile(r"\|"), ", "),
    (re.compile(r"(\*\*|__|\*|_|~~)(?=\S)(.*?\S)\1", re.S), r"\2"),
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n{2,}"), "\n"),
)


def speech_text(markdown):
    """Texte lu d'une réponse en Markdown (même règles que la version web, voice.js)."""
    text = _CODE.sub(" bloc de code. ", markdown or "")
    for pattern, repl in _SUBS:
        text = pattern.sub(repl, text)
    return text.strip()


# ── Lecture ───────────────────────────────────────────────────────────────────────────────

def can_speak():
    return shutil.which("spd-say") is not None


class Speaker:
    """Une lecture à la fois. `on_end` est appelé (depuis un fil à part) quand elle finit ou
    qu'elle est coupée ; `key` repère ce qui est lu (le même bouton arrête)."""

    def __init__(self):
        self._proc = None
        self.key = None
        self._lock = threading.Lock()

    def speaking(self):
        return self._proc is not None and self._proc.poll() is None

    def speak(self, markdown, key=None, on_end=None):
        text = speech_text(markdown)
        if not text or not can_speak():
            return False
        self.stop()
        # -w : spd-say attend la fin de la lecture, ce qui dit quand elle est finie ; -e : texte sur l'entrée
        proc = subprocess.Popen(["spd-say", "-w", "-l", LANG, "-e"], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        with self._lock:
            self._proc, self.key = proc, key
        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except OSError:
            pass

        def wait():
            proc.wait()
            with self._lock:
                if self._proc is proc:
                    self._proc, self.key = None, None
            if on_end is not None:
                on_end()
        threading.Thread(target=wait, daemon=True).start()
        return True

    def stop(self):
        with self._lock:
            proc, self._proc, self.key = self._proc, None, None
        if proc is None or proc.poll() is not None:
            return
        subprocess.run(["spd-say", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        proc.terminate()


# ── Dictée ────────────────────────────────────────────────────────────────────────────────

def whisper_installed():
    return importlib.util.find_spec("faster_whisper") is not None


def recorder_command(path):
    """Commande qui enregistre le micro dans `path` (WAV 16 kHz mono), ou None sans outil."""
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", path]
    if shutil.which("parecord"):
        return ["parecord", "--rate=16000", "--channels=1", "--format=s16le", "--file-format=wav", path]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", path]
    return None


def can_dictate():
    return whisper_installed() and recorder_command("x.wav") is not None


class Recorder:
    """Enregistrement du micro : `start()` puis `stop()`, qui rend le chemin du WAV (à effacer
    après la transcription) ou None si rien n'a été enregistré."""

    def __init__(self):
        self._proc = None
        self.path = None

    def start(self):
        fd, self.path = tempfile.mkstemp(prefix="ccs-dictee-", suffix=".wav")
        os.close(fd)
        cmd = recorder_command(self.path)
        if cmd is None:
            os.unlink(self.path)
            self.path = None
            raise RuntimeError("aucun outil d'enregistrement (pw-record, parecord ou arecord)")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def recording(self):
        return self._proc is not None and self._proc.poll() is None

    def stop(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return None
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)        # l'outil ferme proprement le WAV
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        path, self.path = self.path, None
        if path and os.path.exists(path) and os.path.getsize(path) > 1000:
            return path
        if path and os.path.exists(path):
            os.unlink(path)
        return None


_model = None
_model_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
        return _model


def transcribe(path):
    """Texte dicté dans le WAV `path` (Whisper, en français). Long la première fois : le modèle
    se charge (et se télécharge à la toute première dictée)."""
    segments, _info = _whisper().transcribe(path, language=LANG, vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()
