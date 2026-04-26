from agent_system.models import Task
from agent_system.skills.architect.apply_pattern_skill import ApplyPatternSkill
from agent_system.skills.registry import ParameterMapper
from agent_system.skills.resource.audio_skill import AudioManagementSkill


def test_audio_parameter_mapper_extracts_audio_resource_path():
    mapper = ParameterMapper()
    skill = AudioManagementSkill()

    params = mapper.map_params(
        "添加一个名为 JumpSFX 的 2D 音频节点并自动播放 res://assets/audio/jump-sfx.ogg",
        skill,
    )

    assert params["audio_name"] == "JumpSFX"
    assert params["audio_path"] == "res://assets/audio/jump-sfx.ogg"
    assert params["is_2d"] is True
    assert params["autoplay"] is True


def test_apply_pattern_skill_records_timestamp_without_name_error():
    skill = ApplyPatternSkill()
    task = Task(prompt="应用设计模式 HealthSystem")

    result = skill.execute(task, {"pattern_name": "HealthSystem", "overrides": {"speed": 500}})

    assert result.success is True
    assert task.context["applied_pattern_info"]["name"] == "HealthSystem"
    assert isinstance(task.context["applied_pattern_info"]["timestamp"], float)
    assert len(task.context["pending_pattern_steps"]) == 2
