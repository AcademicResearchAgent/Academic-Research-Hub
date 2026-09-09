"""Local LaTeX project handlers. They never compile TeX or execute template files."""
from __future__ import annotations

import base64, io, json, os, re, shutil, tempfile, uuid, zipfile
from pathlib import Path, PurePosixPath

RECIPES = {
    "xelatex-bibtex": "latexmk -xelatex -bibtex -interaction=nonstopmode -halt-on-error main.tex",
    "xelatex-biber": "latexmk -xelatex -use-biber -interaction=nonstopmode -halt-on-error main.tex",
    "pdflatex-bibtex": "latexmk -pdf -bibtex -interaction=nonstopmode -halt-on-error main.tex",
    "lualatex-biber": "latexmk -lualatex -use-biber -interaction=nonstopmode -halt-on-error main.tex",
}
TEXT_EXTENSIONS = {".tex", ".bib", ".cls", ".sty", ".bst", ".bbx", ".cbx", ".def", ".cfg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".webp", ".tif", ".tiff"}
MAX_ZIP_BYTES, MAX_UNPACKED_BYTES, MAX_FILES = 100 * 1024 * 1024, 250 * 1024 * 1024, 1000
PROJECTS: dict[str, Path] = {}
SYSTEM_PROMPT = """你是科研论文 LaTeX 编辑器。只返回符合 JSON Schema 的结构化结果。
依据模板文件、用户确认的科研文案、对话记录和图片说明生成内容。保留模板的文档类、宏包、自定义命令和目录结构。
绝不编造实验数值、统计显著性、作者、DOI、参考文献或图片结论；缺失信息放入 missing_data。
只返回需要写入的 UTF-8 .tex/.bib 文件，路径必须是模板内相对路径；不要输出 shell 命令、绝对路径或 shell escape。"""
GENERATED_SCHEMA = {"type": "object", "properties": {
    "files": {"type": "object", "additionalProperties": {"type": "string"}},
    "summary": {"type": "string"}, "missing_data": {"type": "array", "items": {"type": "string"}},
}, "required": ["files", "summary", "missing_data"]}

def _result(success: bool, **data) -> str:
    return json.dumps({"success": success, **data}, ensure_ascii=False)

def _workspace() -> Path:
    raw = os.environ.get("LATEX_PAPER_WORKSPACE")
    root = Path(raw).expanduser() if raw else Path(tempfile.gettempdir()) / "latex-paper-projects"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()

def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if not name or path.is_absolute() or any(p in {"", ".", ".."} or ":" in p for p in path.parts):
        raise ValueError("unsafe relative path")
    return path

def _zip_bytes(args: dict) -> bytes:
    if args.get("template_zip_base64"):
        try:
            data = base64.b64decode(str(args["template_zip_base64"]), validate=True)
        except Exception:
            raise ValueError("template_zip_base64 is invalid") from None
    elif args.get("template_zip_path"):
        source = Path(str(args["template_zip_path"])).expanduser().resolve()
        if not source.is_file() or source.stat().st_size > MAX_ZIP_BYTES:
            raise ValueError("template ZIP is missing or too large")
        data = source.read_bytes()
    else:
        raise ValueError("template_zip_path or template_zip_base64 is required")
    if len(data) > MAX_ZIP_BYTES or not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("template must be a valid ZIP under 100 MB")
    return data

def _extract(data: bytes, destination: Path) -> list[str]:
    names, total = [], 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise ValueError("template contains too many files")
        for info in archive.infolist():
            rel = _safe_relative(info.filename)
            if info.is_dir() or info.filename.endswith("/"):
                continue
            if info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("symbolic links are not allowed in templates")
            total += info.file_size
            if total > MAX_UNPACKED_BYTES:
                raise ValueError("unpacked template is too large")
            target = destination.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            names.append(rel.as_posix())
    return names

def _main_file(root: Path, explicit: str | None = None) -> str:
    if explicit:
        rel = _safe_relative(explicit).as_posix()
        if not (root / rel).is_file() or Path(rel).suffix.lower() != ".tex":
            raise ValueError("main_file does not exist as a .tex file")
        return rel
    candidates = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.tex") if p.is_file())
    preferred = [p for p in candidates if Path(p).name.lower() in {"main.tex", "paper.tex", "manuscript.tex"}]
    if len(preferred) == 1: return preferred[0]
    if len(candidates) == 1: return candidates[0]
    if not candidates: raise ValueError("template contains no .tex file")
    raise ValueError("multiple .tex files found; provide main_file")

def _file_tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

def _project_root(project_id: str) -> Path:
    root = PROJECTS.get(project_id)
    if root is None or not root.is_dir(): raise ValueError("unknown project_id")
    return root

def _add_images(root: Path, images: object) -> list[dict]:
    if not images: return []
    if not isinstance(images, list) or len(images) > 100: raise ValueError("images must contain at most 100 items")
    figures, added = root / "figures", []
    figures.mkdir(exist_ok=True)
    for item in images:
        if not isinstance(item, dict) or not item.get("name"): raise ValueError("each image needs a name")
        name = _safe_relative(str(item["name"])).name
        if Path(name).suffix.lower() not in IMAGE_EXTENSIONS: raise ValueError("unsupported image extension")
        target = figures / name
        if item.get("base64"):
            try: raw = base64.b64decode(str(item["base64"]), validate=True)
            except Exception: raise ValueError("image base64 is invalid") from None
            if len(raw) > 25 * 1024 * 1024: raise ValueError("image is too large")
            target.write_bytes(raw)
        elif item.get("path"):
            source = Path(str(item["path"])).expanduser().resolve()
            if not source.is_file() or source.stat().st_size > 25 * 1024 * 1024: raise ValueError("image path is missing or too large")
            shutil.copyfile(source, target)
        else: raise ValueError("image needs path or base64 content")
        added.append({"path": f"figures/{name}", "description": str(item.get("description", ""))})
    return added

def _safe_generated(files: object) -> dict[str, str]:
    if not isinstance(files, dict) or not files or len(files) > 100: raise ValueError("files must contain 1-100 files")
    result = {}
    for raw_name, content in files.items():
        path = _safe_relative(str(raw_name))
        if path.suffix.lower() not in {".tex", ".bib"} or not isinstance(content, str): raise ValueError("generated files must be UTF-8 .tex or .bib files")
        if len(content.encode("utf-8")) > 8 * 1024 * 1024: raise ValueError("generated file is too large")
        result[path.as_posix()] = content
    return result

def inspect_template(args: dict, **kwargs) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="latex-inspect-") as tmp:
            root = Path(tmp); files = _extract(_zip_bytes(args), root); main = _main_file(root, args.get("main_file"))
            return _result(True, main_file=main, files=files, text_files=[p for p in files if Path(p).suffix.lower() in TEXT_EXTENSIONS], image_files=[p for p in files if Path(p).suffix.lower() in IMAGE_EXTENSIONS])
    except Exception as exc: return _result(False, error=str(exc))

def generate_project(ctx, args: dict, **kwargs) -> str:
    project_id = uuid.uuid4().hex
    try:
        instruction, material = str(args.get("instruction", "")).strip(), str(args.get("material", ""))
        if not instruction or len(material) > 120000: raise ValueError("instruction and bounded material are required")
        root = _workspace() / project_id; root.mkdir(parents=True)
        _extract(_zip_bytes(args), root); main = _main_file(root, args.get("main_file")); image_info = _add_images(root, args.get("images"))
        template_files = _file_tree(root)
        context = {p: (root / p).read_text(encoding="utf-8", errors="replace") for p in template_files if Path(p).suffix.lower() in TEXT_EXTENSIONS}
        response = ctx.llm.complete_structured(instructions=SYSTEM_PROMPT, input=[{"type": "text", "text": json.dumps({"instruction": instruction, "material": material, "main_file": main, "template_files": context, "images": image_info}, ensure_ascii=False)}], json_schema=GENERATED_SCHEMA, schema_name="latex.paper", purpose="latex-paper.generate", temperature=0.2, max_tokens=16000)
        if response.parsed is None: raise ValueError("模型没有返回有效的结构化 LaTeX")
        for rel, content in _safe_generated(response.parsed.get("files")).items():
            target = root / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
        recipe = str(args.get("recipe", "xelatex-bibtex"))
        if recipe not in RECIPES: raise ValueError("unsupported recipe")
        (root / "latex-paper-recipe.txt").write_text(RECIPES[recipe] + "\n", encoding="utf-8")
        (root / ".latex-paper.json").write_text(json.dumps({"main_file": main, "recipe": recipe, "confirmed": False}, indent=2), encoding="utf-8")
        PROJECTS[project_id] = root
        return _result(True, project_id=project_id, main_file=main, recipe=recipe, files=_file_tree(root), summary=response.parsed.get("summary", ""), missing_data=response.parsed.get("missing_data", []), requires_confirmation=True)
    except Exception as exc:
        shutil.rmtree(_workspace() / project_id, ignore_errors=True); return _result(False, error=str(exc))

def validate_project(args: dict, **kwargs) -> str:
    try:
        root = _project_root(str(args["project_id"])); main = _main_file(root, args.get("main_file")); text = (root / main).read_text(encoding="utf-8", errors="replace")
        missing = []
        for match in re.finditer(r"(?:includegraphics(?:\[[^]]*\])?|input|include|bibliography|addbibresource)\s*\{([^}]+)\}", text):
            ref = match.group(1).strip(); candidates = [root / ref]
            if not Path(ref).suffix: candidates.extend(root / (ref + ext) for ext in (".tex", ".bib", ".png", ".jpg", ".pdf"))
            if not any(p.is_file() for p in candidates): missing.append(ref)
        placeholders = sorted(set(re.findall(r"(?:TODO|TBD|待补充|PLACEHOLDER)", text, flags=re.I)))
        return _result(True, project_id=str(args["project_id"]), main_file=main, missing_references=sorted(set(missing)), placeholders=placeholders, valid=not missing)
    except Exception as exc: return _result(False, error=str(exc))

def confirm_package(args: dict, **kwargs) -> str:
    try:
        if args.get("confirmed") is not True: raise ValueError("explicit user confirmation is required")
        project_id = str(args["project_id"]); root = _project_root(project_id); validation = json.loads(validate_project({"project_id": project_id}))
        if not validation.get("success"): return _result(False, error=validation.get("error", "validation failed"))
        if validation.get("missing_references"): return _result(False, error="project has missing references", validation=validation)
        meta_path = root / ".latex-paper.json"; meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if args.get("recipe"):
            recipe = str(args["recipe"])
            if recipe not in RECIPES: raise ValueError("unsupported recipe")
            meta["recipe"] = recipe; (root / "latex-paper-recipe.txt").write_text(RECIPES[recipe] + "\n", encoding="utf-8")
        meta["confirmed"] = True; meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        archive = _workspace() / f"{project_id}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
            for path in root.rglob("*"):
                if path.is_file(): out.write(path, path.relative_to(root).as_posix())
        return _result(True, project_id=project_id, archive_path=str(archive), recipe=meta.get("recipe"), main_file=meta.get("main_file"), validation=validation)
    except Exception as exc: return _result(False, error=str(exc))
