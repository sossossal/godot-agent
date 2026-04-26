import re
from typing import List, Dict, Any, Optional, Union

class GodotSection:
    """代表 Godot 资源文件中的一个区块 [type key=value ...]"""
    def __init__(self, raw_header: str, section_type: str, attributes: Dict[str, str]):
        self.raw_header = raw_header
        self.type = section_type
        self.attributes = attributes
        self.properties: Dict[str, str] = {}
        self.lines: List[str] = [] # 存储区块内的原始行内容

class GodotStructEditor:
    """Godot 结构化资源编辑器 (.tscn / .tres / .import)
    职责: 结构化解析、精准字段修改、无损序列化
    """
    
    SECTION_RE = re.compile(r'^\[([a-z_]+)\s+(.*)\]$')
    ATTR_RE = re.compile(r'([a-z_]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s]+)')

    def __init__(self):
        self.header_section: Optional[GodotSection] = None
        self.sections: List[GodotSection] = []

    def load(self, content: str):
        """解析 Godot 资源文件内容"""
        self.sections = []
        lines = content.splitlines()
        current_section = None
        
        for line in lines:
            stripped = line.strip()
            if not stripped and current_section:
                current_section.lines.append(line)
                continue
                
            match = self.SECTION_RE.match(stripped)
            if match:
                s_type = match.group(1)
                s_attr_raw = match.group(2)
                attrs = dict(self.ATTR_RE.findall(s_attr_raw))
                
                current_section = GodotSection(line, s_type, attrs)
                if s_type in {"gd_scene", "gd_resource", "remap"}:
                    self.header_section = current_section
                else:
                    self.sections.append(current_section)
            elif current_section:
                # 解析属性行 key = value
                if "=" in line and not line.startswith(" "):
                    parts = line.split("=", 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    current_section.properties[key] = val
                current_section.lines.append(line)

    def find_sections(self, s_type: str, **filters) -> List[GodotSection]:
        """根据类型和属性过滤区块"""
        results = []
        for s in self.sections:
            if s.type == s_type:
                match = True
                for k, v in filters.items():
                    # 自动处理引号包裹的匹配
                    attr_val = s.attributes.get(k, "").strip('"')
                    if attr_val != str(v).strip('"'):
                        match = False
                        break
                if match:
                    results.append(s)
        return results

    def update_ext_resource_path(self, old_path: str, new_path: str) -> int:
        """更新外部资源引用路径"""
        count = 0
        for s in self.sections:
            if s.type == "ext_resource":
                path = s.attributes.get("path", "").strip('"')
                if path == old_path or f"res://{path}" == old_path or path == f"res://{new_path}":
                    s.attributes["path"] = f'"{new_path}"'
                    # 更新原始头字符串
                    s.raw_header = f'[ext_resource type={s.attributes.get("type")} path="{new_path}" id={s.attributes.get("id")}]'
                    count += 1
        return count

    def rename_node(self, old_name: str, new_name: str) -> int:
        """结构化重命名节点及更新 parent 引用"""
        count = 0
        for s in self.sections:
            if s.type == "node":
                # 1. 检查节点定义
                name = s.attributes.get("name", "").strip('"')
                if name == old_name:
                    s.attributes["name"] = f'"{new_name}"'
                    count += 1
                
                # 2. 检查 parent 引用
                parent = s.attributes.get("parent", "").strip('"')
                if parent == old_name:
                    s.attributes["parent"] = f'"{new_name}"'
                    count += 1
                elif parent.endswith("/" + old_name):
                    new_parent = parent[:-len(old_name)] + new_name
                    s.attributes["parent"] = f'"{new_parent}"'
                    count += 1
                    
                # 同步更新 raw_header (简化处理，实际应保留顺序)
                attr_str = " ".join([f'{k}={v}' for k, v in s.attributes.items()])
                s.raw_header = f'[node {attr_str}]'
        return count

    def serialize(self) -> str:
        """将结构化数据还原为文本"""
        output = []
        if self.header_section:
            output.append(self.header_section.raw_header)
            # 头区块通常没有 lines，直接加空行
            output.append("")
            
        for s in self.sections:
            output.append(s.raw_header)
            # properties 已经包含在 lines 中了，因为解析时没从 lines 里删掉
            # 如果修改了 properties，这里需要特殊处理。
            # 目前我们的 rename_node 主要改 attributes(header)，所以直接写 lines 即可。
            for line in s.lines:
                output.append(line)
                
        return "\n".join(output) + "\n"
