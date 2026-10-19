#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面奶蛙 · 素材自检工具
================================================================
用法：双击本文件，或在本文件夹里执行  python 检查素材.py

它会告诉你：
  · 每一张素材到底从哪个路径找到的（找不到的会红色标出）
  · 有没有「用到了本文件夹之外」的素材（跨副本污染警告）
  · 缺什么、应该放哪里、标准文件名是什么
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    print("=" * 72)
    print("  桌面奶蛙 · 素材自检")
    print("=" * 72)
    print(f"  程序目录 : {HERE}")
    print(f"  Python   : {sys.version.split()[0]}")
    print()

    # ---- 依赖 ----
    try:
        import PIL
        print(f"  Pillow   : {PIL.__version__}  ✅")
    except Exception as exc:
        print(f"  Pillow   : ❌ 未安装（{exc}）")
        print("            修复：pip install pillow")
        return 2

    try:
        import desktop_pet as dp
    except Exception:
        import traceback
        print("\n❌ 无法导入 desktop_pet.py（主程序不在本文件夹？）")
        traceback.print_exc()
        return 3

    # ---- 逐项检查 ----
    print("\n" + "-" * 72)
    print("  素材逐项检查（※ = 本文件夹之外，可能是别的副本里的素材）")
    print("-" * 72)
    miss_req, miss_opt, external = [], [], []
    for name, spec in dp.ASSETS.items():
        if spec.get("kind") == "procedural":
            print(f"  [程序生成] {name:12s} （呼吸动画，无需文件）")
            continue
        names = spec.get("names") or []
        path = dp.find_asset(name, names) if names else None
        optional = bool(spec.get("optional"))
        want = os.path.basename(names[0]) if names else "?"
        if not path:
            flag = "可选缺" if optional else "缺失  "
            print(f"  [{flag}] {name:12s} 应为 {want}")
            (miss_opt if optional else miss_req).append((name, want))
            continue
        is_ext = not os.path.abspath(path).startswith(os.path.abspath(HERE) + os.sep)
        mark = "※" if is_ext else "  "
        if is_ext:
            external.append((name, path))
        print(f"  [ OK   ] {name:12s} {mark} {os.path.basename(path)}")
        if is_ext:
            print(f"                       ↑ 实际路径：{path}")

    # ---- 皮肤 ----
    print("-" * 72)
    skins = getattr(dp, "SKINS", {}) or {}
    if skins:
        skin_dir = os.path.join(HERE, getattr(dp, "SKIN_DIR", "assets/skins"))
        smiss = []
        for sid, s in skins.items():
            p = os.path.join(skin_dir, s.get("file", ""))
            if not os.path.isfile(p):
                smiss.append(s.get("name", sid))
        if smiss:
            print(f"  皮肤素材：缺 {len(smiss)}/{len(skins)} → {', '.join(smiss)}")
            print(f"            应放在：{skin_dir}")
        else:
            print(f"  皮肤素材：{len(skins)}/{len(skins)} 就绪 ✅（{skin_dir}）")

    # ---- 结论 ----
    print("=" * 72)
    if external:
        print("  ⚠ 有素材来自本文件夹之外（可能串了别的副本的图）：")
        for n, p in external:
            print(f"     · {n} → {p}")
        print("     处理：把标准命名的素材放进本文件夹的 assets\\ 里")
    if miss_req:
        print(f"  ❌ 缺 {len(miss_req)} 张必需素材：")
        for n, w in miss_req:
            print(f"     · {n}（文件名应为 {w}）")
        print(f"     请放到：{os.path.join(HERE, 'assets')}")
        print("     常见原因：只拷了 .py / 解压时漏了 assets / 素材被改名")
    if not miss_req and not external:
        print("  ✅ 素材全部就绪，且都在本文件夹内 —— 可以放心运行")
    elif not miss_req:
        print("  ✅ 必需素材齐全（但有外部素材，见上方警告）")
    print("=" * 72)

    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n按回车键退出…")
    except Exception:
        pass
    return 0 if (not miss_req and not external) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n按回车键退出…")
        except Exception:
            pass
        sys.exit(9)
