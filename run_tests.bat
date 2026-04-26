@echo off
REM 运行 Godot Agent 测试套件 (Windows)

echo ========================================
echo   Godot Agent - 测试套件
echo ========================================
echo.

REM 检查虚拟环境
if exist venv\Scripts\activate.bat (
    echo ✅ 激活虚拟环境...
    call venv\Scripts\activate.bat
) else (
    echo ⚠️  未找到虚拟环境
    echo 💡 建议先运行 setup_venv.bat
    echo.
)

REM 运行测试
echo 🧪 运行测试...
echo.

python tests\run_tests.py

echo.
echo ========================================
echo   测试完成
echo ========================================
echo.

pause
