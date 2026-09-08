"""Boundary tests for the local ZIP-template LaTeX plugin."""
import base64, importlib.util, io, json, sys, tempfile, types, unittest, zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "extensions/plugins/latex-paper"
spec = importlib.util.spec_from_file_location("latex_paper_test", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)

class FakeContext:
    def __init__(self):
        self.tools, self.skills = {}, []
        self.llm = types.SimpleNamespace(complete_structured=lambda **_: None)
    def register_tool(self, **definition): self.tools[definition["name"]] = definition
    def register_skill(self, name, path): self.skills.append((name, path))

def template_b64():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("main.tex", "\\documentclass{article}\n\\begin{document}\n\\input{sections/results}\n\\includegraphics{figures/result.png}\n\\end{document}")
        z.writestr("sections/results.tex", "\\section{Results}\nTODO")
        z.writestr("custom.sty", "")
    return base64.b64encode(out.getvalue()).decode()

class LatexPluginTests(unittest.TestCase):
    def test_registers_new_tools_and_skill(self):
        context = FakeContext(); module.register(context)
        self.assertEqual(set(context.tools), {"latex_template_inspect", "latex_project_generate", "latex_project_validate", "latex_project_confirm_package"})
        self.assertEqual(context.skills[0][0], "latex-paper")

    def test_inspects_zip_and_rejects_traversal(self):
        result = json.loads(module.tools.inspect_template({"template_zip_base64": template_b64()}))
        self.assertTrue(result["success"]); self.assertEqual(result["main_file"], "main.tex")
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as z: z.writestr("../evil.tex", "bad")
        result = json.loads(module.tools.inspect_template({"template_zip_base64": base64.b64encode(bad.getvalue()).decode()}))
        self.assertFalse(result["success"])

    def test_generates_validates_and_requires_confirmation(self):
        context = FakeContext(); module.register(context)
        context.llm.complete_structured = lambda **_: types.SimpleNamespace(parsed={"files": {"sections/results.tex": "\\section{Results}\\nConfirmed text."}, "summary": "done", "missing_data": []})
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"LATEX_PAPER_WORKSPACE": workspace}):
            generated = json.loads(context.tools["latex_project_generate"]["handler"]({"template_zip_base64": template_b64(), "instruction": "写结果", "material": "已确认结果", "images": [{"name": "result.png", "base64": base64.b64encode(b"png").decode(), "description": "结果图"}]}))
            self.assertTrue(generated["success"]); project_id = generated["project_id"]
            validation = json.loads(module.tools.validate_project({"project_id": project_id}))
            self.assertTrue(validation["success"]); self.assertFalse(validation["missing_references"])
            denied = json.loads(module.tools.confirm_package({"project_id": project_id, "confirmed": False}))
            self.assertFalse(denied["success"])
            packaged = json.loads(module.tools.confirm_package({"project_id": project_id, "confirmed": True}))
            self.assertTrue(packaged["success"]); self.assertTrue(Path(packaged["archive_path"]).is_file())

if __name__ == "__main__": unittest.main()
