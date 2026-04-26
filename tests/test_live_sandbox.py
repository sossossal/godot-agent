import httpx
import pytest
import time
import os
import json
import asyncio
import threading
from pathlib import Path
from urllib.parse import quote

import websockets

# 标记为 live 测试，默认排除
pytestmark = pytest.mark.live

# 配置
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


API_HOST = os.environ.get("GODOT_AGENT_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
API_PORT = _env_int("GODOT_AGENT_API_PORT", 8000)
BASE_URL = f"http://{API_HOST}:{API_PORT}"
PROJECT_PATH = str(Path("sandbox_project").resolve())
HTTP_TIMEOUT = 45.0

@pytest.fixture(scope="session", autouse=True)
def ensure_server_online():
    """确保 API Server 在线，否则跳过所有测试"""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
        assert response.status_code == 200
    except Exception:
        pytest.skip(f"API Server 未在 {BASE_URL} 启动，跳过 live sandbox 测试。")

@pytest.fixture(scope="session")
def editor_online():
    """启动并等待 Godot 编辑器上线"""
    try:
        response = httpx.post(
            f"{BASE_URL}/editor/launch",
            json={
                "project_path": PROJECT_PATH,
                "wait_for_editor": True,
                "editor_timeout": 30
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"无法启动或连接 Godot 编辑器，跳过 live sandbox 测试: {exc}")

    data = response.json()
    if not data.get("editor_online"):
        pytest.skip("Godot 编辑器未在超时时间内上线，跳过 live sandbox 测试。")
    return data["editor_state"]


def _post_editor_operation(operation, **payload):
    body = {
        "project_path": PROJECT_PATH,
        "operation": operation,
        "wait_for_editor_event": True,
        "editor_event_timeout": 10,
    }
    body.update(payload)
    response = httpx.post(f"{BASE_URL}/editor/operation", json=body, timeout=HTTP_TIMEOUT)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["operation"] == operation
    assert data["editor_event"]["kind"] == "editor_operation"
    assert data["editor_event"]["operation"] == operation
    assert data["editor_event"]["status"] == "success", json.dumps(data["editor_event"], ensure_ascii=False, indent=2)
    return data


def _scene_tree_contains_path(node, target_path):
    if not isinstance(node, dict):
        return False
    if node.get("path") == target_path:
        return True
    return any(_scene_tree_contains_path(child, target_path) for child in node.get("children", []))


def _scene_tree_find_path(node, target_path):
    if not isinstance(node, dict):
        return None
    if node.get("path") == target_path:
        return node
    for child in node.get("children", []):
        match = _scene_tree_find_path(child, target_path)
        if match:
            return match
    return None


def test_1_resource_opening(editor_online):
    """测试 1: 资源打开 (res:// 路径)"""
    start_time = time.time()
    response = httpx.post(
        f"{BASE_URL}/editor/open-resource",
        json={
            "project_path": PROJECT_PATH,
            "path": "res://sandbox_main.tscn",
            "wait_for_editor_event": True,
            "editor_event_timeout": 10
        },
        timeout=HTTP_TIMEOUT,
    )
    duration = time.time() - start_time
    assert response.status_code == 200
    data = response.json()
    
    assert "editor_event" in data
    assert data["editor_event"]["status"] == "success"
    assert "command_id" in data["editor_event"]
    assert duration < 10, f"资源打开耗时过长: {duration:.2f}s"
    print(f"\nResource opening passed: {duration:.2f}s")

def test_2_node_injection(editor_online):
    """测试 2: 节点注入 (Sprite2D)"""
    start_time = time.time()
    response = httpx.post(
        f"{BASE_URL}/execute",
        json={
            "project_path": PROJECT_PATH,
            "command": "在当前场景添加一个名为 TestSprite 的 Sprite2D 节点",
            "wait_for_editor_event": True,
            "editor_event_timeout": 10
        },
        timeout=HTTP_TIMEOUT,
    )
    duration = time.time() - start_time
    assert response.status_code == 200
    data = response.json()
    
    # 验证是否生成了编辑器脚本并执行成功
    assert "editor_event" in data
    assert data["editor_event"]["status"] == "success"
    assert data["editor_event"]["kind"] == "execute_script"
    assert "command_id" in data["editor_event"]
    assert duration < 10, f"节点注入耗时过长: {duration:.2f}s"
    print(f"\nNode injection passed: {duration:.2f}s")

def test_3_scene_creation(editor_online):
    """测试 3: 场景创建"""
    scene_name = f"TestScene_{int(time.time())}"
    start_time = time.time()
    response = httpx.post(
        f"{BASE_URL}/execute",
        json={
            "project_path": PROJECT_PATH,
            "command": f"创建一个名为 {scene_name} 的新场景",
            "wait_for_editor_event": True,
            "editor_event_timeout": 10
        },
        timeout=HTTP_TIMEOUT,
    )
    duration = time.time() - start_time
    assert response.status_code == 200
    data = response.json()
    
    # 验证场景创建回执
    assert "editor_event" in data
    assert data["editor_event"]["status"] == "success"
    
    # 验证产物
    artifacts = data.get("artifacts", [])
    assert any(a["type"] == "scene" for a in artifacts)
    
    assert duration < 10, f"场景创建耗时过长: {duration:.2f}s"
    print(f"\nScene creation passed: {duration:.2f}s")

def test_4_e2e_screenshot(editor_online):
    """测试 4: E2E 截图"""
    start_time = time.time()
    response = httpx.post(
        f"{BASE_URL}/execute",
        json={
            "project_path": PROJECT_PATH,
            "command": "测试当前场景并截图",
            "wait_for_editor_event": True,
            "editor_event_timeout": 15
        },
        timeout=HTTP_TIMEOUT,
    )
    duration = time.time() - start_time
    assert response.status_code == 200
    data = response.json()
    
    # 验证是否有截图产物
    artifacts = data.get("artifacts", [])
    screenshot = next((a for a in artifacts if a["type"] == "screenshot"), None)
    assert screenshot is not None
    assert os.path.exists(screenshot["path"])
    
    assert duration < 15, f"E2E 截图耗时过长: {duration:.2f}s"
    print(f"\nE2E screenshot passed: {duration:.2f}s")


def test_5_portal_websocket_realtime_stream(editor_online):
    """测试 5: Portal WebSocket 实时流"""
    node_name = f"WsProbe_{int(time.time())}"
    command = f"在当前场景添加一个名为 {node_name} 的 Sprite2D 节点"
    normalized_project = f"{Path(PROJECT_PATH).resolve().as_posix().rstrip('/')}/"

    async def run_case():
        uri = f"ws://{API_HOST}:{API_PORT}/ws/portal?project_path={quote(PROJECT_PATH, safe='')}"
        response_holder = {}
        completion = threading.Event()

        def execute_command():
            try:
                response = httpx.post(
                    f"{BASE_URL}/execute",
                    json={
                        "project_path": PROJECT_PATH,
                        "command": command,
                        "wait_for_editor_event": True,
                        "editor_event_timeout": 10,
                    },
                    timeout=HTTP_TIMEOUT,
                )
                response_holder["status_code"] = response.status_code
                response_holder["json"] = response.json()
            except Exception as exc:
                response_holder["error"] = str(exc)
            finally:
                completion.set()

        async with websockets.connect(uri, open_timeout=10, close_timeout=2) as websocket:
            initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
            assert initial["type"] == "health_update"
            assert initial["project_path"] == normalized_project

            worker = threading.Thread(target=execute_command, daemon=True)
            worker.start()

            seen_task_update = False
            seen_editor_success = False
            message_types = [initial["type"]]
            deadline = time.monotonic() + 20

            while time.monotonic() < deadline:
                remaining = max(0.2, deadline - time.monotonic())
                try:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=min(2.0, remaining))
                except TimeoutError:
                    if completion.is_set() and seen_task_update and seen_editor_success:
                        break
                    continue

                payload = json.loads(raw_message)
                message_type = payload.get("type")
                message_types.append(message_type)

                if message_type == "task_update":
                    task_update = payload.get("task_update", {})
                    if task_update.get("prompt") == command and task_update.get("status") in {"waiting_ack", "success"}:
                        seen_task_update = True

                elif message_type == "editor_event":
                    editor_event = payload.get("editor_event", {})
                    if editor_event.get("status") == "success" and editor_event.get("kind") == "execute_script":
                        seen_editor_success = True

                if completion.is_set() and seen_task_update and seen_editor_success:
                    break

            worker.join(timeout=5)
            assert "error" not in response_holder
            assert response_holder.get("status_code") == 200
            assert seen_task_update, f"未收到匹配的 task_update，消息类型: {message_types}"
            assert seen_editor_success, f"未收到匹配的 editor_event，消息类型: {message_types}"
            return message_types

    message_types = asyncio.run(run_case())
    print(f"\nPortal WebSocket 实时流成功: {message_types}")


def test_6_typed_editor_operations(editor_online):
    """测试 6: 类型化实时操作 (创建、选择、改属性、读场景树、删除)"""
    node_name = f"LiveOpProbe_{int(time.time())}"
    start_time = time.time()

    created = _post_editor_operation(
        "create_node",
        parent_path=".",
        node_type="Node2D",
        node_name=node_name,
        select_created=True,
    )
    node_path = created["editor_event"]["node_path"]
    assert created["editor_event"]["node_name"] == node_name
    assert created["editor_event"]["node_type"] == "Node2D"

    selected = _post_editor_operation("select_node", node_path=node_path)
    assert selected["editor_event"]["selected_node_path"] == node_path
    assert selected["editor_event"]["selected_node_name"] == node_name

    changed = _post_editor_operation(
        "set_node_property",
        node_path=node_path,
        property_name="position",
        value=[123, 45],
        value_type="vector2",
    )
    assert changed["editor_event"]["property_name"] == "position"
    assert changed["editor_event"]["value"] == {"x": 123.0, "y": 45.0}

    tree = _post_editor_operation("get_scene_tree", max_depth=4, max_nodes=200)
    assert tree["editor_event"]["node_count"] >= 1
    assert _scene_tree_contains_path(tree["editor_event"]["root"], node_path)

    deleted = _post_editor_operation("delete_node", node_path=node_path)
    assert deleted["editor_event"]["deleted_node_path"] == node_path
    assert deleted["editor_event"]["deleted_node_name"] == node_name

    after_delete = _post_editor_operation("get_scene_tree", max_depth=4, max_nodes=200)
    assert not _scene_tree_contains_path(after_delete["editor_event"]["root"], node_path)

    duration = time.time() - start_time
    assert duration < 20, f"类型化实时操作耗时过长: {duration:.2f}s"
    print(f"\nTyped editor operations passed: {duration:.2f}s")


def test_7_p7_editor_operations(editor_online):
    """测试 7: P7 编辑器操作扩展 (保存、结构调整、批量、脚本、实例化)"""
    suffix = int(time.time())
    start_time = time.time()

    open_response = httpx.post(
        f"{BASE_URL}/editor/open-resource",
        json={
            "project_path": PROJECT_PATH,
            "path": "res://sandbox_main.tscn",
            "wait_for_editor_event": True,
            "editor_event_timeout": 10,
        },
        timeout=HTTP_TIMEOUT,
    )
    assert open_response.status_code == 200, open_response.text

    parent_a_name = f"P7ParentA_{suffix}"
    parent_b_name = f"P7ParentB_{suffix}"
    child_name = f"P7Child_{suffix}"
    batch = _post_editor_operation(
        "batch_create_nodes",
        items=[
            {"parent_path": ".", "node_type": "Node2D", "node_name": parent_a_name},
            {"parent_path": ".", "node_type": "Node2D", "node_name": parent_b_name},
            {"parent_path": parent_a_name, "node_type": "Node2D", "node_name": child_name},
        ],
    )
    assert batch["editor_event"]["success_count"] == 3
    parent_a_path = batch["editor_event"]["results"][0]["node_path"]
    parent_b_path = batch["editor_event"]["results"][1]["node_path"]
    child_path = batch["editor_event"]["results"][2]["node_path"]

    changed = _post_editor_operation(
        "batch_set_properties",
        items=[
            {"node_path": parent_a_path, "property_name": "position", "value": [10, 20], "value_type": "vector2"},
            {"node_path": child_path, "property_name": "position", "value": [30, 40], "value_type": "vector2"},
        ],
    )
    assert changed["editor_event"]["success_count"] == 2

    duplicated = _post_editor_operation(
        "duplicate_node",
        node_path=child_path,
        new_name=f"P7ChildCopy_{suffix}",
    )
    copy_path = duplicated["editor_event"]["node_path"]

    renamed = _post_editor_operation(
        "rename_node",
        node_path=copy_path,
        new_name=f"P7ChildRenamed_{suffix}",
    )
    renamed_path = renamed["editor_event"]["node_path"]
    assert renamed["editor_event"]["old_node_path"] == copy_path

    reparented = _post_editor_operation(
        "reparent_node",
        node_path=renamed_path,
        target_parent_path=parent_b_path,
    )
    moved_path = reparented["editor_event"]["node_path"]
    assert moved_path.startswith(parent_b_path)

    ordered = _post_editor_operation("move_node_order", node_path=moved_path, index=0)
    assert ordered["editor_event"]["index"] == 0

    attached = _post_editor_operation(
        "attach_script",
        node_path=parent_a_path,
        script_path="res://scripts/sandbox_root.gd",
    )
    assert attached["editor_event"]["script_path"] == "res://scripts/sandbox_root.gd"

    tree_with_script = _post_editor_operation("get_scene_tree", max_depth=5, max_nodes=300)
    parent_a_node = _scene_tree_find_path(tree_with_script["editor_event"]["root"], parent_a_path)
    assert parent_a_node and parent_a_node["script_path"] == "res://scripts/sandbox_root.gd"

    detached = _post_editor_operation("detach_script", node_path=parent_a_path)
    assert detached["editor_event"]["old_script_path"] == "res://scripts/sandbox_root.gd"

    instantiated = _post_editor_operation(
        "instantiate_scene",
        parent_path=parent_b_path,
        scene_path="res://sandbox_main.tscn",
        node_name=f"P7SandboxInstance_{suffix}",
    )
    assert instantiated["editor_event"]["scene_path"] == "res://sandbox_main.tscn"
    assert instantiated["editor_event"]["node_path"].startswith(parent_b_path)

    saved_path = f"res://scenes/P7Live_{suffix}.tscn"
    saved = _post_editor_operation("save_scene_as", scene_path=saved_path)
    assert saved["editor_event"]["saved"] is True
    assert (Path(PROJECT_PATH) / "scenes" / f"P7Live_{suffix}.tscn").exists()

    reloaded = _post_editor_operation("reload_scene", scene_path=saved_path)
    assert reloaded["editor_event"]["scene_path"] == saved_path
    time.sleep(0.5)

    reloaded_tree = _post_editor_operation("get_scene_tree", max_depth=5, max_nodes=400)
    assert reloaded_tree["editor_event"]["scene_path"] == saved_path
    assert _scene_tree_contains_path(reloaded_tree["editor_event"]["root"], parent_a_path)
    assert _scene_tree_contains_path(reloaded_tree["editor_event"]["root"], moved_path)

    saved_current = _post_editor_operation("save_scene")
    assert saved_current["editor_event"]["saved"] is True
    assert saved_current["editor_event"]["scene_path"] == saved_path
    assert saved_current["editor_event"]["audit"]["rollback_anchor"]["operation"] == "save_scene"

    duration = time.time() - start_time
    assert duration < 35, f"P7 编辑器操作耗时过长: {duration:.2f}s"
    print(f"\nP7 editor operations passed: {duration:.2f}s")

if __name__ == "__main__":
    # 也可以直接运行脚本
    import sys
    pytest.main([__file__, "-v", "-s"])
