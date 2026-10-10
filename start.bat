@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
echo MathMaster 本地数学练习系统
where py >nul 2>nul
if not errorlevel 1 (
    py -3 scripts\bootstrap.py
    goto :done
)
where python >nul 2>nul
if errorlevel 1 (
    echo 请先安装 Python 3.11+，推荐 Python 3.13，并启用 Add Python to PATH。
    pause
    exit /b 1
)
python scripts\bootstrap.py
:done
if errorlevel 1 (
    echo 启动未成功。请根据上方提示处理后再次双击 start.bat。
    pause
    exit /b 1
)
endlocal
