# -*- coding: utf-8 -*-
"""data_format_read —— 常见数据格式读取能力自检。

验证 cfd-npy3d 扩展（pvjob_pvdata 的 READERS 映射 + OpenDataFile 兜底）对常见
ParaView/VTK 数据格式的读取能力：

1. make_samples_pv.py 在 pvpython 下现场生成 tiny 样例
   （.vti/.vtu/.vtp/.vts/.vtr/.vtk/.vtm/.stl/.ply/.obj/.csv/.pvd/.ex2/.e 等）；
2. run_format_read_check.py 逐格式调用扩展真实读取路径
   pvbridge.run_job("inspect", ...)，输出支持矩阵。

运行：
    python -m checks.data_format_read.run_format_read_check
"""
