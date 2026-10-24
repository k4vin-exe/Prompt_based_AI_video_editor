#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "   IncuBrix Prompt-Based AI Video Editor"
echo "=========================================================="
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+."
    exit 1
fi

# 2. Check .env configuration
if [ ! -f .env ]; then
    echo "[*] No .env file detected. Creating .env from .env.example..."
    cp .env.example .env
    echo "[*] Created .env with default configuration."
    echo "[*] Tip: To use Groq, Gemini, or Ollama, open .env and add your API key."
    echo ""
fi

# 3. Virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment 'venv'..."
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Install Dependencies
echo "[*] Checking dependencies..."
pip install -r requirements.txt --quiet

# 5. Open Browser (cross-platform)
if command -v xdg-open &> /dev/null; then
    (sleep 1 && xdg-open "http://127.0.0.1:8000/demo") &
elif command -v open &> /dev/null; then
    (sleep 1 && open "http://127.0.0.1:8000/demo") &
fi

# 6. Start Uvicorn Server
echo ""
echo "=========================================================="
echo "   Server starting at http://127.0.0.1:8000/demo"
echo "   Press Ctrl+C to stop the server"
echo "=========================================================="
echo ""
python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
