@echo off
setlocal enabledelayedexpansion

echo ==========================================================
echo    IncuBrix Prompt-Based AI Video Editor
echo ==========================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in system PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

:: 2. Check .env configuration
if not exist .env (
    echo [*] No .env file detected. Creating .env from .env.example...
    copy .env.example .env >nul
    echo [*] Created .env with default configuration.
    echo [*] Tip: To use Groq, Gemini, or Ollama, open .env and add your API key.
    echo.
)

:: 3. Optional Virtual Environment
if not exist venv (
    echo [*] Creating virtual environment 'venv'...
    python -m venv venv
)
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: 4. Install Dependencies
echo [*] Checking dependencies...
pip install -r requirements.txt --quiet

:: 5. Open Browser in Background
start "" "http://127.0.0.1:8000/demo"

:: 6. Start Uvicorn Server
echo.
echo ==========================================================
echo    Server starting at http://127.0.0.1:8000/demo
echo    Press Ctrl+C to stop the server
echo ==========================================================
echo.
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

pause
