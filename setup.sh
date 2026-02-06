#!/bin/bash
set -e

echo ""
echo "  LocalVoice Setup"
echo "  ================"
echo ""

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# --- Python venv ---
echo "[1/4] Setting up Python environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q pynput sounddevice numpy pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices

# --- Compile paste_helper ---
echo "[2/4] Compiling paste_helper..."
swiftc paste_helper.swift -o paste_helper -framework Cocoa -framework ApplicationServices 2>/dev/null
codesign --force --sign - --identifier "com.localvoice.paste-helper" paste_helper 2>/dev/null

# --- Download whisper model ---
echo "[3/4] Downloading whisper model..."
mkdir -p models
MODEL="models/ggml-base.en.bin"
if [ ! -f "$MODEL" ]; then
    curl -L --progress-bar \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" \
        -o "$MODEL"
    echo "  Downloaded base.en model (148 MB)"
else
    echo "  Model already exists, skipping"
fi

# --- Build whisper-cpp with Metal ---
echo "[4/4] Building whisper-cpp with Metal GPU acceleration..."
if [ -f "whisper-cli-metal" ]; then
    echo "  whisper-cli-metal already exists, skipping"
else
    # Check for cmake
    CMAKE=""
    if command -v cmake &>/dev/null; then
        CMAKE="cmake"
    elif [ -f ".venv/bin/cmake" ]; then
        CMAKE=".venv/bin/cmake"
    else
        echo "  Installing cmake..."
        pip install -q cmake
        CMAKE=".venv/bin/cmake"
    fi

    TMPDIR=$(mktemp -d)
    echo "  Cloning whisper.cpp..."
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$TMPDIR/whisper.cpp" 2>/dev/null

    echo "  Building with Metal support (this takes ~1 min)..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        $CMAKE -B "$TMPDIR/whisper.cpp/build" -S "$TMPDIR/whisper.cpp" \
            -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release 2>/dev/null
    else
        # Cross-compile for arm64 on x86 (Rosetta)
        $CMAKE -B "$TMPDIR/whisper.cpp/build" -S "$TMPDIR/whisper.cpp" \
            -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_OSX_ARCHITECTURES=arm64 -DGGML_NATIVE=OFF 2>/dev/null
    fi

    $CMAKE --build "$TMPDIR/whisper.cpp/build" --config Release \
        -j$(sysctl -n hw.ncpu) 2>/dev/null

    cp "$TMPDIR/whisper.cpp/build/bin/whisper-cli" whisper-cli-metal

    # Copy shared libraries
    mkdir -p lib
    find "$TMPDIR/whisper.cpp/build" -name "*.dylib" -exec cp {} lib/ \; 2>/dev/null

    rm -rf "$TMPDIR"
    echo "  Built whisper-cli-metal with GPU acceleration"
fi

# --- Upgrade model if Metal is available ---
if [ -f "whisper-cli-metal" ]; then
    MEDIUM="models/ggml-medium.en-q5_0.bin"
    if [ ! -f "$MEDIUM" ]; then
        echo ""
        echo "  Metal build detected! Downloading medium quantized model for better accuracy..."
        curl -L --progress-bar \
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en-q5_0.bin" \
            -o "$MEDIUM"
        echo "  Downloaded medium.en-q5_0 model (539 MB)"
        echo "  With Metal: ~1.5s transcription. Without: ~8s. Big difference."
    fi
fi

echo ""
echo "  Setup complete!"
echo ""
echo "  Before first run, grant these permissions in System Settings > Privacy & Security:"
echo ""
echo "    Accessibility:    $(pwd)/paste_helper"
echo "    Input Monitoring: Terminal (or your terminal app)"
echo "    Microphone:       Terminal (or your terminal app)"
echo ""
echo "  Then run:  ./start.sh"
echo ""
