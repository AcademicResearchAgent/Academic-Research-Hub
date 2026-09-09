"""JSON schemas exposed to Hermes."""

INSPECT = {
    "name": "latex_template_inspect", "description": "Inspect a user-provided ZIP LaTeX template without modifying it.",
    "parameters": {"type": "object", "properties": {
        "template_zip_path": {"type": "string", "description": "Path in the controlled upload workspace"},
        "template_zip_base64": {"type": "string", "description": "Base64 encoded ZIP, for small uploads"},
        "main_file": {"type": "string"},
    }, "oneOf": [{"required": ["template_zip_path"]}, {"required": ["template_zip_base64"]}]},
}

GENERATE = {
    "name": "latex_project_generate", "description": "Generate LaTeX files inside a copied ZIP template from confirmed research material and image descriptions; do not invent data.",
    "parameters": {"type": "object", "properties": {
        "template_zip_path": {"type": "string"}, "template_zip_base64": {"type": "string"}, "main_file": {"type": "string", "maxLength": 240},
        "instruction": {"type": "string", "maxLength": 8000}, "material": {"type": "string", "maxLength": 120000},
        "images": {"type": "array", "maxItems": 100, "items": {"type": "object", "properties": {
            "name": {"type": "string", "maxLength": 180}, "path": {"type": "string", "maxLength": 500}, "base64": {"type": "string"}, "description": {"type": "string", "maxLength": 4000}
        }, "required": ["name"]}},
        "recipe": {"type": "string", "enum": ["xelatex-bibtex", "xelatex-biber", "pdflatex-bibtex", "lualatex-biber"]},
    }, "oneOf": [{"required": ["template_zip_path"]}, {"required": ["template_zip_base64"]}], "required": ["instruction", "material"]},
}

VALIDATE = {
    "name": "latex_project_validate", "description": "Statically validate a generated LaTeX project for missing files, unsafe paths and unresolved placeholders.",
    "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}, "main_file": {"type": "string", "maxLength": 240}}, "required": ["project_id"]},
}

PACKAGE = {
    "name": "latex_project_confirm_package", "description": "After explicit user confirmation, package LaTeX files, images and the build recipe as a ZIP archive.",
    "parameters": {"type": "object", "properties": {
        "project_id": {"type": "string"}, "confirmed": {"type": "boolean"},
        "recipe": {"type": "string", "enum": ["xelatex-bibtex", "xelatex-biber", "pdflatex-bibtex", "lualatex-biber"]},
    }, "required": ["project_id", "confirmed"]},
}
