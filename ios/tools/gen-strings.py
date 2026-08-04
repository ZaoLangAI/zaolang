#!/usr/bin/env python3
"""从 `front/src/i18n/messages/*.json` 生成 iOS 的 `Localizable.xcstrings`。

真源是网页端的 next-intl 文案；只导 M1 用得到的命名空间，键名保持
`namespace.key`（比如 `discover.results`），三语原样搬。

**插值方式的取舍**：next-intl 用 `{var}`，Xcode String Catalog 原生的做法是转成
`%1$@` 之类的位置参数 + `substitutions` 字典。那套机制本机没有 Xcode 没法跑一遍验证，
一旦哪个字段配错就是运行时才会暴露的哑文案。所以这里选更笨但更可靠的路子：
**原样保留 `{var}`**，App 层用一个几行的字符串替换函数在取到本地化文案之后自己插值
（见 `App/Sources/Support/L10n.swift`）。两种方式效果等价，这种更容易靠读代码看出对不对。

用法：
    python3 ios/tools/gen-strings.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MESSAGES_DIR = REPO_ROOT / "front" / "src" / "i18n" / "messages"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "App" / "Resources" / "Localizable.xcstrings"

# next-intl locale -> Apple 语言标识；三个都要在 ios/project.yml 与 Info.plist 里对应声明。
LOCALE_FILES = {
    "zh-Hans": "zh-CN.json",
    "en": "en.json",
    "ja": "ja.json",
}

# M1 只读闭环 + M2/M3（账号、创作闭环、入门引导）用得到的命名空间；后台运维（`admin*`）、
# 短视频合规引擎（`shortform`）、多集角色库（`characters`）、指令面板（`commandPalette`）、
# 门户装饰（`footer`/`gateway`/`devicePreview`）不在这个范围——iOS 没有对应界面。
NAMESPACES = [
    "discover",
    "work",
    "workPage",
    "lineagePanel",
    "learnPage",
    "profilePage",
    "states",
    "actions",
    "a11y",
    "nav",
    "visibility",
    "license",
    "theme",
    "region",
    "brand",
    "auth",
    "collectionPage",
    "createPage",
    "remixPage",
    "job",
    "jobPage",
    "publishPage",
    "settingsPage",
    "billingPage",
    "notificationsPage",
    "credits",
    "iosOnboarding",
]

SOURCE_LANGUAGE = "zh-Hans"


def load_locale(filename: str) -> dict:
    path = MESSAGES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    messages = {locale: load_locale(filename) for locale, filename in LOCALE_FILES.items()}

    strings: dict[str, dict] = {}
    total_keys = 0
    for ns in NAMESPACES:
        per_locale_keys = {locale: set(messages[locale].get(ns, {}).keys()) for locale in LOCALE_FILES}
        reference = per_locale_keys[SOURCE_LANGUAGE]
        for locale, keys in per_locale_keys.items():
            if keys != reference:
                missing = reference - keys
                extra = keys - reference
                print(
                    f"警告：命名空间 {ns} 在 {locale} 缺 {sorted(missing)}，多出 {sorted(extra)}",
                    file=sys.stderr,
                )

        for key in sorted(reference):
            full_key = f"{ns}.{key}"
            localizations = {}
            for locale in LOCALE_FILES:
                value = messages[locale].get(ns, {}).get(key)
                if value is None:
                    continue
                localizations[locale] = {"stringUnit": {"state": "translated", "value": value}}
            strings[full_key] = {"extractionState": "manual", "localizations": localizations}
            total_keys += 1

    catalog = {
        "sourceLanguage": SOURCE_LANGUAGE,
        "strings": strings,
        "version": "1.0",
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"完成：{len(NAMESPACES)} 个命名空间、{total_keys} 个 key 写入 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
