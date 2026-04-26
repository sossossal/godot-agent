"""
Godot 日志解析工具 (Log Parser)
职责: 从 Godot 输出中提取脚本错误、堆栈跟踪和行号
"""

import re
from typing import List, Dict, Optional
from pydantic import BaseModel


class GodotError(BaseModel):
    file_path: str
    line_number: int
    error_msg: str
    stack_trace: List[str] = []


class LogParser:
    # 匹配示例: SCRIPT ERROR: Parse Error: ...
    # At: res://scripts/player.gd:12
    ERROR_PATTERN = re.compile(r'SCRIPT ERROR: (.*?)\n\s*At: (res://.*?):(\d+)', re.DOTALL)
    
    @staticmethod
    def parse_errors(output: str) -> List[Dict]:
        errors = []
        # 寻找脚本错误
        matches = re.finditer(r'SCRIPT ERROR: (.*?)\s*At: (res://.*?):(\d+)', output)
        for match in matches:
            errors.append({
                "message": match.group(1).strip(),
                "file": match.group(2).strip(),
                "line": int(match.group(3)),
                "type": "runtime_error"
            })
            
        # 寻找崩溃或引擎错误
        if "ERROR:" in output and not errors:
            engine_match = re.search(r'ERROR: (.*?)\n', output)
            if engine_match:
                errors.append({
                    "message": engine_match.group(1).strip(),
                    "type": "engine_error"
                })
                
        return errors
