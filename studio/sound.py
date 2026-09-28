"""
Звуковые инструменты для сцен.  В сцене:

    def sound(a, dur):
        a.braam(0, 0.8)          # тяжёлый удар в начале сцены
        a.piano(1.2, 'D4')       # нота фортепиано через 1.2 секунды

Время — в секундах от начала сцены. g — громкость (примерно 0..1.5).
Ноты: 'C4', 'D#3', 'Bb2' или номер MIDI (60 = C4) или частота в Гц (> 127).
"""
import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
TAIL = 6.0     # звук сцены может звучать ещё 6 секунд после её конца (хвосты, реверберация)

_NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_SOS = {}


def hz(n):
    """Нота -> частота. 'A4' = 440, 69 = 440."""
    if isinstance(n, str):
        s = n.strip()
        base = _NOTE[s[0].upper()]
        i = 1
        while i < len(s) and s[i] in '#b':
            base += 1 if s[i] == '#' else -1
            i += 1
        octave = int(s[i:]) if i < len(s) else 4
        n = base + (octave + 1) * 12
    n = float(n)
    if n > 127:
        return n
    return 440.0 * 2 ** ((n - 69) / 12)


def _sos(kind, f, o=2):
    k = (kind, tuple(f) if isinstance(f, (list, tuple)) else f, o)
    if k not in _SOS:
        _SOS[k] = butter(o, f, kind, fs=SR, output='sos')
    return _SOS[k]


def lp(x, f, o=2): return sosfilt(_sos('low', f, o), x)
def hp(x, f, o=2): return sosfilt(_sos('high', f, o), x)
def bp(x, a, b, o=2): return sosfilt(_sos('band', [a, b], o), x)
def saw(f, t): return 2 * ((f * t) % 1) - 1
def tt(d): return np.arange(int(d * SR)) / SR


class SceneAudio:
    def __init__(self, dur, seed=0):
        self.dur = dur
        self.n = int((dur + TAIL) * SR)
        self.L = np.zeros(self.n)
        self.R = np.zeros(self.n)
        self.WET = np.zeros(self.n)
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------ core
    def add(self, s, t0, g=1.0, pan=0.0, wet=0.0):
        """Добавить свой сигнал s (numpy-массив, 44100 Гц) в момент t0."""
        i = int(t0 * SR)
        if i >= self.n or i < -len(s):
            return
        if i < 0:
            s = s[-i:]; i = 0
        j = min(self.n, i + len(s))
        s = np.asarray(s[:j - i]) * g
        self.L[i:j] += s * (1 - max(0, pan))
        self.R[i:j] += s * (1 + min(0, pan))
        self.WET[i:j] += s * wet

    def noise(self, d):
        return self.rng.standard_normal(int(d * SR))

    # ------------------------------------------------------------ instruments
    def heart(self, t0, g=1.0):
        """Удар сердца (двойной)."""
        for k, dt in enumerate([0, 0.19]):
            t = tt(0.5)
            f = 62 - 20 * t
            s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.11) * (1 if k == 0 else .7)
            self.add(s, t0 + dt, g * 0.9)

    def braam(self, t0, g=1.0, root=36.71):
        """Трейлерный «БРААМ» — тяжёлый медный удар с сабом."""
        t = tt(3.2)
        s = np.zeros_like(t)
        for m in [1, 1.5, 2, 3]:
            for dt in [-0.4, 0.35]:
                s += saw(root * m * (1 + dt / 100), t) / m
        env = np.minimum(1, t / 0.03) * np.exp(-t / 1.1)
        s = lp(s, 700, 4) * env * 0.35
        sub = np.sin(2 * np.pi * np.cumsum(root * (1.6 - 0.6 * np.minimum(1, t / 0.25))) / SR) * np.exp(-t / 0.9) * 0.8
        nz = lp(self.rng.standard_normal(len(t)), 2500) * np.exp(-t / 0.12) * 0.35
        self.add(s + sub + nz, t0, g, wet=0.5 * g)

    def taiko(self, t0, g=1.0, pan=0.0):
        """Большой барабан."""
        t = tt(0.9)
        f = 95 - 40 * np.minimum(1, t / 0.12)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.28)
        s += bp(self.rng.standard_normal(len(t)), 120, 900) * np.exp(-t / 0.04) * 0.5
        self.add(s, t0, g * 0.8, pan, wet=0.25 * g)

    def tick(self, t0, g=0.3):
        """Тиканье / щелчок."""
        t = tt(0.05)
        s = hp(self.rng.standard_normal(len(t)), 3000) * np.exp(-t / 0.006) + np.sin(2 * np.pi * 1800 * t) * np.exp(-t / 0.01) * 0.5
        self.add(s, t0, g, wet=0.05)

    def piano(self, t0, note, g=0.3, d=4.0):
        """Нота фортепиано."""
        f = hz(note)
        t = tt(d)
        s = np.zeros_like(t)
        for k in range(1, 8):
            s += np.sin(2 * np.pi * f * k * (1 + 0.0004 * k * k) * t) * (1 / k ** 1.3) * np.exp(-t * (0.6 + 0.55 * k))
        s *= np.minimum(1, t / 0.004)
        self.add(s, t0, g, pan=float(np.clip((f - 400) / 800, -0.4, 0.4)), wet=0.9 * g)

    def pad(self, t0, notes, d, g=0.1, att=1.2, rel=1.5):
        """Тянущийся аккорд. notes — список нот, d — длительность."""
        t = tt(d + rel)
        s = np.zeros_like(t)
        for n in notes:
            f = hz(n)
            for dt in [-0.25, 0, 0.3]:
                s += saw(f * (1 + dt / 100), t + self.rng.random())
        s = lp(s, 1100, 3)
        env = np.minimum(1, t / att) * np.clip((d + rel - t) / rel, 0, 1)
        self.add(s * env, t0, g, wet=0.6 * g)

    def riser(self, t0, d, g=0.5):
        """Нарастающий шум — подводка к удару. Заканчивается в t0 + d."""
        t = tt(d)
        s = hp(self.rng.standard_normal(len(t)), 1200) * (t / d) ** 2.5
        s += np.sin(2 * np.pi * np.cumsum(80 + 320 * (t / d) ** 2) / SR) * (t / d) ** 2 * 0.3
        self.add(s, t0, g, wet=0.3)

    def bass(self, t0, note, g=0.22, d=0.22):
        """Короткая бас-нота."""
        t = tt(d)
        s = lp(saw(hz(note), t), 400) * np.exp(-t / 0.08)
        self.add(s, t0, g)

    def whoosh(self, t0, d=0.6, g=0.5):
        """Свист-пролёт."""
        t = tt(d)
        env = np.sin(np.pi * t / d) ** 2
        s = bp(self.rng.standard_normal(len(t)), 400, 3000) * env
        self.add(s, t0, g, wet=0.3)

    # ------------------------------------------------------------ patterns
    def war_drums(self, t0, t1, step=0.225, g=1.0):
        """Боевой ритм барабанов от t0 до t1."""
        i = 0
        x = t0
        while x < t1 - 1e-6:
            if i % 4 == 0: self.taiko(x, 1.0 * g)
            elif i % 4 == 2: self.taiko(x, 0.6 * g, pan=0.3)
            elif i % 8 in (3, 7): self.taiko(x, 0.35 * g, pan=-0.3)
            i += 1
            x += step
        return self

    def pulse(self, t0, t1, g=0.22, notes=(26, 25), step=0.25):
        """Тревожный бас-пульс: по 8 ударов на каждую ноту из notes."""
        i = 0
        x = t0
        while x < t1 - 1e-6:
            self.bass(x, notes[(i // 8) % len(notes)], g)
            i += 1
            x += step

    def ticks(self, t0, t1, start=0.45, accel=0.03, g=0.25):
        """Ускоряющееся тиканье часов."""
        k = 0
        x = t0
        while x < t1:
            self.tick(x, g)
            x += max(0.1, start - k * accel)
            k += 1

    def melody(self, t0, notes, step=0.5, g=0.2):
        """Последовательность нот фортепиано с шагом step."""
        for i, n in enumerate(notes):
            self.piano(t0 + i * step, n, g)
