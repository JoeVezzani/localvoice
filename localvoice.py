#!/usr/bin/env python3
"""
LocalVoice - Talk to your computer. It types what you say.

100% local. No cloud APIs. No data leaves your machine. Ever.

Architecture: whisper-server runs persistently with model loaded in GPU memory.
Transcription happens via HTTP POST - no cold-start, ~0.4s per clip.

Two modes:
  1. Quick:  Hold Right Option -> speak -> release to stop & transcribe
  2. Locked: Tap Right Option -> press Space to lock open -> tap again to stop

Usage:
    python3 localvoice.py [--key alt_r] [--model small]
"""

import argparse
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
import requests
import sounddevice as sd
from pynput import keyboard

import objc
from AppKit import (
    NSApplication, NSObject, NSWindow, NSView, NSColor, NSBezierPath,
    NSBackingStoreBuffered, NSWindowStyleMaskBorderless,
    NSFloatingWindowLevel, NSScreen, NSTimer, NSRunLoop,
    NSRunLoopCommonModes, NSFont, NSString, NSMakeRect, NSMakePoint,
    NSEvent, NSApplicationActivationPolicyAccessory,
)
from Quartz import CGDisplayBounds, CGMainDisplayID

# --- Config ---
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
PILL_WIDTH = 300
PILL_HEIGHT = 60
PILL_MARGIN_BOTTOM = 100
SERVER_PORT = 8178
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/inference"

# --- State ---
recording = False
locked = False
audio_frames = []
stream = None
state_lock = threading.Lock()
last_transcription_time = 0
COOLDOWN = 0.5
MIN_DURATION = 0.3
server_process = None

# Audio level for visualizer (updated by audio callback)
audio_level_lock = threading.Lock()
level_history = [0.0] * 40  # rolling waveform bars
frame_count = 0  # for animations

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MODELS = {
    "base": os.path.join(SCRIPT_DIR, "models", "ggml-base.en.bin"),
    "small": os.path.join(SCRIPT_DIR, "models", "ggml-small.en.bin"),
    "medium": os.path.join(SCRIPT_DIR, "models", "ggml-medium.en-q5_0.bin"),
    "large": os.path.join(SCRIPT_DIR, "models", "ggml-large-v3-turbo-q5_0.bin"),
}


def _pick_default_model():
    """Pick the best available model."""
    for name in ["small", "medium", "base"]:
        if os.path.exists(MODELS[name]):
            return name
    return "base"


def _find_server():
    metal = os.path.join(SCRIPT_DIR, "whisper-server-metal")
    if os.path.exists(metal):
        return metal
    for path in [
        "/opt/homebrew/bin/whisper-server",
        "/usr/local/bin/whisper-server",
    ]:
        if os.path.exists(path):
            return path
    return None


def start_whisper_server(model_path):
    """Start whisper-server with model loaded in GPU memory."""
    global server_process

    server_bin = _find_server()
    if not server_bin:
        print("ERROR: whisper-server-metal not found. Run ./setup.sh", file=sys.stderr)
        sys.exit(1)

    # Check if server already running
    try:
        r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/", timeout=1)
        if r.status_code == 200:
            print("  Whisper server already running", file=sys.stderr)
            return
    except requests.ConnectionError:
        pass

    print("  Starting whisper server (Metal + Flash Attention)...", file=sys.stderr)
    server_process = subprocess.Popen(
        [server_bin, "-m", model_path, "-t", "8", "--port", str(SERVER_PORT), "-fa"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready
    for i in range(30):
        time.sleep(0.5)
        try:
            r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/", timeout=1)
            if r.status_code == 200:
                print(f"  Server ready (took {(i+1)*0.5:.1f}s)", file=sys.stderr)
                return
        except requests.ConnectionError:
            pass

    print("ERROR: Whisper server failed to start", file=sys.stderr)
    sys.exit(1)


def stop_whisper_server():
    global server_process
    if server_process:
        server_process.terminate()
        server_process.wait()
        server_process = None


def play_sound(sound_name="Tink"):
    # Fire-and-forget with start_new_session to avoid zombie processes
    subprocess.Popen(
        ["afplay", f"/System/Library/Sounds/{sound_name}.aiff"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# =============================================================================
# Floating Overlay
# =============================================================================

class WaveformView(NSView):
    """Custom NSView that draws a waveform visualizer with 60fps animations."""

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self.window().performWindowDragWithEvent_(event)

    def drawRect_(self, rect):
        global frame_count
        frame_count = (frame_count + 1) % 100000  # prevent unbounded growth

        with state_lock:
            is_locked = locked
            is_recording = recording

        # Background pill
        if is_recording:
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.04, 0.12, 0.94).set()
        else:
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.06, 0.04, 0.94).set()

        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), PILL_HEIGHT / 2, PILL_HEIGHT / 2
        )
        pill.fill()

        # Subtle border glow
        if is_recording:
            pulse = 0.3 + 0.15 * math.sin(frame_count * 0.08)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.2, 1.0, pulse).set()
        else:
            pulse = 0.3 + 0.2 * math.sin(frame_count * 0.15)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.6, 0.2, pulse).set()
        pill.setLineWidth_(1.5)
        pill.stroke()

        # Draw waveform bars
        bar_count = len(level_history)
        bar_width = 3
        bar_gap = 2
        total_bars_width = bar_count * (bar_width + bar_gap) - bar_gap
        start_x = (PILL_WIDTH - total_bars_width) / 2
        center_y = PILL_HEIGHT / 2

        with audio_level_lock:
            levels = list(level_history)

        for i, level in enumerate(levels):
            x = start_x + i * (bar_width + bar_gap)

            if is_recording:
                idle_wave = 0.03 * math.sin(frame_count * 0.06 + i * 0.3)
                effective_level = max(level, abs(idle_wave))
                bar_height = max(2, effective_level * (PILL_HEIGHT - 20))

                # Purple to cyan gradient based on position and level
                t = i / max(bar_count - 1, 1)
                r = 0.45 * (1 - t) + 0.1 * t
                g = 0.15 * (1 - t) + 0.85 * t
                b = 1.0 * (1 - t) + 0.95 * t
                alpha = 0.5 + 0.5 * min(level * 3, 1.0)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha).set()
            else:
                # Transcribing: warm amber wave animation
                wave_offset = math.sin(frame_count * 0.12 + i * 0.2) * 0.5 + 0.5
                bar_height = max(2, wave_offset * 12)
                alpha = 0.4 + 0.4 * wave_offset
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.65, 0.2, alpha).set()

            bar_rect = NSMakeRect(x, center_y - bar_height / 2, bar_width, bar_height)
            bar_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bar_rect, bar_width / 2, bar_width / 2
            )
            bar_path.fill()

        # Status text
        if is_recording:
            label = "LOCKED" if is_locked else "LISTENING"
            text_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.4, 1.0, 0.8)
        else:
            label = "TRANSCRIBING"
            text_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.7, 0.3, 0.8)

        attrs = {
            "NSFont": NSFont.systemFontOfSize_weight_(9, 0.4),
            "NSColor": text_color,
        }
        ns_str = NSString.stringWithString_(label)
        str_size = ns_str.sizeWithAttributes_(attrs)
        ns_str.drawAtPoint_withAttributes_(
            ((PILL_WIDTH - str_size.width) / 2, 4), attrs
        )


class OverlayController(NSObject):
    """Manages the floating overlay window. Draggable."""

    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self._window = None
        self._view = None
        self._timer = None
        self._setup_window()
        return self

    def _setup_window(self):
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        x = 20  # Bottom-left corner
        y = PILL_MARGIN_BOTTOM

        rect = NSMakeRect(x, y, PILL_WIDTH, PILL_HEIGHT)
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(False)
        self._window.setHasShadow_(True)
        self._window.setCollectionBehavior_(1 << 4)  # can join all spaces

        self._view = WaveformView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PILL_WIDTH, PILL_HEIGHT)
        )
        self._window.setContentView_(self._view)

    def show(self):
        self._window.orderFront_(None)
        self._window.setAlphaValue_(1.0)
        if not self._timer:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 60.0, self, b"tick:", None, True
            )
            NSRunLoop.currentRunLoop().addTimer_forMode_(self._timer, NSRunLoopCommonModes)

    def hide(self):
        if self._timer:
            self._timer.invalidate()
            self._timer = None
        self._window.orderOut_(None)

    @objc.typedSelector(b"v@:@")
    def tick_(self, timer):
        self._view.setNeedsDisplay_(True)


overlay = None


# =============================================================================
# Recording
# =============================================================================

def start_recording():
    global recording, locked, audio_frames, stream

    with state_lock:
        if recording:
            return False
        if time.time() - last_transcription_time < COOLDOWN:
            return False
        recording = True
        locked = False
        audio_frames = []

    with audio_level_lock:
        for i in range(len(level_history)):
            level_history[i] = 0.0

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  [audio status: {status}]", file=sys.stderr)
        audio_frames.append(indata.copy())
        rms = np.sqrt(np.mean(indata.astype(np.float32) ** 2))
        level = min(rms / 2200.0, 1.0)
        with audio_level_lock:
            level_history.pop(0)
            level_history.append(level)

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        callback=callback,
        blocksize=512,
    )
    stream.start()
    play_sound("Tink")
    print("  [recording...]", file=sys.stderr)

    from PyObjCTools.AppHelper import callAfter
    callAfter(overlay.show)
    return True


def lock_recording():
    global locked
    with state_lock:
        if not recording or locked:
            return
        locked = True
    play_sound("Tink")
    print("  [locked open]", file=sys.stderr)


def stop_recording_and_transcribe():
    global recording, locked, stream, last_transcription_time, audio_frames

    with state_lock:
        if not recording:
            return
        recording = False
        locked = False

    if stream:
        stream.stop()
        stream.close()
        stream = None

    # Grab frames and immediately clear the global list to free memory
    frames = audio_frames
    audio_frames = []

    if not frames:
        print("  [no audio captured]", file=sys.stderr)
        from PyObjCTools.AppHelper import callAfter
        callAfter(overlay.hide)
        return

    audio_data = np.concatenate(frames, axis=0)
    del frames  # free the individual frame references
    duration = len(audio_data) / SAMPLE_RATE

    if duration < MIN_DURATION:
        print(f"  [too short: {duration:.1f}s, skipping]", file=sys.stderr)
        from PyObjCTools.AppHelper import callAfter
        callAfter(overlay.hide)
        return

    # Auto-gain: if peak level is low, boost so whisper can detect speech
    peak = np.max(np.abs(audio_data))
    if 0 < peak < 8000:  # int16 range is 32767; 8000 ~ 24% = very quiet
        gain = min(8000 / peak, 6.0)  # cap at 6x to avoid noise blowup
        audio_data = np.clip(audio_data.astype(np.float32) * gain, -32767, 32767).astype(np.int16)
        print(f"  [auto-gain: {gain:.1f}x, peak was {peak:.0f}]", file=sys.stderr)

    print(f"  [captured {duration:.1f}s, peak={peak}, transcribing...]", file=sys.stderr)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())
        del audio_data  # free the concatenated audio

        wav_size = os.path.getsize(tmp.name)
        print(f"  [wav: {wav_size} bytes]", file=sys.stderr)

        start = time.time()
        with open(tmp.name, "rb") as audio_file:
            r = requests.post(
                SERVER_URL,
                files={"file": ("audio.wav", audio_file, "audio/wav")},
                data={"response_format": "json", "language": "en"},
                timeout=15,
            )
        elapsed = time.time() - start

        from PyObjCTools.AppHelper import callAfter
        callAfter(overlay.hide)

        if r.status_code != 200:
            print(f"  [server error: {r.status_code}]", file=sys.stderr)
            play_sound("Basso")
            return

        result = r.json()
        raw_text = result.get("text", "")
        print(f"  [whisper raw: {repr(raw_text[:200])}]", file=sys.stderr)
        text = raw_text.strip()
        text = text.replace("[BLANK_AUDIO]", "").strip()
        text = " ".join(text.split())

        if not text:
            print("  [empty transcription]", file=sys.stderr)
            return

        preview = f'"{text[:80]}..."' if len(text) > 80 else f'"{text}"'
        print(f"  [{elapsed:.2f}s: {preview}]", file=sys.stderr)

        paste_text(text)
        play_sound("Pop")
        last_transcription_time = time.time()

    except requests.Timeout:
        print("  [transcription timed out]", file=sys.stderr)
        play_sound("Basso")
        from PyObjCTools.AppHelper import callAfter
        callAfter(overlay.hide)
    except Exception as e:
        print(f"  [transcription error: {e}]", file=sys.stderr)
        play_sound("Basso")
        from PyObjCTools.AppHelper import callAfter
        callAfter(overlay.hide)
    finally:
        os.unlink(tmp.name)


def paste_text(text):
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))
    time.sleep(0.01)

    helper = os.path.join(SCRIPT_DIR, "paste_helper")
    if not os.path.exists(helper):
        print("  [paste_helper not found - text on clipboard, paste with Cmd+V]", file=sys.stderr)
        return
    try:
        result = subprocess.run([helper], capture_output=True, timeout=5)
        if result.returncode != 0:
            stderr = result.stderr.decode().strip()
            print(f"  [paste_helper failed: {stderr}]", file=sys.stderr)
            print("  [text is on clipboard - paste with Cmd+V]", file=sys.stderr)
    except Exception as e:
        print(f"  [paste_helper error: {e}]", file=sys.stderr)


# =============================================================================
# Main
# =============================================================================

def main():
    global overlay

    parser = argparse.ArgumentParser(description="LocalVoice - talk, it types.")
    parser.add_argument("--key", default="alt_r",
                        help="Hotkey (default: alt_r / Right Option)")
    parser.add_argument("--model", default=None, choices=MODELS.keys(),
                        help="Model: base, small (default, fast), medium (best accuracy), large")
    args = parser.parse_args()

    model_name = args.model or _pick_default_model()

    key_map = {
        "alt_r": keyboard.Key.alt_r,
        "alt_l": keyboard.Key.alt_l,
        "ctrl_r": keyboard.Key.ctrl_r,
        "f5": keyboard.Key.f5,
        "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7,
        "f8": keyboard.Key.f8,
    }
    hotkey = key_map.get(args.key.lower())
    if not hotkey:
        print(f"Unknown key: {args.key}. Options: {', '.join(key_map.keys())}")
        sys.exit(1)

    model_path = MODELS[model_name]
    if not os.path.exists(model_path):
        print(f"ERROR: Model not found: {model_path}")
        print("Run ./setup.sh to download models")
        sys.exit(1)

    # Start persistent whisper server
    start_whisper_server(model_path)

    # Set up macOS app (needed for overlay window)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    overlay = OverlayController.alloc().init()

    print(f"\n  LocalVoice is ready. 100% local - Metal GPU accelerated.\n")
    print(f"  Model: {model_name} (server mode, model stays in GPU memory)")
    print(f"  Hotkey: {args.key}\n")
    print(f"  Hold {args.key} and talk, release to transcribe.")
    print(f"  Or tap to start, press Space to lock, tap again to stop.")
    print(f"  The pill is draggable - move it wherever you want.")
    print(f"  Ctrl+C to quit.\n")

    recording_started_at = [0]

    def on_press(key):
        if key == hotkey:
            with state_lock:
                is_recording = recording
            if is_recording:
                threading.Thread(
                    target=stop_recording_and_transcribe,
                    daemon=True
                ).start()
            else:
                if start_recording():
                    recording_started_at[0] = time.time()
        elif key == keyboard.Key.space:
            with state_lock:
                is_recording = recording
            if is_recording:
                lock_recording()

    def on_release(key):
        if key == hotkey:
            with state_lock:
                is_recording = recording
                is_locked = locked
            if is_recording and not is_locked and (time.time() - recording_started_at[0]) > 0.3:
                threading.Thread(
                    target=stop_recording_and_transcribe,
                    daemon=True
                ).start()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    try:
        from PyObjCTools import AppHelper
        AppHelper.runConsoleEventLoop()
    except KeyboardInterrupt:
        print("\nStopping server...")
        stop_whisper_server()
        listener.stop()
        print("Done.")


if __name__ == "__main__":
    main()
