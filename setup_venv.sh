#!/bin/bash
# Godot Agent - 虚拟环境快速设置 (Linux/macOS)

echo "========================================"
echo "  Godot Agent - 虚拟环境设置"
echo "========================================"
echo ""

# 检查 Python 是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3"
    echo "请安装 Python 3.10 或更高版本"
    exit 1
fi

echo "✅ 找到 Python"
python3 --version
echo ""

# 运行设置脚本
python3 setup_venv.py

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "  设置完成!"
    echo "========================================"
    echo ""
    echo "💡 运行以下命令激活虚拟环境:"
    echo "   source activate.sh"
    echo ""
else
    echo ""
    echo "❌ 设置失败"
    echo ""
fi
