"""科研作图样式：SCI（Times New Roman）与 Nature 投稿风（无衬线）双 preset。

Nature preset / 色板 / 多格式导出参考上游 skill：
`.cursor/skills/nature-figure`（yuan1z0825/nature-skills）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# ── Nature / 高影响因子常用色板（来自 nature-figure references/api.md）──
PALETTE: dict[str, str] = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green_1": "#DDF3DE",
    "green_2": "#AADCA9",
    "green_3": "#8BCF8B",
    "red_1": "#F6CFCB",
    "red_2": "#E9A6A1",
    "red_strong": "#B64342",
    "neutral_light": "#CFCECE",
    "neutral_mid": "#767676",
    "neutral_dark": "#4D4D4D",
    "neutral_black": "#272727",
    "gold": "#FFD700",
    "teal": "#42949E",
    "violet": "#9A4D8E",
    "magenta": "#EA84DD",
}

DEFAULT_COLORS: list[str] = [
    PALETTE["blue_main"],
    PALETTE["green_3"],
    PALETTE["red_strong"],
    PALETTE["teal"],
    PALETTE["violet"],
    PALETTE["neutral_mid"],
]

# 材料计算常见曲线（能量、DOS 等）优先色
CMATS_SERIES_COLORS: list[str] = [
    PALETTE["blue_main"],
    PALETTE["red_strong"],
    PALETTE["teal"],
    PALETTE["violet"],
    PALETTE["green_3"],
    PALETTE["neutral_dark"],
]

_TNR_FILES = {
    "regular": [
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
        Path("/Library/Fonts/Times New Roman.ttf"),
        Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/timesnr.ttf"),
    ],
    "bold": [
        Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
        Path("/Library/Fonts/Times New Roman Bold.ttf"),
        Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
        Path("C:/Windows/Fonts/timesbd.ttf"),
    ],
    "italic": [
        Path("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
        Path("/Library/Fonts/Times New Roman Italic.ttf"),
        Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Italic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        Path("C:/Windows/Fonts/timesi.ttf"),
    ],
    "bold_italic": [
        Path("/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"),
        Path("/Library/Fonts/Times New Roman Bold Italic.ttf"),
        Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Bold_Italic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"),
        Path("C:/Windows/Fonts/timesbi.ttf"),
    ],
}

_cached_family: Optional[str] = None
_cached_props: dict[str, Any] = {}
_active_preset: str = "nature"


def _first_existing(paths: list[Path]) -> Optional[Path]:
    for p in paths:
        if p.is_file():
            return p
    return None


def resolve_plot_preset(requested: str = "") -> str:
    """sci | nature。默认 sci（Times New Roman）；可用 CMATS_PLOT_STYLE 覆盖。"""
    raw = (
        requested
        or os.environ.get("CMATS_PLOT_STYLE")
        or os.environ.get("DFTB_NEU_PLOT_STYLE")
        or "sci"
    ).strip().lower()
    if raw in ("nature", "arial", "sans"):
        return "nature"
    return "sci"


def active_preset() -> str:
    return _active_preset


def palette_color(name: str, fallback: str = "") -> str:
    return PALETTE.get(name) or fallback or PALETTE["blue_main"]


def series_colors(n: int = 0) -> list[str]:
    if n <= 0:
        return list(CMATS_SERIES_COLORS)
    out: list[str] = []
    for i in range(n):
        out.append(CMATS_SERIES_COLORS[i % len(CMATS_SERIES_COLORS)])
    return out


def apply_sci_fonts(*, dpi: int = 300) -> str:
    """SCI 规范：强制 Times New Roman（含粗体/斜体）。"""
    global _cached_family, _cached_props, _active_preset
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.font_manager import FontProperties

    _active_preset = "sci"
    family = "Times New Roman"
    props: dict[str, FontProperties] = {}
    for weight, paths in _TNR_FILES.items():
        path = _first_existing(paths)
        if not path:
            continue
        try:
            font_manager.fontManager.addfont(str(path))
            fp = FontProperties(fname=str(path))
            props[weight] = fp
            if weight == "regular":
                family = fp.get_name()
        except Exception:
            continue

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [family, "Times New Roman", "Times", "DejaVu Serif"],
            "mathtext.fontset": "stix",
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "axes.linewidth": 0.9,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "axes.spines.top": True,
            "axes.spines.right": True,
            "legend.frameon": False,
            "figure.dpi": dpi,
            "savefig.dpi": dpi,
            "axes.grid": False,
        }
    )
    _cached_family = family
    _cached_props = props
    return family


def apply_nature_style(*, dpi: int = 600, font_size: float = 7) -> str:
    """Nature / 高影响因子投稿风：无衬线、去上右边框、矢量可编辑字。"""
    global _active_preset
    import matplotlib.pyplot as plt

    _active_preset = "nature"
    family = "Arial"
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "mathtext.fontset": "dejavusans",
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.size": font_size,
            "axes.labelsize": font_size,
            "axes.titlesize": font_size + 1,
            "xtick.labelsize": max(6.0, font_size - 1),
            "ytick.labelsize": max(6.0, font_size - 1),
            "legend.fontsize": max(6.0, font_size - 1),
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.6,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.top": False,
            "ytick.right": False,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "legend.frameon": False,
            "figure.dpi": min(dpi, 300),
            "savefig.dpi": dpi,
            "axes.grid": False,
        }
    )
    return family


def apply_plot_style(preset: str = "", *, dpi: Optional[int] = None) -> str:
    """统一入口。默认 sci / Times New Roman。"""
    if not (preset or "").strip():
        try:
            from ..config import settings

            preset = str(getattr(settings, "plot_style", "") or "")
        except Exception:
            preset = ""
    kind = resolve_plot_preset(preset)
    if kind == "nature":
        return apply_nature_style(dpi=dpi or 600)
    return apply_sci_fonts(dpi=dpi or 300)


def sci_font(*, weight: str = "regular", size: Optional[float] = None) -> Any:
    """返回强制绑定到 TNR 文件的 FontProperties（SCI preset）。"""
    from matplotlib.font_manager import FontProperties

    if not _cached_props:
        apply_sci_fonts()
    fp = _cached_props.get(weight) or _cached_props.get("regular")
    if fp is None:
        return FontProperties(family="Times New Roman", size=size)
    out = FontProperties(fname=fp.get_file())
    if size is not None:
        out.set_size(size)
    return out


def label_font(*, weight: str = "regular", size: Optional[float] = None) -> Any:
    """按当前 preset 返回适合 set_*label 的 FontProperties。"""
    from matplotlib.font_manager import FontProperties

    if _active_preset == "sci":
        return sci_font(weight=weight, size=size)
    return FontProperties(
        family="sans-serif",
        weight="bold" if weight in ("bold", "bold_italic") else "normal",
        style="italic" if weight in ("italic", "bold_italic") else "normal",
        size=size,
    )


def force_axes_fonts(ax) -> None:
    """把坐标轴标题/刻度/图例钉到当前 preset 字体。"""
    if _active_preset == "sci":
        ax.set_title(ax.get_title(), fontproperties=sci_font(weight="bold", size=13))
        ax.set_xlabel(ax.get_xlabel(), fontproperties=sci_font(size=12))
        ax.set_ylabel(ax.get_ylabel(), fontproperties=sci_font(size=12))
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontproperties(sci_font(size=10))
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                t.set_fontproperties(sci_font(size=10))
        return
    # nature：依赖 rcParams，仅统一去掉图例边框
    leg = ax.get_legend()
    if leg is not None:
        leg.set_frame_on(False)


def figure_size_mm(width_mm: float = 89.0, height_mm: float = 70.0) -> tuple[float, float]:
    """期刊栏宽（单栏约 89 mm，双栏约 183 mm）→ inches。"""
    return (width_mm / 25.4, height_mm / 25.4)


def save_publication(
    fig: Any,
    stem: Path | str,
    *,
    formats: Sequence[str] = ("png", "pdf", "svg"),
    dpi: Optional[int] = None,
    facecolor: str = "white",
) -> dict[str, str]:
    """投稿常用多格式导出。stem 不含后缀。返回 {fmt: path}。"""
    import matplotlib.pyplot as plt

    stem_path = Path(stem)
    if stem_path.suffix.lower() in {".png", ".pdf", ".svg", ".tif", ".tiff"}:
        stem_path = stem_path.with_suffix("")
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    save_dpi = dpi
    if save_dpi is None:
        save_dpi = 600 if _active_preset == "nature" else 300
    out: dict[str, str] = {}
    for fmt in formats:
        key = fmt.lower().lstrip(".")
        if key == "tif":
            key = "tiff"
        path = stem_path.with_suffix(f".{key}")
        kw: dict[str, Any] = {"bbox_inches": "tight", "facecolor": facecolor}
        if key in ("png", "tiff"):
            kw["dpi"] = save_dpi
        fig.savefig(path, **kw)
        out[key] = str(path)
    return out
