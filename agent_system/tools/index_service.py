import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .gdscript_ast import GDScriptAstParser


class ProjectIndexService:
    """Godot 项目索引服务 (语义中台核心)
    职责: 全局符号表维护、依赖图谱构建、跨文件引用分析
    """

    EXCLUDED_DIR_NAMES = {
        ".actions-runner",
        ".git",
        ".godot",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "addons",
        "logs",
        "node_modules",
        "pytest-cache-files",
        "venv",
    }
    EXCLUDED_DIR_PREFIXES = (
        "pytest-cache-files",
        "runtime-artifacts-",
    )

    EXT_RES_RE = re.compile(r'\[ext_resource\s+type="([^"]+)"\s+path="([^"]+)"\s+id="([^"]+)"')
    NODE_RE = re.compile(r'\[node\s+name="([^"]+)"\s+type="([^"]+)"(?:\s+parent="([^"]*)")?')
    NODE_SCRIPT_RE = re.compile(r'script\s*=\s*ExtResource\(\s*"([^"]+)"\s*\)')
    CONNECTION_RE = re.compile(r'\[connection\s+([^\]]+)\]')
    SECTION_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        self.cache_file = self.project_path / ".godot_agent_index.json"
        self.gdscript_parser = GDScriptAstParser()

        self.classes: Dict[str, Dict[str, Any]] = {}
        self.files: Dict[str, Dict[str, Any]] = {}
        self.scenes: Dict[str, Dict[str, Any]] = {}
        self.dependency_graph: Dict[str, Set[str]] = {}
        self.symbol_definitions: Dict[str, List[Dict[str, Any]]] = {}
        self.symbol_references: Dict[str, List[Dict[str, Any]]] = {}

        self.load_index()

    def rebuild(self, force: bool = False):
        sys.stderr.write(f"[Index] 正在扫描项目索引: {self.project_path}\n")
        start_time = time.time()

        found_files: List[Path] = []
        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]
            for filename in filenames:
                if filename.endswith((".gd", ".tscn", ".tres", ".res")):
                    found_files.append(Path(root) / filename)

        found_rel_paths = {path.relative_to(self.project_path).as_posix() for path in found_files}
        stale_paths = set(self.files) - found_rel_paths
        for rel_path in stale_paths:
            self.files.pop(rel_path, None)
            self.scenes.pop(rel_path, None)
        stale_scene_paths = set(self.scenes) - found_rel_paths
        for rel_path in stale_scene_paths:
            self.scenes.pop(rel_path, None)

        changed_count = 0
        for file_path in found_files:
            if self._scan_file(file_path, force):
                changed_count += 1

        if changed_count > 0 or stale_paths or stale_scene_paths or force:
            self._rebuild_symbol_maps()
            self._build_dependency_map()
            self.save_index()

        sys.stderr.write(
            f"[Index] 索引重建完成: 扫描 {len(found_files)} 文件, 更新 {changed_count} 项, "
            f"耗时 {time.time() - start_time:.2f}s\n"
        )

    def _scan_file(self, path: Path, force: bool) -> bool:
        rel_path = path.relative_to(self.project_path).as_posix()
        try:
            file_hash = self._get_file_hash(path)
            if not force and rel_path in self.files and self.files[rel_path].get("hash") == file_hash:
                return False

            data: Dict[str, Any] = {
                "hash": file_hash,
                "mtime": os.path.getmtime(path),
                "symbols": [],
                "refs": [],
                "deps": [],
                "type": path.suffix[1:],
            }
            content = path.read_text(encoding="utf-8", errors="ignore")

            if path.suffix == ".gd":
                self._parse_gdscript(rel_path, content, data)
            elif path.suffix == ".tscn":
                self._parse_scene(rel_path, content, data)
            else:
                self._parse_generic_resource(rel_path, content, data)

            self.files[rel_path] = data
            return True
        except Exception as exc:
            sys.stderr.write(f"[Index][Warn] 扫描文件失败 {rel_path}: {exc}\n")
            return False

    def _parse_gdscript(self, rel_path: str, content: str, data: Dict[str, Any]):
        ast = self.gdscript_parser.parse(content, rel_path)
        class_name = next(iter(ast.classes.keys()), None)

        for symbol in ast.symbols:
            entry = {
                "name": symbol.name,
                "type": symbol.symbol_type,
                "line": symbol.line,
                "column": symbol.column,
            }
            if symbol.base:
                entry["base"] = symbol.base
                data["deps"].append(symbol.base)
            if symbol.signature:
                entry["signature"] = symbol.signature
            if symbol.args:
                entry["args"] = list(symbol.args)
            data["symbols"].append(entry)

        for reference in ast.references:
            ref_entry = {
                "name": reference.name,
                "type": reference.symbol_type,
                "line": reference.line,
                "column": reference.column,
                "context": reference.context,
                "scope": reference.scope,
            }
            data["refs"].append(ref_entry)

        for match in re.finditer(r'res://([A-Za-z0-9_./\-]+)', content):
            dep = match.group(1)
            if dep != rel_path:
                data["deps"].append(dep)

        for symbol_name in ast.classes:
            info = ast.classes[symbol_name]
            self.classes[symbol_name] = {
                "path": f"res://{rel_path}",
                "base": info.get("base"),
                "signals": list(info.get("signals", [])),
                "methods": list(info.get("methods", [])),
                "line": info.get("line"),
            }

        data["class_name"] = class_name

    def _parse_scene(self, rel_path: str, content: str, data: Dict[str, Any]):
        ext_res_map: Dict[str, str] = {}
        for _type_name, path, res_id in self.EXT_RES_RE.findall(content):
            if path.startswith("res://"):
                clean_path = path.replace("res://", "")
                ext_res_map[res_id] = clean_path
                data["deps"].append(clean_path)

        nodes: List[Dict[str, Any]] = []
        node_sections = re.split(r'(\[node\s+)', content)[1:]
        for index in range(0, len(node_sections), 2):
            node_header = node_sections[index] + node_sections[index + 1]
            match = self.NODE_RE.search(node_header)
            if not match:
                continue
            node_data = {
                "name": match.group(1),
                "type": match.group(2),
                "parent": match.group(3),
            }
            script_match = self.NODE_SCRIPT_RE.search(node_header)
            if script_match:
                res_id = script_match.group(1)
                if res_id in ext_res_map:
                    node_data["script"] = ext_res_map[res_id]
                    data["refs"].append({
                        "name": ext_res_map[res_id],
                        "type": "脚本路径",
                        "line": content[: script_match.start(1)].count("\n") + 1,
                        "column": 1,
                        "context": "node_script",
                        "scope": None,
                    })
            nodes.append(node_data)

        for match in self.CONNECTION_RE.finditer(content):
            attrs = dict(self.SECTION_ATTR_RE.findall(match.group(1)))
            signal_name = attrs.get("signal")
            method_name = attrs.get("method")
            line_no = content[: match.start()].count("\n") + 1
            if signal_name:
                data["refs"].append({
                    "name": signal_name,
                    "type": "信号",
                    "line": line_no,
                    "column": 1,
                    "context": "scene_connection_signal",
                    "scope": None,
                })
            if method_name:
                data["refs"].append({
                    "name": method_name,
                    "type": "函数",
                    "line": line_no,
                    "column": 1,
                    "context": "scene_connection_method",
                    "scope": None,
                })

        self.scenes[rel_path] = {"nodes": nodes}

    def _parse_generic_resource(self, rel_path: str, content: str, data: Dict[str, Any]):
        for match in re.finditer(r'res://([A-Za-z0-9_./\-]+)', content):
            dep = match.group(1)
            if dep != rel_path:
                data["deps"].append(dep)

    def _rebuild_symbol_maps(self):
        self.symbol_definitions = {}
        self.symbol_references = {}
        self.classes = {}

        for rel_path, info in self.files.items():
            symbols = [symbol for symbol in info.get("symbols", []) if isinstance(symbol, dict)]
            refs = [reference for reference in info.get("refs", []) if isinstance(reference, dict)]

            for symbol in symbols:
                symbol_type = symbol.get("type")
                symbol_name = symbol.get("name")
                if not symbol_name:
                    continue
                key = self._symbol_key(symbol_type, symbol_name)
                entry = {
                    "path": rel_path,
                    "line": symbol.get("line"),
                    "column": symbol.get("column"),
                    "type": symbol_type,
                    "signature": symbol.get("signature"),
                }
                if symbol.get("base"):
                    entry["base"] = symbol.get("base")
                self.symbol_definitions.setdefault(key, []).append(entry)

            if info.get("class_name"):
                class_symbol = next(
                    (symbol for symbol in symbols if symbol.get("type") == "类" and symbol.get("name") == info["class_name"]),
                    None,
                )
                if class_symbol:
                    signal_names = [s["name"] for s in symbols if s.get("type") == "信号"]
                    methods = [
                        {
                            "name": s["name"],
                            "args": ", ".join(s.get("args", [])),
                            "line": s.get("line"),
                        }
                        for s in symbols
                        if s.get("type") == "函数"
                    ]
                    self.classes[info["class_name"]] = {
                        "path": f"res://{rel_path}",
                        "base": class_symbol.get("base"),
                        "signals": signal_names,
                        "methods": methods,
                        "line": class_symbol.get("line"),
                    }

            for reference in refs:
                ref_type = reference.get("type")
                ref_name = reference.get("name")
                if not ref_name:
                    continue
                key = self._symbol_key(ref_type, ref_name)
                self.symbol_references.setdefault(key, []).append({
                    "path": rel_path,
                    "line": reference.get("line"),
                    "column": reference.get("column"),
                    "type": ref_type,
                    "context": reference.get("context"),
                    "scope": reference.get("scope"),
                })

    def _build_dependency_map(self):
        self.dependency_graph = {}
        for rel_path, info in self.files.items():
            for dep in set(info.get("deps", [])):
                self.dependency_graph.setdefault(dep, set()).add(rel_path)

    def _symbol_key(self, symbol_type: Optional[str], symbol_name: str) -> str:
        return f"{symbol_type or '*'}::{symbol_name}"

    def find_symbol_references(
        self,
        symbol_name: str,
        symbol_type: Optional[str] = None,
        defining_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        keys = [self._symbol_key(symbol_type, symbol_name)] if symbol_type else [
            self._symbol_key("类", symbol_name),
            self._symbol_key("函数", symbol_name),
            self._symbol_key("信号", symbol_name),
            self._symbol_key("*", symbol_name),
        ]

        references: List[Dict[str, Any]] = []
        for key in keys:
            references.extend(self.symbol_references.get(key, []))

        if defining_path:
            normalized_path = defining_path.replace("res://", "").replace("\\", "/")
            references = [ref for ref in references if ref.get("path") != normalized_path]

        unique_refs: Dict[Tuple[str, int, int, str], Dict[str, Any]] = {}
        for ref in references:
            dedupe_key = (
                ref.get("path", ""),
                int(ref.get("line") or 0),
                int(ref.get("column") or 0),
                ref.get("context", ""),
            )
            unique_refs[dedupe_key] = ref
        return sorted(unique_refs.values(), key=lambda item: (item.get("path", ""), item.get("line", 0), item.get("column", 0)))

    def get_symbol_impact(
        self,
        symbol_name: str,
        symbol_type: Optional[str] = None,
        defining_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        references = self.find_symbol_references(symbol_name, symbol_type=symbol_type, defining_path=defining_path)
        impacted_files = sorted({ref["path"] for ref in references})
        return {
            "symbol_name": symbol_name,
            "symbol_type": symbol_type,
            "reference_count": len(references),
            "impacted_files": impacted_files,
            "references": references,
        }

    def get_class_hierarchy(self, class_name: str) -> List[str]:
        hierarchy = [class_name]
        current = class_name
        while current in self.classes and self.classes[current].get("base"):
            base = self.classes[current]["base"]
            hierarchy.append(base)
            current = base
        return hierarchy

    def get_impact_scope(self, rel_path: str) -> List[str]:
        return list(self.dependency_graph.get(rel_path, []))

    def search_class(self, name: str) -> Optional[Dict[str, Any]]:
        return self.classes.get(name)

    def _get_file_hash(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _should_skip_dir(self, dirname: str) -> bool:
        return dirname in self.EXCLUDED_DIR_NAMES or any(
            dirname.startswith(prefix) for prefix in self.EXCLUDED_DIR_PREFIXES
        )

    def _is_ignored_rel_path(self, rel_path: str) -> bool:
        parts = Path(rel_path).parts
        return any(self._should_skip_dir(part) for part in parts)

    def save_index(self):
        try:
            serializable_graph = {key: list(value) for key, value in self.dependency_graph.items()}
            data = {
                "classes": self.classes,
                "files": self.files,
                "scenes": self.scenes,
                "graph": serializable_graph,
                "symbol_definitions": self.symbol_definitions,
                "symbol_references": self.symbol_references,
                "updated_at": time.time(),
            }
            self.cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"[Index][Error] 保存索引失败: {exc}\n")

    def load_index(self):
        if not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.classes = data.get("classes", {})
            self.files = data.get("files", {})
            self.scenes = data.get("scenes", {})
            graph_data = data.get("graph", {})
            self.dependency_graph = {key: set(value) for key, value in graph_data.items()}
            self.symbol_definitions = data.get("symbol_definitions", {})
            self.symbol_references = data.get("symbol_references", {})
            self._sanitize_loaded_files()
            self._sanitize_loaded_scenes()
        except Exception:
            pass

    def _sanitize_loaded_files(self):
        sanitized: Dict[str, Dict[str, Any]] = {}
        for rel_path, info in self.files.items():
            if not isinstance(info, dict):
                continue
            if self._is_ignored_rel_path(rel_path):
                continue

            symbols = info.get("symbols", [])
            refs = info.get("refs", [])
            deps = info.get("deps", [])
            needs_rescan = any(not isinstance(symbol, dict) for symbol in symbols) or any(
                not isinstance(reference, dict) for reference in refs
            )

            normalized = dict(info)
            normalized["symbols"] = [symbol for symbol in symbols if isinstance(symbol, dict)]
            normalized["refs"] = [reference for reference in refs if isinstance(reference, dict)]
            normalized["deps"] = [dep for dep in deps if isinstance(dep, str)]

            if needs_rescan:
                normalized["hash"] = None

            sanitized[rel_path] = normalized

        self.files = sanitized

    def _sanitize_loaded_scenes(self):
        self.scenes = {
            rel_path: info
            for rel_path, info in self.scenes.items()
            if isinstance(info, dict) and not self._is_ignored_rel_path(rel_path)
        }
