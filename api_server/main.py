"""
Godot Studio Agent — FastAPI 服务器
提供 REST API + Web UI 静态服务
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import uvicorn
from pathlib import Path
import sys
import json
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))
from agent_system.router import GodotStudioRouter

# ─── 应用初始化 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Godot Studio Agent API",
    description="单机游戏 AI 编程助手 — 支持 11 个专业角色",
    version="2.0.0",
)

# 挂载 Web UI 静态文件
web_ui_path = Path(__file__).parent.parent / "web_ui"
if web_ui_path.exists():
    app.mount("/static", StaticFiles(directory=str(web_ui_path)), name="static")

# 全局 Agent 实例
_router: Optional[GodotStudioRouter] = None


def get_router() -> GodotStudioRouter:
    global _router
    if _router is None:
        _router = GodotStudioRouter()
    return _router


# ─── 数据模型 ────────────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    command: str
    context: Optional[Dict[str, Any]] = None
    godot_project_path: Optional[str] = None


class PipelineRequest(BaseModel):
    commands: List[str]
    context: Optional[Dict[str, Any]] = None


class RegisterRoleRequest(BaseModel):
    name: str
    keywords: List[str]


# ─── 路由 ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    get_router()
    print("🚀 Godot Studio Agent API 服务器已启动")


@app.get("/", response_class=HTMLResponse)
async def root():
    """重定向到 Web UI"""
    return HTMLResponse("""
    <html><head><meta http-equiv="refresh" content="0; url=/ui"></head>
    <body>正在跳转到控制面板...</body></html>
    """)


@app.get("/ui", response_class=HTMLResponse)
async def ui():
    """返回 Web 控制面板"""
    html_path = web_ui_path / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Web UI 未找到，请检查 web_ui/index.html</h1>")


@app.post("/execute")
async def execute_command(req: CommandRequest):
    """执行 Agent 命令"""
    router = get_router()
    if req.godot_project_path:
        router.godot_cli.project_path = req.godot_project_path
    result = router.execute(req.command, req.context)
    result["timestamp"] = datetime.now().isoformat()
    return result


@app.post("/pipeline")
async def execute_pipeline(req: PipelineRequest):
    """执行命令流水线（多步骤顺序执行）"""
    router = get_router()
    results = router.execute_pipeline(req.commands)
    return {
        "success": all(r.get("success") for r in results),
        "steps": len(results),
        "results": results,
    }


@app.get("/roles")
async def get_roles():
    """获取所有可用角色信息"""
    return {"roles": get_router().get_roles_info()}


@app.get("/history")
async def get_history(limit: int = 20):
    """获取命令历史"""
    return {"history": get_router().get_history(limit)}


@app.post("/session/clear")
async def clear_session():
    """清空会话上下文（开始新项目）"""
    get_router().clear_session()
    return {"success": True, "message": "会话已清空"}


@app.get("/templates")
async def list_templates():
    """列出所有 GDScript 模板"""
    from agent_system.tools.script_library import ScriptLibrary
    lib = ScriptLibrary()
    return {"templates": lib.list_templates()}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "roles": len(get_router()._roles),
        "history_count": len(get_router().history),
    }


# ─── 启动 ───────────────────────────────────────────────────────────────────

def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")


if __name__ == "__main__":
    main()
