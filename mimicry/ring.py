"""Thread-safe float32 ring buffer for audio callbacks."""
from __future__ import annotations

import threading

import numpy as np


class Ring:
    def __init__(self, capacity: int):
        self.buf = np.zeros(capacity, np.float32)
        self.cap = capacity
        self.r = self.w = self.n = 0
        self.lock = threading.Lock()
        self.overflows = 0
        self.underruns = 0

    def write(self, x: np.ndarray) -> None:
        x = np.asarray(x, np.float32)
        with self.lock:
            if len(x) > self.cap:
                x = x[-self.cap:]
            drop = self.n + len(x) - self.cap
            if drop > 0:                                  # keep latency bounded: drop oldest
                self.r = (self.r + drop) % self.cap
                self.n -= drop
                self.overflows += 1
            idx = (self.w + np.arange(len(x))) % self.cap
            self.buf[idx] = x
            self.w = (self.w + len(x)) % self.cap
            self.n += len(x)

    def read(self, k: int) -> np.ndarray:
        with self.lock:
            m = min(k, self.n)
            idx = (self.r + np.arange(m)) % self.cap
            out = np.zeros(k, np.float32)
            out[:m] = self.buf[idx]
            self.r = (self.r + m) % self.cap
            self.n -= m
            if m < k:
                self.underruns += 1
            return out

    def __len__(self):
        return self.n
