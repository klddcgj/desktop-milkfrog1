# -*- coding: utf-8 -*-
"""
================================================================================
 🐣 桌宠 Desktop Pet · 黑客松参赛原型 Demo（单文件版）
================================================================================
 项目定位
    一只常驻桌面、永远悬浮在所有窗口之上的黄色小团子。它有自己的情绪与作息，
    会跟着你的鼠标歪头、被拖动、被点击、被投喂、被抚摸，也会在没人理它的时候
    自己散步、发呆、自言自语、打盹。

 技术选型
    · Python 3.14（本机 3.14.0a1）+ 标准库 tkinter 做窗口（轻量、无 Electron）
    · Pillow 仅用于「图像处理」：抠背景、翻转、旋转、调色、缓存
    · 透明窗口原理：Windows 分层窗口色键（color key）
        root.wm_attributes("-transparentcolor", KEY)
      凡是颜色正好等于 KEY 的像素变成全透明 → 于是我们让整块画布背景 = KEY，
      只把宠物本体和白色气泡画上去，就实现「无边框 + 透明背景 + 只渲染本体」。
      色键区域在 Windows 上同时是「鼠标穿透」的，所以点空白处不会误触宠物。

 素材（严格使用给定 4 张，不额外创作美术资源）
    assets/pet_idle.webp   ← 第 3 张（平常表情 / 待机）
    assets/pet_happy.gif   ← 第 1 张（动图，开心蹦跳）
    assets/pet_talk.webp   ← 第 2 张（大笑，对话时使用）
    assets/pet_eat.webp    ← 第 4 张（喝珍珠奶茶，进食时使用）

--------------------------------------------------------------------------------
 【环境准备】—— 复制粘贴即可
--------------------------------------------------------------------------------
    pip install pillow                 # 唯一的第三方依赖；tkinter 是 Python 自带
    # 如需指定 Python 3.14：
    #   py -3.14 -m pip install pillow
    # 检查环境是否 OK（不开窗口，只跑素材管线自检）：
    #   python desktop_pet.py --selftest

--------------------------------------------------------------------------------
 【运行】
--------------------------------------------------------------------------------
    python desktop_pet.py                     # 直接启动桌宠
    python desktop_pet.py --height 200        # 换一个宠物大小（像素高）
    python desktop_pet.py --pos 100,100       # 指定初始位置
    python desktop_pet.py --selftest          # 素材管线自检 + 生成预览拼图
    python desktop_pet.py --verbose           # 控制台打印状态机日志（答辩演示用）

--------------------------------------------------------------------------------
 【交互总览】
--------------------------------------------------------------------------------
    左键单击       → 随机开心动作 + 台词气泡（快乐值↑）
    左键拖拽       → 直接搬到桌面任意位置（多显示器可用）
    左键长按(0.4s) → 抚摸：快乐值持续上涨 + 开心反馈气泡
    鼠标悬停       → 歪头看向光标（跟随鼠标方向）+ 好奇气泡
    右键           → 菜单：对话 / 抚摸 / 喂食 / 睡觉 / 状态 / 退出
    右键「对话」   → 弹出输入框聊天，桌宠用可爱短句回复（可接大模型，见 ChatBrain）

--------------------------------------------------------------------------------
 【接入大模型（可选，30 秒搞定）】
--------------------------------------------------------------------------------
    桌宠默认用「本地关键词规则」聊天，不联网也能演示。
    想让它真正会聊天，二选一：
      A. 环境变量（推荐，最省事）：
           set DEEPSEEK_API_KEY=sk-xxxxxxxx        （Windows CMD）
           $env:DEEPSEEK_API_KEY="sk-xxxxxxxx"     （PowerShell）
      B. 配置文件：把 config.example.json 复制成 config.json，填 api_key
    然后启动时会自动检测并开启；也可以强制开关：
           python desktop_pet.py --llm on          强制开启
           python desktop_pet.py --llm off         强制关闭（纯本地规则）
           python desktop_pet.py --llm-test "你好"  只测接口，不开窗口
    支持 DeepSeek / OpenAI / Kimi / 智谱 / 通义 / 本地 Ollama，
    只依赖标准库 urllib，不需要 requests。

--------------------------------------------------------------------------------
 【已知局限】（详见文末演示文档，答辩时可以主动讲，显得很懂）
--------------------------------------------------------------------------------
    1. 色键透明是「硬边」方案（alpha 只有 0/255），宠物边缘没有半透明羽化；
       若要丝滑边缘需换 PySide6/PyQt 的 WA_TranslucentBackground。
    2. 色键要求像素颜色“精确”等于 KEY，因此宠物素材里不能出现 #FF00FE 这个颜色。
    3. 本机 Python 3.14.0a1 的 Pillow 12.3.0 轮子在 getpixel/load()/ImageDraw
       上会触发 0xC0000005 访问违例（已实测），所以本 Demo 的所有像素级操作
       全部改用 C 级批量算子（point/ImageChops/ImageFilter/convert(matrix)）实现，
       见 SafeImageOps 段落注释——这也是本项目一个隐藏的工程亮点。
    4. 气泡为 Tk Canvas 绘制，圆角是样条近似，没有抗锯齿。
    5. 逻辑与渲染同线程（tkinter 单线程），素材解码放在后台线程。

 作者：黑客松参赛原型 / 可自由修改
================================================================================
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import os
import queue
import random
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

# ==============================================================================
# 0. 依赖导入与兼容别名
# ==============================================================================
try:  # Pillow 是唯一第三方依赖
    from PIL import (Image, ImageChops, ImageEnhance, ImageFilter, ImageSequence,
                     ImageStat, ImageTk)

    HAVE_PIL = True
except Exception:  # pragma: no cover - 没装 Pillow 时给出人话提示
    HAVE_PIL = False

import tkinter as tk
from tkinter import font as tkfont


# ------------------------------------------------------------------------------
# 【启动健壮性】pythonw.exe（无控制台）下 sys.stdout / sys.stderr 是 None，
# 此时任何 print() 都会抛 AttributeError 让程序「一闪而过」。
# 所以第一件事就是把它们兜底成空流，并记下有没有控制台，
# 用于决定出错时是「打印日志」还是「弹窗告诉你」。
# ------------------------------------------------------------------------------
class _NullIO:
    """无声输出流：吞掉所有 print，避免 pythonw 下启动即崩。"""

    def write(self, *args, **kwargs):
        return 0

    def flush(self):
        pass

    def reconfigure(self, *args, **kwargs):
        pass

    def isatty(self):
        return False

    def close(self):
        pass


HAS_CONSOLE = (sys.stdout is not None) and (sys.stderr is not None)
if sys.stdout is None:
    sys.stdout = _NullIO()
if sys.stderr is None:
    sys.stderr = _NullIO()


# ------------------------------------------------------------------------------
# 【排障黑匣子】把「启动 / 退出 / 崩溃」全部写进 logs/desktop_pet.log
#   · 每条都立即落盘（开-写-关），所以哪怕进程被强杀，也已经留下证据
#   · faulthandler 能抓住 0xC0000005 这类「原生崩溃」（它不产生 Python 异常）
#   · 桌宠异常退出时，把最后 20 行日志发给开发者即可定位
# ------------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_PATH = os.path.join(LOG_DIR, "desktop_pet.log")
_log_fp = None
_console_handler_ref = None


def log_event(tag: str, msg: str = ""):
    """追加一条日志（每次开-写-关，保证被强杀时也不丢）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}][pid {os.getpid()}][{tag}] {msg}\n")
    except Exception:
        pass


def install_console_handler():
    """
    监听控制台事件：Ctrl+C、控制台窗口被关闭等。
    这些情况下 Python 可能来不及抛异常就被系统干掉，日志是唯一的线索。
    """
    if not HAS_CONSOLE:
        return
    try:
        import ctypes
        from ctypes import wintypes

        names = {0: "CTRL_C_EVENT（控制台里按了 Ctrl+C）",
                 1: "CTRL_BREAK_EVENT",
                 2: "CTRL_CLOSE_EVENT（控制台窗口被关闭 → 桌宠会一起结束）",
                 5: "CTRL_LOGOFF_EVENT（用户注销）",
                 6: "CTRL_SHUTDOWN_EVENT（系统关机）"}
        HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def _handler(ctrl_type):
            log_event("CONSOLE-EVENT", names.get(int(ctrl_type), str(ctrl_type)))
            return False          # False = 交回系统默认处理（该退还是退）
        global _console_handler_ref
        _console_handler_ref = HANDLER(_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler_ref, True)
        log_event("DIAG", "已注册控制台事件监听")
    except Exception as exc:
        log_event("DIAG", f"控制台事件监听注册失败: {exc}")


def install_diagnostics():
    """装上全局异常钩子与 faulthandler：任何死法都要留痕。"""
    global _log_fp
    log_event("START", f"argv={sys.argv[1:]} cwd={os.getcwd()} exe={sys.executable} "
                       f"console={HAS_CONSOLE} py={sys.version.split()[0]}")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _log_fp = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        import faulthandler
        faulthandler.enable(file=_log_fp, all_threads=True)   # 原生崩溃也能留下栈
    except Exception:
        _log_fp = None

    def _hook(exc_type, exc, tb):
        log_event("FATAL", "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = _hook

    install_console_handler()

    def _thread_hook(args):
        log_event("THREAD-FATAL", "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback)))
    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass

    try:
        import atexit
        atexit.register(lambda: log_event("ATEXIT", "解释器正常退出"))
    except Exception:
        pass


def show_fatal(title: str, message: str):
    """
    致命错误提示：有控制台就打印，没有控制台（pythonw / 双击运行）就弹窗。
    这样「双击后一闪而过」的情况会变成一个看得见的错误框，方便现场排障。
    """
    log_event("SHOW-FATAL", f"{title} :: {message[:400]}")
    try:
        print(f"[{title}] {message}", flush=True)
    except Exception:
        pass
    if HAS_CONSOLE:
        return
    try:
        from tkinter import messagebox
        box = tk.Tk()
        box.withdraw()
        box.attributes("-topmost", True)
        messagebox.showerror(title, message)
        box.destroy()
    except Exception:
        pass

# Pillow 10+ 把常量挪进了枚举，这里做一层兼容别名
if HAVE_PIL:
    try:
        RES_NEAREST = Image.Resampling.NEAREST
        RES_BILINEAR = Image.Resampling.BILINEAR
        RES_BICUBIC = Image.Resampling.BICUBIC
        RES_LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:  # 老版本 Pillow
        RES_NEAREST, RES_BILINEAR = Image.NEAREST, Image.BILINEAR
        RES_BICUBIC, RES_LANCZOS = Image.BICUBIC, Image.LANCZOS
    try:
        FLIP_LR = Image.Transpose.FLIP_LEFT_RIGHT
    except AttributeError:
        FLIP_LR = Image.FLIP_LEFT_RIGHT


# ==============================================================================
# 1. 全局配置（想改效果基本都在这里）
# ==============================================================================
class CFG:
    """集中配置。答辩时改这里就能演示不同参数，不用翻代码。"""

    # ---- 窗口几何 ----
    WIN_W = 300                 # 窗口宽（宠物居中）
    SPRITE_H = 210              # 宠物绘制区高度
    BUBBLE_ZONE = 145           # 顶部留给气泡的高度
    WIN_H = SPRITE_H + BUBBLE_ZONE
    BASE_LINE_GAP = 8           # 宠物脚底距窗口底部的距离
    BUBBLE_MAX_W = 224          # 气泡最大宽度
    BUBBLE_BOTTOM = BUBBLE_ZONE - 6   # 气泡底边 y（尾巴从这里指向宠物）

    # ---- 视觉 ----
    KEY_COLOR = "#ff00fe"       # 透明色键（挑一个素材里绝不会出现的怪色）
    BUBBLE_FILL = "#ffffff"
    BUBBLE_LINE = "#c9c9c9"
    BUBBLE_TEXT = "#3a3a3a"
    FONT_FAMILY = "Microsoft YaHei UI"
    FONT_SIZE = 10

    # ==================================================================
    # 第五阶段：UI 美化参数（所有颜色/尺寸/时长都放这里，方便现场调）
    # ==================================================================
    # ---- 总开关（性能差的机器可以一键关掉）----
    DECORATIONS = True          # 常驻装饰：阴影 / 等级徽章 / 状态图标条 / 经验条
    PARTICLE_EFFECTS = True     # 互动粒子：飘心 / 星星 / 气泡 / 礼花 / 乌云
    BUBBLE_TYPEWRITER = True    # 气泡打字机效果
    BUBBLE_ANIM = True          # 气泡淡入上浮动画
    CUSTOM_MENU = True          # 自定义右键面板（关掉则用系统原生菜单）
    UI_THEME = True             # Toplevel 面板统一主题

    # ---- 主题色（模块5）----
    UI_BG = "#fafafa"           # 面板背景
    UI_CARD = "#ffffff"         # 卡片底
    UI_LINE = "#e0e0e0"         # 卡片描边
    UI_LINE_HOVER = "#b388fc"   # 卡片悬停描边（主色）
    UI_MAIN = "#b388fc"         # 主色：紫粉
    UI_ACCENT = "#ff8fab"       # 辅助色：粉
    UI_TEXT = "#333333"
    UI_TEXT_DIM = "#777777"
    UI_BTN = "#f0f0f0"
    UI_BTN_HOVER = "#e0e0e0"
    UI_HOVER_BG = "#e3f2fd"     # 菜单项悬停底色
    UI_HOVER_TEXT = "#1565c0"   # 菜单项悬停文字

    # ---- 模块1：宠物装饰 ----
    SHADOW_ON = True
    SHADOW_W = 96               # 阴影椭圆宽
    SHADOW_H = 18               # 阴影椭圆高
    SHADOW_SHADES = ("#b9b3ae", "#cfcac5", "#e3dfdb")   # 由深到浅，模拟羽化
    BADGE_R = 12                # 等级徽章半径（直径 24）
    BADGE_LEVELS = ((16, "#ffd700", "#8a6d00"),   # (最低等级, 底色, 文字色)
                    (6, "#c0c0c0", "#5a5a5a"),
                    (1, "#cd7f32", "#ffffff"))
    BADGE_BOUNCE = 0.45         # 升级时徽章放大幅度
    ICON_R = 8                  # 状态小图标半径（16px 直径）
    ICON_GAP = 4                # 图标间距
    ICON_BAR_Y = 0              # 由代码按 BUBBLE_ZONE 计算
    ICON_DIM_ALPHA = 0.45       # 未悬停时的淡化程度（用颜色混合模拟）
    EXPBAR_W = 60               # 经验条宽
    EXPBAR_H = 4                # 经验条高
    EXPBAR_BG = "#e0e0e0"
    EXPBAR_COLORS = ("#b388fc", "#ff8fab")           # 渐变紫粉
    EXPBAR_FLASH = 0.6          # 升级时闪白光时长

    # ---- 模块2：气泡 ----
    BUBBLE_MIN_W = 80
    BUBBLE_PAD_X = 14
    BUBBLE_PAD_Y = 10
    BUBBLE_RADIUS = 16          # 胶囊形圆角
    BUBBLE_TYPE_SPEED = 0.030   # 每字 30ms
    BUBBLE_FADE_IN = 0.20       # 淡入 + 上浮时长
    BUBBLE_RISE = 5             # 上浮像素
    # 按情绪分主题：(底色, 描边色, 文字色)
    BUBBLE_THEMES = {
        "normal": ("#ffffff", "#dddddd", "#3a3a3a"),
        "happy": ("#fff0f3", "#ffc2d1", "#8c4a5c"),
        "warn": ("#fff8e1", "#ffd54f", "#8a6a1f"),
        "sad": ("#e3f2fd", "#90caf9", "#33526b"),
        "gold": ("#fff8e1", "#ffd700", "#8a6d00"),
    }
    BUBBLE_SPARKLE = True       # 升级/成就气泡加星光点缀

    # ---- 模块3：粒子 ----
    PARTICLE_MAX = 20           # 同屏粒子上限（对象池）
    HEART_COUNT = (3, 5)        # 点击飘心数量
    HEART_LIFE = 1.0
    HEART_COLOR_HAPPY = "#ff8fab"
    HEART_COLOR_SAD = "#bdbdbd"
    STAR_LIFE = 2.0
    STAR_COLOR = "#ffd54f"
    STAR_MAX_ON_PET = 10        # 抚摸时同屏最多星星
    EAT_BUBBLE_COUNT = 4
    EAT_BUBBLE_LIFE = 1.2
    CONFETTI_COUNT = 14         # 升级礼花数量
    CONFETTI_LIFE = 1.5
    CONFETTI_COLORS = ("#ff8fab", "#b388fc", "#ffd54f", "#64b5f6", "#81c784")
    CLOUD_INTERVAL = 5.0        # 生病时每 5 秒一朵乌云
    CLOUD_LIFE = 2.6
    DUST_INTERVAL = 0.32        # 走路扬尘间隔
    DUST_LIFE = 0.6
    DUST_COLOR = "#d8d2cc"

    # ---- 待机动画（超过 5 分钟没互动 → 自动进入放空/打瞌睡循环）----
    IDLE_ANIM_DELAY = 300.0     # 无互动多少秒后进入待机动画
    # ==================================================================
    # 第九阶段：程序化生成「呼吸待机动画」（不用 AI 生图，纯代码变换）
    # ==================================================================
    IDLE_BREATH_FRAMES = 6              # 一个呼吸循环几帧
    IDLE_BREATH_FRAME_MS = 400          # 每帧时长（6×400 = 2.4 秒一圈）
    IDLE_BREATH_SCALE_MAX = 1.03        # 吸气最大放大
    IDLE_BREATH_LIFT_MAX = 2            # 吸气最大上移像素
    # 6 帧参数表：(缩放, 上移像素(正数=往上), 倾斜角度)
    IDLE_BREATH_TABLE = ((1.000, 0, 0.0),      # 0 正常待机
                         (1.015, 1, 0.5),      # 1 吸气开始
                         (1.030, 2, 1.0),      # 2 吸气最大（肚子鼓起来）
                         (1.015, 1, 0.5),      # 3 呼气开始
                         (0.990, 0, -0.5),     # 4 呼气放松（略下沉）
                         (1.000, 0, 0.0))      # 5 回到原位
    IDLE_RANDOM_ACTION_INTERVAL = (30.0, 60.0)  # 随机小动作间隔（秒，原来 8~15 太频繁）
    IDLE_ACTION_DURATION = 1.2          # 每个小动作持续时长
    IDLE_TILT_MAX = 8.0                 # 歪头最大角度
    IDLE_DIM_BLINK = 0.85               # 眨眼时变暗程度
    IDLE_ACTION_KINDS = ("tilt", "look", "shake", "blink")
    IDLE_SHADOW_BREATH = 0.05           # 阴影随呼吸的宽度变化幅度
    IDLE_ANIM_DOZE_EVERY = 20.0         # 每隔多久打一会儿瞌睡
    IDLE_ANIM_DOZE_FOR = 9.0    # 每次瞌睡持续多久
    IDLE_ANIM_SWAY = 2.2        # 放空时左右轻晃幅度（度）
    IDLE_ANIM_ZZZ_EVERY = 7.0   # 冒 zzZ 的间隔
    IDLE_ANIM_LINES = ("（发呆中…）", "…zzZ", "（打了个哈欠）", "（尾巴轻轻晃）",
                       "（看着窗外发呆）", "（缩成一团）")

    # ---- 模块6：动画细节 ----
    WALK_TILT = 3.0             # 走路左右倾斜幅度（度）
    BREATH_SCALE = 1.02         # 待机呼吸缩放上限
    BREATH_PERIOD = 2.0         # 呼吸周期（秒）
    LOOK_DELAY = 0.20           # 眼神跟随延迟（秒）

    # ---- 模块4：自定义右键面板 ----
    MENU_ROW_H = 26             # 每行高度
    MENU_PAD = 6
    MENU_W = 176                # 菜单宽度
    MENU_FADE_MS = 100          # 淡入时长

    # ==================================================================
    # 第六阶段：桌面实用挂件（时钟 / 天气 / 网速）
    # ==================================================================
    SHOW_WIDGETS = True         # 挂件总开关
    SHOW_CLOCK = True
    SHOW_WEATHER = True
    SHOW_NET_SPEED = True
    WIDGET_SIDE = "right"       # "right"=宠物右侧 / "left"=宠物左侧
    PET_COL_W = 300             # 宠物所在列宽（原窗口宽）
    WIDGET_W = 132              # 挂件卡片宽
    WIDGET_H = 104              # 挂件卡片高（实际高度按行数自适应）
    WIDGET_GAP = 10             # 卡片与宠物间距
    WIDGET_LINE_H = 22          # 默认行高
    # 每行实际高度（钟点行字号大，要单独给高一点，否则会压到日期行）
    WIDGET_ROW_H = {"clock": 30, "date": 18, "weather": 22, "net": 20}
    WIDGET_PAD = 9
    PET_CX = 150                # 宠物中心 x（由 apply_layout 计算）
    # 卡片配色随时段变化：(底色, 描边, 主文字, 副文字)
    WIDGET_THEMES = {
        "day": ("#ffffff", "#e0e0e0", "#333333", "#777777"),
        "evening": ("#e3f2fd", "#bbdefb", "#2a4a63", "#5a7a93"),
        "night": ("#37474f", "#263238", "#ffffff", "#b0bec5"),
    }
    CHIME_ON_HOUR = True        # 整点报时
    CHIME_MEALS = ((12, "到饭点啦，记得吃饭哦～"), (18, "到饭点啦，记得吃饭哦～"))
    CHIME_SLEEP = (23, "很晚了，早点睡吧～")
    # ---- 天气 ----
    WEATHER_CITY = "武汉"
    WEATHER_LAT = 30.59
    WEATHER_LON = 114.31
    WEATHER_REFRESH_MIN = 10.0  # 每 10 分钟刷新
    WEATHER_TIMEOUT = 10.0      # open-meteo 在部分地区较慢，给足 10 秒
    # 备用源：open-meteo 不通时用它（国内可达性更好）
    WEATHER_FALLBACK_API = "https://wttr.in/{city}?format=j1"
    # 失败重试退避（秒）：第一次失败 15 秒后重试，逐次翻倍，封顶 5 分钟
    WEATHER_RETRY_BACKOFF = (15.0, 30.0, 60.0, 120.0, 300.0)
    WEATHER_API = ("https://api.open-meteo.com/v1/forecast"
                   "?latitude={lat}&longitude={lon}"
                   "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                   "&daily=temperature_2m_max,temperature_2m_min"
                   "&timezone=auto&forecast_days=1")
    # WMO 天气代码 → (emoji, 中文)
    WMO_MAP = {
        0: ("☀️", "晴"), 1: ("🌤️", "少云"), 2: ("⛅️", "多云"), 3: ("☁️", "阴"),
        45: ("🌫️", "雾"), 48: ("🌫️", "雾凇"),
        51: ("🌦️", "小毛雨"), 53: ("🌦️", "毛毛雨"), 55: ("🌧️", "密毛雨"),
        61: ("🌧️", "小雨"), 63: ("🌧️", "中雨"), 65: ("🌧️", "大雨"),
        66: ("🌧️", "冻雨"), 67: ("🌧️", "强冻雨"),
        71: ("🌨️", "小雪"), 73: ("🌨️", "中雪"), 75: ("❄️", "大雪"), 77: ("🌨️", "米雪"),
        80: ("🌦️", "阵雨"), 81: ("🌦️", "强阵雨"), 82: ("⛈️", "暴雨"),
        85: ("🌨️", "阵雪"), 86: ("❄️", "强阵雪"),
        95: ("⛈️", "雷雨"), 96: ("⛈️", "雷雨冰雹"), 99: ("⛈️", "强雷雨冰雹"),
    }
    # 穿衣建议：(温度上限, 建议)
    CLOTHING_BANDS = ((30.0, "天好热！穿短袖短裤就好，记得防晒～"),
                      (25.0, "有点热，穿短袖或薄T恤就行"),
                      (20.0, "舒服的天气！长袖T恤加薄外套刚刚好"),
                      (15.0, "有点凉啦，穿件厚外套或卫衣吧"),
                      (10.0, "冷了哦！风衣 / 厚卫衣安排上"),
                      (5.0, "很冷！羽绒服 + 毛衣别冻着"),
                      (-999.0, "超级冷！全副武装，手套围巾都带上"))
    # ---- 网速 ----
    NET_SAMPLE_INTERVAL = 1.0   # 采样间隔（秒）
    NET_FAST = 500.0            # 下载 > 此值（KB/s）→ 绿色
    NET_IDLE = 10.0             # 下载 < 此值 → 灰色
    NET_COLORS = ("#4caf50", "#333333", "#999999")   # 快 / 一般 / 闲置

    # ==================================================================
    # 第十阶段：视觉美化（在「完整挂件版」基础上只做外观打磨，不改布局）
    # ==================================================================
    COMPACT = False                 # ★ 回退：不再压缩尺寸 / 不隐藏装饰
    DEFAULT_PET_SIZE = 165          # 默认显示高度（回到原来大小）
    PET_SIZE_PRESETS = {"小": 120, "中": 145, "大": 165}
    PET_SIZE = 165                  # 当前显示高度
    COMPACT_WIN_W = 300
    COMPACT_BUBBLE_ZONE = 145
    COMPACT_BASE_GAP = 8
    COMPACT_BUBBLE_W = 224
    HOVER_DECOR_DELAY = 0.0         # 0 = 装饰常显
    HOVER_DECOR_FADE_OUT = 0.0
    DECOR_FADE_STEPS = 5
    WIDGET_ON_TOP = False           # ★ 回退：挂件仍在宠物右侧（多行卡片）
    WIDGET_LINE_H = 22
    WIDGET_ONTOP_PAD = 6
    WIDGET_ONTOP_BG = "#f5f5f5"
    WIDGET_ONTOP_LINE = "#e2e2e2"
    NET_HIDE_BELOW = 0.0            # 0 = 网速一直显示
    ULTRA_MODE = False
    ULTRA_PET_SIZE = 110
    ULTRA_BUBBLE_FONT = 9
    ULTRA_DIM = 0.95
    DRAG_DIM = 1.0                  # 拖拽不变暗
    BUBBLE_MS_NORMAL = 3.0          # 普通台词 3 秒（回退）
    BUBBLE_MS_IMPORTANT = 4.0
    EDGE_HIDE = False               # 回退：不做靠边隐藏
    EDGE_HIDE_THRESHOLD = 20
    EDGE_HIDE_PEEK = 0.45
    EDGE_SLIDE_BACK = 3.0
    MENU_COMPACT_W = 176
    MENU_PAGE1 = 99

    # ---- 美化参数（本轮唯一目的：好看一点，纯视觉）----
    UI_SHADOW = True                # 卡片/气泡/菜单下加柔和投影
    UI_SHADOW_STEPS = 3             # 投影分几层模拟羽化
    UI_SHADOW_COLOR = "#b4b9c2"     # 投影基色
    UI_SHADOW_OFFSET = 2            # 投影下移像素
    BUBBLE_GLOSS = True             # 气泡顶部高光条
    BADGE_GLOSS = True              # 等级徽章高光
    EXPBAR_CAP = True               # 经验条圆角收口
    WIDGET_SOFT = True              # 挂件卡片柔化（浅描边 + 圆角加大）
    WIDGET_DIVIDER = True           # 挂件卡片分组分隔线
    MENU_HOVER_RADIUS = 6           # 菜单悬停块圆角
    # ---- 面板滚动 ----
    PANEL_WHEEL_UNITS = 4           # 滚轮一格翻多少（Canvas 单位 = 1/10 可视高）
    PANEL_KEY_UNITS = 2             # ↑↓ 一次翻多少
    PANEL_PAGE_UNITS = 8            # PgUp/PgDn 一次翻多少
    PANEL_SCROLLBAR_W = 10          # 滚动条宽度

    @classmethod
    def apply_layout(cls, show_widgets: bool = None, side: str = None):
        """
        按「是否显示挂件 / 挂件位置 / 紧凑模式」重算窗口宽度与宠物中心 x。
        必须在建窗口之前调用（窗口宽度、精灵画布都依赖它）。
        紧凑模式下挂件贴宠物正上方 → 不占额外横向空间，窗口宽度就是 COMPACT_WIN_W。
        """
        if show_widgets is not None:
            cls.SHOW_WIDGETS = bool(show_widgets)
        if side in ("left", "right"):
            cls.WIDGET_SIDE = side
        if cls.COMPACT:
            cls.WIN_W = cls.COMPACT_WIN_W
            cls.BUBBLE_ZONE = cls.COMPACT_BUBBLE_ZONE
            cls.BASE_LINE_GAP = cls.COMPACT_BASE_GAP
            cls.BUBBLE_MAX_W = cls.COMPACT_BUBBLE_W
            cls.PET_COL_W = cls.COMPACT_WIN_W
            cls.PET_CX = cls.WIN_W // 2
        else:
            # 非紧凑：保持老逻辑（挂件在左右两侧时占横向空间）
            if cls.SHOW_WIDGETS and not cls.WIDGET_ON_TOP:
                extra = cls.WIDGET_W + cls.WIDGET_GAP
                cls.WIN_W = cls.PET_COL_W + extra
                cls.PET_CX = (cls.PET_COL_W // 2 + extra) if cls.WIDGET_SIDE == "left" \
                    else cls.PET_COL_W // 2
            else:
                cls.WIN_W = cls.PET_COL_W
                cls.PET_CX = cls.PET_COL_W // 2
        cls.WIN_H = cls.SPRITE_H + cls.BUBBLE_ZONE
        return cls.WIN_W, cls.PET_CX

    @classmethod
    def set_pet_size(cls, height: int):
        """切换宠物显示尺寸（只影响渲染缩放，不重切素材）"""
        cls.PET_SIZE = max(60, min(240, int(height)))
        return cls.PET_SIZE

    @classmethod
    def pet_scale(cls) -> float:
        """渲染缩放 = 目标高度 / 素材抠图高度"""
        ref = max(1, cls.PET_HEIGHT)
        return max(0.2, min(3.0, cls.PET_SIZE / ref))

    # ---- 时间 ----
    TICK_MS = 40                # 主循环 25 FPS
    TOPMOST_REASSERT = 3.0      # 每 3 秒重申一次置顶
    IDLE_AI_DELAY = 6.0         # 用户停止操作 6 秒后开始自主行为

    # ---- 窗口行为 ----
    NO_ACTIVATE = True          # 宠物永不抢焦点（点它时不会打断你正在打字的窗口）
    SHOW_IN_TASKBAR = False     # 是否出现在任务栏/Alt-Tab

    # ---- 素材 ----
    PET_HEIGHT = 165            # 宠物显示高度（px）
    GIF_STEP = 2                # 开心动图抽帧步长（116 帧 → 58 帧，降内存保流畅）

    # ---- 数值系统（每秒变化量）----
    # ★ 第七阶段：休闲化平衡 —— 全面放慢（原 0.35/0.55/0.30/0.60 太肝）
    DECAY_HAPPY = 0.07
    DECAY_FULL = 0.11
    DECAY_ENERGY = 0.06
    GROW_BORED = 0.12
    SLEEP_ENERGY_GAIN = 1.80

    # ==================================================================
    # 第七阶段：休闲小游戏 + 探险挂机 + 数值平衡
    # ==================================================================
    # ---- 小游戏 ----
    GAME_DAILY_LIMIT = 5            # 每个小游戏每天最多玩几次
    GAME_RPS_COOLDOWN = 3.0         # 猜拳每局冷却（秒）
    GAME_CATCH_TIME = 60.0          # 接星星时长
    GAME_CATCH_W = 240
    GAME_CATCH_H = 240
    GAME_CATCH_FALL = 46.0          # 星星下落速度（px/s）
    GAME_CATCH_SPAWN = 0.62         # 生成间隔（秒）
    GAME_CATCH_POOL = 12            # 星星对象池大小（复用，不每帧新建）
    GAME_CATCH_BAD_RATE = 0.22      # 坏星星比例
    GAME_CATCH_GOLD_RATE = 0.10     # 金色星星比例
    GAME_MOLE_TIME = 30.0           # 打地鼠时长
    GAME_MOLE_COOLDOWN = 0.55       # 打空后的冷却
    GAME_MEMORY_PAIRS = 6           # 记忆翻牌对数（12 张）
    GAME_MEMORY_EMOJI = ("🐸", "⭐", "🌙", "🍀", "🧸", "🍓")
    # ---- 第十一阶段：3 个经典单机小游戏 ----
    GAME_DAILY_LIMITS = {"tetris": 3, "mine": 3, "breakout": 3}   # 各自每日次数
    GAME_FPS_MS = 16                 # 游戏循环 ~60FPS
    # ① 俄罗斯方块
    TETRIS_COLS = 10
    TETRIS_ROWS = 20
    TETRIS_CELL = 20
    TETRIS_FALL_MS = 620             # 基础下落间隔
    TETRIS_FALL_MIN_MS = 130
    TETRIS_SPEEDUP_PER_LINE = 12     # 每消一行加快多少 ms
    TETRIS_LINE_COINS = 5
    TETRIS_LINE_EXP = 1
    TETRIS_HELP_USES = 3             # 每局道具次数
    TETRIS_FREEZE_MS = 5000          # 🧊 冰冻 5 秒
    TETRIS_PRANK_INTERVAL = 45.0     # 🐾 捣乱间隔
    TETRIS_DANGER_RATIO = 0.80       # 堆到 80% 就提醒
    TETRIS_IDLE_LINE_SEC = 30.0      # 多久没消行就催
    TETRIS_COLORS = {"I": "#00d8e0", "O": "#f0d000", "T": "#b060e0",
                     "S": "#3fc93f", "Z": "#e85050", "J": "#4a6cf0",
                     "L": "#f09830"}
    # ② 扫雷
    MINE_COLS = 9
    MINE_ROWS = 9
    MINE_COUNT = 10
    MINE_CELL = 32
    MINE_LIVES = 3                   # 踩 3 颗雷才 Game Over
    MINE_MISS_COINS = -5
    MINE_MISS_BOND = -3
    MINE_DETECT_USES = 3             # 探测器次数
    MINE_DETECT_FOOT = "#7a5230"     # 脚印颜色
    # 经典数字配色：1蓝 2绿 3红 4紫 5深红 6青 7黑 8灰
    MINE_NUM_COLORS = ("#000000", "#1565c0", "#2e7d32", "#c62828", "#6a1b9a",
                       "#8e0000", "#00838f", "#212121", "#757575")
    # ③ 弹球打砖块
    BREAKOUT_W = 300
    BREAKOUT_H = 400
    BREAKOUT_COLS = 10
    BREAKOUT_ROWS = 4
    BREAKOUT_BRICK_H = 14
    BREAKOUT_BRICK_GAP = 1
    BREAKOUT_TOP = 34
    BREAKOUT_LIVES = 3
    BREAKOUT_BRICK_COINS = 2
    BREAKOUT_PADDLE_SPEED = 400
    BREAKOUT_BALL_SPEED = 215
    BREAKOUT_BALL_R = 5
    BREAKOUT_POWER_CHANCE = 0.15
    BREAKOUT_POWER_KINDS = ("magnet", "multi", "slow", "life")
    BREAKOUT_POWER_FALL = 90.0
    BREAKOUT_WIDE_SEC = 10.0
    BREAKOUT_SLOW_SEC = 8.0
    BREAKOUT_COLORS = ("#ef5350", "#ffa726", "#66bb6a", "#42a5f5")
    # 奖励（结算）
    # ==================================================================
    # 第十二阶段：15 项扩展功能参数
    # ==================================================================
    # A1 日记
    DIARY_HOUR = 23                 # 每天 23 点写日记
    DIARY_ACHIEVEMENTS = (7, 30, 100)
    # A2 纪念日
    ANNIV_GIFT_COINS = 500
    # A4 记忆库
    MEMORY_MAX = 40
    MEMORY_PROMPT_N = 5
    # A5 情绪
    EMOTION_HUG_AFTER = 600.0       # 连续负面情绪多久后主动抱抱
    EMOTION_HUG_BOND = 5
    # B7 提醒
    WATER_REMIND_EVERY = 50 * 60
    SIT_REMIND_EVERY = 60 * 60
    # B8 待办
    TODO_SHOW_MAX = 3
    TODO_ALL_BOND = 10
    # B9 系统监控
    SYS_SAMPLE_EVERY = 30.0
    CPU_HIGH_RATIO = 0.90
    CPU_HIGH_HOLD = 10.0
    BATTERY_WARN = 20
    # C11 图鉴
    CODEX_PAGES = ("animal", "item", "place")
    CODEX_REWARD_COINS = 200
    # C12 扭蛋
    GACHA_PRICE = 100
    GACHA_DAILY = 10
    GACHA_DUP_REFUND = 30
    GACHA_ANIM_SEC = 2.0
    # C14 家具
    FURNITURE_GROUND_W = 64
    # C15 季节
    SEASON_FADE_SEC = 6.0
    # D17 天赋
    TALENT_LEVELS = (5, 10, 15, 20)
    TALENT_RESPEC_PRICE = 300
    TALENT_RESPEC_ALLOWED = True
    # D20 故事
    STORY_COINS = 120
    # 显示开关（第十二阶段：默认不挡桌面）
    SHOW_OUTFIT = False             # ★ 已按需求关闭：装扮不再画到奶蛙身上（只在换装小屋里预览）
    SHOW_TODO_NOTE = True           # 显示待办便签
    SHOW_SEASON_GROUND = True       # 显示季节地面色
    SKIN_DIR = "assets/skins"        # 皮肤素材目录（只在换装界面用）
    # ---- 装扮定位：按「素材自己的轮廓」算，换素材自动跟随 ----
    OUTFIT_EYE_DEPTH = 0.24         # 眼睛在轮廓顶往下多少（占轮廓高比例）
    OUTFIT_HAT_OVER = 0.03          # 帽子压进轮廓顶部多少
    OUTFIT_BACK_DEPTH = 0.55        # 披风/翅膀在轮廓中部
    OUTFIT_LENS_W = 0.30            # 镜片直径 / 轮廓半宽（实测眼睛约占 0.3）
    OUTFIT_EYE_SPREAD = 0.20        # 两个镜片中心到中线的距离 / 轮廓半宽
    OUTFIT_HIDE_ON_LYING = True     # 趴睡等躺姿素材不戴眼镜（看不到眼睛）
    # 这些素材看不见眼睛（趴睡背影 / 被手挡住），自动不戴眼镜
    OUTFIT_NO_GLASSES = ("sleep_b", "pat", "sick")
    EYE_R_MIN = 0.012               # 识别到的眼睛半径下限（占图宽）
    EYE_R_MAX = 0.095               # 上限；超出视为误判（整块身体）
    OUTFIT_LYING_RATIO = 0.55       # 轮廓高/图高 小于此值视为躺姿
    # ---- 无互动时更安静（减少移动与素材切换，避免打扰）----
    IDLE_DECIDE_INTERVAL = (14.0, 30.0)   # 自主决策间隔（原 4~9 秒）
    IDLE_WALK_WEIGHT = 1                  # 散步权重（原 4）
    IDLE_WALK_DUR = (3.0, 6.0)            # 散步时长
    IDLE_SELFTALK_RATE = 0.35             # 自言自语概率（原 0.65）
    IDLE_NAP_WEIGHT = 4                   # 打盹权重（原 1，更爱安静待着）
    LOOK_DELAY_IDLE = 0.9                 # 空闲时眼神翻转更慢
    STORY_BOND = 30
    GAME_RARE_POOL = ("稀有种子", "鸭鸭明信片", "松果帽子", "奶蛙之铃", "限定围巾")
    GAME_MEDAL_ITEM = "打砖块冠军奖牌"
    GAME_DOUBLE_ITEM = "幸运饼干"    # 吃掉它 → 当天游戏奖励 x2
    GAME_DOUBLE_HOURS = 24
    # ---- 探险挂机档位：(名称, 秒数, 精力消耗倍率) ----
    ADVENTURE_DURATIONS = (("短途", 30, 1.0), ("中途", 600, 2.0),
                           ("长途", 3600, 3.0), ("过夜", 28800, 5.0))
    ADVENTURE_OFFLINE_CAP = 28800.0     # 离线收益封顶 8 小时
    ADVENTURE_OFFLINE_SETTLE = True     # True=启动时到点直接结算
    ADVENTURE_EXP_PER_TRIP = 5          # 每去一次该地点 +5 熟练度
    ADVENTURE_EXP_MAX = 100             # 熟练度上限（满则掉落升一档）
    ADVENTURE_BOOST_ITEM = "探险指南针"   # 下一次探险收益 x2
    ADVENTURE_BOOST_MULT = 2.0
    # ---- 休闲化：自动恢复与保护 ----
    SAD_AUTOHEAL_AT = 20.0          # 心情低于此值 → 自动缓慢回升
    SAD_AUTOHEAL_RATE = 0.2         # 每 5 秒回 1 点
    SICK_SAFE_FULL = 50.0           # 饱食高于此值不会随机生病
    BORED_AUTOSLEEP_AT = 80.0       # 无聊高于此值且无人互动 → 自动睡觉
    OFFLINE_DECAY_PROTECT = True    # 关程序期间衰减暂停
    OFFLINE_FULL_RATE = 0.02        # 离线时「每小时掉当前饱食的 2%」（8 小时≈掉 13 点）
    OFFLINE_MAX_HOURS = 8.0         # 离线结算最多按这么久算
    NEWBIE_LEVEL = 5                # 这个等级以下算新手
    NEWBIE_DECAY_MULT = 0.5         # 新手衰减减半
    NEWBIE_SAFE_DAYS = 3            # 前 N 天不会生病

    # ---- 阈值 ----
    HUNGRY_AT = 25.0            # 饱食低于此值 → 饥饿
    SLEEPY_AT = 22.0            # 精力低于此值 → 困倦
    BORED_AT = 78.0             # 无聊高于此值 → 无聊踱步
    FULL_REFUSE = 88.0          # 饱食高于此值 → 拒绝进食

    # ---- 喂食 / 赠送（只能操作背包物品）----
    GIFT_HAPPY = 6              # 送礼加的心情
    GIFT_FAVORITE_BONUS = 1.6   # 「最爱礼物」好感倍率
    # 奶蛙最爱的礼物（好感加成 + 专属台词）
    GIFT_FAVORITES = ("草莓蛋糕", "音乐盒", "野花", "珍珠奶茶", "逗猫棒")
    # 这些是任务信物 / 探险装备，不能送人（送了会卡任务或丢 buff）
    GIFT_BLOCKED = ("藏宝图碎片", "奶蛙之铃", "松果帽子", "鸭鸭明信片",
                    "便当", "手电筒", "指南针", "雨伞", "大背包")
    GIFT_PRICE_RATE = 0.22      # 没有显式 gift_bond 时，按价格折算好感

    # ---- 身体状况（第二阶段扩展）----
    MOOD100_AT = 95.0           # 心情 >= 此值 → 播放「心情100」动画
    MOOD50_AT = 50.0            # 心情 <= 此值 → 播放「心情50」动画
    MOOD20_AT = 20.0            # 心情 <= 此值 → 播放「心情20」动画（失落）
    MOOD0_AT = 0.5              # 心情 <= 此值 → 播放「心情0」动画 + 伤感文案
    SICK_BAND = (38.0, 62.0)    # 饱食落在这个区间时，每隔一段时间掷一次骰子
    SICK_CHANCE = 0.08          # 掷中生病的概率（休闲化：0.20 → 0.08）
    SICK_ROLL_EVERY = 120.0     # 掷骰间隔（秒，休闲化：18 → 120）
    RESLEEP_DELAY = 5.0         # 被强行叫醒后，无互动多少秒再次自动入睡
    SAD_REPEAT = 13.0           # 低心情时每隔多久自动冒一次伤感文案
    SICK_PENALTY = 1.6          # 生病时心情/精力衰减倍率

    # ---- 聊天里讲笑话的节奏控制（用户要求：正常聊天为主，偶尔才讲笑话）----
    CHAT_JOKE_CHANCE = 0.07     # 每次聊天的「讲笑话」概率（约 14 句里 1 次）
    CHAT_JOKE_COOLDOWN = 300.0  # 两次笑话至少间隔 5 分钟
    CHAT_JOKE_MIN_MSGS = 8      # 至少先正常聊 8 句，才可能出现笑话

    # ==================================================================
    # 第三阶段：养成系统参数
    # ==================================================================
    # ---- 模块1 等级与经验 ----
    LEVEL_MAX = 30              # 等级上限（满级大佬成就按 Lv.20 判定）
    EXP_BASE = 50.0             # 升级经验公式基数：exp_to_next = EXP_BASE * level^EXP_POW
    EXP_POW = 1.5
    EXP_ON_CLICK = 2            # 各互动给的经验（喂食 > 抚摸 > 聊天 > 点击）
    EXP_ON_PET_PER_SEC = 3.0    # 抚摸按秒给
    EXP_ON_FEED = 12
    EXP_ON_CHAT = 6
    EXP_ON_TREAT = 15
    EXP_ON_PLAY = 10            # 使用玩具
    EXP_ON_GIFT = 9             # 赠送礼物
    LEVEL_DECAY_RELIEF = 0.03   # 每升 1 级，四维衰减慢 3%
    LEVEL_DECAY_FLOOR = 0.45    # 衰减倍率下限（最多慢到 45%）

    # ---- 模块2 金币与背包 ----
    COINS_START = 100           # 初始金币
    COINS_ON_CLICK = 1          # 各互动给的金币
    COINS_ON_FEED = 2
    COINS_ON_CHAT = 2
    COINS_ON_PET_PER_SEC = 0.5
    COINS_ON_LEVELUP = 30       # 升级奖励
    COINS_DAILY_LOGIN = 20      # 每日登录奖励
    AUTOSAVE_EVERY = 60.0       # 自动存档间隔（秒）

    # ---- 模块3 亲密度 ----
    BOND_MAX = 1000.0
    BOND_ON_PET_PER_SEC = 1.2   # 抚摸加得最多
    BOND_ON_CHAT = 1.0
    BOND_ON_FEED = 0.8
    BOND_ON_CLICK = 0.4
    BOND_DAILY_FIRST_BONUS = 5.0    # 每天第一次互动的额外加成
    BOND_DECAY_PER_HOUR = 2.0       # 长期不互动缓慢下降（远慢于获取）
    BOND_FOLLOW_AT = 600.0          # 亲密度达到此值 → 主动靠近鼠标
    BOND_HUG_AT = 300.0             # 解锁「抱抱」特殊互动
    # 亲密度等级：门槛从小到大
    BOND_TIERS = [(0, "陌生人"), (100, "熟人"), (300, "朋友"),
                  (600, "好朋友"), (1000, "亲密伙伴")]

    # ---- 模块4 成就 ----
    ACHIEVEMENT_COIN_BONUS = 1.0    # 成就金币按定义发放（此处留作倍率）
    ACHIEVEMENT_CHECK_EVERY = 4.0   # 每隔几秒检查一次成就条件

    # ---- 模块5 成长形态 ----
    #   (最低等级, 名称, 体型缩放倍率)——素材缺失时用现有 idle 图等比缩放代替
    GROWTH_STAGES = [(16, "成年形态", 1.16), (6, "少年形态", 1.0), (1, "幼年形态", 0.76)]
    GROWTH_ANIM_SEC = 2.6           # 形态切换过渡动画时长

    # ---- 模块6 每日任务 ----
    DAILY_TASK_COUNT = 3            # 每天随机几个任务

    # ---- 模块7 存档 ----
    SAVE_FILE = "savegame.json"
    SAVE_VERSION = 2

    # ==================================================================
    # 第四阶段：外出探险系统
    # ==================================================================
    ADVENTURE_MODE = "bar"          # 探险中表现： "bar"=原地站着+头顶进度条(A) / "hide"=隐藏窗口(B)
    ADVENTURE_EVENT_CHANCE = 0.30   # 每次探险触发随机事件的概率
    ADVENTURE_COOLDOWN = 3.0        # 结算后多少秒才能再次出发（防刷）
    ADVENTURE_HUNGRY_FULL = 30.0    # 饱食低于此值 → 本次收益减半
    ADVENTURE_LOW_ENERGY = 10.0     # 探险中精力低于此值 → 累到提前回家（收益减半）
    ADVENTURE_EARLY_RATIO = 0.5     # 提前回家 / 累计减半时的收益倍率
    ADVENTURE_DAILY_BONUS = 30      # 每天第一次探险的额外金币
    ADVENTURE_LEGENDARY_ONCE = True # 传说掉落每件只能获得一次
    ADVENTURE_SAVE_PARTIAL = True   # True=退出时正在探险直接结算一半收益；False=下次启动继续倒计时
    ADVENTURE_BAG_LIMIT = 6         # 单次探险默认最多带回几件物品（大背包 +2）
    ADVENTURE_BAG_BONUS = 2         # 「大背包」道具的额外上限
    ADVENTURE_MIN_ITEMS = 2         # 单次探险最少掉落件数
    ADVENTURE_MAX_ITEMS = 4         # 最多掉落件数（再受背包上限约束）
    ADVENTURE_ITEMS_SCALE = 0.35    # 有多少件物品要「完成 1 件后掷骰再要 1 件」的概率
    # 掉率分层：累计概率 → 档位名
    ADVENTURE_TIERS = ((0.70, "common"), (0.90, "rare"), (0.98, "epic"), (1.00, "legendary"))
    ADVENTURE_REWARD_MULT_BELL = 1.5   # 持有「奶蛙之铃」时探险收益倍率
    ADVENTURE_EXP_BASE = 12         # 探险基础经验，按地点时长再放大
    ADVENTURE_BOND_BASE = 2.0       # 探险基础亲密度


# ==============================================================================
# 2. SafeImageOps —— 「无像素访问」安全图像算子
# ==============================================================================
# 【为什么要有这一段？】
#   本机 Python 3.14.0a1 + Pillow 12.3.0 实测：任何「逐像素访问」都会让进程
#   直接 0xC0000005 崩溃（Access Violation），包括：
#       img.getpixel(x,y) / img.load() / img.putpixel / ImageDraw.Draw(...).xxx
#   而下面这些 C 级批量算子是安全的（已逐个实测通过）：
#       open / convert / resize / rotate / transpose / paste / copy
#       putalpha / getchannel / point(查表) / convert("L", matrix)
#       ImageChops.* / ImageFilter.* / ImageEnhance.* / Image.alpha_composite
#   因此：抠图（背景转透明）完全用「查表 + 逻辑运算 + 形态学 + 连通域扩散」实现，
#   一次像素循环都不写，同时也比 Python 逐像素快几百倍。
# ==============================================================================
WHITE_RGB = (255, 255, 255)
MAT_SUM = (1.0, 1.0, 1.0, 0.0)          # RGB→L：三通道求和（白度/暗度量）
MAT_WARM = (-1.0, 0.0, 1.0, 128.0)      # RGB→L：(B-R)+128，<128 偏暖(宠物)，=128 中性(背景)
LUT_HARD = [0 if v < 128 else 255 for v in range(256)]   # alpha 硬化：0/255 二值化（防色键毛边）


class SafeImageOps:
    """全部只使用 C 级批量算子的图像工具箱。"""

    @staticmethod
    def white_sum(rgb: "Image.Image") -> "Image.Image":
        """离纯白有多远（0=纯白背景，越大=越像宠物/阴影）。"""
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, WHITE_RGB))
        return diff.convert("L", MAT_SUM)

    @staticmethod
    def warmth(rgb: "Image.Image") -> "Image.Image":
        """冷暖度：(B-R)+128。<128 偏暖=宠物皮肤；≈128 中性灰=背景/地面阴影。"""
        return rgb.convert("L", MAT_WARM)

    @staticmethod
    def _border_seed(mask: "Image.Image") -> "Image.Image":
        """取图像最外一圈作为「背景种子」。"""
        w, h = mask.size
        seed = Image.new("L", (w, h), 0)
        seed.paste(mask.crop((0, 0, w, 1)), (0, 0))
        seed.paste(mask.crop((0, h - 1, w, h)), (0, h - 1))
        seed.paste(mask.crop((0, 0, 1, h)), (0, 0))
        seed.paste(mask.crop((w - 1, 0, w, h)), (w - 1, 0))
        return seed

    @staticmethod
    def _same(a: "Image.Image", b: "Image.Image") -> bool:
        """两张掩膜是否完全相同（用 difference+getbbox，避开像素访问）。"""
        return ImageChops.difference(a, b).getbbox() is None

    @classmethod
    def flood_from(cls, mask: "Image.Image", seed_mode: str = "border", ratio: float = 0.12,
                   scale: int = 4) -> "Image.Image":
        """
        通用「连通域扩散」：在 mask=255 的区域里，从种子出发按测地膨胀铺开。
        seed_mode="border" 从图像最外一圈出发（吃背景）；
        seed_mode="center" 从画面正中一小块出发（只留与中心连通的前景）。

        【坑】种子必须「在缩小后的小图上」构造：
        如果在全分辨率上取 1 像素宽的边框再缩小 4 倍，NEAREST 采样会把它整条丢掉，
        种子变空 → 一个像素都扩散不出去（实测踩过）。
        """
        w, h = mask.size
        sw, sh = max(2, w // scale), max(2, h // scale)
        small = mask.resize((sw, sh), RES_NEAREST)
        if seed_mode == "center":
            seed_small = Image.new("L", (sw, sh), 0)
            bw, bh = max(1, int(sw * ratio)), max(1, int(sh * ratio))
            seed_small.paste(255, (sw // 2 - bw // 2, sh // 2 - bh // 2,
                                   sw // 2 + bw // 2, sh // 2 + bh // 2))
        else:
            seed_small = cls._border_seed(small)
        fill = ImageChops.darker(seed_small, small)
        for _ in range(400):                     # 粗尺度：通常几十轮就收敛
            grown = ImageChops.darker(fill.filter(ImageFilter.MaxFilter(9)), small)
            if cls._same(grown, fill):
                break
            fill = grown
        # 放大回原尺寸后先腐蚀 1px（去掉 NEAREST 放大带来的“多吃”），再精修
        full = fill.resize((w, h), RES_NEAREST).filter(ImageFilter.MinFilter(3))
        for _ in range(400):
            grown = ImageChops.darker(full.filter(ImageFilter.MaxFilter(3)), mask)
            if cls._same(grown, full):
                break
            full = grown
        return full

    @classmethod
    def flood_from_border(cls, cand: "Image.Image", scale: int = 4) -> "Image.Image":
        """从图像最外一圈出发的连通域扩散（用来吃掉背景）。"""
        return cls.flood_from(cand, "border", scale=scale)

    @classmethod
    def flood_from_center(cls, mask: "Image.Image", ratio: float = 0.12,
                          scale: int = 4) -> "Image.Image":
        """
        从「画面正中一小块」出发的连通域扩散。
        适合「宠物在中央、背景是复杂场景」的素材（素材5）：
        只有和中心连通的区域才算宠物，孤立的背景碎片一律丢掉。
        """
        return cls.flood_from(mask, "center", ratio=ratio, scale=scale)

    @staticmethod
    def border_refs(rgb: "Image.Image", gate: float = 35.0, verbose: bool = False):
        """
        从四条边推断「背景参考色」。
        【关键】只在「这条边足够均匀」时才采用它的中位色：
        宠物身体常常压到图片下边缘，那条边的中位色其实是宠物颜色，
        直接拿来当背景会把宠物整只抠掉（实测踩过这个坑）。
        """
        w, h = rgb.size
        band = max(2, min(w, h) // 25)
        strips = [("上", rgb.crop((0, 0, w, band))), ("下", rgb.crop((0, h - band, w, h))),
                  ("左", rgb.crop((0, 0, band, h))), ("右", rgb.crop((w - band, 0, w, h)))]
        refs = []
        for name, s in strips:
            st = ImageStat.Stat(s)
            sd = max(st.stddev)
            if sd <= gate:
                refs.append(tuple(int(v) for v in st.median))
            if verbose:
                print(f"      {name}: median={[int(v) for v in st.median]} sd={sd:.1f}"
                      f"{' →采用' if sd <= gate else ' →跳过(不均匀)'}", flush=True)
        return refs

    @classmethod
    def cut_out(cls, rgba: "Image.Image", mode: str = "border", tol: int = 110,
                close: int = 9, gate: float = 35.0, keep_warm: int = 106,
                bright: int = 120, extra_refs=()) -> "Image.Image":
        """
        抠图（四种模式，全部只用 C 级批量算子）：

        · border —— 通用：四条边中位色 + 纯白 作为背景参考色，取「够接近参考色」的像素
                    作候选，再从图像边缘做连通域扩散，只吃掉与边相连的背景。
        · warm   —— 场景图专用：只保留「偏暖」的像素（黄/棕/粉），剔掉冷灰场景。
        · center —— 复杂场景专用（素材5 心情0）：先把「偏暖 or 够亮」的像素当作前景候选，
                    再只保留与画面中心连通的部分 —— 孤立的场景碎片（展柜、雕像）自动丢掉。
        · alpha  —— 直接用素材自带的透明通道（GIF 本身带透明时最准，如素材10）。

        各模式之后都会做形态学闭运算，封掉浅色高光造成的细小漏缝。
        """
        rgb = rgba.convert("RGB")
        src_alpha = rgba.getchannel("A")
        has_src_alpha = src_alpha.getextrema()[0] < 200     # 素材自带透明信息

        if mode == "alpha" and has_src_alpha:
            out = rgba.copy()
            out.putalpha(src_alpha.point(LUT_HARD))
            return out

        if mode in ("warm", "center"):
            lut_w = [255 if v <= keep_warm else 0 for v in range(256)]
            pet = cls.warmth(rgb).point(lut_w)
            if mode == "center":
                # 亮度也当作前景证据（奶蛙的白色肚皮不够「暖」）
                lut_b = [255 if v >= bright else 0 for v in range(256)]
                pet = ImageChops.lighter(pet, rgb.convert("L").point(lut_b))
                pet = cls.flood_from_center(pet)             # ★ 只留和中心连通的
        else:                                               # border（含 alpha 退化）
            refs = cls.border_refs(rgb, gate) + [WHITE_RGB] + [tuple(r) for r in extra_refs]
            lut = [255 if v <= tol else 0 for v in range(256)]
            mask = None
            for ref in refs:
                d = ImageChops.difference(rgb, Image.new("RGB", rgb.size, ref)).convert("L", MAT_SUM)
                m = d.point(lut)
                mask = m if mask is None else ImageChops.lighter(mask, m)
            bg = cls.flood_from_border(mask).filter(ImageFilter.MedianFilter(3))
            pet = ImageChops.invert(bg)

        pet = pet.filter(ImageFilter.MaxFilter(close)).filter(ImageFilter.MinFilter(close))
        if has_src_alpha:                                   # 素材自带透明 → 再求个交集
            pet = ImageChops.darker(pet, src_alpha.point(LUT_HARD))
        out = rgba.copy()
        out.putalpha(pet.point(LUT_HARD))      # 二值 alpha：只留 0/255，避免色键毛边
        return out

    @staticmethod
    def fit_height(img: "Image.Image", height: int) -> "Image.Image":
        """等比缩放到指定高度（LANCZOS 高质量）。"""
        w = max(1, round(img.width * height / img.height))
        return img.resize((w, height), RES_LANCZOS)

    @staticmethod
    def keyed_rgb(rgba: "Image.Image", key_rgb) -> "Image.Image":
        """
        把 RGBA 拍平到色键底色上并转成 RGB：
        透明处 = 正好等于 KEY_COLOR 的纯色 → 被 Windows 分层窗口抠掉；
        不透明处 = 宠物原始颜色（无半透明混合，因此不会出现紫边）。
        """
        back = Image.new("RGBA", rgba.size, tuple(key_rgb) + (255,))
        return Image.alpha_composite(back, rgba).convert("RGB")


# ==============================================================================
# 3. AssetLibrary —— 素材加载 / 抠图 / 磁盘缓存 / 后台解码
# ==============================================================================
# 素材角色分工（每次都用「用户给的原始图」，不额外创作美术）
#   ── 第一批 4 张 ──────────────────────────────────────────────────────────
#   idle    平常表情（待机/散步/发呆/无聊）
#   happy   第 1 张动图（点击开心、蹦跳）
#   talk    大笑（对话中）
#   eat     喝奶茶（进食）
#   ── 第二批 11 张（用户后续提供）──────────────────────────────────────────
#   think     素材1  回答/思考前的动作
#   mood100   素材2  心情 = 100
#   mood50    素材3  心情 = 50
#   joke      素材4  讲笑话搞怪
#   mood0     素材5  心情 = 0（配伤感文案，可点击刷新）
#   mood20    素材6  心情 = 20
#   sleep_b   素材7  睡觉动作 B（和原睡觉动画可点按切换）
#   sick      素材8  生病（饱食 50 时概率触发）
#   allzero   素材9  四项状态全部归零的特殊动画
#   pat       素材10 抚摸专用动画
#   hungry0   素材11 饱食 = 0
ASSETS = {
    # ---- 第一批 ----
    "idle": dict(kind="static", profile="white",
                 names=["assets/pet_idle.webp", "assets/pet_idle.png",
                        "6a024455af779H8Y.webp", "pet_idle.webp"]),
    "talk": dict(kind="static", profile="white",
                 names=["assets/pet_talk.webp", "assets/pet_talk.png",
                        "download.webp", "pet_talk.webp"]),
    "eat": dict(kind="static", profile="white",
                names=["assets/pet_eat.webp", "assets/pet_eat.png",
                       "OIP-C.webp", "pet_eat.webp"]),
    "happy": dict(kind="gif", profile="white",
                  names=["assets/pet_happy.gif", "OGC.gif", "pet_happy.gif"]),
    # ---- 第二批 ----
    "think": dict(kind="static", profile="white", names=["assets/pet_think.webp"]),
    "mood100": dict(kind="static", profile="white", names=["assets/pet_mood100.webp"]),
    "mood50": dict(kind="static", profile="white", names=["assets/pet_mood50.webp"]),
    "joke": dict(kind="static", profile="white", names=["assets/pet_joke.webp"]),
    "mood0": dict(kind="gif", profile="center", names=["assets/pet_mood0.gif"]),
    "mood20": dict(kind="static", profile="border", names=["assets/pet_mood20.webp"]),
    "sleep_b": dict(kind="static", profile="white", names=["assets/pet_sleep_b.webp"]),
    "sick": dict(kind="static", profile="border", names=["assets/pet_sick.webp"]),
    "allzero": dict(kind="static", profile="white", names=["assets/pet_allzero.webp"]),
    "pat": dict(kind="gif", profile="alpha", names=["assets/pet_pat.gif"]),
    "hungry0": dict(kind="static", profile="tight", names=["assets/pet_hungry0.webp"]),
    # ---- 程序化生成的呼吸待机动画（不需要外部文件，由 IdleAnimationGenerator 生成）----
    "idle_anim": dict(kind="procedural", profile="white", generated_from="idle", names=[]),
    # ---- 模块5 成长形态专用素材（用户后续提供；缺失时自动用现有素材等比缩放代替）----
    "stage_baby": dict(kind="static", profile="white", optional=True,
                       names=["assets/pet_stage_baby.webp", "assets/baby_jr.webp"]),
    "stage_adult": dict(kind="static", profile="white", optional=True,
                        names=["assets/pet_stage_adult.webp", "assets/adult.webp"]),
    # ---- 物品图标（可选；缺失时背包/商店显示纯文字，功能完全不受影响）----
    "item_milktea": dict(kind="static", profile="white", optional=True,
                         names=["assets/item_milktea.webp"]),
    "item_cake": dict(kind="static", profile="white", optional=True,
                      names=["assets/item_cake.webp"]),
    "item_meal": dict(kind="static", profile="white", optional=True,
                      names=["assets/item_meal.webp"]),
    "item_ball": dict(kind="static", profile="white", optional=True,
                      names=["assets/item_ball.webp"]),
    "item_wand": dict(kind="static", profile="white", optional=True,
                      names=["assets/item_wand.webp"]),
    "item_music": dict(kind="static", profile="white", optional=True,
                       names=["assets/item_music.webp"]),
    "item_cookie": dict(kind="static", profile="white", optional=True,
                        names=["assets/item_cookie.webp"]),
    "item_revive": dict(kind="static", profile="white", optional=True,
                        names=["assets/item_revive.webp"]),
}
# 抠图参数档位（tol=颜色容差, gate=边框均匀度阈值, keep_warm=暖色保留阈值）
PROFILES = {
    "white": dict(mode="border", tol=95, gate=35, close=9),      # 影棚白底（第一批素材）
    "border": dict(mode="border", tol=130, gate=42, close=9),    # 彩色/渐变底
    "tight": dict(mode="border", tol=20, gate=22, close=25),      # 浅色宠物 + 浅灰底（素材11）
    "warm": dict(mode="warm", keep_warm=106, close=9),
    "center": dict(mode="center", keep_warm=104, bright=150, close=9),   # 复杂场景（素材5）
    "alpha": dict(mode="alpha", close=9),                        # 素材自带透明（素材10）
}
CACHE_VERSION = "v9"            # 改抠图算法时 +1，自动失效旧缓存


def app_dir() -> str:
    """脚本所在目录（兼容 PyInstaller 打包后的路径）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_asset(name: str, candidates) -> str | None:
    """
    只在**本程序自己的目录**里找素材，避免误用桌面/下载里的其它副本。

    搜索顺序（前两个是正规布局）：
        <脚本目录>/assets/<名字>
        <脚本目录>/<名字>
        <脚本目录>/src/<名字>

    兼容旧需求：设置环境变量 DP_ALLOW_EXTERNAL_ASSETS=1 才会额外搜索
    桌面 / 下载 / 当前工作目录，并且命中时会打 [ASSET-WARN] 告警。
    """
    local_roots = [os.path.join(app_dir(), "assets"), app_dir(),
                   os.path.join(app_dir(), "src")]
    roots = list(local_roots)
    if os.environ.get("DP_ALLOW_EXTERNAL_ASSETS", "").strip() in ("1", "true", "yes"):
        roots += [os.path.expanduser("~/Desktop"), os.path.expanduser("~/Downloads"),
                  os.getcwd()]
    for rel in candidates:
        if os.path.isabs(rel) and os.path.isfile(rel):
            return rel
        for root in roots:
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                p = os.path.abspath(p)
                if root not in local_roots:
                    try:
                        log_event("ASSET-WARN", f"{name} 用了外部素材：{p}")
                    except Exception:
                        pass
                return p
    return None


class AssetLibrary:
    """负责把 4 张素材变成「已经抠好背景、尺寸统一」的 RGBA 帧，并做磁盘缓存。"""

    def __init__(self, cfg=CFG):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.data: dict[str, dict] = {}          # name -> {frames:[RGBA], durations:[ms], ready:bool}
        self.paths: dict[str, str] = {}
        self.cache_root = os.path.join(tempfile.gettempdir(), "desktop_pet_cache")
        self.warnings: list[str] = []

    # ---------- 对外接口 ----------
    def get(self, name: str):
        with self.lock:
            d = self.data.get(name)
            if not d:
                return []
            return d["frames"]

    def durations(self, name: str):
        with self.lock:
            d = self.data.get(name)
            return list(d["durations"]) if d else []

    def is_ready(self, name: str) -> bool:
        with self.lock:
            return bool(self.data.get(name, {}).get("ready"))

    # ---------- 主流程 ----------
    def prepare_sync(self):
        """同步加载全部「静态」素材（毫秒级），保证窗口一出现就有形象。
        加载完再程序化生成「呼吸待机动画」（缓存命中时几乎零耗时）。"""
        for name, spec in ASSETS.items():
            if spec["kind"] == "static":
                self._load_one(name)
        # ★ 第九阶段：基于 idle 生成呼吸动画帧
        try:
            self.idle_gen = IdleAnimationGenerator(self, self.cfg)
            self.idle_gen.ensure()
        except Exception:
            log_event("IDLE-ANIM", "生成异常，退回静态 idle\\n" + traceback.format_exc())

    def prepare_gif_async(self):
        """动图帧数多，全部放后台线程处理，避免开窗口时卡顿。"""
        t = threading.Thread(target=self._load_all_gifs, name="gif-loader", daemon=True)
        t.start()
        return t

    def _load_all_gifs(self):
        for name, spec in ASSETS.items():
            if spec["kind"] == "gif":
                self._load_one(name)

    # ---------- 内部实现 ----------
    def _cache_key(self, path: str, spec: dict) -> str:
        st = os.stat(path)
        raw = f"{CACHE_VERSION}|{path}|{st.st_size}|{int(st.st_mtime)}|{spec['profile']}|{self.cfg.PET_HEIGHT}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def _read_cache(self, cdir: str):
        """读磁盘缓存；没有或损坏返回 None。"""
        meta_path = os.path.join(cdir, "meta.json")
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("n", 0) <= 0:
                return None
            frames = []
            for i in range(meta["n"]):
                p = os.path.join(cdir, f"f{i:03d}.png")
                if not os.path.isfile(p):
                    return None
                frames.append(Image.open(p).convert("RGBA").copy())
            return frames, meta.get("durations", [])
        except Exception:
            return None

    def _write_cache(self, cdir: str, frames, durations):
        """写缓存（PNG 无损）。写完最后落 meta.json 作为完成标记。"""
        try:
            os.makedirs(cdir, exist_ok=True)
            for i, fr in enumerate(frames):
                fr.save(os.path.join(cdir, f"f{i:03d}.png"), "PNG", optimize=False)
            tmp = os.path.join(cdir, "meta.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(n=len(frames), durations=list(durations), h=self.cfg.PET_HEIGHT), f)
            os.replace(tmp, os.path.join(cdir, "meta.json"))
        except Exception as exc:  # 缓存失败不影响主流程
            self.warnings.append(f"缓存写入失败: {exc}")

    def _decode(self, path: str, spec: dict):
        """真正干活：打开 → 缩放 → 抠图。返回 (frames, durations)。"""
        prof = PROFILES[spec["profile"]]
        frames, durations = [], []
        im = Image.open(path)
        if spec["kind"] == "gif":
            step = max(1, int(self.cfg.GIF_STEP))
            if spec.get("all_frames"):
                step = 1
            for i, fr in enumerate(ImageSequence.Iterator(im)):
                dur = fr.info.get("duration") or 80
                if i % step and i != getattr(im, "n_frames", 1) - 1:
                    continue
                # ★ 必须用 RGBA：本机 Pillow 对某些 GIF 帧 convert("RGB") 会崩溃，
                #   而 RGBA 既安全、又能保留 GIF 自带的透明通道（素材10 就靠它）。
                rgba = fr.convert("RGBA")
                durations.append(dur * (step if i % step == 0 else 1))
                frames.append(SafeImageOps.cut_out(
                    SafeImageOps.fit_height(rgba, self.cfg.PET_HEIGHT), **prof))
        else:
            rgba = im.convert("RGBA")
            frames.append(SafeImageOps.cut_out(SafeImageOps.fit_height(rgba, self.cfg.PET_HEIGHT), **prof))
            durations.append(0)
        return frames, durations

    def _load_one(self, name: str):
        """加载单个素材（静态或动图）：优先读磁盘缓存，否则解码后写缓存。"""
        spec = ASSETS[name]
        path = find_asset(name, spec["names"])
        if not path:
            if not spec.get("optional"):          # 可选素材（成长形态/物品图标）缺失不报警
                self.warnings.append(f"找不到素材 {name}（候选: {spec['names']}）")
            with self.lock:
                self.data[name] = dict(frames=[], durations=[], ready=True)
            return
        self.paths[name] = path
        cdir = os.path.join(self.cache_root, self._cache_key(path, spec))
        cached = self._read_cache(cdir)
        if cached is None:
            frames, durations = self._decode(path, spec)
            self._write_cache(cdir, frames, durations)
        else:
            frames, durations = cached
        with self.lock:
            self.data[name] = dict(frames=frames, durations=durations, ready=True)


# ==============================================================================
# 4. SpriteRenderer —— 精灵合成 + LRU 缓存
# ==============================================================================
# 每一次「画面上真正显示的一帧」都是：原始帧 → 翻转 → 躺倒 → 缩放 → 歪头 →
# 调暗 → 贴进固定尺寸画布(锚点=脚底) → alpha 硬化 → 拍平到色键 → Tk PhotoImage。
# 结果按 (素材, 帧号, 翻转, 角度档, 明暗档, 姿态) 做 LRU 缓存，25FPS 下几乎零开销。
# ==============================================================================
class SpriteRenderer:
    def __init__(self, cfg=CFG):
        self.cfg = cfg
        self.cache: "dict[tuple, ImageTk.PhotoImage]" = {}
        self.order: list[tuple] = []
        self.cache_max = 96
        self.key_rgb = self._hex_to_rgb(cfg.KEY_COLOR)

    @staticmethod
    def _hex_to_rgb(hex_color: str):
        h = hex_color.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def photo(self, frame, *, flip=False, tilt=0.0, dim=1.0, lying=False, scale=1.0):
        """返回一张 (WIN_W × SPRITE_H) 的 PhotoImage，宠物脚底对齐画布底部。"""
        tq = int(round(tilt / 3.0))                     # 角度量化到 3° 一档，提高缓存命中
        dq = int(round(dim * 20))                       # 明暗量化
        key = (id(frame), flip, tq, dq, lying, int(round(scale * 50)),
               self.cfg.WIN_W, self.cfg.PET_CX)
        hit = self.cache.get(key)
        if hit is not None:
            return hit

        img = frame
        if flip:
            img = img.transpose(FLIP_LR)
        if lying:                                       # 睡觉：转 90° 侧躺
            img = img.rotate(-90, resample=RES_BICUBIC, expand=True)
        if abs(scale - 1.0) > 0.01:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                             RES_BICUBIC)
        if abs(tq) > 0:
            img = img.rotate(tq * 3.0, resample=RES_BICUBIC, expand=True)   # 歪头
        if dq < 20:
            img = ImageEnhance.Brightness(img).enhance(max(0.2, dq / 20.0))

        canvas = Image.new("RGBA", (self.cfg.WIN_W, self.cfg.SPRITE_H), (0, 0, 0, 0))
        x = self.cfg.PET_CX - img.width // 2
        y = self.cfg.SPRITE_H - self.cfg.BASE_LINE_GAP - img.height
        canvas.paste(img, (x, y))
        # alpha 硬化：旋转/缩放会引入半透明边，直接二值化避免和色键混合出紫边
        canvas.putalpha(canvas.getchannel("A").point(LUT_HARD))
        flat = SafeImageOps.keyed_rgb(canvas, self.key_rgb)
        photo = ImageTk.PhotoImage(flat)

        self.cache[key] = photo
        self.order.append(key)
        while len(self.order) > self.cache_max:         # LRU 淘汰
            old = self.order.pop(0)
            self.cache.pop(old, None)
        return photo


# ==============================================================================
# 4.5 IdleAnimationGenerator —— 程序化生成「呼吸待机动画」
# ==============================================================================
# 【思路】不生成新美术，纯用 C 级算子把现有 idle 图做「缩放 + 轻微旋转 + 上移」，
#   拼成 6 帧循环，看起来就是肚子一鼓一瘪在呼吸。
#   · 全部用 resize / rotate / paste / putalpha —— 零逐像素访问，不触发 Pillow 崩溃
#   · 6 帧拼进「同一尺寸画布」，保证切帧时不跳
#   · 结果缓存到 %TEMP%/desktop_pet_cache/idle_anim/，下次启动直接读
# ==============================================================================
class IdleAnimationGenerator:
    """基于 idle 素材生成呼吸循环帧，结果写回 AssetLibrary.data["idle_anim"]。"""

    KEY = "idle_anim"

    def __init__(self, lib, cfg=CFG):
        self.lib = lib
        self.cfg = cfg
        self.built = False
        self.used_cache = False

    # ---------------- 对外 ----------------
    def ensure(self) -> bool:
        """确保 idle_anim 可用（优先读缓存）；失败则用静态 idle 单帧兜底。"""
        if self.lib.get(self.KEY):
            return True
        frames, durs = self._load_cache()
        if frames:
            self.used_cache = True
        else:
            frames, durs = self._build()
            if frames:
                self._save_cache(frames, durs)
        if not frames:                          # 生成失败 → 退回单帧 idle
            idle = self.lib.get("idle")
            if idle:
                frames, durs = [idle[0]], [self.cfg.IDLE_BREATH_FRAME_MS]
                log_event("IDLE-ANIM", "生成失败，退回静态 idle 单帧")
        if not frames:
            return False
        with self.lib.lock:
            self.lib.data[self.KEY] = dict(frames=frames, durations=durs, ready=True)
        self.built = True
        log_event("IDLE-ANIM", f"呼吸动画就绪：{len(frames)} 帧，"
                               f"{'读缓存' if self.used_cache else '新生成'}，"
                               f"尺寸 {frames[0].size}")
        return True

    # ---------------- 生成 ----------------
    def _build(self):
        """按参数表生成 6 帧（全部 C 级算子）"""
        idle = self.lib.get("idle")
        if not idle:
            return [], []
        base = idle[0].convert("RGBA")
        poses = []                              # [(变换后的图, 上移像素)]
        for scale, lift, tilt in self.cfg.IDLE_BREATH_TABLE:
            img = base
            if abs(scale - 1.0) > 0.001:
                w = max(1, int(round(img.width * scale)))
                h = max(1, int(round(img.height * scale)))
                img = img.resize((w, h), RES_BICUBIC)
            if abs(tilt) > 0.01:
                img = img.rotate(tilt, resample=RES_BICUBIC, expand=True)
            poses.append((img, max(0, int(lift))))
        # ---- 统一画布：取最大尺寸，所有帧拼成同样大小（切帧不跳）----
        cw = max(im.width for im, _ in poses)
        ch = max(im.height + lift for im, lift in poses)
        frames = []
        for img, lift in poses:
            canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            x = (cw - img.width) // 2
            y = ch - img.height - lift          # 脚底贴底，再按 lift 上移
            canvas.paste(img, (x, y))
            # 旋转引入的半透明边会跟色键混出紫边 → 硬化 alpha（同 SpriteRenderer）
            canvas.putalpha(canvas.getchannel("A").point(LUT_HARD))
            frames.append(canvas)
        durs = [self.cfg.IDLE_BREATH_FRAME_MS] * len(frames)
        return frames, durs

    # ---------------- 缓存 ----------------
    def _cache_dir(self) -> str:
        return os.path.join(tempfile.gettempdir(), "desktop_pet_cache", self.KEY)

    def _params_key(self) -> str:
        raw = (f"{CACHE_VERSION}|{self.cfg.PET_HEIGHT}|"
               f"{self.cfg.IDLE_BREATH_TABLE}|{self.cfg.IDLE_BREATH_FRAME_MS}")
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def _load_cache(self):
        cdir = self._cache_dir()
        meta_path = os.path.join(cdir, "meta.json")
        if not os.path.isfile(meta_path):
            return [], []
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("key") != self._params_key():
                return [], []                    # 参数/缓存版本变了 → 重建
            n = int(meta.get("n", 0))
            if n <= 0:
                return [], []
            frames = []
            for i in range(n):
                p = os.path.join(cdir, f"f{i:03d}.png")
                if not os.path.isfile(p):
                    return [], []
                frames.append(Image.open(p).convert("RGBA").copy())
            return frames, list(meta.get("durations") or
                                [self.cfg.IDLE_BREATH_FRAME_MS] * n)
        except Exception as exc:
            log_event("IDLE-ANIM", f"读缓存失败，将重建：{exc}")
            return [], []

    def _save_cache(self, frames, durs):
        cdir = self._cache_dir()
        try:
            os.makedirs(cdir, exist_ok=True)
            for i, fr in enumerate(frames):
                fr.save(os.path.join(cdir, f"f{i:03d}.png"), "PNG", optimize=False)
            tmp = os.path.join(cdir, "meta.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(n=len(frames), durations=list(durs),
                               key=self._params_key(),
                               size=list(frames[0].size)), f)
            os.replace(tmp, os.path.join(cdir, "meta.json"))
        except Exception as exc:
            log_event("IDLE-ANIM", f"写缓存失败（不影响运行）：{exc}")


# ==============================================================================
# 5. PetStats —— 四维状态数值系统
# ==============================================================================
class PetStats:
    """
    心情 / 饱食 / 精力 / 无聊 四维数值 + 身体状况 + 养成数据（等级/经验/金币/背包/亲密度/成就/每日任务）
    """

    def __init__(self):
        self.happy = 78.0
        self.full = 70.0
        self.energy = 82.0
        self.bored = 20.0
        self.sleeping = False
        # ---- 第二阶段：身体状况 ----
        self.sick = False               # 生病（需要右键「治疗」才能好）
        self.sick_roll_t = 0.0          # 下次掷骰时间
        self.starving = False           # 饱食归零后的「饿坏了」状态
        self.collapsed = False          # 四项全归零的「彻底瘫掉」状态（会锁存，直到被救）
        self.sad_level = 0              # 伤感文案播放级别（用于节流）
        # ---- 第三阶段：养成系统 ----
        self.level = 1
        self.exp = 0
        self.coins = CFG.COINS_START
        self.bond = 0.0                 # 亲密度 0~1000
        self.inventory = dict(INVENTORY_START)
        self.achievements = {}          # {成就id: 解锁时间字符串}
        self.counters = dict(feed=0, pet_seconds=0.0, chat=0, play=0,
                             treat=0, click=0, levelups=0, days=0)
        self.daily_date = ""            # 当前每日任务的日期
        self.daily_tasks = []           # [{"id":.., "progress":.., "done":..}]
        self.streak_days = 0            # 连续登录天数
        self.last_login_date = ""       # 上次登录日期（判断连续天数/首互动加成）
        self.first_today = False        # 今天是否已经拿过「首次互动加成」
        self.happy_seconds = 0.0        # 心情>=80 的累计秒数（每日任务用）
        self.last_ups = 0               # 最近一次互动带来的升级数（上层取用后清零）
        self.newly_unlocked = []        # 本帧新解锁的成就（交给上层弹提示）
        # ---- 第四阶段：外出探险 ----
        self.adventure = {}             # 进行中的探险（空 dict = 不在探险）
        self.adventure_quests = {}      # {任务id: {progress, done, triggered}}
        self.adventure_collections = {} # 探险图鉴：物品名 → 获得次数
        self.adventure_total_count = 0  # 累计探险次数
        self.adventure_last_time = ""   # 上次探险日期（每日奖励用）
        self.animals_met = 0            # 遇到小动物的累计次数（社交达人成就）
        # ---- 第七阶段：小游戏 + 挂机 ----
        self.game_play_count = {}       # {游戏id: 今日已玩次数}
        self.game_play_reset_date = ""  # 次数重置日期
        self.game_double_until = 0.0    # 游戏奖励双倍截止时间戳
        self.game_high = {}             # ★ 各小游戏历史最高分 {游戏id: 分数}
        self.extra = ExtraState()       # ★ 第十二阶段：15 项扩展功能的全部状态
        self.adventure_location_exp = {}   # {地点: 熟练度 0-100}
        self.adventure_buff_pending = {}   # 下一次探险待生效的 buff
        self.adventure_offline_until = 0.0  # 离线探险结束时间戳
        self.first_play_date = ""       # 首次游玩日期（新手保护用）

    # ---------------- 基础 ----------------
    def clamp(self):
        self.happy = min(100.0, max(0.0, self.happy))
        self.full = min(100.0, max(0.0, self.full))
        self.energy = min(100.0, max(0.0, self.energy))
        self.bored = min(100.0, max(0.0, self.bored))
        self.bond = min(CFG.BOND_MAX, max(0.0, self.bond))

    def bond_tier(self) -> str:
        return bond_tier(self.bond)

    def exp_to_next(self) -> int:
        return exp_needed(self.level)

    def all_zero(self) -> bool:
        """
        四项状态全部见底 → 触发「全状态归零」特殊动画（素材9）。
        注意：无聊值每帧都在涨，真正四项同时为 0 只是一瞬间，
        所以这里用一个「锁存」的 collapsed 标志：一旦瘫掉就保持，
        直到被喂食 / 治疗 / 抚摸救回来（这样素材9 才有意义地显示出来）。
        """
        return self.collapsed or (self.happy <= 0.5 and self.full <= 0.5
                                  and self.energy <= 0.5 and self.bored <= 5.0)

    def _update_collapse(self):
        """判断是否进入「彻底瘫掉」，以及是否已经被救回来。"""
        if not self.collapsed:
            if (self.happy <= 0.5 and self.full <= 0.5
                    and self.energy <= 0.5 and self.bored <= 5.0):
                self.collapsed = True
        elif self.happy > 6 or self.full > 6 or self.energy > 6:
            self.collapsed = False           # 被照顾回来了

    # ---------------- 模块1：等级与经验 ----------------
    def add_exp(self, amount: float, reason: str = "") -> int:
        """
        加经验，返回本次升了几级（0=没升级）。
        升级：level+1，exp 减去所需经验（支持一次加很多连升），等级封顶 LEVEL_MAX。
        """
        if amount <= 0 or self.level >= CFG.LEVEL_MAX:
            return 0
        self.exp += int(round(amount))
        ups = 0
        while self.level < CFG.LEVEL_MAX and self.exp >= self.exp_to_next():
            self.exp -= self.exp_to_next()
            self.level += 1
            ups += 1
            self.coins += CFG.COINS_ON_LEVELUP
        if ups:
            self.counters["levelups"] = self.counters.get("levelups", 0) + ups
            self.happy = min(100.0, self.happy + 10 * ups)      # 升级顺便开心
            log_event("LEVELUP", f"→ Lv.{self.level}（{reason}，连升 {ups}）")
        self.last_ups = ups                  # 记录最近一次互动的升级数
        return ups

    def take_ups(self) -> int:
        """取出并清空「最近一次互动带来的升级数」（上层拿来弹升级气泡）"""
        ups = getattr(self, "last_ups", 0)
        self.last_ups = 0
        return ups

    def add_coins(self, n: float):
        self.coins = max(0, int(self.coins + n))

    # ---------------- 模块2：背包 ----------------
    def add_item(self, name: str, n: int = 1):
        self.inventory[name] = self.inventory.get(name, 0) + n

    def use_item(self, name: str) -> tuple:
        """
        使用一个物品，返回 (成功?, 提示文字)
        物品效果全部由 ITEMS 表驱动：四维增减 / 治病 / 救瘫 / 随机增益
        """
        if self.inventory.get(name, 0) <= 0:
            return False, f"背包里没有「{name}」了"
        spec = ITEMS.get(name)
        if not spec:
            return False, f"「{name}」暂时用不了"
        if spec.get("revive") and not self.collapsed:
            return False, "现在精神得很，不用吃药～"
        # 扣物品
        self.inventory[name] -= 1
        if self.inventory[name] <= 0:
            self.inventory.pop(name, None)
        msgs = [f"使用了「{name}」"]
        if spec.get("revive"):
            self.collapsed = False
            self.happy = min(100, self.happy + 30)
            self.full = min(100, self.full + 30)
            self.energy = min(100, self.energy + 30)
            self.bored = max(0, self.bored - 30)
            msgs.append("被救回来了！")
        if spec.get("boost_adv"):                     # 探险指南针：下一次探险 x2
            self.adventure_buff_pending["boost"] = True
            msgs.append("下次探险收益翻倍！")
        if spec.get("game_double"):                   # 幸运饼干：当天游戏奖励 x2
            self.game_double_until = time.time() + CFG.GAME_DOUBLE_HOURS * 3600
            msgs.append(f"接下来 {CFG.GAME_DOUBLE_HOURS} 小时游戏奖励翻倍！")
        if spec.get("random_gift"):
            roll = random.random()
            if roll < 0.25:
                self.add_coins(50)
                msgs.append("开出了 50 金币！")
            elif roll < 0.6:
                self.happy = min(100, self.happy + 25)
                msgs.append("心情 +25")
            elif roll < 0.9:
                self.full = min(100, self.full + 20)
                msgs.append("饱食 +20")
            else:
                self.energy = min(100, self.energy + 30)
                msgs.append("精力 +30")
        if spec.get("cure") and self.sick:
            self.sick = False
            msgs.append("病好了！")
        for key, label in (("full", "饱食"), ("happy", "心情"),
                           ("energy", "精力"), ("bored", "无聊")):
            v = spec.get(key)
            if v:
                setattr(self, key, getattr(self, key) + v)
                msgs.append(f"{label}{'+' if v > 0 else ''}{v:g}")
        self.clamp()
        self._update_collapse()
        self.add_exp(CFG.EXP_ON_PLAY, "使用物品")
        self.counters["play"] = self.counters.get("play", 0) + 1
        return True, "，".join(msgs)

    # ---------------- 模块3：亲密度 ----------------
    def add_bond(self, amount: float, reason: str = ""):
        if amount <= 0:
            return
        bonus = 0.0
        if not self.first_today:                 # 每天第一次互动有额外加成
            self.first_today = True
            bonus = CFG.BOND_DAILY_FIRST_BONUS
        before = self.bond_tier()
        self.bond = min(CFG.BOND_MAX, self.bond + amount + bonus)
        after = self.bond_tier()
        if after != before:
            log_event("BOND", f"亲密度升级：{before} → {after}（{self.bond:.0f}）")
        self.clamp()

    # ---------------- 每日任务（模块6） ----------------
    def refresh_daily(self, force: bool = False) -> bool:
        """
        跨天刷新每日任务：随机抽 DAILY_TASK_COUNT 个，进度清零。
        返回是否发生了刷新。
        """
        today = today_str()
        if not force and self.daily_date == today and self.daily_tasks:
            return False
        pool = random.sample(DAILY_TASKS, min(CFG.DAILY_TASK_COUNT, len(DAILY_TASKS)))
        self.daily_tasks = [dict(id=t["id"], name=t["name"], desc=t["desc"],
                                 target=t["target"], coins=t["coins"], exp=t["exp"],
                                 counter=t["counter"], progress=0.0, done=False)
                            for t in pool]
        self.daily_date = today
        self.happy_seconds = 0.0
        log_event("DAILY", f"刷新每日任务：{[t['name'] for t in self.daily_tasks]}")
        return True

    def daily_progress(self):
        """把计数器同步到每日任务进度，返回本次刚完成的任务列表。"""
        done_now = []
        for task in self.daily_tasks:
            if task["done"]:
                continue
            cur = self.counters.get(task["counter"], 0)
            if task["counter"] == "happy_seconds":
                cur = self.happy_seconds
            task["progress"] = min(float(cur), float(task["target"]))
            if task["progress"] >= task["target"]:
                task["done"] = True
                self.add_coins(task["coins"])
                self.add_exp(task["exp"], "每日任务")
                done_now.append(task)
        return done_now

    # ---------------- 模块4：成就 ----------------
    def check_achievements(self) -> list:
        """检查成就条件，返回本次新解锁的成就定义列表。"""
        unlocked = []
        for ach in ACHIEVEMENTS:
            aid = ach["id"]
            if aid in self.achievements:
                continue
            if self._ach_done(aid):
                self.achievements[aid] = time.strftime("%Y-%m-%d %H:%M")
                self.add_coins(ach["coins"] * CFG.ACHIEVEMENT_COIN_BONUS)
                unlocked.append(ach)
                log_event("ACHIEVE", f"解锁成就：{ach['name']}")
        return unlocked

    def _ach_done(self, aid: str) -> bool:
        c = self.counters
        hour = now_hour()
        return {
            "first_meet": True,                                   # 启动即达成
            "week_streak": self.streak_days >= 7,
            "foodie": c.get("feed", 0) >= 50,
            "pet_master": c.get("pet_seconds", 0) >= 600,
            "rich": self.coins >= 1000,
            "max_level": self.level >= 20,
            "soulmate": self.bond >= CFG.BOND_MAX,
            "survivor": bool(c.get("saved_from_collapse")),
            "night_owl": 2 <= hour < 4,
            # ---- 模块7：探险成就 ----
            "adv_first": self.adventure_total_count >= 1,
            "adv_10": self.adventure_total_count >= 10,
            "adv_50": self.adventure_total_count >= 50,
            "treasure_hunter": bool(self.adventure_quests.get("forest", {}).get("done")),
            "social": self.animals_met >= 10,
            "lucky": bool(c.get("legendary_drop")),
            "night_adv": bool(c.get("night_adventure")),
        }.get(aid, False)

    # ---------------- 模块1~7：外出探险 ----------------
    def adventure_unlocked(self, key: str) -> bool:
        spot = ADVENTURE_SPOTS.get(key)
        return bool(spot) and self.level >= spot["unlock_level"]

    def adventure_can_start(self, key: str) -> tuple:
        """
        能否出发 → (可以?, 提示文字)
        检查：地点解锁 / 精力够不够 / 是否已经在探险中
        """
        spot = ADVENTURE_SPOTS.get(key)
        if not spot:
            return False, "没有这个地方呀"
        if self.adventure:
            return False, "我已经在外面探险啦"
        if self.level < spot["unlock_level"]:
            return False, f"要到 Lv.{spot['unlock_level']} 才能去哦"
        if self.energy < spot["energy_cost"]:
            return False, random.choice(ADV_LINES["tired"])
        return True, ""

    def start_adventure(self, key: str, buffs=None, duration: float = None,
                        energy_ratio: float = 1.0) -> bool:
        """
        出发：扣精力、记录出发时间与 buff。
        duration / energy_ratio 支持挂机档位（30s / 10min / 1h / 8h）。
        """
        ok, _ = self.adventure_can_start(key)
        if not ok:
            return False
        spot = ADVENTURE_SPOTS[key]
        dur = float(duration or spot["duration"])
        cost = spot["energy_cost"] * max(1.0, float(energy_ratio))
        if self.energy < cost:
            return False
        self.energy = max(0.0, self.energy - cost)
        boost = bool(self.adventure_buff_pending.pop("boost", False))
        self.adventure = dict(
            spot=key,
            start=time.time(),
            end=time.time() + dur,
            duration=dur,
            buffs=list(buffs or []),
            halted=False,
            event_bonus=[],
            boost=boost,
        )
        if boost:
            log_event("ADVENTURE", f"探险指南针生效：本次收益 x{CFG.ADVENTURE_BOOST_MULT}")
        self.adventure_total_count += 1
        # 每日首探险奖励 / 夜行者成就
        today = now_day_str()
        if self.adventure_last_time != today:
            self.add_coins(CFG.ADVENTURE_DAILY_BONUS)
            self.counters["daily_adv_bonus"] = 1
        self.adventure_last_time = today
        if 0 <= now_hour() < 5:
            self.counters["night_adventure"] = 1
        self.clamp()
        log_event("ADVENTURE", f"出发 → {spot['name']}（{spot['duration']}s，buffs={buffs}）")
        return True

    def adventure_remaining(self) -> float:
        """还剩几秒回来（没在探险就返回 0）"""
        if not self.adventure:
            return 0.0
        return max(0.0, self.adventure["end"] - time.time())

    def adventure_progress(self) -> float:
        """0~1 进度（给头顶进度条用）"""
        if not self.adventure:
            return 0.0
        dur = max(1.0, float(self.adventure.get("duration", 1)))
        return min(1.0, max(0.0, 1.0 - self.adventure_remaining() / dur))

    def halt_adventure(self):
        """探险中精力见底 → 累到提前回家（收益减半）"""
        if self.adventure:
            self.adventure["halted"] = True
            self.adventure["end"] = time.time()

    def adventure_bag_limit(self) -> int:
        limit = CFG.ADVENTURE_BAG_LIMIT
        if self.adventure and "bigbag" in self.adventure.get("buffs", []):
            limit += CFG.ADVENTURE_BAG_BONUS
        return limit

    def _roll_tier(self, spot_key: str = None) -> str:
        """掷掉落档位。该地点熟练度满 100 → 整体往好档位偏（equivalent 升一档）"""
        r = random.random()
        if spot_key and self.adv_exp(spot_key) >= CFG.ADVENTURE_EXP_MAX:
            # 熟练度满：把均匀分布往高档位推（common 70%→60%，史诗/传说更多）
            r = r ** 0.7
        for edge, name in CFG.ADVENTURE_TIERS:
            if r <= edge:
                return name
        return "legendary"

    def _pick_drop(self, spot: dict, tier: str) -> str:
        """按档位挑一件掉落物（该档位为空就往下退）"""
        order = ["legendary", "epic", "rare", "common"]
        start = order.index(tier)
        for t in order[start:]:
            pool = list(spot.get(t) or [])
            if t == "legendary" and CFG.ADVENTURE_LEGENDARY_ONCE:
                pool = [n for n in pool if self.adventure_collections.get(n, 0) == 0]
            if pool:
                return random.choice(pool)
        return "小石子"

    def finish_adventure(self, early: bool = False) -> dict:
        """
        结算探险 → 返回结果字典（给结算窗口用）。
        收益倍率：提前回家/累趴 → ×0.5（可叠加一次）、饱食低 → ×0.5、奶蛙之铃 → ×1.5
        """
        if not self.adventure:
            return {}
        a = self.adventure
        spot = ADVENTURE_SPOTS[a["spot"]]
        buffs = list(a.get("buffs", []))
        notes = []
        mult = 1.0

        # ---- 1) 金币 ----
        lo, hi = spot["coins"]
        coins = random.randint(lo, hi)
        base_coins = coins

        # ---- 2) 掉落 ----
        limit = self.adventure_bag_limit()
        want = random.randint(CFG.ADVENTURE_MIN_ITEMS, CFG.ADVENTURE_MAX_ITEMS)
        want = min(want, limit)
        items = {}
        tier_hits = {}
        for _ in range(want):
            tier = self._roll_tier(a["spot"])
            # 手电筒：小树林史诗概率翻倍
            if tier != "epic" and "flashlight" in buffs and a["spot"] in \
                    BUFF_BY_KEY["flashlight"]["epic_double_spots"] and random.random() < 0.5:
                tier = "epic"
            name = self._pick_drop(spot, tier)
            items[name] = items.get(name, 0) + 1
            tier_hits[tier] = tier_hits.get(tier, 0) + 1

        # ---- 3) 随机事件 ----
        event = None
        blocked = set()
        for b in buffs:
            blocked.update(BUFF_BY_KEY.get(b, {}).get("block_events", ()))
        if random.random() < CFG.ADVENTURE_EVENT_CHANCE:
            pool = []
            for ev in ADVENTURE_EVENTS:
                if ev["id"] in blocked:
                    continue
                w = ev["weight"]
                for b in buffs:
                    w *= BUFF_BY_KEY.get(b, {}).get("event_weight", {}).get(ev["id"], 1.0)
                pool.append((ev, w))
            if pool:
                total = sum(w for _, w in pool)
                r = random.uniform(0, total)
                acc = 0.0
                for ev, w in pool:
                    acc += w
                    if r <= acc:
                        event = ev
                        break
        if event:
            if event.get("coins"):
                coins += event["coins"]
            if event.get("coin_mult"):
                coins = int(coins * event["coin_mult"])
            if event.get("happy"):
                self.happy += event["happy"]
            if event.get("energy"):
                self.energy += event["energy"]          # 通常是负数
            if event.get("bond"):
                self.bond += event["bond"]
            if event.get("bored_clear"):
                self.bored = 0.0
            if event.get("random_rare"):
                items["稀有种子"] = items.get("稀有种子", 0) + 1
            if event.get("random_epic"):
                items["幸运饼干"] = items.get("幸运饼干", 0) + 1
            for n, c in (event.get("items") or {}).items():
                items[n] = items.get(n, 0) + c
            if event.get("animal"):
                self.animals_met += 1
            notes.append(f"{event['emoji']} {event['name']}：{event['desc']}")

        # ---- 4) 倍率：饱食偏低 / 提前回家 / 累趴 ----
        if self.full < CFG.ADVENTURE_HUNGRY_FULL:
            mult *= CFG.ADVENTURE_EARLY_RATIO
            notes.append("肚子饿着出去，收益打了对折…")
        if early:
            mult *= CFG.ADVENTURE_EARLY_RATIO
            notes.append("提前回家，收益减半")
        if a.get("halted"):
            mult *= CFG.ADVENTURE_EARLY_RATIO
            notes.append("累到走不动，收益减半")
        if a.get("boost"):
            mult *= CFG.ADVENTURE_BOOST_MULT
            notes.append(f"探险指南针生效，收益 x{CFG.ADVENTURE_BOOST_MULT:g}")
        bell = self.adventure_collections.get("奶蛙之铃", 0) > 0 or \
            self.inventory.get("奶蛙之铃", 0) > 0
        if bell:
            mult *= CFG.ADVENTURE_REWARD_MULT_BELL
            notes.append("奶蛙之铃叮当响，收益 +50%")

        coins = max(1, int(round(coins * mult)))

        # ---- 5) 经验 / 亲密度 ----
        exp = int(CFG.ADVENTURE_EXP_BASE * (spot["duration"] / 30.0) * mult)
        bond = round(CFG.ADVENTURE_BOND_BASE * (spot["duration"] / 60.0 + 1) * mult, 1)

        # ---- 6) 入账 ----
        self.add_coins(coins)
        for name, cnt in items.items():
            # 图鉴：所有掉落都记录
            self.adventure_collections[name] = self.adventure_collections.get(name, 0) + cnt
            # 可用物品进背包；材料也进背包（可以卖钱）
            self.add_item(name, cnt)
            if "legendary" in tier_hits and name in (spot.get("legendary") or []):
                self.counters["legendary_drop"] = 1
        ups = self.add_exp(exp, "探险")
        self.bond = min(CFG.BOND_MAX, self.bond + bond)
        self.happy = min(100.0, self.happy + 8)
        self.bored = max(0.0, self.bored - 25)
        self.clamp()

        # ---- 7) 任务线进度 ----
        quest_msgs = []
        for name in items:
            quest_msgs += self.advance_quest_by_item(name)
        if event and event.get("quest"):
            quest_msgs += self.advance_quest(event["quest"])

        # ---- 熟练度：每去一次 +5，满 100 之后掉落整体升一档已体现在 tiers 上 ----
        prof_up = self.adv_exp_add(a["spot"])
        if prof_up:
            pass
        if prof_up:
            notes.append(f"{spot['name']}熟练度满啦！以后掉落品质更高了")
        # ---- 8) 结算 ----
        result = dict(
            spot_key=a["spot"], spot=spot, coins=coins, base_coins=base_coins,
            items=items, tiers=tier_hits, exp=exp, bond=bond, event=event,
            notes=notes, quest_msgs=quest_msgs, early=early,
            halted=bool(a.get("halted")), mult=round(mult, 2), levelups=ups,
            daily_bonus=(self.counters.pop("daily_adv_bonus", 0) == 1),
        )
        self.adventure = {}
        log_event("ADVENTURE", f"归来 ← {spot['name']} 金币{coins} 物品{items} "
                              f"事件={event['name'] if event else '无'} 倍率{mult:.2f}")
        return result

    # ---------------- 模块5：任务线进度 ----------------
    def quest_state(self, qid: str) -> dict:
        return self.adventure_quests.setdefault(qid, dict(progress=0, done=False,
                                                          triggered=False))

    def advance_quest(self, qid: str) -> list:
        """推进某个任务线（触发或 +1），返回提示文字列表"""
        q = QUEST_LINES.get(qid)
        if not q:
            return []
        st = self.quest_state(qid)
        msgs = []
        if st["done"]:
            return msgs
        if not st["triggered"]:
            st["triggered"] = True
            msgs.append(f"任务开启：{q['emoji']} {q['name']}（{q['desc']}）")
            log_event("QUEST", f"触发任务线 {q['name']}")
        st["progress"] = min(q["target"], st["progress"] + 1)
        if st["progress"] >= q["target"]:
            st["done"] = True
            msgs += self._quest_reward(qid)
        return msgs

    def advance_quest_by_item(self, item_name: str) -> list:
        """拿到某个信物时自动推进对应任务线"""
        msgs = []
        for qid, q in QUEST_LINES.items():
            if q.get("trigger_item") == item_name:
                msgs += self.advance_quest(qid)
        return msgs

    def _quest_reward(self, qid: str) -> list:
        q = QUEST_LINES[qid]
        r = q["rewards"]
        msgs = [f"任务完成：{q['emoji']} {q['name']}！{q['reward_text']}"]
        if r.get("coins"):
            self.add_coins(r["coins"])
        if r.get("bond"):
            self.bond = min(CFG.BOND_MAX, self.bond + r["bond"])
        for name, cnt in (r.get("items") or {}).items():
            self.add_item(name, cnt)
            self.adventure_collections[name] = self.adventure_collections.get(name, 0) + cnt
        if r.get("achievement"):
            self.counters[f"quest_{qid}_done"] = 1
        ups = self.add_exp(r.get("exp", 0), f"任务线 {q['name']}")
        if ups:
            msgs.append(f"升级啦！Lv.{self.level}")
        self.check_achievements()
        log_event("QUEST", f"完成任务线 {q['name']}，奖励已发放")
        return msgs

    # ---------------- 主循环 ----------------
    def tick(self, dt: float, active: bool, resting: bool = False, traveling: bool = False):
        """
        dt 秒过去了。
        active   = 用户刚刚有互动（互动时不涨无聊值）
        resting  = 正在睡觉或打盹（精力回涨、消耗变慢）
        traveling= 正在外面探险（精力暂停衰减，饱食照常；饱食不衰减要看便当 buff）
        返回本帧「刚刚发生的事件」列表，交给上层决定说什么/播什么动画。
        """
        events = []
        self._update_collapse()              # ★ 先判「全归零」，再让数值继续变化
        relief = self.decay_factor()          # ★ 等级回报 × 新手保护
        if traveling:
            # 出门在外：精力不衰减（累了会由事件扣），饱食照常掉；
            # 用了「便当」则饱食也不掉
            no_food = False
            if self.adventure:
                no_food = "bento" in self.adventure.get("buffs", [])
            self.happy -= CFG.DECAY_HAPPY * 0.3 * relief * dt
            if not no_food:
                self.full -= CFG.DECAY_FULL * relief * dt
            self.bored += CFG.GROW_BORED * 0.5 * relief * dt
        elif resting:
            self.energy += CFG.SLEEP_ENERGY_GAIN * (1.0 if self.sleeping else 0.7) * dt
            self.full -= CFG.DECAY_FULL * 0.4 * relief * dt
            self.bored -= CFG.GROW_BORED * 0.3 * relief * dt
        else:
            penalty = CFG.SICK_PENALTY if self.sick else 1.0      # 生病时状态掉得更快
            self.happy -= CFG.DECAY_HAPPY * penalty * relief * dt
            self.full -= CFG.DECAY_FULL * relief * dt
            self.energy -= CFG.DECAY_ENERGY * penalty * relief * dt
            if active:
                self.bored -= CFG.GROW_BORED * 1.6 * relief * dt
            else:
                self.bored += CFG.GROW_BORED * relief * dt
                self.happy -= CFG.DECAY_HAPPY * 0.4 * relief * dt
        self.clamp()

        # ★ 休闲化：心情低于 20 时自愈（每 5 秒 +1），不会一直丧
        self.sad_autoheal(dt)
        # 每日任务：心情保持计时
        if self.happy >= 80 and not resting:
            self.happy_seconds += dt

        # 亲密度：长期不互动缓慢下降（每小时 BOND_DECAY_PER_HOUR）
        if not active:
            self.bond = max(0.0, self.bond - CFG.BOND_DECAY_PER_HOUR * dt / 3600.0)

        # ---- 饱食归零：饿坏了 + 直接生病（必须由用户手动治疗才能好）----
        if self.full <= 0.5 and not self.starving:
            self.starving = True
            events.append("starving")
            if not self.sick and not self.newbie_sick_safe():
                self.sick = True                 # 饿到生病
                events.append("got_sick")
        elif self.full > 8 and self.starving:
            self.starving = False

        # ---- 饱食在中间区间：每隔一段时间掷骰子，有概率生病 ----
        # ★ 休闲化：饱食高于 SICK_SAFE_FULL 完全不掷骰；新手前 3 天免疫
        now = time.time()
        if now >= self.sick_roll_t:
            self.sick_roll_t = now + CFG.SICK_ROLL_EVERY
            lo, hi = CFG.SICK_BAND
            full_ok = self.full < CFG.SICK_SAFE_FULL
            if (not self.sick and full_ok and lo <= self.full <= hi
                    and not self.newbie_sick_safe()
                    and random.random() < CFG.SICK_CHANCE):
                self.sick = True
                events.append("got_sick")
        return events

    # ---------------- 第七阶段：休闲化保护 ----------------
    def newbie_sick_safe(self) -> bool:
        """新手保护期内不会生病（前 NEWBIE_SAFE_DAYS 天）"""
        if self.level > CFG.NEWBIE_LEVEL:
            return False
        if not self.first_play_date:
            return True                          # 刚建档，算第一天
        return _day_gap(self.first_play_date, time.strftime("%Y-%m-%d")) < \
            CFG.NEWBIE_SAFE_DAYS

    def decay_factor(self) -> float:
        """综合衰减系数：等级回报 × 新手保护"""
        f = decay_multiplier(self.level)
        if self.level <= CFG.NEWBIE_LEVEL:
            f *= CFG.NEWBIE_DECAY_MULT
        return f

    def sad_autoheal(self, dt: float):
        """心情过低时自动缓慢回升，不会一直丧着"""
        if self.happy < CFG.SAD_AUTOHEAL_AT:
            self.happy = min(CFG.SAD_AUTOHEAL_AT, self.happy + CFG.SAD_AUTOHEAL_RATE * dt)

    def should_autosleep(self, idle_seconds: float) -> bool:
        """无聊到极点又没人理 → 自己睡觉打发时间"""
        return (self.bored >= CFG.BORED_AUTOSLEEP_AT and idle_seconds > 20.0
                and not self.sleeping)

    def apply_offline_decay(self, hours: float) -> dict:
        """
        ★ 离线衰减保护：关程序期间只让饱食按 10% 速度慢慢掉，其他暂停。
        返回本次掉了多少，便于提示。
        """
        if not CFG.OFFLINE_DECAY_PROTECT or hours <= 0:
            return {}
        hours = min(max(0.0, hours), CFG.OFFLINE_MAX_HOURS)
        before = dict(happy=self.happy, full=self.full, energy=self.energy,
                      bored=self.bored)
        # 按比例掉：8 小时 ≈ 掉当前饱食的 16%，属于「基本没变化」
        drop = self.full * CFG.OFFLINE_FULL_RATE * hours
        self.full = max(0.0, self.full - drop)
        self.clamp()
        return dict(hours=hours, full_drop=round(before["full"] - self.full, 1),
                    before=before)

    # --- 互动带来的数值变化（同时结算经验/金币/亲密度/计数器）---
    def on_click(self):
        self.happy += 10
        self.bored -= 12
        self.add_exp(CFG.EXP_ON_CLICK, "点击")
        self.add_coins(CFG.COINS_ON_CLICK)
        self.add_bond(CFG.BOND_ON_CLICK, "点击")
        self.counters["click"] = self.counters.get("click", 0) + 1
        self.clamp()

    def on_pet(self, dt: float):
        self.happy += 9 * dt
        self.bored -= 25 * dt
        self.add_exp(CFG.EXP_ON_PET_PER_SEC * dt, "抚摸")
        self.add_coins(CFG.COINS_ON_PET_PER_SEC * dt)
        self.add_bond(CFG.BOND_ON_PET_PER_SEC * dt, "抚摸")
        self.counters["pet_seconds"] = self.counters.get("pet_seconds", 0) + dt
        self.clamp()

    # ---------------- 喂食 / 赠送（只能动背包里的东西，没有凭空喂食）----------------
    def feed_item(self, name: str) -> tuple:
        """
        ★ 喂食改造：只能吃背包里的「食物」，不再有凭空喂食。
        返回 (成功?, 提示文字)
        """
        spec = ITEMS.get(name)
        if not spec:
            return False, f"背包里没有「{name}」呀"
        if self.inventory.get(name, 0) <= 0:
            return False, f"背包里没有「{name}」了，去商店买点吧～"
        if spec.get("cat") != "食物":
            return False, f"「{name}」不能吃啦，可以送给奶蛙当礼物～"
        if self.full >= CFG.FULL_REFUSE:
            return False, random.choice(LINES["refuse"])
        was_sick = self.sick
        ok, msg = self.use_item(name)
        if not ok:
            return False, msg
        # 喂食额外结算：计数 / 好感 / 补足喂食经验
        self.counters["feed"] = self.counters.get("feed", 0) + 1
        self.add_bond(CFG.BOND_ON_FEED, "喂食")
        self.add_coins(CFG.COINS_ON_FEED)
        self.add_exp(max(0, CFG.EXP_ON_FEED - CFG.EXP_ON_PLAY), "喂食")
        if self.full > 8:
            self.starving = False
        self.clamp()
        log_event("FEED", f"吃掉了「{name}」→ 饱食{self.full:.0f}"
                          f"{'（顺便治好了）' if was_sick and not self.sick else ''}")
        return True, msg

    def gift_item(self, name: str) -> tuple:
        """
        ★ 新增：赠送礼物提升好感度。
        返回 (成功?, 提示文字, 获得的好感值)
        """
        if name in CFG.GIFT_BLOCKED:
            return False, f"「{name}」是奶蛙的宝贝，舍不得送人啦", 0
        if self.inventory.get(name, 0) <= 0:
            return False, f"背包里没有「{name}」了", 0
        if self.bond >= CFG.BOND_MAX:
            return False, "我们的心意已经满格啦，不用再送东西了～", 0
        value = gift_bond_value(name)
        fav = name in CFG.GIFT_FAVORITES
        if fav:
            value = int(round(value * CFG.GIFT_FAVORITE_BONUS))
        # 扣物品
        self.inventory[name] -= 1
        if self.inventory[name] <= 0:
            self.inventory.pop(name, None)
        self.add_bond(value, f"赠送{name}")
        self.happy = min(100.0, self.happy + (CFG.GIFT_HAPPY * (2 if fav else 1)))
        self.bored = max(0.0, self.bored - 15)
        self.add_exp(CFG.EXP_ON_GIFT, "赠送礼物")
        self.counters["gift"] = self.counters.get("gift", 0) + 1
        self.clamp()
        log_event("GIFT", f"送出「{name}」→ 好感 +{value}"
                          f"{'（最爱！）' if fav else ''} 当前 {self.bond:.0f}")
        return True, f"送出了「{name}」，好感 +{value}", value

    # ---------------- 统一奖励入口（小游戏/探险/任务都用它）----------------
    def add_reward(self, coins: float = 0, exp: float = 0, bond: float = 0,
                   items=None, happy: float = 0, reason: str = "") -> dict:
        """
        ★ 统一发奖：金币 / 经验 / 好感 / 物品 / 心情 一次结算。
        返回 dict(coins, exp, bond, items, levelups) 供 UI 展示。
        所有数值都做上下限保护，不会因为刷奖励把属性打爆。
        """
        items = items or {}
        coins = max(0, int(round(coins)))
        exp = max(0, int(round(exp)))
        bond = max(0.0, float(bond))
        if coins:
            self.add_coins(coins)
        got_bond = 0.0
        if bond:
            before = self.bond
            self.bond = min(CFG.BOND_MAX, self.bond + bond)
            got_bond = self.bond - before
        for name, cnt in items.items():
            if cnt <= 0:
                continue
            self.add_item(name, int(cnt))
            self.adventure_collections[name] = \
                self.adventure_collections.get(name, 0) + int(cnt)
        if happy:
            self.happy = min(100.0, self.happy + happy)
        ups = self.add_exp(exp, reason or "奖励") if exp else 0
        self.clamp()
        return dict(coins=coins, exp=exp, bond=round(got_bond, 1),
                    items=dict(items), levelups=ups)

    # ---------------- 第七阶段：小游戏次数 ----------------
    def game_key(self, game_id: str) -> str:
        """今日玩某游戏的次数（跨天自动清零）"""
        today = time.strftime("%Y-%m-%d")
        if self.game_play_reset_date != today:
            self.game_play_reset_date = today
            self.game_play_count = {}
        return str(self.game_play_count.get(game_id, 0))

    def game_limit(self, game_id: str) -> int:
        """该游戏每天最多玩几次（第十一阶段：新游戏各 3 次）"""
        return int(CFG.GAME_DAILY_LIMITS.get(game_id, CFG.GAME_DAILY_LIMIT))

    def game_high_score(self, game_id: str) -> float:
        """历史最高分"""
        try:
            return float(self.game_high.get(game_id, 0) or 0)
        except Exception:
            return 0.0

    def game_record(self, game_id: str, score: float) -> bool:
        """刷新最高分；破了返回 True"""
        cur = self.game_high_score(game_id)
        if score > cur:
            self.game_high[game_id] = score
            return True
        return False

    def game_left(self, game_id: str) -> int:
        self.game_key(game_id)                       # ★ 顺带处理跨天重置
        try:
            used = int(self.game_play_count.get(game_id, 0))
        except Exception:
            used = 0
        return max(0, self.game_limit(game_id) - used)

    def game_use(self, game_id: str) -> bool:
        """消耗一次游戏机会；次数用完返回 False"""
        self.game_key(game_id)                       # 触发跨天重置
        if self.game_left(game_id) <= 0:
            return False
        self.game_play_count[game_id] = int(self.game_play_count.get(game_id, 0)) + 1
        return True

    def game_double_active(self) -> bool:
        """背包里吃过幸运饼干 → 当日游戏奖励翻倍"""
        return getattr(self, "game_double_until", 0) > time.time()

    # ---------------- 第七阶段：探险熟练度 / 离线 ----------------
    def adv_exp(self, spot_key: str) -> int:
        try:
            return int(self.adventure_location_exp.get(spot_key, 0))
        except Exception:
            return 0

    def adv_exp_add(self, spot_key: str) -> bool:
        """去该地点探险 +熟练度；返回是否刚好满级"""
        cur = self.adv_exp(spot_key)
        new = min(CFG.ADVENTURE_EXP_MAX, cur + CFG.ADVENTURE_EXP_PER_TRIP)
        self.adventure_location_exp[spot_key] = new
        return cur < CFG.ADVENTURE_EXP_MAX <= new

    def adv_exp_ratio(self, spot_key: str) -> float:
        return self.adv_exp(spot_key) / max(1, CFG.ADVENTURE_EXP_MAX)

    def adv_boost_ready(self) -> bool:
        return bool(self.adventure_buff_pending.get("boost"))

    def on_chat(self):
        self.happy += 5
        self.bored -= 18
        self.add_exp(CFG.EXP_ON_CHAT, "聊天")
        self.add_coins(CFG.COINS_ON_CHAT)
        self.add_bond(CFG.BOND_ON_CHAT, "聊天")
        self.counters["chat"] = self.counters.get("chat", 0) + 1
        self.clamp()

    def on_treat(self):
        """手动治疗：治好病 + 恢复一点心情（这是唯一的痊愈方式）。"""
        was = self.sick
        self.sick = False
        self.happy += 15
        self.add_exp(CFG.EXP_ON_TREAT, "治疗")
        self.add_bond(2.0, "治疗")
        self.counters["treat"] = self.counters.get("treat", 0) + 1
        if self.collapsed:                       # 「大难不死」成就
            self.collapsed = False
            self.counters["saved_from_collapse"] = 1
        self.clamp()
        return was

    def mood(self) -> str:
        """由数值推出的主导情绪（优先级从高到低）。"""
        if self.sleeping:
            return "sleep"
        if self.full <= 0.5:        # 用实时数值判断，避免 starving 标志残留
            return "starving"
        if self.sick:
            return "sick"
        if self.full <= CFG.HUNGRY_AT:
            return "hungry"
        if self.energy <= CFG.SLEEPY_AT:
            return "sleepy"
        if self.happy <= CFG.MOOD20_AT:
            return "sad"
        if self.bored >= CFG.BORED_AT:
            return "bored"
        return "fine"

    def status_icon(self) -> str:
        """状态图标（用文字代替 emoji，避免字体缺字）"""
        if self.sleeping:
            return "睡眠中"
        if self.sick:
            return "生病中(需治疗)"
        if self.starving:
            return "饿坏了"
        return "健康"

    def bar(self, v: float, n: int = 10) -> str:
        k = int(round(v / 100.0 * n))
        return "█" * k + "·" * (n - k)

    def report(self) -> str:
        """状态面板：四条进度条 + 身体状况 + 当前心情标签"""
        mood_cn = {"fine": "正常", "hungry": "饿了", "sleepy": "困了", "bored": "无聊",
                   "sad": "情绪低落", "sick": "生病了", "starving": "饿坏了",
                   "sleep": "睡觉中"}.get(self.mood(), "正常")
        return (f"身体状况：{self.status_icon()}　心情：{mood_cn}\n"
                f"心情 {self.happy:4.0f} {self.bar(self.happy)}\n"
                f"饱食 {self.full:4.0f} {self.bar(self.full)}\n"
                f"精力 {self.energy:4.0f} {self.bar(self.energy)}\n"
                f"无聊 {self.bored:4.0f} {self.bar(self.bored)}\n"
                f"（右键「治疗」可治好生病，「喂食」可解饿）")


# ==============================================================================
# 6. 台词库 & ChatBrain —— 聊天引擎（预留大模型接口）
# ==============================================================================
LINES = {
    "click": ["嘿嘿，好痒～", "点我干嘛呀？", "今天也要开心哦！", "被你发现啦！",
              "摸摸头，我在充电中…", "咦？你叫我吗"],
    "hover": ["诶？你在看我吗", "你的鼠标好暖和", "想跟我玩吗？", "我在这儿哦"],
    "hungry": ["咕噜噜…肚子饿了", "想吃点什么…", "有吃的吗？我饿了", "闻到香味了！"],
    "sleepy": ["呼啊…好困…", "眼皮好重…", "让我眯一会儿…", "困困的…"],
    "bored": ["好无聊呀…", "陪我玩会儿嘛", "我们来玩个游戏吧？", "发呆中…"],
    "selftalk": ["今天天气不错呢", "我在想晚饭吃什么", "你工作辛苦啦", "要不要休息一下？",
                 "我一直都在这里哦", "记得多喝水呀", "偷懒一下也没关系"],
    "pet": ["好舒服～再摸摸", "呼噜呼噜…", "最喜欢你了！", "再摸一会儿嘛"],
    "eat": ["咕嘟咕嘟…好喝！", "谢谢投喂！", "珍珠好Q弹～", "满足～"],
    "refuse": ["吃不下啦…肚子好撑", "真的吃不下了…", "先放着，我等会儿吃"],
    # ---- 赠送礼物 ----
    "gift": ["谢谢你！我会好好收着的～", "诶…是给我的吗？开心！", "收到礼物啦，我会珍惜的"],
    "gift_love": ["哇！这是我最喜欢的！", "你怎么知道我想要这个…好感动",
                  "最喜欢你了！这个我要收藏一辈子"],
    "sleep": ["晚安…zzZ", "做个好梦…", "先睡一会儿…"],
    "wake": ["睡醒啦！精神满满！", "唔…几点了？", "我回来啦！"],
    "drag": ["哇——好高！", "要带我去哪儿？", "飞起来啦～"],
    "drop": ["这里不错，就住这儿了", "新家！", "站稳啦～"],
    "ready": ["我来啦！", "初次见面，请多指教～"],
    # ---- 第二阶段：状态驱动的新台词 ----
    "sad": [                                    # 心情过低时的伤感文案（可点击刷新）
        "有点难过…可以陪我说说话吗",
        "我是不是…不太讨人喜欢呀",
        "今天好像没什么力气笑呢…",
        "能不能…抱一下我",
        "心里空空的，像没装满的奶茶",
        "我是不是被忘记了…",
        "没关系，我自己待一会儿就好",
        "要是能被需要就好了…",
        "眼泪在打转了，但我会忍住的",
        "有点想哭，可是我是个小团子呀",
    ],
    "sad0": [                                   # 心情归零专用（更丧一点）
        "呜…我好像真的撑不住了",
        "什么都做不好…对不起",
        "让我一个人待着吧…",
        "今天…不想笑了",
    ],
    "complain_sleep": [                         # 被吵醒的抱怨
        "唔…干嘛呀，我正睡着呢…",
        "才睡了一会儿…好困…",
        "别闹啦，我还没睡够…",
        "叫醒我是有什么急事吗…",
    ],
    "complain_hungry": ["肚子好饿…先给我点吃的吧", "空着肚子动不了啦…", "咕噜噜…听，肚子在抗议"],
    "complain_sick": ["我有点不舒服…能照顾一下我吗", "头晕晕的…想被摸摸", "生病好难受…"],
    "complain_busy": ["现在不想动啦…", "让我歇会儿嘛"],
    "joke": [                                   # 讲笑话（搞怪动作 素材4）
        "为什么奶蛙不减肥？因为圆一点才可爱呀！",
        "我去健身房了…然后办了张年卡就回家了！",
        "你猜我最喜欢的运动是什么？躺着！",
        "我昨天梦见自己会飞，醒来发现是被你拎起来了。",
        "别看我圆，我可是有腰的…只是还在找。",
        "朋友问我几岁，我说我还是个宝宝呀～",
    ],
    "joke_laugh": ["哈哈哈！我自己先笑为敬", "嘿嘿，好笑吧～", "憋住…不许不笑！"],
    "sick": ["咳咳…好像有点感冒了", "头好晕…今天没什么精神", "难受…需要治疗一下"],
    "treat": ["谢谢你照顾我！舒服多啦～", "有你在真好，我马上就好起来！", "叮！治疗完成，恢复活力～"],
    "resleep": ["不行了…我又要睡着了…zzZ", "眼睛睁不开了…晚安…", "再睡一会儿…就一会儿…"],
    "wake_forced": ["唔…几点了…我是被叫醒的吗", "呼啊…还想再睡会儿…"],
}


class ChatBrain:
    """
    极简聊天引擎：关键词规则 + 随机可爱短句。
    ★ 扩展点：把 llm_reply() 换成真实大模型调用即可（见文末升级思路）。
    """

    RULES = [
        (("你好", "hi", "hello", "嗨", "在吗"), ["你好呀！我是奶蛙～", "嗨嗨！我在的！", "你来啦！"]),
        (("名字", "叫什么", "你是谁"), ["我叫奶蛙，是一只桌宠", "我是你的桌面小团子奶蛙呀"]),
        (("吃", "饿", "饭", "奶茶", "投喂"), ["我想喝珍珠奶茶！", "右键点「喂食」就能投喂我哦", "肚子…有点饿"]),
        (("睡", "困", "晚安"), ["那我们一起去睡觉吧…zzZ", "晚安，做个好梦"]),
        (("累", "加班", "工作", "烦", "难", "压力"), ["辛苦啦，先喝口水吧", "摸鱼也是工作的一部分！",
                                                  "休息一下，我陪着你"]),
        (("喜欢", "爱你", "可爱", "萌"), ["嘿嘿…我也喜欢你！", "被夸到了，开心！", "害羞…"]),
        (("谢谢", "感谢"), ["不客气～", "举手之劳啦"]),
        (("再见", "拜拜", "走了"), ["记得回来看看我呀", "拜拜～我在这儿等你"]),
        (("玩", "游戏", "无聊"), ["那我们来玩猜拳吧？…算了，我只会出包子", "陪我散散步？"]),
        (("?", "？", "什么", "吗"), ["嗯…让我想想", "这个问题好难，我只是一只小团子", "大概…是这样吧？"]),
    ]
    FALLBACK = ["原来是这样呀", "嗯嗯，我在听", "听起来不错呢", "记下了记下了",
                "嘿嘿，跟你聊天真开心", "然后呢然后呢？", "我懂我懂～"]

    @classmethod
    def reply(cls, text: str) -> str:
        """对外统一入口（同步、纯本地）：关键词规则 → 自定义钩子 → 兜底短句。"""
        return cls.rules_reply(text)

    @classmethod
    def rules_reply(cls, text: str) -> str:
        """
        本地规则回复。既是大模型关闭时的默认方案，
        也是大模型请求失败时的「降级兜底」——保证现场演示永远有反应。
        """
        t = (text or "").strip()
        if not t:
            return random.choice(cls.FALLBACK)
        low = t.lower()
        for keys, answers in cls.RULES:
            if any(k in low for k in keys):
                return random.choice(answers)
        hook = cls.llm_reply(t)          # ★ 想写死自己的回复逻辑，改这个钩子
        if hook:
            return hook
        return random.choice(cls.FALLBACK)

    @staticmethod
    def build_system_prompt(stats_line: str, mood: str, memory: str = "") -> str:
        """
        ★ 人格联动的关键：把「人设」+「当前四维状态」一起塞进 system prompt，
        这样接上大模型后，宠物会因为饿了而抱怨、困了而打哈欠，而不是永远一个腔调。
        """
        mood_cn = {"fine": "心情不错", "hungry": "肚子很饿", "sleepy": "很困想睡",
                   "bored": "有点无聊", "sleep": "正在睡觉"}.get(mood, "心情不错")
        base = SYSTEM_PROMPT_TMPL.format(mood=mood_cn,
                                         stats=stats_line or "状态正常")
        if memory:
            base += "\n" + memory
        return base

    # ------------------------------------------------------------------
    # ★ 大模型接入钩子（默认关闭）
    #   打开方式：pip install requests，填好 API KEY，然后 return 即可。
    # ------------------------------------------------------------------
    @staticmethod
    def llm_reply(text: str):
        return None
        # import requests
        # r = requests.post(
        #     "https://api.deepseek.com/chat/completions",
        #     headers={"Authorization": "Bearer <YOUR_KEY>"},
        #     json={"model": "deepseek-chat",
        #           "messages": [{"role": "system", "content": "你是桌面宠物奶蛙，像朋友一样正常聊天，20字内。"},
        #                        {"role": "user", "content": text}],
        #           "max_tokens": 60},
        #     timeout=8)
        # return r.json()["choices"][0]["message"]["content"].strip()


# ==============================================================================
# 6.2 养成系统数据层 —— 物品 / 成就 / 每日任务 / 亲密度台词 / 成长形态
# ==============================================================================
# 【设计说明】
#   全部数据集中在这里，改数值不用翻逻辑；素材由用户后续提供，
#   物品图片暂用文字占位（ITEM_ICON 里写素材名，注册到 ASSETS 后自动可用）。
# ==============================================================================

# ---- 模块2：金币商店 + 背包物品 ----
#   full/happy/energy/bored = 使用后对四维的增减；cure=治病；revive=救瘫；random=随机增益
ITEMS = {
    "珍珠奶茶": dict(cat="食物", price=20, icon="item_milktea",
                 desc="香浓珍珠奶茶：饱食 +25", full=25, happy=3),
    "草莓蛋糕": dict(cat="食物", price=45, icon="item_cake",
                 desc="甜甜的草莓蛋糕：饱食 +40、心情 +15", full=40, happy=15),
    "营养套餐": dict(cat="食物", price=60, icon="item_meal",
                 desc="营养均衡：饱食 +30 并治愈生病", full=30, happy=5, cure=True),
    "小球": dict(cat="玩具", price=30, icon="item_ball",
                desc="追着小球跑：心情 +30、无聊 -20", happy=30, bored=-20),
    "逗猫棒": dict(cat="玩具", price=40, icon="item_wand",
                 desc="忍不住扑上去：心情 +25、无聊 -30", happy=25, bored=-30),
    "音乐盒": dict(cat="玩具", price=50, icon="item_music",
                 desc="听着音乐打个盹：心情 +20、精力 +20", happy=20, energy=20),
    "幸运饼干": dict(cat="特殊", price=25, icon="item_cookie",
                  desc="随机增益；吃掉后当天小游戏奖励 x2！", random_gift=True,
                  game_double=True),
    "复活药": dict(cat="特殊", price=120, icon="item_revive",
                 desc="从「瘫掉」状态直接救回，四维各 +30", revive=True),
    # ---- 模块6：探险前使用的道具（在「外出探险」窗口的下拉框里用，不能直接吃）----
    "便当": dict(cat="探险", price=35, icon="item_bento", buff="bento",
               desc="探险用：饱食不衰减，且不会迷路"),
    "手电筒": dict(cat="探险", price=45, icon="item_torch", buff="flashlight",
                desc="探险用：小树林史诗掉落率翻倍"),
    "指南针": dict(cat="探险", price=40, icon="item_compass", buff="compass",
                desc="探险用：迷路概率大幅降低"),
    "雨伞": dict(cat="探险", price=30, icon="item_umbrella", buff="umbrella",
               desc="探险用：免疫下雨事件"),
    "大背包": dict(cat="探险", price=60, icon="item_bag", buff="bigbag",
                desc="探险用：本次携带上限 +2"),
    # ---- 探险掉落里可以直接用的 ----
    "野花": dict(cat="玩具", price=5, icon="mat_flower",
               desc="闻一闻就开心：心情 +8", happy=8),
    "毛巾": dict(cat="特殊", price=15, icon="item_towel",
               desc="擦干用：心情 +5，抵消淋雨", happy=5),
    # ---- 第七阶段：挂机加速道具 ----
    "探险指南针": dict(cat="特殊", price=80, icon="item_advcompass", boost_adv=True,
                  desc="下一次探险收益 x2（可与其他道具叠加）"),
}
# 新玩家初始背包（避免一上来什么都玩不了）
INVENTORY_START = {"珍珠奶茶": 1, "小球": 1}

# ---- 模块4：成就（condition 用 PetStats / 存档状态判断，见 check_achievements） ----
ACHIEVEMENTS = [
    dict(id="first_meet", name="初次见面", desc="第一次启动奶蛙", coins=20),
    dict(id="week_streak", name="无微不至", desc="连续 7 天每天都来陪它", coins=100),
    dict(id="foodie", name="美食家", desc="累计喂食 50 次", coins=80),
    dict(id="pet_master", name="摸鱼大师", desc="累计抚摸 10 分钟", coins=80),
    dict(id="rich", name="百万富翁", desc="金币达到 1000", coins=200),
    dict(id="max_level", name="满级大佬", desc="等级达到 Lv.20", coins=300),
    dict(id="soulmate", name="知心朋友", desc="亲密度达到「亲密伙伴」", coins=150),
    dict(id="survivor", name="大难不死", desc="从「瘫掉」状态把它救回来", coins=100),
    dict(id="night_owl", name="深夜陪伴", desc="凌晨 2~4 点还陪着它", coins=60),
]


# ---- 模块6：每日任务池（每天随机抽 DAILY_TASK_COUNT 个）----
DAILY_TASKS = [
    dict(id="feed3", name="投喂三次", desc="今天喂食 3 次", target=3, coins=30, exp=25,
         counter="feed"),
    dict(id="pet60", name="摸摸时间", desc="今天抚摸累计 60 秒", target=60, coins=30, exp=25,
         counter="pet_seconds"),
    dict(id="chat5", name="聊聊天", desc="今天聊 5 句", target=5, coins=25, exp=20,
         counter="chat"),
    dict(id="play2", name="一起玩玩具", desc="今天使用玩具 2 次", target=2, coins=35, exp=30,
         counter="play"),
    dict(id="happy10", name="保持好心情", desc="心情 ≥80 累计 10 分钟", target=600, coins=40,
         exp=35, counter="happy_seconds"),
]

# ---- 模块3：亲密度等级台词（不同羁绊说不同的话）----
BOND_LINES = {
    "陌生人": ["……你好", "你是谁呀？", "我还不认识你呢"],
    "熟人": ["嗯…又是你呀", "你还挺常来的", "今天也来啦？"],
    "朋友": ["嘿！我等你半天了", "今天想跟我聊什么？", "看到你就开心～"],
    "好朋友": ["你来啦！我一直在这儿呢", "今天也要一起玩哦！", "有你在真好～"],
    "亲密伙伴": ["你终于来啦…我都想你了", "今天也最喜欢你啦", "不许走太久哦，我会想你的"],
}
# 亲密度解锁的特殊互动台词
HUG_LINES = ["抱紧一点…好暖和", "嘿嘿，最喜欢抱抱了", "这样待着…真安心"]

# ---- 模块5：成长形态（素材缺失时用现有图等比缩放代替）----
#   GROWTH_STAGES 在 CFG 里定义：(最低等级, 名称, 体型缩放)
#   对应的外形素材名（用户后续提供即可自动启用；没有就用 idle 缩放）
GROWTH_ASSETS = {"幼年形态": "stage_baby", "少年形态": "idle", "成年形态": "stage_adult"}


def bond_tier(bond: float) -> str:
    """亲密度数值 → 等级名称（陌生人/熟人/朋友/好朋友/亲密伙伴）"""
    name = CFG.BOND_TIERS[0][1]
    for need, label in CFG.BOND_TIERS:
        if bond >= need:
            name = label
    return name


def growth_stage(level: int):
    """等级 → (名称, 体型缩放)。默认返回幼年形态。"""
    for need, name, scale in CFG.GROWTH_STAGES:
        if level >= need:
            return name, scale
    return CFG.GROWTH_STAGES[-1][1], CFG.GROWTH_STAGES[-1][2]


def exp_needed(level: int) -> int:
    """升级所需经验：EXP_BASE * level^EXP_POW（50 * lv^1.5）"""
    return int(round(CFG.EXP_BASE * (max(1, level) ** CFG.EXP_POW)))


def decay_multiplier(level: int) -> float:
    """等级越高，四维衰减越慢（养成有回报感）"""
    mult = 1.0 - (max(1, level) - 1) * CFG.LEVEL_DECAY_RELIEF
    return max(CFG.LEVEL_DECAY_FLOOR, mult)


# ==============================================================================
# 6.4 外出探险数据层 —— 地点 / 事件 / 材料 / 道具 Buff / 任务线
# ==============================================================================
# 【设计说明】
#   1. 全部数据集中在这里，改数值不用翻逻辑。
#   2. 地点插画、事件图标、掉落图片都由用户后续提供；缺失时用 emoji + 文字占位，
#      窗口照常打开（素材名见 spot["art"] / event["icon"] / MATERIALS[...]["icon"]）。
# ==============================================================================

# ---- 模块1：探险地点（等级解锁）----
ADVENTURE_SPOTS = {
    "park": dict(
        name="楼下小公园", emoji="🌳", art="spot_park", unlock_level=1,
        duration=30, energy_cost=15, coins=(5, 15),
        desc="熟悉的小公园，散散步就能捡到不少东西",
        common=["小石子", "野花", "松果", "普通饼干"],
        rare=["珍珠奶茶", "草莓蛋糕"],
        epic=["幸运饼干"],
        legendary=[],
    ),
    "street": dict(
        name="附近街区", emoji="🏘️", art="spot_street", unlock_level=3,
        duration=60, energy_cost=25, coins=(15, 40),
        desc="热闹的街道，什么都能捡到一点",
        common=["零食", "易拉罐", "小球", "野花"],
        rare=["逗猫棒", "音乐盒", "珍珠奶茶"],
        epic=["复活药"],
        legendary=[],
    ),
    "bigpark": dict(
        name="城市大公园", emoji="🎡", art="spot_bigpark", unlock_level=5,
        duration=120, energy_cost=40, coins=(40, 100),
        desc="很大很漂亮，稀有货不少，就是要走很久",
        common=["易拉罐", "零食", "野花", "小石子"],
        rare=["草莓蛋糕", "音乐盒", "逗猫棒"],
        epic=["复活药", "幸运饼干"],
        legendary=["限定围巾"],
    ),
    "forest": dict(
        name="神秘小树林", emoji="🌲", art="spot_forest", unlock_level=10,
        duration=180, energy_cost=60, coins=(80, 200),
        desc="雾蒙蒙的林子，据说藏着宝藏和传说",
        common=["松果", "野花", "易拉罐"],
        rare=["藏宝图碎片", "营养套餐", "音乐盒"],
        epic=["复活药", "幸运饼干", "稀有种子"],
        legendary=["奶蛙之铃", "松果帽子"],
    ),
}

# ---- 模块4：随机事件池（weight 越大越常见）----
#   字段说明：
#     coins / happy / energy / bond = 直接增减；coin_mult = 金币倍率
#     items = 附带物品；animal = 算作「遇到小动物」；quest = 触发任务线
#     blocked_by = 有这些 buff 就不会发生；weight_mod = 在对应 buff 下权重变化
ADVENTURE_EVENTS = [
    dict(id="squirrel", emoji="🐿️", name="遇到小松鼠", weight=1.2, animal=True,
         desc="它把一颗松果塞进你手里，还蹭了蹭你的手心", items={"松果": 1}, bond=5),
    dict(id="duck", emoji="🦆", name="遇到流浪鸭", weight=1.2, animal=True, quest="duck",
         desc="它摇摇摆摆跟着你走了一段路，好像在送你", happy=20),
    dict(id="chest", emoji="🎁", name="发现路边宝箱", weight=0.8,
         desc="打开一看，里面亮闪闪的！", coin_mult=2.0, random_rare=True),
    dict(id="rain", emoji="🌧️", name="突然下雨了", weight=1.0, blocked_by=("umbrella",),
         desc="毛都淋湿了…回家得用毛巾好好擦干", happy=-10),
    dict(id="lost", emoji="🧭", name="迷路了", weight=0.9, blocked_by=("bento",),
         desc="绕了好久才找到路，不过路上捡到了奇怪的东西",
         energy=-15, random_epic=True, weight_mod={"compass": 0.35}),
    dict(id="banana", emoji="🪨", name="踩到香蕉皮", weight=1.0,
         desc="啪叽一下摔了个屁股墩，但捡到了路人掉的钱", happy=-5, coins=15),
    dict(id="cat", emoji="🐱", name="遇到大橘猫", weight=1.2, animal=True,
         desc="被撸了一顿，它还很给面子地打了呼噜", happy=15, bored_clear=True),
    dict(id="bottle", emoji="📮", name="捡到漂流瓶", weight=0.6, quest="forest",
         desc="瓶里有一封信，看着像藏宝图的线索…", items={"藏宝图碎片": 1}),
    dict(id="flower", emoji="🌸", name="发现好看的花", weight=1.3,
         desc="顺手摘了一朵，香香的", items={"野花": 1}),
    dict(id="wallet", emoji="💰", name="捡到钱包", weight=0.7,
         desc="原地等了半小时还给失主，他非要塞给你谢礼", coins=40, bond=3),
]

# ---- 模块3：探险材料（可卖钱 / 任务信物）----
#   price>0 可以在背包里卖钱；售价 0 = 任务信物或限定装扮，只能收藏
MATERIALS = {
    "小石子": dict(emoji="🪨", price=2, icon="mat_stone", desc="圆圆的，挺好看"),
    "野花": dict(emoji="🌸", price=5, icon="mat_flower", desc="香香的"),
    "松果": dict(emoji="🌰", price=4, icon="mat_pinecone", desc="小松鼠最爱的"),
    "易拉罐": dict(emoji="🥫", price=6, icon="mat_can", desc="可以卖钱"),
    "零食": dict(emoji="🍬", price=3, icon="mat_snack", desc="路上顺手买的"),
    "普通饼干": dict(emoji="🍪", price=4, icon="mat_cookie", desc="干干的但很香"),
    "打砖块冠军奖牌": dict(emoji="🏅", price=200, icon="mat_medal",
                          desc="和奶蛙一起打通砖块的纪念，闪着光"),
    "稀有种子": dict(emoji="🌱", price=25, icon="mat_seed", desc="种下去会开出什么？"),
    "藏宝图碎片": dict(emoji="🗺️", price=0, icon="mat_map", desc="拼起来好像是张藏宝图"),
    "鸭鸭明信片": dict(emoji="📮", price=0, icon="mat_postcard", desc="鸭鸭送你的纪念"),
    "松果帽子": dict(emoji="🎩", price=0, icon="mat_hat", desc="小松鼠送的装扮"),
    "奶蛙之铃": dict(emoji="🔔", price=0, icon="mat_bell", desc="传说道具，探险收益 +50%"),
    "限定围巾": dict(emoji="🧣", price=0, icon="mat_scarf", desc="限定装扮，很暖和"),
}

# ---- 模块6：探险前可用的道具（buff）----
ADVENTURE_BUFFS = {
    "便当": dict(key="bento", emoji="🍙", desc="探险中饱食不衰减，且不会迷路",
               no_hunger_decay=True, block_events=("lost",)),
    "手电筒": dict(key="flashlight", emoji="🔦", desc="神秘小树林的史诗掉落率翻倍",
                 epic_double_spots=("forest",)),
    "指南针": dict(key="compass", emoji="🧭", desc="迷路概率大幅降低",
                 event_weight={"lost": 0.35}),
    "雨伞": dict(key="umbrella", emoji="☂️", desc="免疫下雨事件", block_events=("rain",)),
    "大背包": dict(key="bigbag", emoji="🎒", desc="本次携带上限 +2",
                bag_bonus=CFG.ADVENTURE_BAG_BONUS),
}

# 按 buff key 反查（buff 列表里存的是英文 key，如 "bento"/"umbrella"）
BUFF_BY_KEY = {v["key"]: v for v in ADVENTURE_BUFFS.values()}

# ---- 模块5：特殊任务线（长期目标）----
QUEST_LINES = {
    "squirrel": dict(
        name="松鼠的松果", emoji="🐿️", spot="park",
        desc="小松鼠的家被大风吹走了，帮它收集 5 颗松果重建",
        trigger_item="松果", target=5,
        rewards=dict(coins=200, exp=100, items={"松果帽子": 1}),
        reward_text="获得装扮「松果帽子」",
    ),
    "duck": dict(
        name="流浪鸭的归乡", emoji="🦆", spot="street",
        desc="鸭鸭想回家却不知道主人在哪，帮它拍 5 张照片",
        trigger_event="duck", target=5,
        rewards=dict(bond=100, items={"鸭鸭明信片": 1}),
        reward_text="鸭鸭送了你一张明信片，亲密度 +100",
    ),
    "forest": dict(
        name="神秘森林的传说", emoji="🌲", spot="forest",
        desc="漂流瓶里的藏宝图碎片，要集齐 3 张才能拼出宝藏位置",
        trigger_item="藏宝图碎片", target=3,
        rewards=dict(items={"奶蛙之铃": 1}, achievement="treasure_hunter"),
        reward_text="获得传奇道具「奶蛙之铃」，探险收益 +50%",
    ),
}

# 探险专用成就（与既有成就系统合并）
ADVENTURE_ACHIEVEMENTS = [
    dict(id="adv_first", name="初次探险", desc="第一次出门探险", coins=30),
    dict(id="adv_10", name="探险家", desc="累计探险 10 次", coins=90),
    dict(id="adv_50", name="资深探险家", desc="累计探险 50 次", coins=250),
    dict(id="treasure_hunter", name="寻宝猎人", desc="完成神秘森林的传说任务线", coins=200),
    dict(id="social", name="社交达人", desc="累计遇到 10 次野外小动物", coins=80),
    dict(id="lucky", name="欧皇", desc="单次探险获得传说掉落", coins=150),
    dict(id="night_adv", name="夜行者", desc="在凌晨 0~5 点出发探险过", coins=60),
]
# 把探险成就合并进主成就列表（成就面板/检查逻辑自动包含它们）
ACHIEVEMENTS = ACHIEVEMENTS + ADVENTURE_ACHIEVEMENTS

# ---- 探险台词（软萌风格，不要系统术语）----
ADV_LINES = {
    "depart": ["我去探险啦！等我回来～", "出发！回来给你带礼物～", "我出门啦，乖乖等我哦"],
    "return": ["我回来啦！看看我带回了什么～", "累死我了…不过收获满满！", "回家啦！想我了吗"],
    "early": ["唔…太累了，我先回来啦", "撑不住了…提前回家休息一下"],
    "busy": ["我正在探险中，别打扰我啦～", "在外面呢，等我回去再说嘛"],
    "tired": ["太累了，先睡一觉吧…", "精力不够啦，让我歇会儿再出门"],
    "halted": ["累到头昏眼花…只能先回家了", "实在走不动了，收益就打折吧…"],
}


def gift_bond_value(name: str) -> int:
    """
    一件物品能提升多少好感度。
    优先用物品自带的 gift_bond；没有就按价格折算（越贵越有心意）。
    """
    spec = ITEMS.get(name) or MATERIALS.get(name) or {}
    if "gift_bond" in spec:
        return int(spec["gift_bond"])
    price = spec.get("price", 0) or 0
    return max(2, int(round(price * CFG.GIFT_PRICE_RATE)))


def is_food(name: str) -> bool:
    return (ITEMS.get(name) or {}).get("cat") == "食物"


def is_giftable(name: str) -> bool:
    """能不能当礼物送（排除任务信物/探险装备，且不能是探险 buff 道具）"""
    if name in CFG.GIFT_BLOCKED:
        return False
    spec = ITEMS.get(name) or MATERIALS.get(name)
    if not spec:
        return False
    return True


def material_or_item(name: str) -> dict:
    """取掉落物的描述信息（先查 ITEMS 再查 MATERIALS）"""
    spec = ITEMS.get(name)
    if spec:
        return dict(emoji="🎁", price=spec["price"], desc=spec["desc"],
                    icon=spec.get("icon", ""), usable=True)
    m = MATERIALS.get(name, {})
    return dict(emoji=m.get("emoji", "❔"), price=m.get("price", 0),
                desc=m.get("desc", ""), icon=m.get("icon", ""), usable=False)


def now_day_str() -> str:
    return time.strftime("%Y-%m-%d")


# ==============================================================================
# 6.3 存档模块 —— savegame.json 读写（模块7）
# ==============================================================================
def save_path() -> str:
    return os.path.join(app_dir(), CFG.SAVE_FILE)


def _extra_save_fields(stats) -> dict:
    """把第十二阶段的扩展状态摊平进存档（键名按需求文档）"""
    try:
        return stats.extra.to_dict()
    except Exception:
        return {}


def load_savegame() -> dict:
    """读存档；没有或损坏就返回空字典（等于新档）。"""
    p = save_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        log_event("SAVE", f"读取存档成功：{p}")
        return data
    except Exception as exc:                       # noqa: BLE001
        log_event("SAVE", f"存档损坏，按新档处理：{exc}")
        return {}


def write_savegame(data: dict) -> bool:
    """原子写存档（先写临时文件再替换，避免中途崩溃写坏档）。"""
    p = save_path()
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as exc:                       # noqa: BLE001
        log_event("SAVE", f"写存档失败：{exc}")
        return False


def reset_savegame() -> bool:
    """删除存档（配合「重置养成」）。"""
    try:
        p = save_path()
        if os.path.isfile(p):
            os.remove(p)
        log_event("SAVE", "存档已重置")
        return True
    except Exception as exc:                       # noqa: BLE001
        log_event("SAVE", f"重置存档失败：{exc}")
        return False


def today_str() -> str:
    return time.strftime("%Y-%m-%d")


def now_hour() -> int:
    return time.localtime().tm_hour


def _day_gap(d1: str, d2: str) -> int:
    """两个 YYYY-MM-DD 相差几天（用于判断连续登录）"""
    try:
        t1 = time.mktime(time.strptime(d1, "%Y-%m-%d"))
        t2 = time.mktime(time.strptime(d2, "%Y-%m-%d"))
        return int(round((t2 - t1) / 86400.0))
    except Exception:
        return 999


# ==============================================================================
# 6.5 大模型对接 —— LLMConfig / LLMClient（OpenAI 兼容协议 · 只用标准库）
# ==============================================================================
# 【设计要点】
#   1. 用的是业界通用的 OpenAI Chat Completions 协议，所以 DeepSeek / OpenAI /
#      Kimi / 智谱 / 通义 / 本地 Ollama 一套代码全兼容，只换 base_url + model。
#   2. 只依赖 Python 标准库 urllib，不用 requests —— 保持「极少外部依赖」。
#   3. API Key 三级优先级：命令行 > 环境变量 > config.json，绝不硬编码进源码。
#   4. 网络请求跑在后台线程，结果通过 queue 回主线程刷新气泡，GUI 永不卡死。
#   5. 任何异常（超时 / 401 / 欠费 / 断网）都会自动降级到本地规则回复。
# ==============================================================================
SYSTEM_PROMPT_TMPL = (
    "你是一只名叫「奶蛙」的桌面宠物，形象是一坨黄色的小团子（像一团会走路的布丁）。"
    "说话要求：像朋友一样正常聊天，真诚、口语化、简短，不超过25个字，"
    "可以用「～」和「…」，不要用表情符号，不要用列表，不要解释自己是AI或程序。"
    "【重要】平时就正常聊天：回答问题、顺着话题聊、关心对方在做什么，"
    "不要主动讲笑话、不要玩梗、不要每句都卖萌刷宝。"
    "只有当对方明确要求听笑话时，才可以讲一个短笑话。"
    "你当前的状态是：{mood}（{stats}）。语气要和状态一致：饿了就撒娇要吃的，"
    "困了就说话懒洋洋，无聊就求陪玩，开心就活泼一点，心情低落就安静一点。"
)

PROVIDER_PRESETS = {
    "deepseek": dict(name="DeepSeek", base_url="https://api.deepseek.com/v1",
                     model="deepseek-chat", env="DEEPSEEK_API_KEY"),
    "bailian": dict(name="阿里云百炼 Token Plan", base_url="",
                    model="qwen-plus", env="DASHSCOPE_API_KEY"),
    "openai": dict(name="OpenAI", base_url="https://api.openai.com/v1",
                   model="gpt-4o-mini", env="OPENAI_API_KEY"),
    "moonshot": dict(name="Kimi 月之暗面", base_url="https://api.moonshot.cn/v1",
                     model="moonshot-v1-8k", env="MOONSHOT_API_KEY"),
    "zhipu": dict(name="智谱 GLM", base_url="https://open.bigmodel.cn/api/paas/v4",
                  model="glm-4-flash", env="ZHIPU_API_KEY"),
    "qwen": dict(name="通义千问(DashScope)", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                 model="qwen-turbo", env="DASHSCOPE_API_KEY"),
    "ollama": dict(name="本地 Ollama", base_url="http://127.0.0.1:11434/v1",
                   model="qwen2.5:7b", env=""),
    "custom": dict(name="自定义(OpenAI兼容)", base_url="", model="", env="LLM_API_KEY"),
}


# ------------------------------------------------------------------------------
# 阿里云百炼 Token Plan 混淆 Key（o1_...）本地解码
#   百炼控制台给的 o1_ 开头 Key 是「混淆」过的，要用它自家的 Feistel + CRC32 算法还原。
#   这里是从官方 bootstrap 脚本移植过来的纯 Python 版，末尾 6 位是 CRC32 base65 校验和，
#   解错会直接报错 —— 所以「解出来的一定是对的」，不需要外挂 Node.js CLI。
# ------------------------------------------------------------------------------
TP_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
TP_SIZE = len(TP_ALPHABET)
TP_MASK = 0xFFFFFFFF
TP_FNV_OFFSET = 0x811C9DC5
TP_GOLDEN = 0x9E3779B1
TP_FNV_PRIME = 0x01000193
TP_MIX1 = 0x85EBCA6B
TP_MIX2 = 0xC2B2AE35
TP_NONZERO = 0x6D2B79F5
TP_CRC_POLY = 0xEDB88320
TP_ROUNDS = 8
TP_SALT_LEN = 6
TP_CK_LEN = 6


def _tp_u32(v):
    return v & TP_MASK


def _tp_imul(a, b):
    return (_tp_u32(a) * _tp_u32(b)) & TP_MASK


def _tp_mix(state, value):
    return _tp_imul(state ^ value, TP_FNV_PRIME)


def _tp_next_state(s):
    s = _tp_u32(s)
    s ^= _tp_u32(s << 13)
    s ^= s >> 17
    s ^= _tp_u32(s << 5)
    return _tp_u32(s)


def _tp_round_mask(right_digits, salt, rnd, length):
    state = TP_FNV_OFFSET ^ _tp_imul(rnd + 1, TP_GOLDEN)
    state = _tp_mix(state, len(right_digits))
    state = _tp_mix(state, length)
    for ch in salt:
        state = _tp_mix(state, TP_ALPHABET.index(ch) + 1)
    for d in right_digits:
        state = _tp_mix(state, d + 1)
    state ^= state >> 16
    state = _tp_imul(state, TP_MIX1)
    state ^= state >> 13
    state = _tp_imul(state, TP_MIX2)
    state ^= state >> 16
    if state == 0:
        state = TP_NONZERO
    mask = []
    for i in range(length):
        state = _tp_u32(state + _tp_imul(i + 1, TP_GOLDEN))
        state = _tp_next_state(state)
        mask.append(state % TP_SIZE)
    return mask


def _tp_crc32(text: str) -> int:
    checksum = TP_MASK
    for ch in text:
        checksum ^= ord(ch)
        for _ in range(8):
            checksum = ((checksum >> 1) ^ TP_CRC_POLY) if (checksum & 1) else (checksum >> 1)
            checksum &= TP_MASK
    return checksum ^ TP_MASK


def _tp_base65(value: int, length: int) -> str:
    out = ["A"] * length
    remaining = _tp_u32(value)
    for i in range(length - 1, -1, -1):
        out[i] = TP_ALPHABET[remaining % TP_SIZE]
        remaining = (remaining - (remaining % TP_SIZE)) // TP_SIZE
    if remaining != 0:
        raise ValueError("混淆 Key 长度异常")
    return "".join(out)


def decode_token_plan_key(token: str) -> str:
    """把百炼的 o1_ 混淆 Key 还原成真 Key；校验和不符会抛 ValueError。"""
    token = (token or "").strip()
    if len(token) < 3 + TP_SALT_LEN + TP_CK_LEN + 1 or not token.startswith("o1_"):
        raise ValueError("不是 o1_ 开头的百炼 Token Plan Key")
    body = token[3:]
    if any(c not in TP_ALPHABET for c in body):
        raise ValueError("Key 含非法字符")
    salt = body[:TP_SALT_LEN]
    payload = body[TP_SALT_LEN:len(body) - TP_CK_LEN]
    checksum = body[-TP_CK_LEN:]
    digits = [TP_ALPHABET.index(c) for c in payload]
    mid = len(digits) >> 1
    left, right = list(digits[:mid]), list(digits[mid:])
    for rnd in range(TP_ROUNDS - 1, -1, -1):          # Feistel 逆运算
        prev_right = list(left)
        mask = _tp_round_mask(prev_right, salt, rnd, len(right))
        prev_left = [(right[i] - mask[i] + TP_SIZE) % TP_SIZE for i in range(len(right))]
        left, right = prev_left, prev_right
    api_key = "".join(TP_ALPHABET[d] for d in (left + right))
    if any(c not in TP_ALPHABET for c in api_key):
        raise ValueError("解码结果非法")
    if checksum != _tp_base65(_tp_crc32(api_key), TP_CK_LEN):
        raise ValueError("校验和不匹配（Key 可能复制不完整）")
    return api_key


class LLMError(Exception):
    """大模型调用失败（带中文可读原因，方便现场排障）。"""


class LLMConfig:
    """
    大模型配置。优先级：命令行参数 > 环境变量 > config.json > 内置默认值。
    """

    def __init__(self, enabled=False, provider="deepseek", api_key="", base_url="", model="",
                 timeout=12.0, max_tokens=140, temperature=1.0, history_turns=6,
                 key_source="(未配置)", config_path="", workspace="", region="cn-beijing"):
        self.enabled = bool(enabled)
        self.provider = provider
        self.workspace = (workspace or "").strip()
        self.region = (region or "cn-beijing").strip()
        self.key_source = key_source
        self.config_path = config_path
        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])
        self.preset_name = preset["name"]
        # ★ 阿里云百炼：base_url 由「workspace + region」拼出来，不用手填
        if not base_url and provider == "bailian" and self.workspace:
            base_url = f"https://{self.workspace}.{self.region}.maas.aliyuncs.com/compatible-mode/v1"
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.model = model or preset["model"]
        # ★ o1_ 开头的是百炼 Token Plan 混淆 Key，这里自动解码成真 Key
        self.raw_api_key = api_key
        self.api_key = api_key
        self.key_error = ""
        if api_key.startswith("o1_"):
            try:
                self.api_key = decode_token_plan_key(api_key)
                self.key_source = f"{key_source}（o1_ 已自动解码）"
            except Exception as exc:                   # noqa: BLE001
                log_event("LLM-KEY", f"o1_ 解码失败：{exc}")
                self.api_key = ""
                self.key_error = str(exc)
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.history_turns = int(history_turns)

    # ---------- 加载 ----------
    @classmethod
    def load(cls, cli=None, config_names=("config.json", "pet_config.json")):
        """
        读取配置：先找 config.json，再叠加环境变量，最后叠加命令行参数。
        cli 形如 dict(provider=..., api_key=..., mode="auto|on|off", base_url=..., model=...)
        """
        cli = cli or {}
        data, cfg_path = {}, ""
        for name in config_names:
            for root in (app_dir(), os.getcwd()):
                p = os.path.join(root, name)
                if os.path.isfile(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        cfg_path = p
                    except Exception as exc:
                        print(f"[提示] 配置文件 {p} 解析失败：{exc}", flush=True)
                    break
            if cfg_path:
                break
        sec = data.get("llm", {}) if isinstance(data, dict) else {}

        provider = cli.get("provider") or sec.get("provider") or "deepseek"
        provider = str(provider).lower()
        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])

        # API Key：命令行 > 配置文件 > 环境变量（环境变量放最后，方便 CI/演示机统一注入）
        api_key, key_source = "", "(未配置)"
        if cli.get("api_key"):
            api_key, key_source = cli["api_key"], "命令行 --llm-key"
        elif sec.get("api_key"):
            api_key, key_source = str(sec["api_key"]).strip(), os.path.basename(cfg_path or "config.json")
        else:
            for env_name in ([preset["env"]] if preset["env"] else []):
                if os.environ.get(env_name):
                    api_key, key_source = os.environ[env_name].strip(), f"环境变量 {env_name}"
                    break

        cfg = cls(
            provider=provider,
            api_key=api_key,
            base_url=cli.get("base_url") or sec.get("base_url", ""),
            model=cli.get("model") or sec.get("model", ""),
            workspace=cli.get("workspace") or sec.get("workspace", ""),
            region=cli.get("region") or sec.get("region", "cn-beijing"),
            timeout=cli.get("timeout") or sec.get("timeout", 12.0),
            max_tokens=cli.get("max_tokens") or sec.get("max_tokens", 140),
            temperature=sec.get("temperature", 1.0),
            history_turns=sec.get("history_turns", 6),
            key_source=key_source,
            config_path=cfg_path,
        )
        # 开关：auto=有 Key 就开；on=强制开（没 Key 也开，好让用户看到报错原因）；off=强制关
        mode = (cli.get("mode") or sec.get("mode") or "auto").lower()
        if mode == "on":
            cfg.enabled = True
        elif mode == "off":
            cfg.enabled = False
        else:
            cfg.enabled = bool(api_key) or provider == "ollama"
        cfg.mode = mode
        return cfg

    def describe(self) -> str:
        if not self.enabled:
            return "未开启（本地规则回复）"
        tail = "" if self.api_key else " · 无Key(本地模型)"
        return f"已开启 · {self.preset_name} / {self.model}{tail}"

    def hint(self) -> str:
        """给用户看的开启指引。"""
        preset = PROVIDER_PRESETS.get(self.provider, PROVIDER_PRESETS["deepseek"])
        env = preset["env"] or "LLM_API_KEY"
        return (f"设置环境变量 {env}=你的Key，"
                f"或把 config.example.json 复制为 config.json 并填入 api_key")


class LLMClient:
    """OpenAI 兼容协议的极简客户端（后台线程调用，阻塞式）。"""

    def __init__(self, cfg: LLMConfig, verbose: bool = False):
        self.cfg = cfg
        self.verbose = verbose
        self.history: list[dict] = []        # 多轮上下文记忆
        self.last_error = ""

    # ---------- 对外 ----------
    def chat(self, text: str, stats_line: str = "", mood: str = "fine",
             memory: str = "") -> str:
        """发一轮对话，返回宠物要说的话。memory 会拼进 system prompt。"""
        messages = [{"role": "system",
                     "content": ChatBrain.build_system_prompt(stats_line, mood,
                                                              memory)}]
        keep = max(0, self.cfg.history_turns) * 2
        if keep:
            messages += self.history[-keep:]
        messages.append({"role": "user", "content": text})
        reply = self._post(messages)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > 40:                       # 防止无限增长
            self.history = self.history[-20:]
        return reply

    def test(self, text: str = "你好") -> str:
        """连通性自测（--llm-test 用）。"""
        return self._post([{"role": "system", "content": "回复请简短可爱，20字内。"},
                           {"role": "user", "content": text}])

    # ---------- 内部 ----------
    def _post(self, messages) -> str:
        if not self.cfg.base_url:
            raise LLMError("没有配置 base_url（自定义厂商时必须填）")
        if not self.cfg.model:
            raise LLMError("没有配置模型名（用 --llm-model 或 config.json 的 model 指定）")
        url = self.cfg.base_url + "/chat/completions"
        payload = json.dumps({
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "stream": False,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = "Bearer " + self.cfg.api_key
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        if self.verbose:
            print(f"[LLM] POST {url} model={self.cfg.model} msgs={len(messages)}", flush=True)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:180]
            self.last_error = f"HTTP {exc.code} {body}"
            if exc.code in (401, 403):
                raise LLMError(f"鉴权失败({exc.code})，请检查 API Key 是否正确/是否欠费") from exc
            if exc.code == 404:
                raise LLMError(f"接口 404，请检查 base_url 是否为 OpenAI 兼容地址") from exc
            if exc.code == 429:
                raise LLMError("触发限流(429)，稍后再试") from exc
            raise LLMError(f"接口错误 {exc.code}：{body}") from exc
        except Exception as exc:            # 超时 / DNS / 断网
            self.last_error = str(exc)
            raise LLMError(f"网络异常：{exc}") from exc

        try:
            data = json.loads(raw)
            reply = data["choices"][0]["message"]["content"]
        except Exception as exc:
            self.last_error = raw[:180]
            raise LLMError(f"返回结构异常：{raw[:120]}") from exc
        reply = (reply or "").strip().replace("\n", " ")
        if not reply:
            raise LLMError("模型返回了空内容")
        if len(reply) > 60:                 # 气泡太长不好看，礼貌截断
            reply = reply[:56] + "…"
        return reply


# ==============================================================================
# 6.6 API Key 接入向导 —— 把 Key 写进 config.json，并当场验证能不能用
# ==============================================================================
# 两种用法：
#   · 图形向导（给用户）：双击 配置API密钥.bat  →  选厂商、粘贴 Key、点「保存并测试」
#   · 命令行（可脚本化）：python desktop_pet.py --set-llm-key sk-xxx --llm-provider deepseek
# Key 只会写进本机 config.json（已在 .gitignore 里），不会写进源码、不会上传。
# ==============================================================================
def default_config_path() -> str:
    """config.json 的默认位置（脚本目录）。"""
    return os.path.join(app_dir(), "config.json")


def save_llm_config(path: str, provider: str, api_key: str, model: str = "",
                    base_url: str = "", workspace: str = "", region: str = "") -> str:
    """把大模型配置写进 config.json（保留文件里其它字段）。返回写入的路径。"""
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    llm = data.get("llm") or {}
    llm.update({
        "mode": "auto",
        "provider": provider,
        "api_key": api_key.strip(),
        "model": (model or "").strip(),
        "base_url": (base_url or "").strip(),
        "workspace": (workspace or "").strip(),
        "region": (region or "").strip() or "cn-beijing",
    })
    data["llm"] = llm
    if "pet" not in data:
        data["pet"] = {"height": CFG.PET_HEIGHT}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def test_llm_config(provider: str, api_key: str, model: str = "", base_url: str = "",
                    text: str = "你好", workspace: str = "", region: str = "") -> str:
    """用给定参数真发一次请求做连通性测试；成功返回模型回复，失败抛 LLMError。"""
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])
    cfg = LLMConfig(provider=provider, api_key=api_key, model=model, base_url=base_url,
                    timeout=15.0, enabled=True, workspace=workspace, region=region)
    if not api_key and preset["env"]:
        raise LLMError("没有填写 API Key")
    if api_key.startswith("o1_") and not cfg.api_key:
        raise LLMError("o1_ 混淆 Key 解码失败：" + getattr(cfg, "key_error", "格式不对"))
    if provider == "bailian" and not cfg.base_url:
        raise LLMError("百炼需要填写 Workspace（形如 ws-xxxxxxxx），或直接填完整接口地址")
    return LLMClient(cfg).test(text)


def llm_set_key_cli(provider: str, api_key: str, model: str = "", base_url: str = "",
                    cfg_path: str = "", do_test: bool = True, workspace: str = "",
                    region: str = "") -> int:
    """命令行方式接入 Key：写配置 + 测连通性。"""
    path = cfg_path or default_config_path()
    save_llm_config(path, provider, api_key, model, base_url, workspace, region)
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])
    real = api_key
    note = ""
    if api_key.startswith("o1_"):
        try:
            real = decode_token_plan_key(api_key)
            note = "（o1_ 混淆 Key 已自动解码）"
        except Exception as exc:                   # noqa: BLE001
            real, note = api_key, f"（o1_ 解码失败：{exc}）"
    print("=" * 74)
    print(" API Key 已写入配置文件" + note)
    print(f"   文件    : {path}")
    print(f"   厂商    : {preset['name']}（{provider}）")
    print(f"   模型    : {model or preset['model']}")
    if provider == "bailian":
        print(f"   工作空间: {workspace or '(未填)'}   地域: {region or 'cn-beijing'}")
    print(f"   Key     : {real[:6]}…{real[-4:]}" if len(real) > 12
          else f"   Key     : {'(空，本地模型无需 Key)' if not real else real}")
    print("=" * 74)
    if not do_test:
        return 0
    if not api_key and preset["env"]:
        print("[跳过测试] 没有 Key，无法测试。")
        return 3
    print("正在测试连通性 ...")
    t0 = time.time()
    try:
        reply = test_llm_config(provider, api_key, model, base_url, workspace=workspace,
                                region=region)
    except LLMError as exc:
        print(f"[失败] {exc}")
        print("       常见原因：Key 复制不完整 / Key 与厂商不匹配 / 账户余额不足 / 没有联网")
        return 1
    print(f"[成功] 耗时 {time.time() - t0:.2f}s")
    print(f"       桌宠回复：{reply}")
    print()
    print("现在直接启动桌宠就能用大模型聊天了： python desktop_pet.py")
    return 0


def run_llm_setup(gui: bool = True, cfg_path: str = "") -> int:
    """
    图形化 API Key 接入向导（Tk 窗口）：
    选厂商 → 粘贴 Key → 「保存并测试」→ 现场告诉你通不通。
    """
    path = cfg_path or default_config_path()
    cur = LLMConfig.load()
    state = {"cfg_path": path, "busy": False}

    from tkinter import ttk          # Combobox 在子模块里，必须显式导入

    root = tk.Tk()
    root.title("桌宠 · 接入大模型 API Key")
    root.configure(bg=CFG.UI_BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    families = set(tkfont.families())
    fam = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else (
        "Microsoft YaHei" if "Microsoft YaHei" in families else "TkDefaultFont")
    F = (fam, 10)
    FB = (fam, 11, "bold")

    tk.Label(root, text="接入大模型 API Key", font=FB, bg=CFG.UI_BG).grid(
        row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 2))
    tk.Label(root, text="Key 只保存在本机 config.json（已加入 .gitignore），不会上传。",
             font=(fam, 9), fg="#777", bg=CFG.UI_BG).grid(
        row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))

    tk.Label(root, text="厂商", font=F, bg=CFG.UI_BG).grid(row=2, column=0, sticky="e", padx=(16, 8), pady=4)
    provider_box = ttk.Combobox(root, width=34, font=F, state="readonly",
                                values=[f"{k}  ·  {v['name']}" for k, v in PROVIDER_PRESETS.items()])
    provider_box.grid(row=2, column=1, columnspan=2, sticky="w", pady=4)

    tk.Label(root, text="API Key", font=F, bg=CFG.UI_BG).grid(row=3, column=0, sticky="e", padx=(16, 8), pady=4)
    key_var = tk.StringVar(value=cur.raw_api_key or cur.api_key)
    key_entry = tk.Entry(root, width=34, font=F, textvariable=key_var, show="*")
    key_entry.grid(row=3, column=1, sticky="w", pady=4)
    show_var = tk.BooleanVar(value=False)
    tk.Checkbutton(root, text="显示", font=(fam, 9), bg=CFG.UI_BG, variable=show_var,
                   command=lambda: key_entry.config(show="" if show_var.get() else "*")).grid(
        row=3, column=2, sticky="w", padx=6)

    tk.Label(root, text="模型", font=F, bg=CFG.UI_BG).grid(row=4, column=0, sticky="e", padx=(16, 8), pady=4)
    model_var = tk.StringVar(value="")
    tk.Entry(root, width=34, font=F, textvariable=model_var).grid(row=4, column=1, columnspan=2,
                                                                  sticky="w", pady=4)
    tk.Label(root, text="接口地址", font=F, bg=CFG.UI_BG).grid(row=5, column=0, sticky="e", padx=(16, 8), pady=4)
    url_var = tk.StringVar(value="")
    tk.Entry(root, width=34, font=F, textvariable=url_var).grid(row=5, column=1, columnspan=2,
                                                                sticky="w", pady=4)
    tk.Label(root, text="Workspace", font=F, bg=CFG.UI_BG).grid(row=6, column=0, sticky="e", padx=(16, 8), pady=4)
    ws_var = tk.StringVar(value=cur.workspace)
    tk.Entry(root, width=34, font=F, textvariable=ws_var).grid(row=6, column=1, columnspan=2,
                                                               sticky="w", pady=4)
    tk.Label(root, text="地域 Region", font=F, bg=CFG.UI_BG).grid(row=7, column=0, sticky="e", padx=(16, 8), pady=4)
    region_var = tk.StringVar(value=cur.region or "cn-beijing")
    tk.Entry(root, width=34, font=F, textvariable=region_var).grid(row=7, column=1, columnspan=2,
                                                                   sticky="w", pady=4)
    hint = tk.Label(root, text="（模型/地址留空＝用默认值；阿里云百炼只需填 Workspace + Region）",
                    font=(fam, 9), fg="#777", bg=CFG.UI_BG, wraplength=430, justify="left")
    hint.grid(row=8, column=1, columnspan=2, sticky="w", pady=(0, 6))

    result = tk.Text(root, height=6, width=52, font=(fam, 9), bg=CFG.UI_CARD, relief="flat", wrap="word")
    result.grid(row=9, column=0, columnspan=3, padx=16, pady=(4, 8), sticky="we")
    result.insert("1.0", "填好后点「保存并测试」，我会真的发一句「你好」给模型验证连通性。")
    result.config(state="disabled")

    def pick_provider(*_):
        key = provider_box.get().split("  ·  ")[0]
        preset = PROVIDER_PRESETS.get(key, {})
        model_var.set("")
        url_var.set("")
        if key == "bailian":
            hint.config(text="（阿里云百炼 Token Plan：填 Workspace 与 Region 即可，"
                             "接口地址会自动拼成 https://<workspace>.<region>.maas.aliyuncs.com/compatible-mode/v1；"
                             "Key 支持 o1_ 混淆格式，程序会自动解码）")
        elif key == "custom":
            hint.config(text=f"（自定义：默认模型 {preset.get('model', '') or '需自填'}，"
                             f"需要自填接口地址，例如 http://127.0.0.1:11434/v1）")
        else:
            hint.config(text=f"（{preset.get('name', '')} 默认模型：{preset.get('model', '') or '需自填'}）")
    provider_box.bind("<<ComboboxSelected>>", pick_provider)

    cur_key = cur.provider if cur.provider in PROVIDER_PRESETS else "deepseek"
    provider_box.set(f"{cur_key}  ·  {PROVIDER_PRESETS[cur_key]['name']}")
    pick_provider()
    # 回填上次保存的模型/地址，方便直接在原来的基础上改
    if cur.provider == cur_key:
        if cur.model and cur.model != PROVIDER_PRESETS[cur_key]["model"]:
            model_var.set(cur.model)
        if cur.base_url and cur.base_url != PROVIDER_PRESETS[cur_key]["base_url"]:
            url_var.set(cur.base_url)

    def say(msg: str):
        result.config(state="normal")
        result.delete("1.0", "end")
        result.insert("1.0", msg)
        result.config(state="disabled")

    def set_busy(busy: bool):
        state["busy"] = busy
        state_txt = "测试中…" if busy else ""
        btn_save.config(state="disabled" if busy else "normal", text="保存并测试")
        if busy:
            say("正在请求模型，请稍候…")

    def on_save_test():
        if state["busy"]:
            return
        provider = provider_box.get().split("  ·  ")[0]
        api_key = key_var.get().strip()
        model = model_var.get().strip()
        base_url = url_var.get().strip()
        workspace = ws_var.get().strip()
        region = region_var.get().strip() or "cn-beijing"
        preset = PROVIDER_PRESETS.get(provider, {})
        if not api_key and preset["env"] and provider != "ollama":
            say("请先粘贴 API Key。\n\n获取地址：\n"
                "· 阿里云百炼 https://bailian.console.aliyun.com/  （Key 支持 o1_ 格式，会自动解码）\n"
                "· DeepSeek  https://platform.deepseek.com/api_keys\n"
                "· OpenAI    https://platform.openai.com/api-keys\n"
                "· Kimi      https://platform.moonshot.cn/console/api-keys\n"
                "· 智谱      https://open.bigmodel.cn/usercenter/apikeys")
            return
        if provider == "bailian" and not workspace and not base_url:
            say("阿里云百炼需要填 Workspace（形如 ws-xxxxxxxx）。\n"
                "在百炼控制台右上角可以找到；Region 一般是 cn-beijing。")
            return
        save_llm_config(path, provider, api_key, model, base_url, workspace, region)
        set_busy(True)

        def work():
            try:
                reply = test_llm_config(provider, api_key, model, base_url,
                                        workspace=workspace, region=region)
                extra = ""
                if api_key.startswith("o1_"):
                    extra = "（o1_ 混淆 Key 已自动解码）"
                ok, msg = True, (f"✅ 接入成功！{extra}\n\n已写入：{path}\n"
                                 f"厂商：{preset.get('name')}　模型：{model or preset.get('model')}\n\n"
                                 f"模型回复：{reply}\n\n现在回桌宠右键 →「对话」即可聊天。")
            except LLMError as exc:
                ok, msg = False, (f"❌ 测试失败：{exc}\n\n配置已经保存（{path}），"
                                  f"可以改好 Key 后重新测试。\n"
                                  f"常见原因：Key 不完整 / 与厂商不匹配 / 余额不足 / 没联网。")
            except Exception as exc:                      # noqa: BLE001
                ok, msg = False, f"❌ 出错了：{exc}"

            def done():
                set_busy(False)
                say(msg)
                log_event("LLM-SETUP", ("OK " if ok else "FAIL ") + msg.replace("\n", " ")[:200])
            root.after(0, done)

        threading.Thread(target=work, name="llm-setup-test", daemon=True).start()

    def on_test_only():
        provider = provider_box.get().split("  ·  ")[0]
        api_key = key_var.get().strip()
        if not api_key and PROVIDER_PRESETS.get(provider, {}).get("env"):
            say("请先粘贴 API Key，再点「仅测试」。")
            return
        set_busy(True)

        def work():
            try:
                reply = test_llm_config(provider, api_key, model_var.get().strip(),
                                        url_var.get().strip(),
                                        workspace=ws_var.get().strip(),
                                        region=region_var.get().strip() or "cn-beijing")
                msg = f"✅ 连通正常！模型回复：{reply}\n\n（还没保存，点「保存并测试」才会写入配置）"
            except LLMError as exc:
                msg = f"❌ 测试失败：{exc}"

            def done():
                set_busy(False)
                say(msg)
            root.after(0, done)

        threading.Thread(target=work, name="llm-test-only", daemon=True).start()

    btns = tk.Frame(root, bg=CFG.UI_BG)
    btns.grid(row=10, column=0, columnspan=3, sticky="we", padx=16, pady=(0, 14))
    btn_save = tk.Button(btns, text="保存并测试", font=F, command=on_save_test,
                         bg="#ffe06a", activebackground="#ffd23f", relief="flat", padx=16, pady=4)
    btn_save.pack(side="left")
    tk.Button(btns, text="仅测试", font=F, command=on_test_only, relief="flat",
              padx=14, pady=4).pack(side="left", padx=8)
    tk.Button(btns, text="关闭", font=F, command=root.destroy, relief="flat",
              padx=14, pady=4).pack(side="right")

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
    key_entry.focus_force()
    log_event("LLM-SETUP", f"打开配置向导（当前配置：{cur.describe()}）")
    root.mainloop()
    return 0


# ==============================================================================
# 7. Brain —— 行为状态机（自主 AI 行为 + 情绪驱动）
# ==============================================================================
class Act:
    IDLE = "idle"       # 发呆
    WALK = "walk"       # 散步
    HAPPY = "happy"     # 被点击 → 播放动图蹦跳
    TALK = "talk"       # 对话中（大笑素材）
    EAT = "eat"         # 进食
    PET = "pet"         # 被抚摸（素材10）
    SLEEP = "sleep"     # 睡觉
    NAP = "nap"         # 自己找地方打盹
    HUNGRY = "hungry"   # 饥饿：肚子咕咕叫
    SLEEPY = "sleepy"   # 困倦：眼皮耷拉打哈欠
    BORED = "bored"     # 无聊：来回踱步张望
    LOOK = "look"       # 悬停好奇
    DRAG = "drag"       # 拖拽中
    # ---- 第二阶段新增 ----
    THINK = "think"     # 思考/回答前（素材1）
    JOKE = "joke"       # 讲笑话搞怪（素材4）
    SAD = "sad"         # 心情低落、播伤感文案（素材5/6）
    SICK = "sick"       # 生病（素材8）
    STARVING = "starving"   # 饱食归零（素材11）
    ALLZERO = "allzero"     # 四项全零的特殊状态（素材9）
    LEISURE = "leisure"     # 长时间没互动 → 放空/打瞌睡待机动画


# 行为 → 素材（身体状态类素材由 resolve_asset 动态决定）
ACT_ASSET = {
    Act.IDLE: "idle", Act.WALK: "idle", Act.HAPPY: "happy", Act.TALK: "talk",
    Act.EAT: "eat", Act.PET: "pat", Act.SLEEP: "idle", Act.NAP: "idle",
    Act.HUNGRY: "idle", Act.SLEEPY: "idle", Act.BORED: "idle", Act.LOOK: "idle",
    Act.DRAG: "idle", Act.THINK: "think", Act.JOKE: "joke",
    Act.SAD: "mood20", Act.SICK: "sick", Act.STARVING: "hungry0", Act.ALLZERO: "allzero",
    Act.LEISURE: "idle",
}
# 背景行为（可被自主决策随时替换）
AMBIENT_ACTS = {Act.IDLE, Act.WALK, Act.BORED, Act.NAP}
# 这些行为优先于「身体状况」动画（用户主动互动时先给反应）
INTERACT_ACTS = {Act.JOKE, Act.PET, Act.THINK, Act.EAT, Act.HAPPY, Act.TALK, Act.DRAG}


def resolve_asset(act: str, stats: "PetStats", sleep_anim_b: bool = False,
                  pat_anim: bool = True) -> str:
    """
    ★ 整套「状态 → 动画」的决策中心（第二阶段核心）。
    优先级：用户主动互动 > 身体状况（全零/饿坏/生病）> 心情表情 > 默认待机。

    素材对应关系（严格按用户给的说明）：
      全状态归零 → allzero(素材9)   饱食0 → hungry0(素材11)   生病 → sick(素材8)
      心情100 → mood100(素材2)      心情50 → mood50(素材3)    心情20 → mood20(素材6)
      心情0  → mood0(素材5)         抚摸 → pat(素材10)        思考 → think(素材1)
      讲笑话 → joke(素材4)          睡觉 → sleep_b(素材7) 或 原睡觉姿势（可点按切换）
    """
    # 1) 用户主动互动优先
    if act in INTERACT_ACTS:
        if act == Act.PET and not pat_anim:
            return "idle"
        return ACT_ASSET.get(act, "idle")
    # 2) 四项全归零：这是最惨的特殊状态，优先于睡觉展示
    if stats.all_zero():
        return "allzero"
    # 3) 睡觉：两种姿势轮换
    if act in (Act.SLEEP, Act.NAP):
        return "sleep_b" if sleep_anim_b else "idle"
    # 4) 身体状况
    if stats.full <= 0.5:
        return "hungry0"
    if stats.sick:
        return "sick"
    # 5) 心情表情
    if stats.happy <= CFG.MOOD0_AT:
        return "mood0"
    if stats.happy <= CFG.MOOD20_AT:
        return "mood20"
    if stats.happy <= CFG.MOOD50_AT:
        return "mood50"
    if stats.happy >= CFG.MOOD100_AT:
        return "mood100"
    # 6) 默认
    return "idle"


class Brain:
    """决定「现在在做什么、说什么、往哪走」。与窗口/渲染解耦，便于讲解与测试。"""

    def __init__(self, stats: PetStats, verbose: bool = False):
        self.stats = stats
        self.verbose = verbose
        self.act = Act.IDLE
        self.act_until = 0.0
        self.target_x = None            # 散步目标（窗口左上角 x）
        self.last_dir = 1               # 上次移动方向（无聊踱步反向用）
        self.flip = False               # 朝右走时为 True（素材本身朝左）
        self.say = None                 # 当前气泡文本
        self.say_until = 0.0
        self.frame_i = 0                # 动图帧号
        self.next_decision = 0.0
        self.last_user = time.time()    # ★ 初值必须是「现在」，否则会被误判成已闲置 5 分钟
        self.next_zzz = 0.0
        self.t0 = time.time()
        # ---- 第二阶段新增 ----
        self.sleep_anim_b = False       # 睡觉姿势开关（点按奶蛙可切换 素材7 ↔ 原睡姿）
        self.pat_anim = True            # 抚摸是否用专用动画（素材10）
        self.resleep_at = 0.0           # 被叫醒后的「再睡倒计时」
        self.sleep_clicks = 0           # 睡觉中被点了几次（1 次=换姿势，2 次=叫醒）
        self.sad_idx = 0                # 伤感文案轮播下标
        self.next_sad = 0.0             # 下次自动播伤感文案的时间
        self.notified = set()          # 已经提示过的状态（避免刷屏）
        # ---- 聊天笑话节流：正常聊天为主，偶尔才讲一个笑话 ----
        self.leisure_since = 0.0        # 进入待机动画的时间
        self.leisure_doze = False       # 当前是否在打瞌睡
        self.chat_msgs = 0              # 累计聊了多少句
        self.chat_jokes = 0             # 其中讲了几次笑话
        self.last_joke_t = 0.0          # 上次讲笑话的时间戳
        # ---- 第三阶段：养成系统 ----
        self.growth_anim_until = 0.0    # 形态切换过渡动画截止时间
        self.stage_name, self.stage_scale = growth_stage(self.stats.level)
        self.next_ach_check = 0.0       # 下次检查成就的时间
        self.next_save_hint = 0.0
        self.pending_tips = []          # 待播的提示（升级/成就/任务），逐条冒泡

    # ---------- 养成：奖励与提示 ----------
    def celebrate_levelup(self, ups: int) -> str:
        """升级反馈：气泡 + happy 动图 + 成长过渡动画"""
        txt = f"升级啦！Lv.{self.stats.level}"
        self.set_act(Act.HAPPY, 3.2, txt, 3.0)
        self.growth_anim_until = time.time() + CFG.GROWTH_ANIM_SEC
        self._log(f"升级 +{ups}", txt)
        return txt

    def queue_tip(self, text: str):
        """把提示排进队列（避免多个提示同时把气泡挤掉）"""
        if text:
            self.pending_tips.append(text)

    def flush_tips(self, now: float):
        """空闲时把队列里的提示一条条冒出来"""
        if not self.pending_tips:
            return
        if self.act in (Act.SLEEP, Act.NAP, Act.TALK, Act.JOKE, Act.EAT, Act.PET):
            return                              # 正在忙就不打断
        if self.current_text():                 # 上一句还没说完
            return
        tip = self.pending_tips.pop(0)
        self.show_text(tip, 3.4)
        self._log("提示:", tip)

    def sync_growth(self) -> bool:
        """等级变化 → 形态变化（返回是否发生了切换）"""
        name, scale = growth_stage(self.stats.level)
        if name != self.stage_name:
            self.stage_name, self.stage_scale = name, scale
            self.growth_anim_until = time.time() + CFG.GROWTH_ANIM_SEC
            self.queue_tip(f"我长大啦！现在是{name}")
            log_event("GROWTH", f"形态切换 → {name}（scale={scale}）")
            return True
        return False

    def check_progress(self, now: float):
        """周期性结算：每日任务 + 成就 + 登录奖励（由 tick 调用）"""
        s = self.stats
        # 每日任务进度
        for task in s.daily_progress():
            self.queue_tip(f"任务完成：{task['name']}（+{task['coins']}金币）")
        # 成就
        if now >= self.next_ach_check:
            self.next_ach_check = now + CFG.ACHIEVEMENT_CHECK_EVERY
            for ach in s.check_achievements():
                self.queue_tip(f"解锁成就：{ach['name']}（+{ach['coins']}金币）")

    # ---------- 小工具 ----------
    def _log(self, *a):
        if self.verbose:
            print(f"[{time.time() - self.t0:7.2f}s][{self.act:8s}]", *a, flush=True)

    # ---------- 待机动画（超过 IDLE_ANIM_DELAY 没互动）----------
    def leisure_tick(self, now: float, dt: float) -> bool:
        """
        返回 True 表示「当前处于待机放空状态」（上层据此跳过其他自主行为）。
        规则：无互动 ≥ IDLE_ANIM_DELAY 秒 → 进入 LEISURE；
              每 IDLE_ANIM_DOZE_EVERY 秒里有 IDLE_ANIM_DOZE_FOR 秒「打瞌睡」（换成素材7 趴睡图）；
              期间每隔几秒冒一句放空台词 / zzZ；用户一有动作立刻退出。
        """
        idle = now - self.last_user
        s = self.stats
        # 睡着/重度异常状态时不进待机动画（那些优先级更高）
        if s.sleeping or self.act in (Act.SLEEP, Act.STARVING, Act.SICK, Act.ALLZERO,
                                      Act.JOKE, Act.THINK, Act.EAT):
            if self.act == Act.LEISURE:
                self.set_act(Act.IDLE, 3.0)
            return False
        if idle < CFG.IDLE_ANIM_DELAY:
            if self.act == Act.LEISURE:                 # 用户回来了 → 退出待机
                self.set_act(Act.IDLE, 3.0)
                self._log("退出待机动画")
            return False
        # 进入 / 维持 LEISURE
        if self.act != Act.LEISURE:
            self.set_act(Act.LEISURE, 99999.0)
            self.leisure_since = now
            self._log("待机动画：放空")
        # 瞌睡循环：以进入待机的时间为基准做周期
        phase = (now - self.leisure_since) % CFG.IDLE_ANIM_DOZE_EVERY
        self.leisure_doze = phase < CFG.IDLE_ANIM_DOZE_FOR
        # 台词 / zzZ
        if now >= self.next_zzz:
            self.next_zzz = now + CFG.IDLE_ANIM_ZZZ_EVERY
            line = "…zzZ" if self.leisure_doze else random.choice(CFG.IDLE_ANIM_LINES)
            self.show_text(line, 2.8)
        return True

    def complain(self, why: str = "auto") -> str:
        """
        ★ 「互动时有抱怨文字」：根据当前身体/情绪状态挑一句抱怨。
        why="sleep" 被吵醒 / "hungry" 饿 / "sick" 生病 / "auto" 按状态自动判断
        """
        s = self.stats
        if why == "auto":
            if s.sleeping or self.act in (Act.SLEEP, Act.NAP):
                why = "sleep"
            elif s.sick:
                why = "sick"
            elif s.full <= CFG.HUNGRY_AT:
                why = "hungry"
            else:
                why = "busy"
        table = {"sleep": LINES["complain_sleep"], "hungry": LINES["complain_hungry"],
                 "sick": LINES["complain_sick"], "busy": LINES["complain_busy"]}
        line = random.choice(table.get(why, LINES["complain_busy"]))
        self.show_text(line, 3.0)
        self._log("抱怨:", line)
        return line

    def next_sad_line(self) -> str:
        """伤感文案：点一次换一句（循环播放）"""
        pool = LINES["sad0"] if self.stats.happy <= CFG.MOOD0_AT else LINES["sad"]
        self.sad_idx = (self.sad_idx + 1) % len(pool)
        line = pool[self.sad_idx]
        self.show_text(line, 4.5)
        self._log("伤感:", line)
        return line

    def toggle_sleep_anim(self):
        """点按睡觉中的奶蛙 → 切换睡觉动画（素材7 ↔ 原睡姿）"""
        self.sleep_anim_b = not self.sleep_anim_b
        self._log("切换睡姿:", "素材7" if self.sleep_anim_b else "原睡姿")
        return self.sleep_anim_b

    def set_act(self, act: str, dur: float | None = None, say: str | None = None,
                say_dur: float | None = None):
        if act != self.act:
            self._log("→", act)
        self.act = act
        now = time.time()
        self.act_until = now + (dur if dur is not None else 5.0)
        self.frame_i = 0
        if say:
            self.show_text(say, say_dur if say_dur is not None else max(2.0, min(6.0, 0.09 * len(say) + 2)))
        if act == Act.HAPPY:
            self.frame_i = 0

    def show_text(self, text: str, dur: float = 3.0, important=None):
        """
        ★ 紧凑化：普通台词 2 秒就收，重要（升级/成就/任务）4 秒，
        长文本按字数给足阅读时间。点击时立刻覆盖旧台词。
        """
        if important is None:
            important = any(k in text for k in ("升级", "成就", "任务", "解锁",
                                                "长大", "失败", "警告"))
        base = CFG.BUBBLE_MS_IMPORTANT if important else CFG.BUBBLE_MS_NORMAL
        if len(text) > 28:
            base = max(base, min(6.0, 0.085 * len(text) + 1.5))
        self.say = text
        self.say_until = time.time() + base
        self.bubble_seq = getattr(self, "bubble_seq", 0) + 1

    def current_text(self):
        if self.say and time.time() < self.say_until:
            return self.say
        return None

    def touch(self):
        """记录用户互动时间，用于判断「无人操作」的空闲状态。"""
        self.last_user = time.time()

    # ---------- 主循环 ----------
    def tick(self, dt: float, traveling: bool = False):
        now = time.time()
        active = (now - self.last_user) < 2.5
        resting = self.act in (Act.SLEEP, Act.NAP)
        events = self.stats.tick(dt, active, resting, traveling)   # 数值变化 + 身体状况事件
        s = self.stats
        if traveling:                       # 探险中：站着不动，不做自主行为
            return
        # ★ 待机动画：超过 5 分钟没互动就放空/打瞌睡（优先级高于普通自主行为）
        if self.leisure_tick(now, dt):
            return

        # ---- 养成：每日任务 / 成就 / 形态 / 提示队列 ----
        self.check_progress(now)
        self.sync_growth()
        self.flush_tips(now)

        # ---- 0) 身体状况事件（饿坏 / 生病）----
        for ev in events:
            if ev == "starving":
                self.set_act(Act.STARVING, 8.0, "咕噜噜…我饿坏了，快给我吃的！")
            elif ev == "got_sick":
                self.set_act(Act.SICK, 8.0, random.choice(LINES["sick"]))
                self._log("生病了！")

        # ---- 1) 精力归零 → 自动睡着；但如果四项全归零，优先播「全归零」特殊动画 ----
        if s.all_zero() and self.act != Act.ALLZERO:
            if self.act in (Act.SLEEP, Act.NAP):
                s.sleeping = False
            self.set_act(Act.ALLZERO, 15.0, "……", 3.0)
            self.resleep_at = 0.0
            self._log("四项状态全部归零")
        elif s.energy <= 0.5 and self.act not in (Act.SLEEP, Act.NAP) and not s.all_zero():
            self.set_act(Act.SLEEP, 999.0, "累到断电了…先睡一会儿…zzZ")
            self.resleep_at = 0.0
            self._log("精力归零 → 强制睡眠")

        # ---- 2) 被叫醒之后的「再睡倒计时」：无互动 5 秒就再次睡着 ----
        if self.resleep_at and self.act not in (Act.SLEEP, Act.NAP):
            if (now - self.last_user) > 0.8 and now >= self.resleep_at:
                self.stats.sleeping = True
                self.set_act(Act.SLEEP, 999.0, random.choice(LINES["resleep"]))
                self.resleep_at = 0.0
                self._log("5 秒没互动 → 再次睡着")

        # 3) 行为到期 → 回到待机
        if now > self.act_until and self.act not in (Act.IDLE,):
            if self.act in (Act.SLEEP,):
                self.wake_up()
            else:
                self.set_act(Act.IDLE, random.uniform(2.5, 5.0))

        # 4) 自动苏醒（睡够了）
        if self.act == Act.SLEEP and self.stats.energy >= 96:
            self.wake_up()

        # 5) 自主 AI 行为：只有在用户闲置且处于背景行为时才自行决定
        if (self.act in AMBIENT_ACTS) and (now - self.last_user) > CFG.IDLE_AI_DELAY:
            if now >= self.next_decision:
                self._decide()

        # 6) 情绪插播（饿/困/无聊/难过/生病）
        if self.act in AMBIENT_ACTS and (now - self.last_user) > 1.0:
            mood = s.mood()
            if mood == "starving" and self.act != Act.STARVING:
                self.set_act(Act.STARVING, 8.0, random.choice(LINES["complain_hungry"]))
            elif mood == "sick" and self.act != Act.SICK:
                self.set_act(Act.SICK, 7.0, random.choice(LINES["sick"]))
            elif mood == "hungry" and self.act != Act.HUNGRY:
                self.set_act(Act.HUNGRY, 6.0, random.choice(LINES["hungry"]))
            elif mood == "sleepy" and self.act not in (Act.SLEEPY, Act.NAP):
                self.set_act(Act.SLEEPY, 6.0, random.choice(LINES["sleepy"]))
            elif mood == "sad" and self.act != Act.SAD:
                self.set_act(Act.SAD, 8.0)
            elif mood == "bored" and self.act != Act.BORED:
                self.set_act(Act.BORED, 7.0, random.choice(LINES["bored"]))

        # 7) 心情过低 → 自动播伤感文案（每隔一段时间一句，点击可立刻刷新）
        if s.happy <= CFG.MOOD20_AT and self.act not in (Act.SLEEP, Act.NAP):
            if now >= self.next_sad:
                self.next_sad = now + CFG.SAD_REPEAT
                if self.act in AMBIENT_ACTS or self.act == Act.SAD:
                    self.next_sad_line()

        # 8) 睡觉时的 zzZ 气泡
        if self.act in (Act.SLEEP, Act.NAP) and now >= self.next_zzz:
            self.show_text(random.choice(["…zzZ", "呼…呼…", "Zzz…"]), 2.4)
            self.next_zzz = now + 4.0

    def _decide(self):
        """空闲时随机挑一个自主行为：散步 / 发呆 / 自言自语 / 打盹。"""
        now = time.time()
        lo, hi = CFG.IDLE_DECIDE_INTERVAL
        self.next_decision = now + random.uniform(lo, hi)
        mood = self.stats.mood()
        if mood in ("hungry", "sleepy"):
            return                                   # 情绪优先，交给上方插播逻辑
        pool = ([Act.WALK] * CFG.IDLE_WALK_WEIGHT + [Act.IDLE] * 3
                + [Act.BORED] * 2 + [Act.NAP] * CFG.IDLE_NAP_WEIGHT)
        if self.stats.energy < 45:
            pool += [Act.NAP] * 3
        pick = random.choice(pool)
        if pick == Act.WALK:
            self.set_act(Act.WALK, random.uniform(*CFG.IDLE_WALK_DUR))
            self._log("自主: 散步")
        elif pick == Act.BORED:
            self.set_act(Act.BORED, random.uniform(4.0, 7.0))
        elif pick == Act.NAP:
            self.set_act(Act.NAP, random.uniform(8.0, 14.0))
            self.stats.sleeping = False                # 打盹不算正式睡觉
            self._log("自主: 打盹")
        else:
            self.set_act(Act.IDLE, random.uniform(3.0, 7.0))
            if random.random() < CFG.IDLE_SELFTALK_RATE:   # 自言自语
                self.show_text(random.choice(LINES["selftalk"]), 3.4)
                self._log("自主: 自言自语")

    # ---------- 互动入口（由窗口调用）----------
    def clicked(self):
        """
        左键单击的统一入口（第二阶段重写）：
          · 睡着时点它 → 唤醒 + 抱怨；如果精力依旧见底，5 秒后自己再睡回去
          · 低落/归零时点它 → 刷新伤感文案（用户要求「可以点击刷新文案」）
          · 生病/饿坏时点它 → 抱怨
          · 其余情况 → 开心蹦跳
        """
        self.touch()
        s = self.stats
        # ① 睡觉中：第 1 次点 = 切换睡觉动画（素材7 ↔ 原睡姿）；再点一次 = 叫醒
        if self.act in (Act.SLEEP, Act.NAP) or s.sleeping:
            self.sleep_clicks += 1
            if self.sleep_clicks == 1:
                self.toggle_sleep_anim()
                self.show_text("（翻了个身…）", 2.0)
                return
            low_energy = s.energy < 25 or self.act == Act.SLEEP
            self.stats.sleeping = False
            self.sleep_clicks = 0
            self.set_act(Act.IDLE, 3.0)
            self.complain("sleep")
            if low_energy:                       # 精力没恢复 → 安排「再睡倒计时」
                self.resleep_at = time.time() + CFG.RESLEEP_DELAY
                self._log(f"安排再睡：{CFG.RESLEEP_DELAY:.0f} 秒后若无互动")
            return
        self.sleep_clicks = 0
        # ② 心情过低 / 归零 → 点击刷新伤感文案
        if s.happy <= CFG.MOOD20_AT:
            self.set_act(Act.SAD, 6.0)
            self.next_sad = time.time() + CFG.SAD_REPEAT
            self.next_sad_line()                 # 点一次换一句
            return
        # ③ 生病 / 饿坏 → 抱怨（不是开心）
        if s.sick or s.full <= 0.5:
            self.complain("sick" if s.sick else "hungry")
            self.set_act(Act.IDLE, 2.5)
            return
        # ④ 正常 → 开心（台词随亲密度变化）
        self.stats.on_click()
        self.set_act(Act.HAPPY, 3.2, self._greet_line(), 2.4)
        self._celebrate_if_levelup()

    def _celebrate_if_levelup(self) -> bool:
        """若刚才的互动带来升级，就播升级反馈（气泡 + happy 动图 + 形态过渡）"""
        ups = self.stats.take_ups()
        if ups:
            self.celebrate_levelup(ups)
            return True
        return False

    def _greet_line(self) -> str:
        """按亲密度等级挑不同台词（羁绊越深越亲昵）"""
        tier = self.stats.bond_tier()
        pool = BOND_LINES.get(tier)
        if pool and random.random() < 0.6:
            return random.choice(pool)
        return random.choice(LINES["click"])

    def hug(self) -> bool:
        """特殊互动「抱抱」：亲密度达标才解锁（用素材3 的抱心动画）"""
        if self.stats.bond < CFG.BOND_HUG_AT:
            need = CFG.BOND_HUG_AT - self.stats.bond
            self.show_text(f"我们还不够熟呢…再多陪陪我（还差 {need:.0f} 亲密度）", 3.2)
            return False
        self.touch()
        self.resleep_at = 0.0
        self.stats.happy = min(100, self.stats.happy + 12)
        self.stats.add_bond(3.0, "拥抱")
        self.stats.add_exp(8, "拥抱")
        self.set_act(Act.HAPPY, 3.4, random.choice(HUG_LINES), 3.0)
        self._log("拥抱")
        return True

    def start_pet(self):
        self.touch()
        self.resleep_at = 0.0
        self.set_act(Act.PET, 1.0)
        if self.stats.sick:
            self.complain("sick")
        elif self.stats.happy <= CFG.MOOD20_AT:
            self.next_sad_line()
        else:
            self.show_text(random.choice(LINES["pet"]), 2.2)

    def keep_pet(self, dt: float):
        before = self.stats.level
        self.stats.on_pet(dt)
        self.touch()
        self.resleep_at = 0.0
        self.act_until = time.time() + 0.8
        if self.stats.level > before:
            self.celebrate_levelup(self.stats.level - before)
        elif random.random() < dt * 0.5:
            self.show_text(random.choice(LINES["pet"]), 2.0)

    def feed_item(self, name: str) -> bool:
        """
        ★ 喂食改造：吃掉背包里的指定食物（没有凭空喂食了）。
        由「喂食」面板 / 背包调用。
        """
        self.touch()
        self.resleep_at = 0.0
        was_starving = self.stats.full <= 0.5
        ok, msg = self.stats.feed_item(name)
        if not ok:
            self.set_act(Act.IDLE, 2.0, msg, 2.6)
            return False
        say = "终于有吃的了…谢谢！" if was_starving else random.choice(LINES["eat"])
        self.set_act(Act.EAT, 3.4, say, 2.6)
        self._celebrate_if_levelup()
        return True

    def gift_item(self, name: str) -> bool:
        """
        ★ 新增：赠送礼物 → 提升好感度（结果由调用方刷新面板）。
        """
        self.touch()
        self.resleep_at = 0.0
        ok, msg, value = self.stats.gift_item(name)
        if not ok:
            self.set_act(Act.IDLE, 2.2, msg, 2.8)
            return False
        fav = name in CFG.GIFT_FAVORITES
        line = random.choice(LINES["gift_love"] if fav else LINES["gift"])
        self.set_act(Act.HAPPY, 3.6, f"{line}（好感 +{value}）", 3.4)
        self._celebrate_if_levelup()
        return True

    def joke(self, from_chat: bool = False):
        """讲笑话：搞怪动作（素材4）+ 一句冷笑话"""
        self.touch()
        self.resleep_at = 0.0
        self.stats.happy += 8
        self.stats.bored -= 22
        self.stats.clamp()
        self.set_act(Act.JOKE, 4.0, random.choice(LINES["joke"]), 3.6)
        self.last_joke_t = time.time()
        if from_chat:
            self.chat_jokes += 1
        self._log("讲笑话")

    def should_tell_joke(self) -> bool:
        """
        ★ 聊天时是否「插一个笑话」（用户要求：以正常聊天为主，时不时才讲一个）。
        三个条件同时满足才会讲：
          1. 已经正常聊够 CHAT_JOKE_MIN_MSGS 句（前几句绝对不打断）
          2. 距离上次笑话超过 CHAT_JOKE_COOLDOWN 秒
          3. 掷骰子命中 CHAT_JOKE_CHANCE（默认 7%，约十几句里一次）
        """
        if self.chat_msgs <= CFG.CHAT_JOKE_MIN_MSGS:      # 必须先正常聊满这么多句
            return False
        if time.time() - self.last_joke_t < CFG.CHAT_JOKE_COOLDOWN:
            return False
        return random.random() < CFG.CHAT_JOKE_CHANCE

    def note_chat_message(self):
        """记一笔「聊了一句」，用于笑话节流统计"""
        self.chat_msgs += 1

    def treat(self) -> bool:
        """手动治疗（只有生病时才有效）"""
        self.touch()
        self.resleep_at = 0.0
        was_sick = self.stats.on_treat()
        if was_sick:
            self.set_act(Act.HAPPY, 3.4, random.choice(LINES["treat"]), 3.0)
            self._log("治疗成功")
            self._celebrate_if_levelup()
        else:
            self.set_act(Act.IDLE, 2.4, "我现在很健康呀，不用担心～", 2.6)
        return was_sick

    def say_reply(self, reply: str):
        """把一句回复显示成气泡（TALK 状态 + 第 2 张大笑素材）。"""
        self.set_act(Act.TALK, max(3.0, 0.11 * len(reply) + 2.2), reply,
                     max(3.0, 0.13 * len(reply) + 2.4))
        return reply

    def chat(self, text: str):
        """本地规则式对话（大模型关闭 / 请求失败降级时使用），同样遵守笑话节流。"""
        self.touch()
        self.resleep_at = 0.0
        self.note_chat_message()
        self.stats.on_chat()
        if self.should_tell_joke():
            self.joke(from_chat=True)
            return random.choice(LINES["joke"])
        reply = self.say_reply(ChatBrain.rules_reply(text))
        self._celebrate_if_levelup()
        return reply

    def thinking(self, hint: str = "嗯…让我想想～"):
        """回答前的思考动作（素材1）—— 大模型请求期间显示，避免用户以为卡住。"""
        self.touch()
        self.resleep_at = 0.0
        self.set_act(Act.THINK, 60.0, hint, 60.0)

    def stats_line(self) -> str:
        """给大模型看的当前状态摘要。"""
        s = self.stats
        sick = "，正在生病" if s.sick else ""
        return (f"心情{s.happy:.0f}/100，饱食{s.full:.0f}/100，"
                f"精力{s.energy:.0f}/100，无聊{s.bored:.0f}/100{sick}")

    def hover(self):
        if self.act in AMBIENT_ACTS:
            self.set_act(Act.LOOK, 2.5)
            if random.random() < 0.10:
                self.show_text(random.choice(LINES["hover"]), 2.4)

    def toggle_sleep(self):
        self.touch()
        if self.act == Act.SLEEP:
            self.wake_up()
        else:
            self.stats.sleeping = True
            self.set_act(Act.SLEEP, 999.0, random.choice(LINES["sleep"]), 2.6)

    def wake_up(self):
        self.stats.sleeping = False
        self.set_act(Act.IDLE, 4.0, random.choice(LINES["wake"]), 2.6)

    def start_drag(self):
        self.touch()
        self.act = Act.DRAG
        self.act_until = time.time() + 999
        self.show_text(random.choice(LINES["drag"]), 1.6)

    def end_drag(self):
        self.touch()
        self.set_act(Act.IDLE, 3.0, random.choice(LINES["drop"]), 2.0)


# ==============================================================================
# 8. ChatDialog —— 聊天输入框（自绘 Toplevel，保持置顶）
# ==============================================================================
class ChatDialog(tk.Toplevel):
    def __init__(self, master, on_submit, font_spec):
        super().__init__(master)
        self.on_submit = on_submit
        self.title("和桌宠聊天")
        self.configure(bg=CFG.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.geometry("320x96")
        tk.Label(self, text="对我说点什么吧～", bg=CFG.UI_BG, fg=CFG.UI_TEXT_DIM,
                 font=font_spec).pack(anchor="w", padx=12, pady=(10, 2))
        row = tk.Frame(self, bg=CFG.UI_BG)
        row.pack(fill="x", padx=12, pady=(0, 10))
        self.entry = tk.Entry(row, font=font_spec, relief="solid", bd=1)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        # 回车 / 小键盘回车 都能发送；同时绑定在 Toplevel 上，避免焦点在不经意间跑掉
        for seq in ("<Return>", "<KP_Enter>"):
            self.entry.bind(seq, lambda e: self._send())
            self.bind(seq, lambda e: self._send())
        tk.Button(row, text="发送", font=font_spec, command=self._send,
                  relief="flat", bg="#ffe06a", activebackground="#ffd23f",
                  padx=14).pack(side="left", padx=(8, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self._place_near_master()
        self.after(60, self._focus)

    def _place_near_master(self):
        try:
            mx, my = self.master.winfo_rootx(), self.master.winfo_rooty()
            x = mx + (CFG.WIN_W - 320) // 2
            y = max(0, my - 110)
            self.geometry(f"320x96+{x}+{y}")
        except Exception:
            pass

    def _focus(self):
        try:
            self.entry.focus_force()
        except Exception:
            pass

    def _send(self):
        text = self.entry.get().strip()
        self.destroy()
        if text:
            self.on_submit(text)


# ==============================================================================
# 8.5 养成系统 UI —— 背包 / 商店 / 成就 / 每日任务 / 确认弹窗
# ==============================================================================
# 【说明】物品与成就图片素材由用户后续提供：把素材注册进 ASSETS（名字用 ITEMS[...]["icon"]）
#   即可自动显示图标；没提供时优雅降级成「文字标签」，功能完全不受影响。
# ==============================================================================
class PanelBase(tk.Toplevel):
    """养成面板基类：统一窗口样式 / 置顶 / Esc 关闭 / 刷新（模块5 统一视觉规范）。
    SCROLLABLE=True 的面板，内容超出高度时可用滚轮 / 滚动条 / ↑↓ 翻动。"""

    SCROLLABLE = False

    def __init__(self, master, pet, title: str, size=(420, 460)):
        super().__init__(master)
        self.pet = pet
        self.title(title)
        self.configure(bg=CFG.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.family = pet.font_spec[0]
        self.font = (self.family, 10)
        self.font_b = (self.family, 12, "bold")
        self.font_s = (self.family, 9)
        self.geometry(f"{size[0]}x{size[1]}")
        # 标题区：主题色竖条 + 粗体标题
        head = tk.Frame(self, bg=CFG.UI_BG)
        head.pack(fill="x", padx=14, pady=(12, 6))
        bar = tk.Frame(head, bg=CFG.UI_MAIN, width=4, height=18)
        bar.pack(side="left", padx=(0, 8))
        bar.pack_propagate(False)
        tk.Label(head, text=title, font=self.font_b, bg=CFG.UI_BG,
                 fg=CFG.UI_TEXT).pack(side="left")
        self.body = tk.Frame(self, bg=CFG.UI_BG)
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        # ★ 滚动支持：把 body 换成「Canvas + 内层 Frame」，之后 pack 进 self.body 的内容都能滚
        self.scroll_canvas = None
        self.scroll_bar = None
        self.scroll_inner = None
        if self.SCROLLABLE:
            self._enable_scroll()
        self.footer = tk.Label(self, text="", font=self.font_s, fg=CFG.UI_TEXT_DIM,
                               bg=CFG.UI_BG, justify="left", anchor="w",
                               wraplength=size[0] - 28)
        self.footer.pack(fill="x", padx=14, pady=(0, 4))
        self.make_button(self, "关闭", self.destroy).pack(anchor="e", padx=14, pady=(0, 12))
        self.bind("<Escape>", lambda e: self.destroy())
        self._center()
        self.refresh()

    # ---------------- 滚动（滚轮 / 拖动条 / 方向键） ----------------
    def _enable_scroll(self):
        host = self.body
        self.scroll_canvas = tk.Canvas(host, bg=CFG.UI_BG, highlightthickness=0,
                                       bd=0, takefocus=0)
        self.scroll_bar = tk.Scrollbar(host, orient="vertical",
                                       width=CFG.PANEL_SCROLLBAR_W,
                                       command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self._on_scroll_set)
        self.scroll_canvas.pack(side="left", fill="both", expand=True)
        self.scroll_inner = tk.Frame(self.scroll_canvas, bg=CFG.UI_BG)
        self._scroll_win = self.scroll_canvas.create_window(
            (0, 0), window=self.scroll_inner, anchor="nw")
        self.scroll_inner.bind("<Configure>", self._sync_scrollregion)
        self.scroll_canvas.bind("<Configure>", self._sync_scroll_width)
        # 之后所有内容都 pack 进内层框架
        self.body = self.scroll_inner
        # 滚轮绑在整个面板上：鼠标在面板内任意子控件上滚动都能翻
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda e: self._on_wheel(e, -1))
        self.bind("<Button-5>", lambda e: self._on_wheel(e, 1))
        for key, step in (("<Up>", -CFG.PANEL_KEY_UNITS),
                          ("<Down>", CFG.PANEL_KEY_UNITS),
                          ("<Prior>", -CFG.PANEL_PAGE_UNITS),
                          ("<Next>", CFG.PANEL_PAGE_UNITS)):
            self.bind(key, lambda e, s=step: self._scroll_by(s))

    def _sync_scrollregion(self, _e=None):
        if self.scroll_canvas is not None:
            try:
                self.scroll_canvas.configure(
                    scrollregion=self.scroll_canvas.bbox("all"))
            except Exception:
                pass

    def _sync_scroll_width(self, event):
        """内层框架宽度跟随可视区，避免横向滚不到"""
        try:
            self.scroll_canvas.itemconfigure(self._scroll_win, width=event.width)
        except Exception:
            pass

    def _on_scroll_set(self, lo, hi):
        """内容装得下就隐藏滚动条，装不下才显示"""
        try:
            visible = not (float(lo) <= 0.0 and float(hi) >= 1.0)
            if visible and not self.scroll_bar.winfo_ismapped():
                self.scroll_bar.pack(side="right", fill="y")
            elif not visible and self.scroll_bar.winfo_ismapped():
                self.scroll_bar.pack_forget()
            self.scroll_bar.set(lo, hi)
        except Exception:
            pass

    def _scrollable(self) -> bool:
        if self.scroll_canvas is None:
            return False
        lo, hi = self.scroll_canvas.yview()
        return (hi - lo) < 0.999

    def _on_wheel(self, event, direction=None):
        if not self._scrollable():
            return "break"
        if direction is None:
            direction = -1 if getattr(event, "delta", 0) > 0 else 1
        self._scroll_by(direction * CFG.PANEL_WHEEL_UNITS)
        return "break"

    def _scroll_by(self, units: int):
        if not self._scrollable():
            return "break"
        self.scroll_canvas.yview_scroll(int(units), "units")
        return "break"

    def scroll_to_top(self):
        if self.scroll_canvas is not None:
            try:
                self.scroll_canvas.yview_moveto(0.0)
            except Exception:
                pass

    def scroll_hint(self):
        """内容超出时在 footer 提示可以滚动"""
        if self.scroll_canvas is None:
            return ""
        try:
            self.update_idletasks()
            self._sync_scrollregion()
            lo, hi = self.scroll_canvas.yview()
            return "" if (hi - lo) >= 0.999 else "（内容较多，可用滚轮 / ↑↓ 上下翻看）"
        except Exception:
            return ""


    # ---------------- 统一控件工厂（模块5） ----------------
    def make_button(self, parent, text, command, primary=False, width=None):
        """统一按钮：浅灰底 / 悬停变深 / 扁平；primary=True 用主题紫"""
        bg = CFG.UI_MAIN if primary else CFG.UI_BTN
        fg = "#ffffff" if primary else CFG.UI_TEXT
        hover = "#a274f7" if primary else CFG.UI_BTN_HOVER
        btn = tk.Button(parent, text=text, command=command, font=self.font_s,
                        bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                        relief="flat", bd=0, padx=16, pady=6, cursor="hand2",
                        highlightthickness=0)
        if width:
            btn.config(width=width)
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def make_card(self, parent, pady: int = 2):
        """统一卡片：白底 + 1px 浅灰描边，悬停描边变主题紫
        （tkinter 原生控件没有圆角，用描边 + 内边距近似；真圆角用在 Canvas 绘制处）"""
        card = tk.Frame(parent, bg=CFG.UI_CARD, highlightbackground=CFG.UI_LINE,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", pady=pady)
        card.bind("<Enter>", lambda e: card.config(highlightbackground=CFG.UI_LINE_HOVER))
        card.bind("<Leave>", lambda e: card.config(highlightbackground=CFG.UI_LINE))
        return card

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def refresh(self):
        raise NotImplementedError

    def say(self, text: str):
        self.footer.config(text=text)
        if text:
            self.pet.brain.show_text(text, 2.6)

    def icon_for(self, name: str):
        """有图标素材就返回 PhotoImage，没有就返回 None（优雅降级为纯文字）"""
        if not name:
            return None
        frames = self.pet.assets.get(name)
        if not frames:
            return None
        try:
            from PIL import ImageTk
            cache = getattr(self.pet, "_panel_icons", None)
            if cache is None:
                cache = {}
                self.pet._panel_icons = cache
            if name not in cache:
                img = frames[0].copy()
                img.thumbnail((40, 40))
                cache[name] = ImageTk.PhotoImage(SafeImageOps.keyed_rgb(img, (255, 0, 254)))
            return cache[name]
        except Exception:
            return None


class InventoryPanel(PanelBase):
    """背包：列出物品与数量，点「使用」直接生效（模块2）
    物品多时可滚轮 / 拖动条 / ↑↓ 翻看。"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "背包", (480, 380))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text=f"金币 {s.coins}　等级 Lv.{s.level}　"
                                 f"亲密度 {s.bond:.0f}（{s.bond_tier()}）",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))
        if not s.inventory:
            tk.Label(self.body, text="背包空空的～去「商店」买点东西吧",
                     font=self.font, bg=CFG.UI_BG).pack(anchor="w", pady=10)
            return
        self.scroll_to_top()
        for name, count in sorted(s.inventory.items()):
            spec = ITEMS.get(name, {})
            row = self.make_card(self.body)          # ★ 卡片化
            icon = self.icon_for(spec.get("icon", ""))
            if icon:
                tk.Label(row, image=icon, bg=CFG.UI_CARD).pack(side="left", padx=(6, 2), pady=4)
            tk.Label(row, text=f"{name} ×{count}", font=self.font, bg=CFG.UI_CARD,
                     width=13, anchor="w").pack(side="left", padx=(6, 0))
            tk.Label(row, text=spec.get("desc", ""), font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_CARD, anchor="w", wraplength=210, justify="left").pack(
                side="left", fill="x", expand=True)
            is_food_item = is_food(name)
            self.make_button(row, "喂" if is_food_item else "使用",
                             lambda n=name: self.use(n)).pack(side="right", padx=6)
        # 物品多到一屏放不下时，提示可以用滚轮
        hint = self.scroll_hint()
        if hint:
            self.footer.config(text=hint)

    def use(self, name: str):
        """背包里点按钮：食物走「喂食」路径（计数/好感/经验齐全），其他走「使用」"""
        if is_food(name):
            ok = self.pet.brain.feed_item(name)
            msg = "" if ok else "吃不下或者没有了～"
        else:
            ok, msg = self.pet.stats.use_item(name)
        self.say(msg)
        if ok:
            self.pet.brain.set_act(Act.EAT if ITEMS.get(name, {}).get("cat") == "食物"
                                   else Act.HAPPY, 3.0, msg, 3.0)
            self.pet._celebrate_if_levelup()
            self.pet.autosave(force=True)
        self.refresh()


class ShopPanel(PanelBase):
    """商店：用金币购买物品（模块2）"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "商店", (520, 520))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text=f"金币：{s.coins}", font=self.font_b, fg="#b8860b",
                 bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))
        # ★ 第十二阶段：扭蛋机入口
        top = tk.Frame(self.body, bg=CFG.UI_BG)
        top.pack(fill="x", pady=(0, 6))
        self.make_button(top, "🎰 扭蛋机（100 金币/次）", self._gacha,
                         primary=True).pack(side="left")
        cat_now = None
        for name, spec in ITEMS.items():
            if spec.get("cat") != cat_now:
                cat_now = spec.get("cat")
                tk.Label(self.body, text=f"—— {cat_now} ——", font=self.font_s,
                         fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(6, 2))
            row = self.make_card(self.body)          # ★ 卡片化
            tk.Label(row, text=name, font=self.font, bg=CFG.UI_CARD, width=10,
                     anchor="w").pack(side="left", padx=(6, 0))
            tk.Label(row, text=spec.get("desc", ""), font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_CARD, anchor="w", wraplength=230, justify="left").pack(
                side="left", fill="x", expand=True)
            tk.Label(row, text=f"{spec['price']}币", font=self.font_s, fg="#b8860b",
                     bg=CFG.UI_CARD, width=6).pack(side="left")
            btn = tk.Button(row, text="购买", font=self.font_s, relief="flat", bg="#ffd23f",
                            padx=10, command=lambda n=name: self.buy(n))
            if s.coins < spec["price"]:
                btn.config(state="disabled", bg="#e0e0e0")
            btn.pack(side="right", padx=6)

    def _gacha(self):
        try:
            self.destroy()
        except Exception:
            pass
        self.pet.open_gacha()

    def buy(self, name: str):
        s = self.pet.stats
        spec = ITEMS[name]
        if s.coins < spec["price"]:
            self.say("金币不够呀…多陪陪我就能赚钱啦")
            return
        s.add_coins(-spec["price"])
        s.add_item(name, 1)
        self.say(f"买到了「{name}」！已放进背包")
        self.pet.brain.show_text(f"买到了{name}！", 2.4)
        self.pet.autosave(force=True)
        self.refresh()


class AchievementPanel(PanelBase):
    """成就（模块4）：16 条，超出一屏可滚动"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "成就", (500, 455))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text=f"已解锁 {len(s.achievements)}/{len(ACHIEVEMENTS)}",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))
        for ach in ACHIEVEMENTS:
            got = ach["id"] in s.achievements
            bg = "#f4f4f4" if got else "#ececec"
            row = tk.Frame(self.body, bg=bg)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="★" if got else "☆", font=self.font, bg=bg,
                     fg="#e6a700" if got else "#aaa").pack(side="left", padx=(6, 2), pady=4)
            tk.Label(row, text=ach["name"], font=self.font, bg=bg, width=9,
                     anchor="w").pack(side="left")
            tk.Label(row, text=ach["desc"], font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=bg,
                     anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=f"+{ach['coins']}币", font=self.font_s, fg="#b8860b",
                     bg=bg, width=7).pack(side="right", padx=6)


class DailyPanel(PanelBase):
    """每日任务（模块6）"""

    def __init__(self, master, pet):
        super().__init__(master, pet, "每日任务", (480, 330))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text=f"日期：{s.daily_date}　连续登录：{s.streak_days} 天",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))
        if not s.daily_tasks:
            tk.Label(self.body, text="今天还没有任务", font=self.font, bg=CFG.UI_BG).pack(pady=10)
            return
        for task in s.daily_tasks:
            row = tk.Frame(self.body, bg=CFG.UI_CARD)
            row.pack(fill="x", pady=3)
            head = tk.Frame(row, bg=CFG.UI_CARD)
            head.pack(fill="x")
            tk.Label(head, text=("已完成 " if task["done"] else "待完成 ") + task["name"],
                     font=self.font, bg=CFG.UI_CARD, anchor="w").pack(side="left", padx=(6, 0),
                                                                    pady=(4, 0))
            tk.Label(head, text=f"+{task['coins']}币 +{task['exp']}经验", font=self.font_s,
                     fg="#b8860b", bg=CFG.UI_CARD).pack(side="right", padx=6, pady=(4, 0))
            tk.Label(row, text=task["desc"], font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD,
                     anchor="w").pack(fill="x", padx=6)
            ratio = task["progress"] / max(1.0, float(task["target"]))
            filled = int(ratio * 20)
            bar = "█" * filled + "·" * (20 - filled)
            tk.Label(row, text=f"{bar} {task['progress']:.0f}/{task['target']:.0f}",
                     font=(self.family, 8), fg="#3a7d44" if task["done"] else "#555",
                     bg=CFG.UI_CARD).pack(fill="x", padx=6, pady=(0, 4))


class ConfirmDialog(tk.Toplevel):

    def __init__(self, master, title: str, message: str, on_ok, font_spec):
        super().__init__(master)
        self.on_ok = on_ok
        self.title(title)
        self.configure(bg=CFG.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        tk.Label(self, text=title, font=(font_spec[0], 11, "bold"), bg=CFG.UI_BG).pack(
            anchor="w", padx=16, pady=(14, 4))
        tk.Label(self, text=message, font=font_spec, bg=CFG.UI_BG, justify="left",
                 wraplength=330).pack(anchor="w", padx=16, pady=(0, 10))
        row = tk.Frame(self, bg=CFG.UI_BG)
        row.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(row, text="确认", font=font_spec, relief="flat", bg="#ff8080",
                  padx=18, pady=3, command=self._ok).pack(side="right")
        tk.Button(row, text="取消", font=font_spec, relief="flat",
                  padx=18, pady=3, command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")

    def _ok(self):
        self.destroy()
        self.on_ok()


# ==============================================================================
# 8.6 外出探险 UI —— 地点选择 / 结算 / 任务日志
# ==============================================================================
class AdventurePanel(PanelBase):
    """
    模块1：探险地点选择。
    每个地点一张卡片：名字 / 时长 / 精力消耗 / 预计收益 / 解锁状态。
    底部有「使用道具」下拉框（模块6），选中即消耗一个道具并附加 buff。
    """

    def __init__(self, master, pet):
        self.buff_var = None
        super().__init__(master, pet, "外出探险", (560, 560))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text=f"Lv.{s.level}　精力 {s.energy:.0f}　金币 {s.coins}　"
                                 f"累计探险 {s.adventure_total_count} 次",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(0, 4))
        if s.adventure:
            left = s.adventure_remaining()
            tk.Label(self.body, text=f"正在「{ADVENTURE_SPOTS[s.adventure['spot']]['name']}」"
                                     f"探险中，还有 {left:.0f} 秒回来～",
                     font=self.font_b, fg="#b8860b", bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))
            tk.Button(self.body, text="提前回家（收益减半）", font=self.font, relief="flat",
                      bg="#ffb3b3", padx=12, pady=4,
                      command=self.pet.do_recall).pack(anchor="w", pady=(0, 6))
            return

        # ---- 地点卡片 ----
        for key, spot in ADVENTURE_SPOTS.items():
            unlocked = s.level >= spot["unlock_level"]
            bg = "#f4f4f4" if unlocked else "#e9e9e9"
            card = tk.Frame(self.body, bg=bg)
            card.pack(fill="x", pady=3)
            head = tk.Frame(card, bg=bg)
            head.pack(fill="x", padx=8, pady=(5, 0))
            tk.Label(head, text=f"{spot['emoji']} {spot['name']}", font=self.font_b,
                     bg=bg, fg=CFG.UI_TEXT if unlocked else "#999").pack(side="left")
            lo, hi = spot["coins"]
            tk.Label(head, text=f"{spot['duration']}秒　精力-{spot['energy_cost']}　"
                                f"{lo}~{hi}金币", font=self.font_s, fg="#777" if unlocked else "#aaa",
                     bg=bg).pack(side="left", padx=10)
            if unlocked:
                enough = s.energy >= spot["energy_cost"]
                tk.Button(head, text="出发", font=self.font_s, relief="flat",
                          bg="#ffe06a" if enough else "#e0e0e0", padx=14,
                          state="normal" if enough else "disabled",
                          command=lambda k=key: self.depart(k)).pack(side="right")
            else:
                tk.Label(head, text=f"达到 Lv.{spot['unlock_level']} 解锁", font=self.font_s,
                         fg="#b06", bg=bg).pack(side="right")
            tk.Label(card, text=spot["desc"], font=self.font_s,
                     fg=CFG.UI_TEXT_DIM if unlocked else "#aaa",
                     bg=bg, anchor="w").pack(fill="x", padx=8)
            # ★ 挂机档位 + 熟练度
            tiers = tk.Frame(card, bg=bg)
            tiers.pack(fill="x", padx=8, pady=(2, 6))
            if unlocked:
                for tname, tsec, tratio in CFG.ADVENTURE_DURATIONS:
                    self.make_button(
                        tiers, f"{tname} {self._dur_label(tsec)}",
                        lambda k=key, d=tsec, r=tratio: self.depart(k, d, r)
                    ).pack(side="left", padx=(0, 4))
            prof = s.adv_exp(key)
            ratio = prof / CFG.ADVENTURE_EXP_MAX
            bar = "█" * int(ratio * 12) + "·" * (12 - int(ratio * 12))
            tk.Label(tiers, text=f"熟练 {bar} {prof}/100",
                     font=(self.family, 8), fg="#3a7d44" if prof >= 100 else "#888",
                     bg=bg).pack(side="right")

        # ---- 模块6：使用道具 ----
        tk.Label(self.body, text="—— 出门前用个道具（可选）——", font=self.font_s,
                 fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(8, 2))
        owned = [n for n, c in s.inventory.items() if c > 0 and ITEMS.get(n, {}).get("buff")]
        row = tk.Frame(self.body, bg=CFG.UI_BG)
        row.pack(fill="x")
        self.buff_var = tk.StringVar(value="不带道具")
        choices = ["不带道具"] + [f"{n}（{ITEMS[n]['desc']}）" for n in owned]
        from tkinter import ttk
        box = ttk.Combobox(row, textvariable=self.buff_var, values=choices,
                           state="readonly", width=42, font=self.font_s)
        box.pack(side="left")
        tk.Button(row, text="立即出发(楼下小公园)", font=self.font_s, relief="flat",
                  bg="#c8e6a0", padx=10,
                  command=lambda: self.depart("park")).pack(side="right")
        if not owned:
            tk.Label(self.body, text="背包里还没有探险道具，去商店买点吧（便当/手电筒/指南针/雨伞/大背包）",
                     font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG, wraplength=500,
                     justify="left").pack(anchor="w", pady=(4, 0))

    @staticmethod
    def _dur_label(sec: float) -> str:
        if sec >= 3600:
            return f"{sec / 3600:.0f}h"
        if sec >= 60:
            return f"{sec / 60:.0f}min"
        return f"{int(sec)}s"

    def _selected_buff(self) -> str:
        """把下拉框的选择翻译成 buff key（同时在调用方扣除道具）"""
        val = (self.buff_var.get() if self.buff_var else "") or ""
        for name, spec in ITEMS.items():
            if spec.get("buff") and val.startswith(name):
                return name
        return ""

    def depart(self, key: str, duration: float = None, energy_ratio: float = 1.0):
        buff_item = self._selected_buff()
        buffs = []
        if buff_item:
            if self.pet.stats.inventory.get(buff_item, 0) <= 0:
                self.say(f"背包里没有「{buff_item}」啦")
                self.refresh()
                return
            self.pet.stats.inventory[buff_item] -= 1
            if self.pet.stats.inventory[buff_item] <= 0:
                self.pet.stats.inventory.pop(buff_item, None)
            buffs = [ITEMS[buff_item]["buff"]]
        ok, msg = self.pet.stats.adventure_can_start(key)
        if not ok:
            if buff_item:                        # 出发失败就退还道具
                self.pet.stats.add_item(buff_item, 1)
            self.say(msg)
            return
        self.destroy()
        self.pet.start_adventure(key, buffs, duration=duration,
                                 energy_ratio=energy_ratio)


class AdventureResultPanel(PanelBase):
    """模块3/4：探险结算窗口（金币 / 物品 / 经验 / 事件 / 任务提示）"""

    def __init__(self, master, pet, result: dict):
        self.result = result
        super().__init__(master, pet, "探险归来", (520, 560))

    def refresh(self):
        self.clear()
        r = self.result
        spot = r.get("spot") or {}
        if not r:
            tk.Label(self.body, text="这次什么都没有带回来…", font=self.font, bg=CFG.UI_BG).pack()
            return
        tk.Label(self.body, text=f"{spot.get('emoji','')} 从「{spot.get('name','')}」回来了！",
                 font=self.font_b, fg=CFG.UI_TEXT, bg=CFG.UI_BG).pack(anchor="w", pady=(0, 6))

        def line(emoji, label, value, color="#333"):
            row = tk.Frame(self.body, bg=CFG.UI_CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{emoji} {label}", font=self.font, bg=CFG.UI_CARD,
                     width=9, anchor="w").pack(side="left", padx=(6, 0), pady=3)
            tk.Label(row, text=value, font=self.font, fg=color, bg=CFG.UI_CARD,
                     anchor="w").pack(side="left")

        line("💰", "金币", f"+{r['coins']}" + (f"（基础 {r['base_coins']}，倍率 {r['mult']}）"
                                              if r["mult"] != 1.0 else ""), "#b8860b")
        item_txt = "、".join(f"{n}×{c}" for n, c in r["items"].items()) or "什么也没捡到…"
        line("🎒", "收获", item_txt)
        line("⭐", "经验", f"+{r['exp']} EXP")
        line("💗", "亲密度", f"+{r['bond']}")
        if r.get("daily_bonus"):
            line("🎉", "额外", f"今天第一次出门，额外 +{CFG.ADVENTURE_DAILY_BONUS} 金币")
        if r.get("levelups"):
            line("🎊", "等级", f"升级啦！现在是 Lv.{self.pet.stats.level}")

        if r.get("event"):
            ev = r["event"]
            box = tk.Frame(self.body, bg="#fff4d6")
            box.pack(fill="x", pady=(8, 2))
            tk.Label(box, text=f"{ev['emoji']} {ev['name']}", font=self.font_b,
                     bg="#fff4d6", anchor="w").pack(fill="x", padx=8, pady=(5, 0))
            tk.Label(box, text=ev["desc"], font=self.font_s, fg="#6b5a20", bg="#fff4d6",
                     anchor="w", wraplength=470, justify="left").pack(fill="x", padx=8, pady=(0, 5))
        for note in r.get("notes") or []:
            tk.Label(self.body, text="· " + note, font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG,
                     anchor="w", wraplength=470, justify="left").pack(fill="x", pady=1)
        for msg in r.get("quest_msgs") or []:
            tk.Label(self.body, text="📜 " + msg, font=self.font_s, fg="#2f6b3a", bg="#eef8ee",
                     anchor="w", wraplength=470, justify="left").pack(fill="x", pady=2)

        row = tk.Frame(self.body, bg=CFG.UI_BG)
        row.pack(fill="x", pady=(10, 0))
        tk.Button(row, text="再去一次", font=self.font, relief="flat", bg="#c8e6a0",
                  padx=16, pady=4, command=self._again).pack(side="right", padx=6)
        tk.Button(row, text="太棒了！", font=self.font, relief="flat", bg="#ffe06a",
                  padx=16, pady=4, command=self.destroy).pack(side="right")

    def _again(self):
        self.destroy()
        self.pet.open_adventure()


class QuestLogPanel(PanelBase):
    """模块5：任务日志（显示进行中的任务线与图鉴）"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "任务日志", (500, 480))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        tk.Label(self.body, text="—— 探险任务线 ——", font=self.font_s, fg=CFG.UI_TEXT_DIM,
                 bg=CFG.UI_BG).pack(anchor="w")
        any_quest = False
        for qid, q in QUEST_LINES.items():
            st = s.adventure_quests.get(qid)
            if not st or not st.get("triggered"):
                continue
            any_quest = True
            bg = "#eef8ee" if st.get("done") else "#f4f4f4"
            card = tk.Frame(self.body, bg=bg)
            card.pack(fill="x", pady=2)
            head = tk.Frame(card, bg=bg)
            head.pack(fill="x", padx=6, pady=(4, 0))
            tk.Label(head, text=f"{q['emoji']} {q['name']}", font=self.font_b,
                     bg=bg).pack(side="left")
            tk.Label(head, text="已完成" if st.get("done") else "进行中",
                     font=self.font_s, fg="#2f6b3a" if st.get("done") else "#b8860b",
                     bg=bg).pack(side="right")
            tk.Label(card, text=q["desc"], font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=bg,
                     anchor="w", wraplength=450, justify="left").pack(fill="x", padx=6)
            p, t = st.get("progress", 0), q["target"]
            filled = int(min(1.0, p / max(1, t)) * 18)
            tk.Label(card, text="█" * filled + "·" * (18 - filled) + f" {p}/{t}",
                     font=(self.family, 9), fg="#3a7d44", bg=bg).pack(anchor="w", padx=6, pady=(0, 4))
        if not any_quest:
            tk.Label(self.body, text="还没有接到探险任务～出门走走说不定能捡到什么",
                     font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=6)

        tk.Label(self.body, text=f"—— 探险图鉴（共 {len(s.adventure_collections)} 种）——",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w", pady=(10, 2))
        if not s.adventure_collections:
            tk.Label(self.body, text="图鉴还是空的", font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_BG).pack(anchor="w")
        else:
            grid = tk.Frame(self.body, bg=CFG.UI_BG)
            grid.pack(fill="x")
            for i, (name, cnt) in enumerate(sorted(s.adventure_collections.items())):
                info = material_or_item(name)
                tk.Label(grid, text=f"{info['emoji']} {name}×{cnt}", font=self.font_s,
                         fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG, width=16, anchor="w").grid(
                    row=i // 3, column=i % 3, sticky="w", pady=1)


# ==============================================================================
# 8.7 UI 美化引擎 —— 粒子系统 / 装饰绘制工具
# ==============================================================================
# 【硬性约束回顾】
#   1. 宠物窗口是色键透明的：所有元素必须画在 Canvas 上，且颜色不能接近 KEY_COLOR。
#   2. 禁止逐像素访问；这里只用 tkinter Canvas 图元（圆/多边形/文字），不碰 PIL 像素。
#   3. 粒子用「对象池 + 上限」控制：每个粒子只在生成时 create、死亡时 delete，
#      动画阶段只改 coords/itemconfigure，绝不在每帧 create 新图元。
# ==============================================================================
def blend(c1: str, c2: str, t: float) -> str:
    """把颜色 c1 按比例 t 混向 c2（用来做「淡化」：和背景色混合模拟半透明）"""
    try:
        a = tuple(int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        b = tuple(int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        t = max(0.0, min(1.0, t))
        return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))
    except Exception:
        return c1


def lerp_color(c1: str, c2: str, t: float) -> str:
    return blend(c1, c2, t)


def dpi_scale(root) -> float:
    """高 DPI 缩放系数（96 DPI = 1.0）。失败时退回 1.0。"""
    try:
        hwnd = root.winfo_id()
        u = ctypes.windll.user32
        try:
            dpi = u.GetDpiForWindow(ctypes.wintypes.HWND(hwnd))
        except Exception:
            dpi = 96
        if not dpi:
            dpi = 96
        return max(1.0, min(2.5, dpi / 96.0))
    except Exception:
        return 1.0


class Particle:
    """一颗粒子：只持有一两个 Canvas 图元，动画期间只改坐标/颜色。"""

    __slots__ = ("kind", "items", "x", "y", "vx", "vy", "life", "max_life",
                 "size", "color", "spin", "angle", "sway", "phase", "alpha_steps")

    def __init__(self, kind, items, x, y, vx, vy, life, size, color, sway=0.0, spin=0.0):
        self.kind = kind
        self.items = items
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = life
        self.max_life = life
        self.size = size
        self.color = color
        self.sway = sway
        self.spin = spin
        self.angle = 0.0
        self.phase = random.uniform(0, math.tau)
        self.alpha_steps = 0


class ParticleSystem:
    """
    粒子系统（模块3）。
    支持：心形 / 星星 / 小气泡 / 彩带 / 乌云雨滴 / 扬尘。
    同屏上限 CFG.PARTICLE_MAX，超了就回收最老的。
    """

    def __init__(self, canvas, font_spec, key_color="#ff00fe"):
        self.canvas = canvas
        self.font = font_spec
        self.key = key_color
        self.parts: list[Particle] = []
        self.counts = {}

    # ---------------- 形状工厂（Canvas 图元，不碰像素）----------------
    def _heart(self, x, y, r, color):
        """用两个圆 + 一个三角形拼一颗心"""
        c = self.canvas
        items = [
            c.create_oval(x - r, y - r * 0.9, x, y + r * 0.1, fill=color, outline=""),
            c.create_oval(x, y - r * 0.9, x + r, y + r * 0.1, fill=color, outline=""),
            c.create_polygon(x - r * 0.95, y - r * 0.15, x + r * 0.95, y - r * 0.15,
                             x, y + r * 1.15, fill=color, outline=""),
        ]
        return items

    def _star(self, x, y, r, color):
        """四角星（两个交叉的细长菱形）"""
        c = self.canvas
        pts1 = [x, y - r, x + r * 0.28, y, x, y + r, x - r * 0.28, y]
        pts2 = [x - r, y, x, y + r * 0.28, x + r, y, x, y - r * 0.28]
        return [c.create_polygon(pts1, fill=color, outline=""),
                c.create_polygon(pts2, fill=color, outline="")]

    def _circle(self, x, y, r, color, outline="", width=0):
        c = self.canvas
        return [c.create_oval(x - r, y - r, x + r, y + r, fill=color,
                              outline=outline, width=width)]

    def _rect(self, x, y, w, h, color):
        c = self.canvas
        return [c.create_rectangle(x - w / 2, y - h / 2, x + w / 2, y + h / 2,
                                   fill=color, outline="")]

    # ---------------- 生成器 ----------------
    def _room(self) -> bool:
        while len(self.parts) >= CFG.PARTICLE_MAX:
            self._kill(self.parts[0], recycle=True)
        return True

    def spawn_hearts(self, x, y, count=3, color=None):
        """模块3-1：点击飘心"""
        if not CFG.PARTICLE_EFFECTS:
            return
        color = color or CFG.HEART_COLOR_HAPPY
        for _ in range(count):
            self._room()
            r = random.uniform(4.5, 7.5)
            px = x + random.uniform(-16, 16)
            py = y + random.uniform(-6, 6)
            items = self._heart(px, py, r, color)
            self.parts.append(Particle(
                "heart", items, px, py,
                random.uniform(-22, 22), random.uniform(-62, -40),
                CFG.HEART_LIFE * random.uniform(0.85, 1.15), r, color,
                sway=random.uniform(14, 26)))

    def spawn_stars(self, x, y, count=1, color=None):
        """模块3-2：抚摸星星"""
        if not CFG.PARTICLE_EFFECTS:
            return
        if sum(1 for p in self.parts if p.kind == "star") >= CFG.STAR_MAX_ON_PET:
            return
        color = color or CFG.STAR_COLOR
        for _ in range(count):
            self._room()
            r = random.uniform(4, 7)
            px = x + random.uniform(-30, 30)
            py = y + random.uniform(-10, 18)
            items = self._star(px, py, r, color)
            self.parts.append(Particle(
                "star", items, px, py,
                random.uniform(-20, 20), random.uniform(-40, -18),
                CFG.STAR_LIFE * random.uniform(0.8, 1.1), r, color,
                sway=random.uniform(12, 24), spin=random.uniform(-90, 90)))

    def spawn_eat_bubbles(self, x, y, count=4):
        """模块3-3：进食小气泡"""
        if not CFG.PARTICLE_EFFECTS:
            return
        for _ in range(count):
            self._room()
            r = random.uniform(2.5, 5)
            px = x + random.uniform(-14, 14)
            py = y + random.uniform(-4, 8)
            items = self._circle(px, py, r, "#ffffff", outline="#e8e8e8", width=1)
            self.parts.append(Particle(
                "bubble", items, px, py, random.uniform(-12, 12), random.uniform(-46, -28),
                CFG.EAT_BUBBLE_LIFE, r, "#ffffff", sway=random.uniform(8, 16)))

    def spawn_confetti(self, x, y, count=14):
        """模块3-4：升级礼花（星星 + 彩带）"""
        if not CFG.PARTICLE_EFFECTS:
            return
        for i in range(count):
            self._room()
            ang = random.uniform(0, math.tau)
            speed = random.uniform(80, 170)
            if i % 3 == 0:
                r = random.uniform(4, 6.5)
                items = self._star(x, y, r, random.choice(CFG.CONFETTI_COLORS))
                kind = "spark"
            else:
                w, h = random.uniform(3, 5), random.uniform(6, 10)
                items = self._rect(x, y, w, h,
                                   random.choice(CFG.CONFETTI_COLORS))
                kind = "confetti"
            self.parts.append(Particle(
                kind, items, x, y,
                math.cos(ang) * speed, math.sin(ang) * speed - 40,
                CFG.CONFETTI_LIFE * random.uniform(0.8, 1.2),
                random.uniform(4, 6), "#ffd700",
                sway=0, spin=random.uniform(-200, 200)))

    def spawn_cloud(self, x, y):
        """模块3-5：生病小乌云（灰圆叠 + 一滴雨）"""
        if not CFG.PARTICLE_EFFECTS:
            return
        c = self.canvas
        self._room()
        items = []
        base = CFG.CLOUD_LIFE
        for dx, dy, r in ((-11, 1, 8), (0, -3, 10), (11, 1, 8), (0, 4, 9)):
            items.append(c.create_oval(x + dx - r, y + dy - r, x + dx + r, y + dy + r,
                                       fill="#b9bec7", outline=""))
        items.append(c.create_oval(x - 2, y + 17, x + 2, y + 23, fill="#8fb8e8", outline=""))
        self.parts.append(Particle("cloud", items, x, y, 0, -4, base, 10, "#b9bec7"))

    def spawn_dust(self, x, y):
        """模块6-1：走路扬尘"""
        if not CFG.PARTICLE_EFFECTS:
            return
        self._room()
        r = random.uniform(2, 3.6)
        items = self._circle(x, y, r, CFG.DUST_COLOR)
        self.parts.append(Particle("dust", items, x, y,
                                   random.uniform(-10, 10), random.uniform(-16, -6),
                                   CFG.DUST_LIFE, r, CFG.DUST_COLOR))

    # ---------------- 驱动 ----------------
    def update(self, dt: float):
        """每帧推进（在主循环里调用，不额外开循环）"""
        if not self.parts:
            return
        dead = []
        for p in self.parts:
            p.life -= dt
            if p.life <= 0:
                dead.append(p)
                continue
            p.phase += dt * 3.0
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.kind in ("heart", "star", "bubble"):
                p.vy += 26 * dt                     # 轻重力，飘得自然
                p.vx *= 0.985
                if p.sway:
                    p.x += math.sin(p.phase) * p.sway * dt
            elif p.kind in ("confetti", "spark"):
                p.vy += 190 * dt                    # 礼花受重力下落
                p.vx *= 0.97
            elif p.kind == "dust":
                p.vy += 40 * dt
                p.vx *= 0.94
            if p.spin:
                p.angle += p.spin * dt
            self._move(p)
        for p in dead:
            self._kill(p)

    def _move(self, p: Particle):
        """只改坐标/颜色，不新建图元"""
        c = self.canvas
        k = p.life / max(0.001, p.max_life)          # 1 → 0
        try:
            if p.kind == "heart":
                r = p.size
                x, y = p.x, p.y
                c.coords(p.items[0], x - r, y - r * 0.9, x, y + r * 0.1)
                c.coords(p.items[1], x, y - r * 0.9, x + r, y + r * 0.1)
                c.coords(p.items[2], x - r * 0.95, y - r * 0.15, x + r * 0.95,
                         y - r * 0.15, x, y + r * 1.15)
                if k < 0.45:                          # 后 45% 时间模拟变淡
                    col = blend(p.color, "#ffffff", (0.45 - k) / 0.45 * 0.75)
                    for it in p.items:
                        c.itemconfigure(it, fill=col)
            elif p.kind == "star":
                r = p.size * (0.7 + 0.3 * k)
                x, y = p.x, p.y
                c.coords(p.items[0], x, y - r, x + r * 0.28, y, x, y + r, x - r * 0.28, y)
                c.coords(p.items[1], x - r, y, x, y + r * 0.28, x + r, y, x, y - r * 0.28)
                if k < 0.5:
                    col = blend(p.color, "#fff8e1", (0.5 - k) / 0.5)
                    for it in p.items:
                        c.itemconfigure(it, fill=col)
            elif p.kind == "bubble":
                grow = 1.0 + (1.0 - k) * 0.9          # 逐渐变大再消失
                r = p.size * grow
                c.coords(p.items[0], p.x - r, p.y - r, p.x + r, p.y + r)
                if k < 0.3:
                    c.itemconfigure(p.items[0], outline="#f2f2f2")
            elif p.kind == "confetti":
                w, h = p.size, p.size * 1.7
                x, y = p.x, p.y
                c.coords(p.items[0], x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                if k < 0.4:
                    c.itemconfigure(p.items[0], fill=blend(p.color, "#ffffff",
                                                           (0.4 - k) / 0.4 * 0.8))
            elif p.kind == "spark":
                r = p.size * k
                c.coords(p.items[0], p.x, p.y - r, p.x + r * 0.28, p.y,
                         p.x, p.y + r, p.x - r * 0.28, p.y)
                c.coords(p.items[1], p.x - r, p.y, p.x, p.y + r * 0.28,
                         p.x + r, p.y, p.x, p.y - r * 0.28)
            elif p.kind == "cloud":
                dx = p.x - (p.items[0].__class__ and 0)
                for i, (ox, oy) in enumerate(((-11, 1), (0, -3), (11, 1), (0, 4))):
                    rr = (8, 10, 8, 9)[i]
                    c.coords(p.items[i], p.x + ox - rr, p.y + oy - rr,
                             p.x + ox + rr, p.y + oy + rr)
                c.coords(p.items[4], p.x - 2, p.y + 17, p.x + 2, p.y + 23)
                if k < 0.3:
                    for it in p.items:
                        c.itemconfigure(it, fill=blend("#b9bec7", "#ffffff",
                                                       (0.3 - k) / 0.3 * 0.7))
            elif p.kind == "dust":
                r = p.size * (0.6 + 0.6 * k)
                c.coords(p.items[0], p.x - r, p.y - r, p.x + r, p.y + r)
                if k < 0.5:
                    c.itemconfigure(p.items[0],
                                    fill=blend(CFG.DUST_COLOR, "#ffffff", (0.5 - k) / 0.5))
        except Exception:
            pass

    def _kill(self, p: Particle, recycle: bool = False):
        for it in p.items:
            try:
                self.canvas.delete(it)
            except Exception:
                pass
        try:
            self.parts.remove(p)
        except ValueError:
            pass
        if recycle:
            p.items = []

    def clear(self):
        for p in list(self.parts):
            self._kill(p)


class Decor:
    """
    模块1：宠物周边常驻装饰（阴影 / 等级徽章 / 状态图标条 / 经验条）。
    全部画在 Canvas 上，位置由每帧传入的宠物脚底坐标决定。
    """

    def __init__(self, canvas, font_spec, cfg):
        self.canvas = canvas
        self.cfg = cfg
        self.font = font_spec
        self.small = (font_spec[0], 7)
        self.tiny = (font_spec[0], 6)
        self.items = {}
        self.shadow_items = []
        self.icon_items = []
        self._shadow_phase = 0
        self._badge_bounce_until = 0.0
        self._exp_flash_until = 0.0
        self._last_level = 0
        self._last_exp = -1
        self.alpha = 1.0        # 装饰默认可见（美化版：不再隐藏）
        self._faded = False
        self._build()

    # ---------------- 构建（只建一次，之后只改坐标/颜色）----------------
    def _build(self):
        c = self.canvas
        cfg = self.cfg
        if not cfg.DECORATIONS:
            return
        # 阴影：三层椭圆模拟羽化
        for i, col in enumerate(cfg.SHADOW_SHADES):
            self.shadow_items.append(c.create_oval(0, 0, 1, 1, fill=col, outline=""))
        # 经验条
        bx = cfg.PET_CX - cfg.EXPBAR_W / 2
        by = cfg.WIN_H - cfg.BASE_LINE_GAP + 2
        self.items["exp_bg"] = c.create_rectangle(
            bx, by, bx + cfg.EXPBAR_W, by + cfg.EXPBAR_H,
            fill=cfg.EXPBAR_BG, outline="")
        # 渐变填充：分 8 段
        self.exp_segs = []
        segw = cfg.EXPBAR_W / 8.0
        for i in range(8):
            col = lerp_color(cfg.EXPBAR_COLORS[0], cfg.EXPBAR_COLORS[1], i / 7.0)
            self.exp_segs.append(c.create_rectangle(
                bx + i * segw, by, bx + i * segw, by + cfg.EXPBAR_H,
                fill=col, outline=""))
        # 等级徽章
        self.items["badge"] = c.create_oval(0, 0, 1, 1, fill="#cd7f32",
                                            outline="#ffffff", width=2)
        self.items["badge_text"] = c.create_text(0, 0, text="Lv.1", fill="#ffffff",
                                                 font=self.small)
        # ★ 美化：徽章左上角一点高光，有金属质感
        if cfg.BADGE_GLOSS:
            self.items["badge_gloss"] = c.create_oval(0, 0, 1, 1, fill="#ffffff",
                                                      outline="")
        # 状态图标条（4 个圆 + 符号）
        self.icon_items = []
        for i in range(4):
            self.icon_items.append(dict(
                circle=c.create_oval(0, 0, 1, 1, fill="#dddddd", outline="#ffffff", width=1),
                glyph=c.create_text(0, 0, text="", fill="#ffffff", font=self.tiny)))

    # ---------------- 每帧更新 ----------------
    def set_alpha(self, alpha: float):
        """0~1 可见度（用 stipple 阶梯模拟淡入淡出；0 时整组隐藏）"""
        alpha = max(0.0, min(1.0, alpha))
        self.alpha = alpha
        st = ""
        if alpha <= 0.02:
            state = "hidden"
        else:
            state = "normal"
            if alpha < 0.98:
                lv = int(alpha * 4)
                st = ("gray25", "gray50", "gray75", "")[min(3, lv)]
        for it in self.shadow_items:
            self.canvas.itemconfigure(it, state="normal")     # 阴影始终显示
        for k, it in self.items.items():
            self.canvas.itemconfigure(it, state=state)
            if st:
                try:
                    self.canvas.itemconfigure(it, stipple=st)
                except Exception:
                    pass
        for rec in self.icon_items:
            for it in (rec["circle"], rec["glyph"]):
                self.canvas.itemconfigure(it, state=state)
                if st:
                    try:
                        self.canvas.itemconfigure(it, stipple=st)
                    except Exception:
                        pass
        self._faded = state == "hidden"

    def update(self, now: float, x_center: float, feet_y: float, bob: float,
               stats, hovering: bool, breath: float = 1.0):
        if not self.cfg.DECORATIONS or not self.items:
            return
        c = self.canvas
        cfg = self.cfg
        scale = getattr(self, "dpi", 1.0)
        # ---- 阴影：随 bob 缩放 + 变浅；★模块4 再叠加「呼吸」幅度 ----
        if cfg.SHADOW_ON:
            k = max(0.0, min(1.0, 1.0 - (bob + 8) / 26.0))     # bob 越高 → 阴影越小越浅
            # 吸气（breath>1）→ 阴影变宽变浅；呼气（breath<1）→ 变窄变深
            bs = 1.0 + (breath - 1.0) * (cfg.IDLE_SHADOW_BREATH / 0.03)
            bs = max(0.9, min(1.12, bs))
            ps_sh = 1.0
            try:
                ps_sh = cfg.pet_scale()
            except Exception:
                pass
            w = cfg.SHADOW_W * (0.72 + 0.28 * k) * bs * ps_sh
            h = cfg.SHADOW_H * (0.55 + 0.45 * k) * (1.0 + (bs - 1.0) * 0.5) * max(0.7, ps_sh)
            for i, col in enumerate(cfg.SHADOW_SHADES):
                grow = 1.0 + i * 0.16
                ww, hh = w * grow, h * grow
                c.coords(self.shadow_items[i], x_center - ww / 2, feet_y - hh / 2,
                         x_center + ww / 2, feet_y + hh / 2)
                # 吸气时更浅（breath 越大往白色混得越多）
                tint = (1.0 - k) * 0.55 + max(0.0, breath - 1.0) * 2.0
                c.itemconfigure(self.shadow_items[i],
                                fill=blend(col, "#ffffff", min(0.85, tint)))
        # ★ 装饰隐藏时只保留阴影，其余（徽章/图标条/经验条）不动，省 CPU
        if getattr(self, "_faded", False):
            return
        # ---- 经验条 ----
        need = max(1, stats.exp_to_next())
        ratio = max(0.0, min(1.0, stats.exp / need))
        bx = cfg.PET_CX - cfg.EXPBAR_W / 2
        by = cfg.WIN_H - cfg.BASE_LINE_GAP + 3
        segw = cfg.EXPBAR_W / 8.0
        c.coords(self.items["exp_bg"], bx, by, bx + cfg.EXPBAR_W, by + cfg.EXPBAR_H)
        for i, seg in enumerate(self.exp_segs):
            lo = i * segw
            fill = max(0.0, min(segw, ratio * cfg.EXPBAR_W - lo))
            if fill <= 0.05:
                c.itemconfigure(seg, state="hidden")
            else:
                c.itemconfigure(seg, state="normal")
                # ★ 美化：首尾两段做一点圆弧收口，整条看起来更像"胶囊"
                dx0 = 0
                dx1 = 0
                if cfg.EXPBAR_CAP:
                    if i == 0:
                        dx0 = cfg.EXPBAR_H * 0.35
                    if lo + fill >= cfg.EXPBAR_W - 0.6:
                        dx1 = cfg.EXPBAR_H * 0.35
                c.coords(seg, bx + lo + dx0, by, bx + lo + fill - dx1, by + cfg.EXPBAR_H)
            if now < self._exp_flash_until:                  # 升级闪白光
                c.itemconfigure(seg, fill="#ffffff")
            else:
                c.itemconfigure(seg, fill=lerp_color(cfg.EXPBAR_COLORS[0],
                                                    cfg.EXPBAR_COLORS[1], i / 7.0))
        # ---- 等级徽章 ----
        tier = cfg.BADGE_LEVELS[-1]
        for need_lv, bg, fg in cfg.BADGE_LEVELS:
            if stats.level >= need_lv:
                tier = (need_lv, bg, fg)
                break
        r = cfg.BADGE_R
        if now < self._badge_bounce_until:                   # 升级弹跳
            t = (self._badge_bounce_until - now) / 0.6
            r *= 1.0 + cfg.BADGE_BOUNCE * abs(math.sin(t * math.pi * 2)) * t
        ps = 1.0
        try:
            ps = cfg.pet_scale()
        except Exception:
            pass
        bx2 = x_center - 60 * ps
        by2 = feet_y - 152 * ps + bob * 0.4
        c.coords(self.items["badge"], bx2 - r, by2 - r, bx2 + r, by2 + r)
        if "badge_gloss" in self.items:              # 高光跟着徽章走
            gr = r * 0.62
            c.coords(self.items["badge_gloss"], bx2 - gr * 0.85, by2 - gr * 0.95,
                     bx2 + gr * 0.15, by2 - gr * 0.15)
            c.itemconfigure(self.items["badge_gloss"],
                            fill=blend(tier[1], "#ffffff", 0.55))
        c.itemconfigure(self.items["badge"], fill=tier[1])
        c.coords(self.items["badge_text"], bx2, by2)
        c.itemconfigure(self.items["badge_text"], text=f"Lv.{stats.level}", fill=tier[2])
        # ---- 状态图标条（气泡下方一行）----
        icons = [("♥", stats.happy, "#ff8fab", 30),
                 ("■", stats.full, "#ffb74d", 30),
                 ("⚡", stats.energy, "#64b5f6", 30)]
        if stats.sick:
            icons.append(("✚", 0, "#ef5350", 99))
        n = len(icons)
        gap = cfg.ICON_GAP * 2 + cfg.ICON_R * 2
        total = n * gap
        start = x_center - total / 2 + gap / 2
        y_ic = cfg.BUBBLE_ZONE + 15     # 气泡下方、宠物头顶上方的空隙
        bright = hovering or now < self._badge_bounce_until
        for i, (glyph, val, col, thresh) in enumerate(icons):
            if i >= len(self.icon_items):
                break
            rec = self.icon_items[i]
            if not bright:                                   # 淡显：往白色混
                col = blend(col, "#ffffff", cfg.ICON_DIM_ALPHA)
            if glyph != "✚" and val < thresh:
                col = blend(col, "#cfcfcf", 0.75)            # 低值变灰
            xx = start + i * gap
            r = cfg.ICON_R
            c.coords(rec["circle"], xx - r, y_ic - r, xx + r, y_ic + r)
            c.itemconfigure(rec["circle"], fill=col, state="normal")
            c.coords(rec["glyph"], xx, y_ic)
            c.itemconfigure(rec["glyph"], text=glyph, state="normal",
                            fill="#ffffff" if bright else "#f7f7f7")
        for i in range(n, len(self.icon_items)):             # 多余图标隐藏
            c.itemconfigure(self.icon_items[i]["circle"], state="hidden")
            c.itemconfigure(self.icon_items[i]["glyph"], state="hidden")

    def on_levelup(self, now: float):
        self._badge_bounce_until = now + 0.6
        self._exp_flash_until = now + CFG.EXPBAR_FLASH

    def hide_all(self):
        for it in self.shadow_items:
            self.canvas.itemconfigure(it, state="hidden")
        for it in self.items.values():
            self.canvas.itemconfigure(it, state="hidden")
        for rec in self.icon_items:
            self.canvas.itemconfigure(rec["circle"], state="hidden")
            self.canvas.itemconfigure(rec["glyph"], state="hidden")


# ==============================================================================
# 8.8 模块4：自定义右键面板 / 模块5：可视化状态面板
# ==============================================================================
class MenuWindow(tk.Toplevel):
    """
    ★ 右键菜单：独立的弹窗窗口（不是浮在宠物身上的小面板）
      · 有标题栏，可以拖动、可以直接关
      · 三列网格排布，40 项也只占一屏的一半左右
      · 位置永远避开宠物窗口，不会被奶蛙挡住
      · grab_set 独占输入：点菜单绝不会误触到奶蛙
      · 点任意一项 → 关窗并执行；Esc / 关闭按钮也能关
    """

    COLS = 3
    BTN_W = 15
    ROW_H = 30

    def __init__(self, master, pet, items, x=None, y=None):
        super().__init__(master)
        self.pet = pet
        self._done = False
        cfg = CFG
        fam = pet.font_spec[0]
        self.title("奶蛙菜单")
        self.configure(bg=cfg.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)

        # ---- 内容：按分隔线分组，组内三列网格 ----
        groups, cur = [], []
        for it in items:
            if it[0] == "-":
                if cur:
                    groups.append(cur)
                    cur = []
            else:
                cur.append(it)
        if cur:
            groups.append(cur)

        body = tk.Frame(self, bg=cfg.UI_BG)
        body.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        head = tk.Frame(body, bg=cfg.UI_BG)
        head.pack(fill="x")
        tk.Frame(head, bg=cfg.UI_MAIN, width=4, height=16).pack(side="left", padx=(0, 6))
        tk.Label(head, text="想让我做什么？", font=(fam, 10, "bold"), bg=cfg.UI_BG,
                 fg=cfg.UI_TEXT).pack(side="left")

        grid = tk.Frame(body, bg=cfg.UI_BG)
        grid.pack(fill="both", expand=True, pady=(6, 0))
        row_i = 0
        self._btns = []
        for gi, group in enumerate(groups):
            if gi:                                  # 组间加一条细分隔线
                tk.Frame(grid, bg=cfg.UI_LINE, height=1).grid(
                    row=row_i, column=0, columnspan=self.COLS, sticky="ew",
                    pady=(4, 4))
                row_i += 1
            for j, (emoji, label, cb) in enumerate(group):
                r, c = row_i + j // self.COLS, j % self.COLS
                b = tk.Button(grid, text=f"{emoji} {label}", font=(fam, 9),
                              anchor="w", width=self.BTN_W, relief="flat",
                              bg=cfg.UI_CARD, fg=cfg.UI_TEXT, bd=0,
                              activebackground=cfg.UI_HOVER_BG,
                              activeforeground=cfg.UI_HOVER_TEXT,
                              cursor="hand2",
                              command=lambda f=cb: self._run(f))
                b.grid(row=r, column=c, padx=2, pady=1, sticky="ew")
                self._btns.append(b)
            row_i += (len(group) + self.COLS - 1) // self.COLS
        for c in range(self.COLS):
            grid.grid_columnconfigure(c, weight=1)

        foot = tk.Frame(body, bg=cfg.UI_BG)
        foot.pack(fill="x", pady=(8, 0))
        tk.Label(foot, text="点一下就能使唤我～（Esc 关闭）", font=(fam, 8),
                 fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG).pack(side="left")
        tk.Button(foot, text="关闭", font=(fam, 8), relief="flat",
                  bg=cfg.UI_BTN, fg=cfg.UI_TEXT, padx=12, cursor="hand2",
                  command=self.close).pack(side="right")

        self.bind("<Escape>", lambda e: self.close())
        self.update_idletasks()
        self._place(x, y)
        try:
            pet._menu_open = True
        except Exception:
            pass
        self.after(60, self._take_input)

    # ---------------- 定位：永远避开宠物窗口 ----------------
    def _place(self, x, y):
        cfg = CFG
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 360)
        h = max(self.winfo_reqheight(), 200)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        px = getattr(self.pet, "x", 0)
        py = getattr(self.pet, "y", 0)
        pw = getattr(cfg, "WIN_W", 442)
        ph = getattr(cfg, "WIN_H", 355)
        gap = 14
        cands = [(px + pw + gap, py),                  # 右
                 (px - w - gap, py),                   # 左
                 (px + pw + gap, py + ph - h),         # 右（下对齐）
                 (px - w - gap, py + ph - h),          # 左（下对齐）
                 (px + pw // 2 - w // 2, py - h - gap),  # 上
                 (px + pw // 2 - w // 2, py + ph + gap)]  # 下
        pos = None
        for cx_, cy_ in cands:
            if 6 <= cx_ and cx_ + w <= sw - 6 and 6 <= cy_ and cy_ + h <= sh - 48:
                pos = (cx_, cy_)
                break
        if pos is None:                                # 屏幕太小：屏幕中间
            pos = (max(6, (sw - w) // 2), max(6, (sh - h) // 2))
        self.geometry(f"{w}x{h}+{int(pos[0])}+{int(pos[1])}")

    def _take_input(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()                # 独占输入：点菜单不会误触奶蛙
        except Exception:
            pass

    def _run(self, cb):
        self.close()
        try:
            cb()
        except Exception:
            log_event("MENU", traceback.format_exc())

    def close(self):
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.pet._menu_open = False
            if getattr(self.pet, "_bmenu", None) is self:
                self.pet._bmenu = None
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


class BubbleMenu(tk.Toplevel):
    """
    自定义右键菜单：圆角卡片 + emoji 图标 + 悬停高亮 + 淡入动画。
    用 Toplevel（独立窗口，可以放心用 Label/Frame），而不是往透明宠物窗口上堆控件。
    """

    def __init__(self, master, pet, items, x, y):
        super().__init__(master)
        self.pet = pet
        self.items = items                    # [("emoji", "文字", 回调) 或 ("-",) 分隔线]
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.0)    # 淡入起点
        except Exception:
            pass
        cfg = CFG
        pad = cfg.MENU_PAD
        row_h = cfg.MENU_ROW_H
        w = cfg.MENU_W
        h = pad * 2 + sum((row_h if it[0] != "-" else 9) for it in items)
        self.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        fam = pet.font_spec[0]
        self.canvas = tk.Canvas(self, width=w, height=h, bg=cfg.UI_CARD,
                               highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        # ★ 美化：卡片投影（多层叠加模拟羽化）
        if CFG.UI_SHADOW:
            for i in range(CFG.UI_SHADOW_STEPS, 0, -1):
                grow = i * 1.5
                col = blend(CFG.UI_SHADOW_COLOR, "#ffffff", 0.42 + 0.16 * i)
                self.canvas.create_polygon(
                    DesktopPet._round_rect(1 - grow + 1, 1 - grow + CFG.UI_SHADOW_OFFSET,
                                           w - 1 + grow + 1, h - 1 + grow + CFG.UI_SHADOW_OFFSET,
                                           9 + grow),
                    smooth=True, fill=col, outline="")
        # 圆角卡片 + 描边
        self.canvas.create_polygon(
            DesktopPet._round_rect(1, 1, w - 1, h - 1, 9),
            smooth=True, fill=cfg.UI_CARD, outline=cfg.UI_LINE, width=1)
        self.rows = []
        cy = pad
        for it in items:
            if it[0] == "-":
                self.canvas.create_line(8, cy + 4, w - 8, cy + 4, fill=cfg.UI_LINE)
                cy += 9
                continue
            emoji, label, cb = it
            tag = f"row{len(self.rows)}"
            rect = self.canvas.create_rectangle(
                5, cy, w - 5, cy + row_h, fill=cfg.UI_CARD, outline="",
                tags=(tag,))
            ei = self.canvas.create_text(19, cy + row_h / 2, text=emoji,
                                         font=(fam, 10), fill="#666", tags=(tag,))
            ti = self.canvas.create_text(34, cy + row_h / 2, text=label, anchor="w",
                                         font=(fam, 10), fill=cfg.UI_TEXT, tags=(tag,))
            self.rows.append(dict(tag=tag, rect=rect, ei=ei, ti=ti, cb=cb, y=cy))
            cy += row_h
        for r in self.rows:
            for tg in (r["tag"],):
                self.canvas.tag_bind(tg, "<Enter>",
                                     lambda e, rr=r: self._hover(rr, True))
                self.canvas.tag_bind(tg, "<Leave>",
                                     lambda e, rr=r: self._hover(rr, False))
                self.canvas.tag_bind(tg, "<Button-1>",
                                     lambda e, rr=r: self._click(rr))
        self.bind("<Escape>", lambda e: self._safe_destroy())
        # ★ 点面板空白处 = 关闭（grab 之后所有点击都先到本窗口）
        self.bind("<Button-1>", lambda e: self._on_blank_click(e))
        # ★ 独立弹窗：抢焦点 + 独占输入，这样点菜单不会穿透到奶蛙身上
        self.after(cfg.MENU_FADE_MS + 40, self._take_input)
        self._fade(0.0, 0)
        try:
            pet._menu_open = True          # 通知宠物：菜单开着，别响应点击、别抢置顶
        except Exception:
            pass

    def _focus_self(self):
        try:
            self.focus_force()
        except Exception:
            pass

    def _take_input(self):
        """抢焦点 + 独占鼠标输入：菜单内的点击不会落到宠物窗口上"""
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass
        try:
            self.grab_set()               # ★ 关键：独占输入，解决「点菜单误触奶蛙」
        except Exception:
            pass

    def _on_blank_click(self, e):
        """点到菜单空白（不是某一行）就关闭"""
        if not self.rows:
            self._safe_destroy()
            return
        top = self.rows[0]["y"]
        bottom = self.rows[-1]["y"] + CFG.MENU_ROW_H
        if not (top <= e.y <= bottom):
            self._safe_destroy()

    def _fade(self, cur: float, step: int):
        """淡入（用窗口 alpha，100ms 内 4 步）"""
        steps = 4
        nxt = min(1.0, cur + 1.0 / steps)
        try:
            self.attributes("-alpha", nxt)
        except Exception:
            return
        if nxt < 1.0 and step < steps + 2:
            self.after(max(10, CFG.MENU_FADE_MS // steps),
                       lambda: self._fade(nxt, step + 1))

    def _hover(self, row, on: bool):
        cfg = self.cfg if hasattr(self, "cfg") else CFG
        try:
            self.canvas.itemconfigure(row["rect"],
                                      fill=cfg.UI_HOVER_BG if on else cfg.UI_CARD)
            self.canvas.itemconfigure(row["ti"],
                                      fill=cfg.UI_HOVER_TEXT if on else cfg.UI_TEXT)
        except Exception:
            pass

    def _click(self, row):
        self._safe_destroy()
        try:
            row["cb"]()
        except Exception:
            log_event("MENU", traceback.format_exc())

    def _safe_destroy(self):
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.pet._menu_open = False
            self.pet._bmenu = None
        except Exception:
            pass


class ItemPickPanel(PanelBase):
    """
    喂食 / 赠送 共用的物品选择面板。
    左侧物品卡片、右侧操作按钮，卡片化 + 悬停高亮（沿用统一主题）。
    filter_fn 决定列出哪些物品；action_text 是按钮文字。
    """

    def __init__(self, master, pet, title, filter_fn, action_text, action_fn,
                 empty_tip, header_extra=""):
        self.filter_fn = filter_fn
        self.action_text = action_text
        self.action_fn = action_fn
        self.empty_tip = empty_tip
        self.header_extra = header_extra
        super().__init__(master, pet, title, (470, 420))

    def refresh(self):
        self.clear()
        cfg = CFG
        s = self.pet.stats
        head = f"金币 {s.coins}　好感 {s.bond:.0f}（{s.bond_tier()}）"
        if self.header_extra:
            head += f"　{self.header_extra.format(s=s)}"
        tk.Label(self.body, text=head, font=self.font_s, fg=cfg.UI_TEXT_DIM,
                 bg=cfg.UI_BG).pack(anchor="w", pady=(0, 6))
        items = [(n, c) for n, c in sorted(s.inventory.items())
                 if c > 0 and self.filter_fn(n)]
        if not items:
            tk.Label(self.body, text=self.empty_tip, font=self.font_s,
                     fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG, wraplength=430,
                     justify="left").pack(anchor="w", pady=10)
            self.make_button(self.body, "去商店买", self.pet.open_shop,
                             primary=True).pack(anchor="w", pady=6)
            return
        for name, count in items:
            spec = ITEMS.get(name) or MATERIALS.get(name) or {}
            card = self.make_card(self.body)
            row = tk.Frame(card, bg=cfg.UI_CARD)
            row.pack(fill="x", padx=8, pady=6)
            tk.Label(row, text=f"{name} ×{count}", font=self.font, bg=cfg.UI_CARD,
                     width=13, anchor="w").pack(side="left")
            tk.Label(row, text=spec.get("desc", ""), font=self.font_s,
                     fg=cfg.UI_TEXT_DIM, bg=cfg.UI_CARD, anchor="w",
                     wraplength=230, justify="left").pack(side="left", fill="x",
                                                         expand=True)
            if self.action_text == "赠送":
                bonus = gift_bond_value(name)
                if name in CFG.GIFT_FAVORITES:
                    bonus = int(round(bonus * CFG.GIFT_FAVORITE_BONUS))
                tk.Label(row, text=f"好感+{bonus}", font=self.font_s,
                         fg=cfg.UI_ACCENT, bg=cfg.UI_CARD).pack(side="left", padx=6)
            self.make_button(row, self.action_text,
                             lambda n=name: self._do(n)).pack(side="right", padx=4)

    def _do(self, name):
        if self.action_fn(name):
            self.refresh()
        else:
            self.refresh()


class FeedPanel(ItemPickPanel):
    """喂食：只列背包里的「食物」"""

    def __init__(self, master, pet):
        super().__init__(
            master, pet, "喂食（吃背包里的食物）",
            filter_fn=is_food,
            action_text="喂",
            action_fn=lambda n: pet.brain.feed_item(n),
            empty_tip="背包里没有食物啦～去「商店」买点：珍珠奶茶 / 草莓蛋糕 / 营养套餐",
            header_extra="饱食 {s.full:.0f}")


class GiftPanel(ItemPickPanel):
    """赠送：送礼涨好感"""

    def __init__(self, master, pet):
        super().__init__(
            master, pet, "赠送礼物",
            filter_fn=is_giftable,
            action_text="赠送",
            action_fn=lambda n: pet.brain.gift_item(n),
            empty_tip="背包里没有能送的礼物～去「商店」逛逛，或者出门探险捡点回来",
            header_extra="")


class StatusPanel(PanelBase):
    """
    模块5-2：可视化状态面板。
    头像 + 名字 + 等级徽章 + 四条渐变进度条 + 身体状况胶囊标签，全部画在 Canvas 上。
    """

    def __init__(self, master, pet):
        super().__init__(master, pet, "奶蛙的状态", (420, 400))

    def refresh(self):
        self.clear()
        cfg = CFG
        s = self.pet.stats
        fam = self.family
        holder = tk.Frame(self.body, bg=cfg.UI_BG)
        holder.pack(fill="both", expand=True)
        W, H = 392, 320
        cv = tk.Canvas(holder, width=W, height=H, bg=cfg.UI_BG, highlightthickness=0)
        cv.pack()
        # ---- 顶部：头像 + 名字 + Lv 徽章 ----
        avatar = None
        try:
            frames = self.pet.assets.get("idle")
            if frames:
                from PIL import ImageTk
                img = frames[0].copy()
                img.thumbnail((64, 64))
                avatar = ImageTk.PhotoImage(
                    SafeImageOps.keyed_rgb(img, (255, 0, 254)))
                self._avatar = avatar           # 保引用
        except Exception:
            avatar = None
        if avatar:
            cv.create_image(18, 14, image=avatar, anchor="nw")
        else:                                    # 素材缺失 → 画个圆脸占位
            cv.create_oval(18, 14, 82, 78, fill="#ffd94a", outline="#e8bd2e", width=2)
            cv.create_oval(34, 36, 44, 46, fill="#3a3a3a")
            cv.create_oval(58, 36, 68, 46, fill="#3a3a3a")
            cv.create_arc(36, 44, 66, 64, start=200, extent=140, style="arc",
                          outline="#8a6b1f", width=2)
        cv.create_text(96, 26, text="奶蛙", font=(fam, 13, "bold"),
                       fill=cfg.UI_TEXT, anchor="w")
        tier = cfg.BADGE_LEVELS[-1]
        for need, bg, fg in cfg.BADGE_LEVELS:
            if s.level >= need:
                tier = (need, bg, fg)
                break
        cv.create_oval(96, 44, 96 + 26, 44 + 18, fill=tier[1], outline="#ffffff", width=2)
        cv.create_text(96 + 13, 44 + 9, text=f"Lv.{s.level}", font=(fam, 8),
                       fill=tier[2])
        cv.create_text(130, 53, text=f"{s.bond_tier()}　亲密度 {s.bond:.0f}",
                       font=(fam, 9), fill=cfg.UI_TEXT_DIM, anchor="w")
        # ---- 四条属性条 ----
        bars = [(f"心情  {s.happy:4.0f}", s.happy, "#ff8fab"),
                (f"饱食  {s.full:4.0f}", s.full, "#ffb74d"),
                (f"精力  {s.energy:4.0f}", s.energy, "#64b5f6"),
                (f"无聊  {s.bored:4.0f}", s.bored, "#81c784")]
        y = 96
        for label, val, color in bars:
            cv.create_text(18, y, text=label, font=(fam, 9), fill=cfg.UI_TEXT,
                           anchor="w")
            bx0, bx1, bh = 106, 372, 12
            cv.create_rectangle(bx0, y - bh / 2, bx1, y + bh / 2,
                                fill="#eeeeee", outline="")
            fillw = int((bx1 - bx0) * max(0.0, min(100.0, val)) / 100.0)
            if fillw > 0:
                # 圆角胶囊填充（用平滑多边形）
                cv.create_polygon(
                    DesktopPet._round_rect(bx0, y - bh / 2, bx0 + max(bh, fillw),
                                           y + bh / 2, bh / 2),
                    smooth=True, fill=color, outline="")
            y += 34
        # ---- 底部：身体状况胶囊 ----
        sick = s.sick
        pill_txt = "生病中 · 需要治疗" if sick else "状态健康"
        pill_bg = "#ffebee" if sick else "#e8f5e9"
        pill_fg = "#c62828" if sick else "#2e7d32"
        py = 258
        cv.create_polygon(DesktopPet._round_rect(18, py, 18 + 132, py + 26, 13),
                          smooth=True, fill=pill_bg, outline="")
        cv.create_text(18 + 66, py + 13, text=pill_txt, font=(fam, 9), fill=pill_fg)
        # 金币 / 经验 / 成就
        cv.create_text(166, py + 6, text=f"金币 {s.coins}", font=(fam, 9),
                       fill=cfg.UI_TEXT_DIM, anchor="w")
        cv.create_text(166, py + 22, text=f"经验 {s.exp}/{s.exp_to_next()}　"
                                       f"成就 {len(s.achievements)}/{len(ACHIEVEMENTS)}",
                       font=(fam, 8), fill=cfg.UI_TEXT_DIM, anchor="w")
        tk.Label(self.body, text=s.report().split("\n")[0], font=self.font_s,
                 fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG).pack(pady=(4, 0))


# ==============================================================================
# 8.9 桌面挂件数据层 —— 天气 / 穿衣建议 / 网速采样（纯标准库）
# ==============================================================================
def wmo_info(code) -> tuple:
    """WMO 天气代码 → (emoji, 中文描述)；未知代码返回 ('🌡️', '未知')"""
    try:
        return CFG.WMO_MAP.get(int(code), ("🌡️", "未知"))
    except Exception:
        return ("🌡️", "未知")


def is_rain_code(code) -> bool:
    try:
        c = int(code)
    except Exception:
        return False
    return 51 <= c <= 67 or 80 <= c <= 82 or 95 <= c <= 99


def is_snow_code(code) -> bool:
    try:
        c = int(code)
    except Exception:
        return False
    return 71 <= c <= 77 or 85 <= c <= 86


def clothing_advice(temp, code=0, wind=0.0) -> str:
    """
    模块2-3：穿衣建议。
    温度分档 + 特殊天气（雨/雪/大风/高温）追加提示。
    temp 为 None 时返回「还没拿到天气」的提示。
    """
    if temp is None:
        return "天气获取中，稍后再问我哦～"
    try:
        t = float(temp)
    except Exception:
        return "天气获取中，稍后再问我哦～"
    base = CFG.CLOTHING_BANDS[-1][1]
    for limit, text in CFG.CLOTHING_BANDS:
        if t > limit:
            base = text
            break
    extra = []
    if is_rain_code(code):
        extra.append("记得带伞🌂！")
    elif is_snow_code(code):
        extra.append("下雪啦！穿防滑的鞋子哦")
    try:
        if float(wind) >= 30:                     # km/h，大风
            extra.append("风好大，别穿太宽松的衣服被吹跑啦")
    except Exception:
        pass
    if t > 35:
        extra.insert(0, "高温预警！多喝水，少出门")
    msg = base
    if extra:
        msg += "　" + "；".join(extra)
    return msg


def fetch_weather(lat=None, lon=None, timeout=None) -> dict:
    """
    模块2-1：获取天气。多源兜底（都用 urllib，无需 API Key）：
      1) Open-Meteo（主源，返回 struct 统一格式）
      2) wttr.in（备用源：国内可达性更好；open-meteo 在部分地区会被墙/超时）
    失败时抛最后一个异常，由调用方降级为「暂无天气」。
    """
    lat = CFG.WEATHER_LAT if lat is None else lat
    lon = CFG.WEATHER_LON if lon is None else lon
    timeout = CFG.WEATHER_TIMEOUT if timeout is None else timeout
    errors = []
    # ---- 源 1：Open-Meteo ----
    try:
        url = CFG.WEATHER_API.format(lat=lat, lon=lon)
        req = urllib.request.Request(url, headers={"User-Agent": "DesktopPet/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace"))
        cur = data.get("current") or {}
        daily = data.get("daily") or {}

        def _first(key):
            v = daily.get(key) or []
            return v[0] if v else None

        if cur.get("temperature_2m") is not None:
            return dict(
                temp=cur.get("temperature_2m"), code=cur.get("weather_code"),
                humidity=cur.get("relative_humidity_2m"),
                wind=cur.get("wind_speed_10m"),
                tmin=_first("temperature_2m_min"), tmax=_first("temperature_2m_max"),
                city=CFG.WEATHER_CITY, source="open-meteo", at=time.time())
        errors.append("open-meteo 返回缺字段")
    except Exception as exc:
        errors.append(f"open-meteo: {type(exc).__name__}: {exc}")
        log_event("WEATHER", errors[-1])

    # ---- 源 2：wttr.in（备用）----
    try:
        url = CFG.WEATHER_FALLBACK_API.format(city=urllib.parse.quote(CFG.WEATHER_CITY))
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=max(6.0, timeout)) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace"))
        cc = (data.get("current_condition") or [{}])[0]
        day = (data.get("weather") or [{}])[0]
        temp = cc.get("temp_C")
        if temp is not None:
            # wttr 的 weatherCode 是 WWO 码，这里折算成近似 WMO 码供图标复用
            wwo = str(cc.get("weatherCode", ""))
            def _num(v):
                try:
                    return float(v)
                except Exception:
                    return None
            return dict(
                temp=_num(temp),
                code=_wwo_to_wmo(wwo),
                humidity=_num(cc.get("humidity")),
                wind=_num(cc.get("windspeedKmph")),
                tmin=_num(day.get("mintempC")), tmax=_num(day.get("maxtempC")),
                city=CFG.WEATHER_CITY, source="wttr.in", at=time.time())
        errors.append("wttr.in 返回缺字段")
    except Exception as exc:
        errors.append(f"wttr.in: {type(exc).__name__}: {exc}")
        log_event("WEATHER", errors[-1])

    raise RuntimeError(" / ".join(errors) or "天气源全部失败")


def _wwo_to_wmo(code: str) -> int:
    """wttr.in 的 WWO 天气码 → 近似 WMO 码（只是为了复用同一套 emoji）"""
    try:
        c = int(code)
    except Exception:
        return 3
    if c in (113,):
        return 0                      # 晴
    if c in (116,):
        return 2                      # 多云
    if c in (119, 122):
        return 3                      # 阴
    if c in (143, 248, 260):
        return 45                     # 雾
    if c in (296, 353, 263, 266, 293, 176):
        return 61                     # 小雨
    if c in (299, 302, 305, 308, 356, 359):
        return 63                     # 中/大雨
    if c in (179, 182, 185, 281, 284, 311, 314, 317, 320, 362, 365, 374, 377):
        return 66                     # 冻雨/雨夹雪
    if c in (323, 326, 329, 332, 335, 338, 368, 371):
        return 71                     # 雪
    if c in (200, 386, 389, 392, 395):
        return 95                     # 雷雨
    if c in (227, 230):
        return 75                     # 暴雪
    return 3


# ---- 网速：ctypes 调 IP Helper API（GetIfTable），不依赖 psutil ----
MAX_INTERFACE_NAME_LEN = 256
MAXLEN_PHYSADDR = 8
MAXLEN_IFDESCR = 256


class MIB_IFROW(ctypes.Structure):
    """Win32 MIB_IFROW（用于 GetIfTable，字段顺序/大小严格按 ipifcons.h）"""
    _fields_ = [
        ("wszName", ctypes.c_wchar * MAX_INTERFACE_NAME_LEN),
        ("dwIndex", ctypes.c_uint32), ("dwType", ctypes.c_uint32),
        ("dwMtu", ctypes.c_uint32), ("dwSpeed", ctypes.c_uint32),
        ("dwPhysAddrLen", ctypes.c_uint32),
        ("bPhysAddr", ctypes.c_ubyte * MAXLEN_PHYSADDR),
        ("dwAdminStatus", ctypes.c_uint32), ("dwOperStatus", ctypes.c_uint32),
        ("dwLastChange", ctypes.c_uint32),
        ("dwInOctets", ctypes.c_uint32), ("dwOutOctets", ctypes.c_uint32),
        ("dwInUcastPkts", ctypes.c_uint32), ("dwInNUcastPkts", ctypes.c_uint32),
        ("dwInDiscards", ctypes.c_uint32), ("dwInErrors", ctypes.c_uint32),
        ("dwInUnknownProtos", ctypes.c_uint32),
        ("dwOutUcastPkts", ctypes.c_uint32), ("dwOutNUcastPkts", ctypes.c_uint32),
        ("dwOutDiscards", ctypes.c_uint32), ("dwOutErrors", ctypes.c_uint32),
        ("dwOutQLen", ctypes.c_uint32), ("dwDescrLen", ctypes.c_uint32),
        ("bDescr", ctypes.c_ubyte * MAXLEN_IFDESCR),
    ]


IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_OPER_STATUS_UP = 1


class NetSpeed:
    """
    模块3：网速采样器（纯 ctypes，不用 psutil）。
    每秒读一次网卡的累计字节数，差值 / 间隔 = 速度。
    自动挑选「状态 UP 且流量最大」的网卡；失败时全部返回 0，界面照常显示。
    """

    def __init__(self):
        self.ok = False
        self.adapter = ""
        self.kind = "未知"
        self.in_kb = 0.0
        self.out_kb = 0.0
        self.total_in = 0.0          # 本次运行累计（KB）
        self.total_out = 0.0
        self._prev = None            # (in_octets, out_octets)
        self._prev_t = 0.0
        self._idx = None
        self._warned = False
        # 结构体大小自检：对不上就整体降级（避免读到野数据）
        expected = 860
        self.size_ok = ctypes.sizeof(MIB_IFROW) == expected
        try:
            self.iphlpapi = ctypes.windll.iphlpapi
        except Exception:
            self.iphlpapi = None

    # ---------------- 内部 ----------------
    def _read_rows(self):
        """调用 GetIfTable 读出所有网卡行"""
        if not self.iphlpapi or not self.size_ok:
            return []
        size = ctypes.c_ulong(0)
        # 第一次调用一定返回 122（ERROR_INSUFFICIENT_BUFFER），同时把所需字节数写进 size——
        # 这是正常流程，不能当错误处理。
        self.iphlpapi.GetIfTable(None, ctypes.byref(size), True)
        if size.value <= 4:
            return []
        buf = ctypes.create_string_buffer(size.value)
        rc = self.iphlpapi.GetIfTable(buf, ctypes.byref(size), True)
        if rc != 0:
            return []
        n = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[0]
        base = ctypes.addressof(buf) + 4
        row_size = ctypes.sizeof(MIB_IFROW)
        if n <= 0 or n > 512:
            return []
        out = []
        for i in range(n):
            try:
                row = MIB_IFROW.from_address(base + i * row_size)
            except Exception:
                break
            out.append(row)
        return out

    @staticmethod
    def _desc(row) -> str:
        try:
            n = min(int(row.dwDescrLen), MAXLEN_IFDESCR)
            raw = bytes(bytearray(row.bDescr[:n]))
            return raw.split(b"\x00")[0].decode("mbcs", "replace").strip()
        except Exception:
            return ""

    def _pick(self, rows):
        """
        挑一个活跃的物理网卡：
        排除回环 / 隧道 / 虚拟 / VPN 适配器，优先 oper=Up，其次按累计流量最大者。
        （实测：某些机器上活动网卡的 dwOperStatus 报 Dormant(5) 而不是 Up(1)，
          所以不能只看状态位，流量大小才是最可靠的判据。）
        """
        bad_words = ("loopback", "miniport", "tunnel", "teredo", "isatap", "virtual",
                     "vpn", "6to4", "ip-https", "wi-fi direct", "wan ")
        best, best_score = None, -1
        best_up, best_up_score = None, -1
        for row in rows:
            try:
                if int(row.dwType) == IF_TYPE_SOFTWARE_LOOPBACK:
                    continue
                desc = self._desc(row).lower()
                if not desc or any(w in desc for w in bad_words):
                    continue
                score = int(row.dwInOctets) + int(row.dwOutOctets)
                if int(row.dwOperStatus) == IF_OPER_STATUS_UP and score > best_up_score:
                    best_up_score, best_up = score, row
                if score > best_score:
                    best_score, best = score, row
            except Exception:
                continue
        return best_up if best_up is not None else best

    def _kind_of(self, desc: str) -> str:
        d = (desc or "").lower()
        if any(k in d for k in ("wi-fi", "wifi", "wlan", "wireless", "无线", "802.11")):
            return "WiFi"
        if any(k in d for k in ("ethernet", "以太", "realtek", "intel", "gbe")):
            return "以太网"
        return "以太网"

    # ---------------- 对外 ----------------
    def sample(self, now: float):
        """采样一次（由主循环按 NET_SAMPLE_INTERVAL 调用）"""
        rows = self._read_rows()
        if not rows:
            self.ok = False
            if not self._warned:
                self._warned = True
                log_event("NET", f"网速不可用（struct_ok={self.size_ok}）")
            return
        row = self._pick(rows)
        if row is None:
            self.ok = False
            return
        try:
            cin, cout = int(row.dwInOctets), int(row.dwOutOctets)
        except Exception:
            self.ok = False
            return
        self.ok = True
        if not self.adapter:
            self.adapter = self._desc(row) or f"网卡{int(row.dwIndex)}"
            self.kind = self._kind_of(self.adapter)
        if self._prev is not None:
            dt = max(0.2, now - self._prev_t)
            din = (cin - self._prev[0]) & 0xFFFFFFFF      # 32 位计数器会回绕
            dout = (cout - self._prev[1]) & 0xFFFFFFFF
            if din > 0x7FFFFFFF:                          # 明显是异常值 → 丢弃
                din = 0
            if dout > 0x7FFFFFFF:
                dout = 0
            self.in_kb = din / 1024.0 / dt
            self.out_kb = dout / 1024.0 / dt
            self.total_in += din / 1024.0
            self.total_out += dout / 1024.0
        self._prev = (cin, cout)
        self._prev_t = now

    def fmt_speed(self, kb: float) -> str:
        if kb < 1:
            return "0 KB/s"
        if kb >= 1024:
            return f"{kb / 1024:.1f} MB/s"
        return f"{kb:.0f} KB/s"

    def text(self) -> str:
        return f"↓ {self.fmt_speed(self.in_kb)} ↑ {self.fmt_speed(self.out_kb)}"

    def color(self) -> str:
        if self.in_kb >= CFG.NET_FAST:
            return CFG.NET_COLORS[0]
        if self.in_kb < CFG.NET_IDLE:
            return CFG.NET_COLORS[2]
        return CFG.NET_COLORS[1]


# ==============================================================================
# 8.10 模块1/2/3/4：桌面挂件卡片（时钟 + 天气 + 网速，画在宠物同一个 Canvas 上）
# ==============================================================================
WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")


def time_theme(tm) -> str:
    """时段 → 主题键：白天 / 傍晚 / 深夜"""
    h = tm.tm_hour
    if 6 <= h < 18:
        return "day"
    if 18 <= h < 22:
        return "evening"
    return "night"


class WidgetCard:
    """
    一张贴在宠物旁边的信息卡（时钟 + 日期 + 天气 + 网速）。
    全部用 Canvas 图元绘制、只创建一次，之后只在数值变化时 itemconfigure。
    卡片画在宠物窗口的同一个 Canvas 上 → 拖拽宠物时自动跟随。
    """

    def __init__(self, canvas, cfg, font_family):
        self.canvas = canvas
        self.cfg = cfg
        self.fam = font_family
        self.items = {}
        self.rows = {}            # 行名 → (y0, y1) 用于悬停命中
        self.visible = False
        self._texts = {}
        self._theme = None
        self.alpha = 1.0
        self._faded = True
        self.bbox = (0, 0, 0, 0)
        self.enabled_rows = []

    # ---------------- 布局 ----------------
    def layout(self):
        """
        挂件卡片：贴在宠物右侧（WIDGET_ON_TOP=False）或正上方（True）。
        多行卡片，高度按启用行数自适应，位置垂直居中于宠物身体。
        """
        cfg = self.cfg
        rows = []
        if cfg.SHOW_CLOCK:
            rows += ["clock", "date"]
        if cfg.SHOW_WEATHER:
            rows.append("weather")
        if cfg.SHOW_NET_SPEED:
            rows.append("net")
        self.enabled_rows = rows
        if not cfg.SHOW_WIDGETS or not rows or (cfg.ULTRA_MODE and cfg.COMPACT):
            return None
        h = cfg.WIDGET_PAD * 2 + sum(cfg.WIDGET_ROW_H.get(r, cfg.WIDGET_LINE_H)
                                     for r in rows)
        if cfg.WIDGET_ON_TOP:
            w = max(90, min(cfg.WIN_W - 8, cfg.WIDGET_W))
            x0 = (cfg.WIN_W - w) // 2
            y0 = 4
        else:
            w = cfg.WIDGET_W
            x0 = 6 if cfg.WIDGET_SIDE == "left" else cfg.PET_COL_W + cfg.WIDGET_GAP
            body_cx = cfg.BUBBLE_ZONE + cfg.SPRITE_H // 2
            y0 = body_cx - h // 2
        self.bbox = (x0, y0, x0 + w, y0 + h)
        return self.bbox

    # ---------------- 绘制 ----------------
    def build(self):
        """创建全部图元（只在启动/开关切换时调用一次）"""
        c = self.canvas
        self.destroy()
        box = self.layout()
        if not box:
            self.visible = False
            return False
        x0, y0, x1, y1 = box
        cfg = self.cfg
        fill, line, main, dim = cfg.WIDGET_THEMES["day"]
        radius = 12 if cfg.WIDGET_SOFT else 10
        # ★ 美化：卡片下方的柔和投影（多层叠加模拟羽化）
        if cfg.UI_SHADOW:
            for i in range(cfg.UI_SHADOW_STEPS, 0, -1):
                grow = i * 1.6
                col = blend(cfg.UI_SHADOW_COLOR, "#ffffff", 0.35 + 0.18 * i)
                self.items[f"sh{i}"] = c.create_polygon(
                    DesktopPet._round_rect(x0 - grow + 1, y0 - grow + cfg.UI_SHADOW_OFFSET,
                                           x1 + grow + 1, y1 + grow + cfg.UI_SHADOW_OFFSET,
                                           radius + grow),
                    smooth=True, fill=col, outline="")
        self.items["bg"] = c.create_polygon(
            DesktopPet._round_rect(x0, y0, x1, y1, radius),
            smooth=True, fill=fill, outline=line, width=1)
        # ★ 美化：卡片顶部一条极淡的高光，让白卡片不"死板"
        if cfg.BUBBLE_GLOSS:
            self.items["gloss"] = c.create_polygon(
                DesktopPet._round_rect(x0 + 2, y0 + 1.5, x1 - 2, y0 + 10, radius - 3),
                smooth=True, fill=blend(fill, "#ffffff", 0.55), outline="")
        self.rows = {}
        cy = y0 + cfg.WIDGET_PAD
        px = x0 + cfg.WIDGET_PAD
        row_h = cfg.WIDGET_ROW_H
        for row in self.enabled_rows:
            rh = row_h.get(row, cfg.WIDGET_LINE_H)
            if row == "clock":
                self.items["clock"] = c.create_text(
                    px, cy + 1, text="00:00", anchor="nw",
                    font=(self.fam, 15, "bold"), fill=main)
            elif row == "date":
                self.items["date"] = c.create_text(
                    px, cy + 2, text="--月--日 星期-", anchor="nw",
                    font=(self.fam, 8), fill=dim)
            elif row == "weather":
                self.items["weather"] = c.create_text(
                    px, cy + 3, text="🌡️ --℃", anchor="nw",
                    font=(self.fam, 9), fill=main)
            elif row == "net":
                self.items["net"] = c.create_text(
                    px, cy + 4, text="↓ 0 KB/s ↑ 0 KB/s", anchor="nw",
                    font=(self.fam, 8), fill=dim)
            self.rows[row] = (cy, cy + rh)
            cy += rh
        # ★ 美化：日期与天气之间加一条发丝分隔线，信息分组更清楚
        if cfg.WIDGET_DIVIDER and "date" in self.rows and "weather" in self.rows:
            ly = (self.rows["date"][1] + self.rows["weather"][0]) / 2
            self.items["div"] = c.create_line(x0 + 8, ly, x1 - 8, ly,
                                              fill=blend(line, "#ffffff", 0.35))
        self._texts = {}
        self._colors = {}
        self._theme = None
        self.visible = True
        return True

    def _layout_row(self):
        """多行卡片不需要重排（保留方法名兼容旧调用）"""
        return

    def destroy(self):
        """清掉卡片全部图元"""
        for it in self.items.values():
            try:
                self.canvas.delete(it)
            except Exception:
                pass
        self.items = {}
        self.rows = {}
        self.visible = False

    def _set(self, key, text, color=None):
        """只有内容变了才更新（避免每帧刷 Canvas）"""
        it = self.items.get(key)
        if it is None:
            return
        if self._texts.get(key) != text:
            self._texts[key] = text
            self.canvas.itemconfigure(it, text=text)
        if color is not None:
            if not hasattr(self, "_colors"):
                self._colors = {}
            if self._colors.get(key) != color:
                self._colors[key] = color
                self.canvas.itemconfigure(it, fill=color)

    # ---------------- 主题（随时间段换色） ----------------
    def apply_theme(self, tm):
        """按当前时段给卡片换底色/文字色（白天白 / 傍晚浅蓝 / 深夜深蓝灰）"""
        cfg = self.cfg
        key = time_theme(tm)
        if key == self._theme:
            return
        self._theme = key
        fill, line, main, dim = cfg.WIDGET_THEMES[key]
        if not hasattr(self, "_colors"):
            self._colors = {}
        if "bg" in self.items:
            self.canvas.itemconfigure(self.items["bg"], fill=fill, outline=line)
        # 投影也跟着底色调整，避免深色卡片配浅投影显脏
        for k in list(self.items):
            if k.startswith("sh"):
                i = int(k[2:])
                col = blend(cfg.UI_SHADOW_COLOR, "#ffffff", 0.35 + 0.18 * i)
                self.canvas.itemconfigure(self.items[k], fill=col)
        if "div" in self.items:
            self.canvas.itemconfigure(self.items["div"],
                                      fill=blend(line, fill, 0.4))
        for name, color in (("clock", main), ("date", dim),
                            ("weather", main), ("net", dim)):
            it = self.items.get(name)
            if it is not None:
                self.canvas.itemconfigure(it, fill=color)
                self._colors[name] = color

    # ---------------- 内容更新 ----------------
    def update(self, tm, weather: dict = None, net=None):
        """多行卡片：钟点 / 日期 / 天气 / 网速"""
        if not self.visible:
            return
        cfg = self.cfg
        self.apply_theme(tm)
        fill, line, main, dim = cfg.WIDGET_THEMES[self._theme or "day"]
        if "clock" in self.items:
            self._set("clock", f"{tm.tm_hour:02d}:{tm.tm_min:02d}", main)
        if "date" in self.items:
            self._set("date", f"{tm.tm_mon}月{tm.tm_mday}日 "
                               f"星期{WEEKDAY_CN[tm.tm_wday]}", dim)
        if "weather" in self.items:
            if weather and weather.get("temp") is not None:
                emoji, label = wmo_info(weather.get("code"))
                txt = f"{emoji} {weather['temp']:.0f}℃ {label}"
            elif getattr(self, "fail_hint", False):
                txt = "🌡️ 获取失败·点击刷新"
            else:
                txt = "🌡️ 获取中…"
            self._set("weather", txt, main)
        if "net" in self.items and net is not None:
            self._set("net", net.text(), net.color())

    # ---------------- 悬停命中 ----------------
    def hit(self, x: float, y: float):
        """鼠标是否落在卡片某一行上 → 返回行名"""
        x0, y0, x1, y1 = self.bbox
        if not self.visible or not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        for row, (ry0, ry1) in self.rows.items():
            if ry0 <= y <= ry1:
                return row
        return None


# ==============================================================================
# 8.11 模块3-3 / 4-2：网速详情面板 + 挂件设置
# ==============================================================================
class NetSpeedPanel(PanelBase):
    """网速详情：当前上/下行、本次运行累计、网络类型"""

    def __init__(self, master, pet):
        super().__init__(master, pet, "网速详情", (400, 340))

    def refresh(self):
        self.clear()
        n = self.pet.net
        cfg = CFG
        box = tk.Frame(self.body, bg=cfg.UI_BG)
        box.pack(fill="x", pady=(2, 8))
        tk.Label(box, text=f"↓ {n.fmt_speed(n.in_kb)}", font=(self.family, 18, "bold"),
                 fg=cfg.NET_COLORS[0] if n.in_kb >= cfg.NET_FAST else cfg.UI_TEXT,
                 bg=cfg.UI_BG).pack(anchor="w")
        tk.Label(box, text=f"↑ {n.fmt_speed(n.out_kb)}", font=(self.family, 14, "bold"),
                 fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG).pack(anchor="w")

        def row(label, value, color=None):
            card = self.make_card(self.body)
            tk.Label(card, text=label, font=self.font_s, fg=cfg.UI_TEXT_DIM,
                     bg=cfg.UI_CARD, width=13, anchor="w").pack(side="left",
                                                               padx=(8, 0), pady=6)
            tk.Label(card, text=value, font=self.font, bg=cfg.UI_CARD,
                     fg=color or cfg.UI_TEXT, anchor="w").pack(side="left")

        row("网络类型", n.kind if n.ok else "未识别",
            cfg.UI_MAIN if n.ok else cfg.UI_TEXT_DIM)
        row("网卡", (n.adapter or "—")[:24])
        row("本次累计下载", f"{n.total_in / 1024:.2f} MB" if n.total_in > 1024
            else f"{n.total_in:.1f} KB")
        row("本次累计上传", f"{n.total_out / 1024:.2f} MB" if n.total_out > 1024
            else f"{n.total_out:.1f} KB")
        tk.Label(self.body, text=("每秒采样一次（ctypes 调 IP Helper API，不依赖 psutil）"
                                 if n.ok else
                                 "读不到网卡计数，网速会保持 0 KB/s（其他功能不受影响）"),
                 font=self.font_s, fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG,
                 wraplength=360, justify="left").pack(anchor="w", pady=(8, 0))


class WidgetSettingsDialog(tk.Toplevel):
    """挂件设置：显示时钟 / 天气 / 网速 + 左右位置"""

    def __init__(self, master, pet, font_spec):
        super().__init__(master)
        self.pet = pet
        cfg = CFG
        self.title("挂件设置")
        self.configure(bg=cfg.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        fam = font_spec[0]
        tk.Label(self, text="挂件设置", font=(fam, 12, "bold"), bg=cfg.UI_BG,
                 fg=cfg.UI_TEXT).pack(anchor="w", padx=16, pady=(14, 8))
        self.vars = {}
        for key, label in (("SHOW_CLOCK", "显示时钟"), ("SHOW_WEATHER", "显示天气"),
                           ("SHOW_NET_SPEED", "显示网速")):
            v = tk.BooleanVar(value=getattr(cfg, key))
            self.vars[key] = v
            tk.Checkbutton(self, text=label, variable=v, font=(fam, 10),
                           bg=cfg.UI_BG, activebackground=cfg.UI_BG,
                           selectcolor="#ffffff", anchor="w",
                           command=self.apply).pack(fill="x", padx=20, pady=1)
        tk.Frame(self, bg=cfg.UI_LINE, height=1).pack(fill="x", padx=16, pady=8)
        tk.Label(self, text="挂件位置", font=(fam, 9), fg=cfg.UI_TEXT_DIM,
                 bg=cfg.UI_BG).pack(anchor="w", padx=16)
        self.side = tk.StringVar(value=cfg.WIDGET_SIDE)
        row = tk.Frame(self, bg=cfg.UI_BG)
        row.pack(anchor="w", padx=20, pady=(2, 8))
        for val, label in (("right", "宠物右侧"), ("left", "宠物左侧")):
            tk.Radiobutton(row, text=label, value=val, variable=self.side,
                           font=(fam, 9), bg=cfg.UI_BG, activebackground=cfg.UI_BG,
                           selectcolor="#ffffff",
                           command=self.apply).pack(side="left", padx=6)
        tk.Label(self, text="改完立刻生效，也会写进 config.json", font=(fam, 8),
                 fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG).pack(anchor="w", padx=16)
        btns = tk.Frame(self, bg=cfg.UI_BG)
        btns.pack(fill="x", padx=16, pady=(10, 14))
        tk.Button(btns, text="关闭", font=(fam, 9), relief="flat", bg=cfg.UI_BTN,
                  padx=16, pady=5, command=self.destroy, cursor="hand2").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")

    def apply(self):
        cfg = CFG
        cfg.SHOW_CLOCK = self.vars["SHOW_CLOCK"].get()
        cfg.SHOW_WEATHER = self.vars["SHOW_WEATHER"].get()
        cfg.SHOW_NET_SPEED = self.vars["SHOW_NET_SPEED"].get()
        old_side = cfg.WIDGET_SIDE
        new_side = self.side.get()
        cfg.apply_layout(True, new_side)
        self.pet.rebuild_widget()
        if new_side != old_side:
            self.pet.relayout_window()
        save_widget_config()
        log_event("WIDGET", f"设置：clock={cfg.SHOW_CLOCK} weather={cfg.SHOW_WEATHER} "
                            f"net={cfg.SHOW_NET_SPEED} side={new_side}")


def save_widget_config():
    """
    模块5：把挂件/城市设置写回 config.json（与 API Key 同文件，不覆盖其他字段）。
    """
    path = os.path.join(app_dir(), "config.json")
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.update(dict(
        city=CFG.WEATHER_CITY, latitude=CFG.WEATHER_LAT, longitude=CFG.WEATHER_LON,
        show_clock=CFG.SHOW_CLOCK, show_weather=CFG.SHOW_WEATHER,
        show_net_speed=CFG.SHOW_NET_SPEED, widget_side=CFG.WIDGET_SIDE,
        weather_refresh_minutes=int(CFG.WEATHER_REFRESH_MIN),
    ))
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log_event("CONFIG", "挂件配置已写入 config.json")
        return True
    except Exception as exc:
        log_event("CONFIG", f"写配置失败：{exc}")
        return False


def load_widget_config() -> dict:
    """
    模块5：从 config.json 读挂件设置（都有默认值，不配也能跑）。
    返回读到的原始字段，供日志/调试使用。
    """
    path = os.path.join(app_dir(), "config.json")
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    # 城市
    city = data.get("city")
    if isinstance(city, str) and city.strip():
        CFG.WEATHER_CITY = city.strip()
    for key, attr in (("latitude", "WEATHER_LAT"), ("longitude", "WEATHER_LON")):
        v = data.get(key)
        if isinstance(v, (int, float)):
            setattr(CFG, attr, float(v))
    rm = data.get("weather_refresh_minutes")
    if isinstance(rm, (int, float)) and rm > 0:
        CFG.WEATHER_REFRESH_MIN = float(rm)
    # 显示开关
    for key, attr in (("show_clock", "SHOW_CLOCK"), ("show_weather", "SHOW_WEATHER"),
                      ("show_net_speed", "SHOW_NET_SPEED")):
        if isinstance(data.get(key), bool):
            setattr(CFG, attr, data[key])
    side = data.get("widget_side")
    if side in ("left", "right"):
        CFG.WIDGET_SIDE = side
    show_any = CFG.SHOW_CLOCK or CFG.SHOW_WEATHER or CFG.SHOW_NET_SPEED
    CFG.apply_layout(show_any, CFG.WIDGET_SIDE)
    log_event("CONFIG", f"挂件配置：city={CFG.WEATHER_CITY} "
                        f"({CFG.WEATHER_LAT},{CFG.WEATHER_LON}) "
                        f"clock={CFG.SHOW_CLOCK} weather={CFG.SHOW_WEATHER} "
                        f"net={CFG.SHOW_NET_SPEED} side={CFG.WIDGET_SIDE}")
    return data


# ==============================================================================
# 8.12 模块1：休闲小游戏（4 个，独立 Toplevel + Canvas，after 驱动）
# ==============================================================================
class MiniGameBase(tk.Toplevel):
    """
    小游戏基类：
      · 每天限次（CFG.GAME_DAILY_LIMIT），进入即消耗一次
      · 右上角显示今日剩余次数
      · 所有定时任务登记在 self.jobs，关窗立即取消（不留后台循环）
      · 奖励统一走 stats.add_reward()，幸运饼干生效时自动翻倍
    """
    GAME_ID = "base"
    GAME_TITLE = "小游戏"
    GAME_W = 320
    GAME_H = 380

    def __init__(self, master, pet, auto_open=True):
        super().__init__(master)
        self.pet = pet
        self.stats = pet.stats
        self.jobs = []
        self.closed = False
        self.over = False
        cfg = CFG
        self.title(self.GAME_TITLE)
        self.configure(bg=cfg.UI_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        fam = pet.font_spec[0]
        self.fam = fam
        head = tk.Frame(self, bg=cfg.UI_BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text=self.GAME_TITLE, font=(fam, 12, "bold"), bg=cfg.UI_BG,
                 fg=cfg.UI_TEXT).pack(side="left")
        self.left_lbl = tk.Label(head, text="", font=(fam, 9), bg=cfg.UI_BG,
                                 fg=cfg.UI_TEXT_DIM)
        self.left_lbl.pack(side="right")
        self.body = tk.Frame(self, bg=cfg.UI_BG)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.footer = tk.Label(self, text="", font=(fam, 9), bg=cfg.UI_BG,
                               fg=cfg.UI_TEXT_DIM, wraplength=self.GAME_W - 36,
                               justify="left")
        self.footer.pack(fill="x", padx=12, pady=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.geometry(f"{self.GAME_W}x{self.GAME_H}")
        self._center()
        self._update_left()
        self.pet.games_open = getattr(self.pet, "games_open", 0) + 1
        try:                                   # 桌宠本体趴着陪玩
            if self.pet.brain.act not in (Act.SLEEP,):
                self.pet.brain.set_act(Act.NAP, 999.0, "陪你玩～我就趴这儿看着", 3.0)
        except Exception:
            pass

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{max(0, (sw - self.GAME_W) // 2)}"
                      f"+{max(0, (sh - self.GAME_H) // 3)}")

    def after_job(self, ms: int, fn):
        """登记 after 任务，关窗时统一取消"""
        if self.closed:
            return None
        jid = self.after(ms, fn)
        self.jobs.append(jid)
        return jid

    def close(self):
        self.closed = True
        for jid in self.jobs:
            try:
                self.after_cancel(jid)
            except Exception:
                pass
        self.jobs = []
        try:
            self.pet.games_open = max(0, getattr(self.pet, "games_open", 1) - 1)
            if self.pet.games_open == 0:
                self.pet.brain.set_act(Act.IDLE, 2.0)
        except Exception:
            pass
        self.destroy()

    def _update_left(self):
        self.left_lbl.config(
            text=f"今日剩余 {self.stats.game_left(self.GAME_ID)} / "
                 f"{self.stats.game_limit(self.GAME_ID)} 次")

    def reward(self, coins: float, exp: float, bond: float, items=None) -> dict:
        """发奖（幸运饼干生效时翻倍）"""
        mult = CFG.ADVENTURE_BOOST_MULT if self.stats.game_double_active() else 1.0
        res = self.stats.add_reward(coins=coins * mult, exp=exp * mult,
                                    bond=bond * mult, items=items,
                                    reason=self.GAME_TITLE)
        self.pet.autosave(force=True)
        if res.get("levelups"):
            self.pet.burst_levelup()
        return res

    def say_result(self, text: str):
        self.footer.config(text=text)
        try:
            self.pet.brain.show_text(text, 3.4)
        except Exception:
            pass


class RPSGame(MiniGameBase):
    """游戏1：猜拳大作战（三局两胜，每局 3 秒冷却）"""
    GAME_ID = "rps"
    GAME_TITLE = "猜拳大作战"
    GAME_W, GAME_H = 340, 400

    def __init__(self, master, pet):
        super().__init__(master, pet)
        self.wins = self.losses = self.rounds = 0
        self.cool_left = 0.0
        fam, cfg = self.fam, CFG
        self.show_lbl = tk.Label(self.body, text="🐸  准备好了吗？", font=(fam, 16),
                                 bg=cfg.UI_BG, fg=cfg.UI_TEXT)
        self.show_lbl.pack(pady=(6, 4))
        self.vs_lbl = tk.Label(self.body, text="三局两胜，用 石头/剪刀/布 决胜负～",
                               font=(fam, 9), bg=cfg.UI_BG, fg=cfg.UI_TEXT_DIM)
        self.vs_lbl.pack(pady=(0, 10))
        row = tk.Frame(self.body, bg=cfg.UI_BG)
        row.pack(pady=4)
        self.btns = {}
        for name, emoji in (("石头", "✊"), ("剪刀", "✌"), ("布", "🖐")):
            b = tk.Button(row, text=f"{emoji}\n{name}", font=(fam, 11), width=5,
                          height=2, relief="flat", bg=cfg.UI_BTN, cursor="hand2",
                          command=lambda n=name: self.play(n))
            b.pack(side="left", padx=6)
            self.btns[name] = b
        self.score_lbl = tk.Label(self.body, text="比分 0 : 0", font=(fam, 10),
                                  bg=cfg.UI_BG, fg=cfg.UI_MAIN)
        self.score_lbl.pack(pady=(10, 0))
        self.footer.config(text="赢一局：好感+8 金币+10 经验+15　输了也有陪伴奖～")

    def play(self, pick: str):
        if self.over or self.cool_left > 0:
            return
        emojis = {"石头": "✊", "剪刀": "✌", "布": "🖐"}
        pet_pick = random.choice(list(emojis))
        self.show_lbl.config(text=f"你 {emojis[pick]}　vs　奶蛙 {emojis[pet_pick]}")
        beats = {"石头": "剪刀", "剪刀": "布", "布": "石头"}
        if pick == pet_pick:
            self.vs_lbl.config(text="平局～心有灵犀！")
        elif beats[pick] == pet_pick:
            self.wins += 1
            self.reward(coins=10, exp=15, bond=8)
            self.vs_lbl.config(text="你赢啦！好厉害～")
        else:
            self.losses += 1
            self.reward(coins=3, exp=4, bond=2)
            self.vs_lbl.config(text="奶蛙赢啦，嘿嘿～")
        self.rounds += 1
        self.score_lbl.config(text=f"比分 {self.wins} : {self.losses}　第 {self.rounds}/3 局")
        if self.rounds >= 3:
            self.finish()
            return
        self.cool_left = CFG.GAME_RPS_COOLDOWN
        self._set_buttons(False)
        self._cool_tick()

    def _set_buttons(self, on: bool):
        for b in self.btns.values():
            b.config(state="normal" if on else "disabled",
                     bg=CFG.UI_BTN if on else "#e8e8e8")

    def _cool_tick(self):
        if self.closed:
            return
        self.cool_left -= 0.25
        if self.cool_left <= 0:
            self.cool_left = 0
            self._set_buttons(True)
            self.footer.config(text="赢一局：好感+8 金币+10 经验+15")
            return
        self.footer.config(text=f"歇 {self.cool_left:.1f} 秒再出下一拳～")
        self.after_job(250, self._cool_tick)

    def finish(self):
        self.over = True
        self._set_buttons(False)
        if self.wins > self.losses:
            msg = f"三局结束：你赢啦！好厉害～（{self.wins}:{self.losses}）"
        elif self.wins < self.losses:
            msg = f"三局结束：奶蛙赢啦～再来一局嘛！（{self.wins}:{self.losses}）"
        else:
            msg = f"三局结束：打平啦！我们果然是一伙的（{self.wins}:{self.losses}）"
        self.show_lbl.config(text="🎉")
        self.vs_lbl.config(text=msg)
        self.say_result(msg)


class CatchGame(MiniGameBase):
    """游戏2：接星星（60 秒，方向键 / A-D 控制）"""
    GAME_ID = "catch"
    GAME_TITLE = "接星星"
    GAME_W, GAME_H = 300, 440

    def __init__(self, master, pet):
        super().__init__(master, pet)
        cfg = CFG
        self.cw, self.ch = cfg.GAME_CATCH_W, cfg.GAME_CATCH_H
        self.score = 0
        self.t_left = cfg.GAME_CATCH_TIME
        self.stars = []
        self.next_spawn = 0.0
        self.basket_x = self.cw / 2
        self.canvas = tk.Canvas(self.body, width=self.cw, height=self.ch,
                               bg="#eaf4ff", highlightthickness=1,
                               highlightbackground=cfg.UI_LINE)
        self.canvas.pack(pady=4)
        self.hud = tk.Label(self.body, text="", font=(self.fam, 10), bg=cfg.UI_BG,
                            fg=cfg.UI_TEXT)
        self.hud.pack()
        self.basket = self.canvas.create_arc(
            self.basket_x - 22, self.ch - 26, self.basket_x + 22, self.ch + 8,
            start=0, extent=180, fill="#ffd94a", outline="#e8bd2e", width=2)
        self.face = self.canvas.create_text(self.basket_x, self.ch - 12, text="🐸",
                                            font=(self.fam, 13))
        # 对象池：预建图元，运行期只改坐标/状态
        for _ in range(cfg.GAME_CATCH_POOL):
            it = self.canvas.create_text(0, 0, text="⭐", font=(self.fam, 13),
                                         state="hidden")
            self.stars.append(dict(item=it, x=0.0, y=0.0, kind="normal", active=False))
        self.canvas.focus_set()
        self.bind("<Left>", lambda e: self._move(-16))
        self.bind("<Right>", lambda e: self._move(16))
        for k in ("a", "A"):
            self.bind(f"<{k}>", lambda e: self._move(-16))
        for k in ("d", "D"):
            self.bind(f"<{k}>", lambda e: self._move(16))
        self._upd_hud()
        self.footer.config(text="← → 或 A D 移动　⭐+10　☄️-5　🌟+50")
        self.after_job(60, self._loop)

    def _move(self, dx):
        if self.over:
            return
        self.basket_x = max(24, min(self.cw - 24, self.basket_x + dx))
        self.canvas.coords(self.basket, self.basket_x - 22, self.ch - 26,
                           self.basket_x + 22, self.ch + 8)
        self.canvas.coords(self.face, self.basket_x, self.ch - 12)

    def _spawn(self):
        free = [s for s in self.stars if not s["active"]]
        if not free:
            return
        s = free[0]
        r = random.random()
        if r < CFG.GAME_CATCH_BAD_RATE:
            s["kind"], glyph = "bad", "☄️"
        elif r < CFG.GAME_CATCH_BAD_RATE + CFG.GAME_CATCH_GOLD_RATE:
            s["kind"], glyph = "gold", "🌟"
        else:
            s["kind"], glyph = "normal", "⭐"
        s["x"] = random.uniform(18, self.cw - 18)
        s["y"] = -10.0
        s["active"] = True
        self.canvas.coords(s["item"], s["x"], s["y"])
        self.canvas.itemconfigure(s["item"], text=glyph, state="normal")

    def _loop(self):
        if self.closed or self.over:
            return
        dt = 0.06
        self.t_left -= dt
        self.next_spawn -= dt
        if self.next_spawn <= 0:
            self.next_spawn = CFG.GAME_CATCH_SPAWN * random.uniform(0.7, 1.3)
            self._spawn()
        for s in self.stars:
            if not s["active"]:
                continue
            s["y"] += CFG.GAME_CATCH_FALL * dt
            self.canvas.coords(s["item"], s["x"], s["y"])
            if s["y"] >= self.ch - 22 and abs(s["x"] - self.basket_x) < 26:
                s["active"] = False
                self.canvas.itemconfigure(s["item"], state="hidden")
                self.score += -5 if s["kind"] == "bad" else (50 if s["kind"] == "gold" else 10)
            elif s["y"] > self.ch + 14:
                s["active"] = False
                self.canvas.itemconfigure(s["item"], state="hidden")
                if s["kind"] != "bad":
                    self.score -= 2
        self._upd_hud()
        if self.t_left <= 0:
            self.finish()
            return
        self.after_job(60, self._loop)

    def _upd_hud(self):
        self.hud.config(text=f"得分 {self.score}　剩余 {max(0, self.t_left):.0f} 秒")

    def finish(self):
        self.over = True
        for s in self.stars:
            s["active"] = False
            self.canvas.itemconfigure(s["item"], state="hidden")
        if self.score >= 30:
            items = {}
            if random.random() < 0.20:
                items[random.choice(["草莓蛋糕", "音乐盒", "稀有种子"])] = 1
            res = self.reward(coins=20, exp=25, bond=15, items=items)
            msg = f"太棒了！{self.score} 分，好感 +15 金币 +20"
        elif self.score >= 15:
            res = self.reward(coins=10, exp=15, bond=10)
            msg = f"不错哦！{self.score} 分，好感 +10 金币 +10"
        else:
            res = self.reward(coins=5, exp=8, bond=5)
            msg = f"{self.score} 分～参与奖！好感 +5 金币 +5"
        if res.get("items"):
            msg += f"　还捡到了 {list(res['items'])}"
        self.hud.config(text=f"最终得分 {self.score}")
        self.say_result(msg)


class MemoryGame(MiniGameBase):
    """游戏3：记忆翻牌（4x3，6 对）"""
    GAME_ID = "memory"
    GAME_TITLE = "记忆翻牌"
    GAME_W, GAME_H = 350, 430

    def __init__(self, master, pet):
        super().__init__(master, pet)
        cfg, fam = CFG, self.fam
        self.steps = 0
        self.matched = 0
        self.flipped = []
        self.locked = False
        cards = list(cfg.GAME_MEMORY_EMOJI)[:cfg.GAME_MEMORY_PAIRS] * 2
        random.shuffle(cards)
        self.cards = cards
        self.cell, self.gap, cols = 66, 8, 4
        rows = 3
        w = cols * self.cell + (cols + 1) * self.gap
        h = rows * self.cell + (rows + 1) * self.gap
        self.canvas = tk.Canvas(self.body, width=w, height=h, bg=cfg.UI_BG,
                               highlightthickness=0)
        self.canvas.pack(pady=4)
        self.rects = []
        for i in range(len(cards)):
            r, c = divmod(i, cols)
            x0 = self.gap + c * (self.cell + self.gap)
            y0 = self.gap + r * (self.cell + self.gap)
            rect = self.canvas.create_rectangle(x0, y0, x0 + self.cell,
                                               y0 + self.cell, fill=cfg.UI_MAIN,
                                               outline="#ffffff", width=2,
                                               tags=f"c{i}")
            txt = self.canvas.create_text(x0 + self.cell / 2, y0 + self.cell / 2,
                                          text="?", fill="#ffffff",
                                          font=(fam, 20, "bold"), tags=f"c{i}")
            self.rects.append((rect, txt))
            self.canvas.tag_bind(f"c{i}", "<Button-1>", lambda e, k=i: self.flip(k))
        self.hud = tk.Label(self.body, text="", font=(fam, 10), bg=cfg.UI_BG,
                            fg=cfg.UI_TEXT)
        self.hud.pack()
        self._upd_hud()
        self.footer.config(text="点两张牌试试～步数越少奖励越高")

    def _upd_hud(self):
        self.hud.config(text=f"步数 {self.steps}　已配对 "
                             f"{self.matched}/{CFG.GAME_MEMORY_PAIRS}")

    def flip(self, i):
        if self.over or self.locked or i in self.flipped or self.cards[i] is None:
            return
        rect, txt = self.rects[i]
        self.canvas.itemconfigure(rect, fill="#ffffff")
        self.canvas.itemconfigure(txt, text=self.cards[i], fill=CFG.UI_TEXT)
        self.flipped.append(i)
        if len(self.flipped) < 2:
            return
        self.steps += 1
        a, b = self.flipped
        if self.cards[a] == self.cards[b]:
            self.cards[a] = self.cards[b] = None
            self.matched += 1
            self.flipped = []
            self._upd_hud()
            if self.matched >= CFG.GAME_MEMORY_PAIRS:
                self.finish()
        else:
            self.locked = True
            self.after_job(700, self._flip_back)
        self._upd_hud()

    def _flip_back(self):
        if self.closed:
            return
        for i in self.flipped:
            rect, txt = self.rects[i]
            self.canvas.itemconfigure(rect, fill=CFG.UI_MAIN)
            self.canvas.itemconfigure(txt, text="?", fill="#ffffff")
        self.flipped = []
        self.locked = False

    def finish(self):
        self.over = True
        if self.steps <= 10:
            items = {random.choice(["草莓蛋糕", "音乐盒", "稀有种子"]): 1}
            res = self.reward(coins=25, exp=30, bond=20, items=items)
            msg = f"全部配对！{self.steps} 步，好感 +20 金币 +25"
        elif self.steps <= 15:
            res = self.reward(coins=15, exp=20, bond=12)
            msg = f"全部配对！{self.steps} 步，好感 +12 金币 +15"
        else:
            res = self.reward(coins=8, exp=12, bond=8)
            msg = f"全部配对！{self.steps} 步，好感 +8 金币 +8"
        if res.get("items"):
            msg += f"　奖励 {list(res['items'])}"
        self.say_result(msg)
        self._upd_hud()


class MoleGame(MiniGameBase):
    """游戏4：打地鼠（30 秒，3x3 洞）"""
    GAME_ID = "mole"
    GAME_TITLE = "打地鼠"
    GAME_W, GAME_H = 330, 420

    def __init__(self, master, pet):
        super().__init__(master, pet)
        cfg = CFG
        self.hits = 0
        self.t_left = cfg.GAME_MOLE_TIME
        self.cool = 0.0
        self.mole = -1
        self.size = 260
        self.canvas = tk.Canvas(self.body, width=self.size, height=self.size,
                                bg="#f7f1e3", highlightthickness=1,
                                highlightbackground=cfg.UI_LINE)
        self.canvas.pack(pady=4)
        pad = 14
        self.cell = (self.size - pad * 4) / 3
        self.holes = []
        for r in range(3):
            for c in range(3):
                x0 = pad + c * (self.cell + pad)
                y0 = pad + r * (self.cell + pad)
                hole = self.canvas.create_oval(x0, y0, x0 + self.cell,
                                               y0 + self.cell, fill="#d9c7a3",
                                               outline="#b8a480", width=2, tags="hole")
                self.holes.append((x0, y0, hole))
        self.mole_item = self.canvas.create_text(0, 0, text="🐸", font=(self.fam, 22),
                                                 state="hidden", tags="mole")
        self.canvas.tag_bind("mole", "<Button-1>", lambda e: self.hit_mole())
        self.canvas.tag_bind("hole", "<Button-1>", lambda e: self.miss())
        self.hud = tk.Label(self.body, text="", font=(self.fam, 10), bg=cfg.UI_BG,
                            fg=cfg.UI_TEXT)
        self.hud.pack()
        self._upd_hud()
        self.footer.config(text="30 秒内点到的奶蛙越多越好～打空要歇一下")
        self._pop()
        self._loop()

    def _upd_hud(self):
        self.hud.config(text=f"打中 {self.hits} 次　剩余 {max(0, self.t_left):.0f} 秒")

    def _pop(self):
        if self.closed or self.over:
            return
        idx = random.randrange(9)
        tries = 0
        while idx == self.mole and tries < 5:
            idx = random.randrange(9)
            tries += 1
        self.mole = idx
        x0, y0, _ = self.holes[idx]
        self.canvas.coords(self.mole_item, x0 + self.cell / 2, y0 + self.cell / 2)
        self.canvas.itemconfigure(self.mole_item, state="normal")
        self.after_job(random.randint(620, 1100), self._hide)

    def _hide(self):
        if self.closed or self.over:
            return
        self.canvas.itemconfigure(self.mole_item, state="hidden")
        self.after_job(random.randint(180, 420), self._pop)

    def hit_mole(self):
        if self.over or self.cool > 0 or self.closed:
            return
        self.hits += 1
        self.stats.add_bond(1.0, "打地鼠")
        self.canvas.itemconfigure(self.mole_item, state="hidden")
        self._upd_hud()

    def miss(self):
        if self.over or self.cool > 0 or self.closed:
            return
        self.cool = CFG.GAME_MOLE_COOLDOWN
        self._cool()

    def _cool(self):
        if self.closed or self.over:
            return
        self.cool -= 0.25
        if self.cool > 0:
            self.after_job(250, self._cool)
        self._upd_hud()

    def _loop(self):
        if self.closed or self.over:
            return
        self.t_left -= 0.25
        self._upd_hud()
        if self.t_left <= 0:
            self.finish()
            return
        self.after_job(250, self._loop)

    def finish(self):
        self.over = True
        self.canvas.itemconfigure(self.mole_item, state="hidden")
        if self.hits >= 15:
            items = {random.choice(["草莓蛋糕", "音乐盒", "稀有种子"]): 1}
            res = self.reward(coins=22, exp=28, bond=18, items=items)
            msg = f"好快的手！打中 {self.hits} 次，好感 +18 金币 +22"
        elif self.hits >= 8:
            res = self.reward(coins=12, exp=18, bond=10)
            msg = f"打中 {self.hits} 次，好感 +10 金币 +12"
        else:
            res = self.reward(coins=5, exp=8, bond=5)
            msg = f"打中 {self.hits} 次～下次更快些，好感 +5 金币 +5"
        if res.get("items"):
            msg += f"　奖励 {list(res['items'])}"
        self.say_result(msg)


class PetGameBase(MiniGameBase):
    """
    第十一阶段：带桌宠互动的游戏基类。
      · 标题统一「和奶蛙一起玩：XXX」
      · 右侧/顶部画桌宠头像（复用现有 idle 素材，缩小显示）
      · 提供 say()/头像换心情/历史最高分显示
    """
    AVATAR_H = 72

    def __init__(self, master, pet, auto_open=True):
        super().__init__(master, pet, auto_open)
        self.title(f"和奶蛙一起玩：{self.GAME_TITLE}")
        self._avatars = {}
        self._avatar_item = None
        self.pet_mood = "idle"
        self._best = int(self.stats.game_high_score(self.GAME_ID))
        if self._best > 0:
            self.footer.config(text=f"历史最高：{self._best}")

    # ---------------- 桌宠头像 ----------------
    def avatar(self, mood: str = "idle", height: int = None):
        """把现有素材缩成小头像（带 alpha，直接贴到普通窗口）"""
        h = int(height or self.AVATAR_H)
        key = (mood, h)
        if key in self._avatars:
            return self._avatars[key]
        frames = self.pet.assets.get(mood) or self.pet.assets.get("idle") or []
        if not frames:
            return None
        img = frames[0]
        try:
            w = max(1, int(round(img.width * h / img.height)))
            small = img.convert("RGBA").resize((w, h), RES_BICUBIC)
            photo = ImageTk.PhotoImage(small, master=self)
        except Exception:
            return None
        self._avatars[key] = photo
        return photo

    def set_mood(self, mood: str):
        """切换游戏窗口里桌宠的表情素材"""
        if mood == self.pet_mood:
            return
        photo = self.avatar(mood)
        if photo is None:
            return
        self.pet_mood = mood
        if self._avatar_item is not None:
            try:
                self.canvas.itemconfigure(self._avatar_item, image=photo)
            except Exception:
                pass

    def say(self, text: str, dur: float = 2.6):
        """游戏内台词 + 桌面气泡同步（桌宠本体在趴着陪玩）"""
        lbl = getattr(self, "hint", None)
        if lbl is not None:
            try:
                lbl.config(text=text)
            except Exception:
                pass
        try:
            self.pet.brain.show_text(text, dur)
        except Exception:
            pass

    # ---------------- 结算 ----------------
    def finish(self, score: float, coins: float, exp: float, bond: float,
               items=None, tail: str = ""):
        """统一结算：最高分 → 奖励 → 提示"""
        if self.over:
            return
        self.over = True
        broke = self.stats.game_record(self.GAME_ID, score)
        res = self.reward(coins, exp, bond, items)
        best = int(self.stats.game_high_score(self.GAME_ID))
        bits = []
        if coins:
            bits.append(f"金币 +{coins:g}")
        if exp:
            bits.append(f"经验 +{exp:g}")
        if bond:
            bits.append(f"亲密度 +{bond:g}")
        got = res.get("items") or {}
        if got:
            bits.append("得到 " + "、".join(f"{k}×{v}" for k, v in got.items()))
        txt = ("🏆 新纪录！" if broke else "") + "　".join(bits)
        if tail:
            txt = (txt + "　" if txt else "") + tail
        self.footer.config(text=f"{txt}\n历史最高：{best}")
        try:
            self.pet.brain.show_text("（结算）" + (txt or "玩得开心！"), 4.0)
        except Exception:
            pass

    def penalty(self, coins: float = 0, bond: float = 0):
        """扣金币 / 扣亲密度（add_reward 只接受正数，惩罚单独走）"""
        try:
            if coins:
                self.stats.add_coins(int(coins))
            if bond:
                self.stats.bond = max(0.0, self.stats.bond + float(bond))
            self.pet.autosave(force=True)
        except Exception:
            log_event("GAME", traceback.format_exc())

    def grant_rare(self):
        """随机给一个稀有道具（add_reward 要 {名称: 数量}）"""
        name = random.choice(CFG.GAME_RARE_POOL)
        return {name: 1}


# ==============================================================================
# 游戏 5：俄罗斯方块（桌宠当陪练）
# ==============================================================================
TETRIS_SHAPES = {
    "I": ((0, 1), (1, 1), (2, 1), (3, 1)),
    "O": ((1, 0), (2, 0), (1, 1), (2, 1)),
    "T": ((1, 0), (0, 1), (1, 1), (2, 1)),
    "S": ((1, 0), (2, 0), (0, 1), (1, 1)),
    "Z": ((0, 0), (1, 0), (1, 1), (2, 1)),
    "J": ((0, 0), (0, 1), (1, 1), (2, 1)),
    "L": ((2, 0), (0, 1), (1, 1), (2, 1)),
}


class TetrisGame(PetGameBase):
    GAME_ID = "tetris"
    GAME_TITLE = "俄罗斯方块"
    GAME_W, GAME_H = 480, 530

    def __init__(self, master, pet, auto_open=True):
        super().__init__(master, pet, auto_open)
        cfg = CFG
        self.cols, self.rows, self.cell = cfg.TETRIS_COLS, cfg.TETRIS_ROWS, cfg.TETRIS_CELL
        self.board = [[None] * self.cols for _ in range(self.rows)]
        self.score, self.lines = 0, 0
        self.help_left = cfg.TETRIS_HELP_USES
        self.freeze_until = 0.0
        self.last_clear_t = time.time()
        self.last_prank_t = time.time()
        self.danger_said = False
        self.paused = False
        self._fall_acc = 0.0
        self._last_now = time.time()
        self._drawn = [[None] * self.cols for _ in range(self.rows)]

        # ---- 布局：左棋盘 + 右信息栏 ----
        wrap = tk.Frame(self.body, bg=CFG.UI_BG)
        wrap.pack()
        self.cw, self.ch = self.cols * self.cell, self.rows * self.cell
        self.canvas = tk.Canvas(wrap, width=self.cw + 20, height=self.ch + 8,
                                bg="#fafafa", highlightthickness=1,
                                highlightbackground="#dcdcdc")
        self.canvas.pack(side="left", padx=(0, 8))
        self.board_x, self.board_y = 10, 4

        side = tk.Frame(wrap, bg=CFG.UI_BG, width=190)
        side.pack(side="left", fill="y")
        # 桌宠头像
        photo = self.avatar("idle", 88)
        self._avatar_item = self.canvas.create_image(
            self.cw + 10, self.ch // 2, image=photo, anchor="e") if False else None
        self.avatar_lbl = tk.Label(side, bg=CFG.UI_BG, image=photo)
        if photo is not None:
            self.avatar_lbl.image = photo
        self.avatar_lbl.pack(pady=(2, 4))
        self.hint = tk.Label(side, text="我坐这儿陪你～", font=(self.fam, 9),
                             fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG, wraplength=180,
                             justify="left")
        self.hint.pack(anchor="w", pady=(0, 6))
        self.info = tk.Label(side, text="", font=(self.fam, 10), fg=CFG.UI_TEXT,
                             bg=CFG.UI_BG, justify="left")
        self.info.pack(anchor="w")
        # 三个道具按钮
        btns = tk.Frame(side, bg=CFG.UI_BG)
        btns.pack(anchor="w", pady=(8, 0))
        self.help_btns = {}
        for key, text, cmd in (("freeze", "🧊 冰冻", self.use_freeze),
                               ("lightning", "⚡ 闪电", self.use_lightning),
                               ("gift", "🎁 随机", self.use_gift)):
            b = tk.Button(btns, text=text, font=(self.fam, 8), width=7,
                          bg=CFG.UI_CARD, fg=CFG.UI_TEXT, relief="flat",
                          activebackground=CFG.UI_ACCENT, cursor="hand2",
                          command=cmd)
            b.pack(side="left", padx=1)
            self.help_btns[key] = b

        self._draw_grid()
        self._spawn()
        self._bind_keys()
        self._refresh_info()
        self._last_now = time.time()
        self.after_job(16, self._loop)
        self.say("来玩俄罗斯方块！我就在旁边看着～", 3.0)

    # ---------------- 键盘 ----------------
    def _bind_keys(self):
        self.focus_set()
        self.bind("<Left>", lambda e: self.move(-1))
        self.bind("<Right>", lambda e: self.move(1))
        self.bind("<Down>", lambda e: self.soft_drop())
        self.bind("<Up>", lambda e: self.rotate(1))
        self.bind("<space>", lambda e: self.hard_drop())
        self.bind("<KeyPress-a>", lambda e: self.move(-1))
        self.bind("<KeyPress-d>", lambda e: self.move(1))
        self.bind("<KeyPress-s>", lambda e: self.soft_drop())
        self.bind("<KeyPress-w>", lambda e: self.rotate(1))
        self.bind("<KeyPress-p>", lambda e: self.toggle_pause())

    def toggle_pause(self):
        if self.over:
            return
        self.paused = not self.paused
        self.say("歇一下～（按 P 继续）" if self.paused else "接着来！")

    # ---------------- 方块 ----------------
    def _spawn(self):
        kind = getattr(self, "next_kind", None) or random.choice(list(TETRIS_SHAPES))
        self.cur = dict(kind=kind, cells=list(TETRIS_SHAPES[kind]),
                        x=(self.cols - 4) // 2, y=0)
        self.next_kind = random.choice(list(TETRIS_SHAPES))
        if self._collide(self.cur["cells"], self.cur["x"], self.cur["y"]):
            self._game_over()

    def _collide(self, cells, px, py):
        for cx, cy in cells:
            x, y = px + cx, py + cy
            if x < 0 or x >= self.cols or y >= self.rows:
                return True
            if y >= 0 and self.board[y][x]:
                return True
        return False

    def move(self, dx):
        if self.over or self.paused or not getattr(self, "cur", None):
            return
        if not self._collide(self.cur["cells"], self.cur["x"] + dx, self.cur["y"]):
            self.cur["x"] += dx
            self._render()

    def rotate(self, direction=1):
        if self.over or self.paused or not getattr(self, "cur", None):
            return
        cells = [((3 - y) if direction > 0 else y, x) for x, y in self.cur["cells"]]
        for kick in (0, -1, 1, -2, 2):
            if not self._collide(cells, self.cur["x"] + kick, self.cur["y"]):
                self.cur["cells"] = cells
                self.cur["x"] += kick
                self._render()
                return

    def soft_drop(self):
        if self.over or self.paused or not getattr(self, "cur", None):
            return
        if not self._collide(self.cur["cells"], self.cur["x"], self.cur["y"] + 1):
            self.cur["y"] += 1
            self._render()
        else:
            self._lock()

    def hard_drop(self):
        if self.over or self.paused or not getattr(self, "cur", None):
            return
        while not self._collide(self.cur["cells"], self.cur["x"], self.cur["y"] + 1):
            self.cur["y"] += 1
        self._lock()

    def _lock(self):
        color = CFG.TETRIS_COLORS[self.cur["kind"]]
        for cx, cy in self.cur["cells"]:
            x, y = self.cur["x"] + cx, self.cur["y"] + cy
            if 0 <= y < self.rows and 0 <= x < self.cols:
                self.board[y][x] = color
        self.cur = None
        cleared = self._clear_lines()
        if cleared:
            self.score += cleared * 10
            self.lines += cleared
            coins = cleared * CFG.TETRIS_LINE_COINS
            exp = cleared * CFG.TETRIS_LINE_EXP
            self.reward(coins, exp, 0)
            self.last_clear_t = time.time()
            self.danger_said = False
            if cleared >= 4:
                self.say("哇——！太帅了吧！！", 3.0)
                self.set_mood("happy")
                self.after_job(1400, lambda: self.set_mood("idle"))
            else:
                self.say("好厉害！" if cleared > 1 else "消掉啦～", 2.2)
        self._refresh_info()
        self._spawn()

    def _clear_lines(self):
        keep = [row for row in self.board if any(c is None for c in row)]
        cleared = self.rows - len(keep)
        if cleared:
            self.board = [[None] * self.cols for _ in range(cleared)] + keep
            self._drawn = [[None] * self.cols for _ in range(self.rows)]
            self._draw_grid()
        return cleared

    def _stack_ratio(self):
        filled = sum(1 for row in self.board for c in row if c)
        return filled / float(self.cols * self.rows)

    def _fall_interval(self):
        ms = CFG.TETRIS_FALL_MS - self.lines * CFG.TETRIS_SPEEDUP_PER_LINE
        return max(CFG.TETRIS_FALL_MIN_MS, ms) / 1000.0

    # ---------------- 道具 ----------------
    def _spend_help(self):
        if self.help_left <= 0:
            self.say("我的道具用完啦，剩下的靠你自己！", 2.6)
            return False
        self.help_left -= 1
        self._refresh_info()
        return True

    def use_freeze(self):
        if self.over or not self._spend_help():
            return
        self.freeze_until = time.time() + CFG.TETRIS_FREEZE_MS / 1000.0
        self.say("冻结！方块先别掉～", 2.2)
        self.set_mood("happy")
        self.after_job(1200, lambda: self.set_mood("idle"))

    def use_lightning(self):
        if self.over or not self._spend_help():
            return
        if all(c is None for c in self.board[self.rows - 1]):
            self.say("最下面那行本来就空的呀～", 2.2)
            return
        self.board.pop()
        self.board.insert(0, [None] * self.cols)
        self.lines += 1
        self.score += 10
        self.reward(CFG.TETRIS_LINE_COINS, CFG.TETRIS_LINE_EXP, 0)
        self._drawn = [[None] * self.cols for _ in range(self.rows)]
        self._draw_grid()
        self._refresh_info()
        self.say("闪电！最底下一行没啦～", 2.4)
        self.set_mood("happy")
        self.after_job(1200, lambda: self.set_mood("idle"))

    def use_gift(self):
        if self.over or not self._spend_help():
            return
        if random.random() < 0.5:
            name = random.choice(CFG.GAME_RARE_POOL)
        else:
            name = random.choice(["珍珠奶茶", "草莓蛋糕", "小球", "音乐盒"])
        self.reward(0, 0, 0, items={name: 1})
        self.say(f"送你一个「{name}」！", 2.6)
        self.set_mood("happy")
        self.after_job(1200, lambda: self.set_mood("idle"))

    # ---------------- 主循环 ----------------
    def _loop(self):
        if self.closed:
            return
        now = time.time()
        dt = min(0.1, max(0.0, now - self._last_now))
        self._last_now = now
        if self.over:
            return
        if not self.paused and getattr(self, "cur", None):
            interval = self._fall_interval()
            if now < self.freeze_until:
                interval = 99.0
            self._fall_acc += dt
            if self._fall_acc >= interval:
                self._fall_acc = 0.0
                if not self._collide(self.cur["cells"], self.cur["x"], self.cur["y"] + 1):
                    self.cur["y"] += 1
                else:
                    self._lock()
        # 危险提醒
        if not self.danger_said and self._stack_ratio() >= CFG.TETRIS_DANGER_RATIO:
            self.danger_said = True
            self.say("小心哦！要堆到我脸上啦！", 3.0)
        # 30 秒没消行
        if now - self.last_clear_t > CFG.TETRIS_IDLE_LINE_SEC and not self.over:
            self.last_clear_t = now
            self.say("发什么呆呢，快放呀～", 2.4)
        # 捣乱（亲密度高 → 频率减半）
        gap = CFG.TETRIS_PRANK_INTERVAL
        if bond_tier(self.stats.bond) in ("好朋友", "亲密伙伴"):
            gap *= 2.0
        if now - self.last_prank_t > gap and not self.paused:
            self.last_prank_t = now
            self.say("呀！对不起手滑了～", 2.2)
            self.rotate(1)
        self._render()
        self.after_job(16, self._loop)

    def _game_over(self):
        if self.over:
            return
        self.cur = None
        self.set_mood("sad" if self.pet.assets.get("mood20") else "idle")
        self.say("呜……没关系啦，再来一局！", 3.4)
        lines = self.lines
        if lines >= 10:
            items = self.grant_rare() if random.random() < 0.20 else None
            self.finish(self.score, 30, 20, 15, items,
                        tail="(10 行以上，好厉害！)" if items is None else "")
        elif lines >= 5:
            self.finish(self.score, 15, 10, 10)
        else:
            self.finish(self.score, 5, 5, 5, tail="(陪玩奖)")

    # ---------------- 绘制 ----------------
    def _draw_grid(self):
        if getattr(self, "_grid_done", False):
            return
        self._grid_done = True
        for y in range(self.rows):
            for x in range(self.cols):
                x0 = self.board_x + x * self.cell
                y0 = self.board_y + y * self.cell
                self.canvas.create_rectangle(x0, y0, x0 + self.cell - 1,
                                             y0 + self.cell - 1,
                                             fill="#f2f2f2", outline="#e6e6e6")
        self._cells = {}
        for y in range(self.rows):
            for x in range(self.cols):
                x0 = self.board_x + x * self.cell
                y0 = self.board_y + y * self.cell
                self._cells[(x, y)] = self.canvas.create_rectangle(
                    x0, y0, x0 + self.cell - 1, y0 + self.cell - 1,
                    fill="", outline="")

    def _paint(self, x, y, color):
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return
        if self._drawn[y][x] == color:
            return
        self._drawn[y][x] = color
        item = self._cells.get((x, y))
        if item is None:
            return
        if color:
            self.canvas.itemconfigure(item, fill=color,
                                      outline=blend(color, "#000000", 0.25))
            self.canvas.tag_raise(item)
        else:
            self.canvas.itemconfigure(item, fill="", outline="")

    def _render(self):
        for y in range(self.rows):
            for x in range(self.cols):
                self._paint(x, y, self.board[y][x])
        if getattr(self, "cur", None):
            color = CFG.TETRIS_COLORS[self.cur["kind"]]
            for cx, cy in self.cur["cells"]:
                self._paint(self.cur["x"] + cx, self.cur["y"] + cy, color)

    def _refresh_info(self):
        nxt = getattr(self, "next_kind", "?")
        self.info.config(text=f"分数 {self.score}\n行数 {self.lines}\n"
                              f"下一个 {nxt}\n道具 {self.help_left}/{CFG.TETRIS_HELP_USES}")
        self._update_left()
        for key, btn in self.help_btns.items():
            btn.config(state=("disabled" if (self.over or self.help_left <= 0)
                              else "normal"))


# ==============================================================================
# 游戏 6：扫雷（桌宠当探测器）
# ==============================================================================
class MinesweeperGame(PetGameBase):
    GAME_ID = "mine"
    GAME_TITLE = "扫雷"
    GAME_W, GAME_H = 400, 540

    def __init__(self, master, pet, auto_open=True):
        super().__init__(master, pet, auto_open)
        cfg = CFG
        self.cols, self.rows, self.cell = cfg.MINE_COLS, cfg.MINE_ROWS, cfg.MINE_CELL
        self.mine_count = cfg.MINE_COUNT
        self.lives = cfg.MINE_LIVES
        self.detect_left = cfg.MINE_DETECT_USES
        self.mines, self.counts = set(), {}
        self.opened, self.flags, self.foot = set(), set(), set()
        self.start_t = None
        self.elapsed = 0.0
        self.shake_until = 0.0
        self._place_mines()

        # ---- 顶部信息条 ----
        top = tk.Frame(self.body, bg=CFG.UI_BG)
        top.pack(fill="x")
        self.mine_lbl = tk.Label(top, text="", font=(self.fam, 10), bg=CFG.UI_BG,
                                 fg=CFG.UI_TEXT)
        self.mine_lbl.pack(side="left")
        self.time_lbl = tk.Label(top, text="⏱ 0s", font=(self.fam, 10), bg=CFG.UI_BG,
                                 fg=CFG.UI_TEXT_DIM)
        self.time_lbl.pack(side="right")
        self.life_lbl = tk.Label(top, text="", font=(self.fam, 10), bg=CFG.UI_BG,
                                 fg="#e57373")
        self.life_lbl.pack(side="right", padx=8)

        # ---- 宠物 + 探测器 ----
        prow = tk.Frame(self.body, bg=CFG.UI_BG)
        prow.pack(fill="x", pady=(2, 4))
        photo = self.avatar("idle", 56)
        self.avatar_lbl = tk.Label(prow, bg=CFG.UI_BG, image=photo, cursor="hand2")
        if photo is not None:
            self.avatar_lbl.image = photo
        self.avatar_lbl.pack(side="left")
        self.avatar_lbl.bind("<Button-1>", lambda e: self.detect())
        self.hint = tk.Label(prow, text="点我，我帮你闻一闻～", font=(self.fam, 9),
                             fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG, wraplength=250,
                             justify="left")
        self.hint.pack(side="left", padx=8)
        self.detect_lbl = tk.Label(prow, text="", font=(self.fam, 9),
                                   fg=CFG.UI_ACCENT, bg=CFG.UI_BG)
        self.detect_lbl.pack(side="right")

        # ---- 棋盘 ----
        self.canvas = tk.Canvas(self.body, width=self.cols * self.cell + 4,
                                height=self.rows * self.cell + 4, bg="#c9c9c9",
                                highlightthickness=1, highlightbackground="#b0b0b0")
        self.canvas.pack(pady=4)
        self._rects = {}
        for y in range(self.rows):
            for x in range(self.cols):
                x0, y0 = 2 + x * self.cell, 2 + y * self.cell
                self._rects[(x, y)] = [
                    self.canvas.create_rectangle(x0, y0, x0 + self.cell - 2,
                                                 y0 + self.cell - 2,
                                                 fill="#dcdcdc", outline="#bdbdbd"),
                    self.canvas.create_text(x0 + self.cell / 2 - 1, y0 + self.cell / 2 - 1,
                                            text="", font=(self.fam, 11, "bold")),
                ]
        self.canvas.bind("<Button-1>", lambda e: self.click(e.x, e.y, False))
        self.canvas.bind("<Button-3>", lambda e: self.click(e.x, e.y, True))
        self._refresh()
        self.after_job(200, self._loop)
        self.say("踩到雷我会被吓到哦，小心点～", 3.0)

    def _place_mines(self):
        cells = [(x, y) for y in range(self.rows) for x in range(self.cols)]
        self.mines = set(random.sample(cells, self.mine_count))
        self.counts = {}
        for y in range(self.rows):
            for x in range(self.cols):
                self.counts[(x, y)] = sum(
                    1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx or dy) and (x + dx, y + dy) in self.mines)

    def _cell_at(self, px, py):
        x = (px - 2) // self.cell
        y = (py - 2) // self.cell
        if 0 <= x < self.cols and 0 <= y < self.rows:
            return (int(x), int(y))
        return None

    def click(self, px, py, flag):
        if self.over:
            return
        cell = self._cell_at(px, py)
        if cell is None:
            return
        if self.start_t is None:
            self.start_t = time.time()
            while cell in self.mines:           # 第一下不炸
                self._place_mines()
        if flag:
            if cell in self.opened:
                return
            if cell in self.flags:
                self.flags.discard(cell)
            else:
                self.flags.add(cell)
            self._refresh()
            return
        if cell in self.flags or cell in self.opened:
            return
        if cell in self.mines:
            self._boom(cell)
            return
        self._reveal(cell)
        self._refresh()
        if len(self.opened) >= self.rows * self.cols - self.mine_count:
            self._win()

    def _reveal(self, cell):
        stack = [cell]
        zero_hit = False
        while stack:
            c = stack.pop()
            if c in self.opened or c in self.flags:
                continue
            self.opened.add(c)
            self.foot.discard(c)
            if self.counts.get(c, 0) == 0:
                zero_hit = True
                x, y = c
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (x + dx, y + dy)
                        # ★ 必须做边界钳制：否则边缘的 0 格会往 (-1,-1) 无限扩散
                        if not (0 <= n[0] < self.cols and 0 <= n[1] < self.rows):
                            continue
                        if (dx or dy) and n not in self.opened and n not in self.mines:
                            stack.append(n)
        if zero_hit:
            self.set_mood("happy")
            self.after_job(700, lambda: self.set_mood("idle"))
            self.say("好多空格！我鼓掌！", 2.0)

    def _boom(self, cell):
        self.opened.add(cell)
        self.lives -= 1
        self.shake_until = time.time() + 0.45
        self.penalty(CFG.MINE_MISS_COINS, CFG.MINE_MISS_BOND)
        self.set_mood("sick")
        self.say("哇！炸到我了！", 2.6)
        self._refresh()
        if self.lives <= 0:
            self._lose()
        else:
            self.after_job(900, lambda: self.set_mood("idle"))

    def detect(self):
        """奶娃探测器：找一块 3×3 无雷区域，标记脚印"""
        if self.over:
            return
        if self.detect_left <= 0:
            self.say("我闻不出来啦，剩下的靠你自己！", 3.0)
            return
        candidates = []
        for y in range(self.rows - 2):
            for x in range(self.cols - 2):
                area = [(x + dx, y + dy) for dx in range(3) for dy in range(3)]
                if not any(a in self.mines for a in area) and \
                        any(a not in self.opened for a in area):
                    candidates.append(area)
        if not candidates:
            self.say("嗯……我好像闻不出哪里安全了", 2.6)
            return
        area = random.choice(candidates)
        self.detect_left -= 1
        self.foot.update(a for a in area if a not in self.opened)
        self._refresh()
        self.set_mood("happy")
        self.after_job(1000, lambda: self.set_mood("idle"))
        self.say(f"这块 3×3 肯定没有雷！（还剩 {self.detect_left} 次）", 3.0)

    def _win(self):
        if self.over:
            return
        self.set_mood("happy")
        self.say("全找出来啦！！撒花～", 3.4)
        self._confetti()
        self.finish(int(max(1, 600 - self.elapsed)), 40, 25, 20, self.grant_rare())

    def _lose(self):
        if self.over:
            return
        for c in self.mines:
            self.opened.add(c)
        self._refresh()
        self.set_mood("sad" if self.pet.assets.get("mood20") else "idle")
        self.say("三次都被炸到……下次一定行！", 3.2)
        self.finish(int(max(1, self.elapsed)), 5, 5, 5)

    def _confetti(self):
        w = self.cols * self.cell
        for _ in range(18):
            x = random.uniform(6, w - 6)
            y = random.uniform(6, 40)
            self.canvas.create_text(x, y, text=random.choice(("✨", "🌟", "⭐")),
                                    font=(self.fam, 12))

    def _loop(self):
        if self.closed or self.over:
            return
        now = time.time()
        if self.start_t:
            self.elapsed = now - self.start_t
            self.time_lbl.config(text=f"⏱ {int(self.elapsed)}s")
        # 踩雷抖动
        if getattr(self, "shake_until", 0) > now:
            dx = random.choice((-2, -1, 0, 1, 2))
            self.canvas.place(x=dx, y=dx)
        elif getattr(self, "shake_until", 0):
            self.shake_until = 0.0
            self.canvas.place(x=0, y=0)
        self.after_job(120, self._loop)

    def _refresh(self):
        left = self.mine_count - len(self.flags)
        self.mine_lbl.config(text=f"💣 剩余 {max(0, left)}")
        self.life_lbl.config(text="❤" * max(0, self.lives))
        self.detect_lbl.config(text=f"探测器 {self.detect_left}/{CFG.MINE_DETECT_USES}")
        self._update_left()
        for (x, y), (rect, txt) in self._rects.items():
            cell = (x, y)
            if cell in self.opened:
                if cell in self.mines:
                    self.canvas.itemconfigure(rect, fill="#ffcdd2", outline="#ef9a9a")
                    self.canvas.itemconfigure(txt, text="💥", fill="#c62828")
                else:
                    n = self.counts.get(cell, 0)
                    self.canvas.itemconfigure(rect, fill="#f5f5f5", outline="#e0e0e0")
                    self.canvas.itemconfigure(
                        txt, text=(str(n) if n else ""),
                        fill=CFG.MINE_NUM_COLORS[min(8, n)])
            else:
                if cell in self.flags:
                    self.canvas.itemconfigure(rect, fill="#ffe0b2", outline="#ffb74d")
                    self.canvas.itemconfigure(txt, text="🚩", fill="#ef6c00")
                elif cell in self.foot:
                    self.canvas.itemconfigure(rect, fill="#e8f5e9", outline="#a5d6a7")
                    self.canvas.itemconfigure(txt, text="🐾", fill=CFG.MINE_DETECT_FOOT)
                else:
                    self.canvas.itemconfigure(rect, fill="#dcdcdc", outline="#bdbdbd")
                    self.canvas.itemconfigure(txt, text="", fill="#333333")


# ==============================================================================
# 游戏 7：弹球打砖块（桌宠当挡板）
# ==============================================================================
class BreakoutGame(PetGameBase):
    GAME_ID = "breakout"
    GAME_TITLE = "弹球打砖块"
    GAME_W, GAME_H = 360, 560

    def __init__(self, master, pet, auto_open=True):
        super().__init__(master, pet, auto_open)
        cfg = CFG
        self.cw, self.ch = cfg.BREAKOUT_W, cfg.BREAKOUT_H
        self.lives = cfg.BREAKOUT_LIVES
        self.score = 0
        self.bricks = []
        self.balls = []
        self.powers = []
        self.keys = set()
        self.wide_until = 0.0
        self.slow_until = 0.0
        self.half_said = False
        self.last_said = 0.0
        self._last_now = time.time()
        self.paddle_w = 62.0

        self.canvas = tk.Canvas(self.body, width=self.cw, height=self.ch,
                                bg="#fbfbfb", highlightthickness=1,
                                highlightbackground="#d8d8d8")
        self.canvas.pack()
        # 桌宠 = 挡板
        photo = self.avatar("idle", 40)
        self.paddle_img = photo
        self.paddle_item = self.canvas.create_image(
            self.cw / 2, self.ch - 22, image=photo) if photo is not None else None
        self.paddle_shadow = self.canvas.create_oval(
            self.cw / 2 - 26, self.ch - 8, self.cw / 2 + 26, self.ch - 2,
            fill="#e6e6e6", outline="")
        self.hint_lbl = self.canvas.create_text(
            self.cw / 2, self.ch / 2, text="按 ← → / A D 移动，空格发球",
            font=(self.fam, 9), fill="#9e9e9e")
        self.paddle_x = self.cw / 2
        self.hint = tk.Label(self.body, text="", font=(self.fam, 9),
                             fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG)
        self.hint.pack(pady=(4, 0))
        self._build_bricks()
        self._reset_ball()
        self._bind_keys()
        self._refresh_bar()
        self.after_job(16, self._loop)
        self.say("我当挡板！左右键带我跑～", 3.0)

    def _bind_keys(self):
        self.focus_set()
        self.bind("<KeyPress-Left>", lambda e: self.keys.add("left"))
        self.bind("<KeyRelease-Left>", lambda e: self.keys.discard("left"))
        self.bind("<KeyPress-Right>", lambda e: self.keys.add("right"))
        self.bind("<KeyRelease-Right>", lambda e: self.keys.discard("right"))
        self.bind("<KeyPress-a>", lambda e: self.keys.add("left"))
        self.bind("<KeyRelease-a>", lambda e: self.keys.discard("left"))
        self.bind("<KeyPress-d>", lambda e: self.keys.add("right"))
        self.bind("<KeyRelease-d>", lambda e: self.keys.discard("right"))
        self.bind("<space>", lambda e: self.launch())

    def _build_bricks(self):
        cfg = CFG
        bw = self.cw / cfg.BREAKOUT_COLS
        for r in range(cfg.BREAKOUT_ROWS):
            for c in range(cfg.BREAKOUT_COLS):
                x0 = c * bw + 1
                y0 = cfg.BREAKOUT_TOP + r * (cfg.BREAKOUT_BRICK_H + cfg.BREAKOUT_BRICK_GAP)
                item = self.canvas.create_rectangle(
                    x0, y0, x0 + bw - 2, y0 + cfg.BREAKOUT_BRICK_H,
                    fill=cfg.BREAKOUT_COLORS[r % len(cfg.BREAKOUT_COLORS)],
                    outline="")
                self.bricks.append(dict(item=item, x0=x0, y0=y0,
                                        x1=x0 + bw - 2,
                                        y1=y0 + cfg.BREAKOUT_BRICK_H, alive=True))

    def _reset_ball(self):
        self.balls = [dict(x=self.paddle_x, y=self.ch - 40,
                           vx=0.0, vy=0.0, r=CFG.BREAKOUT_BALL_R,
                           stuck=True,
                           item=self.canvas.create_oval(0, 0, 0, 0,
                                                        fill="#37474f", outline=""))]
        if hasattr(self, "hint_lbl"):
            self.canvas.itemconfigure(self.hint_lbl, state="normal")

    def launch(self):
        for b in self.balls:
            if b["stuck"]:
                b["stuck"] = False
                sp = CFG.BREAKOUT_BALL_SPEED
                b["vx"] = random.choice((-1, 1)) * sp * 0.55
                b["vy"] = -sp
        if hasattr(self, "hint_lbl"):
            self.canvas.itemconfigure(self.hint_lbl, state="hidden")

    # ---------------- 主循环 ----------------
    def _loop(self):
        if self.closed or self.over:
            return
        now = time.time()
        dt = min(0.05, max(0.0, now - self._last_now))
        self._last_now = now
        # 挡板移动
        sp = CFG.BREAKOUT_PADDLE_SPEED
        if "left" in self.keys:
            self.paddle_x -= sp * dt
        if "right" in self.keys:
            self.paddle_x += sp * dt
        half = (self.paddle_w * (1.5 if now < self.wide_until else 1.0)) / 2
        self.paddle_x = max(half + 2, min(self.cw - half - 2, self.paddle_x))
        self._move_paddle(half)
        # 球
        slow = 0.55 if now < self.slow_until else 1.0
        for b in list(self.balls):
            if b["stuck"]:
                b["x"] = self.paddle_x
                b["y"] = self.ch - 40
            else:
                b["x"] += b["vx"] * slow * dt
                b["y"] += b["vy"] * slow * dt
                # 墙
                if b["x"] - b["r"] <= 0:
                    b["x"] = b["r"]
                    b["vx"] = abs(b["vx"])
                elif b["x"] + b["r"] >= self.cw:
                    b["x"] = self.cw - b["r"]
                    b["vx"] = -abs(b["vx"])
                if b["y"] - b["r"] <= 0:
                    b["y"] = b["r"]
                    b["vy"] = abs(b["vy"])
                self._hit_bricks(b)
                # 挡板
                py = self.ch - 22
                if (b["vy"] > 0 and py - 14 <= b["y"] + b["r"] <= py + 10
                        and abs(b["x"] - self.paddle_x) <= half + b["r"]):
                    b["y"] = py - 14 - b["r"]
                    b["vy"] = -abs(b["vy"])
                    offset = (b["x"] - self.paddle_x) / max(1.0, half)
                    b["vx"] = CFG.BREAKOUT_BALL_SPEED * 0.85 * offset
                    self._catch_cheer()
                if b["y"] - b["r"] > self.ch:
                    self.balls.remove(b)
        if not self.balls and not self.over:
            self._lose_life()
        self._update_powers(dt)
        self._draw()
        if not self.bricks:
            self._win_bricks()
        self.after_job(16, self._loop)

    def _move_paddle(self, half):
        if self.paddle_item is not None:
            self.canvas.coords(self.paddle_item, self.paddle_x, self.ch - 22)
        self.canvas.coords(self.paddle_shadow, self.paddle_x - half * 0.8,
                           self.ch - 8, self.paddle_x + half * 0.8, self.ch - 2)

    def _hit_bricks(self, b):
        for br in self.bricks:
            if not br["alive"]:
                continue
            if (br["x0"] - b["r"] <= b["x"] <= br["x1"] + b["r"]
                    and br["y0"] - b["r"] <= b["y"] <= br["y1"] + b["r"]):
                br["alive"] = False
                self.canvas.itemconfigure(br["item"], state="hidden")
                b["vy"] = -b["vy"]
                self.score += 10
                self.reward(CFG.BREAKOUT_BRICK_COINS, 1, 0)
                if random.random() < CFG.BREAKOUT_POWER_CHANCE:
                    self._drop_power((br["x0"] + br["x1"]) / 2, br["y1"])
                alive = [x for x in self.bricks if x["alive"]]
                if alive and not self.half_said and \
                        len(alive) <= len(self.bricks) / 2:
                    self.half_said = True
                    self.say("一半都没啦！球要变快了哦～", 2.6)
                    for bb in self.balls:
                        bb["vx"] *= 1.12
                        bb["vy"] *= 1.12
                self._refresh_bar()
                return

    def _drop_power(self, x, y):
        kind = random.choice(CFG.BREAKOUT_POWER_KINDS)
        icon = {"magnet": "🧲", "multi": "🎈", "slow": "🐌", "life": "💗"}[kind]
        item = self.canvas.create_text(x, y, text=icon, font=(self.fam, 12))
        self.powers.append(dict(kind=kind, x=x, y=y, item=item))

    def _update_powers(self, dt):
        half = (self.paddle_w * (1.5 if time.time() < self.wide_until else 1.0)) / 2
        for p in list(self.powers):
            p["y"] += CFG.BREAKOUT_POWER_FALL * dt
            self.canvas.coords(p["item"], p["x"], p["y"])
            if p["y"] > self.ch:
                self.powers.remove(p)
                self.canvas.delete(p["item"])
                continue
            if (self.ch - 30 <= p["y"] <= self.ch - 8
                    and abs(p["x"] - self.paddle_x) <= half + 8):
                self._apply_power(p["kind"])
                self.powers.remove(p)
                self.canvas.delete(p["item"])

    def _apply_power(self, kind):
        now = time.time()
        if kind == "magnet":
            self.wide_until = now + CFG.BREAKOUT_WIDE_SEC
            self.say("🧲 我变宽啦！", 2.0)
        elif kind == "multi":
            base = self.balls[0] if self.balls else None
            if base is not None:
                for _ in range(2):
                    nb = dict(base)
                    nb["item"] = self.canvas.create_oval(0, 0, 0, 0,
                                                         fill="#37474f", outline="")
                    nb["vx"] = base["vx"] + random.uniform(-70, 70)
                    nb["vy"] = -abs(base["vy"] or CFG.BREAKOUT_BALL_SPEED)
                    self.balls.append(nb)
            self.say("🎈 三个球！冲呀！", 2.0)
        elif kind == "slow":
            self.slow_until = now + CFG.BREAKOUT_SLOW_SEC
            self.say("🐌 球慢下来了，好接～", 2.0)
        elif kind == "life":
            self.lives += 1
            self._refresh_bar()
            self.say("💗 多一条命！", 2.0)
        self.set_mood("happy")
        self.after_job(900, lambda: self.set_mood("idle"))

    def _catch_cheer(self):
        now = time.time()
        if now - self.last_said < 1.2:
            return
        self.last_said = now
        self.say("接住啦！", 1.4)
        self.after_job(120, lambda: self._hop())

    def _hop(self):
        if self.closed:
            return
        self.canvas.move(self.paddle_item, 0, -6)
        self.after_job(140, lambda: self.canvas.move(self.paddle_item, 0, 6))

    def _lose_life(self):
        self.lives -= 1
        self._refresh_bar()
        self.set_mood("sad" if self.pet.assets.get("mood20") else "idle")
        if self.lives <= 0:
            self.say("呜……三条命都用完了", 3.0)
            self.finish(self.score, 10, 8, 8)
            return
        self.say("呜……让它跑了", 2.2)
        if self.lives == 1:
            self.say("只剩最后一条命了哦……", 3.0)
        self.after_job(700, lambda: self.set_mood("idle"))
        self._reset_ball()

    def _win_bricks(self):
        if self.over:
            return
        self.set_mood("happy")
        self.say("通关啦！我在终点跳舞～", 3.4)
        for _ in range(16):
            self.canvas.create_text(random.uniform(10, self.cw - 10),
                                    random.uniform(60, 200),
                                    text=random.choice(("✨", "🌟")),
                                    font=(self.fam, 12))
        items = {CFG.GAME_MEDAL_ITEM: 1} if random.random() < 0.15 else None
        self.finish(self.score, 35, 25, 18, items)

    def _refresh_bar(self):
        self._update_left()
        alive = len([b for b in self.bricks if b["alive"]])
        self.footer.config(text=f"❤ {self.lives}　砖块剩 {alive}　分数 {self.score}")

    def _draw(self):
        for b in self.balls:
            r = b["r"]
            self.canvas.coords(b["item"], b["x"] - r, b["y"] - r,
                               b["x"] + r, b["y"] + r)
            self.canvas.tag_raise(b["item"])


# ==============================================================================
# ==============================================================================
# 12. 第十二阶段：15 项扩展功能 —— 数据层
# ==============================================================================
# 设计说明：
#   全部状态集中在 ExtraState 里，由 PetStats.extra 持有，存档时整体序列化，
#   面板 / 渲染 / 计时器都只读这个对象，互不耦合，方便单独测试。
# ==============================================================================

# ---------------- C13 装扮（全部 Canvas 形状绘制，不依赖外部素材） ----------------
# kind: hat / glasses / back；shape 决定画什么形状
OUTFITS = {
    # 普通（60%）
    "hat_cap":    dict(kind="hat", shape="cap", name="小圆帽", tier=1, desc="软软的针织小圆帽"),
    "hat_straw":  dict(kind="hat", shape="straw", name="草帽", tier=1, desc="夏天戴最合适"),
    "hat_beanie": dict(kind="hat", shape="beanie", name="毛线帽", tier=1, desc="冬天不冻耳朵"),
    "hat_bow":    dict(kind="hat", shape="bow", name="蝴蝶结", tier=1, desc="系在头顶很可爱"),
    # 稀有（30%）
    "back_wing":   dict(kind="back", shape="wing", name="小翅膀", tier=2, desc="虽然飞不起来"),
    # 史诗（10%）
    "hat_crown":   dict(kind="hat", shape="crown", name="小皇冠", tier=3, desc="你是我的国王/女王"),
    "hat_wizard":  dict(kind="hat", shape="wizard", name="魔法帽", tier=3, desc="帽尖会跟着晃"),
    "back_halo":   dict(kind="back", shape="halo", name="小光环", tier=3, desc="光环是限量款哦"),
}
# ---------------- 皮肤（整只奶蛙换色，只在换装界面预览，不显示到桌面上） ----------------
# rate = 扭蛋机里抽到的概率，与装扮共用同一次抽取（总和 21%，其余 79% 是装扮）
SKIN_DIR = "assets/skins"
SKINS = {
    "skin_red":     dict(name="热情苹果红", file="skin_red.png", rate=0.05,
                         desc="红通通的，像刚摘下来的苹果"),
    "skin_pink":    dict(name="樱花桃粉", file="skin_pink.png", rate=0.05,
                         desc="粉粉嫩嫩，樱花落下来的颜色"),
    "skin_blue":    dict(name="晴空海豚蓝", file="skin_blue.png", rate=0.05,
                         desc="晴天的海豚蓝，看着就凉快"),
    "skin_purple":  dict(name="香芋薰衣草紫", file="skin_purple.png", rate=0.05,
                         desc="薰衣草味的香芋紫"),
    "skin_rainbow": dict(name="彩虹渐变", file="skin_rainbow.png", rate=0.01,
                         desc="传说款！整只蛙都是渐变的彩虹"),
}
SKIN_IDS = tuple(SKINS)
OUTFIT_TIER_NAME = {1: "普通", 2: "稀有", 3: "史诗"}
OUTFIT_TIER_COLOR = {1: "#9e9e9e", 2: "#42a5f5", 3: "#ff9800"}
GACHA_TIER_WEIGHT = ((1, 0.60), (2, 0.30), (3, 0.10))

# ---------------- C14 家具 ----------------
FURNITURE = {
    "mat":      dict(name="小垫子", price=80, emoji="🟫", desc="无聊值衰减更慢（-25%）",
                     effect="bored_slow"),
    "lamp":     dict(name="小台灯", price=120, emoji="💡", desc="晚上精力恢复 +30%",
                     effect="night_energy"),
    "tent":     dict(name="小帐篷", price=150, emoji="⛺", desc="生病恢复速度翻倍",
                     effect="heal_fast"),
}

# ---------------- D17 天赋树 ----------------
TALENTS = {
    # 效率分支
    "adv_bonus":   dict(branch="效率", name="探险收益 +20%", desc="探险奖励提高两成",
                        need_level=5, effect="adv_bonus"),
    "game_bonus":  dict(branch="效率", name="游戏奖励 +30%", desc="小游戏奖励提高三成",
                        need_level=10, effect="game_bonus"),
    "coin_bonus":  dict(branch="效率", name="金币获取 +25%", desc="所有金币收入提高两成半",
                        need_level=15, effect="coin_bonus"),
    # 生存分支
    "sick_resist": dict(branch="生存", name="生病概率 -50%", desc="不容易生病了",
                        need_level=5, effect="sick_resist"),
    "decay_slow":  dict(branch="生存", name="属性衰减 -30%", desc="四维掉得更慢",
                        need_level=10, effect="decay_slow"),
    "offline_pro": dict(branch="生存", name="离线保护 +4 小时", desc="回来时掉得很少",
                        need_level=15, effect="offline_pro"),
    # 互动分支
    "bond_bonus":  dict(branch="互动", name="亲密度获取 +30%", desc="陪它更有效果",
                        need_level=5, effect="bond_bonus"),
    "daily_extra": dict(branch="互动", name="每日奖励次数 +2", desc="小游戏能多玩两次",
                        need_level=10, effect="daily_extra"),
    "bag_extra":   dict(branch="互动", name="背包容量 +5", desc="能装更多东西",
                        need_level=15, effect="bag_extra"),
}
TALENT_BRANCHES = ("效率", "生存", "互动")

# ---------------- D20 主线故事 ----------------
STORY_CHAPTERS = (
    dict(level=1, title="第一章 · 我是谁？",
         text="（一只小小的黄色奶蛙从屏幕角落探出头）\n"
              "「我为什么会出现在你的桌面上？……我也不知道诶。\n"
              "　不过我好像记得，有人在等我。」"),
    dict(level=5, title="第二章 · 来自奶蛙星球",
         text="「其实我是从奶蛙星球来的……那里的天是奶茶色的。\n"
              "　我坐了好久的流星才到这儿，正好落在你的桌面上。\n"
              "　这一定是缘分吧！」"),
    dict(level=10, title="第三章 · 发现的小秘密",
         text="「今天第一次出去探险，我发现了一个小秘密——\n"
              "　每次我走远了，你都会偷偷看我回来没有。\n"
              "　嘿嘿，我都知道哦。」"),
    dict(level=15, title="第四章 · 你一直在照顾我",
         text="「原来你一直在悄悄照顾我。\n"
              "　怕我饿，怕我无聊，怕我生病……\n"
              "　其实我什么都不缺，只要你在就好。」"),
    dict(level=20, title="终章 · 一直在一起",
         text="「谢谢你选了我。\n"
              "　往后的每一个清晨和深夜，我都想赖在你的桌面上。\n"
              "　我们要一直在一起哦。」"),
)

# ---------------- B10 节日表（农历节日用固定表，超出年份就不放） ----------------
FESTIVALS = {
    # (月, 日): (名称, 装饰形状, 粒子里形状, 祝福台词)
    (1, 1):  ("元旦", "firework", "star", "新年快乐！今年也要一起过哦～"),
    (2, 14): ("情人节", "heart", "heart", "情人节快乐！虽然我只是一只蛙，但我很喜欢你"),
    (10, 1): ("国庆节", "flag", "star", "国庆快乐！放假了要好好休息呀"),
    (12, 25): ("圣诞节", "christmas", "snow", "圣诞快乐！我给你准备了小礼物～"),
}
# 农历节日（按年份硬编码，未收录的年份只显示公历节日）
LUNAR_FESTIVALS = {
    2026: {"spring": "2026-02-17", "dragon": "2026-06-19", "mid": "2026-09-25"},
    2027: {"spring": "2027-02-06", "dragon": "2027-06-09", "mid": "2027-09-15"},
    2028: {"spring": "2028-01-26", "dragon": "2028-05-28", "mid": "2028-10-03"},
}
LUNAR_NAMES = {"spring": ("春节", "fu", "firecracker", "春节快乐！恭喜发财，红包拿来～"),
               "dragon": ("端午节", "zongzi", "leaf", "端午快乐！今天要记得吃粽子哦"),
               "mid": ("中秋节", "moon", "leaf", "中秋快乐！月亮好圆，我们一起看吧")}

# ---------------- C15 季节 ----------------
SEASONS = {
    "spring": dict(name="春", months=(3, 4, 5), particle="petal",
                   colors=("#ffd6e7", "#ffb7d5"), ground="#8bc34a",
                   line="春天来了，花开啦～"),
    "summer": dict(name="夏", months=(6, 7, 8), particle="sun",
                   colors=("#fff59d", "#ffe082"), ground="#66bb6a",
                   line="夏天好热，记得多喝水哦"),
    "autumn": dict(name="秋", months=(9, 10, 11), particle="leaf",
                   colors=("#ffcc80", "#d7a86e"), ground="#b8860b",
                   line="秋天到了，叶子都黄了"),
    "winter": dict(name="冬", months=(12, 1, 2), particle="snow",
                   colors=("#e3f2fd", "#ffffff"), ground="#eceff1",
                   line="冬天啦，我把小垫子铺厚一点"),
}

# ---------------- A5 情绪关键词 ----------------
EMOTION_WORDS = {
    "neg": ("累", "烦", "难过", "emo", "痛苦", "想哭", "压力", "崩溃", "疲惫",
            "加班", "失眠", "不开心", "委屈", "撑不住"),
    "pos": ("开心", "哈哈", "太好了", "高兴", "快乐", "爽", "棒", "喜欢",
            "好耶", "幸福", "升职", "放假"),
    "angry": ("生气", "气死", "妈的", "烦死", "滚", "讨厌", "火大", "可恶"),
}
EMOTION_REPLY = {
    "neg": ("辛苦了，休息一下吧", "嗯…我在呢，慢慢来就好",
            "别硬撑，先喝口水再说"),
    "pos": ("我也跟着开心起来了！", "嘿嘿，看你这么高兴我也高兴",
            "太好了！要记得跟我分享呀"),
    "angry": ("别生气别生气，气坏身体不好", "深呼吸一下，我陪你缓一缓",
              "谁惹你了呀？我帮你瞪他"),
}

# ---------------- A1 日记模板 ----------------
DIARY_TIME_LINES = ("今天主人陪了我 {mins} 分钟，我一直在数着。",
                    "和主人待了 {mins} 分钟，感觉时间过得好快。",
                    "{mins} 分钟里有大半你都在看我，我知道的。",
                    "今天一起待了 {mins} 分钟，我挺满足的。")
DIARY_HAPPY_LINES = ("今天最开心的是{what}。",
                     "要说最高兴的事，那就是{what}了。",
                     "今天让我偷偷乐了半天的是{what}。")
DIARY_HAPPY_WHAT = ("我们一起玩了游戏", "主人喂我喝奶茶", "我升级了",
                    "主人摸了摸我的头", "我们一起出门探险",
                    "主人夸我可爱", "我戴上新帽子照了半天")
DIARY_REGRET_LINES = ("不过也有点小遗憾：{what}。",
                      "要说遗憾，大概就是{what}吧。",
                      "有一点小小的不开心：{what}。")
DIARY_REGRET_WHAT = ("主人太久没理我了", "我今天生了一次病",
                     "主人一直在忙，没顾上我", "我想吃的东西还没有吃到",
                     "我又犯困了，没陪你多久")
DIARY_WISH_LINES = ("明天的小愿望是{what}。",
                    "明天要是能{what}就好了。",
                    "悄悄许个愿：明天可以{what}。")
DIARY_WISH_WHAT = ("和主人去探险", "吃到草莓蛋糕", "有一顶新帽子",
                   "主人多陪我一会儿", "一起玩俄罗斯方块", "睡个饱饱的午觉")
DIARY_EMOTION_LINES = {
    "neg": "今天你好像有点不开心，我一直在旁边陪着，没敢闹。",
    "angry": "今天你生气了，我缩在角落里，希望你现在好一点了。",
    "pos": "今天你心情特别好，我也跟着蹦了好几下。",
}


class ExtraState:
    """15 项扩展功能的全部状态（整体序列化进 savegame）"""

    def __init__(self):
        # ---- A1 日记 ----
        self.diary = []                 # [{date, content, mood}]
        # ---- A2 纪念日 ----
        self.first_day = ""
        self.anniv_seen = ""
        # ---- A4 记忆库 ----
        self.memory = []                # [{topic, content, time}]
        # ---- A5 情绪 ----
        self.emotion = "normal"         # normal / neg / pos / angry
        self.emotion_since = 0.0
        self.emotion_last_hug = 0.0
        self.emotion_today = "normal"
        # ---- B7 提醒 ----
        self.water_on = True
        self.sit_on = True
        self.water_t = 0.0
        self.sit_t = 0.0
        # ---- B8 待办 ----
        self.todo = []                  # [{text, done}]
        self.todo_all_done_date = ""
        # ---- B9 系统 ----
        self.cpu_high_since = 0.0
        self.battery_warned = False
        # ---- C11 图鉴 ----
        self.codex = {"animal": [], "item": [], "place": []}
        self.codex_time = {}            # {条目id: 首次获得时间}
        # ---- C12/C13 装扮 ----
        self.wardrobe = []
        self.skin_owned = []            # 已获得的皮肤 id
        self.skin_current = ""          # 当前皮肤（只影响换装界面预览）
        self.outfit = {"hat": "", "glasses": "", "back": ""}
        self.outfit_presets = []        # [{hat, glasses, back, name}]
        self.gacha_date = ""
        self.gacha_count = 0
        # ---- C14 家具 ----
        self.furniture = []
        self.placed = []
        # ---- C15 季节 ----
        self.season_override = ""
        # ---- D17 天赋 ----
        self.talent_points = 0
        self.talents = []
        self.talent_levels_given = 0
        # ---- D20 故事 ----
        self.story_read = []
        # ---- 引导 ----
        self.tips_seen = []

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return dict(
            diary_list=self.diary, first_day=self.first_day,
            anniv_seen=self.anniv_seen, memory_store=self.memory,
            emotion=self.emotion, emotion_since=self.emotion_since,
            emotion_last_hug=self.emotion_last_hug, emotion_today=self.emotion_today,
            reminder=dict(water_on=self.water_on, sit_on=self.sit_on,
                          water_t=self.water_t, sit_t=self.sit_t),
            todo_list=self.todo, todo_all_done_date=self.todo_all_done_date,
            codex_unlocked=self.codex, codex_time=self.codex_time,
            wardrobe=self.wardrobe, equipped_outfit=self.outfit,
            skin_owned=self.skin_owned, skin_current=self.skin_current,
            outfit_presets=self.outfit_presets,
            gacha_date=self.gacha_date, gacha_count=self.gacha_count,
            furniture=self.furniture, furniture_placed=self.placed,
            season_override=self.season_override,
            talent_points=self.talent_points, talents=self.talents,
            talent_levels_given=self.talent_levels_given,
            story_chapters_read=self.story_read,
            tips_seen=self.tips_seen,
        )

    def from_dict(self, data: dict):
        if not isinstance(data, dict):
            return
        self.diary = [d for d in (data.get("diary_list") or [])
                      if isinstance(d, dict) and d.get("date")]
        self.first_day = str(data.get("first_day") or "")
        self.anniv_seen = str(data.get("anniv_seen") or "")
        self.memory = [m for m in (data.get("memory_store") or [])
                       if isinstance(m, dict)]
        self.emotion = str(data.get("emotion") or "normal")
        self.emotion_since = float(data.get("emotion_since") or 0)
        self.emotion_last_hug = float(data.get("emotion_last_hug") or 0)
        self.emotion_today = str(data.get("emotion_today") or "normal")
        rem = data.get("reminder") or {}
        if isinstance(rem, dict):
            self.water_on = bool(rem.get("water_on", True))
            self.sit_on = bool(rem.get("sit_on", True))
            self.water_t = float(rem.get("water_t") or 0)
            self.sit_t = float(rem.get("sit_t") or 0)
        self.todo = [t for t in (data.get("todo_list") or [])
                     if isinstance(t, dict) and t.get("text")]
        self.todo_all_done_date = str(data.get("todo_all_done_date") or "")
        cx = data.get("codex_unlocked") or {}
        if isinstance(cx, dict):
            for k in ("animal", "item", "place"):
                v = cx.get(k) or []
                self.codex[k] = [str(x) for x in v]
        ct = data.get("codex_time") or {}
        if isinstance(ct, dict):
            self.codex_time = {str(k): str(v) for k, v in ct.items()}
        # 已删除的装扮（如披风）自动从衣柜里剔除，避免出现空条目
        self.wardrobe = [w for w in (str(x) for x in (data.get("wardrobe") or []))
                         if w in OUTFITS]
        self.skin_owned = [s for s in (str(x) for x in (data.get("skin_owned") or []))
                           if s in SKINS]
        _cur = str(data.get("skin_current") or "")
        self.skin_current = _cur if _cur in self.skin_owned else ""
        eq = data.get("equipped_outfit") or {}
        if isinstance(eq, dict):
            for k in ("hat", "glasses", "back"):
                self.outfit[k] = str(eq.get(k) or "")
        self.outfit_presets = [p for p in (data.get("outfit_presets") or [])
                               if isinstance(p, dict)][:3]
        for k in ("hat", "glasses", "back"):
            if self.outfit.get(k) and self.outfit[k] not in OUTFITS:
                self.outfit[k] = ""
        self.gacha_date = str(data.get("gacha_date") or "")
        self.gacha_count = int(data.get("gacha_count") or 0)
        self.furniture = [str(x) for x in (data.get("furniture") or [])]
        self.placed = [str(x) for x in (data.get("furniture_placed") or [])]
        self.season_override = str(data.get("season_override") or "")
        self.talent_points = int(data.get("talent_points") or 0)
        self.talents = [str(x) for x in (data.get("talents") or [])]
        self.talent_levels_given = int(data.get("talent_levels_given") or 0)
        self.story_read = [int(x) for x in (data.get("story_chapters_read") or [])
                           if str(x).isdigit()]
        self.tips_seen = [str(x) for x in (data.get("tips_seen") or [])]

    # ---------------- A1 日记 ----------------
    def diary_has(self, date: str) -> bool:
        return any(d.get("date") == date for d in self.diary)

    def diary_add(self, date: str, content: str, mood: str = "normal"):
        if self.diary_has(date):
            for d in self.diary:
                if d.get("date") == date:
                    d["content"] = content
                    d["mood"] = mood
                    return
        self.diary.append(dict(date=date, content=content, mood=mood))
        self.diary.sort(key=lambda d: d.get("date", ""))

    def diary_count(self) -> int:
        return len(self.diary)

    def diary_of_month(self, year: int, month: int) -> dict:
        """{日: 有日记?}"""
        out = {}
        for d in self.diary:
            try:
                y, m, dd = str(d["date"]).split("-")
                if int(y) == year and int(m) == month:
                    out[int(dd)] = True
            except Exception:
                continue
        return out

    # ---------------- A4 记忆库 ----------------
    def memory_add(self, topic: str, content: str, limit: int = 40):
        if not topic or not content:
            return
        content = str(content)[:120]
        for m in self.memory:
            if m.get("topic") == topic:
                m["content"] = content
                m["time"] = time.strftime("%Y-%m-%d %H:%M")
                return
        self.memory.append(dict(topic=str(topic)[:24], content=content,
                                time=time.strftime("%Y-%m-%d %H:%M")))
        if len(self.memory) > limit:
            self.memory = self.memory[-limit:]

    def memory_recent(self, n: int = 5) -> list:
        return list(self.memory[-n:])

    def memory_prompt(self, n: int = 5) -> str:
        """
        拼进 system prompt 的记忆。
        ★ 关键信息（生日/名字/喜好/在忙/住处）**优先保留**，
          不会被后来的「备忘」挤出去；剩余名额再补最近的其它记忆。
        """
        n = max(1, n)
        keys = ("生日", "名字", "喜欢", "讨厌", "在忙", "住处")
        key_items = [m for m in self.memory if m.get("topic") in keys]
        others = [m for m in self.memory if m.get("topic") not in keys]
        room = max(0, n - len(key_items))
        mem = key_items[-max(n, len(key_items)):] + (others[-room:] if room else [])
        if not mem:
            return ""
        lines = [f"- {m.get('topic', '')}：{m.get('content', '')}" for m in mem]
        return ("【你记得的关于主人的事（长期记忆）】\n" + "\n".join(lines) +
                "\n这些是你真的记下来的：对方问到时要准确回答（比如生日、名字、"
                "喜欢的东西）；平时可以自然地提起，但不要每次生硬复述。"
                "如果对方说「要记住…」，回答里要确认你记住了。")

    def memory_delete(self, idx: int):
        if 0 <= idx < len(self.memory):
            self.memory.pop(idx)

    # ---------------- B8 待办 ----------------
    def todo_add(self, text: str):
        text = str(text).strip()[:60]
        if text:
            self.todo.append(dict(text=text, done=False))

    def todo_toggle(self, idx: int):
        if 0 <= idx < len(self.todo):
            self.todo[idx]["done"] = not self.todo[idx].get("done")

    def todo_del(self, idx: int):
        if 0 <= idx < len(self.todo):
            self.todo.pop(idx)

    def todo_pending(self) -> list:
        return [t for t in self.todo if not t.get("done")]

    # ---------------- C11 图鉴 ----------------
    def codex_unlock(self, kind: str, key: str) -> bool:
        """返回是否新解锁"""
        if kind not in self.codex or not key:
            return False
        if key in self.codex[kind]:
            return False
        self.codex[kind].append(str(key))
        self.codex_time[f"{kind}:{key}"] = time.strftime("%Y-%m-%d")
        return True

    def codex_has(self, kind: str, key: str) -> bool:
        return key in (self.codex.get(kind) or [])

    # ---------------- C12 扭蛋 ----------------
    def gacha_reset_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        if self.gacha_date != today:
            self.gacha_date = today
            self.gacha_count = 0

    def gacha_left(self) -> int:
        self.gacha_reset_if_needed()
        return max(0, CFG.GACHA_DAILY - self.gacha_count)

    def gacha_draw(self) -> dict:
        """
        抽一次（不扣钱，扣钱由调用方处理）。
        ★ 皮肤与装扮**同一次抽取里共同计算概率**：
          皮肤占 rate 之和（0.05×4 + 0.01 = 21%），剩下 79% 按原 60/30/10 分给装扮。
        返回 {outfit, kind, is_new, refund}，kind 为 "skin" 或 "outfit"。
        """
        self.gacha_reset_if_needed()
        self.gacha_count += 1
        r = random.random()
        skin_total = sum(v["rate"] for v in SKINS.values())
        if r < skin_total:                       # ---- 先判皮肤 ----
            acc = 0.0
            pick = SKIN_IDS[-1]
            for sid in SKIN_IDS:
                acc += SKINS[sid]["rate"]
                if r <= acc:
                    pick = sid
                    break
            if pick in self.skin_owned:
                return dict(outfit=pick, kind="skin", is_new=False,
                            refund=CFG.GACHA_DUP_REFUND)
            self.skin_owned.append(pick)
            if not self.skin_current:            # 第一件皮肤自动穿上（仅界面）
                self.skin_current = pick
            return dict(outfit=pick, kind="skin", is_new=True, refund=0)
        # ---- 其余 79% 给装扮（保持 60/30/10 的内部比例）----
        scale = 1.0 / max(1e-6, (1.0 - skin_total))
        acc = skin_total
        tier = 3
        for t, w in GACHA_TIER_WEIGHT:
            acc += w * scale * (1.0 - skin_total)
            if r <= acc:
                tier = t
                break
        pool = [k for k, v in OUTFITS.items() if v["tier"] == tier]
        if not pool:
            pool = list(OUTFITS)
        pick = random.choice(pool)
        if pick in self.wardrobe:
            return dict(outfit=pick, kind="outfit", is_new=False,
                        refund=CFG.GACHA_DUP_REFUND)
        self.wardrobe.append(pick)
        return dict(outfit=pick, kind="outfit", is_new=True, refund=0)

    def skin_equip(self, skin_id: str) -> bool:
        """切换当前皮肤（只影响换装界面预览）"""
        if skin_id and skin_id not in self.skin_owned:
            return False
        self.skin_current = "" if skin_id == self.skin_current else skin_id
        return True

    def skin_has(self, skin_id: str) -> bool:
        return skin_id in self.skin_owned

    # ---------------- C13 换装 ----------------
    def equip(self, outfit_id: str) -> bool:
        """穿上/脱下；冲突（同 kind）自动替换"""
        if not outfit_id:
            for k in self.outfit:
                self.outfit[k] = ""
            return True
        spec = OUTFITS.get(outfit_id)
        if not spec or outfit_id not in self.wardrobe:
            return False
        kind = spec["kind"]
        if self.outfit.get(kind) == outfit_id:
            self.outfit[kind] = ""
        else:
            self.outfit[kind] = outfit_id
        return True

    def equipped_ids(self) -> list:
        return [v for v in self.outfit.values() if v]

    def save_preset(self, idx: int):
        preset = dict(self.outfit)
        preset["name"] = time.strftime("搭配%d", ) if False else f"搭配{idx + 1}"
        while len(self.outfit_presets) <= idx:
            self.outfit_presets.append(dict(hat="", glasses="", back="", name=""))
        self.outfit_presets[idx] = preset

    def load_preset(self, idx: int) -> bool:
        if 0 <= idx < len(self.outfit_presets):
            p = self.outfit_presets[idx]
            for k in ("hat", "glasses", "back"):
                oid = p.get(k) or ""
                self.outfit[k] = oid if oid in self.wardrobe else ""
            return True
        return False

    # ---------------- C14 家具 ----------------
    def furniture_buy(self, key: str) -> bool:
        if key in self.furniture:
            return False
        self.furniture.append(key)
        return True

    def furniture_toggle(self, key: str) -> bool:
        if key not in self.furniture:
            return False
        if key in self.placed:
            self.placed.remove(key)
        else:
            self.placed.append(key)
        return True

    def furniture_has(self, key: str) -> bool:
        return key in self.placed

    # ---------------- C15 季节 ----------------
    def season_now(self, now=None) -> str:
        if self.season_override in SEASONS:
            return self.season_override
        month = (now.tm_mon if isinstance(now, time.struct_time)
                 else time.localtime(now).tm_mon)
        for key, spec in SEASONS.items():
            if month in spec["months"]:
                return key
        return "spring"

    # ---------------- D17 天赋 ----------------
    def talent_has(self, tid: str) -> bool:
        return tid in self.talents

    def talent_effect(self, effect: str) -> float:
        """返回对应效果是否点亮（1.0 / 0.0），方便调用处相乘"""
        for tid, spec in TALENTS.items():
            if spec.get("effect") == effect and tid in self.talents:
                return 1.0
        return 0.0

    def talent_buy(self, tid: str) -> bool:
        if tid not in TALENTS or tid in self.talents or self.talent_points <= 0:
            return False
        self.talents.append(tid)
        self.talent_points -= 1
        return True

    def talent_grant(self, level: int) -> int:
        """按等级发放天赋点（5/10/15/20 各 1 点，总数不会重复发）"""
        want = sum(1 for lv in CFG.TALENT_LEVELS if level >= lv)
        give = max(0, want - self.talent_levels_given)
        if give:
            self.talent_points += give
            self.talent_levels_given += give
        return give

    # ---------------- D20 故事 ----------------
    def story_available(self, level: int) -> list:
        return [c for c in STORY_CHAPTERS
                if level >= c["level"] and c["level"] not in self.story_read]

    def story_mark(self, level: int):
        if level not in self.story_read:
            self.story_read.append(level)
            self.story_read.sort()

    # ---------------- A5 情绪 ----------------
    def emotion_detect(self, text: str):
        """返回 (情绪, 回应台词) 或 (None, None)"""
        if not text:
            return None, None
        low = str(text).lower()
        for state in ("angry", "neg", "pos"):
            words = EMOTION_WORDS[state]
            if any(w.lower() in low for w in words):
                return state, random.choice(EMOTION_REPLY[state])
        return None, None


def season_of(month: int) -> str:
    for key, spec in SEASONS.items():
        if month in spec["months"]:
            return key
    return "spring"


def festival_today(now=None):
    """今天是什么节日 → (名称, 装饰形状, 粒子形状, 祝福) 或 None
    now 可以是时间戳 / struct_time / None"""
    if isinstance(now, time.struct_time):
        t = now
    else:
        t = time.localtime(now)
    key = (t.tm_mon, t.tm_mday)
    if key in FESTIVALS:
        return FESTIVALS[key]
    ymd = time.strftime("%Y-%m-%d", t)
    for year, table in LUNAR_FESTIVALS.items():
        for lk, day in table.items():
            if day == ymd and lk in LUNAR_NAMES:
                return LUNAR_NAMES[lk]
    return None


GAMES = (("rps", "猜拳大作战", "✊", RPSGame, "三局两胜，最省时的陪伴"),
         ("catch", "接星星", "⭐", CatchGame, "60 秒接星星，方向键操作"),
         ("memory", "记忆翻牌", "🃏", MemoryGame, "12 张牌找 6 对，步数越少奖励越高"),
         ("mole", "打地鼠", "🐸", MoleGame, "30 秒点奶蛙，手快有奖"),
         ("tetris", "俄罗斯方块", "🧱", TetrisGame, "我陪你玩，还能帮你 3 次"),
         ("mine", "扫雷", "💣", MinesweeperGame, "我来当探测器，帮你闻安全区"),
         ("breakout", "弹球打砖块", "🎾", BreakoutGame, "我当挡板，你带我左右跑"))


class GameHubPanel(PanelBase):
    """小游戏选择：7 个游戏卡片 + 今日剩余次数（超出一屏可滚动）"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "玩个小游戏", (470, 440))

    def refresh(self):
        self.clear()
        cfg = CFG
        if self.pet.stats.game_double_active():
            tk.Label(self.body, text="🍀 幸运饼干生效中：今天所有游戏奖励翻倍！",
                     font=self.font_s, fg=cfg.UI_ACCENT, bg=cfg.UI_BG).pack(
                anchor="w", pady=(0, 6))
        for gid, title, emoji, cls, desc in GAMES:
            left = self.pet.stats.game_left(gid)
            card = self.make_card(self.body)
            row = tk.Frame(card, bg=cfg.UI_CARD)
            row.pack(fill="x", padx=8, pady=6)
            tk.Label(row, text=emoji, font=(self.family, 14), bg=cfg.UI_CARD,
                     width=3).pack(side="left")
            col = tk.Frame(row, bg=cfg.UI_CARD)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=title, font=self.font, bg=cfg.UI_CARD,
                     anchor="w").pack(anchor="w")
            tk.Label(col, text=desc, font=self.font_s, fg=cfg.UI_TEXT_DIM,
                     bg=cfg.UI_CARD, anchor="w").pack(anchor="w")
            tk.Label(row, text=f"今日剩 {left}/{self.pet.stats.game_limit(gid)}",
                     font=self.font_s, fg=cfg.UI_TEXT_DIM, bg=cfg.UI_CARD).pack(
                side="left", padx=6)
            btn = self.make_button(row, "开始", lambda c=cls: self.start(c),
                                   primary=left > 0)
            if left <= 0:
                btn.config(state="disabled")
            btn.pack(side="right", padx=4)
        tk.Label(self.body, text="玩游戏时奶蛙会趴着陪你看，精力消耗减半～",
                 font=self.font_s, fg=cfg.UI_TEXT_DIM, bg=cfg.UI_BG).pack(
            anchor="w", pady=(8, 0))

    def start(self, cls):
        if not self.pet.stats.game_use(cls.GAME_ID):
            self.say("今天玩够啦，明天再来吧～")
            return
        self.refresh()
        try:
            cls(self.pet.root, self.pet)
        except Exception:
            log_event("GAME", "小游戏启动失败\n" + traceback.format_exc())
            self.say("这个小游戏暂时开不了，换个试试～")


# ==============================================================================
# 12.2 第十二阶段：宠物身上的叠加装饰（装扮 / 家具 / 节日 / 季节 / 便签 / 图标）
# ==============================================================================
class ExtraOverlay:
    """
    全部用 Canvas 形状画，不依赖任何外部素材：
      · 装扮：帽子（圆帽/草帽/毛线帽/蝴蝶结/皇冠/魔法帽）、眼镜（圆框/墨镜）、背上（披风/翅膀/光环）
      · 家具：小垫子 / 小台灯 / 小帐篷（画在脚边）
      · 节日：圣诞树角/福字/月饼/粽子/爱心/烟花/旗子
      · 季节：脚下地面颜色 + 飘浮粒子（花瓣/落叶/雪花/小太阳）
      · 便签：待办小便签（前 3 条）
      · 提醒图标：小杯子 / 电池
    """

    def __init__(self, canvas, cfg):
        self.canvas = canvas
        self.cfg = cfg
        self.items = {}          # 命名图元
        self.parts = []          # 季节/节日飘浮粒子 [{id, kind, x, y, sp, ph}]
        self._cache = {}         # 状态指纹，避免每帧重画
        self._box_cache = {}     # 每个素材的轮廓比例（换素材自动重算）

    def asset_box(self, asset: str, frame) -> dict:
        """
        按素材自身的不透明轮廓算定位比例 —— 这是「每个素材单独定位」的关键。
        只用 alpha 通道的 getbbox()（C 级批量算子，不逐像素访问）。
        """
        fw = getattr(frame, "width", 0) or 1
        fh = getattr(frame, "height", 0) or 1
        key = (asset, fw, fh, id(frame))
        hit = self._box_cache.get(key)
        if hit is not None:
            return hit
        try:
            bb = frame.getchannel("A").getbbox()
        except Exception:
            bb = None
        if not bb:
            bb = (0, 0, fw, fh)
        x0, y0, x1, y1 = bb
        sil_h_px = max(1, y1 - y0)
        box = dict(
            sil_h=(y1 - y0) / float(fh),                 # 轮廓高 / 图高
            top_pad=y0 / float(fh),                      # 顶部留白占图高比例
            half_w=((x1 - x0) / 2.0) / float(fw),        # 半宽 / 图宽
            cx_off=(((x0 + x1) / 2.0) - fw / 2.0) / float(fw),
            aspect=fw / float(fh),                       # 图宽/图高
            # ---- 头顶：取轮廓最上面 32% 那一带的水平中心（帽子要压在头顶）----
            head_cx=((x0 + x1) / 2.0) / float(fw),
            head_w=((x1 - x0) / 2.0) / float(fw),
            # ---- 绿眼：没识别到就是 None ----
            eye_cx=None, eye_cy=None, eye_r=0.0, two_eyes=False,
        )
        try:
            band_bottom = min(fh, y0 + int(sil_h_px * 0.32))
            alpha = frame.getchannel("A").crop((0, y0, fw, band_bottom))
            hb = alpha.point(lambda v: 255 if v > 128 else 0).getbbox()
            if hb:
                box["head_cx"] = ((hb[0] + hb[2]) / 2.0) / float(fw)
                box["head_w"] = ((hb[2] - hb[0]) / 2.0) / float(fw)
            # 没有眼镜类装扮就跳过绿眼识别（眼镜已删除，这段只在以后加回眼镜时生效）
            if not any(v.get("kind") == "glasses" for v in OUTFITS.values()):
                self._box_cache[key] = box
                return box
            # 绿眼识别：只用 C 级算子（getchannel / ImageChops.subtract / point / getbbox）
            # 注意：这里绝不能用 rgb.split() —— 本环境 Pillow12+Py3.14 下 split() 会
            # 直接 0xC0000005 崩掉（已实测），只能用 getchannel 逐个取通道。
            rgb = frame.convert("RGB")
            gg = rgb.getchannel("G")
            rr = rgb.getchannel("R")
            bb2 = rgb.getchannel("B")
            g_minus_r = ImageChops.subtract(gg, rr)      # 绿色比红色亮 → 眼睛
            g_minus_b = ImageChops.subtract(gg, bb2)     # 排除青色（生病素材整身发青）
            _lut = [255 if v > 18 else 0 for v in range(256)]
            m1 = g_minus_r.point(_lut)
            m2 = g_minus_b.point(_lut)
            mask = ImageChops.multiply(m1, m2)
            # 只在轮廓上半部分找，避免尾巴/脚上的绿色误判
            top_lim = y0 + int(sil_h_px * 0.62)
            mask = mask.crop((0, 0, fw, top_lim))
            eb = mask.getbbox()
            if eb:
                ew, eh = eb[2] - eb[0], eb[3] - eb[1]
                er = (max(ew, eh) / 2.0) / float(fw)
                # 半径必须落在「像一只眼睛」的范围内；否则是整块身子/被手挡住，
                # 一律当识别失败，退回按头顶对称摆放（实测 sick/think/allzero/joke 会误判）
                lo, hi = self.cfg.EYE_R_MIN, self.cfg.EYE_R_MAX
                if ew >= 3 and eh >= 3 and lo <= er <= hi:
                    box["eye_cx"] = ((eb[0] + eb[2]) / 2.0) / float(fw)
                    box["eye_cy"] = ((eb[1] + eb[3]) / 2.0) / float(fh)
                    box["eye_r"] = er
                    box["two_eyes"] = ew > fw * 0.22        # 一整条很宽 → 两只眼
        except Exception:
            pass
        self._box_cache[key] = box
        return box

    # ---------------- 工具 ----------------
    def _del(self, key):
        it = self.items.pop(key, None)
        if it is not None:
            try:
                self.canvas.delete(it)
            except Exception:
                pass

    def clear_prefix(self, *prefixes):
        """按前缀清掉一整组图元（note0/note1/note2 这种带序号的必须用它，
        只删 note / note_bg 会把文字留在桌面上）"""
        for k in [k for k in list(self.items)
                  if any(k.startswith(p) for p in prefixes)]:
            self._del(k)

    def _poly(self, key, pts, **kw):
        self._del(key)
        self.items[key] = self.canvas.create_polygon(pts, smooth=True, **kw)
        return self.items[key]

    def _oval(self, key, x0, y0, x1, y1, **kw):
        self._del(key)
        self.items[key] = self.canvas.create_oval(x0, y0, x1, y1, **kw)
        return self.items[key]

    def _line(self, key, pts, **kw):
        self._del(key)
        self.items[key] = self.canvas.create_line(pts, **kw)
        return self.items[key]

    def _text(self, key, x, y, txt, **kw):
        self._del(key)
        self.items[key] = self.canvas.create_text(x, y, text=txt, **kw)
        return self.items[key]

    def _rect(self, key, x0, y0, x1, y1, **kw):
        self._del(key)
        self.items[key] = self.canvas.create_polygon(
            DesktopPet._round_rect(x0, y0, x1, y1, kw.pop("r", 3)),
            smooth=True, **kw)
        return self.items[key]

    # ---------------- 装扮 ----------------
    def draw_outfit(self, outfit: dict, cx: float, feet_y: float, pet_px: float,
                    box: dict = None, flip: bool = False, asset: str = ""):
        """
        装扮绘制：**每个素材都按它自己的轮廓重新定位**
          · box = asset_box(素材名, 当前帧)，提供轮廓顶/宽/水平偏移
          · 换素材（idle→talk→happy→sleep…）时 box 变，装扮位置立刻跟着变
          · 先清空所有装扮图元再重画 —— 否则脱下某件后旧图元会一直留在画面上
            （这就是「眼镜脱不下来」的根因）
        """
        cfg = self.cfg
        self.clear_outfit()
        if not outfit or not any(outfit.values()):
            return
        pet_px = max(40.0, float(pet_px))
        box = box or dict(sil_h=0.92, top_pad=0.06, half_w=0.45, cx_off=0.0, aspect=0.95)
        px = pet_px / 165.0                                   # 线宽/小件换算基准
        pet_w = pet_px * box["aspect"]
        sil_top = feet_y - pet_px * (1.0 - box["top_pad"])     # 轮廓最高点
        sil_h = max(20.0, pet_px * box["sil_h"])
        # 轮廓水平中心（素材本身可能不居中，翻面时镜像）
        cx_s = cx + (-1 if flip else 1) * pet_w * box["cx_off"]
        half_w = max(14.0, pet_w * box["half_w"])
        lying = box["sil_h"] < cfg.OUTFIT_LYING_RATIO
        # ---- 头顶位置：用「轮廓上部 32% 那一带」的水平中心，帽子才压在脑袋上 ----
        head_cx = cx + (-1 if flip else 1) * pet_w * (box.get("head_cx", 0.5) - 0.5)
        hat_y = sil_top + sil_h * cfg.OUTFIT_HAT_OVER
        back_y = sil_top + sil_h * cfg.OUTFIT_BACK_DEPTH
        # ---- 眼睛位置：优先用识别到的绿眼，识别不到才退回比例估算 ----
        eye_cx = head_cx
        eye_y = sil_top + sil_h * cfg.OUTFIT_EYE_DEPTH
        if box.get("eye_cx") is not None:
            eye_cx = cx + (-1 if flip else 1) * pet_w * (box["eye_cx"] - 0.5)
            eye_y = feet_y - pet_px * (1.0 - box["eye_cy"])

        # ---- 帽子 ----
        spec = OUTFITS.get(outfit.get("hat") or "") or {}
        if spec:
            shape = spec["shape"]
            if shape == "cap":
                self._oval("hat", head_cx - 21 * px, hat_y - 20 * px,
                           head_cx + 21 * px, hat_y + 4 * px,
                           fill="#e57373", outline="#b71c1c", width=2)
                self._rect("hat_brim", head_cx - 26 * px, hat_y + 1 * px,
                           head_cx + 26 * px, hat_y + 7 * px,
                           fill="#ef9a9a", outline="#b71c1c", r=2)
            elif shape == "straw":
                self._oval("hat", head_cx - 34 * px, hat_y - 1 * px,
                           head_cx + 34 * px, hat_y + 13 * px,
                           fill="#ffd54f", outline="#f9a825", width=2)
                self._oval("hat_top", head_cx - 17 * px, hat_y - 20 * px,
                           head_cx + 17 * px, hat_y + 7 * px,
                           fill="#ffe082", outline="#f9a825", width=2)
            elif shape == "beanie":
                self._oval("hat", head_cx - 19 * px, hat_y - 22 * px,
                           head_cx + 19 * px, hat_y + 5 * px,
                           fill="#90caf9", outline="#1565c0", width=2)
                self._oval("hat_pom", head_cx - 7 * px, hat_y - 32 * px,
                           head_cx + 7 * px, hat_y - 18 * px,
                           fill="#e3f2fd", outline="#1565c0")
            elif shape == "bow":
                self._poly("hat", (head_cx - 3 * px, hat_y,
                                   head_cx - 24 * px, hat_y - 15 * px,
                                   head_cx - 24 * px, hat_y + 9 * px),
                           fill="#f06292", outline="#ad1457", width=2)
                self._poly("hat2", (head_cx + 3 * px, hat_y,
                                    head_cx + 24 * px, hat_y - 15 * px,
                                    head_cx + 24 * px, hat_y + 9 * px),
                           fill="#f06292", outline="#ad1457", width=2)
            elif shape == "crown":
                self._poly("hat", (head_cx - 20 * px, hat_y + 5 * px,
                                   head_cx - 20 * px, hat_y - 15 * px,
                                   head_cx - 10 * px, hat_y - 3 * px,
                                   head_cx, hat_y - 21 * px,
                                   head_cx + 10 * px, hat_y - 3 * px,
                                   head_cx + 20 * px, hat_y - 15 * px,
                                   head_cx + 20 * px, hat_y + 5 * px),
                           fill="#ffd54f", outline="#f9a825", width=2)
                self._oval("hat_gem", head_cx - 4 * px, hat_y - 7 * px,
                           head_cx + 4 * px, hat_y + 1 * px, fill="#e53935", outline="")
            elif shape == "wizard":
                self._poly("hat", (head_cx - 22 * px, hat_y + 5 * px, head_cx,
                                   hat_y - 42 * px, head_cx + 22 * px, hat_y + 5 * px),
                           fill="#7e57c2", outline="#4527a0", width=2)
                self._oval("hat_star", head_cx - 4 * px, hat_y - 17 * px,
                           head_cx + 4 * px, hat_y - 9 * px, fill="#fff176", outline="")

        # ---- 眼镜：已按需求删除（圆框眼镜 / 小墨镜）----

        # ---- 背上 ----
        bspec = OUTFITS.get(outfit.get("back") or "") or {}
        if bspec:
            shape = bspec["shape"]
            if shape == "wing":
                for sgn, tag in ((-1, "wing_l"), (1, "wing_r")):
                    self._poly(tag, (cx_s + sgn * half_w * 0.45, back_y,
                                     cx_s + sgn * half_w * 1.35, back_y - sil_h * 0.16,
                                     cx_s + sgn * half_w * 1.10, back_y + sil_h * 0.10),
                               fill="#e1f5fe", outline="#4fc3f7", width=2)
            elif shape == "halo":
                rw = half_w * 0.62
                self._oval("back", cx_s - rw, hat_y - sil_h * 0.16,
                           cx_s + rw, hat_y - sil_h * 0.05,
                           fill="", outline="#ffd54f", width=3)

    def clear_outfit(self):
        for k in list(self.items):
            if k.startswith(("hat", "gl_", "wing", "back")):
                self._del(k)

    # ---------------- 家具 ----------------
    def draw_furniture(self, placed: list, cx: float, feet_y: float):
        self.clear_prefix("fur")        # 收起家具后必须清干净，否则会留在桌面上
        if "mat" in placed:
            self._oval("fur_mat", cx - 34, feet_y - 6, cx + 34, feet_y + 10,
                       fill="#a1887f", outline="#795548")
        if "tent" in placed:
            self._poly("fur_tent", (cx + 30, feet_y + 8, cx + 46, feet_y - 26,
                                    cx + 62, feet_y + 8),
                       fill="#ffe0b2", outline="#ef6c00")
        if "lamp" in placed:
            self._line("fur_lamp_pole", (cx - 46, feet_y + 8, cx - 46, feet_y - 22),
                       fill="#607d8b", width=3)
            self._oval("fur_lamp_shade", cx - 56, feet_y - 36, cx - 36, feet_y - 20,
                       fill="#fff59d", outline="#fbc02d")

    # ---------------- 节日装饰 ----------------
    def draw_festival(self, fest, cx: float, feet_y: float):
        self.clear_prefix("fest")
        if not fest:
            return
        name, shape, _p, _line = fest
        if shape == "christmas":
            self._poly("fest", (cx + 40, feet_y + 8, cx + 52, feet_y - 24,
                                cx + 64, feet_y + 8), fill="#2e7d32", outline="#1b5e20")
            self._oval("fest2", cx + 46, feet_y - 30, cx + 58, feet_y - 18,
                       fill="#ffd54f", outline="")
        elif shape == "fu":
            self._rect("fest", cx + 34, feet_y - 34, cx + 62, feet_y - 6,
                       fill="#e53935", outline="#b71c1c", r=4)
            self._text("fest2", cx + 48, feet_y - 20, "福", fill="#ffd54f",
                       font=("Microsoft YaHei UI", 13, "bold"))
        elif shape == "moon":
            self._oval("fest", cx + 36, feet_y - 40, cx + 64, feet_y - 12,
                       fill="#fff59d", outline="#fbc02d")
        elif shape == "zongzi":
            self._poly("fest", (cx + 34, feet_y - 6, cx + 48, feet_y - 34,
                                cx + 62, feet_y - 6), fill="#8d6e63", outline="#4e342e")
        elif shape == "heart":
            self._poly("fest", (cx + 48, feet_y - 10, cx + 36, feet_y - 24,
                                cx + 48, feet_y - 34, cx + 60, feet_y - 24),
                       fill="#ef5350", outline="#b71c1c")
        elif shape == "firework":
            for i, ang in enumerate(range(0, 360, 45)):
                import math as _m
                r = 12
                x2 = cx + 48 + r * _m.cos(_m.radians(ang))
                y2 = feet_y - 24 + r * _m.sin(_m.radians(ang))
                self._line(f"fest{i}", (cx + 48, feet_y - 24, x2, y2),
                           fill="#ffb300", width=2)
        elif shape == "flag":
            self._line("fest", (cx + 40, feet_y + 8, cx + 40, feet_y - 34),
                       fill="#795548", width=2)
            self._poly("fest2", (cx + 41, feet_y - 34, cx + 64, feet_y - 28,
                                 cx + 41, feet_y - 20), fill="#e53935", outline="")

    # ---------------- 地面（季节色） ----------------
    def draw_ground(self, season: str, cx: float, feet_y: float):
        spec = SEASONS.get(season) or SEASONS["spring"]
        col = spec["ground"]
        self._oval("ground", cx - 40, feet_y - 3, cx + 40, feet_y + 9,
                   fill=col, outline="")
        self.canvas.tag_lower(self.items["ground"])

    # ---------------- 便签 ----------------
    def draw_todo_note(self, lines: list, cx: float, feet_y: float):
        # ★ 关键：note0/note1/note2 是带序号的文字图元，必须整组清，
        #   否则全部完成或删光后文字会一直留在桌面上（本次修复的问题）。
        self.clear_prefix("note")
        if not lines:
            return
        x0, y0 = cx + 46, feet_y - 74
        x1, y1 = x0 + 96, y0 + 14 + 15 * len(lines)
        self._rect("note_bg", x0, y0, x1, y1, fill="#fff9c4", outline="#f0c419", r=3)
        for i, t in enumerate(lines[:3]):
            self._text(f"note{i}", x0 + 6, y0 + 12 + 15 * i, f"· {t}"[:14],
                       anchor="w", fill="#795548",
                       font=("Microsoft YaHei UI", 8))

    # ---------------- 提醒图标 ----------------
    def draw_icon(self, kind: str, cx: float, feet_y: float):
        """kind: cup / battery"""
        if not kind:
            return
        y = feet_y - self.cfg.PET_SIZE * 0.5
        if kind == "cup":
            self._rect("icon", cx - 40, y - 12, cx - 18, y + 12,
                       fill="#b3e5fc", outline="#0288d1", r=3)
            self._line("icon2", (cx - 40, y - 6, cx - 18, y - 6), fill="#0288d1")
        elif kind == "battery":
            self._rect("icon", cx - 44, y - 8, cx - 14, y + 8,
                       fill="#fff59d", outline="#f9a825", r=2)
            self._rect("icon2", cx - 14, y - 4, cx - 10, y + 4,
                       fill="#f9a825", outline="", r=1)
            self._text("icon3", cx - 29, y, "低", fill="#e65100",
                       font=("Microsoft YaHei UI", 8, "bold"))

    def clear_icons(self):
        for k in ("icon", "icon2", "icon3"):
            self._del(k)

    def clear_parts(self):
        for p in self.parts:
            try:
                self.canvas.delete(p["id"])
            except Exception:
                pass
        self.parts = []

    # ---------------- 季节/节日飘浮粒子 ----------------
    def update_particles(self, now: float, kind: str, cx: float):
        """kind: petal/leaf/snow/sun/star/heart/firecracker"""
        want = {"petal": "#ffb7d5", "leaf": "#d7a86e", "snow": "#ffffff",
                "sun": "#ffe082", "star": "#ffd54f", "heart": "#ef9a9a",
                "firecracker": "#e53935"}.get(kind, "#ffb7d5")
        if len(self.parts) < 6 and random.random() < 0.04:
            x = random.uniform(10, self.cfg.WIN_W - 10)
            y = random.uniform(10, self.cfg.BUBBLE_ZONE)
            if kind == "snow":
                pid = self.canvas.create_oval(x, y, x + 4, y + 4,
                                              fill=want, outline="")
            elif kind == "petal":
                pid = self.canvas.create_oval(x, y, x + 7, y + 4,
                                              fill=want, outline="")
            elif kind == "leaf":
                pid = self.canvas.create_polygon(
                    x, y, x + 8, y + 3, x, y + 7, smooth=True,
                    fill=want, outline="")
            else:
                pid = self.canvas.create_text(x, y, text="✦", fill=want,
                                              font=("Microsoft YaHei UI", 9))
            self.parts.append(dict(id=pid, kind=kind, x=x, y=y,
                                   sp=random.uniform(8, 22),
                                   ph=random.uniform(0, 6.28)))
        for p in list(self.parts):
            p["y"] += p["sp"] * 0.02
            if p["y"] > self.cfg.BUBBLE_ZONE + 40:
                try:
                    self.canvas.delete(p["id"])
                except Exception:
                    pass
                self.parts.remove(p)
                continue
            dx = math.sin(now + p["ph"]) * 6
            try:
                self.canvas.coords(p["id"], p["x"] + dx, p["y"])
            except Exception:
                pass


# ==============================================================================
# 12.3 第十二阶段：新功能的窗口（日记 / 图鉴 / 换装 / 小窝 / 天赋 / 故事 / 记忆 / 待办 / 系统 / 扭蛋 / 提醒）
# ==============================================================================
class DiaryPanel(PanelBase):
    """A1 日记本：月历视图 + 点击查看当天日记"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        self.ym = time.localtime()[:2]
        self.picked = time.strftime("%Y-%m-%d")
        super().__init__(master, pet, "奶蛙日记", (520, 470))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        y, m = self.ym
        head = tk.Frame(self.body, bg=CFG.UI_BG)
        head.pack(fill="x")
        self.make_button(head, "‹", lambda: self._shift(-1)).pack(side="left")
        tk.Label(head, text=f"{y} 年 {m} 月", font=self.font, bg=CFG.UI_BG,
                 fg=CFG.UI_TEXT).pack(side="left", padx=10)
        self.make_button(head, "›", lambda: self._shift(1)).pack(side="left")
        tk.Label(head, text=f"共 {ex.diary_count()} 篇", font=self.font_s,
                 fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(side="right")

        # 日历网格
        grid = tk.Frame(self.body, bg=CFG.UI_BG)
        grid.pack(fill="x", pady=6)
        for i, wd in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            tk.Label(grid, text=wd, font=self.font_s, bg=CFG.UI_BG,
                     fg=CFG.UI_TEXT_DIM, width=4).grid(row=0, column=i)
        import calendar as _cal
        first_wd, days = _cal.monthrange(y, m)
        has = ex.diary_of_month(y, m)
        row, col = 1, first_wd
        for d in range(1, days + 1):
            date = f"{y:04d}-{m:02d}-{d:02d}"
            marked = has.get(d)
            fg = "#ffffff" if marked else CFG.UI_TEXT
            bg = CFG.UI_MAIN if marked else CFG.UI_BG
            tk.Button(grid, text=str(d), font=self.font_s, width=3, relief="flat",
                      bg=bg, fg=fg, activebackground=CFG.UI_ACCENT,
                      cursor="hand2" if marked else "arrow",
                      command=(lambda dd=date: self._pick(dd)) if marked else None
                      ).grid(row=row, column=col, padx=1, pady=1)
            col += 1
            if col > 6:
                col, row = 0, row + 1

        # 选中那天
        item = next((d for d in ex.diary if d.get("date") == self.picked), None)
        card = self.make_card(self.body)
        if item:
            mood = item.get("mood", "normal")
            face = {"pos": "😊", "neg": "🥺", "angry": "😣"}.get(mood, "🙂")
            tk.Label(card, text=f"{face}  {item['date']}", font=self.font,
                     bg=CFG.UI_CARD, anchor="w").pack(anchor="w", padx=8, pady=(6, 2))
            tk.Label(card, text=item.get("content", ""), font=self.font_s,
                     bg=CFG.UI_CARD, fg=CFG.UI_TEXT, justify="left", anchor="w",
                     wraplength=440).pack(anchor="w", padx=8, pady=(0, 8))
        else:
            tk.Label(card, text="这一天还没写日记～（点有颜色的日期看看）",
                     font=self.font_s, bg=CFG.UI_CARD, fg=CFG.UI_TEXT_DIM).pack(
                anchor="w", padx=8, pady=8)
        self.scroll_to_top()

    def _shift(self, delta: int):
        y, m = self.ym
        m += delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self.ym = (y, m)
        self.refresh()

    def _pick(self, date: str):
        self.picked = date
        self.refresh()


class CodexPanel(PanelBase):
    """C11 图鉴：动物 / 物品 / 地点 三页"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        self.page = "animal"
        super().__init__(master, pet, "图鉴", (520, 500))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        tabs = tk.Frame(self.body, bg=CFG.UI_BG)
        tabs.pack(fill="x", pady=(0, 6))
        names = {"animal": "🐾 动物", "item": "🎁 物品", "place": "🗺️ 地点"}
        for key in CFG.CODEX_PAGES:
            got = len(ex.codex.get(key) or [])
            total = len(self._entries(key))
            b = self.make_button(tabs, f"{names[key]} {got}/{total}",
                                 lambda k=key: self._tab(k),
                                 primary=(key == self.page))
            b.pack(side="left", padx=2)
        grid = tk.Frame(self.body, bg=CFG.UI_BG)
        grid.pack(fill="both", expand=True)
        for i, (key, name, desc) in enumerate(self._entries(self.page)):
            got = ex.codex_has(self.page, key)
            cell = tk.Frame(grid, bg=CFG.UI_CARD, highlightbackground=CFG.UI_LINE,
                            highlightthickness=1)
            cell.grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky="nsew")
            tk.Label(cell, text=(name if got else "❔"),
                     font=(self.family, 10, "bold"), bg=CFG.UI_CARD,
                     fg=(CFG.UI_TEXT if got else "#bbbbbb")).pack(pady=(6, 0))
            tk.Label(cell, text=(desc if got else "？"),
                     font=(self.font_s[0], 8), bg=CFG.UI_CARD,
                     fg=(CFG.UI_TEXT_DIM if got else "#cccccc"),
                     wraplength=140, justify="left").pack(padx=4, pady=(0, 4))
            if got:
                when = ex.codex_time.get(f"{self.page}:{key}", "")
                tk.Label(cell, text=when, font=(self.font_s[0], 7), bg=CFG.UI_CARD,
                         fg=CFG.UI_TEXT_DIM).pack(pady=(0, 4))
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1)
        # 集齐整页奖励
        got = len(ex.codex.get(self.page) or [])
        total = len(self._entries(self.page))
        if total and got >= total:
            self.footer.config(text=f"🏆 这一页集齐啦！去领奖励吧（金币 +{CFG.CODEX_REWARD_COINS}）")
        self.scroll_to_top()

    def _tab(self, key):
        self.page = key
        self.refresh()

    def _entries(self, page):
        if page == "animal":
            return [(a, a, "探险时遇见的伙伴") for a in CDEX_ANIMALS]
        if page == "item":
            out = []
            for name, spec in list(ITEMS.items()) + list(MATERIALS.items()):
                out.append((name, f"{spec.get('emoji', '')}{name}",
                            spec.get("desc", "")))
            return out
        return [(k, v.get("name", k), v.get("desc", ""))
                for k, v in ADVENTURE_SPOTS.items()]


# 图鉴里的动物清单（探险可能遇到的伙伴）
CDEX_ANIMALS = ("小松鼠", "蝴蝶", "麻雀", "野猫", "萤火虫", "小刺猬",
                "鸭子", "兔子", "蜻蜓", "小鹿")


class WardrobePanel(PanelBase):
    """C13 换装小屋：左边预览，右边已拥有装扮"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "换装小屋", (520, 520))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        top = tk.Frame(self.body, bg=CFG.UI_BG)
        top.pack(fill="x")
        tk.Label(top, text=f"已拥有 {len(ex.wardrobe)}/{len(OUTFITS)} 件装扮",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(side="left")
        self.make_button(top, "🎰 去扭蛋", self._goto_gacha).pack(side="right")
        # ★ 实时预览：左边把宠物和当前装扮一起画出来（规格要求，之前漏了）
        pv = tk.Frame(self.body, bg=CFG.UI_CARD, highlightbackground=CFG.UI_LINE,
                      highlightthickness=1)
        pv.pack(pady=6)
        pv_canvas = tk.Canvas(pv, width=210, height=190, bg=CFG.UI_CARD,
                              highlightthickness=0)
        pv_canvas.pack()
        self._draw_preview(pv_canvas, 105, 176, 140)
        tk.Label(pv, text="↑ 试穿效果预览（只在这里看，不会戴到桌面奶蛙身上）",
                 font=(self.font_s[0], 8), fg=CFG.UI_TEXT_DIM,
                 bg=CFG.UI_CARD).pack(pady=(0, 4))
        # ★ 皮肤区（含获取方式说明）
        skin_total = sum(v["rate"] for v in SKINS.values())
        tk.Label(self.body, text=f"🐸 皮肤（{len(ex.skin_owned)}/{len(SKINS)}）",
                 font=self.font, bg=CFG.UI_BG, fg=CFG.UI_MAIN).pack(anchor="w",
                                                                   pady=(6, 0))
        tk.Label(self.body,
                 text=f"获取方式：🛒 商店 → 🎰 扭蛋机抽取（{CFG.GACHA_PRICE} 金币/次）。"
                      f"前四款各 {SKINS[SKIN_IDS[0]]['rate'] * 100:.0f}%，"
                      f"{SKINS[SKIN_IDS[-1]]['name']} {SKINS[SKIN_IDS[-1]]['rate'] * 100:.0f}%，"
                      f"与装扮一起算在同一个奖池里（皮肤合计 {skin_total * 100:.0f}%）；"
                      f"重复获得返还 {CFG.GACHA_DUP_REFUND} 金币。\n"
                      f"皮肤只改变这里的预览，不会显示到桌面上的奶蛙身上。",
                 font=(self.font_s[0], 8), fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG,
                 justify="left", wraplength=460).pack(anchor="w", pady=(0, 4))
        for sid in SKIN_IDS:
            spec = SKINS[sid]
            owned = ex.skin_has(sid)
            row = self.make_card(self.body)
            tk.Label(row, text="★" if sid == SKIN_IDS[-1] else "🎨",
                     font=(self.family, 10), bg=CFG.UI_CARD).pack(side="left",
                                                                  padx=(8, 2))
            tk.Label(row, text=spec["name"], font=self.font, bg=CFG.UI_CARD,
                     width=10, anchor="w",
                     fg=(CFG.UI_TEXT if owned else "#b0b0b0")).pack(side="left")
            tk.Label(row, text=f"{spec['rate'] * 100:.0f}%", font=self.font_s,
                     bg=CFG.UI_CARD, fg="#f39c12", width=4).pack(side="left")
            tk.Label(row, text=spec["desc"], font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_CARD, anchor="w", wraplength=180,
                     justify="left").pack(side="left", fill="x", expand=True)
            if owned:
                using = ex.skin_current == sid
                self.make_button(row, "脱下" if using else "换上",
                                 lambda s=sid: self._use_skin(s),
                                 primary=not using).pack(side="right", padx=6)
            else:
                tk.Label(row, text="未获得", font=self.font_s, fg="#b0b0b0",
                         bg=CFG.UI_CARD).pack(side="right", padx=8)

        # 当前穿戴
        cur = tk.Frame(self.body, bg=CFG.UI_BG)
        cur.pack(fill="x", pady=6)
        _skin_name = (SKINS[ex.skin_current]["name"]
                      if ex.skin_current in SKINS else "（原色）")
        tk.Label(cur, text=f"皮肤：{_skin_name}", font=self.font_s,
                 bg=CFG.UI_BG, fg=CFG.UI_TEXT).pack(side="left", padx=(0, 12))
        for kind, label in (("hat", "帽子"), ("back", "背上")):
            oid = ex.outfit.get(kind) or ""
            name = OUTFITS[oid]["name"] if oid in OUTFITS else "（没戴）"
            tk.Label(cur, text=f"{label}：{name}", font=self.font_s,
                     bg=CFG.UI_BG, fg=CFG.UI_TEXT).pack(side="left", padx=(0, 12))
        if not ex.wardrobe:
            tk.Label(self.body, text="还没有装扮～先去商店扭个蛋吧",
                     font=self.font, bg=CFG.UI_BG).pack(anchor="w", pady=10)
            return
        for oid in ex.wardrobe:
            spec = OUTFITS.get(oid) or {}
            row = self.make_card(self.body)
            tk.Label(row, text=f"{OUTFIT_TIER_NAME.get(spec.get('tier'), '普通')}",
                     font=self.font_s, bg=CFG.UI_CARD, width=4,
                     fg=OUTFIT_TIER_COLOR.get(spec.get("tier"), "#888")).pack(
                side="left", padx=(8, 4))
            tk.Label(row, text=spec.get("name", oid), font=self.font, bg=CFG.UI_CARD,
                     width=9, anchor="w").pack(side="left")
            tk.Label(row, text=spec.get("desc", ""), font=self.font_s,
                     fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD, anchor="w",
                     wraplength=240).pack(side="left", fill="x", expand=True)
            worn = ex.outfit.get(spec.get("kind")) == oid
            self.make_button(row, "脱下" if worn else "穿上",
                             lambda o=oid: self._wear(o),
                             primary=not worn).pack(side="right", padx=6)
        # 搭配方案
        pr = tk.Frame(self.body, bg=CFG.UI_BG)
        pr.pack(fill="x", pady=(8, 0))
        tk.Label(pr, text="搭配方案：", font=self.font_s, fg=CFG.UI_TEXT_DIM,
                 bg=CFG.UI_BG).pack(side="left")
        for i in range(3):
            self.make_button(pr, f"存{i + 1}",
                             lambda k=i: self._save(k)).pack(side="left", padx=1)
            self.make_button(pr, f"换{i + 1}",
                             lambda k=i: self._load(k)).pack(side="left", padx=1)
        self.scroll_to_top()

    def _skin_image(self, skin_id: str):
        """读皮肤素材（带缓存；只在换装界面用，不参与桌面渲染）"""
        cache = getattr(self.pet, "_skin_cache", None)
        if cache is None:
            cache = {}
            self.pet._skin_cache = cache
        if skin_id in cache:
            return cache[skin_id]
        spec = SKINS.get(skin_id)
        if not spec:
            return None
        # 皮肤素材放在 assets/skins/ 下（脚本目录为基准，兼容打包后路径）
        path = os.path.join(app_dir(), SKIN_DIR, spec["file"])
        if not os.path.isfile(path):
            path = os.path.join(SKIN_DIR, spec["file"])
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            log_event("SKIN", f"皮肤素材读不到：{path}")
            return None
        cache[skin_id] = img
        return img

    def _preview_base(self, pet_h: int):
        """预览底图：有皮肤就用皮肤素材，否则用平常的 idle 素材"""
        ex = self.pet.stats.extra
        if ex.skin_current and ex.skin_has(ex.skin_current):
            img = self._skin_image(ex.skin_current)
            if img is not None:
                w = max(1, int(round(img.width * pet_h / img.height)))
                return img.resize((w, pet_h), RES_BICUBIC), True
        frames = self.pet.assets.get("idle") or self.pet.assets.get("talk") or []
        if not frames:
            return None, False
        img = frames[0].convert("RGBA")
        w = max(1, int(round(img.width * pet_h / img.height)))
        return img.resize((w, pet_h), RES_BICUBIC), False

    def _draw_preview(self, canvas, cx: float, feet_y: float, pet_h: int):
        """在面板里画出「宠物（当前皮肤）+ 当前装扮」的小预览"""
        try:
            small, is_skin = self._preview_base(pet_h)
            if small is None:
                return
            photo = ImageTk.PhotoImage(small, master=canvas)
            canvas.create_image(cx, feet_y, image=photo, anchor="s")
            canvas._photo_ref = photo            # 防 GC
            ov = ExtraOverlay(canvas, CFG)
            ex = self.pet.stats.extra
            box = ov.asset_box("skin" if is_skin else "idle", small)
            ov.draw_outfit(ex.outfit, cx, feet_y, float(pet_h), box=box,
                           asset="skin" if is_skin else "idle")
            ov.draw_ground(ex.season_now(), cx, feet_y)
            canvas.tag_lower(ov.items["ground"])
        except Exception:
            log_event("EXTRA", "预览绘制失败\n" + traceback.format_exc())

    def _use_skin(self, sid: str):
        ex = self.pet.stats.extra
        if not ex.skin_has(sid):
            self.say("还没抽到这款皮肤哦～去商店扭蛋试试")
            return
        ex.skin_equip(sid)
        on = ex.skin_current == sid
        self.say(f"换上「{SKINS[sid]['name']}」啦" if on else "换回原来的颜色啦")
        self.pet.brain.show_text(f"好看吗？～（{SKINS[sid]['name']}）" if on
                                 else "还是原来的颜色～", 2.4)
        self.pet.autosave(force=True)
        self.refresh()

    def _wear(self, oid):
        ex = self.pet.stats.extra
        ex.equip(oid)
        self.pet.brain.show_text("好看吗？～", 2.4)
        self.pet.autosave(force=True)
        self.refresh()

    def _save(self, i):
        self.pet.stats.extra.save_preset(i)
        self.say(f"搭配 {i + 1} 已保存～")
        self.pet.autosave(force=True)
        self.refresh()

    def _load(self, i):
        ok = self.pet.stats.extra.load_preset(i)
        self.say("换上这套啦～" if ok else "这套还没保存过哦")
        self.pet.autosave(force=True)
        self.refresh()

    def _goto_gacha(self):
        self.destroy()
        try:
            self.pet.open_gacha()          # 原来错传 open_shop(gacha=True)，签名不收参数 → 按钮点了没反应
        except Exception:
            log_event("EXTRA", traceback.format_exc())


class HomePanel(PanelBase):
    """C14 我的小窝：家具仓库 + 摆放"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "我的小窝", (480, 420))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        tk.Label(self.body, text="家具会悄悄帮到你哦：",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w")
        for key, spec in FURNITURE.items():
            row = self.make_card(self.body)
            owned = key in ex.furniture
            placed = key in ex.placed
            tk.Label(row, text=spec["emoji"], font=(self.family, 14),
                     bg=CFG.UI_CARD).pack(side="left", padx=(8, 4))
            col = tk.Frame(row, bg=CFG.UI_CARD)
            col.pack(side="left", fill="x", expand=True, pady=4)
            tk.Label(col, text=spec["name"], font=self.font, bg=CFG.UI_CARD,
                     anchor="w").pack(anchor="w")
            tk.Label(col, text=spec["desc"], font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_CARD, anchor="w").pack(anchor="w")
            if owned:
                self.make_button(row, "收起" if placed else "摆上",
                                 lambda k=key: self._toggle(k),
                                 primary=not placed).pack(side="right", padx=6)
            else:
                self.make_button(row, f"购买 {spec['price']}币",
                                 lambda k=key: self._buy(k)).pack(side="right", padx=6)
        self.footer.config(text=f"金币 {self.pet.stats.coins}")
        self.scroll_to_top()

    def _buy(self, key):
        s = self.pet.stats
        spec = FURNITURE[key]
        if s.coins < spec["price"]:
            self.say("金币不够呀…")
            return
        s.add_coins(-spec["price"])
        s.extra.furniture_buy(key)
        s.extra.furniture_toggle(key)
        self.say(f"「{spec['name']}」摆好啦！")
        self.pet.autosave(force=True)
        self.refresh()

    def _toggle(self, key):
        self.pet.stats.extra.furniture_toggle(key)
        self.pet.autosave(force=True)
        self.refresh()


class TalentPanel(PanelBase):
    """D17 天赋树：三支 × 三节点"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "天赋树", (560, 480))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        top = tk.Frame(self.body, bg=CFG.UI_BG)
        top.pack(fill="x")
        tk.Label(top, text=f"可用天赋点 {ex.talent_points}", font=self.font_b,
                 fg=CFG.UI_ACCENT, bg=CFG.UI_BG).pack(side="left")
        tk.Label(top, text=f"（Lv.{'/'.join(str(l) for l in CFG.TALENT_LEVELS)} 各得 1 点）",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(
            side="left", padx=8)
        cols = tk.Frame(self.body, bg=CFG.UI_BG)
        cols.pack(fill="both", expand=True, pady=6)
        for branch in TALENT_BRANCHES:
            box = tk.Frame(cols, bg=CFG.UI_BG)
            box.pack(side="left", fill="both", expand=True, padx=3)
            tk.Label(box, text=branch, font=self.font, bg=CFG.UI_BG,
                     fg=CFG.UI_MAIN).pack(pady=(0, 4))
            for tid, spec in TALENTS.items():
                if spec["branch"] != branch:
                    continue
                owned = ex.talent_has(tid)
                locked = self.pet.stats.level < spec["need_level"]
                card = tk.Frame(box, bg=CFG.UI_CARD, highlightbackground=CFG.UI_LINE,
                                highlightthickness=1)
                card.pack(fill="x", pady=3)
                tk.Label(card, text=("✅ " if owned else "🔒 " if locked else "◻ ") +
                         spec["name"], font=self.font_s, bg=CFG.UI_CARD,
                         fg=(CFG.UI_MAIN if owned else CFG.UI_TEXT),
                         wraplength=150, justify="left").pack(anchor="w", padx=6, pady=(4, 0))
                tk.Label(card, text=spec["desc"], font=(self.font_s[0], 8),
                         fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD, wraplength=150,
                         justify="left").pack(anchor="w", padx=6)
                tk.Label(card, text=f"需要 Lv.{spec['need_level']}",
                         font=(self.font_s[0], 7), fg=CFG.UI_TEXT_DIM,
                         bg=CFG.UI_CARD).pack(anchor="w", padx=6, pady=(0, 4))
                if not owned and not locked:
                    self.make_button(card, "点亮", lambda t=tid: self._buy(t),
                                     primary=ex.talent_points > 0).pack(
                        anchor="e", padx=6, pady=(0, 5))
        if CFG.TALENT_RESPEC_ALLOWED:
            self.make_button(self.body, f"洗点（{CFG.TALENT_RESPEC_PRICE} 金币）",
                             self._respec).pack(anchor="w", pady=(6, 0))
        self.scroll_to_top()

    def _buy(self, tid):
        ex = self.pet.stats.extra
        if ex.talent_points <= 0:
            self.say("没有天赋点啦，再升升级吧～")
            return
        if ex.talent_buy(tid):
            self.say(f"点亮「{TALENTS[tid]['name']}」！")
            self.pet.autosave(force=True)
            self.refresh()

    def _respec(self):
        s, ex = self.pet.stats, self.pet.stats.extra
        if not ex.talents:
            self.say("还没点过天赋呢")
            return
        if s.coins < CFG.TALENT_RESPEC_PRICE:
            self.say("金币不够洗点呀…")
            return
        s.add_coins(-CFG.TALENT_RESPEC_PRICE)
        ex.talent_points += len(ex.talents)
        ex.talents = []
        self.say("天赋都退回来啦，重新点吧～")
        self.pet.autosave(force=True)
        self.refresh()


class StoryPanel(PanelBase):
    """D20 主线故事：已解锁章节可回看"""

    SCROLLABLE = True

    def __init__(self, master, pet, chapter=None):
        self.chapter = chapter
        super().__init__(master, pet, "故事", (520, 460))

    def refresh(self):
        self.clear()
        s = self.pet.stats
        ex = s.extra
        if self.chapter is not None:
            c = self.chapter
            card = self.make_card(self.body)
            tk.Label(card, text=c["title"], font=self.font_b, bg=CFG.UI_CARD,
                     fg=CFG.UI_MAIN).pack(anchor="w", padx=10, pady=(8, 4))
            tk.Label(card, text=c["text"], font=self.font, bg=CFG.UI_CARD,
                     justify="left", anchor="w", wraplength=450).pack(
                anchor="w", padx=10, pady=(0, 10))
            self.make_button(self.body, "← 返回目录",
                             lambda: self._back()).pack(anchor="w", pady=6)
            self.scroll_to_top()
            return
        tk.Label(self.body, text=f"当前 Lv.{s.level}　"
                                 f"已读 {len(ex.story_read)}/{len(STORY_CHAPTERS)} 章",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w")
        for c in STORY_CHAPTERS:
            read = c["level"] in ex.story_read
            unlocked = s.level >= c["level"]
            row = self.make_card(self.body)
            tk.Label(row, text=c["title"], font=self.font, bg=CFG.UI_CARD,
                     fg=(CFG.UI_TEXT if unlocked else "#bbbbbb"),
                     anchor="w").pack(side="left", padx=8, pady=6)
            tk.Label(row, text=f"Lv.{c['level']}", font=self.font_s,
                     fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD).pack(side="left")
            if unlocked:
                self.make_button(row, "回看" if read else "阅读",
                                 lambda ch=c: self._open(ch)).pack(side="right", padx=6)
            else:
                tk.Label(row, text="未解锁", font=self.font_s, fg="#bbbbbb",
                         bg=CFG.UI_CARD).pack(side="right", padx=8)
        self.scroll_to_top()

    def _open(self, ch):
        self.pet.stats.extra.story_mark(ch["level"])
        self.pet.autosave(force=True)
        self.chapter = ch
        self.refresh()

    def _back(self):
        self.chapter = None
        self.refresh()


class MemoryPanel(PanelBase):
    """A4 记忆库：查看 / 删除它记住的事"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "记忆库", (480, 440))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        tk.Label(self.body, text="奶蛙记住的关于你的事（可以随时删掉）：",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w")
        if not ex.memory:
            tk.Label(self.body, text="还什么都没记住呢～多和它聊聊吧",
                     font=self.font, bg=CFG.UI_BG).pack(anchor="w", pady=10)
            return
        for i, m in enumerate(ex.memory):
            row = self.make_card(self.body)
            tk.Label(row, text=m.get("topic", "?"), font=self.font, bg=CFG.UI_CARD,
                     width=7, anchor="w").pack(side="left", padx=(8, 0))
            col = tk.Frame(row, bg=CFG.UI_CARD)
            col.pack(side="left", fill="x", expand=True, pady=4)
            tk.Label(col, text=m.get("content", ""), font=self.font_s, bg=CFG.UI_CARD,
                     anchor="w", wraplength=270, justify="left").pack(anchor="w")
            tk.Label(col, text=m.get("time", ""), font=(self.font_s[0], 7),
                     fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD).pack(anchor="w")
            self.make_button(row, "忘掉", lambda k=i: self._del(k)).pack(
                side="right", padx=6)
        self.scroll_to_top()

    def _del(self, idx):
        self.pet.stats.extra.memory_delete(idx)
        self.say("好，这件事我忘掉啦")
        self.pet.autosave(force=True)
        self.refresh()


class TodoPanel(PanelBase):
    """B8 待办贴：添加 / 打勾 / 删除"""

    SCROLLABLE = True

    def __init__(self, master, pet):
        super().__init__(master, pet, "待办贴", (460, 440))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        add = tk.Frame(self.body, bg=CFG.UI_BG)
        add.pack(fill="x", pady=(0, 6))
        self.entry = tk.Entry(add, font=self.font, bg=CFG.UI_CARD, relief="flat",
                              highlightthickness=1, highlightbackground=CFG.UI_LINE)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry.bind("<Return>", lambda e: self._add())
        self.make_button(add, "添加", self._add, primary=True).pack(side="left", padx=6)
        pend = ex.todo_pending()
        tk.Label(self.body, text=f"未完成 {len(pend)} 条 / 共 {len(ex.todo)} 条",
                 font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_BG).pack(anchor="w")
        if not ex.todo:
            tk.Label(self.body, text="还没有待办～加一条试试",
                     font=self.font, bg=CFG.UI_BG).pack(anchor="w", pady=10)
            return
        for i, t in enumerate(ex.todo):
            row = self.make_card(self.body)
            done = bool(t.get("done"))
            box = tk.Button(row, text="☑" if done else "☐", font=(self.family, 12),
                            relief="flat", bg=CFG.UI_CARD,
                            fg=(CFG.UI_MAIN if done else "#9e9e9e"),
                            cursor="hand2", command=lambda k=i: self._toggle(k))
            box.pack(side="left", padx=(6, 2))
            tk.Label(row, text=t.get("text", ""), font=self.font, bg=CFG.UI_CARD,
                     anchor="w", wraplength=250, justify="left",
                     fg=("#aaaaaa" if done else CFG.UI_TEXT)).pack(
                side="left", fill="x", expand=True, pady=5)
            self.make_button(row, "删", lambda k=i: self._del(k)).pack(
                side="right", padx=6)
        self.scroll_to_top()

    def _add(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.pet.stats.extra.todo_add(text)
        self.entry.delete(0, "end")
        self.pet.autosave(force=True)
        self.refresh()

    def _toggle(self, i):
        ex = self.pet.stats.extra
        ex.todo_toggle(i)
        if ex.todo and not ex.todo_pending():
            today = time.strftime("%Y-%m-%d")
            if ex.todo_all_done_date != today:
                ex.todo_all_done_date = today
                self.pet.stats.bond = min(CFG.BOND_MAX,
                                          self.pet.stats.bond + CFG.TODO_ALL_BOND)
                self.pet.brain.set_act(Act.HAPPY, 4.0, "待办全清空啦！亲密度 +10", 3.4)
        self.pet.autosave(force=True)
        self.refresh()

    def _del(self, i):
        self.pet.stats.extra.todo_del(i)
        self.pet.autosave(force=True)
        self.refresh()


class SystemPanel(PanelBase):
    """B9 系统状态：CPU / 内存 / 电池"""

    def __init__(self, master, pet):
        super().__init__(master, pet, "系统状态", (420, 340))

    def refresh(self):
        self.clear()
        info = self.pet.sys_info or {}
        rows = (("CPU 占用", f"{info.get('cpu', 0):.1f}%"),
                ("内存占用", f"{info.get('mem', 0):.1f}%"
                             f"（{info.get('mem_used', 0):.1f} GB / "
                             f"{info.get('mem_total', 0):.1f} GB）"),
                ("电池电量", (f"{info.get('battery', -1)}%"
                              f"{'　充电中' if info.get('charging') else ''}"
                              if info.get('battery', -1) >= 0 else "没有电池（台式机）")),
                ("采样时间", info.get("at", "--")))
        for label, val in rows:
            row = self.make_card(self.body)
            tk.Label(row, text=label, font=self.font_s, fg=CFG.UI_TEXT_DIM,
                     bg=CFG.UI_CARD, width=8, anchor="w").pack(side="left", padx=8,
                                                               pady=6)
            tk.Label(row, text=val, font=self.font, bg=CFG.UI_CARD,
                     anchor="w").pack(side="left", fill="x", expand=True)
        self.make_button(self.body, "立刻刷新", self._sample).pack(anchor="w", pady=8)

    def _sample(self):
        try:
            self.pet.sample_system(force=True)
        except Exception:
            pass
        self.refresh()


class ReminderPanel(PanelBase):
    """B7 提醒设置：喝水 / 久坐 开关"""

    def __init__(self, master, pet):
        super().__init__(master, pet, "提醒设置", (420, 300))

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        for key, label, on, every in (
                ("water", "喝水提醒", ex.water_on, CFG.WATER_REMIND_EVERY),
                ("sit", "久坐提醒", ex.sit_on, CFG.SIT_REMIND_EVERY)):
            row = self.make_card(self.body)
            col = tk.Frame(row, bg=CFG.UI_CARD)
            col.pack(side="left", fill="x", expand=True, pady=6, padx=8)
            tk.Label(col, text=label, font=self.font, bg=CFG.UI_CARD,
                     anchor="w").pack(anchor="w")
            tk.Label(col, text=f"每 {int(every // 60)} 分钟提醒一次",
                     font=self.font_s, fg=CFG.UI_TEXT_DIM, bg=CFG.UI_CARD).pack(anchor="w")
            self.make_button(row, "关闭" if on else "开启",
                             lambda k=key: self._toggle(k),
                             primary=not on).pack(side="right", padx=8)
        self.make_button(self.body, "重置计时（我刚喝过 / 刚站起来）",
                         self._reset).pack(anchor="w", pady=8)
        self.footer.config(text="点一下奶蛙也算「我知道了」，会自动重新计时")

    def _toggle(self, key):
        ex = self.pet.stats.extra
        if key == "water":
            ex.water_on = not ex.water_on
            ex.water_t = time.time()
        else:
            ex.sit_on = not ex.sit_on
            ex.sit_t = time.time()
        self.pet.autosave(force=True)
        self.refresh()

    def _reset(self):
        ex = self.pet.stats.extra
        ex.water_t = ex.sit_t = time.time()
        self.pet.autosave(force=True)
        self.say("计时重新开始啦～")


class GachaPanel(PanelBase):
    """C12 扭蛋机：Canvas 画扭蛋机 + 2 秒动画"""

    def __init__(self, master, pet):
        super().__init__(master, pet, "扭蛋机", (420, 460))
        self.anim_until = 0.0

    def refresh(self):
        self.clear()
        ex = self.pet.stats.extra
        c = tk.Canvas(self.body, width=340, height=230, bg=CFG.UI_BG,
                      highlightthickness=0)
        c.pack()
        self.canvas = c
        # 扭蛋机：机柜 + 玻璃球舱 + 出蛋口
        c.create_polygon(DesktopPet._round_rect(110, 40, 230, 190, 14),
                         smooth=True, fill="#ef5350", outline="#b71c1c", width=2)
        c.create_oval(120, 50, 220, 130, fill="#e1f5fe", outline="#4fc3f7", width=2)
        for i, (dx, dy, col) in enumerate(((150, 70, "#ffd54f"), (180, 62, "#81d4fa"),
                                          (165, 92, "#a5d6a7"), (195, 96, "#f48fb1"),
                                          (140, 100, "#ce93d8"))):
            c.create_oval(dx, dy, dx + 18, dy + 18, fill=col, outline="")
        c.create_rectangle(150, 145, 190, 180, fill="#ffe0b2", outline="#8d6e63")
        c.create_text(170, 22, text="🎰 扭蛋机", font=(self.family, 11, "bold"),
                      fill=CFG.UI_TEXT)
        c.create_text(170, 212, text=f"每次 {CFG.GACHA_PRICE} 金币　"
                                     f"今天还能抽 {ex.gacha_left()}/{CFG.GACHA_DAILY}",
                     font=self.font_s, fill=CFG.UI_TEXT_DIM)
        self.ball = c.create_oval(0, 0, 0, 0, fill="#ffd54f", outline="")
        self.msg = tk.Label(self.body, text="", font=self.font, bg=CFG.UI_BG,
                            fg=CFG.UI_MAIN, wraplength=300, justify="center")
        self.msg.pack(pady=6)
        btn = self.make_button(self.body, "抽一次", self._draw, primary=True)
        btn.pack(pady=4)
        self.footer.config(text=f"金币 {self.pet.stats.coins}　"
                                f"已拥有 {len(ex.wardrobe)}/{len(OUTFITS)} 件装扮")

    def _draw(self):
        s, ex = self.pet.stats, self.pet.stats.extra
        if ex.gacha_left() <= 0:
            self.msg.config(text="今天抽够啦，明天再来～")
            return
        if s.coins < CFG.GACHA_PRICE:
            self.msg.config(text="金币不够呀…再攒攒吧")
            return
        s.add_coins(-CFG.GACHA_PRICE)
        res = ex.gacha_draw()
        oid = res["outfit"]
        is_skin = res.get("kind") == "skin"
        if is_skin:
            name = SKINS[oid]["name"]
            if res["is_new"]:
                text = f"抽到皮肤【{name}】！去「换装小屋」看看～"
            else:
                s.add_coins(res["refund"])
                text = f"皮肤「{name}」已经有了，折成 {res['refund']} 金币～"
        else:
            spec = OUTFITS[oid]
            if res["is_new"]:
                ex.codex_unlock("item", oid)
                text = f"抽到【{OUTFIT_TIER_NAME[spec['tier']]}】{spec['name']}！"
            else:
                s.add_coins(res["refund"])
                text = f"{spec['name']} 已经有了，折成 {res['refund']} 金币～"
        self.msg.config(text=text)
        try:
            self.pet.brain.show_text(text, 3.0)
            self.pet.brain.set_act(Act.HAPPY, 2.5)
        except Exception:
            pass
        self.pet.autosave(force=True)
        self._animate()

    def _animate(self):
        """2 秒出球动画：小球从机舱滚到出蛋口再消失"""
        c = self.canvas
        steps = 20
        for i in range(steps):
            def frame(k=i):
                try:
                    x = 170 - 60 * (k / steps)
                    y = 120 + 60 * (k / steps) * (k / steps)
                    c.coords(self.ball, x - 9, y - 9, x + 9, y + 9)
                except Exception:
                    pass
            self.pet.root.after(int(CFG.GACHA_ANIM_SEC * 1000 * i / steps), frame)
        self.pet.root.after(int(CFG.GACHA_ANIM_SEC * 1000),
                            lambda: self.refresh())


# ==============================================================================
# 9. DesktopPet —— 桌宠窗口本体（透明 / 无边框 / 置顶 / 全部交互）
# ==============================================================================
class DesktopPet:
    def __init__(self, cfg=CFG, verbose=False, start_pos=None, llm_cfg=None):
        self.cfg = cfg
        self.verbose = verbose
        self.assets = AssetLibrary(cfg)
        self.renderer = None                     # 等 Tk root 建好后再建
        self.stats = PetStats()
        self.brain = Brain(self.stats, verbose=verbose)

        # --- 大模型对接（可选）：配置 + 客户端 + 线程回传队列 ---
        self.llm_cfg = llm_cfg or LLMConfig.load()
        self.llm = LLMClient(self.llm_cfg, verbose=verbose) if self.llm_cfg.enabled else None
        self.llm_queue: "queue.Queue" = queue.Queue()
        self.llm_busy = False

        # --- 位置与移动 ---
        # ★ 多显示器：以宠物（或启动位置）所在显示器为准，不再固定主屏
        try:
            self.bounds = self._monitor_of(self.x, self.y)
        except Exception:
            self.bounds = self._virtual_screen()
        if start_pos:
            self.x, self.y = start_pos
        else:
            self.x = self.bounds[2] - cfg.WIN_W - 80
            self.y = self.bounds[3] - cfg.WIN_H - 70
        self.speed = 58.0                        # 散步速度 px/s
        self.flip = False
        self.bob_phase = random.random() * 6.28
        self.shake_until = 0.0

        # --- 交互状态 ---
        self.hovering = False
        self.btn_down = False
        self.press_pt = (0, 0)
        self.press_t = 0.0
        self.grab_off = (0, 0)
        self.dragging = False
        self.petting = False
        self.last_tick = time.time()
        self.last_topmost = 0.0
        self.bubble_text = None
        self.bubble_items: list[int] = []
        self.gif_timeline_pos = 0
        self.gif_until = 0.0
        self._last_act = None
        self.next_follow = 0.0          # 下次「主动靠近鼠标」的时间（亲密度高才启用）
        self._adv_items = []            # 探险进度条的 canvas 图元
        self._adv_bar_pct = -1
        self._adv_cooldown_until = 0.0  # 探险冷却（防刷）
        self._adv_saved_pos = None      # 模式B 出发前的位置
        self._pending_adv_result = None # 上次退出时未结算的探险
        self._panel = None              # 当前打开的养成/探险面板（同一时间只留一个）
        self.games_open = 0             # 打开中的小游戏窗口数（用于「陪玩打盹」）
        self._offline_note = ""         # 离线回来时的提示
        # ---- 第五阶段：UI 美化状态（canvas/root 已就绪，见 _build_window）----
        self.bubble_raw = None          # 当前气泡原文（None 表示还没建）
        self.bubble_full = ""           # 完整文本
        self.bubble_shown = 0           # 已打出的字数（打字机）
        self.bubble_type_start = 0.0
        self.bubble_rise_until = 0.0
        self.bubble_text_id = None
        self.bubble_cursor = None
        self.bubble_gold_until = 0.0
        self.look_flip_at = 0.0         # 眼神跟随的延迟计时
        self.look_flip_target = False
        self.cloud_next = 0.0           # 生病乌云的下次时间
        self.dust_next = 0.0            # 走路扬尘的下次时间
        self._last_bob = 0.0
        self.edge_side = None            # 贴边方向（left/right/None）
        self.edge_target_x = None        # 贴边后的隐藏位置
        self.edge_show_until = 0.0       # 滑出保持到什么时候
        # ★ 第十二阶段：扩展功能初始化（Overlay 在 _build_window 之后创建，这里只放纯数据）
        self.extra_ov = None
        self.sys_info = {}
        self.sys_next = 0.0
        self.remind_icon = ""
        self.remind_until = 0.0
        self.diary_done_date = ""
        self.last_interact_t = time.time()
        self.hover_since = 0.0           # 本次悬停开始时间（装饰淡入用）
        self.hover_last = 0.0            # 最近一次悬停时间（淡出延迟用）
        self.idle_action = None          # 当前待机小动作（模块2）
        self.next_idle_action = 0.0      # 下次小动作时间
        self.last_autosave = time.time()  # 上次自动存档时间
        self.debug_state = ""

        # --- 素材：静态三张先同步加载（毫秒级），动图后台解码 ---
        self.assets.prepare_sync()
        self.gif_thread = self.assets.prepare_gif_async()

        # --- 建窗口 ---
        self._prev_fg = self._get_foreground()      # 记住启动前谁在前台，稍后还给它
        self._build_window()
        self.renderer = SpriteRenderer(cfg)
        self.load_progress()                       # ★ 读取养成存档（模块7）
        # ★ 第十二阶段：Overlay 必须在 canvas 建好之后
        try:
            self.extra_ov = ExtraOverlay(self.canvas, self.cfg)
        except Exception:
            self.extra_ov = None
            log_event("EXTRA", "叠加装饰初始化失败\n" + traceback.format_exc())
        # ★ 第十二阶段：初遇日 / 纪念日 / 天赋点 / 故事 / 引导
        self.day_start = time.time()
        try:
            self._anniversary_check()
            self._talent_story_check()
            self._extra_intro()
            self.sample_system(force=True)
        except Exception:
            log_event("EXTRA", "启动扩展初始化失败\n" + traceback.format_exc())
        # ★ 第十阶段：存档里如果开了极简模式，启动就立刻应用（尺寸/挂件/粒子/字号）
        if CFG.ULTRA_MODE:
            try:
                CFG.set_pet_size(CFG.ULTRA_PET_SIZE)
                CFG.SHOW_WIDGETS = False
                CFG.PARTICLE_EFFECTS = False
                self.font_spec = (self.font_spec[0], CFG.ULTRA_BUBBLE_FONT)
                self.widget.build()                # 重建后挂件为空（ULTRA 时 layout 返回 None）
                log_event("UI", "启动即应用极简模式")
            except Exception:
                log_event("UI", "应用极简模式失败\\n" + traceback.format_exc())
        if self._pending_adv_result:               # 上次退出时还在探险 → 补一个结算窗
            self.root.after(1200, lambda: self._show_pending_adventure())
        self.brain.stage_name, self.brain.stage_scale = growth_stage(self.stats.level)
        self.brain.show_text(random.choice(LINES["ready"]), 3.0)

        # 窗口映射完成后，把键盘焦点还给启动前的那个窗口（宠物只该在旁边待着）
        self.root.after(150, self._restore_previous_focus)

        # --- 主循环 ---
        self.root.after(cfg.TICK_MS, self._tick)

    # ---------------------------------------------------------------- 窗口
    @staticmethod
    def _get_foreground() -> int:
        try:
            import ctypes
            return int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:
            return 0

    def _restore_previous_focus(self):
        """
        双击启动时 Windows 会把前台焦点给新窗口，导致你正在打字的程序突然收不到输入。
        这里在窗口出现后把焦点原样还回去 —— 桌宠应该安静地待在旁边，不打扰你。
        """
        if not self.cfg.NO_ACTIVATE or not getattr(self, "_prev_fg", 0):
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            me = int(self.root.frame(), 0)
            if u.GetForegroundWindow() == me and u.IsWindow(self._prev_fg):
                u.SetForegroundWindow(self._prev_fg)
        except Exception:
            pass

    def _monitor_of(self, x: float, y: float):
        """
        ★ 第十阶段：取「某点所在的那台显示器」的工作区（多显示器不乱跑）。
        失败时退回整块虚拟桌面。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.wintypes.DWORD),
                            ("rcMonitor", ctypes.wintypes.RECT),
                            ("rcWork", ctypes.wintypes.RECT),
                            ("dwFlags", ctypes.wintypes.DWORD)]

            u.MonitorFromPoint.restype = ctypes.c_void_p
            hmon = u.MonitorFromPoint(wt.POINT(int(x), int(y)), 2)   # NEAREST
            if hmon:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                u.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi))
                rc = mi.rcWork
                if rc.right > rc.left and rc.bottom > rc.top:
                    return (rc.left, rc.top, rc.right, rc.bottom)
        except Exception:
            pass
        return self._virtual_screen()

    def _cursor_monitor(self):
        """鼠标所在显示器的工作区"""
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            pt = wt.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            return self._monitor_of(pt.x, pt.y)
        except Exception:
            return self._virtual_screen()

    def _virtual_screen(self):
        """整块虚拟桌面（多显示器）范围：(left, top, right, bottom)。"""
        try:
            import ctypes
            u = ctypes.windll.user32
            u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))    # PER_MONITOR_AWARE_V2
        except Exception:
            pass
        try:
            import ctypes
            u = ctypes.windll.user32
            return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                    u.GetSystemMetrics(76) + u.GetSystemMetrics(78),
                    u.GetSystemMetrics(77) + u.GetSystemMetrics(79))
        except Exception:
            return (0, 0, 1920, 1080)

    def _build_window(self):
        cfg = self.cfg
        self.root = tk.Tk()
        self.root.title("Desktop Pet")
        self.root.overrideredirect(True)                        # 无边框
        self.root.attributes("-topmost", True)                  # 永远置顶
        if not cfg.SHOW_IN_TASKBAR:
            try:
                self.root.wm_attributes("-toolwindow", True)    # 不出现在 Alt-Tab/任务栏
            except Exception:
                pass
        try:
            self.root.wm_attributes("-transparentcolor", cfg.KEY_COLOR)   # ★ 透明背景核心
        except tk.TclError:
            print("[警告] 当前系统不支持 -transparentcolor（仅 Windows 支持），"
                  "窗口会显示为纯色背景。", flush=True)
        self.root.geometry(f"{cfg.WIN_W}x{cfg.WIN_H}+{int(self.x)}+{int(self.y)}")
        # ★ 关键：让宠物窗口「永不抢焦点」。否则双击启动后它会夺走当前窗口的键盘焦点，
        #   用户在别处打字会突然打不进去 —— 这是桌宠最容易被投诉的体验问题。
        self._apply_no_activate()
        try:
            log_event("WINDOW", f"hwnd={int(self.root.frame(), 0)} pos=({int(self.x)},{int(self.y)}) "
                                f"size={cfg.WIN_W}x{cfg.WIN_H}")
        except Exception:
            pass

        # 画布：背景 = 色键色 → 被系统抠成全透明
        self.canvas = tk.Canvas(self.root, width=cfg.WIN_W, height=cfg.WIN_H,
                                bg=cfg.KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # 字体（挑一个系统里有的中文字体）
        families = set(tkfont.families())
        family = cfg.FONT_FAMILY if cfg.FONT_FAMILY in families else (
            "Microsoft YaHei" if "Microsoft YaHei" in families else "SimHei"
            if "SimHei" in families else "TkDefaultFont")
        self.font_spec = (family, cfg.FONT_SIZE)
        self.font_obj = tkfont.Font(family=family, size=cfg.FONT_SIZE)

        # 宠物图像项（先占位，tick 里刷新）
        self.pet_item = self.canvas.create_image(0, cfg.BUBBLE_ZONE, anchor="nw")

        # ★ 第五阶段：美化组件（粒子 / 装饰）必须在 canvas + font_spec 就绪后创建
        self.dpi = dpi_scale(self.root)
        self.particles = ParticleSystem(self.canvas, self.font_spec, cfg.KEY_COLOR)
        self.decor = Decor(self.canvas, self.font_spec, cfg)
        self.decor.dpi = self.dpi
        self._part_t = time.time()

        # ★ 第六阶段：桌面挂件（时钟 / 天气 / 网速）
        self.net = NetSpeed()
        self.weather = None            # 最近一次天气数据（None = 还没拿到）
        self.weather_q = queue.Queue() # 后台线程 → 主线程
        self.weather_busy = False
        self.weather_fail = 0          # 连续失败次数（决定重试退避）
        self.weather_err = ""          # 最近一次失败原因（显示在提示里）
        self.next_weather = 0.0        # 下次刷新时间
        self.next_net = 0.0            # 下次网速采样时间
        self.widget = WidgetCard(self.canvas, cfg, self.font_spec[0])
        self.widget.build()
        self._last_chime_hour = time.localtime().tm_hour
        self._widget_hover_row = None
        self._widget_hover_t = 0.0

        # ---------------- 事件绑定 ----------------
        c = self.canvas
        self.root.bind("<ButtonPress-1>", self._on_press)
        self.root.bind("<B1-Motion>", self._on_drag)
        self.root.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Button-3>", self._on_right_click)
        self.root.bind("<Motion>", self._on_motion)
        c.bind("<Enter>", self._on_enter)
        c.bind("<Leave>", self._on_leave)
        # ★【重要修复】这里原来绑定了 <Escape> → quit()。
        #   桌宠窗口一旦拿到键盘焦点，随手按一次 Esc（关控制台、取消输入…）
        #   就会让桌宠「无声无息地退出」，控制台只留一句「桌宠已退出」。
        #   桌宠是常驻程序，绝不该被一个误触按键杀掉 —— 所以只保留右键菜单退出。
        self.root.bind("<Escape>", self._on_escape)
        self.root.protocol("WM_DELETE_WINDOW", self._on_wm_close)

        # ---- 右键菜单：分两页（首屏只放常用 8 项，减少遮挡）----
        #      格式：("emoji", "文字", 回调) 或 ("-",) 表示分隔线
        self.menu_items = [
            ("💬", "对话", self.open_chat),
            ("✋", "抚摸", self.do_pet),
            ("🍚", "喂食", self.do_feed),
            ("🧘", "治疗", self.do_treat),
            ("😜", "讲个笑话", self.do_joke),
            ("-",),
            ("🎮", "玩个小游戏", self.open_games),
            ("🗺️", "外出探险", self.open_adventure),
            ("📜", "任务日志", self.open_quest_log),
            ("🎒", "背包", self.open_inventory),
            ("🏪", "商店（含扭蛋机）", self.open_shop),
            ("📖", "图鉴", self.open_codex),
            ("👒", "换装小屋", self.open_wardrobe),
            ("🏠", "我的小窝", self.open_home),
            ("🌳", "天赋树", self.open_talents),
            ("📔", "奶蛙日记", self.open_diary),
            ("📖", "故事", self.open_story),
            ("🧠", "记忆库", self.open_memory),
            ("📝", "待办", self.open_todo),
            ("-",),
            ("👔", "穿衣建议", self.do_clothing),
            ("💻", "系统状态", self.open_system),
            ("⏰", "提醒设置", self.open_reminders),
            ("🔧", "设置（挂件/尺寸/季节）", self.open_settings),
            ("-",),
            ("😴", "睡觉 / 起床", self.do_sleep),
            ("📊", "查看状态", self.do_status),
            ("📈", "查看养成", self.do_growth_status),
            ("❤", "亲密度详情", self.do_bond_detail),
            ("🎁", "赠送礼物", self.do_gift),
            ("🤗", "抱抱", self.do_hug),
            ("🏆", "成就", self.open_achievements),
            ("📋", "每日任务", self.open_daily),
            ("🌤️", "天气详情/刷新", self.do_weather_detail),
            ("📊", "网速详情", self.do_net_detail),
            ("📏", "尺寸：中/小/大", self.cycle_pet_size),
            ("-",),
            ("🤖", "切换 AI 对话", self.toggle_llm),
            ("🔑", "配置 API Key", self.open_llm_setup),
            ("-",),
            ("♻️", "重置养成", self.do_reset),
            ("🚪", "退出", lambda: self.quit("右键菜单")),
        ]
        self.menu_items_more = []
        # 系统原生菜单（兜底）用同一份列表
        self.menu = tk.Menu(self.root, tearoff=0, font=self.font_spec)
        for it in self.menu_items:
            if it[0] == "-":
                self.menu.add_separator()
            else:
                self.menu.add_command(label=it[1], command=it[2])
        self._bmenu = None

        # 启动提示
        missing = [n for n in ("idle", "talk", "eat") if not self.assets.get(n)]
        if missing:
            print(f"[错误] 以下素材没有找到: {missing}\n"
                  f"        请把 pet_idle.webp / pet_talk.webp / pet_eat.webp / pet_happy.gif\n"
                  f"        放到 {os.path.join(app_dir(), 'assets')} 目录，或放到桌面。",
                  flush=True)
            self._vector_fallback_notice()
        for w in self.assets.warnings:
            print("[提示]", w, flush=True)

    def _apply_no_activate(self):
        """
        给宠物窗口加上 WS_EX_NOACTIVATE：鼠标点它不会激活窗口、不会抢走键盘焦点，
        但你正在打字的窗口/输入框可以继续正常输入（桌宠的正确姿势）。
        同时顺带重申 topmost —— 有些全屏程序会把置顶顶掉，这里一起兜住。
        """
        if not self.cfg.NO_ACTIVATE:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            try:
                hwnd = int(self.root.frame(), 0)        # Tk 顶层窗口句柄
            except Exception:
                hwnd = int(self.root.winfo_id())
            ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (ex & WS_EX_NOACTIVATE):
                u.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _vector_fallback_notice(self):
        """素材缺失时的兜底：用 Canvas 画一只纯色小团子，保证 Demo 不黑屏。"""
        self.canvas.create_oval(90, 60, 210, 200, fill="#ffd94a", outline="#e8bd2e", width=2)
        for cx in (120, 175):
            self.canvas.create_oval(cx, 90, cx + 22, 112, fill="#ffffff", outline="#3a3a3a", width=2)
            self.canvas.create_oval(cx + 6, 96, cx + 16, 106, fill="#2f2f2f", outline="")
        self.canvas.create_line(130, 140, 170, 140, fill="#8a6b1f", width=2)

    # ---------------------------------------------------------------- 绘制
    def _current_pose(self, now: float):
        """把「行为 + 数值 + 鼠标」翻译成一张精灵的姿态参数。"""
        cfg, b, s = self.cfg, self.brain, self.stats
        act = b.act
        t = now - b.t0
        tilt, dim, scale, lying = 0.0, 1.0, 1.0, False
        bob = 0.0

        if act in (Act.IDLE, Act.LOOK):
            bob = math.sin(t * 1.6) * 2.2                     # 轻微呼吸起伏
        elif act == Act.WALK:
            bob = -abs(math.sin(t * 6.0)) * 4.0               # 走路上下颠
        elif act == Act.HAPPY:
            bob = -abs(math.sin(t * 8.0)) * 5.0               # 蹦跳
        elif act == Act.BORED:
            bob = -abs(math.sin(t * 4.0)) * 2.5
            tilt = math.sin(t * 2.2) * 7.0                    # 来回张望
        elif act == Act.EAT:
            bob = -abs(math.sin(t * 5.0)) * 2.0
            scale = 1.0 + 0.05 * math.sin(t * 9.0)            # 咀嚼
        elif act == Act.PET:
            bob = math.sin(t * 7.5) * 2.4
            tilt = math.sin(t * 5.0) * 6.5                    # 舒服地晃
        elif act == Act.TALK:
            bob = -abs(math.sin(t * 4.5)) * 3.0
        elif act == Act.SLEEPY:
            bob = math.sin(t * 1.1) * 2.0
            tilt = -4.0
            dim = 0.90
        elif act == Act.HUNGRY:
            bob = math.sin(t * 12.0) * 1.6                    # 肚子咕咕叫的抖
            scale = 1.0 + 0.03 * math.sin(t * 12.0)
        elif act in (Act.SLEEP, Act.NAP):
            lying = (not b.sleep_anim_b)                      # 素材7 是趴睡姿势，不用旋转
            dim = 0.72 if act == Act.SLEEP else 0.80
            bob = math.sin(t * 1.0) * 1.2
        elif act == Act.DRAG:
            tilt = math.sin(t * 9.0) * 8.0                    # 被拎着晃
        # ---- 第二阶段：新状态的动作细节 ----
        elif act == Act.THINK:
            tilt = math.sin(t * 1.8) * 3.0                    # 思考时轻轻点头
            bob = math.sin(t * 2.2) * 1.6
        elif act == Act.JOKE:
            bob = -abs(math.sin(t * 9.0)) * 6.0               # 搞怪蹦跶
            tilt = math.sin(t * 6.0) * 9.0
        elif act == Act.SAD:
            dim = 0.88                                        # 失落：整体压暗一点
            bob = math.sin(t * 1.0) * 1.8
        elif act == Act.SICK:
            dim = 0.90
            bob = math.sin(t * 2.6) * 1.4
            tilt = math.sin(t * 1.4) * 3.0                    # 病恹恹地晃
        elif act == Act.STARVING:
            bob = math.sin(t * 11.0) * 1.8                    # 饿到发抖
            scale = 1.0 - 0.03 * abs(math.sin(t * 11.0))
        elif act == Act.ALLZERO:
            dim = 0.80
            tilt = math.sin(t * 1.2) * 4.0
        # ★ 待机动画：放空时极慢地左右轻晃 + 呼吸；打瞌睡时更沉
        elif act == Act.LEISURE:
            if getattr(b, "leisure_doze", False):
                dim = 0.86
                tilt = math.sin(t * 0.7) * (cfg.IDLE_ANIM_SWAY * 0.6)
                bob = math.sin(t * 1.1) * 1.0
            else:
                dim = 0.94
                tilt = math.sin(t * 0.8) * cfg.IDLE_ANIM_SWAY
                bob = math.sin(t * 1.3) * 1.8
            scale *= 1.0 + 0.008 * math.sin(t * 0.6)

        # 悬停 → 歪头看向鼠标（跟随方向）
        if self.hovering and act not in (Act.SLEEP, Act.NAP, Act.DRAG):
            try:
                px = self.root.winfo_pointerx()
                cx = self.root.winfo_rootx() + cfg.PET_CX
                tilt += max(-13.0, min(13.0, (px - cx) / 14.0))
            except Exception:
                pass
        if now < self.shake_until:                            # 拒绝喂食时的摇头
            tilt += math.sin(now * 40.0) * 9.0

        # ★ 素材选择：统一走状态决策（身体状况 > 心情表情 > 默认）
        asset = resolve_asset(act, self.stats, b.sleep_anim_b, b.pat_anim)
        if asset in ("sleep_b",) and act in (Act.SLEEP, Act.NAP):
            lying = False                                     # 素材7 本身就是趴着睡
        # ★ 待机动画打瞌睡段：复用素材7 的趴睡姿势（不引入新图片）
        if act == Act.LEISURE and getattr(b, "leisure_doze", False):
            asset = "sleep_b"
            lying = False
        # ★ 第九阶段：静态 idle → 循环播放程序化生成的呼吸动画
        if asset == "idle" and self.assets.get("idle_anim"):
            asset = "idle_anim"
        # ★ 第十阶段：紧凑尺寸（不重切素材，只改渲染缩放 → 切换零延迟）
        scale *= cfg.pet_scale()
        # 极简模式：整体半透明感（不挡桌面内容）
        if cfg.ULTRA_MODE:
            dim = min(dim, cfg.ULTRA_DIM)
        # 拖拽时变半透明，不挡视线
        if self.dragging or act == Act.DRAG:
            dim = min(dim, cfg.DRAG_DIM)
        # ★ 成长形态（模块5）：优先用专用形态素材；没有就等比缩放现有素材
        stage_asset = GROWTH_ASSETS.get(b.stage_name)
        if stage_asset and self.assets.get(stage_asset):
            asset = stage_asset
        else:
            scale *= b.stage_scale
        if now < b.growth_anim_until:                          # 升级/变身的过渡动画
            k = (b.growth_anim_until - now) / CFG.GROWTH_ANIM_SEC
            wobble = abs(math.sin(k * math.pi * 3)) * k
            scale *= 1.0 + 0.12 * wobble
            bob -= 6.0 * wobble
        # ---- 模块6-1：走路左右轻微倾斜（跟步频同步）----
        if act == Act.WALK and not lying:
            tilt += math.sin(t * 6.0) * self.cfg.WALK_TILT
        # ---- 模块6-2：待机呼吸感（每 2 秒一次极轻微缩放）----
        # 呼吸缩放：如果素材本身就是呼吸动画帧（缩放已烘焙进图），这里不再叠加
        has_breath_anim = bool(self.assets.get("idle_anim"))
        if act in (Act.IDLE, Act.LOOK) and not lying and not has_breath_anim:
            breath = math.sin(t * math.tau / max(0.3, self.cfg.BREATH_PERIOD))
            scale *= 1.0 + (self.cfg.BREATH_SCALE - 1.0) * (0.5 + 0.5 * breath)
        # ---- 模块6-3：眼神跟随（身体朝鼠标方向，带 200ms 延迟）----
        if self.hovering and act in (Act.IDLE, Act.LOOK, Act.BORED):
            if now >= self.look_flip_at:
                try:
                    px = self.root.winfo_pointerx()
                    cx = self.root.winfo_rootx() + self.cfg.PET_CX
                    target = px > cx            # 鼠标在右边 → 朝右
                    if target != self.look_flip_target:
                        self.look_flip_target = target
                        # 反应延迟：把「生效时间」推迟；空闲久了翻得更慢
                        idle_quiet = (now - getattr(self.brain, "last_user",
                                                    now)) > 20.0
                        self.look_flip_at = now + (
                            self.cfg.LOOK_DELAY_IDLE if idle_quiet
                            else self.cfg.LOOK_DELAY)
                except Exception:
                    pass
            flip = self.look_flip_target
        else:
            flip = self.flip
            self.look_flip_target = self.flip
            self.look_flip_at = 0.0
        frames = self.assets.get(asset)
        if not frames:                                        # 动图还没解码完 → 退回待机图
            asset = "idle_anim" if self.assets.get("idle_anim") else "idle"
            frames = self.assets.get(asset)
        if not frames:
            return None
        idx = 0
        if asset != getattr(self, "_last_asset", None):       # 素材切换 → 动图从头播
            self._last_asset = asset
            self.gif_timeline_pos = 0
            self.gif_until = 0.0
        if len(frames) > 1 and asset in ("happy", "mood0", "pat", "idle_anim"):
            durs = self.assets.durations(asset)
            if now >= self.gif_until:
                self.gif_timeline_pos = (self.gif_timeline_pos + 1) % len(frames)
                self.gif_until = now + max(0.03, (durs[self.gif_timeline_pos] if
                                                  self.gif_timeline_pos < len(durs) else 80) / 1000.0)
            idx = self.gif_timeline_pos
        elif act == Act.WALK:
            idx = 0
        # ---- 模块2：待机小动作（歪头 / 左右看 / 抖一下 / 眨眼感）----
        shake = 0.0
        breath_k = 1.0
        if asset == "idle_anim":
            # 当前呼吸帧的缩放系数（用于阴影同步呼吸）
            try:
                breath_k = CFG.IDLE_BREATH_TABLE[idx % len(CFG.IDLE_BREATH_TABLE)][0]
            except Exception:
                breath_k = 1.0
            act_now = self.idle_action
            if act_now and now < act_now["end"]:
                p = (now - act_now["start"]) / max(0.001, act_now["dur"])
                p = max(0.0, min(1.0, p))
                kind = act_now["kind"]
                if kind == "tilt":                      # 歪头：0° → 8° → 0°
                    tilt += math.sin(p * math.pi) * cfg.IDLE_TILT_MAX
                elif kind == "look":                    # 左右看：中段转身
                    if 0.3 < p < 0.85:
                        flip = not flip
                elif kind == "shake":                   # 抖一下：快速左右摆
                    shake = math.sin(p * math.pi * 6) * 3.0
                elif kind == "blink":                   # 眨眼感：短暂变暗
                    if 0.40 < p < 0.58:
                        dim = min(dim, cfg.IDLE_DIM_BLINK)
            elif act_now:
                self.idle_action = None                 # 播完自动回呼吸循环
        return dict(frame=frames[idx % len(frames)], flip=flip, tilt=tilt, dim=dim,
                    lying=lying, scale=scale, bob=bob, asset=asset, idx=idx,
                    shake=shake, breath=breath_k)

    def _render(self, now: float):
        if self.brain.act != self._last_act:            # 动作切换：动图从头播放
            self._last_act = self.brain.act
            if self.brain.act == Act.HAPPY:
                self.gif_timeline_pos = 0
                self.gif_until = 0.0
        pose = self._current_pose(now)
        if pose is None:
            return
        photo = self.renderer.photo(pose["frame"], flip=pose["flip"], tilt=pose["tilt"],
                                    dim=pose["dim"], lying=pose["lying"], scale=pose["scale"])
        self.canvas.itemconfigure(self.pet_item, image=photo)
        self.pet_photo = photo                                 # 保住引用，防被 GC
        # 精灵画布本身就是 WIN_W × SPRITE_H，anchor="nw" 所以 x 固定为 0
        # ★ 模块2「抖一下」：给一个 ±3px 的水平偏移
        self.canvas.coords(self.pet_item, pose.get("shake", 0.0),
                           self.cfg.BUBBLE_ZONE + pose["bob"])
        self._last_bob = pose["bob"]
        # ★ 第十二阶段：装扮 / 家具 / 节日 / 季节 / 便签 / 图标（全 Canvas 形状）
        try:
            self._extra_render(now, pose)
        except Exception:
            log_event("EXTRA", traceback.format_exc())
        # ★ 模块1：等级徽章 / 状态图标条 / 经验条 / 脚下阴影（阴影随呼吸同步缩放）
        if self.cfg.DECORATIONS:
            self._decor_alpha_tick(now)
            self.decor.update(now, self.cfg.PET_CX,
                              self.cfg.WIN_H - self.cfg.BASE_LINE_GAP + pose["bob"],
                              pose["bob"], self.stats, self.hovering,
                              breath=pose.get("breath", 1.0))
        # 拖拽时半透明，不挡视线
        try:
            if (self.dragging or self.brain.act == Act.DRAG) and not cfg.ULTRA_MODE:
                self.renderer_dim = cfg.DRAG_DIM
        except Exception:
            pass
        # ★ 模块3/6：粒子推进 + 生病乌云 + 走路扬尘
        self.particles.update(min(0.1, max(0.0, now - getattr(self, "_part_t", now))))
        self._part_t = now
        self._ambient_particles(now, pose)
        self._sync_bubble(now)

    # ---------------------------------------------------------------- 气泡（模块2 全面升级）
    def _bubble_theme(self) -> tuple:
        """按当前情绪/事件挑选气泡配色：(底色, 描边, 文字色)"""
        th = self.cfg.BUBBLE_THEMES
        if getattr(self, "bubble_gold_until", 0) > time.time():
            return th["gold"]                       # 升级 / 成就：浅金 + 星光
        act = self.brain.act
        if act in (Act.HAPPY, Act.TALK, Act.JOKE, Act.PET, Act.EAT):
            return th["happy"]                      # 开心 / 投喂：浅粉
        if act in (Act.HUNGRY, Act.SLEEPY, Act.BORED, Act.STARVING):
            return th["warn"]                       # 饿 / 困 / 无聊：浅黄
        if act in (Act.SAD, Act.SICK, Act.ALLZERO) or self.stats.sick:
            return th["sad"]                        # 难过 / 生病：浅蓝
        if any(k in (self.bubble_raw or "") for k in ("升级", "成就", "长大", "任务完成")):
            return th["gold"]
        return th["normal"]

    def _sync_bubble(self, now: float):
        """气泡状态机：新建 → 淡入上浮 → 逐字打出 → 停留 → 消失"""
        text = self.brain.current_text()
        if text != self.bubble_raw:                 # 文本变化 → 重建
            self.bubble_raw = text
            self._bubble_rebuild(now)
            return
        if not text:
            return
        # ---- 淡入 + 上浮（用 stipple 模拟 alpha：色键窗口没有真半透明）----
        if self.cfg.BUBBLE_ANIM and now < self.bubble_rise_until:
            k = 1.0 - (self.bubble_rise_until - now) / max(0.01, self.cfg.BUBBLE_FADE_IN)
            self._move_bubble(0, self.cfg.BUBBLE_RISE * k * 0.35)
            stipple = "" if k > 0.66 else ("gray50" if k > 0.33 else "gray25")
            for item in self.bubble_items:
                if item != self.bubble_cursor:
                    try:
                        self.canvas.itemconfigure(item, stipple=stipple)
                    except Exception:
                        pass
        # ---- 打字机 ----
        total = len(self.bubble_full)
        if self.bubble_shown < total:
            if self.cfg.BUBBLE_TYPEWRITER:
                want = int((now - self.bubble_type_start) / max(0.001, self.cfg.BUBBLE_TYPE_SPEED))
            else:
                want = total
            if want > self.bubble_shown:
                self.bubble_shown = min(total, want)
                self.canvas.itemconfigure(self.bubble_text_id,
                                          text=self.bubble_full[:self.bubble_shown])
                self.canvas.tag_raise(self.bubble_text_id)
        # ---- 打字光标：没打完时在尾巴末端闪 ----
        if self.bubble_cursor is not None:
            if self.bubble_shown < total:
                blink = int(now * 4) % 2 == 0
                self.canvas.itemconfigure(self.bubble_cursor,
                                          state="normal" if blink else "hidden")
            else:
                self.canvas.itemconfigure(self.bubble_cursor, state="hidden")

    def _bubble_rebuild(self, now: float):
        """文本变了才重建气泡（图元只在换文本时创建，不是每帧）"""
        cfg = self.cfg
        for item in self.bubble_items:
            self.canvas.delete(item)
        self.bubble_items = []
        self.bubble_cursor = None
        self.bubble_full = self.bubble_raw or ""
        self.bubble_shown = 0
        self.bubble_type_start = now
        self.bubble_rise_until = now + (cfg.BUBBLE_FADE_IN if cfg.BUBBLE_ANIM else 0)
        if not self.bubble_full:
            self.bubble_text_id = None
            return
        fill, line, txt_color = self._bubble_theme()
        maxw = cfg.BUBBLE_MAX_W - cfg.BUBBLE_PAD_X * 2
        minw = cfg.BUBBLE_MIN_W - cfg.BUBBLE_PAD_X * 2
        # ---- 自适应宽度：先不折行量自然宽，再按 [MIN, MAX] 定宽 ----
        tid = self.canvas.create_text(0, 0, text=self.bubble_full, font=self.font_spec,
                                      fill=txt_color, anchor="nw", justify="center")
        bx0, by0, bx1, by1 = self.canvas.bbox(tid)
        natural = bx1 - bx0
        if natural > maxw:
            self.canvas.itemconfigure(tid, width=maxw)
        elif natural < minw:
            self.canvas.itemconfigure(tid, width=minw)
        bx0, by0, bx1, by1 = self.canvas.bbox(tid)
        bw = (bx1 - bx0) + cfg.BUBBLE_PAD_X * 2
        bh = (by1 - by0) + cfg.BUBBLE_PAD_Y * 2
        bx = cfg.PET_CX - bw / 2
        by1c = cfg.BUBBLE_BOTTOM
        by0c = max(2.0, by1c - bh)
        # ---- ★ 美化：气泡下方的柔和投影（先画，压在最底层）----
        if cfg.UI_SHADOW:
            for i in range(cfg.UI_SHADOW_STEPS, 0, -1):
                grow = i * 1.5
                col = blend(cfg.UI_SHADOW_COLOR, "#ffffff", 0.42 + 0.16 * i)
                self.bubble_items.append(self.canvas.create_polygon(
                    self._round_rect(bx - grow + 1, by0c - grow + cfg.UI_SHADOW_OFFSET,
                                     bx + bw + grow + 1, by1c + grow + cfg.UI_SHADOW_OFFSET,
                                     cfg.BUBBLE_RADIUS + grow),
                    smooth=True, fill=col, outline=""))
        # ---- 尾巴跟随宠物朝向 ----
        flip = getattr(self, "flip", False)
        tail_x = cfg.PET_CX + (-18 if flip else 18)
        tail_x = max(bx + 26, min(bx + bw - 26, tail_x))
        tail = self.canvas.create_polygon(
            tail_x - 10, by1c - 6, tail_x + 2, by1c + 12, tail_x + 12, by1c - 6,
            fill=fill, outline=line, width=1, smooth=True)
        body = self.canvas.create_polygon(
            self._round_rect(bx, by0c, bx + bw, by1c, cfg.BUBBLE_RADIUS),
            smooth=True, fill=fill, outline=line, width=2)
        # ---- ★ 美化：气泡顶部一层高光，看起来有玻璃质感 ----
        if cfg.BUBBLE_GLOSS:
            self.bubble_items.append(self.canvas.create_polygon(
                self._round_rect(bx + 3, by0c + 2, bx + bw - 3, by0c + 11,
                                 max(4, cfg.BUBBLE_RADIUS - 4)),
                smooth=True, fill=blend(fill, "#ffffff", 0.65), outline=""))
        self.canvas.coords(tid, bx + cfg.BUBBLE_PAD_X, by0c + cfg.BUBBLE_PAD_Y)
        self.canvas.itemconfigure(tid, text="")          # 打字机从 0 字开始
        self.canvas.tag_raise(tid)
        self.bubble_text_id = tid
        # ★ 关键：追加而不是覆盖（列表里已有投影/高光）。覆盖会丢掉它们的引用，
        #   下次重建就删不掉 → 灰投影一层层叠起来把气泡盖住（踩过这个坑）。
        for extra in (tail, body, tid):
            self.bubble_items.append(extra)
        self.bubble_box = (bx, by0c, bx + bw, by1c)
        # ---- 金色气泡的星光点缀 ----
        if cfg.BUBBLE_SPARKLE and self._bubble_theme() == cfg.BUBBLE_THEMES["gold"]:
            for sx, sy in ((bx + 9, by0c + 8), (bx + bw - 10, by0c + 10),
                           (bx + bw - 15, by1c - 9)):
                r = 3.5
                self.bubble_items.append(self.canvas.create_polygon(
                    sx, sy - r, sx + r * 0.3, sy, sx, sy + r, sx - r * 0.3, sy,
                    fill="#ffd700", outline=""))
                self.bubble_items.append(self.canvas.create_polygon(
                    sx - r, sy, sx, sy + r * 0.3, sx + r, sy, sx, sy - r * 0.3,
                    fill="#ffd700", outline=""))
        # ---- 打字光标（尾巴末端小圆点）----
        self.bubble_cursor = self.canvas.create_oval(
            tail_x - 2.5, by1c + 13, tail_x + 2.5, by1c + 18, fill=line, outline="")
        self.bubble_items.append(self.bubble_cursor)

    def _move_bubble(self, dx: float, dy: float):
        for item in self.bubble_items:
            try:
                self.canvas.move(item, dx, dy)
            except Exception:
                pass

    # ---------------------------------------------------------------- 装饰显隐（模块2）
    def _decor_alpha_tick(self, now: float):
        """
        装饰默认隐藏，只在「需要」时淡入：
          · 鼠标悬停宠物 ≥ HOVER_DECOR_DELAY → 淡入
          · 正在说话（气泡可见）/ 睡觉 / 生病 → 保持显示
          · 鼠标离开 → 继续显示 HOVER_DECOR_FADE_OUT 秒后淡出
        极简模式：永远隐藏。
        """
        cfg = self.cfg
        if not cfg.COMPACT:                 # 美化版：装饰常显，不做悬停淡入
            if abs(getattr(self.decor, "alpha", 1.0) - 1.0) > 0.01:
                self.decor.set_alpha(1.0)
            return
        if cfg.ULTRA_MODE:
            if getattr(self.decor, "alpha", 0) != 0.0:
                self.decor.set_alpha(0.0)
            return
        force = False
        if self.bubble_raw:
            force = True                       # 正在说话
        if self.stats.sick or self.brain.act in (Act.SLEEP,):
            force = True                       # 生病 / 睡觉：需要用户注意
        # 只在「刚进入悬停」时记录起点，否则每帧重置会导致延迟失效
        if self.hovering:
            if not getattr(self, "_was_hovering", False):
                self.hover_since = now
            self._was_hovering = True
            self.hover_last = now
        else:
            self._was_hovering = False
        # 目标可见度
        if force:
            target = 1.0
        elif self.hovering:
            # 悬停满 HOVER_DECOR_DELAY 秒才淡入
            target = 1.0 if (now - self.hover_since) >= cfg.HOVER_DECOR_DELAY else 0.0
        elif now - getattr(self, "hover_last", 0.0) < cfg.HOVER_DECOR_FADE_OUT:
            target = 1.0                       # 离开后 2 秒内保持
        else:
            target = 0.0
        cur = getattr(self.decor, "alpha", 0.0)
        step = 1.0 / max(1, cfg.DECOR_FADE_STEPS)
        if target > cur:
            cur = min(target, cur + step)
        elif target < cur:
            cur = max(target, cur - step)
        if cur != getattr(self.decor, "alpha", 0.0):
            self.decor.set_alpha(cur)

    # ---------------------------------------------------------------- 待机小动作（模块2）
    def _idle_action_tick(self, now: float):
        """
        每 8~15 秒随机插一个 1.2 秒的小动作，覆盖在呼吸循环上：
        歪头 / 左右看 / 抖一下 / 眨眼感。播完自动回到呼吸循环。
        """
        cfg = self.cfg
        if not self.assets.get("idle_anim"):
            return
        act = self.brain.act
        if act not in (Act.IDLE, Act.LOOK):
            if self.idle_action:                 # 切到别的状态就丢弃小动作
                self.idle_action = None
            return
        if self.idle_action:
            return                               # 正在播
        if now < self.next_idle_action:
            return
        lo, hi = cfg.IDLE_RANDOM_ACTION_INTERVAL
        self.next_idle_action = now + random.uniform(lo, hi)
        kind = random.choice(cfg.IDLE_ACTION_KINDS)
        self.idle_action = dict(kind=kind, start=now,
                                dur=cfg.IDLE_ACTION_DURATION,
                                end=now + cfg.IDLE_ACTION_DURATION)
        log_event("IDLE-ACTION", f"待机小动作：{kind}")

    # ---------------------------------------------------------------- 粒子触发（模块3/6）
    def _ambient_particles(self, now: float, pose: dict):
        """环境粒子：生病冒乌云、走路扬尘、抚摸星星、进食气泡（全在主循环里驱动）"""
        if not self.cfg.PARTICLE_EFFECTS:
            return
        st = self.stats
        cx = self.cfg.PET_CX
        head_y = self.cfg.BUBBLE_ZONE + 30
        if st.sick and now >= self.cloud_next:            # 生病乌云
            self.cloud_next = now + self.cfg.CLOUD_INTERVAL
            self.particles.spawn_cloud(cx + random.uniform(-10, 10), head_y)
        act = self.brain.act
        if act == Act.WALK and now >= self.dust_next:     # 走路扬尘
            self.dust_next = now + self.cfg.DUST_INTERVAL
            self.particles.spawn_dust(cx + random.uniform(-18, 18),
                                     self.cfg.WIN_H - self.cfg.BASE_LINE_GAP - 4)
        if self.petting and random.random() < 0.30:        # 抚摸星星
            self.particles.spawn_stars(cx + random.uniform(-30, 30), self.cfg.WIN_H - 95)
        # ★ 待机动画：打瞌睡时头顶飘小星星/zzZ，放空时偶尔飘一颗
        if act == Act.LEISURE:
            doze = getattr(self.brain, "leisure_doze", False)
            if doze and random.random() < 0.12:
                self.particles.spawn_stars(cx + random.uniform(-14, 14),
                                           self.cfg.BUBBLE_ZONE + 34, count=1,
                                           color="#cfd8dc")
            elif not doze and random.random() < 0.04:
                self.particles.spawn_stars(cx + random.uniform(-26, 26),
                                           self.cfg.WIN_H - 90, count=1)
        if act == Act.EAT and random.random() < 0.22:      # 进食气泡
            self.particles.spawn_eat_bubbles(cx + random.uniform(-8, 8),
                                            self.cfg.WIN_H - 125, count=1)

    def burst_hearts(self, x: float = None, y: float = None):
        """点击飘心（模块3-1）：开心粉色 / 低落灰色"""
        if not self.cfg.PARTICLE_EFFECTS:
            return
        color = (self.cfg.HEART_COLOR_HAPPY if self.stats.happy >= 30
                 else self.cfg.HEART_COLOR_SAD)
        n = random.randint(*self.cfg.HEART_COUNT)
        self.particles.spawn_hearts(
            x if x is not None else self.cfg.PET_CX,
            y if y is not None else self.cfg.WIN_H - 120, count=n, color=color)

    def burst_levelup(self):
        """升级庆祝（模块3-4）：头顶礼花 + 徽章弹跳 + 经验条闪白 + 金色气泡"""
        if self.cfg.PARTICLE_EFFECTS:
            self.particles.spawn_confetti(self.cfg.PET_CX,
                                          self.cfg.BUBBLE_ZONE + 24,
                                          count=self.cfg.CONFETTI_COUNT)
        if self.cfg.DECORATIONS:
            self.decor.on_levelup(time.time())
        self.flash_bubble_gold(3.0)

    def flash_bubble_gold(self, seconds: float = 3.0):
        """让气泡切到金色主题（升级/成就时调用）"""
        self.bubble_gold_until = time.time() + seconds
        self.bubble_raw = None              # 强制重建以换配色
        for item in self.bubble_items:
            self.canvas.delete(item)
        self.bubble_items = []

    @staticmethod
    def _round_rect(x0, y0, x1, y1, r):
        """圆角矩形顶点（配合 smooth=True 由 Tk 画成样条圆角）。"""
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    # ---------------------------------------------------------------- 主循环
    def _tick(self):
        try:
            now = time.time()
            dt = min(0.2, max(0.001, now - self.last_tick))
            self.last_tick = now

            # 长按 → 抚摸（0.4 秒内几乎没移动 = 抚摸；移动了 = 拖拽）
            if self.btn_down and not self.dragging and (now - self.press_t) > 0.40:
                if not self.petting:
                    self.petting = True
                    self.brain.start_pet()
            if self.petting:
                self.brain.keep_pet(dt)

            traveling = bool(self.stats.adventure)
            if not self.dragging and not self.petting:
                self.brain.tick(dt, traveling=traveling)
                self._maybe_follow_mouse(now)
                self._move(dt)
            self._adventure_tick(now)      # ★ 探险倒计时 / 累趴判定 / 进度条（模块2）
            self._widget_tick(now)         # ★ 挂件：时钟 / 天气 / 网速 / 整点报时

            self._extra_tick(now)         # ★ 第十二阶段：提醒/系统/日记/纪念日/情绪
            self._edge_tick(now)          # ★ 靠边隐藏的滑出/滑回
            self._idle_action_tick(now)   # ★ 待机小动作调度（歪头/左右看/抖/眨眼）
            self._drain_llm()          # 大模型回复回填（线程安全，只查队列）
            self.autosave()            # ★ 养成数据自动存档（模块7）
            self._render(now)
            self._assert_topmost(now)

            if self.verbose:
                st = f"{self.brain.act}|{self.stats.mood()}|" \
                     f"h{self.stats.happy:.0f} f{self.stats.full:.0f} " \
                     f"e{self.stats.energy:.0f} b{self.stats.bored:.0f}"
                if st != self.debug_state:
                    self.debug_state = st
                    print(f"[{now - self.brain.t0:7.2f}s] {st}", flush=True)
        except Exception:
            log_event("TICK-ERROR", traceback.format_exc())
            traceback.print_exc()
        finally:
            self.root.after(self.cfg.TICK_MS, self._tick)

    def _maybe_follow_mouse(self, now: float):
        """
        模块3：亲密度高时主动靠近鼠标（跟随更紧）。
        只在待机/发呆时偶尔触发，避免看起来像抽风。
        """
        if self.stats.bond < CFG.BOND_FOLLOW_AT:
            return
        if self.brain.act not in (Act.IDLE, Act.BORED):
            return
        if now < self.next_follow:
            return
        self.next_follow = now + random.uniform(12.0, 25.0)
        try:
            px = self.root.winfo_pointerx()
            target = max(self.bounds[0] + 10,
                         min(self.bounds[2] - self.cfg.WIN_W - 10,
                             px - self.cfg.PET_CX))
        except Exception:
            return
        if abs(target - self.x) < 60:            # 已经很近了就不用挪
            return
        self.brain.target_x = target
        self.brain.set_act(Act.WALK, 4.0)
        self.brain.show_text("我过来啦～", 2.2)
        self.brain._log("亲密度高 → 主动靠近鼠标")

    def _move(self, dt: float):
        """自主散步 / 无聊踱步的实际位移。"""
        act, cfg = self.brain.act, self.cfg
        if act not in (Act.WALK, Act.BORED):
            return
        left, top, right, bottom = self.bounds
        tx = self.brain.target_x
        arrived = (tx is None) or (abs(tx - self.x) < 10)
        if arrived:
            if act == Act.WALK:      # 散步：换一个随机远点
                tx = random.uniform(left + 20, max(left + 40, right - cfg.WIN_W - 20))
                self.brain.act_until = max(self.brain.act_until, time.time() + 3.0)
            else:                    # 无聊：来回踱步，到点就反向
                span = random.uniform(90, 190)
                tx = self.x - span if (self.brain.last_dir > 0) else self.x + span
                tx = max(left + 10, min(right - cfg.WIN_W - 10, tx))
            self.brain.target_x = tx
        dx = tx - self.x
        speed = self.speed if act == Act.WALK else self.speed * 0.8
        step = math.copysign(min(abs(dx), speed * dt), dx)
        if abs(dx) < 2:
            return
        self.x += step
        self.flip = dx > 0                       # 素材默认朝左 → 向右走时镜像
        self.brain.last_dir = 1 if dx > 0 else -1
        self._apply_geometry()

    def _apply_geometry(self):
        cfg = self.cfg
        left, top, right, bottom = self.bounds
        self.x = max(left - 20, min(right - cfg.WIN_W + 20, self.x))
        self.y = max(top, min(bottom - cfg.WIN_H, self.y))
        self.root.geometry(f"{cfg.WIN_W}x{cfg.WIN_H}+{int(self.x)}+{int(self.y)}")

    def _assert_topmost(self, now: float):
        if (getattr(self, '_bmenu', None) is None
                and now - self.last_topmost > self.cfg.TOPMOST_REASSERT):
            self.last_topmost = now
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass
            self._apply_no_activate()      # 一并重申「不抢焦点」（全屏程序可能顶掉样式）

    # ---------------------------------------------------------------- 鼠标事件
    def _on_press(self, e):
        # ★ 菜单弹窗开着的时候，点哪里都不算摸奶蛙（避免误触）
        if getattr(self, "_menu_open", False):
            return
        # ★ 第十二阶段：点一下桌宠 = 「我知道了」，重置喝水/久坐计时
        try:
            self.acknowledge_reminder()
        except Exception:
            pass
        if self.stats.adventure:              # 探险中：点它只会说句话，不拖不摸
            self.brain.show_text(random.choice(ADV_LINES["busy"]), 2.2)
            return
        self.btn_down = True
        self.press_pt = (e.x_root, e.y_root)
        self.press_t = time.time()
        self.dragging = False
        self.petting = False
        self.grab_off = (e.x_root - self.x, e.y_root - self.y)
        self.brain.touch()

    def _on_drag(self, e):
        if not self.btn_down:
            return
        dx = abs(e.x_root - self.press_pt[0])
        dy = abs(e.y_root - self.press_pt[1])
        if not self.dragging and (dx + dy) > 7:
            self.dragging = True
            self.petting = False
            self.brain.start_drag()
        if self.dragging:
            self.x = e.x_root - self.grab_off[0]
            self.y = e.y_root - self.grab_off[1]
            self._apply_geometry()

    def _on_release(self, e):
        if self.stats.adventure:
            self.btn_down = False
            return
        was_drag, was_pet = self.dragging, self.petting
        if not was_drag and not was_pet:
            # ★ 模块3-1：点击飘心（落点在鼠标处，跟着点的地方冒）
            self.burst_hearts(e.x, e.y)
        self.btn_down = False
        self.dragging = False
        self.petting = False
        if was_drag:
            self.brain.end_drag()
            self._maybe_edge_snap()          # ★ 靠边自动贴边隐藏
        elif was_pet:
            self.brain.set_act(Act.IDLE, 2.0)
        else:
            self.brain.clicked()

    def _on_motion(self, e):
        self.brain.touch()
        # ★ 悬停挂件 → 气泡显示详情
        if self.cfg.SHOW_WIDGETS:
            self._on_widget_hover(e.x, e.y)

    def _on_enter(self, e):
        self.hovering = True
        self.brain.hover()

    def _on_leave(self, e):
        self.hovering = False

    def _on_right_click(self, e):
        self.brain.touch()
        if getattr(self, "_menu_open", False):        # 菜单开着再右键 = 关掉
            self._close_menu()
            return
        if self.cfg.CUSTOM_MENU:
            # ★ 模块4：自定义圆角菜单（失败时退回系统原生菜单）
            try:
                if getattr(self, "_bmenu", None) is not None:
                    try:
                        self._bmenu.destroy()
                    except Exception:
                        pass
                mw = self.cfg.MENU_W
                mh = (self.cfg.MENU_PAD * 2
                      + sum((self.cfg.MENU_ROW_H if it[0] != "-" else 9)
                            for it in self.menu_items))
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                # ★ 菜单放到宠物窗口「外面」：优先右侧，其次左侧、上方、下方
                #   这样不会压在奶蛙身上，也不会被奶蛙抢到前面挡住
                px, py = self.x, self.y
                pw, ph = self.cfg.WIN_W, self.cfg.WIN_H
                gap = 10
                cands = [(px + pw + gap, py),                    # 右
                         (px - mw - gap, py),                    # 左
                         (px, py - mh - gap),                     # 上
                         (px, py + ph + gap),                     # 下
                         (px + pw + gap, py + ph - mh),           # 右下对齐
                         (px + pw // 2 - mw // 2, py - mh - gap)]  # 上方居中
                mx = my = None
                for cx_, cy_ in cands:
                    if 4 <= cx_ <= sw - mw - 4 and 4 <= cy_ <= sh - mh - 44:
                        mx, my = cx_, cy_
                        break
                if mx is None:                       # 屏幕太小：夹到可见范围
                    mx = max(4, min(sw - mw - 4, e.x_root - mw // 2))
                    my = max(4, min(sh - mh - 44, e.y_root - 8))
                self._bmenu = MenuWindow(self.root, self, self.menu_items,
                                         int(mx), int(my))
                return
            except Exception:
                log_event("MENU", "自定义菜单失败，退回系统菜单\n" + traceback.format_exc())
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _close_menu(self):
        """关掉右键菜单窗口"""
        bm = getattr(self, "_bmenu", None)
        self._bmenu = None
        self._menu_open = False
        if bm is not None:
            try:
                bm.destroy()
            except Exception:
                pass

    # ---------------------------------------------------------------- 菜单动作
    def do_feed(self):
        """★ 喂食改造：不再凭空喂食，改成打开「吃背包里的食物」面板"""
        foods = [n for n in self.stats.inventory if is_food(n)]
        if not foods:
            self.brain.show_text("背包里没有吃的啦…去商店买点吧", 3.2)
            self.open_shop()
            log_event("INTERACT", "喂食（背包无食物 → 打开商店）")
            return
        if self.stats.full >= CFG.FULL_REFUSE:
            self.brain.show_text(random.choice(LINES["refuse"]), 2.6)
            self.shake_until = time.time() + 0.7      # 太饱 → 摇头拒绝
            return
        if self.brain.act == Act.SLEEP:
            self.brain.wake_up()
        if self.cfg.PARTICLE_EFFECTS:
            self.particles.spawn_eat_bubbles(self.cfg.PET_CX,
                                            self.cfg.WIN_H - 125, count=3)
        self._open_panel(FeedPanel)
        log_event("INTERACT", "喂食（选择背包食物）")

    def do_gift(self):
        """★ 新增：赠送礼物提升好感度"""
        gifts = [n for n in self.stats.inventory if is_giftable(n)]
        if not gifts:
            self.brain.show_text("背包里没有能送的东西…去商店看看吧", 3.2)
            log_event("INTERACT", "赠送（背包无可赠物品）")
            return
        if self.stats.bond >= CFG.BOND_MAX:
            self.brain.show_text("我们的心意已经满格啦，不用再送东西了～", 3.2)
            return
        self._open_panel(GiftPanel)
        log_event("INTERACT", "赠送礼物")

    def do_pet(self):
        self.brain.start_pet()
        self.petting = True
        self.press_t = time.time()
        self.btn_down = False
        self.root.after(1400, self._end_menu_pet)

    def _end_menu_pet(self):
        self.petting = False
        self.brain.set_act(Act.IDLE, 1.5)

    def do_sleep(self):
        self.brain.toggle_sleep()

    def do_treat(self):
        """右键「治疗」：生病时治好（唯一的痊愈方式），没病时给个提示。"""
        cured = self.brain.treat()
        log_event("INTERACT", f"治疗({'成功' if cured else '无需治疗'})")

    def do_joke(self):
        """右键「讲个笑话」：搞怪动作 + 笑话气泡。"""
        self.brain.joke()
        log_event("INTERACT", "讲笑话")

    def do_status(self):
        """查看状态：打开可视化面板（模块5-2），素材缺失也照常可用"""
        try:
            self._open_panel(StatusPanel)
        except Exception:
            log_event("PANEL", "状态面板失败，退回气泡\n" + traceback.format_exc())
            self.brain.show_text(self.stats.report(), 7.0)
        log_event("INTERACT", "查看状态")

    def do_growth_status(self):
        """养成面板（气泡版）：等级/经验/金币/亲密度/成就进度"""
        s = self.stats
        stage, _ = growth_stage(s.level)
        txt = (f"Lv.{s.level}（{stage}）　经验 {s.exp}/{s.exp_to_next()}\n"
               f"金币 {s.coins}　亲密度 {s.bond:.0f}（{s.bond_tier()}）\n"
               f"成就 {len(s.achievements)}/{len(ACHIEVEMENTS)}　"
               f"连续登录 {s.streak_days} 天\n"
               f"累计：喂食{s.counters.get('feed', 0)} 聊天{s.counters.get('chat', 0)} "
               f"抚摸{s.counters.get('pet_seconds', 0):.0f}秒")
        self.brain.show_text(txt, 7.0)
        log_event("INTERACT", "查看养成")

    def do_hug(self):
        self.brain.hug()
        log_event("INTERACT", "抱抱")

    # ---------------- 桌面挂件（模块1~4） ----------------
    def _widget_tick(self, now: float):
        """
        挂件每帧更新：时钟 / 网速采样 / 天气刷新 / 整点报时。
        全部在主循环里跑；天气请求走后台线程，结果用队列回主线程。
        """
        tm = time.localtime()
        if now >= self.next_net:                       # 网速采样
            self.next_net = now + self.cfg.NET_SAMPLE_INTERVAL
            try:
                self.net.sample(now)
            except Exception:
                log_event("NET", traceback.format_exc())
        try:                                           # 天气：取后台结果
            while True:
                data = self.weather_q.get_nowait()
                self.weather_busy = False
                if data:
                    self.weather = data
                    self.weather_fail = 0
                    self.weather_err = ""
                    log_event("WEATHER", f"{data.get('city')} {data.get('temp')}℃ "
                                         f"code={data.get('code')} 源={data.get('source')}")
                else:
                    # ★ 失败不干等 10 分钟：按退避表快速重试
                    self.weather_fail += 1
                    idx = min(self.weather_fail - 1, len(CFG.WEATHER_RETRY_BACKOFF) - 1)
                    wait = CFG.WEATHER_RETRY_BACKOFF[max(0, idx)]
                    self.next_weather = time.time() + wait
                    log_event("WEATHER", f"获取失败，{wait:.0f} 秒后重试"
                                         f"（第 {self.weather_fail} 次）")
        except queue.Empty:
            pass
        if (self.cfg.SHOW_WEATHER and now >= self.next_weather
                and not self.weather_busy):            # 到期刷新（后台线程）
            if self.weather_fail == 0:
                self.next_weather = now + max(60.0, self.cfg.WEATHER_REFRESH_MIN * 60.0)
            self.weather_busy = True
            threading.Thread(target=self._weather_worker, name="weather",
                             daemon=True).start()
        self._maybe_chime(tm)
        try:
            self.widget.fail_hint = bool(self.weather_fail)
            self.widget.update(tm, self.weather, self.net)
        except Exception:
            log_event("WIDGET", traceback.format_exc())

    def _weather_worker(self):
        """后台线程：请求天气（多源兜底），结果丢队列（失败丢 None 便于降级）"""
        try:
            data = fetch_weather()
        except Exception as exc:
            log_event("WEATHER", f"全部数据源失败：{exc}")
            data = None
            self.weather_err = str(exc)[:120]
        try:
            self.weather_q.put(data)
        except Exception:
            pass

    def _maybe_chime(self, tm):
        """整点报时 + 饭点 / 睡觉点提醒（同一小时只报一次）"""
        if tm.tm_hour == self._last_chime_hour:
            return
        self._last_chime_hour = tm.tm_hour
        if tm.tm_min > 5:                  # 只在整点附近报，重启时不补报
            return
        msgs = []
        for hour, text in self.cfg.CHIME_MEALS:
            if tm.tm_hour == hour:
                msgs.append(text)
        if tm.tm_hour == self.cfg.CHIME_SLEEP[0]:
            msgs.append(self.cfg.CHIME_SLEEP[1])
        if self.cfg.CHIME_ON_HOUR:
            msgs.append(f"现在是 {tm.tm_hour} 点整啦，该休息一下哦～")
        if not msgs:
            return
        self.brain.show_text(msgs[0], 4.0)
        for extra in msgs[1:]:
            self.brain.queue_tip(extra)
        log_event("CHIME", "；".join(msgs))

    def refresh_weather_now(self, silent: bool = False):
        """手动刷新天气：清掉退避计时，立刻重试"""
        self.next_weather = 0.0
        self.weather_busy = False
        self.weather_fail = 0
        if not silent:
            self.brain.show_text("我去看看天气～", 2.4)
        log_event("WEATHER", "用户手动刷新天气")

    def do_weather_detail(self):
        """天气详情（气泡版）：城市/温度/上下限/湿度/风/数据源"""
        w = self.weather
        if not w or w.get("temp") is None:
            msg = "还没拿到天气呢…"
            if self.weather_err:
                msg += f"（{self.weather_err[:60]}）"
            self.brain.show_text(msg + "　点我重试！", 4.0)
            self.refresh_weather_now()
            return
        emoji, label = wmo_info(w.get("code"))
        txt = f"{w.get('city')}　{emoji} {w['temp']:.0f}℃ {label}"
        if w.get("tmin") is not None and w.get("tmax") is not None:
            txt += f"\n今日 {w['tmin']:.0f}~{w['tmax']:.0f}℃"
        if w.get("humidity") is not None:
            txt += f"　湿度 {w['humidity']}%"
        if w.get("wind") is not None:
            txt += f"　风 {w['wind']}km/h"
        txt += f"\n数据源：{w.get('source', '?')}"
        self.brain.show_text(txt, 6.0)

    def do_clothing(self):
        """模块2-3：今天穿什么"""
        w = self.weather
        if not w or w.get("temp") is None:
            self.brain.show_text("天气获取中，稍后再问我哦～", 3.0)
            return
        tip = clothing_advice(w["temp"], w.get("code"), w.get("wind"))
        self.brain.show_text(tip, 6.0)
        log_event("WIDGET", f"穿衣建议：{tip}")

    def do_net_detail(self):
        """模块3-3：网速详情面板"""
        self._open_panel(NetSpeedPanel)

    def do_bond_detail(self):
        """亲密度详情"""
        s = self.stats
        nxt = ""
        for need, label in CFG.BOND_TIERS:
            if s.bond < need:
                nxt = f"　下一档「{label}」还差 {need - s.bond:.0f}"
                break
        self.brain.show_text(f"亲密度 {s.bond:.0f} / {CFG.BOND_MAX:.0f}（{s.bond_tier()}）"
                             f"{nxt}\n抚摸最加分，聊天次之，喂食再次", 6.0)

    def do_widget_settings(self):
        """模块4-2：挂件设置"""
        WidgetSettingsDialog(self.root, self, self.font_spec)

    def rebuild_widget(self):
        self.widget.build()

    # ---------------------------------------------------------------- 靠边隐藏（模块4）
    def _maybe_edge_snap(self):
        """松手时如果贴近屏幕左右边缘 → 只露半个身子藏起来"""
        cfg = self.cfg
        if not cfg.EDGE_HIDE or cfg.ULTRA_MODE:
            self.edge_side = None
            self.edge_target_x = None
            return
        left, top, right, bottom = self.bounds
        th = cfg.EDGE_HIDE_THRESHOLD
        peep_w = int(cfg.WIN_W * cfg.EDGE_HIDE_PEEK)
        if self.x <= left + th:
            self.edge_side = "left"
            self.edge_target_x = float(left - (cfg.WIN_W - peep_w))
        elif self.x + cfg.WIN_W >= right - th:
            self.edge_side = "right"
            self.edge_target_x = float(right - peep_w)
        else:
            self.edge_side = None
            self.edge_target_x = None
        if self.edge_side:
            self.edge_hide_t = time.time()
            log_event("UI", f"贴边隐藏：{self.edge_side} x={int(self.x)}")

    def _edge_tick(self, now: float):
        """每帧处理贴边后的「滑出 / 滑回」"""
        cfg = self.cfg
        if not cfg.EDGE_HIDE:
            return
        if not getattr(self, "edge_side", None):
            return
        left, top, right, bottom = self.bounds
        # 鼠标靠近那条边（且在宠物高度范围内）→ 滑出来
        try:
            px = self.root.winfo_pointerx()
            py = self.root.winfo_pointery()
        except Exception:
            return
        near = (py >= self.y - 10 and py <= self.y + cfg.WIN_H + 10)
        if self.edge_side == "left":
            shown_x = float(left)
            hover_edge = px <= left + 3
        else:
            shown_x = float(right - cfg.WIN_W)
            hover_edge = px >= right - 3
        # 判断鼠标是否在宠物窗口上（悬停时不小时藏）
        over_pet = (self.x <= px <= self.x + cfg.WIN_W
                    and self.y <= py <= self.y + cfg.WIN_H)
        if (hover_edge and near) or over_pet:
            self.edge_show_until = now + 2.0
        target = shown_x if now < getattr(self, "edge_show_until", 0) else self.edge_target_x
        if target is None:
            return
        dx = target - self.x
        if abs(dx) < 1.5:
            return
        # 每秒 900px 的平滑滑动
        step = max(-1.0, min(1.0, dx / 18.0)) * min(abs(dx), 900 * 0.04)
        self.x += step
        self._apply_geometry()

    def relayout_window(self):
        """挂件位置/开关变化后：重设窗口尺寸、宠物中心、精灵画布与装饰位置"""
        cfg = self.cfg
        self.root.geometry(f"{cfg.WIN_W}x{cfg.WIN_H}+{int(self.x)}+{int(self.y)}")
        self.canvas.config(width=cfg.WIN_W, height=cfg.WIN_H)
        self.renderer.cfg = cfg
        self.renderer.cache.clear()          # 画布宽度变了，缓存的精灵图要重做
        self.renderer.order.clear()
        # 重建装饰与挂件（位置依赖新的 PET_CX / WIN_W）
        for item in list(self.canvas.find_all()):
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self.pet_item = self.canvas.create_image(0, cfg.BUBBLE_ZONE, anchor="nw")
        self.decor = Decor(self.canvas, self.font_spec, cfg)
        self.decor.dpi = self.dpi
        self.particles = ParticleSystem(self.canvas, self.font_spec, cfg.KEY_COLOR)
        self.bubble_items = []
        self.bubble_raw = None
        self.widget.canvas = self.canvas
        self.widget.build()
        self._apply_geometry()
        log_event("WINDOW", f"重排窗口：{cfg.WIN_W}x{cfg.WIN_H} PET_CX={cfg.PET_CX}")

    def _on_widget_hover(self, x: float, y: float):
        """悬停挂件某一行 → 气泡显示详情（节流 2 秒）"""
        row = self.widget.hit(x, y)
        if row == self._widget_hover_row:
            return
        self._widget_hover_row = row
        now = time.time()
        if not row or now - self._widget_hover_t < 2.0:
            return
        self._widget_hover_t = now
        if row == "weather" and self.weather:
            w = self.weather
            if w.get("tmin") is not None and w.get("tmax") is not None:
                self.brain.show_text(
                    f"今天全天温度：最低{w['tmin']:.0f}℃ 最高{w['tmax']:.0f}℃", 3.4)
            else:
                self.brain.show_text(f"当前 {w.get('temp', 0):.0f}℃", 3.0)
        elif row == "net":
            self.brain.show_text(
                f"正在下载：{self.net.fmt_speed(self.net.in_kb)}　"
                f"上传：{self.net.fmt_speed(self.net.out_kb)}", 3.0)
        elif row == "clock":
            self.brain.show_text(time.strftime("现在是 %H:%M 哦～"), 2.6)
        elif row == "weather":
            self.do_weather_detail()          # 悬停无数据 / 点击 = 看详情或重试

    # ---------------- 养成面板 ----------------
    def _open_panel(self, cls):
        """打开养成面板（同一时间只留一个，重复打开就刷新并置顶）"""
        old = getattr(self, "_panel", None)
        if old is not None and old.winfo_exists():
            old.refresh()
            old.lift()
            old.focus_force()
            return old
        self._panel = cls(self.root, self)
        return self._panel

    def open_inventory(self):
        self._open_panel(InventoryPanel)

    def open_shop(self):
        self._open_panel(ShopPanel)

    def open_achievements(self):
        self._open_panel(AchievementPanel)

    def open_daily(self):
        self._open_panel(DailyPanel)

    # ---------------------------------------------------------------- 外出探险
    def open_adventure(self):
        """打开地点选择窗口（正在探险时显示倒计时与「提前回家」）"""
        self._open_panel(AdventurePanel)

    def open_quest_log(self):
        self._open_panel(QuestLogPanel)

    def _open_menu_more(self):
        """右键菜单第二页（不常用项 + 极简模式 / 尺寸切换）"""
        try:
            mx, my = self._bmenu.winfo_rootx(), self._bmenu.winfo_rooty()
        except Exception:
            mx = my = 200
        items = [("←", "返回", self._reopen_menu_first)] + list(self.menu_items_more)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        mw = self.cfg.MENU_W
        mh = (self.cfg.MENU_PAD * 2
              + sum((self.cfg.MENU_ROW_H if it[0] != "-" else 9) for it in items))
        mx = max(8, min(sw - mw - 8, mx))
        my = max(8, min(sh - mh - 44, my))
        self._bmenu = MenuWindow(self.root, self, items, mx, my)

    def _reopen_menu_first(self):
        try:
            mx, my = self._bmenu.winfo_rootx(), self._bmenu.winfo_rooty()
        except Exception:
            mx = my = 200
        items = list(self.menu_items) + [("⋯", "更多 ▸", self._open_menu_more)]
        self._bmenu = MenuWindow(self.root, self, items, mx, my)

    def toggle_ultra(self):
        """★ 极简模式：80px / 无装饰 / 无挂件 / 无粒子 / 半透明，桌面角标大小"""
        CFG.ULTRA_MODE = not CFG.ULTRA_MODE
        self.apply_ultra()
        self.brain.show_text("极简模式已开启～我变得很小很小" if CFG.ULTRA_MODE
                             else "极简模式关闭，我回来啦", 3.0)
        log_event("UI", f"极简模式：{CFG.ULTRA_MODE}")

    def apply_ultra(self):
        """应用极简模式相关设置（尺寸 / 装饰 / 挂件 / 粒子 / 气泡字号）"""
        cfg = self.cfg
        if cfg.ULTRA_MODE:
            self._size_before_ultra = getattr(self, "_size_before_ultra",
                                              cfg.PET_SIZE)
            cfg.set_pet_size(cfg.ULTRA_PET_SIZE)
            cfg.SHOW_WIDGETS = False
            cfg.PARTICLE_EFFECTS = False
            self.font_spec = (self.font_spec[0], cfg.ULTRA_BUBBLE_FONT)
            self.decor.set_alpha(0.0)
            self.widget.build()
            self.relayout_window()
        else:
            cfg.set_pet_size(getattr(self, "_size_before_ultra", cfg.DEFAULT_PET_SIZE))
            cfg.SHOW_WIDGETS = True
            cfg.PARTICLE_EFFECTS = True
            self.font_spec = (self.font_spec[0], CFG.FONT_SIZE)
            self.widget.build()
            self.relayout_window()
        self.autosave(force=True)

    def cycle_pet_size(self):
        """尺寸档位轮换：中 → 小 → 大 → 中"""
        cfg = self.cfg
        order = ["中", "小", "大"]
        cur = None
        for name, h in cfg.PET_SIZE_PRESETS.items():
            if h == cfg.PET_SIZE:
                cur = name
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "中"
        cfg.set_pet_size(cfg.PET_SIZE_PRESETS[nxt])
        if cfg.ULTRA_MODE:                    # 极简模式下改尺寸 → 自动退出极简
            cfg.ULTRA_MODE = False
            self.apply_ultra()
        else:
            self.relayout_window()
        self.brain.show_text(f"我变{nxt}号啦～（{cfg.PET_SIZE}px）", 2.4)
        self.autosave(force=True)
        log_event("UI", f"宠物尺寸 → {nxt} {cfg.PET_SIZE}px")

    # ================================================================
    # 第十二阶段：15 项扩展功能的运行时逻辑
    # ================================================================
    # ---------------- A2 相遇纪念日 ----------------
    def _anniversary_check(self):
        ex = self.stats.extra
        today = time.strftime("%Y-%m-%d")
        if not ex.first_day:
            ex.first_day = today
        # 满月（每月 1 号）→ 亲密度 +50
        if time.localtime().tm_mday == 1 and ex.diary_count() >= 0:
            key = f"month:{today[:7]}"
            if key not in ex.tips_seen:
                ex.tips_seen.append(key)
                self.stats.bond = min(CFG.BOND_MAX, self.stats.bond + 50)
                self.brain.show_text("今天是我们认识又满一个月啦！亲密度 +50", 4.0)
                log_event("EXTRA", f"满月纪念 {today} 亲密度 +50")
        # 周年（同月同日且不是第一年）
        try:
            y0, m0, d0 = (int(x) for x in ex.first_day.split("-"))
            t = time.localtime()
            if (t.tm_mon, t.tm_mday) == (m0, d0) and t.tm_year > y0:
                years = t.tm_year - y0
                if ex.anniv_seen != today:
                    ex.anniv_seen = today
                    self.stats.add_reward(coins=CFG.ANNIV_GIFT_COINS, bond=80,
                                          items={random.choice(CFG.GAME_RARE_POOL): 1},
                                          reason="相遇周年")
                    self.brain.show_text(f"今天是我们相遇第 {years} 周年！送你一份礼物～", 6.0)
                    self.brain.set_act(Act.HAPPY, 5.0)
                    self._anniv_burst()
                    log_event("EXTRA", f"周年纪念 {years} 周年，送礼完成")
        except Exception:
            pass

    def _anniv_burst(self):
        """撒花"""
        for _ in range(26):
            try:
                self.particles.spawn_stars(
                    self.cfg.PET_CX + random.uniform(-70, 70),
                    self.cfg.BUBBLE_ZONE + random.uniform(0, 60))
            except Exception:
                break

    # ---------------- A1 日记 ----------------
    def _diary_write_today(self, force: bool = False):
        ex = self.stats.extra
        today = time.strftime("%Y-%m-%d")
        if not force and ex.diary_has(today):
            return
        mins = int(max(1, (time.time() - getattr(self, "day_start", time.time())) / 60))
        happy_what = random.choice(DIARY_HAPPY_WHAT)
        regret_what = random.choice(DIARY_REGRET_WHAT)
        wish_what = random.choice(DIARY_WISH_WHAT)
        parts = [random.choice(DIARY_TIME_LINES).format(mins=mins),
                 random.choice(DIARY_HAPPY_LINES).format(what=happy_what)]
        # 依据真实状态微调「遗憾」
        if self.stats.sick:
            regret_what = "我生了一次病"
        if self.stats.bond < 100:
            regret_what = "主人太久没理我了"
        parts.append(random.choice(DIARY_REGRET_LINES).format(what=regret_what))
        parts.append(random.choice(DIARY_WISH_LINES).format(what=wish_what))
        emo = ex.emotion_today if ex.emotion_today in DIARY_EMOTION_LINES else ""
        if emo:
            parts.append(DIARY_EMOTION_LINES[emo])
        mood = emo or ("pos" if self.stats.happy > 60 else "normal")
        ex.diary_add(today, "".join(parts), mood)
        n = ex.diary_count()
        log_event("EXTRA", f"写下日记 {today}，共 {n} 篇")
        # 成就：7/30/100 篇
        for need in CFG.DIARY_ACHIEVEMENTS:
            aid = f"diary_{need}"
            if n >= need and aid not in self.stats.achievements:
                self.unlock_achievement(aid, f"日记 {need} 篇", coins=60)
        self.autosave(force=True)

    # ---------------- A4 记忆库 ----------------
    def _memory_extract(self, text: str):
        """
        从聊天里抠出值得记住的信息（纯规则，不联网）。
        覆盖：名字 / 生日 / 喜欢 / 讨厌 / 在忙 / 住哪 / 「要记住…」这类叮嘱。
        """
        ex = self.stats.extra
        if not text:
            return []
        t = str(text).strip()
        got = []

        def _save(topic: str, value: str):
            value = value.strip(" ，。！？、,.!?~～…\n\t")
            if not value or len(value) < 1:
                return
            ex.memory_add(topic, value[:60])
            got.append((topic, value[:60]))

        # ---- 「要记住」类叮嘱：整句（或关键词之后的部分）当备忘 ----
        for kw in ("要记住", "记住", "记一下", "记着", "别忘了", "别忘记",
                   "帮我记", "请你记", "记住我说"):
            idx = t.find(kw)
            if idx >= 0:
                rest = t[idx + len(kw):].lstrip(" 我你：:，,、")
                _save("备忘", rest if rest else t[:40])
                break

        # ---- 生日 ----
        for kw in ("生日是", "生日在", "生日是", "出生于", "生日"):
            idx = t.find(kw)
            if idx >= 0:
                rest = t[idx + len(kw):].lstrip(" 我你：:，,、")
                if rest:
                    _save("生日", rest)
                    break
        if not any(k == "生日" for k, _ in got):
            import re as _re
            m = _re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", t)
            if m:
                _save("生日", f"{int(m.group(1))} 月 {int(m.group(2))} 日")

        # ---- 名字 ----
        for kw in ("我叫", "我的名字是", "我的名字叫", "名字是", "叫我"):
            idx = t.find(kw)
            if idx >= 0:
                _save("名字", t[idx + len(kw):][:16])
                break

        # ---- 喜欢 / 讨厌 / 在忙 / 住哪 ----
        for topic, kws in (("喜欢", ("我喜欢", "我最喜欢", "我喜欢吃", "我喜欢喝",
                                     "我爱吃", "我爱喝", "最爱")),
                           ("讨厌", ("我讨厌", "我最讨厌", "我不喜欢", "我怕", "我害怕")),
                           ("在忙", ("我在忙", "最近在", "正在做", "在准备", "在写",
                                     "在上班", "在上学", "在学")),
                           ("住处", ("我住在", "我在", "我家在"))):
            for kw in kws:
                idx = t.find(kw)
                if idx >= 0:
                    frag = t[idx + len(kw):][:20]
                    if frag:
                        _save(topic, frag)
                    break

        if got:
            log_event("MEMORY", "记住：" + "；".join(f"{a}={b}" for a, b in got))
            self.autosave(force=True)
        return got

    def _memory_answer(self, text: str):
        """
        本地规则模式：用户问到记忆里的信息时，直接答出来（不用大模型）
        返回 None 表示没有命中，交给普通聊天逻辑。
        """
        ex = self.stats.extra
        if not ex.memory:
            return None
        t = str(text)
        asks = (("生日", ("生日", "哪一天", "几月几号")),
                ("名字", ("我叫什么", "我的名字", "我是谁", "怎么称呼我")),
                ("喜欢", ("我喜欢什么", "我喜欢吃什么", "我爱吃什么", "我喜欢啥")),
                ("讨厌", ("我讨厌什么", "我不喜欢什么")),
                ("在忙", ("我在忙什么", "最近在干什么", "我在做什么")))
        for topic, kws in asks:
            if any(k in t for k in kws):
                item = next((m for m in reversed(ex.memory)
                             if m.get("topic") == topic), None)
                if item:
                    return {"生日": f"你生日是{item['content']}呀，我记得的～",
                            "名字": f"你叫{item['content']}嘛，对不对～",
                            "喜欢": f"你喜欢{item['content']}，我记着呢～",
                            "讨厌": f"你讨厌{item['content']}，我会避开的～",
                            "在忙": f"你最近在{item['content']}吧？辛苦啦～",
                            }.get(topic)
                return "这个你还没告诉我呢，说说看？我记住了就不会忘～"
        # 用户提到自己「要记住」的内容，回应一句确认
        if any(k in t for k in ("要记住", "记住", "记着", "别忘了", "帮我记")):
            last = ex.memory[-1] if ex.memory else None
            if last:
                return f"记住啦！{last['topic']}：{last['content']}"
            return "好，我记住啦～"
        return None

    # ---------------- A5 情绪镜像 ----------------
    def _emotion_from_input(self, text: str) -> bool:
        """返回 True 表示识别到情绪（由 Brain 决定要不要接话）"""
        ex = self.stats.extra
        state, reply = ex.emotion_detect(text)
        if not state:
            return False
        now = time.time()
        if state != ex.emotion:
            ex.emotion = state
            ex.emotion_since = now
        ex.emotion_today = state
        if reply:
            self.brain.show_text(reply, 3.4)
        if state == "neg":
            self.brain.set_act(Act.SAD, 4.0)
        elif state == "pos":
            self.brain.set_act(Act.HAPPY, 3.0)
        elif state == "angry":
            self.brain.set_act(Act.SAD, 2.5)
        log_event("EMOTION", f"识别到情绪 {state}")
        return True

    def _emotion_tick(self, now: float):
        ex = self.stats.extra
        if ex.emotion != "neg":
            return
        if now - ex.emotion_since < CFG.EMOTION_HUG_AFTER:
            return
        if now - ex.emotion_last_hug < CFG.EMOTION_HUG_AFTER:
            return
        ex.emotion_last_hug = now
        self.stats.happy = min(100.0, self.stats.happy + CFG.EMOTION_HUG_BOND)
        self.brain.show_text("要不要抱一下？我在的哦。", 5.0)
        self.brain.set_act(Act.HAPPY, 4.0)
        log_event("EMOTION", "连续负面情绪 → 主动抱抱")

    # ---------------- B7 提醒 ----------------
    def _reminder_tick(self, now: float):
        ex = self.stats.extra
        if not ex.water_t:
            ex.water_t = now
        if not ex.sit_t:
            ex.sit_t = now
        if ex.water_on and now - ex.water_t >= CFG.WATER_REMIND_EVERY:
            ex.water_t = now
            self.brain.show_text("主人，该喝水啦～", 4.0)
            self._show_icon("cup", 6.0)
            log_event("REMIND", "喝水提醒")
        if ex.sit_on and now - ex.sit_t >= CFG.SIT_REMIND_EVERY:
            ex.sit_t = now
            self.brain.show_text("坐好久了，站起来走两步吧！", 4.5)
            log_event("REMIND", "久坐提醒")

    def _show_icon(self, kind: str, seconds: float):
        self.remind_icon = kind
        self.remind_until = time.time() + seconds

    def acknowledge_reminder(self):
        """点一下桌宠 = 我知道了，重置计时"""
        ex = self.stats.extra
        ex.water_t = ex.sit_t = time.time()
        if self.remind_icon:
            self.remind_icon = ""
            self.remind_until = 0.0
            self.brain.show_text("好的，我记住了～", 2.0)

    # ---------------- B9 系统监控 ----------------
    def sample_system(self, force: bool = False):
        now = time.time()
        if not force and now < self.sys_next:
            return
        self.sys_next = now + CFG.SYS_SAMPLE_EVERY
        info = dict(cpu=0.0, mem=0.0, mem_used=0.0, mem_total=0.0,
                    battery=-1, charging=False,
                    at=time.strftime("%H:%M:%S"))
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                info["mem"] = float(ms.dwMemoryLoad)
                info["mem_total"] = ms.ullTotalPhys / (1024 ** 3)
                info["mem_used"] = (ms.ullTotalPhys - ms.ullAvailPhys) / (1024 ** 3)
        except Exception:
            pass
        # CPU：用 GetSystemTimes 差分估算（不依赖 psutil）
        try:
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                            ("dwHighDateTime", ctypes.c_ulong)]

            def _ft(v):
                return (v.dwHighDateTime << 32) | v.dwLowDateTime

            idle, kern, user = FILETIME(), FILETIME(), FILETIME()
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
            if ok:
                i, k, u = _ft(idle), _ft(kern), _ft(user)
                prev = getattr(self, "_cpu_prev", None)
                if prev:
                    di, dk, du = i - prev[0], k - prev[1], u - prev[2]
                    total = dk + du
                    if total > 0:
                        info["cpu"] = max(0.0, min(100.0, 100.0 * (1 - di / total)))
                    else:
                        info["cpu"] = self.sys_info.get("cpu", 0.0)
                else:
                    info["cpu"] = 0.0
                self._cpu_prev = (i, k, u)
        except Exception:
            pass
        # 电池
        try:
            import ctypes

            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte),
                            ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte),
                            ("Reserved1", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong),
                            ("BatteryFullLifeTime", ctypes.c_ulong)]

            ps = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps)):
                if ps.BatteryLifePercent != 255:
                    info["battery"] = int(ps.BatteryLifePercent)
                    info["charging"] = ps.ACLineStatus == 1
        except Exception:
            pass
        self.sys_info = info
        log_event("SYS", f"CPU {info['cpu']:.0f}% 内存 {info['mem']:.0f}% "
                         f"电池 {info['battery']}%")

    def _system_tick(self, now: float):
        self.sample_system()
        info = self.sys_info or {}
        cpu = info.get("cpu", 0.0) / 100.0
        if cpu >= CFG.CPU_HIGH_RATIO:
            if not self.stats.extra.cpu_high_since:
                self.stats.extra.cpu_high_since = now
            elif now - self.stats.extra.cpu_high_since >= CFG.CPU_HIGH_HOLD:
                self.stats.extra.cpu_high_since = now          # 消化掉，避免刷屏
                self.brain.show_text("电脑好烫哦，少开点窗口吧", 4.0)
                self._show_icon("cup", 5.0)
        else:
            self.stats.extra.cpu_high_since = 0.0
        bat = info.get("battery", -1)
        if 0 <= bat < CFG.BATTERY_WARN and not info.get("charging"):
            if not self.stats.extra.battery_warned:
                self.stats.extra.battery_warned = True
                self.brain.show_text("电量低，记得插电源！", 4.5)
                self._show_icon("battery", 8.0)
        elif info.get("charging") or bat < 0 or bat >= CFG.BATTERY_WARN + 5:
            self.stats.extra.battery_warned = False

    # ---------------- D17 天赋 / D20 故事 ----------------
    def _talent_story_check(self):
        ex = self.stats.extra
        give = ex.talent_grant(self.stats.level)
        if give:
            self.brain.show_text(f"升级送天赋点啦！现在有 {ex.talent_points} 点可用", 4.5)
            log_event("TALENT", f"发放天赋点 {give}，累计可用 {ex.talent_points}")
        for ch in STORY_CHAPTERS:
            if self.stats.level >= ch["level"] and ch["level"] not in ex.story_read:
                ex.story_read.append(ch["level"])
                self.stats.add_reward(coins=CFG.STORY_COINS, bond=CFG.STORY_BOND,
                                      items={random.choice(CFG.GAME_RARE_POOL): 1},
                                      reason=f"章节 {ch['title']}")
                self.brain.show_text(f"解锁新故事：{ch['title']}", 5.0)
                log_event("STORY", f"解锁 {ch['title']}")
                try:
                    StoryPanel(self.root, self, chapter=ch)
                except Exception:
                    log_event("STORY", traceback.format_exc())
                break
        self.autosave()

    # ---------------- C11 图鉴解锁 hooks ----------------
    def codex_touch_inventory(self):
        ex = self.stats.extra
        for name in self.stats.inventory:
            ex.codex_unlock("item", name)
        for name in self.stats.adventure_collections:
            ex.codex_unlock("item", name)

    def codex_touch_places(self):
        ex = self.stats.extra
        for key in self.stats.adventure_location_exp:
            ex.codex_unlock("place", key)

    # ---------------- 主 tick ----------------
    def _extra_tick(self, now: float):
        ex = self.stats.extra
        # 23 点后写当天日记
        lt = time.localtime(now)
        today = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour >= CFG.DIARY_HOUR and self.diary_done_date != today:
            self.diary_done_date = today
            try:
                self._diary_write_today()
            except Exception:
                log_event("EXTRA", "写日记失败\n" + traceback.format_exc())
        self._reminder_tick(now)
        self._system_tick(now)
        self._emotion_tick(now)
        if self.remind_icon and now > self.remind_until:
            self.remind_icon = ""
        # 季节/节日粒子（低频）
        if now >= getattr(self, "_part_next", 0):
            self._part_next = now + 0.5
            ov = self.extra_ov
            if ov is None:
                return
            fest = festival_today(lt)
            season = ex.season_now(lt)
            ov.update_particles(now, (fest[2] if fest else
                                      (SEASONS[season]["particle"]
                                       if SEASONS[season]["particle"] != "sun" else "star")),
                                self.cfg.PET_CX)

    # ---------------- 渲染 ----------------
    def _extra_render(self, now: float, pose: dict):
        cfg = self.cfg
        ex = self.stats.extra
        ov = self.extra_ov
        if ov is None:
            return
        feet = cfg.WIN_H - cfg.BASE_LINE_GAP + pose["bob"]
        cx = cfg.PET_CX
        ps = max(0.45, min(1.6, cfg.pet_scale()))
        # 季节地面（在阴影之下）
        season = ex.season_now()
        ov.draw_ground(season, cx, feet)
        # 家具
        ov.draw_furniture(ex.placed, cx, feet)
        # 节日装饰
        ov.draw_festival(festival_today(), cx, feet)
        # ★ 装扮不再显示在奶蛙身上（按需求移除）：这里只做清场，避免历史图元残留。
        #   想恢复的话把 CFG.SHOW_OUTFIT 改回 True 即可，下面的绘制分支仍保留着。
        if cfg.SHOW_OUTFIT and ex.equipped_ids():
            try:
                pet_px = cfg.PET_HEIGHT * float(pose.get("scale", 1.0) or 1.0)
                ov.draw_outfit(ex.outfit, cx, feet, pet_px,
                               box=ov.asset_box(pose.get("asset", ""), pose.get("frame")),
                               flip=bool(pose.get("flip")),
                               asset=pose.get("asset", ""))
            except Exception:
                log_event("EXTRA", traceback.format_exc())
        else:
            ov.clear_outfit()
        # 待办便签
        pend = ex.todo_pending()
        if cfg.SHOW_TODO_NOTE and pend:
            ov.draw_todo_note([t["text"] for t in pend[:cfg.TODO_SHOW_MAX]], cx, feet)
        else:
            ov.draw_todo_note([], cx, feet)
        # 提醒图标
        if now < self.remind_until and self.remind_icon:
            ov.draw_icon(self.remind_icon, cx, feet)
        else:
            ov.clear_icons()
        # 已点天赋的小图标（贴在左肩）
        ov.clear_icons() if False else None
        self._draw_talent_icons(cx, feet)

    def _draw_talent_icons(self, cx: float, feet: float):
        """已点亮天赋在脚边显示小圆点（最多 9 个，用小字）"""
        ex = self.stats.extra
        ov = self.extra_ov
        if not ex.talents:
            for k in [k for k in ov.items if k.startswith("tal")]:
                ov._del(k)
            return
        mark = "".join({"效率": "⚡", "生存": "🛡", "互动": "💗"}.get(
            TALENTS[t]["branch"], "•") for t in ex.talents if t in TALENTS)
        ov._text("tal", cx - 62, feet - 16, mark[:9],
                 font=("Microsoft YaHei UI", 8), fill="#ff8f00")

    # ---------------- 打开各窗口 ----------------
    def open_diary(self):
        self._open_panel(DiaryPanel)

    def open_codex(self):
        self.codex_touch_inventory()
        self.codex_touch_places()
        self._open_panel(CodexPanel)

    def open_wardrobe(self):
        self._open_panel(WardrobePanel)

    def open_home(self):
        self._open_panel(HomePanel)

    def open_talents(self):
        self._open_panel(TalentPanel)

    def open_story(self):
        self._open_panel(StoryPanel)

    def open_memory(self):
        self._open_panel(MemoryPanel)

    def open_todo(self):
        self._open_panel(TodoPanel)

    def open_system(self):
        self.sample_system(force=True)
        self._open_panel(SystemPanel)

    def open_settings(self):
        """设置入口：挂件开关 + 尺寸 + 季节锁定"""
        try:
            dlg = tk.Toplevel(self.root)
            dlg.title("设置")
            dlg.configure(bg=CFG.UI_BG)
            dlg.attributes("-topmost", True)
            dlg.resizable(False, False)
            fam = self.font_spec[0]
            tk.Label(dlg, text="挂件 / 尺寸 / 季节", font=(fam, 11, "bold"),
                     bg=CFG.UI_BG, fg=CFG.UI_TEXT).pack(anchor="w", padx=14, pady=(12, 6))
            row = tk.Frame(dlg, bg=CFG.UI_BG)
            row.pack(fill="x", padx=14)
            for label, key in (("时钟", "SHOW_CLOCK"), ("天气", "SHOW_WEATHER"),
                               ("网速", "SHOW_NET_SPEED")):
                on = bool(getattr(CFG, key))
                tk.Button(row, text=f"{label}{'开' if on else '关'}",
                          font=(fam, 9), relief="flat", bg=CFG.UI_CARD,
                          width=8, cursor="hand2",
                          command=lambda k=key, b=row: self._toggle_cfg(k)
                          ).pack(side="left", padx=2)
            srow = tk.Frame(dlg, bg=CFG.UI_BG)
            srow.pack(fill="x", padx=14, pady=8)
            tk.Label(srow, text="季节：", font=(fam, 9), bg=CFG.UI_BG,
                     fg=CFG.UI_TEXT_DIM).pack(side="left")
            for key, spec in SEASONS.items():
                cur = self.stats.extra.season_now() == key
                b = tk.Button(srow, text=spec["name"], font=(fam, 9), relief="flat",
                              width=4, cursor="hand2",
                              bg=(CFG.UI_MAIN if cur else CFG.UI_CARD),
                              fg=("#ffffff" if cur else CFG.UI_TEXT),
                              command=lambda k=key: self._lock_season(k))
                b.pack(side="left", padx=2)
            tk.Button(srow, text="自动", font=(fam, 9), relief="flat",
                      bg=CFG.UI_CARD, cursor="hand2",
                      command=lambda: self._lock_season("")).pack(side="left", padx=2)
            tk.Button(dlg, text="关闭", font=(fam, 9), relief="flat",
                      bg=CFG.UI_BTN, padx=16, pady=4,
                      command=dlg.destroy).pack(anchor="e", padx=14, pady=(4, 12))
        except Exception:
            log_event("EXTRA", traceback.format_exc())

    def _toggle_cfg(self, key: str):
        setattr(CFG, key, not getattr(CFG, key))
        self.load_widget_config() if hasattr(self, "load_widget_config") else None
        try:
            self.widget.build()
            self.autosave(force=True)
        except Exception:
            pass
        self.open_settings()

    def _lock_season(self, key: str):
        self.stats.extra.season_override = key
        name = SEASONS[key]["name"] if key in SEASONS else "自动"
        self.brain.show_text(f"季节锁定：{name}" if key else "季节恢复自动啦", 3.0)
        self.autosave(force=True)

    def open_reminders(self):
        self._open_panel(ReminderPanel)

    def open_gacha(self):
        self._open_panel(GachaPanel)

    def _open_panel(self, cls, **kw):
        try:
            return cls(self.root, self, **kw)
        except Exception:
            log_event("EXTRA", f"打开 {cls.__name__} 失败\n" + traceback.format_exc())
            self.brain.show_text("这个窗口暂时打不开～", 2.5)
            return None

    # ---------------- 首次引导 ----------------
    def _extra_intro(self):
        ex = self.stats.extra
        if "extra_v1" in ex.tips_seen:
            return
        ex.tips_seen.append("extra_v1")
        self.root.after(4000, lambda: self.brain.show_text(
            "我有新本领啦！点右键看看～", 5.0))
        log_event("EXTRA", "新功能引导气泡")


    def open_games(self):
        """★ 第七阶段：打开小游戏选择面板"""
        self._open_panel(GameHubPanel)

    def start_adventure(self, spot_key: str, buffs=None) -> bool:
        """
        模块2：出发。扣精力 → 气泡 + happy 动图 → 按 CFG.ADVENTURE_MODE 决定表现方式。
        """
        if self._adv_cooldown_left() > 0:
            self.brain.show_text("刚回来，让我喘口气先～", 2.4)
            return False
        if not self.stats.start_adventure(spot_key, buffs):
            ok, msg = self.stats.adventure_can_start(spot_key)
            self.brain.show_text(msg or "现在出不去啦…", 2.6)
            return False
        spot = ADVENTURE_SPOTS[spot_key]
        self.brain.set_act(Act.HAPPY, 2.6, random.choice(ADV_LINES["depart"]), 2.6)
        self.brain.touch()
        self._adv_bar_pct = -1
        if CFG.ADVENTURE_MODE == "hide":       # 模式B：挪到右下角（仍可右键「提前回家」）
            self._adv_saved_pos = (self.x, self.y)
            left, top, right, bottom = self.bounds
            self.x = right - self.cfg.WIN_W - 8
            self.y = bottom - self.cfg.WIN_H - 8
            self._apply_geometry()
        self.autosave(force=True)
        log_event("ADVENTURE", f"UI 出发：{spot['name']} buff={buffs}")
        return True

    def _show_pending_adventure(self):
        """把「上次退出时未结算的探险」结果补展示出来"""
        result, self._pending_adv_result = self._pending_adv_result, None
        if not result:
            return
        self.brain.show_text(random.choice(ADV_LINES["return"]), 3.0)
        self._panel = AdventureResultPanel(self.root, self, result)

    def _celebrate_if_levelup(self) -> bool:
        """转发给 Brain 的升级反馈，并触发礼花庆祝（探险结算 / 背包使用物品都会用到）"""
        if self.brain._celebrate_if_levelup():
            self.burst_levelup()
            return True
        return False

    def _adv_cooldown_left(self) -> float:
        return max(0.0, getattr(self, "_adv_cooldown_until", 0.0) - time.time())

    def do_recall(self):
        """模块2/9：提前回家（收益减半）"""
        if not self.stats.adventure:
            self.brain.show_text("我就在家里呀～", 2.2)
            return
        self.brain.show_text(random.choice(ADV_LINES["early"]), 2.6)
        self._finish_adventure(early=True)

    def _adventure_tick(self, now: float):
        """
        主循环每帧调用：累趴判定 / 倒计时 / 头顶进度条（模块2）。
        用的是主线程的 after 循环，不开新线程 ✅
        """
        st = self.stats
        if not st.adventure:
            self._clear_adv_bar()
            return
        # 累到提前回家
        if st.energy < CFG.ADVENTURE_LOW_ENERGY and not st.adventure.get("halted"):
            st.halt_adventure()
            self.brain.show_text(random.choice(ADV_LINES["halted"]), 3.0)
            self._finish_adventure(early=True)
            return
        # 时间到 → 结算
        if st.adventure_remaining() <= 0:
            self._finish_adventure()
            return
        self._draw_adv_bar(st.adventure_progress())

    def _draw_adv_bar(self, p: float):
        """模块2 模式A：画一条进度条（纯 tkinter canvas 图元，不碰像素）"""
        if CFG.ADVENTURE_MODE != "bar":
            return
        pct = int(p * 100)
        if abs(pct - getattr(self, "_adv_bar_pct", -1)) < 1:
            return                                   # 百分比没变就不重画，避免闪烁
        self._adv_bar_pct = pct
        self._clear_adv_bar()
        cfg = self.cfg
        y0 = cfg.WIN_H - 15
        x0 = int(cfg.PET_CX - 100)
        x1 = int(cfg.PET_CX + 100)
        c = self.canvas
        items = [c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y0 + 10,
                                    fill="#ffffff", outline="#c9a44a", width=2)]
        if pct > 0:
            items.append(c.create_rectangle(x0, y0, x0 + int((x1 - x0) * p), y0 + 8,
                                            fill="#ffd23f", outline=""))
        items.append(c.create_text((x0 + x1) // 2, y0 + 4, text=f"探险中 {pct}%",
                                   font=(self.font_spec[0], 8), fill="#6b4f10"))
        self._adv_items = items

    def _clear_adv_bar(self):
        for item in getattr(self, "_adv_items", []):
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._adv_items = []

    def _finish_adventure(self, early: bool = False) -> dict:
        """结算：生成结果 → 气泡 → 弹出结算窗口（主线程）"""
        result = self.stats.finish_adventure(early=early)
        self._clear_adv_bar()
        self._adv_bar_pct = -1
        self._adv_cooldown_until = time.time() + CFG.ADVENTURE_COOLDOWN   # 防刷冷却
        if CFG.ADVENTURE_MODE == "hide" and getattr(self, "_adv_saved_pos", None):
            self.x, self.y = self._adv_saved_pos            # 回到原来的位置
            self._apply_geometry()
            self._adv_saved_pos = None
        if not result:
            return {}
        self.brain.show_text(random.choice(ADV_LINES["return"]), 3.0)
        self.brain.set_act(Act.HAPPY, 3.0)
        self.stats.happy = min(100.0, self.stats.happy + 5)
        self._celebrate_if_levelup()
        self.autosave(force=True)
        old = getattr(self, "_panel", None)
        try:
            if old is not None and old.winfo_exists():
                old.destroy()
        except Exception:
            pass
        self._panel = AdventureResultPanel(self.root, self, result)
        return result

    def do_reset(self):
        """重置养成：二次确认后清空存档与所有养成数据（防误触）"""
        ConfirmDialog(
            self.root, "重置养成",
            "确定要重置吗？\n\n等级、经验、金币、背包、亲密度、成就、每日任务\n"
            "全部会清空，且无法恢复。\n（桌宠位置与状态不受影响）",
            self._do_reset_confirmed, self.font_spec)

    def _do_reset_confirmed(self):
        reset_savegame()
        self.stats.__init__()                    # 重新初始化养成与四维数据
        self.brain.stage_name, self.brain.stage_scale = growth_stage(self.stats.level)
        self.brain.pending_tips.clear()
        self.brain.show_text("全部清空啦…我们重新开始吧！", 3.4)
        log_event("RESET", "用户重置了养成数据")
        panel = getattr(self, "_panel", None)
        if panel is not None and panel.winfo_exists():
            panel.refresh()

    def open_chat(self):
        if self.brain.act == Act.SLEEP:
            self.brain.wake_up()
        ChatDialog(self.root, self._on_chat_submit, self.font_spec)

    # ---------------------------------------------------------------- 对话（含大模型）
    def _on_chat_submit(self, text: str):
        """
        统一的对话入口：
          · 先过一道「笑话节流」：绝大多数时候正常聊天，偶尔才插一个笑话
          · 大模型开启 → 显示「思考」动画（素材1）+ 后台线程请求，结果由 _drain_llm 回填
          · 大模型关闭 → 直接走本地关键词规则（零延迟）
        """
        self.brain.note_chat_message()
        # ★ 记忆库：每条消息都试着抠出可记的信息（生日/名字/喜好/「要记住…」）
        try:
            self._memory_extract(text)
        except Exception:
            log_event("MEMORY", traceback.format_exc())
        if self.brain.should_tell_joke():
            # 这一句不讲正事，改成主动讲个笑话（概率很低，见 CFG.CHAT_JOKE_CHANCE）
            self.brain.joke(from_chat=True)
            print(f"[聊天] 第 {self.brain.chat_msgs} 句 → 触发「偶尔讲个笑话」", flush=True)
            return
        if self.llm and not self.llm_busy:
            self.llm_busy = True
            self.brain.thinking("让我想想…")     # ★ 思考动画（素材1）
            threading.Thread(target=self._llm_worker, args=(text,),
                             name="llm-chat", daemon=True).start()
            if self.verbose:
                print(f"[聊天] 用户: {text} → 已请求 {self.llm_cfg.preset_name}", flush=True)
            return
        # ★ 本地模式：先看是不是在问记忆里的事，能答就直接答
        mem_reply = None
        try:
            mem_reply = self._memory_answer(text)
        except Exception:
            log_event("MEMORY", traceback.format_exc())
        if mem_reply:
            self.brain.show_text(mem_reply, 3.6)
            if self.verbose:
                print(f"[聊天] 用户: {text} → 记忆应答: {mem_reply}", flush=True)
            return
        reply = self.brain.chat(text)
        if self.verbose:
            print(f"[聊天] 用户: {text} → 本地规则: {reply}", flush=True)

    def _llm_worker(self, text: str):
        """后台线程：只做网络请求，绝不碰 Tk 控件。"""
        reply, err = None, ""
        try:
            _mem = ""
            try:
                _mem = self.stats.extra.memory_prompt(CFG.MEMORY_PROMPT_N)
            except Exception:
                _mem = ""
            reply = self.llm.chat(text, stats_line=self.brain.stats_line(),
                                  mood=self.stats.mood(), memory=_mem)
        except LLMError as exc:
            err = str(exc)
        except Exception as exc:                       # 兜底，绝不让线程炸掉
            err = f"未知异常：{exc}"
        self.llm_queue.put((text, reply, err))

    def _drain_llm(self):
        """主线程每帧检查一次：大模型回了就把气泡换掉，失败则降级到本地规则。"""
        while True:
            try:
                text, reply, err = self.llm_queue.get_nowait()
            except queue.Empty:
                return
            self.llm_busy = False
            if reply:
                self.stats.on_chat()
                self.brain.say_reply(reply)
                if self.verbose:
                    print(f"[聊天] {self.llm_cfg.preset_name} 回复: {reply}", flush=True)
            else:
                # ★ 降级策略：网络/鉴权/限流任何问题，都让宠物照常有反应
                fallback = self.brain.chat(text)
                self.brain.show_text(f"{fallback}", 3.0)
                print(f"[LLM] 调用失败，已降级为本地规则：{err}", flush=True)
                if self.verbose:
                    print(f"[提示] {self.llm_cfg.hint()}", flush=True)

    def toggle_llm(self):
        """右键菜单：运行时切换 AI 对话（现场演示对比「规则 vs 大模型」很好用）。"""
        if self.llm:
            self.llm = None
            self.llm_cfg.enabled = False
            self.brain.show_text("已切成简单模式～", 2.6)
        elif self.llm_cfg.api_key or self.llm_cfg.provider == "ollama":
            self.llm_cfg.enabled = True
            self.llm = LLMClient(self.llm_cfg, verbose=self.verbose)
            self.brain.show_text("AI 模式开启！", 2.6)
        else:
            self.brain.show_text("还没有配 Key 哦…", 3.0)
            print(f"[LLM] {self.llm_cfg.hint()}", flush=True)
            self.open_llm_setup()

    def open_llm_setup(self):
        """
        右键菜单「配置 API Key」：另起一个进程打开配置向导
        （独立进程 = 不用嵌套事件循环，桌宠本体不受影响；配好后重启桌宠生效）。
        """
        try:
            script = os.path.abspath(__file__)
            exe = sys.executable or "python"
            subprocess.Popen([exe, script, "--setup-llm"], cwd=app_dir(), close_fds=True)
            self.brain.show_text("配置好之后重启我就生效啦～", 3.4)
            log_event("LLM-SETUP", "从右键菜单打开配置向导")
        except Exception as exc:
            log_event("LLM-SETUP", f"打开向导失败: {exc}")
            self.brain.show_text("打开配置向导失败了…", 3.0)

    # ---------------------------------------------------------------- 存档（模块7）
    def load_progress(self):
        """
        启动时读取 savegame.json：
        等级/经验/金币/背包/亲密度/成就/每日任务/计数器/连续登录/桌宠位置
        """
        data = load_savegame()
        s = self.stats
        if data:
            s.level = int(data.get("level", 1))
            s.exp = int(data.get("exp", 0))
            s.coins = int(data.get("coins", CFG.COINS_START))
            s.bond = float(data.get("bond", 0.0))
            inv = data.get("inventory")
            if isinstance(inv, dict):
                s.inventory = {str(k): int(v) for k, v in inv.items() if int(v) > 0}
            ach = data.get("achievements")
            if isinstance(ach, dict):
                s.achievements = dict(ach)
            cnt = data.get("counters")
            if isinstance(cnt, dict):
                s.counters.update({k: v for k, v in cnt.items()})
            s.happy_seconds = float(data.get("happy_seconds", 0.0))
            s.streak_days = int(data.get("streak_days", 0))
            s.last_login_date = str(data.get("last_login_date", ""))
            s.daily_date = str(data.get("daily_date", ""))
            tasks = data.get("daily_tasks")
            if isinstance(tasks, list) and tasks:
                s.daily_tasks = [dict(t) for t in tasks]
            pos = data.get("position")
            if isinstance(pos, list) and len(pos) == 2:
                self.x, self.y = float(pos[0]), float(pos[1])
                self._apply_geometry()
            # ---- 第四阶段：探险数据（模块7 存档扩展）----
            s.adventure_total_count = int(data.get("adventure_total_count", 0))
            s.adventure_last_time = str(data.get("adventure_last_time", ""))
            s.animals_met = int(data.get("animals_met", 0))
            qs = data.get("adventure_quests")
            if isinstance(qs, dict):
                s.adventure_quests = {k: dict(v) for k, v in qs.items() if isinstance(v, dict)}
            col = data.get("adventure_collections")
            if isinstance(col, dict):
                s.adventure_collections = {str(k): int(v) for k, v in col.items()}
            # ---- 第七阶段字段 ----
            gc = data.get("game_play_count")
            if isinstance(gc, dict):
                s.game_play_count = {str(k): int(v) for k, v in gc.items()
                                     if isinstance(v, (int, float))}
            s.game_play_reset_date = str(data.get("game_play_reset_date", ""))
            s.game_double_until = float(data.get("game_double_until", 0) or 0)
        s.extra.from_dict(data)          # ★ 第十二阶段：15 项扩展状态
        gh = data.get("game_high")
        if isinstance(gh, dict):
            s.game_high = {}
            for k, v in gh.items():
                try:
                    s.game_high[str(k)] = float(v)
                except Exception:
                    pass
            le = data.get("adventure_location_exp")
            if isinstance(le, dict):
                s.adventure_location_exp = {str(k): int(v) for k, v in le.items()
                                            if isinstance(v, (int, float))}
            bp = data.get("adventure_buff_pending")
            if isinstance(bp, dict):
                s.adventure_buff_pending = dict(bp)
            s.adventure_offline_until = float(data.get("adventure_offline_until", 0) or 0)
            s.first_play_date = str(data.get("first_play_date", ""))
            # ★ 恢复上次选的宠物尺寸 / 极简模式
            _sz = data.get("pet_size")
            if isinstance(_sz, (int, float)) and 60 <= _sz <= 240:
                CFG.set_pet_size(int(_sz))
            if isinstance(data.get("ultra_mode"), bool):
                CFG.ULTRA_MODE = data["ultra_mode"]
            if not s.first_play_date:
                s.first_play_date = today_str()
            # ---- 离线衰减保护：只让饱食按比例慢慢掉 ----
            saved_ts = float(data.get("saved_at_ts", 0) or 0)
            if saved_ts > 0:
                hours = (time.time() - saved_ts) / 3600.0
                if hours > 0.05:
                    off = s.apply_offline_decay(hours)
                    if off.get("full_drop"):
                        self._offline_note = (
                            f"你不在的 {off['hours']:.1f} 小时里，我乖乖等着的～"
                            f"（饱食 -{off['full_drop']:.0f}）")
                    log_event("OFFLINE", f"离线 {hours:.2f} 小时，"
                                         f"饱食 -{off.get('full_drop', 0)}")
            adv = data.get("adventure_in_progress")
            if isinstance(adv, dict) and adv.get("spot") in ADVENTURE_SPOTS:
                # ★ 挂机化：按「结束时间戳」判定，而不是剩余秒数
                end_ts = float(adv.get("end_ts", 0) or 0)
                remain = float(adv.get("remain", 0))
                if end_ts > 0:
                    remain = max(0.0, end_ts - time.time())
                    remain = min(remain, CFG.ADVENTURE_OFFLINE_CAP)
                base = dict(spot=adv["spot"], start=time.time(),
                            duration=adv.get("duration", 30),
                            buffs=list(adv.get("buffs") or []),
                            halted=False, event_bonus=[],
                            boost=bool(adv.get("boost")))
                if remain <= 0.5 and CFG.ADVENTURE_OFFLINE_SETTLE:
                    # 挂机到点了：离线收益一次发放
                    s.adventure = dict(base, end=time.time())
                    log_event("ADVENTURE", "离线挂机结束 → 立即结算")
                    self._pending_adv_result = s.finish_adventure()
                elif CFG.ADVENTURE_SAVE_PARTIAL and end_ts <= 0:
                    # 关程序时还在外面 → 按「提前回来」结算一半收益
                    s.adventure = dict(base, end=time.time())
                    log_event("ADVENTURE", "上次退出时还在探险 → 按提前归来结算一半收益")
                    self._pending_adv_result = s.finish_adventure(early=True)
                else:
                    # 继续倒计时：把剩余时间平移到现在
                    s.adventure = dict(base, end=time.time() + max(1.0, remain))
                    log_event("ADVENTURE", f"继续上次的探险，还剩 {remain:.0f} 秒")
            log_event("SAVE", f"养成数据已载入：Lv.{s.level} 金币{s.coins} 亲密度{s.bond:.0f}")
        # ---- 跨天处理：连续登录 + 每日任务刷新 + 登录奖励 ----
        today = today_str()
        if s.last_login_date != today:
            if s.last_login_date and _day_gap(s.last_login_date, today) == 1:
                s.streak_days += 1
            else:
                s.streak_days = 1
            s.last_login_date = today
            s.first_today = False
            s.add_coins(CFG.COINS_DAILY_LOGIN)
            self.brain.queue_tip(f"今日登录奖励：+{CFG.COINS_DAILY_LOGIN} 金币"
                                 f"（连续 {s.streak_days} 天）")
            log_event("DAILY", f"新的一天：连续登录 {s.streak_days} 天")
        s.refresh_daily()                        # 没任务或跨天都会刷新

    def autosave(self, force: bool = False):
        """自动存档（默认每 AUTOSAVE_EVERY 秒一次；重要事件可 force）"""
        now = time.time()
        if not force and now - self.last_autosave < CFG.AUTOSAVE_EVERY:
            return
        self.last_autosave = now
        s = self.stats
        data = {
            "version": CFG.SAVE_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": s.level, "exp": s.exp, "coins": s.coins, "bond": round(s.bond, 2),
            "inventory": s.inventory, "achievements": s.achievements,
            "counters": s.counters, "happy_seconds": round(s.happy_seconds, 1),
            "streak_days": s.streak_days, "last_login_date": s.last_login_date,
            "daily_date": s.daily_date, "daily_tasks": s.daily_tasks,
            "position": [int(self.x), int(self.y)],
            # ---- 第四阶段：探险存档 ----
            "adventure_in_progress": (dict(
                spot=s.adventure.get("spot"),
                remain=round(s.adventure_remaining(), 1),
                end_ts=s.adventure.get("end", 0),          # ★ 时间戳：离线也继续计时
                duration=s.adventure.get("duration", 0),
                buffs=s.adventure.get("buffs") or [],
                boost=bool(s.adventure.get("boost")),
            ) if s.adventure else None),
            "adventure_quests": s.adventure_quests,
            "adventure_collections": s.adventure_collections,
            "adventure_total_count": s.adventure_total_count,
            "adventure_last_time": s.adventure_last_time,
            "animals_met": s.animals_met,
            # ---- 第七阶段：小游戏 + 挂机 ----
            "game_play_count": s.game_play_count,
            "game_play_reset_date": s.game_play_reset_date,
            "game_double_until": s.game_double_until,
            "game_high": s.game_high,
            **_extra_save_fields(s),
            "adventure_location_exp": s.adventure_location_exp,
            "adventure_buff_pending": s.adventure_buff_pending,
            "adventure_offline_until": s.adventure_offline_until,
            "first_play_date": s.first_play_date,
            "saved_at_ts": time.time(),
            # ---- 第十阶段：界面偏好 ----
            "pet_size": CFG.PET_SIZE,
            "ultra_mode": CFG.ULTRA_MODE,
            "compact": CFG.COMPACT,
        }
        if write_savegame(data):
            log_event("SAVE", f"已存档：Lv.{s.level} 经验{s.exp} 金币{s.coins} "
                              f"亲密度{s.bond:.0f} 成就{len(s.achievements)}")

    # ---------------------------------------------------------------- 退出
    def _on_escape(self, event=None):
        """Esc 不再退出程序（防误触）。改成让桌宠做个反应，方便确认它活着。"""
        log_event("KEY", "收到 Esc（已忽略，不会退出程序）")
        self.brain.show_text("按 Esc 我不会走的～右键菜单才能让我退出", 3.0)
        return "break"

    def _on_wm_close(self):
        """系统发的关闭消息（Alt+F4 等）—— 记一笔再退。"""
        log_event("QUIT", "WM_DELETE_WINDOW（系统关闭消息 / Alt+F4）")
        self.quit(reason="WM_CLOSE")

    def quit(self, reason: str = "右键菜单"):
        """
        唯一的退出入口。会把「谁调用的」写进日志，方便排查『桌宠自己跑了』这类问题。
        退出前一定保存养成数据（模块7）。
        """
        log_event("QUIT", f"原因={reason}\n调用栈:\n" + "".join(traceback.format_stack()[-6:]))
        try:
            self.autosave(force=True)
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        log_event("MAINLOOP", "进入 Tk 主循环")
        try:
            self.root.mainloop()
        finally:
            log_event("MAINLOOP-END", "mainloop 返回（窗口已销毁，程序即将退出）")


# ==============================================================================
# 10. 自检模式（--selftest）：不开窗口，验证素材管线 + 生成预览拼图
# ==============================================================================
def selftest(cfg=CFG) -> int:
    print("=" * 74)
    print(" 桌宠素材管线自检")
    print("=" * 74)
    if not HAVE_PIL:
        print("[失败] 未安装 Pillow。请执行:  pip install pillow")
        return 2
    print(f"Python : {sys.version.split()[0]}")
    print(f"Pillow : {Image.__version__}")
    print(f"素材目录: {os.path.join(app_dir(), 'assets')}")
    _llm = LLMConfig.load()
    print(f"AI 对话 : {_llm.describe()}")
    if not _llm.enabled:
        print(f"         开启方法 → {_llm.hint()}")
    print("-" * 74)

    lib = AssetLibrary(cfg)
    t0 = time.time()
    lib.prepare_sync()
    t_static = time.time() - t0
    t1 = time.time()
    lib._load_all_gifs()
    t_gif = time.time() - t1

    ok = True
    for name in ASSETS:
        frames = lib.get(name)
        durs = lib.durations(name)
        path = lib.paths.get(name, "(未找到)")
        spec = ASSETS[name]
        optional = bool(spec.get("optional"))
        procedural = spec.get("kind") == "procedural"
        if frames:
            state = "程序" if procedural else "OK "
        else:
            state = "可选" if optional else "缺失"
            if not optional and not procedural:
                ok = False
        size_txt = str(frames[0].size) if frames else "-"
        src_txt = "程序化生成" if procedural else os.path.basename(path)
        print(f"[{state}] {name:12s} 帧数={len(frames):3d} 尺寸={size_txt:>10s} "
              f"档位={spec['profile']:6s} 来源={src_txt}")
        if durs and len(set(durs)) > 1:
            print(f"        帧间隔(ms) 示例: {durs[:6]}...")
    print("-" * 74)
    print(f"静态素材耗时 {t_static * 1000:.0f} ms ；动图解码 {t_gif:.2f} s "
          f"（缓存目录: {lib.cache_root}）")

    # 生成预览拼图（每个素材取第 1 帧 + 动图多取几帧），用来肉眼验收抠图效果
    try:
        tiles = []
        for name in ASSETS:
            fr = lib.get(name)
            if not fr:
                continue
            if ASSETS[name]["kind"] == "gif" and len(fr) > 3:
                step = max(1, len(fr) // 3)
                tiles += fr[::step][:3]
            else:
                tiles.append(fr[0])
        if tiles:
            pad, key = 8, SpriteRenderer._hex_to_rgb(cfg.KEY_COLOR)
            W = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
            H = max(t.height for t in tiles) + pad * 2
            sheet = Image.new("RGB", (W, H), key)
            x = pad
            for t in tiles:
                sheet.paste(SafeImageOps.keyed_rgb(t, key), (x, pad))
                x += t.width + pad
            out = os.path.join(lib.cache_root, "preview.png")
            os.makedirs(lib.cache_root, exist_ok=True)
            sheet.save(out)
            print(f"预览拼图已保存（共 {len(tiles)} 格）: {out}")
    except Exception as exc:
        print("[提示] 预览拼图生成失败（不影响运行）:", exc)

    for w in lib.warnings:
        print("[提示]", w)
    print("=" * 74)
    return 0 if ok else 1


# ==============================================================================
# 11. 入口
# ==============================================================================
def apply_forced_stats(pet, spec: str, sick: bool = False):
    """
    --stats happy=10,full=0,… / --sick：直接设定初始状态。
    给现场演示用：想演哪个表情就演哪个，不用干等状态自然掉下去。
    """
    if sick:
        pet.stats.sick = True
    if not spec:
        return
    for part in spec.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip().lower()
        try:
            val = float(v.strip())
        except ValueError:
            continue
        key = {"happy": "happy", "心情": "happy", "mood": "happy",
               "full": "full", "饱食": "full", "food": "full",
               "energy": "energy", "精力": "energy",
               "bored": "bored", "无聊": "bored"}.get(k)
        if key:
            setattr(pet.stats, key, val)
        elif k in ("level", "等级", "lv"):          # 养成系统也支持演示
            pet.stats.level = max(1, min(CFG.LEVEL_MAX, int(val)))
        elif k in ("coins", "金币"):
            pet.stats.coins = max(0, int(val))
        elif k in ("bond", "亲密度"):
            pet.stats.bond = max(0.0, min(CFG.BOND_MAX, val))
    pet.stats.clamp()
    pet.stats.level = max(1, min(CFG.LEVEL_MAX, pet.stats.level))
    pet.brain.stage_name, pet.brain.stage_scale = growth_stage(pet.stats.level)
    log_event("STATS", f"强制初始状态 {spec} sick={sick}")
    print(f"[演示模式] 初始状态已设定：{spec or ''} {'（生病）' if sick else ''}"
          f"　Lv.{pet.stats.level}（{pet.brain.stage_name}）", flush=True)


def preflight_assets(show_gui=True) -> int:
    """
    启动前素材预检：返回缺失的「必需」素材名列表。
    缺了就用中文说清楚缺什么、放哪里，避免用户看到一只空白蛙。
    """
    missing = []
    for name, spec in ASSETS.items():
        if spec.get("kind") == "procedural":
            continue
        if spec.get("optional"):
            continue
        try:
            if find_asset(name, spec.get("names") or []) is None:
                missing.append(name)
        except Exception:
            missing.append(name)
    if not missing:
        return []
    base = app_dir()
    lines = [
        "找不到这些宠物素材：" + "、".join(missing),
        "",
        f"请把素材放在：{os.path.join(base, 'assets')}\\",
        "需要的文件名：" + "、".join(
            os.path.basename((ASSETS[n].get("names") or ["?"])[0]) for n in missing),
        "",
        "常见原因：",
        "  1) 只把 desktop_pet.py 拷出来了，没有带上 assets 文件夹",
        "  2) 解压时少解了 assets 目录",
        "  3) 素材被改名了（程序只认 pet_idle.webp 这类标准名）",
    ]
    msg = "\n".join(lines)
    print("=" * 74, flush=True)
    print(msg, flush=True)
    print("=" * 74, flush=True)
    try:
        log_event("ASSET-MISS", "启动预检缺素材: " + ", ".join(missing))
    except Exception:
        pass
    if show_gui:
        try:
            import tkinter as _tk
            from tkinter import messagebox
            _r = _tk.Tk()
            _r.withdraw()
            messagebox.showwarning("桌面奶蛙 · 缺少素材", msg)
            _r.destroy()
        except Exception:
            pass
    return missing


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="桌面桌宠 Desktop Pet（单文件 Demo）")
    parser.add_argument("--selftest", action="store_true", help="只跑素材管线自检，不开窗口")
    parser.add_argument("--height", type=int, default=CFG.PET_HEIGHT, help="宠物显示高度(px)")
    parser.add_argument("--pos", type=str, default="", help="初始位置，例如 100,600")
    parser.add_argument("--verbose", action="store_true", help="控制台输出状态机日志")
    # ---- 大模型对接参数 ----
    parser.add_argument("--llm", choices=["auto", "on", "off"], default="auto",
                        help="大模型开关：auto=有Key就开(默认) / on=强制开 / off=纯本地规则")
    parser.add_argument("--llm-provider", default="",
                        help="厂商：" + " / ".join(PROVIDER_PRESETS.keys()))
    parser.add_argument("--llm-key", default="", help="API Key（不填则读环境变量或 config.json）")
    parser.add_argument("--llm-model", default="", help="模型名，例如 deepseek-chat")
    parser.add_argument("--llm-base-url", default="", help="自定义 OpenAI 兼容地址")
    parser.add_argument("--llm-test", default=None, metavar="TEXT",
                        help="只测大模型接口（不开窗口），例如 --llm-test 你好")
    parser.add_argument("--setup-llm", action="store_true",
                        help="打开图形化的 API Key 接入向导")
    parser.add_argument("--set-llm-key", default=None, metavar="KEY",
                        help="命令行接入 Key：写入 config.json 并自动测试连通性")
    parser.add_argument("--llm-workspace", default="", help="阿里云百炼 Workspace（ws-xxxxxxxx）")
    parser.add_argument("--llm-region", default="", help="阿里云百炼地域，默认 cn-beijing")
    parser.add_argument("--no-test", action="store_true", help="配合 --set-llm-key：只保存不测试")
    parser.add_argument("--stats", default="", metavar="K=V,...",
                        help="强制初始状态，方便演示，例如 --stats happy=10,full=0,energy=5,bored=90")
    parser.add_argument("--sick", action="store_true", help="启动时就让奶蛙生病（演示治疗）")
    parser.add_argument("--adv", default="", metavar="SPOT",
                        help="启动后自动出发探险，演示用：park/street/bigpark/forest")
    args = parser.parse_args(argv)

    install_diagnostics()                  # ★ 先装黑匣子，后面任何死法都会留痕

    try:                                   # Windows 控制台中文输出
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 大模型配置（命令行 > 环境变量 > config.json）
    llm_cfg = LLMConfig.load(cli=dict(
        mode=args.llm,
        provider=args.llm_provider or None,
        api_key=args.llm_key or None,
        model=args.llm_model or None,
        base_url=args.llm_base_url or None,
    ))

    # ---- 图形化 API Key 接入向导 ----
    if args.setup_llm:
        try:
            return run_llm_setup()
        except Exception:
            err = traceback.format_exc()
            log_event("FATAL", err)
            show_fatal("配置向导打开失败", err[-1200:])
            return 1

    # ---- 命令行接入 Key（写 config.json + 测试）----
    if args.set_llm_key is not None:
        provider = (args.llm_provider or "deepseek").lower()
        if provider not in PROVIDER_PRESETS:
            print(f"[错误] 未知厂商 {provider}，可选：{' / '.join(PROVIDER_PRESETS)}")
            return 2
        return llm_set_key_cli(provider, args.set_llm_key, args.llm_model or "",
                               args.llm_base_url or "", do_test=not args.no_test,
                               workspace=args.llm_workspace, region=args.llm_region)

    # ---- 只测接口模式 ----
    if args.llm_test is not None:
        print("=" * 74)
        print(f" 大模型连通性自检  |  厂商={llm_cfg.preset_name}  模型={llm_cfg.model}")
        print(f" 地址={llm_cfg.base_url}  Key来源={llm_cfg.key_source}")
        print("=" * 74)
        if not llm_cfg.api_key and llm_cfg.provider != "ollama":
            print("[跳过] 没有检测到 API Key。")
            print(f"       {llm_cfg.hint()}")
            return 3
        client = LLMClient(llm_cfg, verbose=True)
        t0 = time.time()
        try:
            reply = client.test(args.llm_test)
        except LLMError as exc:
            print(f"[失败] {exc}")
            print(f"       排查：{llm_cfg.hint()}")
            return 1
        print(f"[成功] 耗时 {time.time() - t0:.2f}s")
        print(f"用户: {args.llm_test}")
        print(f"桌宠: {reply}")
        return 0

    # 配置文件里可以顺便改宠物大小
    CFG.PET_HEIGHT = max(80, min(360, args.height))
    CFG.WIN_H = CFG.SPRITE_H + CFG.BUBBLE_ZONE

    if args.selftest:
        return selftest(CFG)

    if not HAVE_PIL:
        show_fatal("桌宠启动失败：缺少 Pillow",
                   "没有找到 Pillow 图像库，无法加载宠物素材。\n\n"
                   "请在本窗口执行：\n    pip install pillow\n\n"
                   "或者直接双击「启动桌宠.bat」，它会自动安装。")
        return 2

    pos = None
    if args.pos:
        try:
            a, b = args.pos.split(",")
            pos = (int(a), int(b))
        except Exception:
            print("[提示] --pos 格式应为 100,600，已忽略")

    print("=" * 74)
    print(" 桌宠启动中…  左键单击/拖拽/长按抚摸 · 右键菜单 · 悬停歪头 · Ctrl+C 或右键退出")
    print(f" AI 对话：{llm_cfg.describe()}")
    if not llm_cfg.enabled:
        print(f" （想开启：{llm_cfg.hint()}）")
    else:
        print(f" （Key 来源：{llm_cfg.key_source}）")
    print("=" * 74)
    try:
        preflight_assets()                             # ★ 启动前素材预检（缺了就提示）
        load_widget_config()                          # ★ 读 config.json 的挂件/城市设置
        pet = DesktopPet(CFG, verbose=args.verbose, start_pos=pos, llm_cfg=llm_cfg)
        apply_forced_stats(pet, args.stats, args.sick)     # 演示模式：强制初始状态
        if args.adv:                                       # 演示模式：自动出发探险
            pet.root.after(1500, lambda: pet.start_adventure(args.adv))
        pet.run()
    except KeyboardInterrupt:
        log_event("EXIT", "用户 Ctrl+C 中断")
        pass
    except Exception:
        # ★ 无控制台时（pythonw / 双击启动）把异常弹窗出来，避免「一闪而过」
        err = traceback.format_exc()
        log_event("FATAL", err)
        show_fatal("桌宠启动失败", "启动过程中发生错误：\n\n" + err[-1500:])
        return 1
    log_event("EXIT", "正常退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
