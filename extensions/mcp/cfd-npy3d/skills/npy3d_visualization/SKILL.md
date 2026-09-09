---
name: npy3d-visualization
description: 把以 X/Y/Q 三个 .npy 存储的 CFD 平面场（NACA 翼型/圆柱绕流贴体网格等）做三维可视化：数据集检视、单帧三维曲面图、时间序列三维曲面 GIF 动画。适用于数据是 numpy 数组、网格为规则 (H,W) 或 (T,H,W) 平面网格、物理量 Q 布局为 (H,W)/(C,H,W)/(T,H,W)/(T,C,H,W) 的场景。
data_access_level: raw
task_type: multi-step
permitted_tools:
  - npy3d_inspect
  - npy3d_render_surface
  - npy3d_render_animation
---

# npy3d 三维可视化（.npy CFD 平面场）

## 用途

同一目录下有 `X/Y/Q` 三个 `.npy` 的 CFD 数据（如 `CFD_TEST/NACA_Cylinder_*`），
本技能负责把它变成可读的三维图：

- 检视协议语义：时间帧 T / 物理量通道 C / 网格 H×W；
- 三维曲面图：以空间坐标 (X,Y) 为底面，物理量 Q 同时作为高度与颜色；
- 时间 GIF 动画：某通道沿时间帧的曲面演化。

## 何时使用 / 何时不用

使用：数据是 `.npy`、网格是规则平面网格、想快速看场的三维形态或随时间的演化。

不用：数据是 `.vtu/.ex2/.vtk` 等 ParaView 原生格式（走 `pvdata_*` / pvdata-visualization 技能）；
数据点不在规则网格上（散点，无 X/Y 网格语义）。

## 工具

| 工具 | 作用 |
|---|---|
| `npy3d_inspect` | 推断 T/C/H×W、报告文件与坐标范围、首帧各通道统计（先检视再作图） |
| `npy3d_render_surface` | 单帧三维曲面 PNG；`channels="0"/"all"/"0,2"/"1-3"` |
| `npy3d_render_animation` | 单通道时间序列三维曲面 GIF |

## 标准流程

1. **检视**：`npy3d_inspect(data_dir=<目录>)` 确认 T、C、H×W 与各通道范围；
2. **单帧**：`npy3d_render_surface(data_dir=..., frame=<想看的时间帧>, channels="<想看的通道>", case=<归档名>)`；
3. **动画**（T≥2 且目标通道抽样帧无 NaN）：`npy3d_render_animation(data_dir=..., channel=<通道>, max_frames=<帧数>, case=<归档名>)`。

## 参数约定

- `data_dir`：可选，缺省是包内 `sample_data/` 演示数据；
- `channels` 支持单通道 `"0"`、全通道 `"all"`、逗号列表 `"0,2"`、区间 `"1-3"`；
- `case`：产物归档名，不填则落到 `output/render/`。
- 图像内文字固定英文（避免 matplotlib 缺中文字形），返回的 Markdown 文本用中文。

## 输出与产物

- 工具返回 Markdown（含产物绝对路径）。
- 带 `case`：`<产物根>/cases/<case>/render/<时间戳>.png/.gif`；
  不带 `case`：`<产物根>/render/...`。产物根可用环境变量 `NPY3D_OUT_ROOT` 覆盖。

## 示例

```
npy3d_inspect(data_dir="g:/mcp-/cfd_npy3d_mcp/sample_data")
npy3d_render_surface(data_dir="g:/mcp-/CFD_TEST", frame=0, channels="0", case="naca_cylinder")
npy3d_render_animation(data_dir="g:/mcp-/CFD_TEST", channel=0, max_frames=48, fps=6, case="naca_cylinder")
```

## 限制与注意

- 大数据用 `mmap` 流式读，1 GB 级 `Q.npy` 不会整载入内存。
- 动画要求抽样帧无 NaN；含 NaN 的通道会明确报错，换帧段/通道或先看各帧统计。
- 通道物理含义无法从数值自动判断，先 `npy3d_inspect` 看各通道范围（含负值多为速度/涡量类）。

## 参考

- 数据协议细节：`references/npy_data_protocol.md`
