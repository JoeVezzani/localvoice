# LocalVoice

Talk to your computer. It types what you say.

**100% local. Zero cloud. Zero API keys. Your voice never leaves your machine.**

Uses [whisper.cpp](https://github.com/ggml-org/whisper.cpp) running on your Mac's GPU (Metal) for fast, accurate speech-to-text. Tap a key, talk, and the text appears wherever your cursor is.

<img width="280" alt="recording" src="https://img.shields.io/badge/RECORDING-teal?style=for-the-badge">

## Speed

On Apple Silicon with Metal GPU:

| Model | Transcription Time | Accuracy |
|-------|-------------------|----------|
| base.en | ~0.7s | Good |
| small.en-q5_0 | ~0.8s | Better |
| **medium.en-q5_0** | **~1.5s** | **Best** |

Setup auto-downloads the medium quantized model if Metal is available. Without Metal (CPU only), expect ~8-9s.

## Setup

```bash
git clone https://github.com/user/localvoice.git
cd localvoice
chmod +x setup.sh start.sh
./setup.sh
```

Setup does everything:
1. Creates Python venv and installs dependencies
2. Compiles the paste helper (Swift)
3. Downloads the whisper model from HuggingFace
4. Builds whisper-cpp from source with Metal GPU acceleration

### Permissions (one-time)

Open **System Settings > Privacy & Security** and add:

| Setting | What to add |
|---------|-------------|
| **Accessibility** | `paste_helper` (from this folder) |
| **Input Monitoring** | Terminal.app (or iTerm2, etc.) |
| **Microphone** | Terminal.app (or iTerm2, etc.) |

For Accessibility: click +, press Cmd+Shift+G, paste the full path to `paste_helper` in this folder.

## Usage

```bash
./start.sh
```

Run in a dedicated Terminal tab (keep it open).

### Controls

| Action | What happens |
|--------|-------------|
| **Hold Right Option** | Start recording. Release to transcribe. |
| **Tap Right Option** | Start recording (stays on). |
| **Press Space** while recording | Lock mode (keeps recording until you tap the hotkey again). |
| **Tap Right Option** while recording | Stop and transcribe. |
| **Ctrl+C** | Quit. |

### Change the hotkey

```bash
./start.sh --key alt_l    # Left Option
./start.sh --key ctrl_r   # Right Control
./start.sh --key f5       # F5 (also f6, f7, f8)
```

## How it works

1. **pynput** listens for the hotkey globally
2. **sounddevice** captures audio from your mic
3. A floating **AppKit overlay** shows a live waveform while recording
4. **whisper.cpp** transcribes locally using Metal GPU acceleration
5. Text is copied to clipboard, then **paste_helper** simulates Cmd+V

No network calls. No telemetry. Nothing phoning home. Just local compute.

## Requirements

- macOS 12+ (Monterey or newer)
- Apple Silicon (M1/M2/M3/M4) recommended for Metal GPU
- Python 3.10+
- Xcode Command Line Tools (`xcode-select --install`)

Works on Intel Macs too, just slower (~8-9s per transcription vs ~1.5s on Apple Silicon).

## Troubleshooting

**"paste_helper not found"** - Run `./setup.sh` again.

**Text doesn't paste (but clipboard works)** - paste_helper needs Accessibility permission. Remove and re-add it if you rebuilt it.

**No overlay/pill visible** - Make sure you're running `start.sh` in the foreground (not backgrounded with `&`). The overlay needs the terminal's window server connection.

**Slow transcription** - You're probably using the CPU backend. Run `./setup.sh` to build whisper-cpp with Metal, or install cmake first: `pip install cmake` or `brew install cmake`.

## License

MIT. Do whatever you want with it.
