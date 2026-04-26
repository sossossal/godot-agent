import re
from typing import Dict, List, Any, Optional
from pathlib import Path

class DiagnosisResult:
    """诊断结果"""
    def __init__(self, cause: str, suggested_action: str, confidence: float, risk_level: str = "medium"):
        self.cause = cause
        self.suggested_action = suggested_action
        self.confidence = confidence
        self.risk_level = risk_level # 'low', 'medium', 'high'

class DiagnosisService:
    """错误自诊断服务 (受控自治层核心)
    职责: 分析执行日志、定位错误根源、提供自愈建议
    """
    
    def __init__(self, index_service: Any = None):
        self.index_service = index_service
        
        # 常见错误模式匹配
        self.ERROR_PATTERNS = {
            "node_not_found": re.compile(r'(?:Node not found|get_node): "([^"]+)"'),
            "script_error": re.compile(r'at: (res://[^:]+):(\d+)'),
            "export_template_missing": re.compile(r'No export template found'),
            "missing_resource": re.compile(r'Resource: "([^"]+)" could not be loaded'),
            "invalid_uid": re.compile(r'ID: ([^ ]+) is invalid'),
        }

    def diagnose(self, logs: List[str], context: Dict[str, Any] = None) -> List[DiagnosisResult]:
        """根据日志和上下文进行诊断"""
        results = []
        log_text = "\n".join(logs)
        
        # 1. 检查节点找不到错误 (联动语义中台)
        node_match = self.ERROR_PATTERNS["node_not_found"].search(log_text)
        if node_match:
            node_path = node_match.group(1)
            results.append(self._diagnose_node_error(node_path, context))
            
        # 2. 检查脚本运行时错误
        script_match = self.ERROR_PATTERNS["script_error"].search(log_text)
        if script_match:
            script_path = script_match.group(1)
            line = script_match.group(2)
            results.append(DiagnosisResult(
                cause=f"脚本运行时异常: {script_path} 第 {line} 行",
                suggested_action=f"检查 {script_path} 的逻辑或增加判空保护",
                confidence=0.8,
                risk_level="high"
            ))
            
        # 3. 检查导出模板问题
        if self.ERROR_PATTERNS["export_template_missing"].search(log_text):
            results.append(DiagnosisResult(
                cause="缺少 Godot 导出模板",
                suggested_action="请在 Godot 编辑器中下载对应的导出模板预设",
                confidence=1.0,
                risk_level="low"
            ))
            
        # 4. 检查资源丢失
        res_match = self.ERROR_PATTERNS["missing_resource"].search(log_text)
        if res_match:
            res_path = res_match.group(1)
            results.append(DiagnosisResult(
                cause=f"资源丢失: {res_path}",
                suggested_action=f"使用 Resource Manager 执行 '审计并修复项目资源' 以重建引用",
                confidence=0.9,
                risk_level="medium"
            ))
            
        return results

    def _diagnose_node_error(self, node_path: str, context: Dict[str, Any]) -> DiagnosisResult:
        """针对节点找不到的深度诊断"""
        suggestion = f"确认节点 {node_path} 在当前场景中是否存在"
        
        # 如果有索引，尝试寻找同名但路径不同的节点
        if self.index_service:
            node_name = node_path.split("/")[-1]
            current_scene = (context or {}).get("editor_state", {}).get("current_scene")
            if current_scene:
                rel_scene = current_scene.replace("res://", "")
                scene_data = self.index_service.scenes.get(rel_scene)
                if scene_data:
                    # 寻找模糊匹配
                    alternatives = [n["name"] for n in scene_data["nodes"] if n["name"] == node_name]
                    if alternatives:
                        suggestion = f"节点 {node_name} 的路径可能已改变，建议使用正确路径或通过名称查找"
        
        return DiagnosisResult(
            cause=f"场景内节点未找到: {node_path}",
            suggested_action=suggestion,
            confidence=0.7
        )
