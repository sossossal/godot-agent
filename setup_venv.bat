@echo off
REM Godot Agent - 虚拟环境快速设置 (Windows CMD)

echo ========================================
echo   Godot Agent - 虚拟环境设置
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python
    echo 请从 https://www.python.org 下载并安装 Python 3.10+
    pause
    exit /b 1
)

echo ✅ 找到 Python
echo.

REM 运行设置脚本
python setup_venv.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   设置完成! 
    echo ========================================
    echo.
    echo 💡 运行 activate.bat 激活虚拟环境
    echo.
) else (
    echo.
    echo ❌ 设置失败
    echo.
)

pause
