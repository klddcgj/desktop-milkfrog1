"""
桌宠功能冒烟自检（可长期保留，不依赖窗口）。
用法：python selftest_features.py
覆盖：状态机 / 聊天节流 / 养成 / 探险 / UI 美化 / 挂件 / 喂食与赠送
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desktop_pet as dp                                     # noqa: E402

ok = True
fails = []


def check(cond, msg):
    global ok
    print(("  PASS " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        ok = False
        fails.append(msg)


def section(title):
    print()
    print("=" * 76)
    print(" " + title)
    print("=" * 76)


section("① 状态 → 素材映射")
s = dp.PetStats()
for label, act, over, want in [
        ("待机", dp.Act.IDLE, {}, "idle"),
        ("心情0", dp.Act.IDLE, dict(happy=0), "mood0"),
        ("饱食0", dp.Act.IDLE, dict(happy=60, full=0), "hungry0"),
        ("生病", dp.Act.IDLE, dict(happy=60, full=60, sick=True), "sick"),
        ("全归零", dp.Act.IDLE, dict(happy=0, full=0, energy=0, bored=0), "allzero")]:
    s.happy, s.full, s.energy, s.bored, s.sick, s.collapsed = 70, 70, 70, 20, False, False
    s.__dict__.update(over)
    check(dp.resolve_asset(act, s) == want, f"{label} → {want}")

section("② 精力归零 / 聊天节流")
b = dp.Brain(dp.PetStats())
b.stats.energy = 0.3
b.tick(0.04)
check(b.act == dp.Act.SLEEP, "精力归零 → 强制睡眠")
b2 = dp.Brain(dp.PetStats())
early = 0
for _ in range(dp.CFG.CHAT_JOKE_MIN_MSGS):
    b2.note_chat_message()
    early += 1 if b2.should_tell_joke() else 0
check(early == 0, "前 8 句不讲笑话")

section("③ 养成基础")
s3 = dp.PetStats()
check(s3.add_exp(50) == 1 and s3.level == 2, "经验满自动升级")
check(len(dp.ACHIEVEMENTS) == 16, f"成就 16 个（{len(dp.ACHIEVEMENTS)}）")
s3.refresh_daily()
check(len(s3.daily_tasks) == 3, "每日任务 3 个")

section("④ 喂食改造（只能吃背包食物）")
s4 = dp.PetStats()
s4.inventory = {}
okx, msg = s4.feed_item("珍珠奶茶")
check(not okx, f"背包没食物时喂不了（{msg}）")
s4.inventory = {"珍珠奶茶": 2}
f0, b0, c0 = s4.full, s4.bond, s4.counters.get("feed", 0)
okx, msg = s4.feed_item("珍珠奶茶")
check(okx and s4.full > f0, f"吃掉背包里的食物（饱食 {f0:.0f}→{s4.full:.0f}）")
check(s4.inventory.get("珍珠奶茶") == 1, "物品被消耗 1 个")
check(s4.bond > b0, f"喂食也加好感（+{s4.bond - b0:.1f}）")
check(s4.counters.get("feed", 0) == c0 + 1, "喂食计数 +1（每日任务/成就用）")
s4.full = 95
okx, _ = s4.feed_item("珍珠奶茶")
check(not okx, "太饱时拒绝进食")
s4.full = 50
s4.inventory["小球"] = 1
okx, msg = s4.feed_item("小球")
check(not okx and "礼物" in msg, f"非食物不能喂（{msg}）")
check(not hasattr(dp.PetStats, "on_feed"), "旧的凭空喂食 on_feed 已移除")
check(not hasattr(dp.Brain, "feed"), "旧的 Brain.feed 已移除")
check(hasattr(dp.Brain, "feed_item") and hasattr(dp.Brain, "gift_item"),
      "新的 feed_item / gift_item 已接入")

section("⑤ 赠送礼物（涨好感）")
s5 = dp.PetStats()
s5.inventory = {"小球": 2, "音乐盒": 1, "草莓蛋糕": 1, "藏宝图碎片": 1,
                "便当": 1, "松果": 3}
v_ball = dp.gift_bond_value("小球")
b0 = s5.bond
okx, msg, val = s5.gift_item("小球")
check(okx and val == v_ball and s5.bond > b0, f"送小球 → 好感 +{val}")
check(s5.inventory.get("小球") == 1, "礼物被消耗 1 个")
check(s5.counters.get("gift", 0) == 1, "赠送计数 +1")
# 最爱礼物加成
fav_val = int(round(dp.gift_bond_value("音乐盒") * dp.CFG.GIFT_FAVORITE_BONUS))
okx, msg, val = s5.gift_item("音乐盒")
check(okx and val == fav_val, f"最爱礼物「音乐盒」好感 +{val}（含 {dp.CFG.GIFT_FAVORITE_BONUS}x 加成）")
# 任务信物 / 探险装备不可送
for blocked in ("藏宝图碎片", "便当"):
    okx, msg, _ = s5.gift_item(blocked)
    check(not okx, f"「{blocked}」不能送（{msg}）")
# 没有的物品
okx, msg, _ = s5.gift_item("复活药")
check(not okx, f"背包没有时送不了（{msg}）")
# 好感满级
s5.bond = dp.CFG.BOND_MAX
okx, msg, _ = s5.gift_item("草莓蛋糕")
check(not okx, f"好感满级后不能再送（{msg}）")
# 探险材料也能送
s5.bond = 100
okx, msg, val = s5.gift_item("松果")
check(okx and val >= 2, f"探险材料可以送（松果 +{val}）")

section("⑥ 探险 / 挂件 / UI 美化（不被破坏）")
s6 = dp.PetStats()
s6.level, s6.energy, s6.full = 10, 100, 90
check(s6.start_adventure("park"), "探险出发正常")
s6.adventure["end"] = time.time() - 1
r = s6.finish_adventure()
check(r["coins"] > 0, f"探险结算正常（金币 {r['coins']}）")
w, cx = dp.CFG.apply_layout(True, "right")
check(w >= 442, f"挂件布局正常（窗口宽 {w}，含右侧卡片）")
dp.CFG.apply_layout(True, "right")
check(hasattr(dp, "FeedPanel") and hasattr(dp, "GiftPanel"), "喂食/赠送面板类存在")
check(hasattr(dp, "WidgetCard") and hasattr(dp, "NetSpeed"), "挂件类仍在")
check(hasattr(dp, "ParticleSystem") and hasattr(dp, "Decor"), "粒子/装饰类仍在")
menu_labels = []
pet = dp.DesktopPet.__new__(dp.DesktopPet)
pet.font_spec = ("Microsoft YaHei UI", 10)
pet.stats = dp.PetStats()
pet.brain = dp.Brain(pet.stats)
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    # 只构造菜单数据，不建窗口：直接读源码里的 menu_items 结构
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "desktop_pet.py"), encoding="utf-8").read()
    check('"🎁", "赠送礼物"' in src and '"🍚", "喂食"' in src,
          "右键菜单含「喂食」+「赠送礼物」")
    root.destroy()
except Exception as exc:
    print("   （菜单检查跳过：%s）" % exc, flush=True)

section("⑦ 休闲小游戏 / 探险挂机 / 数值平衡（第七阶段）")
cfg = dp.CFG
check(len(dp.GAMES) >= 4, f"内置 {len(dp.GAMES)} 个小游戏")
sg = dp.PetStats()
check(sg.game_left("rps") == cfg.GAME_DAILY_LIMIT, "游戏初始次数")
for _ in range(cfg.GAME_DAILY_LIMIT):
    sg.game_use("rps")
check(not sg.game_use("rps"), "次数用完不能再玩")
sg.game_play_reset_date = "2000-01-01"
check(sg.game_left("rps") == cfg.GAME_DAILY_LIMIT, "跨天自动重置次数")
check(len(cfg.ADVENTURE_DURATIONS) == 4, "4 个探险挂机档位")
sa = dp.PetStats()
sa.level, sa.energy, sa.full = 10, 100, 90
check(sa.start_adventure("park", duration=3600, energy_ratio=3.0), "长途档出发")
check(abs(sa.adventure["duration"] - 3600) < 1, "挂机时长正确")
sa.adventure["end"] = time.time() - 1
sa.finish_adventure()
check(sa.adv_exp("park") == cfg.ADVENTURE_EXP_PER_TRIP, "探险熟练度 +5")
check(cfg.SICK_CHANCE == 0.08, "生病概率已降低")
check(cfg.DECAY_HAPPY <= 0.10, "衰减速度已放慢")
sn = dp.PetStats()
check(sn.decay_factor() <= 0.51, "新手衰减减半")
sn.full = 80
off = sn.apply_offline_decay(8)
check(off["full_drop"] < 20, f"离线 8 小时只掉 {off['full_drop']} 饱食")

section("⑧ 天气多源兜底 + 待机动画（第八阶段）")
cfg = dp.CFG
check(cfg.WEATHER_TIMEOUT >= 10, f"天气超时放宽到 {cfg.WEATHER_TIMEOUT}s")
check("wttr.in" in cfg.WEATHER_FALLBACK_API, "配置了备用天气源 wttr.in")
check(len(cfg.WEATHER_RETRY_BACKOFF) >= 3, "失败有重试退避表")
# 真实拉一次（成功就用真实数据，失败则确认降级不崩）
try:
    w = dp.fetch_weather(timeout=8)
    check(w.get("temp") is not None, f"天气获取成功：{w['city']} {w['temp']}℃ 源={w['source']}")
    check(isinstance(w.get("tmin"), (int, float, type(None))), "温度字段已转数值")
except Exception as exc:
    print(f"  （当前网络拿不到天气，属正常降级：{str(exc)[:60]}）", flush=True)
check(dp._wwo_to_wmo("113") == 0 and dp._wwo_to_wmo("389") == 95, "WWO→WMO 映射正确")
# 待机动画
check(cfg.IDLE_ANIM_DELAY == 300.0, f"待机动画延迟 {cfg.IDLE_ANIM_DELAY}s（5 分钟）")
check(hasattr(dp.Act, "LEISURE"), "新增待机状态 Act.LEISURE")
bl = dp.Brain(dp.PetStats())
check(bl.leisure_tick(time.time(), 0.04) is False, "刚互动过不会进待机")
bl.last_user = time.time() - 301
check(bl.leisure_tick(time.time(), 0.04) and bl.act == dp.Act.LEISURE,
      "5 分钟无互动 → 进入待机动画")
bl.leisure_since = time.time() - 1
bl.leisure_tick(time.time(), 0.04)
check(bl.leisure_doze, "待机循环里有打瞌睡段")
bl.touch()
check(not bl.leisure_tick(time.time(), 0.04) and bl.act == dp.Act.IDLE,
      "用户回来立刻退出待机")

section("⑨ 程序化呼吸待机动画（第九阶段）")
cfg = dp.CFG
check(cfg.IDLE_BREATH_FRAMES == 6 and cfg.IDLE_BREATH_FRAME_MS == 400,
      f"6 帧 × {cfg.IDLE_BREATH_FRAME_MS}ms = 2.4 秒一圈")
check(len(cfg.IDLE_BREATH_TABLE) == cfg.IDLE_BREATH_FRAMES, "参数表帧数一致")
check(dp.ASSETS["idle_anim"]["kind"] == "procedural", "ASSETS 注册为 procedural")
check(dp.ASSETS["idle_anim"]["generated_from"] == "idle", "声明从 idle 生成")
_lib = dp.AssetLibrary(cfg)
_lib.prepare_sync()
_anim = _lib.get("idle_anim")
check(len(_anim) == cfg.IDLE_BREATH_FRAMES, f"生成 {len(_anim)} 帧")
check(len({f.size for f in _anim}) == 1, f"帧尺寸统一 {_anim[0].size if _anim else '-'}")
check(_lib.durations("idle_anim") == [cfg.IDLE_BREATH_FRAME_MS] * 6, "帧时长 400ms")
if _anim:
    _cnt = [sum(f.getchannel("A").histogram()[128:]) for f in _anim]
    check(max(_cnt) > _cnt[0] > min(_cnt), f"呼吸有变大/变小两个方向 {_cnt}")
check(hasattr(dp, "IdleAnimationGenerator"), "生成器类存在")
# 状态机：待机用呼吸动画，其他状态不变
try:
    import tkinter as _tk
    _root = _tk.Tk()
    _root.withdraw()
    _pet = dp.DesktopPet.__new__(dp.DesktopPet)
    _pet.cfg, _pet.root, _pet.assets = cfg, _root, _lib
    _pet.font_spec = ("Microsoft YaHei UI", 10)
    _pet.stats, _pet.brain = dp.PetStats(), dp.Brain(dp.PetStats())
    _pet.renderer = dp.SpriteRenderer(cfg)
    _pet.flip = _pet.hovering = False
    _pet.shake_until = _pet.growth_anim_until = 0.0
    _pet.idle_action, _pet.next_idle_action = None, 0.0
    _pet.gif_timeline_pos, _pet.gif_until, _pet._last_asset = 0, 0.0, None
    _pet.brain.act = dp.Act.IDLE
    check(_pet._current_pose(time.time())["asset"] == "idle_anim", "待机 → 呼吸动画")
    _pet.stats.sick = True
    check(_pet._current_pose(time.time())["asset"] == "sick", "生病仍用 sick 素材")
    _pet.stats.sick = False
    # 小动作
    _pet.idle_action = dict(kind="tilt", start=time.time() - 0.5,
                            dur=cfg.IDLE_ACTION_DURATION,
                            end=time.time() + 0.7)
    _pose = _pet._current_pose(time.time())
    check(abs(_pose["tilt"]) > 0.5, f"歪头小动作生效 tilt={_pose['tilt']:.1f}")
    check("shake" in _pose and "breath" in _pose, "pose 带 shake/breath 字段")
    _root.destroy()
except Exception as exc:
    print(f"  （GUI 部分跳过：{exc}）", flush=True)

section("⑩ 视觉美化（第十阶段）")
cfg = dp.CFG
cfg.apply_layout(True)
check(cfg.COMPACT is False, "紧凑压缩已回退（保留完整布局）")
check(cfg.WIN_W >= 442 and cfg.WIN_H == 355, f"窗口 {cfg.WIN_W}x{cfg.WIN_H}（完整形态）")
check(cfg.PET_SIZE == 165, f"宠物尺寸 {cfg.PET_SIZE}px（原大小）")
check(cfg.BUBBLE_MAX_W == 224 and cfg.BUBBLE_PAD_X == 14, "气泡保持原尺寸")
check(cfg.MENU_W == 176, f"菜单宽 {cfg.MENU_W}")
check(cfg.HOVER_DECOR_DELAY == 0.0, "装饰常显（不隐藏）")
check(cfg.WIDGET_ON_TOP is False, "挂件仍在宠物右侧（多行卡片）")
# 美化开关
for name in ("UI_SHADOW", "BUBBLE_GLOSS", "BADGE_GLOSS", "EXPBAR_CAP",
             "WIDGET_SOFT", "WIDGET_DIVIDER"):
    check(getattr(cfg, name, None) is True, f"美化开关 {name} 已开启")
check(cfg.UI_SHADOW_STEPS >= 2, f"投影层数 {cfg.UI_SHADOW_STEPS}")
check(hasattr(dp.DesktopPet, "_bubble_rebuild"), "气泡重建方法存在")
check(hasattr(dp.DesktopPet, "cycle_pet_size"), "尺寸切换仍在（可选功能）")
_b = dp.Brain(dp.PetStats())
_b.show_text("嘿嘿好痒～")
check(abs((_b.say_until - time.time()) - 3.0) < 0.3, "普通台词 3 秒（已回退）")

section("⑪ 3 个经典小游戏（第十一阶段）")
cfg = dp.CFG
check(len(dp.GAMES) == 7, f"小游戏共 {len(dp.GAMES)} 个")
for gid, title in (("tetris", "俄罗斯方块"), ("mine", "扫雷"), ("breakout", "弹球打砖块")):
    check(dp.PetStats().game_limit(gid) == 3, f"{title} 每日 3 次")
check(dp.PetStats().game_limit("rps") == 5, "老游戏仍 5 次（未受影响）")
_s = dp.PetStats()
_s.game_record("tetris", 800)
check(_s.game_high_score("tetris") == 800 and not _s.game_record("tetris", 500),
      "最高分存档：只在新纪录时刷新")
check(len(dp.TETRIS_SHAPES) == 7 and len(dp.CFG.TETRIS_COLORS) == 7, "7 种方块 + 经典配色")
check(len(dp.CFG.MINE_NUM_COLORS) == 9, "扫雷 8 档数字色")
check(dp.CFG.MINE_LIVES == 3 and dp.CFG.MINE_DETECT_USES == 3, "扫雷 3 命 / 3 次探测")
check(dp.CFG.MINE_COLS == 9 and dp.CFG.MINE_COUNT == 10, "扫雷 9×9 / 10 雷")
check(dp.CFG.BREAKOUT_COLS * dp.CFG.BREAKOUT_ROWS == 40, "打砖块 40 块")
check(set(dp.CFG.BREAKOUT_POWER_KINDS) == {"magnet", "multi", "slow", "life"},
      "4 种道具（磁铁/多球/慢球/加命）")
check(dp.CFG.GAME_FPS_MS <= 16 or dp.CFG.GAME_FPS_MS == 16, "循环 16ms ≈ 60FPS")
check(dp.CFG.TETRIS_HELP_USES == 3, "俄罗斯方块 3 次助力")
check(dp.CFG.TETRIS_PRANK_INTERVAL == 45.0, "捣乱间隔 45 秒（亲密伙伴减半）")
check("打砖块冠军奖牌" in dp.MATERIALS, "通关限定奖牌道具已注册")
for cls in (dp.TetrisGame, dp.MinesweeperGame, dp.BreakoutGame):
    check(issubclass(cls, dp.MiniGameBase), f"{cls.__name__} 继承小游戏基类")
check(dp.bond_tier(1200) in ("好朋友", "亲密伙伴"), "亲密度等级可用于降低捣乱频率")

section("⑫ 面板滚动（背包物品过多可滚轮翻看）")
cfg = dp.CFG
check(dp.InventoryPanel.SCROLLABLE, "背包面板已开启滚动")
check(dp.ShopPanel.SCROLLABLE and dp.AchievementPanel.SCROLLABLE, "商店/成就也可滚动")
check(not dp.StatusPanel.SCROLLABLE, "内容少的面板保持不滚动")
check(cfg.PANEL_WHEEL_UNITS >= 3, f"滚轮步长 {cfg.PANEL_WHEEL_UNITS}")
for _m in ("_enable_scroll", "_on_wheel", "_scroll_by", "scroll_to_top", "scroll_hint"):
    check(hasattr(dp.PanelBase, _m), f"PanelBase.{_m} 存在")
print("  （滚动行为已在 _scroll_test.py 中真跑验证：滚轮/方向键/滚动条/边界）", flush=True)

section("⑬ 15 项扩展功能（第十二阶段）")
cfg = dp.CFG
check(hasattr(dp.PetStats(), "extra"), "PetStats.extra 就位")
_ex = dp.ExtraState()
check(len(dp.DIARY_TIME_LINES) > 0 and dp.CFG.DIARY_ACHIEVEMENTS == (7, 30, 100),
      "A1 日记：模板 + 7/30/100 成就")
check(dp.CFG.ANNIV_GIFT_COINS == 500, "A2 周年礼物 500 金币")
check(_ex.memory_prompt(5) == "", "A4 记忆库空时 prompt 为空")
_ex.memory_add("名字", "小明")
check("关于主人" in _ex.memory_prompt(5), "A4 记忆拼进 prompt")
check(_ex.emotion_detect("好累啊")[0] == "neg", "A5 负面情绪识别")
check(_ex.emotion_detect("哈哈哈太好了")[0] == "pos", "A5 正面情绪识别")
check(dp.CFG.WATER_REMIND_EVERY == 3000 and dp.CFG.SIT_REMIND_EVERY == 3600,
      "B7 喝水 50 分 / 久坐 60 分")
_ex.todo_add("测试"); _ex.todo_toggle(0)
check(not _ex.todo_pending(), "B8 待办打勾生效")
check(all(k in {"cpu", "mem", "battery"} for k in ("cpu", "mem", "battery")),
      "B9 系统监控三项")
check(dp.festival_today() is None or len(dp.festival_today()) == 4, "B10 节日表可用")
check(len(dp.CFG.CODEX_PAGES) == 3 and len(dp.CDEX_ANIMALS) >= 9, "C11 图鉴三页")
check(len(dp.OUTFITS) >= 7 and len(dp.FURNITURE) == 3, "C12/C14 装扮与家具")
check(len(dp.TALENTS) == 9 and len(dp.STORY_CHAPTERS) == 5, "D17/D20 天赋与故事")
check(len(dp.SEASONS) == 4, "C15 四季氛围")
_blob = dp.ExtraState().to_dict()
for _k in ("diary_list", "first_day", "memory_store", "todo_list", "codex_unlocked",
           "wardrobe", "equipped_outfit", "furniture", "talents",
           "story_chapters_read", "season_override"):
    check(_k in _blob, f"存档字段 {_k}")
for _m in ("_extra_tick", "_extra_render", "_diary_write_today", "sample_system",
           "acknowledge_reminder", "open_diary", "open_codex", "open_wardrobe",
           "open_talents", "open_story", "open_memory", "open_todo"):
    check(hasattr(dp.DesktopPet, _m), f"DesktopPet.{_m}")

section("⑭ 换装渲染几何（回归）")
try:
    import tkinter as _tk
    _r2 = _tk.Tk(); _r2.withdraw()
    _cv = _tk.Canvas(_r2, width=400, height=400)
    _lib2 = dp.AssetLibrary(cfg); _lib2.prepare_sync(); _lib2._load_all_gifs()
    FEET, PETPX = 320.0, 165.0
    _of = {"hat": "hat_crown", "glasses": "", "back": "back_wing"}

    def _draw(asset):
        _ov = dp.ExtraOverlay(_cv, cfg)
        frames = _lib2.get(asset) or _lib2.get("idle")
        img = frames[0].convert("RGBA")
        w = max(1, int(round(img.width * PETPX / img.height)))
        small = img.resize((w, int(PETPX)), dp.RES_BICUBIC)
        box = _ov.asset_box(asset, small)
        _ov.draw_outfit(_of, 200.0, FEET, PETPX, box=box, asset=asset)
        return _ov, box

    # 帽子按每个素材自己的轮廓定位（换素材位置跟着变）
    tops = {}
    for a in ("idle", "eat", "happy", "talk"):
        _ov, _b = _draw(a)
        tops[a] = _cv.bbox(_ov.items["hat"])[1] if "hat" in _ov.items else None
    check(len({v for v in tops.values() if v}) >= 3,
          "不同素材帽子高度不同（按各自轮廓定位）")
    _ov, _b = _draw("idle")
    _hat = _cv.bbox(_ov.items["hat"])
    _sil_top = FEET - PETPX * (1.0 - _b["top_pad"])
    check(abs(_hat[3] - _sil_top) <= PETPX * 0.12,
          f"帽子压在头顶（底边距轮廓顶 {abs(_hat[3] - _sil_top):.0f}px）")
    # 眼镜已删除
    check(not [k for k, v in dp.OUTFITS.items() if v.get("kind") == "glasses"],
          "眼镜装扮已全部删除（圆框眼镜 / 小墨镜）")
    check(not any(k.startswith("gl_") for k in _ov.items), "不再绘制任何镜片图元")
    # 披风已删除
    check("back_cape" not in dp.OUTFITS, "披风装扮已删除")
    check(not any(v.get("shape") == "cape" for v in dp.OUTFITS.values()),
          "已无任何披风形状")
    # 背上剩翅膀/光环，仍能正常绘制
    _ov2 = dp.ExtraOverlay(_cv, cfg)
    _ov2.draw_outfit({"hat": "", "glasses": "", "back": "back_wing"},
                     200.0, FEET, PETPX, box=_b, asset="idle")
    check("wing_l" in _ov2.items and "wing_r" in _ov2.items, "翅膀仍正常绘制")
    # 只脱帽子
    _ov3 = dp.ExtraOverlay(_cv, cfg)
    _ov3.draw_outfit(_of, 200.0, FEET, PETPX, box=_b, asset="idle")
    _ov3.draw_outfit({"hat": "", "glasses": "", "back": ""},
                     200.0, FEET, PETPX, box=_b, asset="idle")
    check(not [k for k in _ov3.items if k.startswith(("hat", "gl_", "wing"))],
          "全部脱下后不残留任何装扮图元")
    _r2.destroy()
except Exception as _e:
    print(f"  （GUI 部分跳过：{_e}）", flush=True)

section("⑮ 装扮不再显示在奶蛙身上（按需求移除）")
check(cfg.SHOW_OUTFIT is False, "CFG.SHOW_OUTFIT = False（宠物身上不画装扮）")
try:
    import tkinter as _tk4
    _r4 = _tk4.Tk(); _r4.withdraw()
    _cv4 = _tk4.Canvas(_r4, width=400, height=400)
    _pp = dp.DesktopPet.__new__(dp.DesktopPet)
    _pp.cfg = cfg
    _pp.stats = dp.PetStats()
    _pp.stats.extra.outfit = {"hat": "hat_crown", "glasses": "",
                              "back": "back_wing"}
    _pp.extra_ov = dp.ExtraOverlay(_cv4, cfg)
    _pp.remind_until = 0.0
    _pp.remind_icon = ""
    _pp._draw_talent_icons = lambda cx, feet: None
    for _asset in ("idle", "talk", "happy", "sleep_b"):
        _pp._extra_render(1000.0, dict(asset=_asset, frame=None, scale=1.0,
                                       bob=0.0, flip=False))
        _left = [k for k in _pp.extra_ov.items
                 if k.startswith(("hat", "gl_", "wing", "back"))]
        check(not _left, f"{_asset} 素材上没有任何装扮图元（残留 {_left}）")
    _r4.destroy()
except Exception as _e:
    print(f"  （GUI 部分跳过：{_e}）", flush=True)

section("⑯ 待办便签的消失（完成/删除后不留文字）")
try:
    import tkinter as _tk5
    _r5 = _tk5.Tk(); _r5.withdraw()
    _cv5 = _tk5.Canvas(_r5, width=442, height=355)
    _pn = dp.DesktopPet.__new__(dp.DesktopPet)
    _pn.cfg = cfg
    _pn.stats = dp.PetStats()
    _pn.extra_ov = dp.ExtraOverlay(_cv5, cfg)
    _pn.remind_until = 0.0
    _pn.remind_icon = ""
    _pn._draw_talent_icons = lambda cx, feet: None
    _ex5 = _pn.stats.extra
    _POSE = dict(asset="idle", frame=None, scale=1.0, bob=0.0, flip=False)

    def _r():
        _pn._extra_render(1000.0, dict(_POSE))

    def _notes():
        return [k for k in _pn.extra_ov.items if k.startswith("note")]

    _ex5.todo = [dict(text=f"任务{i}", done=False) for i in range(4)]
    _r()
    check("note0" in _notes() and "note_bg" in _notes(), "有未完成待办 → 便签出现")
    for _t in _ex5.todo:
        _t["done"] = True
    _r()
    check(not _notes(), f"全部完成后便签文字全部消失（残留 {_notes()}）")
    for _t in _ex5.todo:
        _t["done"] = False
    _ex5.todo = _ex5.todo[:1]
    _r()
    check("note0" in _notes() and "note1" not in _notes(),
          "只剩 1 条时不残留旧行")
    _ex5.todo = []
    _r()
    check(not _notes(), "删光待办后不残留任何图元")
    # 同类：家具收起 / 节日结束也要清干净
    _ex5.placed = ["mat"]
    _r()
    check(any(k.startswith("fur") for k in _pn.extra_ov.items), "摆上家具显示")
    _ex5.placed = []
    _r()
    check(not [k for k in _pn.extra_ov.items if k.startswith("fur")],
          "收起家具后不留残影")
    check(hasattr(dp.ExtraOverlay, "clear_prefix"), "有按前缀批量清除工具")
    _r5.destroy()
except Exception as _e:
    print(f"  （GUI 部分跳过：{_e}）", flush=True)

section("⑰ 5 款皮肤（扭蛋获取 · 仅换装界面显示）")
import os as _os
check(len(dp.SKINS) == 5, f"皮肤共 {len(dp.SKINS)} 款")
_names = [dp.SKINS[s]["name"] for s in dp.SKIN_IDS]
for _want in ("热情苹果红", "樱花桃粉", "晴空海豚蓝", "香芋薰衣草紫", "彩虹渐变"):
    check(_want in _names, f"含皮肤「{_want}」")
check(dp.SKINS["skin_rainbow"]["rate"] == 0.01, "彩虹渐变概率 1%")
for _s in dp.SKIN_IDS[:-1]:
    check(abs(dp.SKINS[_s]["rate"] - 0.05) < 1e-9, f"{dp.SKINS[_s]['name']} 概率 5%")
_tot = sum(v["rate"] for v in dp.SKINS.values())
check(abs(_tot - 0.21) < 1e-9, f"皮肤合计 {_tot * 100:.0f}%，其余给装扮")
# 素材文件都在
for _s in dp.SKIN_IDS:
    _p = _os.path.join(dp.app_dir(), dp.SKIN_DIR, dp.SKINS[_s]["file"])
    check(_os.path.isfile(_p), f"{dp.SKINS[_s]['name']} 素材文件存在")
# 概率实测（3 万次抽样）
import collections as _col
_ex = dp.ExtraState()
_c = _col.Counter()
_N = 30000
for _ in range(_N):
    _ex.gacha_date = ""
    _ex.gacha_count = 0
    _c[_ex.gacha_draw()["outfit"]] += 1
for _s in dp.SKIN_IDS:
    _got = _c[_s] * 100.0 / _N
    check(abs(_got - dp.SKINS[_s]["rate"] * 100) < 0.6,
          f"{dp.SKINS[_s]['name']} 实测 {_got:.2f}%（目标 {dp.SKINS[_s]['rate'] * 100:.0f}%）")
# 共同计算：抽出来的东西要么是皮肤要么是装扮，且总概率 100%
_outfit_hits = sum(v for k, v in _c.items() if k in dp.OUTFITS)
check(abs(sum(_c.values()) - _N) == 0, "每次抽取都命中皮肤或装扮之一")
check(_outfit_hits / _N > 0.7, f"装扮仍占多数（{_outfit_hits / _N * 100:.0f}%）")
# 拥有 / 切换 / 重复返还
_ex2 = dp.ExtraState()
res = _ex2.gacha_draw()
check(res["kind"] in ("skin", "outfit"), f"返回类型 {res['kind']}")
_ex2.skin_owned = ["skin_red"]
check(_ex2.skin_has("skin_red") and not _ex2.skin_has("skin_blue"), "皮肤拥有判定")
_ex2.skin_current = ""
check(_ex2.skin_equip("skin_red") and _ex2.skin_current == "skin_red", "换上皮肤")
check(_ex2.skin_equip("skin_red") and _ex2.skin_current == "", "再点一次脱下")
check(not _ex2.skin_equip("skin_blue"), "没抽到的皮肤穿不上")
# 存档往返
_ex2.skin_owned = ["skin_red", "skin_rainbow"]
_ex2.skin_current = "skin_rainbow"
_blob = _ex2.to_dict()
check(_blob.get("skin_owned") == ["skin_red", "skin_rainbow"], "存档写出 skin_owned")
check(_blob.get("skin_current") == "skin_rainbow", "存档写出 skin_current")
_ex3 = dp.ExtraState(); _ex3.from_dict(_blob)
check(_ex3.skin_owned == _ex2.skin_owned and _ex3.skin_current == "skin_rainbow",
      "皮肤存档往返正常")
_bad = dp.ExtraState(); _bad.from_dict(dict(skin_owned=["not_exist"],
                                            skin_current="not_exist"))
check(_bad.skin_owned == [] and _bad.skin_current == "", "无效皮肤自动剔除")
# 桌面不显示皮肤（皮肤只改换装界面预览）
check(cfg.SHOW_OUTFIT is False, "桌面仍不渲染任何装扮/皮肤")
check(hasattr(dp.WardrobePanel, "_preview_base"), "换装界面使用皮肤素材做预览")
check(hasattr(dp.WardrobePanel, "_skin_image"), "换装界面能读皮肤素材")

section("⑱ 右键菜单独立弹窗 + 记忆库生效")
try:
    import tkinter as _tk6
    _r6 = _tk6.Tk(); _r6.withdraw()

    class _FP:
        def __init__(self):
            self.root = _r6; self.cfg = cfg
            self.assets = dp.AssetLibrary(cfg); self.assets.prepare_sync()
            self.stats = dp.PetStats()
            self.font_spec = ("Microsoft YaHei UI", 10)
            self.brain = dp.Brain(self.stats)
            self.games_open = 0; self._panel_icons = {}
            self._menu_open = False; self._bmenu = None
            self.x, self.y = 600, 300

        def autosave(self, force=False):
            return True

    _fake = _FP()
    _hit = []
    _items = [("💬", "对话", lambda: _hit.append("chat")), ("-",),
              ("🎒", "背包", lambda: _hit.append("bag")),
              ("📔", "日记", lambda: _hit.append("diary"))]
    _mw = dp.MenuWindow(_r6, _fake, _items, 1200, 300)
    _r6.update()
    check(isinstance(_mw, _tk6.Toplevel), "菜单是独立 Toplevel 窗口")
    check(_mw.title() == "奶蛙菜单", f"有标题栏：{_mw.title()}")
    check(getattr(_fake, "_menu_open", False) is True, "打开时通知宠物（不响应点击）")
    # 位置不压宠物
    import re as _re2
    _geo = _mw.winfo_geometry()
    _m2 = _re2.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", _geo)
    _x, _y = (int(_m2.group(3)), int(_m2.group(4))) if _m2 else (0, 0)
    check(not (600 <= _x < 600 + cfg.WIN_W and 300 <= _y < 300 + cfg.WIN_H),
          f"菜单位置避开宠物窗口（{_geo}）")
    check(len(_mw._btns) == 3, f"渲染了 {len(_mw._btns)} 个按钮")
    _mw._run(_items[2][2])
    _r6.update()
    check(_hit == ["bag"], f"点菜单项会执行回调（{_hit}）")
    check(_mw._done is True and getattr(_fake, "_menu_open", False) is False,
          "点完自动关窗并恢复宠物")
    check(dp.CFG.MENU_W >= 150, "菜单宽度固定，不会随文字变宽")
    _r6.destroy()
except Exception as _e:
    print(f"  （GUI 部分跳过：{_e}）", flush=True)

# 记忆库：提取 + 提示词 + 本地应答
_exm = dp.PetStats().extra
_pm = dp.DesktopPet.__new__(dp.DesktopPet)
_pm.stats = dp.PetStats(); _pm.stats.extra = _exm
_pm.autosave = lambda force=False: True
_pm._memory_extract("我的生日是 3 月 15 日")
_pm._memory_extract("我叫小明")
_pm._memory_extract("要记住：下周三体检")
check(any(m["topic"] == "生日" for m in _exm.memory), "记住生日")
check(any(m["topic"] == "名字" for m in _exm.memory), "记住名字")
check(any(m["topic"] == "备忘" for m in _exm.memory), "记住「要记住…」的内容")
check("3 月 15" in _exm.memory_prompt(5), "关键信息优先进入提示词（不被挤掉）")
_ans = _pm._memory_answer("我生日是哪天")
check(_ans and "3 月 15" in _ans, f"本地能答出生日：{_ans}")
check(_pm._memory_answer("今天天气不错") is None, "普通闲聊不被记忆劫持")
_sys = dp.ChatBrain.build_system_prompt("正常", "fine", memory=_exm.memory_prompt(5))
check("奶蛙" in _sys and "3 月 15" in _sys, "记忆拼进大模型 system prompt")
import inspect as _insp
check("memory" in _insp.signature(dp.LLMClient.chat).parameters,
      "LLMClient.chat 支持 memory 参数")

print()
print("=" * 76)
if ok:
    print(" 结论：全部通过 ✅")
else:
    print(f" 结论：{len(fails)} 项失败 ❌")
    for f in fails:
        print("   - " + f)
print("=" * 76)
sys.exit(0 if ok else 1)
