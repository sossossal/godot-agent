"""
3D 环境搭建技能 (3D Environment Skill - 增强型)
职责: 自动化搭建 3D 基础场景, 支持编辑器实时注入和离线 CLI 执行
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class Setup3DParams(BaseModel):
    add_ground: bool = Field(default=True, description="是否添加地面")
    add_camera: bool = Field(default=True, description="是否添加相机")
    add_light: bool = Field(default=True, description="是否添加灯光")
    scene_name: str = Field(default="Main3D", description="创建的场景名称 (离线模式下有效)")


class Setup3DEnvironmentSkill(BaseSkill):
    metadata = SkillMetadata(
        name="setup_3d_environment",
        description="一键搭建 3D 基础环境。自动配置 WorldEnvironment、DirectionalLight3D、Camera3D 和地面。",
        category="dev",
        tags=["3d", "setup", "environment", "editor_plugin"]
    )
    input_model = Setup3DParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = Setup3DParams(**params)
        scene_path = f"res://scenes/{p.scene_name}.tscn"
        layout_check = self.validate_managed_output_path(scene_path, "generated_scene")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断 3D 场景创建: {scene_path}",
                params=self.dump_model(p),
                error="project_layout_validation_failed",
                validation={
                    "passed": False,
                    "checks": [{"name": "project_layout", "status": "blocked"}],
                    "layout_check": layout_check,
                },
            )
        task.add_log("🌐 正在初始化 3D 空间环境...")
        
        editor_state = task.context.get("editor_state", {})
        is_active = editor_state.get("is_active", False)
        
        if is_active:
            task.add_log("🎯 编辑器在线: 正在生成实时注入脚本")
            script = self._generate_logic_script(p, mode="editor")
            artifact = Artifact(
                name="setup_3d_space.gd",
                path="internal://",
                type="editor_script",
                content=script
            )
            return self.build_result(
                success=True,
                message="已下发 3D 环境实时初始化指令。",
                params=self.dump_model(p),
                artifacts=[artifact],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "editor_online", "status": "passed"},
                        {"name": "project_layout", "status": "passed"},
                        {"name": "setup_script_generated", "status": "passed"},
                    ],
                    "layout_check": layout_check,
                },
                rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
            )
        else:
            task.add_log("⚙️ 编辑器离线: 使用 Godot CLI 创建 3D 场景文件")
            script = self._generate_logic_script(p, mode="headless")
            result = self.godot_cli.execute_editor_script(script)
            
            if result.success:
                # 更新蓝图
                blueprint = task.context.get("blueprint_manager")
                if blueprint:
                    blueprint.blueprint.game_genre = "3D"
                    from ...tools.blueprint_manager import Feature
                    blueprint.add_feature(Feature(
                        name="3D_Environment",
                        description=f"已配置 3D 环境场景: {scene_path}",
                        files=[scene_path],
                        creation_skill=self.metadata.name,
                        creation_params=params
                    ))
                    blueprint.save()
                return self.build_result(
                    success=True,
                    message=f"3D 基础场景已创建: {scene_path}",
                    params=self.dump_model(p),
                    artifacts=[
                        Artifact(name=f"{p.scene_name}.tscn", path=scene_path, type="scene"),
                        Artifact(name="setup_3d_space.gd", path="internal://", type="headless_script", content=script),
                    ],
                    validation={
                        "passed": True,
                        "checks": [
                            {"name": "headless_setup_script_generated", "status": "passed"},
                            {"name": "project_layout", "status": "passed"},
                            {"name": "scene_create_dispatch", "status": "passed"},
                        ],
                        "layout_check": layout_check,
                    },
                    rollback={"available": False, "strategy": "delete_created_scene_or_restore_from_vcs"},
                )
            return self.build_result(
                success=False,
                message="3D 场景创建失败",
                params=self.dump_model(p),
                error=result.error,
                artifacts=[Artifact(name="setup_3d_space.gd", path="internal://", type="headless_script", content=script)],
                validation={"passed": False, "issues": ["setup_3d_failed"]},
            )

    def _generate_logic_script(self, p: Setup3DParams, mode: str = "editor") -> str:
        """
        生成 3D 环境构建逻辑
        mode: 'editor' (注入 plugin 变量) 或 'headless' (继承 SceneTree)
        """
        
        # 核心构建逻辑 (与平台无关)
        core_logic = f'''
	# 1. 创建环境
	var env = WorldEnvironment.new()
	env.name = "WorldEnvironment"
	var sky_env = Environment.new()
	sky_env.background_mode = Environment.BG_SKY
	sky_env.sky = Sky.new()
	sky_env.sky.sky_material = PanoramaSkyMaterial.new()
	env.environment = sky_env
	root.add_child(env)
	env.owner = root
	
	# 2. 灯光
	if {str(p.add_light).lower()}:
		var light = DirectionalLight3D.new()
		light.name = "DirectionalLight3D"
		light.position = Vector3(0, 10, 0)
		light.rotation_degrees = Vector3(-45, 45, 0)
		light.shadow_enabled = true
		root.add_child(light)
		light.owner = root

	# 3. 相机
	if {str(p.add_camera).lower()}:
		var cam = Camera3D.new()
		cam.name = "MainCamera3D"
		cam.position = Vector3(0, 5, 10)
		cam.look_at(Vector3.ZERO)
		root.add_child(cam)
		cam.owner = root

	# 4. 地面
	if {str(p.add_ground).lower()}:
		var ground = MeshInstance3D.new()
		ground.name = "Ground"
		var plane_mesh = PlaneMesh.new()
		plane_mesh.size = Vector2(20, 20)
		ground.mesh = plane_mesh
		root.add_child(ground)
		ground.owner = root
		# 自动创建碰撞
		ground.create_trimesh_collision()
'''

        if mode == "editor":
            return f'''func _run(plugin: EditorPlugin):
	var root = plugin.get_editor_interface().get_edited_scene_root()
	if not root:
		print("❌ No active scene")
		return
{core_logic}
	print("✅ Done")
'''
        else:
            return f'''extends SceneTree
func _initialize():
	var root = Node3D.new()
	root.name = "{p.scene_name}"
{core_logic}
	
	var scene = PackedScene.new()
	scene.pack(root)
	var path = "res://scenes/{p.scene_name}.tscn"
	var dir_path = path.get_base_dir()
	if not DirAccess.dir_exists_absolute(dir_path):
		DirAccess.make_dir_recursive_absolute(dir_path)
	ResourceSaver.save(scene, path)
	print("✅ Created 3D Scene: %s" % path)
	quit(0)
'''
