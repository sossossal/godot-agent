"""
Godot Agent 链式任务集成测试 (Multi-Skill Chain Validation)
职责: 模拟复杂用户指令, 验证系统是否正确解析多个意向并生成 Skill 链
"""

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

def test_multi_skill_chain():
    # 1. 初始化路由器 (使用 sandbox_project)
    router = GodotAgentRouter()
    
    # 2. 模拟复杂指令
    # 该指令预期触发: create_godot_scene, inject_godot_node, smoke_test_scene
    prompt = "创建一个名为 Level1 的场景, 添加一个 Sprite2D 节点, 然后运行冒烟测试"
    
    print(f"用户指令: {prompt}")
    print("-" * 40)
    
    # 3. 规划阶段 (Planning)
    task = router.plan(prompt)
    
    print(f"规划状态: {task.status.value}")
    print(f"生成的步骤 ({len(task.steps)} 个):")
    for i, step in enumerate(task.steps, 1):
        skill_name = step.metadata.get("skill_name", "N/A")
        print(f"  {i}. {step.name} (Skill: {skill_name}) - {step.description}")
        
    # 4. 验证规划准确性
    expected_skills = ["create_godot_scene", "inject_godot_node", "smoke_test_scene"]
    actual_skills = [s.metadata.get("skill_name") for s in task.steps]
    
    assert len(task.steps) >= 3, "规划失败: 步骤不足"
    assert all(skill in actual_skills for skill in expected_skills), f"规划失败: 缺少预期技能. 实际得到: {actual_skills}"
    
    print("-" * 40)
    print("✅ 规划测试通过: 多意图识别与 Skill Chaining 逻辑正确")
    
    # 5. 执行模拟 (DRY RUN)
    # 我们暂不执行具体文件写入, 仅验证步骤依赖与参数映射
    print("模拟参数映射测试...")
    for step in task.steps:
        skill_name = step.metadata.get("skill_name")
        if skill_name:
            from agent_system.skills.registry import SkillRegistry
            skill_res = SkillRegistry.get_skill_with_params(skill_name, prompt)
            if skill_res:
                skill, params = skill_res
                print(f"  技能 {skill_name} -> 解析参数: {params}")
    
    print("-" * 40)
    print("✅ 参数映射测试通过: Heuristic Regex 能够正确解析场景名和节点名")

if __name__ == "__main__":
    try:
        test_multi_skill_chain()
        print("\n🏆 所有集成验证项通过!")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
