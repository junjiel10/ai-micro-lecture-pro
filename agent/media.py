# -*- coding: utf-8 -*-
"""媒体基础层：ffmpeg 定位、音频时长、TTS 多引擎降级、静音生成。

这一层是「让流程在真实机器上一定跑得通」的保险丝：
  ffmpeg  : imageio-ffmpeg（pip 自带二进制）→ 系统 PATH → 报错提示
  TTS     : edge-tts（联网、音质好）→ Windows SAPI（离线）→ 静音（保底出片）
  时长    : mutagen（纯 Python）→ ffprobe → 按字数估算
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

from . import config

# ----------------------------------------------------------------------
# ffmpeg
# ----------------------------------------------------------------------
_FFMPEG: str | None = None
_FFMPEG_CHECKED = False
_FILTERS: set | None = None


def ffmpeg_exe() -> str | None:
    """返回可用的 ffmpeg 可执行文件路径（结果缓存）"""
    global _FFMPEG, _FFMPEG_CHECKED
    if _FFMPEG_CHECKED:
        return _FFMPEG
    _FFMPEG_CHECKED = True

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            _FFMPEG = exe
            return _FFMPEG
    except Exception:
        pass

    exe = shutil.which("ffmpeg")
    if exe:
        _FFMPEG = exe
    return _FFMPEG


def ffmpeg_version() -> str:
    exe = ffmpeg_exe()
    if not exe:
        return "未找到"
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20).stdout
        return out.splitlines()[0].replace("ffmpeg version ", "").split(" Copyright")[0].strip()
    except Exception as e:
        return f"检测失败：{e}"


def available_filters() -> set:
    """列出 ffmpeg 支持的滤镜名（用于判断能否烧录字幕）"""
    global _FILTERS
    if _FILTERS is not None:
        return _FILTERS
    _FILTERS = set()
    exe = ffmpeg_exe()
    if not exe:
        return _FILTERS
    try:
        out = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30).stdout
        for line in out.splitlines():
            parts = line.split()
            # 形如： " TSC subtitles        V->V       Render text subtitles..."
            if len(parts) >= 3 and parts[0] and not parts[0].startswith("-"):
                _FILTERS.add(parts[1])
    except Exception:
        pass
    return _FILTERS


def has_filter(name: str) -> bool:
    return name in available_filters()


def ff(*args: str, timeout: int = 600,
       cwd: str | None = None) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令（静默、抛出可读错误）

    cwd：工作目录。烧录字幕时用它把路径变成相对路径，
         既避开 Windows 盘符冒号的转义坑，也避开中文路径问题。
    """
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError(
            "未找到 ffmpeg。请在项目目录执行：pip install imageio-ffmpeg")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("ffmpeg 执行失败：" + " | ".join(tail) if tail else "ffmpeg 执行失败")
    return proc


# ----------------------------------------------------------------------
# 音频时长
# ----------------------------------------------------------------------
def probe_duration(path: str) -> float:
    """获取音频/视频时长（秒）。优先 mutagen，其次 ffprobe，最后按体积估算。"""
    if not os.path.exists(path):
        return 0.0
    try:
        from mutagen import File as MutaFile
        m = MutaFile(path)
        if m is not None and m.info is not None and getattr(m.info, "length", 0):
            return float(m.info.length)
    except Exception:
        pass

    exe = ffmpeg_exe()
    if exe:
        probe = os.path.join(os.path.dirname(exe), "ffprobe.exe")
        for cand in (probe, shutil.which("ffprobe") or ""):
            if cand and os.path.exists(cand):
                try:
                    out = subprocess.run(
                        [cand, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", path],
                        capture_output=True, text=True, timeout=30).stdout
                    return float(out.strip())
                except Exception:
                    break
    # 兜底：按文件体积粗估（128kbps）
    try:
        return max(0.5, os.path.getsize(path) / 16000.0)
    except Exception:
        return 0.0


def estimate_duration(text: str, rate: str = "+0%") -> float:
    """按中文字数估算朗读时长（中文约 4.4 字/秒，含标点停顿）"""
    chars = len(re.sub(r"\s", "", text or ""))
    speed = 4.4
    m = re.match(r"([+-])(\d+)%", rate or "")
    if m:
        pct = int(m.group(2))
        speed = speed * (1 + pct / 100) if m.group(1) == "+" else speed * (1 - pct / 100)
    pauses = len(re.findall(r"[，。！？；、,.!?;]", text or "")) * 0.18
    return round(chars / max(speed, 1.0) + pauses + 0.35, 2)


def make_silence(path: str, duration: float, sample_rate: int = 24000) -> str:
    """生成静音 WAV（纯 Python，不依赖 ffmpeg）"""
    duration = max(0.2, float(duration))
    frames = int(sample_rate * duration)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * frames)
    return path


def wav_to_mp3(wav_path: str, mp3_path: str) -> str:
    ff("-i", wav_path, "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "24000", mp3_path)
    return mp3_path


# ----------------------------------------------------------------------
# TTS 引擎 1：edge-tts（联网，音质最佳）
# ----------------------------------------------------------------------
def tts_edge(text: str, out_path: str, voice: str | None = None,
              rate: str | None = None, timeout: int = 90) -> str:
    import asyncio

    import edge_tts

    voice = voice or config.TTS_VOICE
    rate = rate or config.TTS_RATE

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await asyncio.wait_for(communicate.save(out_path), timeout=timeout)

    last_err = None
    for attempt in range(3):
        try:
            asyncio.run(_run())
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                return out_path
            raise RuntimeError("音频文件为空")
        except Exception as e:      # 网络抖动 / 限流
            last_err = e
            import time
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"edge-tts 合成失败：{last_err}")


# ----------------------------------------------------------------------
# TTS 引擎 2：Windows SAPI（离线中文语音，无需联网）
# ----------------------------------------------------------------------
_SAPI_PS = r"""
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($args[0], [System.Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $synth.GetInstalledVoices() | Where-Object {
    $_.VoiceInfo.Culture.Name -like 'zh*' -or $_.VoiceInfo.Name -match 'Huihui|Yaoyao|Kangkang|Xiaoxiao|Chinese'
} | Select-Object -First 1
if (-not $voice) { throw 'NO_CHINESE_VOICE' }
$synth.SelectVoice($voice.VoiceInfo.Name)
$synth.Rate = [int]$args[2]
$synth.SetOutputToWaveFile($args[1])
$synth.Speak($text)
$synth.Dispose()
"""


def tts_sapi(text: str, out_path: str, rate_percent: int = 1) -> str:
    """调用 Windows 内置语音合成（System.Speech），完全离线"""
    if sys.platform != "win32":
        raise RuntimeError("SAPI 仅在 Windows 可用")
    tmpdir = tempfile.mkdtemp(prefix="sapi_")
    ps1 = os.path.join(tmpdir, "tts.ps1")
    txt = os.path.join(tmpdir, "text.txt")
    try:
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(_SAPI_PS)
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", ps1, txt, out_path, str(rate_percent)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            raise RuntimeError((proc.stderr or "SAPI 合成失败").strip()[:200])
        return out_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------
# 统一入口：按 edge → sapi → silent 依次降级
# ----------------------------------------------------------------------
def synthesize(text: str, out_path: str, voice: str | None = None,
               rate: str | None = None, prefer: str = "edge") -> dict:
    """合成一段旁白，返回 {path, engine, duration, error}"""
    text = (text or "").strip()
    if not text:
        text = "（本段暂无旁白）"

    order = list(config.TTS_ENGINES)
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)

    errors = []
    for engine in order:
        try:
            if engine == "edge":
                tts_edge(text, out_path, voice=voice, rate=rate)
            elif engine == "sapi":
                wav = os.path.splitext(out_path)[0] + ".sapi.wav"
                tts_sapi(text, wav)
                if os.path.splitext(out_path)[1].lower() == ".mp3":
                    wav_to_mp3(wav, out_path)
                    os.remove(wav)
                else:
                    shutil.move(wav, out_path)
            else:  # silent（保底）
                dur = estimate_duration(text, rate or config.TTS_RATE)
                make_silence(out_path, dur)
            dur = probe_duration(out_path)
            if dur <= 0.2:
                dur = estimate_duration(text, rate or config.TTS_RATE)
            return {"path": out_path, "engine": engine, "duration": dur,
                    "error": "; ".join(errors) if errors else ""}
        except Exception as e:
            errors.append(f"{engine}: {str(e)[:120]}")
            continue

    # 理论上不会到这里（silent 不会失败），保险起见
    make_silence(out_path, estimate_duration(text, rate or config.TTS_RATE))
    return {"path": out_path, "engine": "silent",
            "duration": probe_duration(out_path), "error": "; ".join(errors)}
