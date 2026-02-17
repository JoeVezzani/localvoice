#!/bin/bash
set -e

echo ""
echo "  LocalVoice Setup"
echo "  ================"
echo ""

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# --- Check prerequisites ---
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

if ! command -v swiftc &>/dev/null; then
    echo "  ERROR: Xcode Command Line Tools not found."
    echo "  Run: xcode-select --install"
    exit 1
fi

# --- Python venv ---
echo "[1/4] Setting up Python environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q pynput sounddevice numpy requests \
    pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \
    pyobjc-framework-ApplicationServices

# --- Compile paste_helper ---
echo "[2/4] Compiling paste_helper..."
swiftc paste_helper.swift -o paste_helper -framework Cocoa -framework ApplicationServices 2>/dev/null
codesign --force --sign - --identifier "com.localvoice.paste-helper" paste_helper 2>/dev/null

# --- Build whisper-cpp with Metal (server + cli) ---
echo "[3/4] Building whisper-cpp with Metal GPU acceleration..."
if [ -f "whisper-server-metal" ]; then
    echo "  whisper-server-metal already exists, skipping build"
else
    # Check for native cmake (brew preferred over pip - pip cmake can be x86 on arm64)
    CMAKE=""
    if [ -f "/opt/homebrew/bin/cmake" ]; then
        CMAKE="/opt/homebrew/bin/cmake"
    elif [ -f "/usr/local/bin/cmake" ] && [ "$(file /usr/local/bin/cmake | grep -c arm64)" -gt 0 ]; then
        CMAKE="/usr/local/bin/cmake"
    elif command -v cmake &>/dev/null; then
        CMAKE="cmake"
    fi

    if [ -z "$CMAKE" ]; then
        echo "  Installing cmake via Homebrew..."
        if command -v brew &>/dev/null; then
            brew install --quiet cmake
            CMAKE="$(brew --prefix)/bin/cmake"
        else
            echo "  Homebrew not found, falling back to pip cmake..."
            pip install -q cmake
            CMAKE=".venv/bin/cmake"
        fi
    fi

    NATIVE_ARCH=$(uname -m)
    echo "  Using cmake: $CMAKE"
    echo "  Native arch: $NATIVE_ARCH"

    TMPDIR=$(mktemp -d)
    echo "  Cloning whisper.cpp..."
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$TMPDIR/whisper.cpp" 2>/dev/null

    echo "  Building with Metal support (this takes ~2 min)..."
    # Always force the native architecture to avoid x86 builds from Rosetta/pip cmake
    $CMAKE -B "$TMPDIR/whisper.cpp/build" -S "$TMPDIR/whisper.cpp" \
        -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_OSX_ARCHITECTURES="$NATIVE_ARCH" 2>/dev/null

    $CMAKE --build "$TMPDIR/whisper.cpp/build" --config Release \
        -j$(sysctl -n hw.ncpu) 2>/dev/null

    # Copy server binary (persistent mode, much faster)
    if [ -f "$TMPDIR/whisper.cpp/build/bin/whisper-server" ]; then
        cp "$TMPDIR/whisper.cpp/build/bin/whisper-server" whisper-server-metal
        echo "  Built whisper-server-metal (server mode)"
    fi

    # Copy CLI binary as fallback
    if [ -f "$TMPDIR/whisper.cpp/build/bin/whisper-cli" ]; then
        cp "$TMPDIR/whisper.cpp/build/bin/whisper-cli" whisper-cli-metal
    fi

    # Copy shared libraries
    mkdir -p lib
    find "$TMPDIR/whisper.cpp/build" -name "*.dylib" -exec cp {} lib/ \; 2>/dev/null

    rm -rf "$TMPDIR"
    echo "  Done! GPU acceleration enabled."
fi

# --- Download whisper models ---
echo "[4/4] Downloading whisper models..."
mkdir -p models

# Always grab the base model (small, fast fallback)
BASE="models/ggml-base.en.bin"
if [ ! -f "$BASE" ]; then
    echo "  Downloading base.en model (148 MB)..."
    curl -L --progress-bar \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" \
        -o "$BASE"
fi

# Download small quantized (best speed/accuracy balance, default)
SMALL="models/ggml-small.en-q5_0.bin"
if [ ! -f "$SMALL" ]; then
    echo "  Downloading small.en quantized model (175 MB)..."
    curl -L --progress-bar \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_0.bin" \
        -o "$SMALL"
fi

# If Metal build succeeded, also grab medium quantized for best accuracy
if [ -f "whisper-server-metal" ]; then
    MEDIUM="models/ggml-medium.en-q5_0.bin"
    if [ ! -f "$MEDIUM" ]; then
        echo "  Downloading medium.en quantized model (539 MB) for best accuracy..."
        curl -L --progress-bar \
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en-q5_0.bin" \
            -o "$MEDIUM"
    fi
fi

echo ""
echo "  Setup complete!"
echo ""
echo "  IMPORTANT: Grant these permissions in System Settings > Privacy & Security:"
echo ""
echo "    1. Accessibility:    $(pwd)/paste_helper"
echo "       (click +, press Cmd+Shift+G, paste the path above)"
echo ""
echo "    2. Input Monitoring: Terminal (or your terminal app)"
echo ""
echo "    3. Microphone:       Terminal (or your terminal app)"
echo ""
echo "  Then run:  ./start.sh"
echo ""
