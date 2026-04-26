"""
技能注册表 (Skill Registry)
职责: 技能的注册、发现和实例化, 以及参数映射 (鲁棒正则版)
"""

from typing import Dict, List, Any, Optional, Type
from .base import BaseSkill
from ..tools.llm_client import LLMClient
import re


class ParameterMapper:
    """智能参数映射器: 从 Prompt 提取 Skill 所需的参数"""
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client
    
    def map_params(self, prompt: str, skill: BaseSkill) -> Dict[str, Any]:
        """优先使用 LLM 语义映射, 失败或离线则回退到正则规则映射"""
        params = {}
        
        # 1. 优先使用 LLM (Semantic Extraction)
        if self.llm_client:
            tool_def = skill.get_tool_definition()
            llm_params = self.llm_client.extract_parameters(prompt, tool_def)
            if llm_params:
                return {k: v for k, v in llm_params.items() if v is not None}

        # 2. 🆕 通用路径提取 (增强: 排除节点名干扰)
        tscn_match = re.search(r'res://[\w/\.]+\.tscn', prompt)
        if tscn_match:
            params["scene_path"] = tscn_match.group(0)
            params["target_scene"] = tscn_match.group(0)
            
        gd_match = re.search(r'res://[\w/\.]+\.gd', prompt)
        if gd_match:
            params["script_path"] = gd_match.group(0)

        audio_match = re.search(r'res://[\w/\.-]+\.(?:ogg|wav|mp3|flac)', prompt, re.IGNORECASE)
        table_path_match = re.search(r'(?:res://)?[\w/\.-]+\.(?:csv|tsv|json)', prompt, re.IGNORECASE)
        asset_path_match = re.search(
            r'(?:res://)?[\w/\.-]+\.(?:png|jpg|jpeg|webp|tres|res|tscn|blend|glb|gltf|ase|aseprite|atlas|zip|sbsar)',
            prompt,
            re.IGNORECASE,
        )
        quoted_asset_path_match = re.search(
            r'["“]([^"\n]+?\.(?:png|jpg|jpeg|webp|tres|res|tscn|blend|glb|gltf|ase|aseprite|atlas|zip|sbsar))["”]',
            prompt,
            re.IGNORECASE,
        )

        # 3. 兜底策略: Regex 规则提取 (Heuristic)
        if skill.metadata.name == "export_godot_project":
            params["preset_name"] = "Windows Desktop" if any(k in prompt.lower() for k in ["win", "windows"]) else "Web"
            
        elif skill.metadata.name == "generate_movement_script":
            params["is_top_down"] = any(k in prompt for k in ["俯视", "top-down", "2.5d"])
            speed_match = re.search(r'(?:速度|speed)\s*[:：=]?\s*(\d+)', prompt)
            if speed_match: params["speed"] = float(speed_match.group(1))
            
        elif skill.metadata.name == "audit_godot_resources":
            params["deep_scan"] = "深度" in prompt or "全量" in prompt
            params["check_naming"] = "命名" in prompt or "规范" in prompt

        elif skill.metadata.name == "manage_level_workflow":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["审计", "检查", "验收", "校验"]):
                params["action"] = "audit"
            elif any(keyword in lowered for keyword in ["snapshot", "快照"]):
                params["action"] = "snapshot"
            elif any(keyword in prompt for keyword in ["diff", "对比"]):
                params["action"] = "diff"
            elif "预览" in prompt:
                params["action"] = "preview"
            else:
                params["action"] = "template"

            level_name_match = re.search(r'(?:关卡|level)\s*(?:名为|叫作|为)?\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if level_name_match:
                params["level_name"] = level_name_match.group(1)

            if any(keyword in lowered for keyword in ["boss", "首领", "boss关"]):
                params["level_type"] = "boss"
            elif any(keyword in lowered for keyword in ["hub", "主城", "据点", "大厅"]):
                params["level_type"] = "hub"
            elif any(keyword in lowered for keyword in ["puzzle", "解谜", "机关"]):
                params["level_type"] = "puzzle"
            else:
                params["level_type"] = "combat"

            params["root_type"] = "Node3D" if any(keyword in lowered for keyword in ["3d", "node3d"]) else "Node2D"

            if tscn_match:
                params["scene_path"] = tscn_match.group(0)
            if table_path_match and table_path_match.group(0).lower().endswith(".json"):
                params["manifest_path"] = table_path_match.group(0)

        elif skill.metadata.name == "create_godot_scene":
            name_match = re.search(r'名为\s*(\w+)', prompt)
            params["scene_name"] = name_match.group(1) if name_match else "NewScene"
            params["root_type"] = "Node3D" if "3D" in prompt else "Node2D"
            if "UI" in prompt or "界面" in prompt: params["root_type"] = "Control"

        elif skill.metadata.name == "inject_godot_node":
            type_match = re.search(r'添加(?:一个)?\s*(?:名为\s*\w+\s*的\s*)?(\w+)\s*节点', prompt)
            name_match = re.search(r'名为\s*(\w+)', prompt)
            if type_match: params["node_type"] = type_match.group(1)
            if name_match: params["node_name"] = name_match.group(1)
            parent_match = re.search(r'(?:在|下)\s*([\w/]+)\s*节点', prompt)
            if parent_match and parent_match.group(1) not in {"当前", "选中"}:
                params["parent_path"] = parent_match.group(1)

        elif skill.metadata.name == "attach_script_to_node":
            # 优先找“中的”之后的节点名
            node_name_match = re.search(r'(?:中的|名为|给)\s*(\w+)\s*节点', prompt)
            if node_name_match: params["target_node_path"] = node_name_match.group(1)

        elif skill.metadata.name == "manage_input_mapping":
            action_match = re.search(
                r'(?:动作|action)\s*([A-Za-z_][A-Za-z0-9_]*)|绑定\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:到|至)?\s*按键',
                prompt,
                re.IGNORECASE,
            )
            key_match = re.search(
                r'(?:按键|键位|key)\s*([A-Za-z_][A-Za-z0-9_]*)|绑定到(?:按键)?\s*([A-Za-z_][A-Za-z0-9_]*)',
                prompt,
                re.IGNORECASE,
            )
            if action_match:
                params["action_name"] = next(group for group in action_match.groups() if group)
            if key_match:
                params["key_code"] = next(group for group in key_match.groups() if group)

        elif skill.metadata.name == "instantiate_scene_prefab":
            if tscn_match:
                params["instance_scene_path"] = tscn_match.group(0)
            num_match = re.search(r'(\d+)\s*(?:个|只|位)', prompt)
            if num_match: params["count"] = int(num_match.group(1))
            name_match = re.search(r'名为\s*(\w+)', prompt)
            if name_match: params["instance_name"] = name_match.group(1)

        elif skill.metadata.name == "configure_physics_collision":
            # 优先找“中的”之后的节点名
            node_name_match = re.search(r'(?:中的|名为|给)\s*(\w+)\s*(?:节点|精灵)?', prompt)
            if node_name_match: params["target_node_path"] = node_name_match.group(1)
            
            if "玩家" in prompt or "控制" in prompt: params["body_type"] = "CharacterBody3D"
            elif "受力" in prompt or "重力" in prompt: params["body_type"] = "RigidBody3D"
            if "圆" in prompt: params["shape_type"] = "SphereShape3D"

        elif skill.metadata.name == "setup_3d_environment":
            params["add_ground"] = "地面" in prompt or "地板" in prompt
            params["add_camera"] = "相机" in prompt or "摄像机" in prompt
            params["add_light"] = "灯光" in prompt or "光照" in prompt

        elif skill.metadata.name == "inject_3d_primitive":
            if "立方体" in prompt or "方块" in prompt or "box" in prompt: params["shape_type"] = "Box"
            elif "球" in prompt or "sphere" in prompt: params["shape_type"] = "Sphere"
            elif "胶囊" in prompt or "capsule" in prompt: params["shape_type"] = "Capsule"
            else: params["shape_type"] = "Box"
            name_match = re.search(r'(?:名为|叫作)\s*(\w+)', prompt)
            if name_match: params["node_name"] = name_match.group(1)
            pos_match = re.search(r'位置(?:在|为)?\s*\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?', prompt)
            if pos_match: params["position"] = [float(pos_match.group(1)), float(pos_match.group(2)), float(pos_match.group(3))]

        elif skill.metadata.name == "smoke_test_scene":
            pass

        elif skill.metadata.name == "auto_debug_runtime":
            params["max_retries"] = 1 if "修复" in prompt or "heal" in prompt else 0

        elif skill.metadata.name == "e2e_test_scene":
            params["screenshot"] = any(k in prompt for k in ["截图", "快照", "screenshot"])
            actions = []
            if "向右" in prompt: actions.append("ui_right")
            if "向左" in prompt: actions.append("ui_left")
            if "跳" in prompt or "交互" in prompt: actions.append("ui_accept")
            params["actions"] = actions
            node_match = re.search(r'(?:断言|验证|检查)节点\s*([A-Za-z0-9_/]+)', prompt)
            if node_match: params["assert_nodes"] = [node_match.group(1)]

        elif skill.metadata.name == "init_game_blueprint":
            genre_match = re.search(r'(?:制作|创建|设定为)\s*(\w+)\s*(?:游戏|项目)', prompt)
            params["game_genre"] = genre_match.group(1) if genre_match else "3D"
            params["naming_style"] = "snake_case"
            params["use_signal_bus"] = "总线" in prompt or "解耦" in prompt

        elif skill.metadata.name == "manage_gameplay_template":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["应用", "接入", "落地", "初始化系统", "写入蓝图"]):
                params["action"] = "apply"
            else:
                params["action"] = "preview"

            if any(keyword in lowered for keyword in ["platformer", "跳台", "平台跳跃"]):
                params["template_id"] = "platformer"
            elif any(keyword in lowered for keyword in ["topdown", "top-down", "俯视"]):
                params["template_id"] = "topdown_action"
            elif any(keyword in lowered for keyword in ["arpg", "动作rpg", "action rpg"]):
                params["template_id"] = "arpg"
            elif any(keyword in lowered for keyword in ["roguelike", "rogue", "肉鸽"]):
                params["template_id"] = "roguelike"
            elif any(keyword in lowered for keyword in ["tower defense", "td", "塔防"]):
                params["template_id"] = "tower_defense"
            elif any(keyword in lowered for keyword in ["visual novel", "vn", "视觉小说"]):
                params["template_id"] = "visual_novel"
            elif any(keyword in lowered for keyword in ["survival", "crafting", "生存", "建造"]):
                params["template_id"] = "survival_crafting"

        elif skill.metadata.name == "plan_game_feature":
            name_match = re.search(r'(?:规划|添加|新增)功能\s*(\w+)', prompt)
            params["feature_name"] = name_match.group(1) if name_match else "NewFeature"
            params["description"] = prompt
            params["dependencies"] = []

        elif skill.metadata.name == "apply_design_pattern":
            name_match = re.search(r'(?:应用|使用|加载)(?:设计)?模式\s*(\w+)', prompt)
            params["pattern_name"] = name_match.group(1) if name_match else "HealthSystem"
            overrides = {}
            speed_match = re.search(r'(?:速度|speed)(?:设为|改为|为)?\s*(\d+)', prompt)
            if speed_match: overrides["speed"] = float(speed_match.group(1))
            name_override = re.search(r'(?:名为|叫作)\s*(\w+)', prompt)
            if name_override: overrides["scene_name"] = name_override.group(1)
            params["overrides"] = overrides

        elif skill.metadata.name == "quick_capture_scene":
            pass

        elif skill.metadata.name == "define_game_flow":
            from_match = re.search(r'(?:从|在)\s*(\w+)\s*(?:中|场景)', prompt)
            to_match = re.search(r'(?:进入|跳转到|切换到)\s*(\w+)', prompt)
            trigger_match = re.search(r'(?:触发|通过|当)\s*(\w+)', prompt)
            params["from_scene"] = from_match.group(1) if from_match else "Unknown"
            params["to_scene"] = to_match.group(1) if to_match else "Unknown"
            params["trigger"] = trigger_match.group(1) if trigger_match else "event"

        elif skill.metadata.name == "manage_signal_bus":
            sig_match = re.search(r'(?:注册|添加|新增)(?:全局)?信号\s*(\w+)', prompt)
            params["signal_name"] = sig_match.group(1) if sig_match else "generic_signal"
            arg_match = re.search(r'(?:带有|携带)参数\s*([\w,\s]+)', prompt)
            if arg_match: params["arguments"] = [a.strip() for a in arg_match.group(1).split(',')]

        elif skill.metadata.name == "manage_audio_resource":
            name_match = re.search(r'(?:名为|叫作)\s*(\w+)', prompt)
            params["audio_path"] = audio_match.group(0) if audio_match else "res://assets/audio/placeholder.ogg"
            params["audio_name"] = name_match.group(1) if name_match else "AudioPlayer"
            params["is_2d"] = "2D" in prompt or "位置" in prompt
            params["autoplay"] = "自动" in prompt or "循环" in prompt or "autoplay" in prompt.lower()

        elif skill.metadata.name == "manage_game_data_tables":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化"]):
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["预览", "diff", "对比"]):
                params["action"] = "preview"
            elif any(keyword in prompt for keyword in ["导入", "应用", "写入", "落盘"]):
                params["action"] = "apply"
            else:
                params["action"] = "validate"

            if any(keyword in prompt for keyword in ["任务表", "quest"]):
                params["table_type"] = "quest"
            elif any(keyword in prompt for keyword in ["敌人", "enemy", "数值"]):
                params["table_type"] = "enemy"
            elif any(keyword in prompt for keyword in ["掉落", "loot"]):
                params["table_type"] = "loot"
            elif any(keyword in prompt for keyword in ["本地化", "翻译", "localization"]):
                params["table_type"] = "localization"
            else:
                params["table_type"] = "dialogue" if any(keyword in prompt for keyword in ["对白", "对话", "dialogue"]) else "quest"

            if table_path_match:
                params["table_path"] = table_path_match.group(0)

        elif skill.metadata.name == "analyze_game_balance":
            lowered = prompt.lower()
            include_tables: List[str] = []
            if any(keyword in prompt for keyword in ["敌人", "enemy", "战斗", "强度"]):
                include_tables.append("enemy")
            if any(keyword in prompt for keyword in ["任务", "quest", "奖励"]):
                include_tables.append("quest")
            if any(keyword in prompt for keyword in ["掉落", "loot", "经济"]):
                include_tables.append("loot")
            params["include_tables"] = include_tables or ["enemy", "quest", "loot"]

            if table_path_match:
                normalized_table_path = table_path_match.group(0)
                if "enemy" in lowered or "敌人" in prompt:
                    params["enemy_table_path"] = normalized_table_path
                elif "loot" in lowered or "掉落" in prompt:
                    params["loot_table_path"] = normalized_table_path
                elif "quest" in lowered or "任务" in prompt:
                    params["quest_table_path"] = normalized_table_path

        elif skill.metadata.name == "manage_game_telemetry":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化"]):
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["导入", "写入", "回流", "保存"]):
                params["action"] = "apply"
            elif any(keyword in prompt for keyword in ["校验", "验证", "检查"]):
                params["action"] = "validate"
            else:
                params["action"] = "analyze"

            if table_path_match and table_path_match.group(0).lower().endswith(".json"):
                params["catalog_path"] = table_path_match.group(0)

            session_match = re.search(r'(?:res://)?[\w/\.-]+\.(?:jsonl|json)', prompt, re.IGNORECASE)
            if session_match and "catalog_path" not in params:
                params["session_path"] = session_match.group(0)
            elif session_match and params.get("catalog_path") and session_match.group(0) != params["catalog_path"]:
                params["session_path"] = session_match.group(0)

        elif skill.metadata.name == "manage_game_performance":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["基线", "baseline", "保存性能"]):
                params["action"] = "baseline"
            elif any(keyword in prompt for keyword in ["校验", "验证", "检查", "budget"]):
                params["action"] = "validate"
            else:
                params["action"] = "analyze"

            if tscn_match:
                params["scene_path"] = tscn_match.group(0)

            profile_matches = re.findall(r'(?:tests/baselines/performance|logs/test_artifacts|[\w/\.-]+)\.json', prompt, re.IGNORECASE)
            if profile_matches:
                first_path = profile_matches[0]
                if "baseline" in lowered or "基线" in prompt:
                    params["baseline_path"] = first_path
                else:
                    params["profile_path"] = first_path
                if len(profile_matches) > 1:
                    params["baseline_path"] = profile_matches[0]
                    params["profile_path"] = profile_matches[1]

            metric_patterns = {
                "scene_load_ms": r'(?:load|加载|scene[_\s-]*load)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*ms',
                "fps": r'(?:fps|帧率)\s*[:：=]?\s*(\d+(?:\.\d+)?)',
                "memory_peak_mb": r'(?:memory|内存峰值|内存)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mb|m)',
                "draw_call_count": r'(?:draw\s*call|drawcall|draw_call|绘制调用)\s*[:：=]?\s*(\d+(?:\.\d+)?)',
                "node_count": r'(?:node\s*count|node_count|节点数)\s*[:：=]?\s*(\d+(?:\.\d+)?)',
                "texture_memory_mb": r'(?:texture|纹理(?:内存|预算)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mb|m)',
                "frame_spike_ms": r'(?:frame\s*spike|尖峰|卡顿峰值)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*ms',
            }
            profile_metrics = {}
            for metric_name, pattern in metric_patterns.items():
                metric_match = re.search(pattern, prompt, re.IGNORECASE)
                if metric_match:
                    profile_metrics[metric_name] = float(metric_match.group(1))
            if profile_metrics:
                params["profile_metrics"] = profile_metrics

        elif skill.metadata.name == "manage_art_asset_pipeline":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化"]):
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["预览", "diff", "对比"]):
                params["action"] = "preview"
            elif any(keyword in prompt for keyword in ["导入", "应用", "入库", "拷贝", "同步"]):
                params["action"] = "apply"
            else:
                params["action"] = "validate"

            if any(keyword in lowered for keyword in ["blender", "gltf", "glb", "模型", "mesh", "3d asset"]):
                params["asset_type"] = "model"
                params["source_tool"] = "blender" if "blender" in lowered else "gltf"
            elif any(keyword in lowered for keyword in ["aseprite", "ase", "aseprite sheet", "aseprite atlas"]):
                params["asset_type"] = "aseprite"
                params["source_tool"] = "aseprite"
            elif any(keyword in lowered for keyword in ["spine", "skeleton", "骨骼动画", "骨骼资源"]):
                params["asset_type"] = "spine"
                params["source_tool"] = "spine"
            elif any(keyword in lowered for keyword in ["substance", "sbsar", "pbr set", "材质集", "贴图集"]):
                params["asset_type"] = "substance"
                params["source_tool"] = "substance"
            elif any(keyword in lowered for keyword in ["outsource", "vendor package", "delivery zip", "外包", "交付包"]):
                params["asset_type"] = "outsource"
                params["source_tool"] = "outsource_delivery"
            elif any(keyword in lowered for keyword in ["ui", "图标", "界面资源", "界面图"]):
                params["asset_type"] = "ui"
            elif any(keyword in lowered for keyword in ["spritesheet", "sprite sheet", "精灵表", "帧图"]):
                params["asset_type"] = "spritesheet"
            elif any(keyword in lowered for keyword in ["material", "材质"]):
                params["asset_type"] = "material"
            elif any(keyword in lowered for keyword in ["vfx", "特效", "粒子资源"]):
                params["asset_type"] = "vfx"
            else:
                params["asset_type"] = "texture"

            asset_match = quoted_asset_path_match or asset_path_match
            if asset_match:
                params["source_path"] = asset_match.group(1) if quoted_asset_path_match else asset_match.group(0)

            target_match = re.search(
                r'(?:到|写入|保存到|目标路径)\s*(res://[\w/\.-]+\.[A-Za-z0-9]+)',
                prompt,
                re.IGNORECASE,
            )
            if target_match:
                params["target_path"] = target_match.group(1)

            asset_id_match = re.search(r'(?:资产ID|asset_id|名为|叫作)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if asset_id_match:
                params["asset_id"] = asset_id_match.group(1)

            size_match = re.search(r'(\d{2,5})\s*[xX]\s*(\d{2,5})', prompt)
            if size_match:
                params["width"] = int(size_match.group(1))
                params["height"] = int(size_match.group(2))

            frame_match = re.search(r'(?:帧|frame)(?:尺寸|大小)?\s*(\d{1,5})\s*[xX]\s*(\d{1,5})', prompt, re.IGNORECASE)
            if frame_match:
                params["frame_width"] = int(frame_match.group(1))
                params["frame_height"] = int(frame_match.group(2))

            memory_match = re.search(r'(?:预算|内存)\s*(\d+(?:\.\d+)?)\s*(?:mb|m)', prompt, re.IGNORECASE)
            if memory_match:
                params["estimated_memory_mb"] = float(memory_match.group(1))

            lod_match = re.search(r'(?:lod|LOD)\s*(\d+)', prompt)
            if lod_match:
                params["lod_count"] = int(lod_match.group(1))

            texture_set_match = re.search(r'(?:texture[_ ]?set|贴图集)\s*[:：=]?\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if texture_set_match:
                params["texture_set"] = texture_set_match.group(1)

            version_match = re.search(r'(?:version|版本)\s*[:：=]?\s*([A-Za-z0-9._-]+)', prompt, re.IGNORECASE)
            if version_match:
                params["package_version"] = version_match.group(1)

            license_match = re.search(r'(?:license|授权)\s*[:：=]?\s*([A-Za-z0-9._-]+)', prompt, re.IGNORECASE)
            if license_match:
                params["license_name"] = license_match.group(1)

        elif skill.metadata.name == "manage_presentation_pipeline":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化"]):
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["预览", "diff", "对比"]):
                params["action"] = "preview"
            elif any(keyword in prompt for keyword in ["导入", "应用", "写入", "落盘", "生成"]):
                params["action"] = "apply"
            else:
                params["action"] = "validate"

            if any(keyword in lowered for keyword in ["animationtree", "animation tree", "animationplayer", "animation player", "状态动画", "动画树"]):
                params["presentation_type"] = "animation"
            elif any(keyword in lowered for keyword in ["shader", "shadermaterial", "shader material", "着色器"]):
                params["presentation_type"] = "shader"
            elif any(keyword in lowered for keyword in ["audio bus", "audio event", "音频总线", "音频事件", "bgm", "sfx"]):
                params["presentation_type"] = "audio"
            elif any(keyword in lowered for keyword in ["vfx profile", "particle profile", "粒子模板", "粒子配置"]):
                params["presentation_type"] = "vfx"

            profile_match = re.search(r'(?:profile|模板|名为|叫作)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if profile_match:
                params["profile_id"] = profile_match.group(1)

            if any(keyword in lowered for keyword in ["animationtree", "animation tree", "动画树"]):
                params["animation_mode"] = "animation_tree"
            elif any(keyword in lowered for keyword in ["状态动画", "state machine", "stateful tween"]):
                params["animation_mode"] = "tween_state"
            elif any(keyword in lowered for keyword in ["animationplayer", "animation player"]):
                params["animation_mode"] = "animation_player"

            if any(keyword in lowered for keyword in ["gpu 3d", "gpuparticles3d", "3d 粒子"]):
                params["particle_mode"] = "gpu_particles_3d"
            elif any(keyword in lowered for keyword in ["cpu 2d", "cpuparticles2d"]):
                params["particle_mode"] = "cpu_particles_2d"
            elif any(keyword in lowered for keyword in ["cpu 3d", "cpuparticles3d"]):
                params["particle_mode"] = "cpu_particles_3d"
            elif any(keyword in lowered for keyword in ["gpu 2d", "gpuparticles2d", "粒子"]):
                params["particle_mode"] = "gpu_particles_2d"

            if any(keyword in lowered for keyword in ["canvas_item", "canvas item", "2d shader"]):
                params["shader_mode"] = "canvas_item"
            elif any(keyword in lowered for keyword in ["spatial", "3d shader"]):
                params["shader_mode"] = "spatial"
            elif "particles shader" in lowered:
                params["shader_mode"] = "particles"

            if any(keyword in lowered for keyword in ["bgm", "背景音乐"]):
                params["audio_role"] = "bgm"
            elif any(keyword in lowered for keyword in ["ui 音效", "ui sfx", "ui音效"]):
                params["audio_role"] = "ui"
            elif any(keyword in lowered for keyword in ["ambience", "环境音"]):
                params["audio_role"] = "ambience"
            elif any(keyword in lowered for keyword in ["sfx", "音效"]):
                params["audio_role"] = "sfx"

            event_match = re.search(r'(?:event|事件)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if event_match:
                params["event_name"] = event_match.group(1)

            bus_match = re.search(r'(?:bus|总线)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if bus_match:
                params["bus_name"] = bus_match.group(1)

            amount_match = re.search(r'(?:粒子|amount)\s*[:：=]?\s*(\d+)', prompt, re.IGNORECASE)
            if amount_match:
                params["amount"] = int(amount_match.group(1))

            duration_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:秒|s)', prompt, re.IGNORECASE)
            if duration_match:
                params["lifetime_seconds"] = float(duration_match.group(1))

            color_match = re.search(r'(#[0-9a-fA-F]{6})', prompt)
            if color_match:
                params["color_hex"] = color_match.group(1)

        elif skill.metadata.name == "manage_liveops_pipeline":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化"]):
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["预览", "diff", "对比"]):
                params["action"] = "preview"
            elif any(keyword in prompt for keyword in ["导入", "应用", "写入", "落盘", "发布"]):
                params["action"] = "apply"
            else:
                params["action"] = "validate"

            if any(keyword in lowered for keyword in ["experiment", "a/b", "ab test", "abtest", "实验", "试验", "灰度实验"]):
                params["liveops_type"] = "experiment_catalog"
            else:
                params["liveops_type"] = "remote_config"

            if table_path_match and table_path_match.group(0).lower().endswith(".json"):
                params["manifest_path"] = table_path_match.group(0)

            entry_match = re.search(r'(?:config|experiment|条目|名为|叫作|key)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if entry_match:
                params["entry_id"] = entry_match.group(1)

            owner_match = re.search(r'(?:owner|负责人)\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            if owner_match:
                params["owner"] = owner_match.group(1)

            rollout_match = re.search(r'(\d+(?:\.\d+)?)\s*%', prompt)
            if rollout_match:
                params["rollout_percentage"] = float(rollout_match.group(1))

            if any(keyword in lowered for keyword in ["bool", "boolean", "开关", "flag"]):
                params["value_type"] = "bool"
            elif any(keyword in lowered for keyword in ["float", "倍率", "系数"]):
                params["value_type"] = "float"
            elif any(keyword in lowered for keyword in ["int", "整数"]):
                params["value_type"] = "int"
            elif any(keyword in lowered for keyword in ["json", "对象", "配置对象"]):
                params["value_type"] = "json"
            elif any(keyword in lowered for keyword in ["string", "文本", "文案"]):
                params["value_type"] = "string"

            if any(keyword in lowered for keyword in ["running", "运行中", "上线实验"]):
                params["status"] = "running"
            elif any(keyword in lowered for keyword in ["paused", "暂停"]):
                params["status"] = "paused"
            elif any(keyword in lowered for keyword in ["completed", "结束"]):
                params["status"] = "completed"
            elif any(keyword in lowered for keyword in ["archived", "归档"]):
                params["status"] = "archived"
            elif "draft" in lowered or "草稿" in prompt:
                params["status"] = "draft"

        elif skill.metadata.name == "manage_platform_delivery":
            lowered = prompt.lower()
            if any(keyword in prompt for keyword in ["模板", "新建", "初始化", "基线"]) or "baseline" in lowered:
                params["action"] = "template"
            elif any(keyword in prompt for keyword in ["预览", "diff", "对比"]):
                params["action"] = "preview"
            elif any(keyword in prompt for keyword in ["导入", "应用", "写入", "落盘"]):
                params["action"] = "apply"
            else:
                params["action"] = "validate"

            if table_path_match and table_path_match.group(0).lower().endswith(".json"):
                params["manifest_path"] = table_path_match.group(0)

        elif skill.metadata.name == "run_scenario_chain_test":
            params["include_all"] = True

        elif skill.metadata.name == "wire_signal_connection":
            sig_match = re.search(r'信号\s*(\w+)', prompt)
            call_match = re.search(r'函数\s*(\w+)', prompt)
            if gd_match: params["target_script"] = gd_match.group(0)
            params["signal_name"] = sig_match.group(1) if sig_match else "generic_signal"
            params["callback_name"] = call_match.group(1) if call_match else f"_on_{params['signal_name']}"

        elif skill.metadata.name == "manage_blueprint_snapshots":
            if any(k in prompt for k in ["保存", "记录", "save"]):
                params["action"] = "save"
                label_match = re.search(r'(?:名为|标签为)\s*(\w+)', prompt)
                params["label"] = label_match.group(1) if label_match else "manual"
            elif any(k in prompt for k in ["列表", "查看", "list"]):
                params["action"] = "list"
            elif any(k in prompt for k in ["恢复", "回滚", "restore"]):
                params["action"] = "restore"
                id_match = re.search(r'snapshot_[\w\.]+', prompt)
                if id_match: params["snapshot_id"] = id_match.group(0)

        elif skill.metadata.name == "auto_layout_ui":
            params["root_name"] = "UILayout"
            params["layout_type"] = "VBoxContainer" if "垂直" in prompt or "列表" in prompt else "CenterContainer"
            elements = []
            if "开始" in prompt: elements.append({"type": "Button", "name": "StartButton", "text": "开始游戏"})
            if "设置" in prompt: elements.append({"type": "Button", "name": "OptionsButton", "text": "设置"})
            if "退出" in prompt: elements.append({"type": "Button", "name": "ExitButton", "text": "退出"})
            if "标题" in prompt: elements.append({"type": "Label", "name": "TitleLabel", "text": "我的游戏"})
            params["elements"] = elements

        elif skill.metadata.name == "apply_tween_animation":
            if gd_match:
                params["target_script"] = gd_match.group(0)
            if "淡入" in prompt or "fade" in prompt: params["animation_type"] = "fade_in"
            elif "缩放" in prompt or "scale" in prompt: params["animation_type"] = "scale_up"
            elif "弹跳" in prompt or "跳动" in prompt or "bounce" in prompt: params["animation_type"] = "bounce"
            elif "旋转" in prompt or "rotate" in prompt: params["animation_type"] = "rotate_loop"
            else: params["animation_type"] = "fade_in"
            duration_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:秒|s)', prompt)
            if duration_match: params["duration"] = float(duration_match.group(1))

        elif skill.metadata.name == "generate_dialogue_system":
            name_match = re.search(r'(?:对话系统|对话|dialogue)\s*(?:名为|叫作)?\s*([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE)
            params["dialogue_name"] = name_match.group(1) if name_match else "story_dialogue"
            params["auto_ui"] = not any(keyword in prompt for keyword in ["仅脚本", "不生成UI", "no ui"])
            quoted_lines = re.findall(r'["“](.+?)["”]', prompt)
            if quoted_lines:
                params["lines"] = [
                    {"character": "Narrator", "text": text, "options": []}
                    for text in quoted_lines
                ]
            else:
                params["lines"] = [
                    {"character": "Narrator", "text": prompt, "options": []},
                    {"character": "Narrator", "text": "继续。", "options": []},
                ]

        elif skill.metadata.name == "generate_ai_behavior":
            name_match = re.search(r'(?:为|给)\s*(\w+)\s*(?:生成|添加)', prompt)
            params["target_node_name"] = name_match.group(1) if name_match else "Enemy"
            state_match = re.search(r'包含\s*([\w、,，\s]+)\s*状态', prompt)
            if state_match:
                states_raw = re.split(r'[、,，\s]+', state_match.group(1))
                params["states"] = [s.strip() for s in states_raw if s.strip()]

        elif skill.metadata.name == "inject_vfx_particle":
            if "爆炸" in prompt or "explosion" in prompt: params["effect_type"] = "explosion"
            elif "烟雾" in prompt or "smoke" in prompt: params["effect_type"] = "smoke"
            elif "火焰" in prompt or "fire" in prompt: params["effect_type"] = "fire"
            elif "火花" in prompt or "spark" in prompt: params["effect_type"] = "sparks"
            else: params["effect_type"] = "explosion"
            name_match = re.search(r'(?:名为|叫作)\s*(\w+)', prompt)
            if name_match: params["node_name"] = name_match.group(1)

        elif skill.metadata.name == "set_ui_style":
            color_match = re.search(r'色调(?:为|设为)?\s*(#[0-9a-fA-F]{6})', prompt)
            radius_match = re.search(r'圆角(?:为|设为)?\s*(\d+)', prompt)
            font_match = re.search(r'字体(?:为|设为)?\s*(\d+)', prompt)
            if color_match: params["primary_color"] = color_match.group(1)
            if radius_match: params["corner_radius"] = int(radius_match.group(1))
            if font_match: params["font_size"] = int(font_match.group(1))

        elif skill.metadata.name == "self_heal_project":
            pass
            
        return params


class SkillRegistry:
    _instance = None
    _skills: Dict[str, Type[BaseSkill]] = {}
    _llm_client: Optional[LLMClient] = None
    _mapper: Optional[ParameterMapper] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SkillRegistry, cls).__new__(cls)
        return cls._instance

    @classmethod
    def set_llm_client(cls, llm_client: LLMClient):
        """配置并初始化语义映射器"""
        cls._llm_client = llm_client
        cls._mapper = ParameterMapper(llm_client)

    @classmethod
    def _get_mapper(cls) -> ParameterMapper:
        """延迟初始化 Mapper (离线兜底)"""
        if not cls._mapper:
            cls._mapper = ParameterMapper(cls._llm_client)
        return cls._mapper

    @classmethod
    def register(cls, skill_class: Type[BaseSkill]):
        """手动注册技能"""
        name = skill_class.metadata.name
        cls._skills[name] = skill_class
        return skill_class

    @classmethod
    def get_skill(cls, name: str, godot_cli: Any = None, index_service: Any = None) -> Optional[BaseSkill]:
        """获取技能实例"""
        skill_class = cls._skills.get(name)
        if skill_class:
            return skill_class(godot_cli, index_service)
        return None

    @classmethod
    def get_skill_with_params(cls, name: str, prompt: str, godot_cli: Any = None, index_service: Any = None) -> Optional[tuple[BaseSkill, Dict[str, Any]]]:
        """获取技能实例及其自动提取的参数"""
        skill = cls.get_skill(name, godot_cli, index_service)
        if skill:
            params = cls._get_mapper().map_params(prompt, skill)
            return skill, params
        return None

    @classmethod
    def list_skills(cls, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有已注册技能的元数据"""
        results = []
        for name, skill_class in cls._skills.items():
            meta = skill_class.metadata
            if category and meta.category != category:
                continue
            results.append(meta.model_dump())
        return results

    @classmethod
    def get_tool_definitions(cls, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取供 LLM 使用的工具定义"""
        results = []
        for name, skill_class in cls._skills.items():
            if category and skill_class.metadata.category != category:
                continue
            # 临时实例化以获取定义 (无需传参数)
            instance = skill_class()
            results.append(instance.get_tool_definition())
        return results
