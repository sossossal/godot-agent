import os
from pathlib import Path
from typing import Optional

class TemplateManager:
    """模板管理器, 支持内置模板和项目级覆盖"""
    
    def __init__(self, project_path: Optional[str] = None):
        self.project_path = project_path
        self.builtin_dir = Path(__file__).parent.parent / "templates"

    def get_template_content(self, category: str, name: str) -> Optional[str]:
        """
        获取模板内容, 优先查找项目路径下的覆盖模板
        查找顺序: 
        1. {project_path}/agent_templates/{category}/{name}
        2. {builtin_dir}/{category}/{name}
        """
        # 1. 尝试查找项目级覆盖
        if self.project_path:
            override_path = Path(self.project_path) / "agent_templates" / category / name
            if override_path.exists() and override_path.is_file():
                try:
                    return override_path.read_text(encoding="utf-8")
                except Exception:
                    pass
        
        # 2. 尝试查找内置模板
        builtin_path = self.builtin_dir / category / name
        if builtin_path.exists() and builtin_path.is_file():
            try:
                return builtin_path.read_text(encoding="utf-8")
            except Exception:
                pass
                
        return None
