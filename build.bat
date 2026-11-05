@echo off
REM Builds dist\YorritySEOGen.exe  (run from this folder; needs Python 3.10+ on PATH)
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt || goto :err
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name YorritySEOGen ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  main.py || goto :err
echo.
echo Done: dist\YorritySEOGen.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
