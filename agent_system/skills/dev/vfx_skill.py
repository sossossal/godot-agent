"""
粒子效果注入技能 (VFX Injection Skill)
职责: 在场景中自动注入粒子节点 (GPUParticles2D), 并配置预设的视觉效果
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class VFXParams(BaseModel):
    effect_type: str = Field(description="效果类型: explosion, smoke, fire, sparks")
    node_name: Optional[str] = Field(None, description="节点名称")
    amount: int = Field(default=32, description="粒子数量")
    one_shot: bool = Field(default=True, description="是否只发射一次")


class ParticleEffectSkill(BaseSkill):
    metadata = SkillMetadata(
        name="inject_vfx_particle",
        description="在当前场景中添加粒子特效。支持爆炸、烟雾、火焰等常用视觉效果预设。",
        category="dev",
        tags=["vfx", "particles", "visual-effect", "editor_plugin"]
    )
    input_model = VFXParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = VFXParams(**params)
        effect_name = p.node_name or f"{p.effect_type}_vfx"
        
        # 1. 检查编辑器状态
        editor_state = task.context.get("editor_state", {})
        if not editor_state.get("is_active"):
            return self.build_result(
                success=False,
                message="编辑器离线, 无法实时注入 VFX 节点",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["editor_offline"]},
            )
            
        task.add_log(f"✨ 正在注入粒子特效: {p.effect_type} (Name: {effect_name})")
        
        # 2. 生成粒子材质配置脚本
        script = self._generate_vfx_script(p, effect_name)
        
        artifact = Artifact(
            name=f"vfx_{effect_name}.gd",
            path="internal://",
            type="editor_script",
            content=script
        )
        
        # 3. 更新蓝图
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"VFX_{effect_name}",
                description=f"粒子特效: {p.effect_type}",
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        return self.build_result(
            success=True,
            message=f"已在场景中成功注入 '{p.effect_type}' 特效节点。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "editor_online", "status": "passed"},
                    {"name": "vfx_script_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
        )

    def _generate_vfx_script(self, p: VFXParams, node_name: str) -> str:
        # 定义不同效果的材质参数
        color_code = "Color(1, 1, 1)"
        if p.effect_type == "fire": color_code = "Color(1, 0.5, 0)"
        elif p.effect_type == "explosion": color_code = "Color(1, 0.8, 0.2)"
        
        return f'''
func _run(plugin: EditorPlugin):
	var scene_root = plugin.get_editor_interface().get_edited_scene_root()
	if not scene_root:
		print("❌ Error: No active scene root")
		return
		
	var particles = GPUParticles2D.new()
	particles.name = "{node_name}"
	particles.amount = {p.amount}
	particles.one_shot = {"true" if p.one_shot else "false"}
	particles.explosiveness = 0.8 if "{p.effect_type}" == "explosion" else 0.0
	
	# 创建并配置材质
	var mat = ParticleProcessMaterial.new()
	mat.gravity = Vector3(0, 98, 0) if "{p.effect_type}" != "smoke" else Vector3(0, -40, 0)
	mat.color = {color_code}
	mat.initial_velocity_min = 50.0
	mat.initial_velocity_max = 100.0
	mat.spread = 180.0 if "{p.effect_type}" == "explosion" else 45.0
	
	particles.process_material = mat
	
	# 确保可见 (使用默认纹理或颜色点)
	# 注意: 这里使用简单渲染, 实际可关联纹理资源
	
	scene_root.add_child(particles)
	particles.owner = scene_root
	print("✅ Success: Added VFX particle {node_name}")
'''
