from .registry import SkillRegistry
from .code.movement_skill import GenerateMovementSkill
from .code.signal_bus_skill import SignalBusSkill
from .code.wiring_skill import SignalWiringSkill
from .code.animation_skill import TweenAnimationSkill
from .code.ai_skill import AIBehaviorSkill
from .code.dialogue_skill import DialogueSystemSkill
from .resource.export_skill import ExportProjectSkill
from .resource.audit_skill import AuditResourceSkill
from .resource.audio_skill import AudioManagementSkill
from .resource.data_table_skill import DataTablePipelineSkill
from .resource.balance_analysis_skill import BalanceAnalysisSkill
from .resource.telemetry_skill import TelemetryPipelineSkill
from .resource.performance_skill import PerformancePipelineSkill
from .resource.art_asset_skill import ArtAssetPipelineSkill
from .resource.presentation_skill import PresentationPipelineSkill
from .resource.liveops_skill import LiveOpsPipelineSkill
from .resource.platform_delivery_skill import PlatformDeliverySkill
from .test.smoke_skill import SmokeTestSkill
from .test.e2e_skill import E2ETestSkill
from .test.capture_skill import QuickCaptureSkill
from .test.chain_test_skill import ScenarioChainTestSkill
from .test.logic_audit_skill import LogicAuditSkill
from .test.debug_skill import AutoDebugSkill
from .dev.create_scene_skill import CreateSceneSkill
from .dev.level_workflow_skill import LevelWorkflowSkill
from .dev.inject_node_skill import InjectNodeSkill
from .dev.ui_layout_skill import UILayoutSkill
from .dev.vfx_skill import ParticleEffectSkill
from .dev.input_skill import InputMappingSkill
from .dev.instantiate_skill import InstantiateSkill
from .dev.physics_skill import PhysicsConfigSkill
from .dev.setup_3d_skill import Setup3DEnvironmentSkill
from .dev.vfx_3d_skill import Inject3DPrimitiveSkill
from .dev.attach_script_skill import AttachScriptSkill
from .architect.init_skill import InitializeProjectSkill
from .architect.gameplay_template_skill import GameplayTemplateSkill
from .architect.plan_skill import PlanFeatureSkill
from .architect.audit_project_skill import AuditProjectSkill
from .architect.apply_pattern_skill import ApplyPatternSkill
from .architect.flow_skill import DefineGameFlowSkill
from .architect.snapshot_skill import BlueprintSnapshotSkill
from .architect.export_doc_skill import ExportBlueprintSkill
from .architect.style_skill import SetUIStyleSkill
from .architect.self_heal_skill import SelfHealSkill

# 自动注册
SkillRegistry.register(GenerateMovementSkill)
SkillRegistry.register(SignalBusSkill)
SkillRegistry.register(SignalWiringSkill)
SkillRegistry.register(TweenAnimationSkill)
SkillRegistry.register(AIBehaviorSkill)
SkillRegistry.register(DialogueSystemSkill)
SkillRegistry.register(ExportProjectSkill)
SkillRegistry.register(AuditResourceSkill)
SkillRegistry.register(AudioManagementSkill)
SkillRegistry.register(DataTablePipelineSkill)
SkillRegistry.register(BalanceAnalysisSkill)
SkillRegistry.register(TelemetryPipelineSkill)
SkillRegistry.register(PerformancePipelineSkill)
SkillRegistry.register(ArtAssetPipelineSkill)
SkillRegistry.register(PresentationPipelineSkill)
SkillRegistry.register(LiveOpsPipelineSkill)
SkillRegistry.register(PlatformDeliverySkill)
SkillRegistry.register(SmokeTestSkill)
SkillRegistry.register(E2ETestSkill)
SkillRegistry.register(QuickCaptureSkill)
SkillRegistry.register(ScenarioChainTestSkill)
SkillRegistry.register(LogicAuditSkill)
SkillRegistry.register(AutoDebugSkill)
SkillRegistry.register(CreateSceneSkill)
SkillRegistry.register(LevelWorkflowSkill)
SkillRegistry.register(InjectNodeSkill)
SkillRegistry.register(UILayoutSkill)
SkillRegistry.register(ParticleEffectSkill)
SkillRegistry.register(InputMappingSkill)
SkillRegistry.register(InstantiateSkill)
SkillRegistry.register(PhysicsConfigSkill)
SkillRegistry.register(Setup3DEnvironmentSkill)
SkillRegistry.register(Inject3DPrimitiveSkill)
SkillRegistry.register(AttachScriptSkill)
SkillRegistry.register(InitializeProjectSkill)
SkillRegistry.register(GameplayTemplateSkill)
SkillRegistry.register(PlanFeatureSkill)
SkillRegistry.register(AuditProjectSkill)
SkillRegistry.register(ApplyPatternSkill)
SkillRegistry.register(DefineGameFlowSkill)
SkillRegistry.register(BlueprintSnapshotSkill)
SkillRegistry.register(ExportBlueprintSkill)
SkillRegistry.register(SetUIStyleSkill)
SkillRegistry.register(SelfHealSkill)
