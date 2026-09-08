---
name: latex-paper
description: Generate and package a LaTeX research project from a user ZIP template, images and confirmed research material without compiling it.
---

# LaTeX 论文工程工作流

1. 调用 `latex_template_inspect` 检查 ZIP 模板，并在存在多个 `.tex` 文件时询问主文件。
2. 只使用用户确认的科研文案、图片说明、附件和选定对话；保留模板的文档类、宏包、自定义命令和目录结构。
3. 调用 `latex_project_generate` 生成或修改 `.tex`/`.bib` 文件，选择编译配方，但不要执行编译。
4. 不编造实验数值、统计显著性、作者、DOI、参考文献或图片结论；缺失内容写入 `missing_data` 并向用户说明。
5. 调用 `latex_project_validate` 检查图片、章节和参考文献引用是否存在，并处理占位符。
6. 向用户展示生成摘要、缺失数据、文件清单和配方，等待用户明确确认。
7. 只有用户确认后才调用 `latex_project_confirm_package`，且必须传入 `confirmed: true`。
8. 最终 ZIP 应包含模板、生成的代码、图片、`latex-paper-recipe.txt` 和元数据；插件不运行 shell、TeX Live 或模板脚本。
