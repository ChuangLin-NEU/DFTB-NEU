# DFTB+ 自然语言命令（课堂版 · 已落地）

触发：句中含 **DFTB+ / DFTB / dftbplus / 紧束缚**（及各族关键词）→ 匹配能力族并生成 `dftb_in.hsd`。

输入：按 [DFTB+ Recipes](https://dftbplus-recipes.readthedocs.io/) 生成 HSD + 几何；作业写入 `~/.dftb-neu/jobs`（Windows 经 WSL2）。

程序内完整表：`GET /api/commands` 或 `dftb_engine.capability.commands_markdown()`。

## 能力族与示例话术

| 能力族 | 示例说法 | 生成要点 |
|--------|----------|----------|
| 电子结构 | 「用 DFTB+ 算单点 SCC」「DFTB+ 能带和 DOS」 | `Hamiltonian=DFTB`，能带含 `BandStructure` |
| 几何/振动 | 「DFTB+ 几何优化」「振动频率」 | `GeometryOptimization` / `SecondDerivatives` + `modes_in.hsd` |
| MD | 「BOMD」「模拟退火」 | `VelocityVerlet` + NoseHoover / TemperatureProfile |
| 溶剂 | 「隐式溶剂 ALPB」「logP」 | `Solvation=GeneralizedBorn` |
| 二维/缺陷 | 「石墨烯缺陷电子结构」 | 周期 K 点 + 能带分析 |
| 线性响应 | 「TD-DFTB 吸收光谱」「Casida」 | `ExcitedState/Casida` |
| 电子动力学 | 「Kick 光谱」「Ehrenfest」 | `ElectronDynamics` |
| 物性 | 「phonopy 声子」「反应能垒」 | 力计算 + `phonopy_dftb.conf` / 路径说明 |
| REKS | 「REKS SSR22」 | `REKS=SSR22` + `SpinConstants` |
| 输运 | 「分子结透射」「ContactHamiltonian」 | `Transport{Device,Contact,Task}` |
| 边界 | 「螺旋边界」 | Helical 采样说明 + 能带 |
| GSM | 「GSM 反应路径」 | 力计算器 + `gsm_readme.txt` |
| 内建 xTB | 「DFTB+ 里用 GFN2-xTB」 | `Hamiltonian=xTB`（≠ 独立 xtb 程序） |
| 接口 | 「ASE 调 DFTB+」「i-PI」 | `run_ase_dftb.py` / `ipi_client.sh` |

## 课堂环境说明

- 隔离前缀：`~/.dftb-neu`（micromamba env + SK）。
- glibc 较旧时部署脚本回退 DFTB+ 21.2。
- 对话编排与 DeepSeek Key 见学生手册；计算可在部署完成后离线进行。
