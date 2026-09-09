# latex-paper Hermes plugin

This plugin accepts a user ZIP template, optional uploaded images and confirmed research dialogue, then generates a LaTeX project without running TeX Live. After explicit confirmation it creates a ZIP containing the template, generated `.tex`/`.bib` files, images and a selected `latexmk` recipe.

Tools:

- `latex_template_inspect`: inspect ZIP structure and find the main `.tex` file.
- `latex_project_generate`: copy the template, add images and generate text files.
- `latex_project_validate`: check static file references and placeholders.
- `latex_project_confirm_package`: require `confirmed: true`, then create the archive.

Set `LATEX_PAPER_WORKSPACE` to a private writable directory in production. Upload paths should be staged there by the host application. The plugin never executes a template file, shell command or TeX compiler.
