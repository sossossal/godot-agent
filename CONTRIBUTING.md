# 贡献指南

感谢您对 Godot 多角色 Agent 系统的关注!我们欢迎各种形式的贡献。

## 如何贡献

### 报告 Bug
如果您发现了 Bug,请提交一个 Issue,并附上详细的复现步骤和环境信息。

### 提交代码
1. Fork 本仓库
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 开发流程
1. 安装依赖: `pip install -r requirements.txt`
2. 运行测试: `pytest` 或 `python tests/test_agent.py`
3. 遵循现有的代码风格和注释规范

## 核心准则
- 保持角色职责单一
- 确保所有新功能都有相应的测试用例
- 文档与代码同步更新

## 角色扩展
如果您想添加新角色:
1. 在 `agent_system/roles/` 下创建新类,继承 `BaseRole`
2. 在 `agent_system/router.py` 中注册新角色
3. 在 `config.yaml` 中添加角色的关键词和优先级

## 许可证
通过提交 Pull Request,您同意您的贡献将基于 MIT 许可证授权。
