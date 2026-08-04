#!/usr/bin/env python3
"""从 `front/src/app/globals.css` 的两套主题块生成 iOS Asset Catalog 色板。

真源是网页端的 CSS 变量，这里只做机械翻译，不手抄任何色值——色值漂移的风险从此归零。
只翻译"纯色"（hex 或 `rgb(r g b / a%)`）：渐变（`poster-scrim` / `gateway-panel`）和
阴影复合值（`card-shadow` / `card-shadow-raised`）不是 Color Set 能表达的东西，
跳过留给 App 设计系统层（`ZLShadow` 之类）用字面量常量表达。

用法：
    python3 ios/tools/gen-colors.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOBALS_CSS = REPO_ROOT / "front" / "src" / "app" / "globals.css"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "App" / "Resources" / "Assets.xcassets" / "Colors"

HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")
RGB_ALPHA_RE = re.compile(r"^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*/\s*([\d.]+)%\s*\)$")
DECLARATION_RE = re.compile(r"--([\w-]+)\s*:\s*(.*?);", re.DOTALL)


def extract_block(css: str, selector_end_marker: str) -> str:
    """从 `selector_end_marker` 后的第一个 `{` 取到与之配对的顶层 `}`。

    这两个主题块里没有嵌套规则集，`{}` 不会嵌套，找下一个 `}` 就是块尾。
    """
    start = css.index(selector_end_marker)
    brace_open = css.index("{", start)
    brace_close = css.index("}", brace_open)
    return css[brace_open + 1 : brace_close]


def parse_flat_color(raw_value: str) -> tuple[float, float, float, float] | None:
    value = raw_value.strip()
    if m := HEX_RE.match(value):
        hex6 = m.group(1)
        r, g, b = (int(hex6[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, 1.0)
    if m := RGB_ALPHA_RE.match(value):
        r, g, b, a = m.groups()
        return (int(r) / 255.0, int(g) / 255.0, int(b) / 255.0, float(a) / 100.0)
    return None


def parse_theme_block(block: str) -> dict[str, tuple[float, float, float, float]]:
    colors: dict[str, tuple[float, float, float, float]] = {}
    for name, raw_value in DECLARATION_RE.findall(block):
        parsed = parse_flat_color(raw_value)
        if parsed is not None:
            colors[name] = parsed
        else:
            print(f"  跳过非纯色 token --{name}（渐变或复合阴影，不进 Color Set）", file=sys.stderr)
    return colors


def kebab_to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-"))


def component_string(value: float) -> str:
    return f"{value:.3f}"


def write_colorset(name: str, light: tuple[float, float, float, float], dark: tuple[float, float, float, float]) -> None:
    def color_entry(rgba: tuple[float, float, float, float], appearances: list[dict] | None) -> dict:
        r, g, b, a = rgba
        entry: dict = {
            "idiom": "universal",
            "color": {
                "color-space": "srgb",
                "components": {
                    "red": component_string(r),
                    "green": component_string(g),
                    "blue": component_string(b),
                    "alpha": component_string(a),
                },
            },
        }
        if appearances:
            entry["appearances"] = appearances
        return entry

    contents = {
        "colors": [
            color_entry(light, None),
            color_entry(dark, [{"appearance": "luminosity", "value": "dark"}]),
        ],
        "info": {"author": "xcode", "version": 1},
    }

    colorset_dir = OUTPUT_DIR / f"{name}.colorset"
    colorset_dir.mkdir(parents=True, exist_ok=True)
    import json

    (colorset_dir / "Contents.json").write_text(json.dumps(contents, indent=2) + "\n")


def main() -> None:
    css = GLOBALS_CSS.read_text(encoding="utf-8")

    print("解析 dark 主题块 …")
    dark_block = extract_block(css, "[data-theme='dark']")
    dark_colors = parse_theme_block(dark_block)

    print("解析 light 主题块 …")
    light_block = extract_block(css, "[data-theme='light']")
    light_colors = parse_theme_block(light_block)

    shared_names = sorted(set(dark_colors) & set(light_colors))
    missing_in_light = sorted(set(dark_colors) - set(light_colors))
    missing_in_dark = sorted(set(light_colors) - set(dark_colors))
    if missing_in_light:
        print(f"警告：{missing_in_light} 只在 dark 块出现，跳过", file=sys.stderr)
    if missing_in_dark:
        print(f"警告：{missing_in_dark} 只在 light 块出现，跳过", file=sys.stderr)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in shared_names:
        pascal_name = kebab_to_pascal(name)
        write_colorset(pascal_name, light_colors[name], dark_colors[name])
        print(f"  写入 Colors/{pascal_name}.colorset")

    print(f"完成：生成 {len(shared_names)} 个 Color Set 到 {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
