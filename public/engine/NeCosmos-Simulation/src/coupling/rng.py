"""Portable counter-based RNG (no hidden sequence state).

u01(seed, stream, day, index) = lowbias32 hash chain / 2^32. Every draw is addressed by
(seed, stream, day, index) so results never depend on how many draws other code made or on
array order. All arithmetic is uint32 with wrap-around, i.e. identical in JavaScript with
Math.imul and >>> (see README "JS port").

  h = mix(seed); h = mix(h ^ stream); h = mix(h ^ day); h = mix(h ^ index)
  mix(x): x ^= x >>> 16; x = imul(x, 0x7feb352d); x ^= x >>> 15; x = imul(x, 0x846ca68b); x ^= x >>> 16
"""
import numpy as np

M = np.uint64(0xFFFFFFFF)

# stream ids (stable; never renumber)
WEATHER, INIT, MOVE, REPRO, SENESCENCE, SPAWN, TERRAIN, PLACE, WISDOM, BIRTHPOS = range(1, 11)


def _mix(x):
    x = x.astype(np.uint64) & M
    x ^= x >> np.uint64(16)
    x = (x * np.uint64(0x7FEB352D)) & M
    x ^= x >> np.uint64(15)
    x = (x * np.uint64(0x846CA68B)) & M
    x ^= x >> np.uint64(16)
    return x


def hash32(seed, stream, day, index):
    seed = np.atleast_1d(np.asarray(seed, dtype=np.uint64))
    h = _mix(seed & M)
    h = _mix(h ^ (np.asarray(stream, dtype=np.uint64) & M))
    h = _mix(h ^ (np.asarray(day, dtype=np.uint64) & M))
    h = _mix(h ^ (np.atleast_1d(np.asarray(index, dtype=np.uint64)) & M))
    return h


def u01(seed, stream, day, index):
    """Uniform [0, 1) draws; index may be an array (e.g. individual ids)."""
    return hash32(seed, stream, day, index).astype(np.float64) / 4294967296.0


def normal(seed, stream, day, index):
    """Standard normal via Box-Muller on two independent counter draws (index*2, index*2+1)."""
    idx = np.atleast_1d(np.asarray(index, dtype=np.uint64))
    a = np.maximum(u01(seed, stream, day, idx * np.uint64(2)), 1e-12)
    b = u01(seed, stream, day, idx * np.uint64(2) + np.uint64(1))
    return np.sqrt(-2 * np.log(a)) * np.cos(2 * np.pi * b)
