"""
Godot Agent 系统初始化
"""

import sys
import io

def configure_utf8_stdio():
    """强制控制台输出为 UTF-8"""
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 自动配置
configure_utf8_stdio()

__version__ = "1.7.0"
