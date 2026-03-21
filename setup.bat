@echo off
chcp 65001 >nul
echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║   Godot Studio Agent — 一键安装           ║
echo  ╚═══════════════════════════════════════════╝
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 或更高版本
    pause & exit /b 1
)

:: 创建虚拟环境
if not exist venv (
    echo [1/3] 创建 Python 虚拟环境...
    python -m venv venv
)

:: 激活并安装依赖
echo [2/3] 安装依赖...
call venv\Scripts\activate.bat
pip install -r requirements.txt -q

:: 生成激活脚本
echo [3/3] 生成启动快捷方式...
echo @echo off > start.bat
echo call venv\Scripts\activate.bat >> start.bat
echo cd api_server >> start.bat
echo echo 正在启动 Godot Studio Agent... >> start.bat
echo echo 打开浏览器访问: http://localhost:8000/ui >> start.bat
echo start http://localhost:8000/ui >> start.bat
echo python main.py >> start.bat

echo.
echo  ✅ 安装完成！双击 start.bat 启动服务
echo  🌐 启动后访问: http://localhost:8000/ui
echo.

:: 询问是否立即启动
set /p LAUNCH="立即启动？(Y/N): "
if /i "%LAUNCH%"=="Y" (
    cd api_server
    start http://localhost:8000/ui
    python main.py
)
pause
