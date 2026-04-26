"""
Godot Agent LLM 客户端 (通用版)
职责: 封装 API 调用, 支持 ChatCompletion 和 Tool Calling
"""

import json
import requests
import sys
from typing import Dict, List, Any, Optional


class LLMClient:
    """通用的 LLM 客户端接口"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        
    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None) -> Optional[Dict]:
        """发起聊天请求"""
        if not self.api_key:
            return None
            
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4o",  # 或 deepseek-chat
            "messages": messages,
            "temperature": 0.1
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]
        except Exception as e:
            print(f"⚠️ LLM 请求失败: {e}")
            return None

    def extract_parameters(self, prompt: str, tool_definition: Dict) -> Dict[str, Any]:
        """利用 LLM Tool Calling 提取结构化参数"""
        messages = [
            {"role": "system", "content": "你是一个精确的 Godot 参数提取助手。根据用户指令, 提取函数调用所需的参数。"},
            {"role": "user", "content": prompt}
        ]
        
        res = self.chat(messages, tools=[tool_definition])
        if res and res.get("tool_calls"):
            tool_call = res["tool_calls"][0]
            try:
                return json.loads(tool_call["function"]["arguments"])
            except:
                return {}
        return {}
