import requests
import json

def test_realtime_default_route():
    # 🆕 使用 "default" 绕过所有路径编码问题
    payload = {
        "command": "在 Tank 节点下添加一个名为 StatusLight 的 OmniLight3D, 并设置颜色为绿色",
        "project_path": "default"
    }

    url = "http://127.0.0.1:8000/execute"
    
    try:
        print(f"Sending command to {url} via DEFAULT route...")
        res = requests.post(url, json=payload)
        print(f"Status Code: {res.status_code}")
        data = res.json()
        print(f"Message: {data.get('message')}")
        print(f"Task Status: {data.get('status')}")
        
        if data.get('status') == 'success':
            print("✅ SUCCESS: Instruction sent to Godot via API Server!")
        else:
            print("❌ FAILED: Still showing offline. Check Godot output console for connection logs.")
                
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_realtime_default_route()
