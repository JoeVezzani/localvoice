# LocalVoice

Talk to your computer. It types what you say.

**100% local. Zero cloud. Zero API keys. Your voice never leaves your machine.**

Uses [whisper.cpp](https://github.com/ggml-org/whisper.cpp) running on your Mac's GPU (Metal) for fast, accurate speech-to-text. Tap a key, talk, and the text appears wherever your cursor is.

## Speed

On Apple Silicon with Metal GPU (server mode, model stays in GPU memory):

| Model | Transcription Time | Accuracy |
|-------|-------------------|----------|
| base.en | ~0.2s | Good |
| **small.en-q5_0** | **~0.4s** | **Better (default)** |
| medium.en-q5_0 | ~0.8s | Best |

Server mode keeps the model loaded in GPU memory. No cold-start penalty per transcription.

## Setup

```bash
git clone https://github.com/JoeVezzani/localvoice.git
cd localvoice
chmod +x setup.sh start.sh
./setup.sh
```

Setup does everything automatically:
1. Creates Python venv and installs dependencies
2. Compiles the paste helper (Swift)
3. Builds whisper-cpp server from source with Metal GPU acceleration
4. Downloads whisper models (base + small + medium)

Takes about 5 minutes. Requires Xcode Command Line Tools (`xcode-select --install`).

### Permissions (one-time)

Open **System Settings > Privacy & Security** and add:

| Setting | What to add |
|---------|-------------|
| **Accessibility** | `paste_helper` (from this folder) |
| **Input Monitoring** | Terminal.app (or iTerm2, etc.) |
| **Microphone** | Terminal.app (or iTerm2, etc.) |

For Accessibility: click +, press Cmd+Shift+G, paste the full path to `paste_helper` shown at the end of setup.

## Usage

```bash
./start.sh
```

Run in a dedicated Terminal tab (keep it open). The whisper server starts automatically and stays running.

### Controls

| Action | What happens |
|--------|-------------|
| **Hold Right Option** | Start recording. Release to transcribe. |
| **Tap Right Option** | Start recording (stays on). |
| **Press Space** while recording | Lock mode (keeps recording until you tap the hotkey again). |
| **Tap Right Option** while recording | Stop and transcribe. |
| **Ctrl+C** | Quit (stops the whisper server too). |

The floating pill overlay is **draggable** - move it wherever you want on screen.

### The Floating Pill

When recording, a floating pill appears at the bottom of your screen:

- **Purple/cyan waveform + "LISTENING"** = recording, keep talking
- **"LOCKED"** = lock mode active, hands-free recording
- **Amber wave + "TRANSCRIBING"** = processing your audio
- **Pill disappears** = done, text was pasted

Sounds: "Tink" = started, "Pop" = done, "Basso" = error.

### Change the hotkey

```bash
./start.sh --key alt_l    # Left Option
./start.sh --key ctrl_r   # Right Control
./start.sh --key f5       # F5 (also f6, f7, f8)
```

### Change the model

```bash
./start.sh --model base     # Fastest, lighter accuracy
./start.sh --model small    # Default - best speed/accuracy balance
./start.sh --model medium   # Best accuracy, slightly slower
```

## How it works

1. **whisper-server** starts with model loaded in GPU memory (Metal)
2. **pynput** listens for the hotkey globally
3. **sounddevice** captures audio from your mic
4. A floating **AppKit overlay** shows a live waveform at 60fps while recording
5. Audio is sent via HTTP to the local whisper server for transcription
6. Text is copied to clipboard, then **paste_helper** simulates Cmd+V

No network calls. No telemetry. Nothing phoning home. Just local compute.

## Requirements

- macOS 12+ (Monterey or newer)
- Apple Silicon (M1/M2/M3/M4) recommended for Metal GPU
- Python 3.10+
- Xcode Command Line Tools (`xcode-select --install`)

## Troubleshooting

**"paste_helper not found"** - Run `./setup.sh` again.

**Text doesn't paste (but clipboard works)** - paste_helper needs Accessibility permission. Remove and re-add it in System Settings if you rebuilt it.

**No overlay/pill visible** - Make sure you're running `start.sh` in the foreground (not backgrounded). The overlay needs the terminal's window server connection.

**"whisper-server-metal not found"** - The Metal build failed during setup. Make sure cmake is available (`brew install cmake` or the setup will install it via pip). Then delete any partial builds and re-run `./setup.sh`.

**Slow transcription (8+ seconds)** - You're probably using the CPU backend. Re-run `./setup.sh` to build with Metal.

**Phantom words when not talking** - The model sometimes hallucinates on silence. Keep recordings short and intentional. The small/medium models do this less than base.

## License

MIT. Do whatever you want with it.
