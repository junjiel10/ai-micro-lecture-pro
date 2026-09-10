# -*- coding: utf-8 -*-
"""背景音乐生成：用 numpy 合成一段柔和的氛围铺底（无版权、可商用、零素材依赖）。

思路：I–V–vi–IV 和弦进行 + 缓慢包络的正弦叠加 + 稀疏琶音，
生成后整体压到 -20 dBFS 左右，作为旁白底噪即可，不会抢人声。
"""
from __future__ import annotations

import wave

import numpy as np

SR = 44100

# 音名 → 频率（十二平均律，A4 = 440Hz）
_NOTE_BASE = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
              "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}


def note_freq(name: str, octave: int = 4) -> float:
    semi = _NOTE_BASE[name] + (octave - 4) * 12
    return 440.0 * (2 ** (semi / 12.0))


# 和弦进行（根音，音程）——温暖、明亮、适合教育类内容
PROGRESSIONS = {
    "calm": [("C", [0, 4, 7, 11]), ("G", [0, 4, 7, 11]),
             ("A", [0, 3, 7, 12]), ("F", [0, 4, 7, 11])],
    "bright": [("F", [0, 4, 7, 11]), ("C", [0, 4, 7, 11]),
               ("G", [0, 4, 7, 11]), ("A", [0, 3, 7, 12])],
    "warm": [("A", [0, 3, 7, 12]), ("F", [0, 4, 7, 11]),
             ("C", [0, 4, 7, 11]), ("G", [0, 4, 7, 11])],
}


def _pad_chord(root: str, intervals, octave: int, dur: float,
               rng: np.random.Generator) -> np.ndarray:
    """单个和弦的氛围铺底（含缓慢的进出包络）"""
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for i, semi in enumerate(intervals):
        f = note_freq(root, octave + (semi // 12)) * (2 ** ((semi % 12) / 12.0))
        # 每个音略微失谐，形成自然的合唱感
        detune = 1.0 + rng.uniform(-0.0015, 0.0015)
        amp = 1.0 / (i + 1.6)
        sig += amp * np.sin(2 * np.pi * f * detune * t)
        sig += amp * 0.22 * np.sin(2 * np.pi * f * 2 * detune * t)   # 泛音
    # 包络：慢进慢出，避免爆音
    attack, release = int(0.35 * SR), int(0.6 * SR)
    env = np.ones(n)
    env[:attack] = np.linspace(0, 1, attack)
    env[-release:] = np.linspace(1, 0, release)
    return sig * env


def _arpeggio(root: str, intervals, octave: int, dur: float,
              rng: np.random.Generator) -> np.ndarray:
    """稀疏琶音，增加一点灵动感"""
    n = int(SR * dur)
    sig = np.zeros(n)
    hits = int(rng.integers(2, 4))
    for _ in range(hits):
        i = int(rng.integers(0, len(intervals)))
        oct_shift = int(rng.integers(0, 2))
        semi = intervals[i] + 12 * oct_shift
        f = note_freq(root, octave + (semi // 12)) * (2 ** ((semi % 12) / 12.0))
        start = int(rng.uniform(0, max(0.05, dur - 1.2)) * SR)
        length = int(1.2 * SR)
        t = np.arange(length) / SR
        env = np.exp(-t * 3.2)
        tone = np.sin(2 * np.pi * f * t) * env * 0.16
        end = min(n, start + length)
        sig[start:end] += tone[: end - start]
    return sig


def build_bgm(duration: float, out_path: str, style: str = "calm",
              seed: int | None = None) -> str:
    """生成 duration 秒的立体声 WAV 背景音乐"""
    duration = max(4.0, float(duration))
    rng = np.random.default_rng(seed if seed is not None else 20260910)
    prog = PROGRESSIONS.get(style, PROGRESSIONS["calm"])
    chord_dur = 4.0

    buf = np.zeros(int(SR * (duration + chord_dur)))
    pos = 0.0
    k = 0
    while pos < duration:
        root, intervals = prog[k % len(prog)]
        octave = 3 if k % 2 == 0 else 4
        chord = _pad_chord(root, intervals, octave, chord_dur, rng)
        if k % 2 == 1:
            chord = chord + _arpeggio(root, intervals, 5, chord_dur, rng)
        start = int(pos * SR)
        end = min(len(buf), start + len(chord))
        buf[start:end] += chord[: end - start]
        pos += chord_dur * 0.9          # 轻微交叉，衔接更自然
        k += 1

    buf = buf[: int(SR * duration)]

    # 整体淡入淡出
    fade = int(1.5 * SR)
    buf[:fade] *= np.linspace(0, 1, fade)
    buf[-fade:] *= np.linspace(1, 0, fade)

    # 归一化到 -20 dBFS
    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf / peak * (10 ** (-20 / 20))

    # 轻微立体声展宽 + 转 16bit PCM
    #
    # 内存提醒（改这段前务必先读）：
    #   106 秒立体声的 float64 数组本身是 75MB，如果写成
    #       stereo = np.stack([left, right], axis=1)
    #       pcm = np.clip(stereo * 32767, -32768, 32767).astype("<i2")
    #   会同时存在 stereo、stereo*32767、clip 结果三个 75MB 大数组，
    #   实测峰值冲到 244MB —— 在 512MB 的小实例上这就是「能不能出片」的分界线。
    #   所以这里分块处理，中间结果直接写进 int16 目标数组，峰值压到 65MB 以内。
    delay = int(0.012 * SR)
    gain = (10 ** (-20 / 20)) / peak * 32767
    n = len(buf)
    pcm = np.zeros((n, 2), dtype="<i2")
    step = SR * 10                       # 每次处理 10 秒
    for s in range(0, n, step):
        e = min(n, s + step)
        seg = buf[s:e] * gain            # 左声道
        np.clip(seg, -32768, 32767, out=seg)
        pcm[s:e, 0] = seg
        rs = max(s, delay)               # 右声道整体延后 delay 个采样（展宽）
        if e > rs:
            seg_r = buf[rs - delay:e - delay] * (gain * 0.92)
            np.clip(seg_r, -32768, 32767, out=seg_r)
            pcm[rs:e, 1] = seg_r

    with wave.open(out_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out_path
