#!/bin/bash
# 运行 Godot Agent 测试套件 (Linux/macOS)

echo "========================================"
echo "  Godot Agent - 测试套件"
echo "========================================"
echo ""

# 检查虚拟环境
if [ -f "venv/bin/activate" ]; then
    echo "✅ 激活虚拟环境..."
    source venv/bin/activate
else
    echo "⚠️  未找到虚拟环境"
    echo "💡 建议先运行 ./setup_venv.sh"
    echo ""
fi

# 运行测试
echo "🧪 运行测试..."
echo ""

python3 tests/run_tests.py

echo ""
echo "========================================"
echo "  测试完成"
echo "========================================"
echo ""
