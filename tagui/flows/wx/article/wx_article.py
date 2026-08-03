# -*- coding: utf-8 -*-
# wx_article.py - 微信搜一搜公众号文章自动抓取(文章类别脚本,一体化主入口,单文件版)
#
# 合并自: wx_common.py + date_utils.py + article_store.py + parse_results.py
#         + setup_workdir.py + wx_agent.py + tag_all.tag 状态机
#
# 用法(一条命令完成整个流程):
#   python wx_article.py --account 隆基绿能 --tab 文章 --start 2026-07-30 --end 2026-08-01
#
# 流程: 检测微信主窗 -> 建独立临时工作目录(拷贝 .tag/.py/.png)
#       -> 复制公众号名到剪贴板 -> 点侧边栏 home.png 打开搜一搜
#       -> TagUI 单进程执行 tag_all.tag(内含 search->detail->scroll 状态机,全部逻辑在本文件)
#       -> 保存 articles.json 到本目录 -> 关闭搜一搜窗口 -> 移除临时目录
#
# 可选维护命令:
#   python wx_article.py --phase close   仅收尾(保存结果+关窗+清理)
#   python wx_article.py --phase status  查看上次结果(不动 UI)
#
# 退出码: 0=成功, 2=流程失败
import argparse
import ctypes
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

# ---- 输出编码+行缓冲: 强制 stdout/stderr 用 UTF-8,避免 Windows GBK 控制台中文乱码;
# 同时开 line_buffering,防止进程被杀/超时 kill 时 stdout 缓冲丢失(日志 0 字节) ----
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace',
                            line_buffering=True)
    except Exception:
        pass
try:
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)   # 控制台输出代码页 -> UTF-8
    ctypes.windll.kernel32.SetConsoleCP(65001)         # 控制台输入代码页 -> UTF-8
except Exception:
    pass

# ---- DPI 感知: 必须在任何截图/取窗口坐标/点击之前调用 ----
# Windows 系统缩放(125%/150%)下,若进程不声明 DPI 感知,GetWindowRect / ImageGrab
# / SetCursorPos 会拿到互相矛盾的逻辑/物理像素,导致所有坐标偏移(点错位置)。
# 声明后统一使用物理像素(与屏幕实际分辨率一致),换电脑/改缩放也不受影响。
_DPI_AWARE = False


def enable_dpi_awareness():
    """声明进程为 DPI 感知(优先 Per-Monitor V2,退而求其次 System aware)。
    必须在任何窗口操作前调用,只生效一次。返回是否成功。"""
    global _DPI_AWARE
    if _DPI_AWARE:
        return True
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()    # 旧版 API 兜底
        except Exception:
            return False
    _DPI_AWARE = True
    return True


enable_dpi_awareness()   # 模块级: 所有 import 本模块的进程(含 TagUI py 块)立即生效

import numpy as np
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
# 显式签名: 允许 GetWindowThreadProcessId 第二参传 None(NULL 指针)
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []
user32.AttachThreadInput.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                     wintypes.BOOL]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

# ================================================================ 常量
# 本文件位于 <tagui-root>\flows\wx\article\(按类别分子目录,未来有 sticker/video 等)。
# 上游目录由 tagui.cmd 的调用方决定,因此源码文件/缓存/任务目录均以 __file__ 为锚,
# 不硬编码任何绝对路径。
WX_DIR = os.path.dirname(os.path.abspath(__file__))      # <tagui-root>\flows\wx\article\
# ---- TagUI 启动器路径: 自动推导,不硬编码 ----
# tagui.cmd 位于 <tagui-root>\src\,本文件向上三级(article -> wx -> flows)即得。
# 找不到时回退 PATH 中的 'tagui.cmd'。
_TAGUI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(WX_DIR)))   # <tagui-root>
TAGUI_CMD = os.path.join(_TAGUI_DIR, 'src', 'tagui.cmd')
if not os.path.exists(TAGUI_CMD):
    _cand = shutil.which('tagui.cmd') or shutil.which('tagui')
    TAGUI_CMD = _cand if _cand else TAGUI_CMD
WORKDIR_FILE = os.path.join(WX_DIR, 'workdir.txt')
ARTICLES_FILE = 'articles.json'
TAB_WORDS = ('全部', '贴图', '文章', '视频号', '服务号', '小程序', '朋友圈')
COPY_EXTS = ('.tag', '.py', '.png')
HEAD_NOISE_END = '视频号'   # parse_results 头部噪音截止标志

# ---- 虚拟键码 ----
VK_CTRL = 0x11
VK_ALT = 0x12
VK_A = 0x41          # Ctrl+A
VK_V = 0x56          # Ctrl+V
VK_W = 0x57          # Ctrl+W 关闭标签页
VK_ENTER = 0x0D
VK_BACK = 0x08          # 退格 Backspace(删除字符)
VK_1 = 0x31             # 数字键 '1'(触发搜索建议面板用)

# ---- 界面等待(秒) ----
SLEEP_CLICK = 0.1        # 点击前/后微停顿
SLEEP_PAGE_OPEN = 0.3    # 详情页/菜单弹出等待
SLEEP_DETAIL_LOAD = 1.0  # 点击标题进入详情页后,等待文章正文加载,再点"更多"按钮
SLEEP_WHEEL = 1.0        # 滚轮操作后
SLEEP_TAB_CLOSE = 1.0    # 关闭标签页后等待完全关闭
SLEEP_UI_SHORT = 0.5
SLEEP_UI_MID = 1.0
SLEEP_UI_LONG = 2.0
SLEEP_ACTIVATE = 1.2     # 窗口激活后
SLEEP_SEARCH_RESULT = 2.0  # 搜索/进入公众号后等待结果渲染

# ---- 模板匹配阈值 ----
THRESHOLD_TEMPLATE = 0.75   # 主要 UI 模板(更多/复制链接/首页/输入框/文章标签)
THRESHOLD_COPY_URL_FALLBACK = 0.68  # 复制链接低阈值兜底
TITLE_FUZZY_RATIO = 0.8     # OCR 标题模糊匹配最小相似度(应对拼写噪声)

# ---- 固定坐标(窗口内相对比例,随窗口尺寸自适应) ----
POS_TABBAR_RATIO = (0.47, 24)   # 鼠标移到顶部标签栏(宽度 47% 处),避免悬停详情内容区

# ---- 重试次数 ----
RETRY_COPY_URL = 3       # 每轮点更多后查找"复制链接"重试次数
RETRY_DETAIL_ROUNDS = 2  # 每篇文章最多进详情页轮数(失败关标签重进)
RETRY_ARTICLE_TAB = 3    # 点击"文章"标签重试次数

# ---- 统一运行时缓存(滚动校准 / 布局学习 / 控件坐标侦查 合并到单一 cache.json) ----
# 原 scroll_calib.json / layout.json / input_field_cache.json / article_cache.json
# 四份缓存统一合并为一份 cache.json, 按分区键管理(读改写互不覆盖)。
# 持久化到稳定目录(真实 WX_DIR),跨运行复用;TagUI 子进程从临时任务目录
# import 本文件副本,其 __file__ 指向任务目录,故用 WX_SOURCE_DIR 环境变量指回真实
# 源码目录(见 run_tag),否则每次运行新任务目录校准缓存恒为空,每次都重新校准。
CACHE_FILE = os.path.join(
    os.environ.get('WX_SOURCE_DIR') or WX_DIR, 'cache.json')
CACHE_SCROLL = 'scroll'          # 滚轮校准: px_per_click / measured_at / item_height
CACHE_LAYOUT = 'layout'          # 列表布局学习: col_split / list_top / learned_at
CACHE_INPUT_FIELD = 'input_field'  # 搜索框坐标侦查: window_rect / coord / recon_at
CACHE_ARTICLE = 'article'        # "文章"标签坐标侦查: window_rect / coord / recon_at

# ---- tag2 滚动: 按"篇数"动态滚动(每轮滚 N 篇文章高度) ----
SCROLL_ITEMS_PER_PAGE = 4     # 每轮滚动滚过多少篇文章
SCROLL_PX_PER_CLICK = 112.0   # 滚轮 1 格移动像素的兜底估算(校准失败时用)

# ================================================================ 窗口
def get_pid2name():
    """一次 tasklist 拿 PID -> 进程名 映射(避免回调里逐窗口 tasklist 太慢)"""
    out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    m = {}
    for line in out.strip().splitlines():
        parts = line.split('","')
        if len(parts) >= 2 and parts[1].strip('"').isdigit():
            m[int(parts[1].strip('"'))] = parts[0].strip('"')
    return m


def find_wx_window():
    """找到可见的 WeChatAppEx(搜一搜)窗口,返回 hwnd 或 None。
    优先可见窗口(排除隐藏的音乐和音频等);若无可见则取第一个带标题的。"""
    pid2name = get_pid2name()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid2name.get(pid.value) == 'WeChatAppEx.exe':
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, buf, 128)
            if buf.value and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    # 优先全屏窗口(搜一搜通常铺满屏幕)
    for hwnd in found:
        l, t, r, b = win_rect(hwnd)
        if (r - l) >= 1000 and (b - t) >= 600:
            return hwnd
    return found[0] if found else None


def find_weixin_main():
    """找到微信主窗口(Weixin.exe,标题'微信'),返回 hwnd 或 None。
    最小化/隐藏(托盘)窗口也能找到(activate 会先还原),优先返回可见窗口。"""
    pid2name = get_pid2name()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid2name.get(pid.value) == 'Weixin.exe':
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, buf, 128)
            if buf.value.strip() == '微信':
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    for hwnd in found:
        if user32.IsWindowVisible(hwnd):
            return hwnd
    return found[0]


def open_soss_from_main(main_hwnd, keyword=''):
    """从微信主窗口打开搜一搜(WeChatAppEx)。
    实测链路: 点击顶部搜索框(wx_search.png 模板匹配,窗口顶部区域)-> 弹出搜索面板
              (含"搜索网络结果"入口) -> 点击"搜索网络结果"文字 -> 打开搜一搜窗口。
    (部分微信版本侧边栏无 home 图标,此路径作为 home.png 方案的替代。
     注意: 面板里的 home1 房子图标点击不是搜一搜入口,必须点"搜索网络结果"文字。)
    返回新的搜一搜 hwnd 或 None。"""
    activate(main_hwnd)
    time.sleep(SLEEP_UI_MID)
    l, t, r, b = win_rect(main_hwnd)

    # 1) 点击顶部搜索框: 优先 wx_search.png 模板匹配(跨机器/跨版本自适应),
    #    匹配失败才按窗口顶部比例回退(相对坐标,不依赖绝对像素)。
    hit = click_template(main_hwnd, os.path.join(WX_DIR, 'wx_search.png'),
                         region=get_region('searchbox', main_hwnd),
                         label='MAIN_SEARCHBOX')
    if not hit:
        fx = l + int((r - l) * 0.18)   # 主窗顶部搜索框约在 18% 宽度处
        fy = t + int((b - t) * 0.06)
        sendinput_click(fx, fy)
        print('MAIN_SEARCHBOX_FALLBACK @ (%d,%d)' % (fx, fy))

    # 2) 确保建议面板弹出: 点击搜索框后直接 OCR 不保证面板弹出(clean 状态下
    #    面板可能不出现,实测只读到聊天列表)。可靠做法(用户实测确认):
    #    点击搜索框 -> 输入一个字符(如 '1') -> 删除 -> 面板必定弹出,
    #    且含"搜索网络结果"(搜一搜入口)。
    #    注意: 必须用真实键盘事件敲 '1',不能用 set_clipboard('1')+ctrl+v ——
    #    那会覆盖 main() 预复制的公众号名称,导致 flow_fill_search 阶段
    #    ctrl+v 粘贴出 '1' 而非账号名。
    hotkey(VK_1)                   # 直接敲 '1' 键(不经过剪贴板)
    time.sleep(1.0)
    hotkey(VK_BACK)                # 退格删除 '1'
    time.sleep(1.0)

    # 3) 在建议面板找"搜索网络结果"(搜一搜入口)并点击
    items, _ = ocr_region(main_hwnd, 0, 60, r - l, 300)
    cands = find_text(items, '搜索网络结果', prefer_exact=False)
    if cands:
        cy, x0, x1, txt = cands[0]
        abs_x = l + int((x0 + x1) / 2)
        abs_y = t + int(cy)
        sendinput_click(abs_x, abs_y)
        print('CLICKED_SOSS_ENTRY %r @ (%d,%d)' % (txt, abs_x, abs_y))
        time.sleep(SLEEP_UI_LONG)
        
        # 等待 SOSS 窗口彻底创建完成
        for _ in range(20):
            soss = find_wx_window()
            if soss:
                break
            time.sleep(0.1)
        if soss:
            # 强制 SOSS 窗口置顶并激活，防止主窗口跳回
            _force_soss_to_foreground(main_hwnd, soss)
        return soss

    # 兜底: 面板仍未出现(极端情况),输入关键字触发建议面板
    print('SOSS_PANEL_NOT_POPPED - 尝试输入关键字触发建议面板')
    if not keyword:
        import pyperclip
        pyperclip.copy('测试')
        keyword = '测试'
    hotkey(VK_CTRL, VK_A)          # ctrl+a 清空
    set_clipboard(keyword)
    hotkey(VK_CTRL, VK_V)          # ctrl+v
    time.sleep(1.5)

    # 3) 在建议面板找"搜索网络结果"(搜一搜入口)并点击
    items, _ = ocr_region(main_hwnd, 0, 60, r - l, 260)
    cands = find_text(items, '搜索网络结果', prefer_exact=False)
    if not cands:
        # 兜底: 找 "搜一搜" 文字
        cands = find_text(items, '搜一搜', prefer_exact=False)
    if not cands:
        print('SOSS_ENTRY_NOT_FOUND - 建议面板内容: %s'
              % [t for _, _, _, t in items][:8])
        # 兜底: 直接回车进入搜索结果
        hotkey(VK_ENTER)
        time.sleep(1.5)
    else:
        cy, x0, x1, txt = cands[0]
        abs_x = l + int((x0 + x1) / 2)
        abs_y = t + int(cy)
        sendinput_click(abs_x, abs_y)
        print('CLICKED_SOSS_ENTRY %r @ (%d,%d)' % (txt, abs_x, abs_y))
        time.sleep(SLEEP_UI_LONG)

    soss = find_wx_window()
    if soss:
        # 让 SOSS 前台优先(先直接置前,失败才最小化主窗口,避免"弹出又隐藏")
        _force_soss_to_foreground(main_hwnd, soss)
    return soss


def open_soss_via_home(main_hwnd, home_tpl):
    """从微信主窗口侧边栏点击 home.png 图标直接打开搜一搜页面。
    返回新的搜一搜 hwnd 或 None。"""
    activate(main_hwnd)
    time.sleep(SLEEP_UI_SHORT)
    l, t, r, b = win_rect(main_hwnd)
    hit = click_template(main_hwnd, home_tpl, region=get_region('home_icon', main_hwnd),
                         label='HOME_ICON')
    if not hit:
        print('HOME_ICON_NOT_FOUND')
        return None
    time.sleep(1.5)
    return find_wx_window()


def ensure_soss_window():
    """确保搜一搜窗口可用: 有可见搜一搜窗口则返回;否则尝试从微信主窗口打开。
    返回 (hwnd, opened): opened=True 表示本次新打开。"""
    hwnd = find_wx_window()
    if hwnd:
        return hwnd, False
    main = find_weixin_main()
    if not main:
        return None, False
    return open_soss_from_main(main), True


def close_window(hwnd):
    """直接关闭窗口(WM_CLOSE)。用于 close 阶段清理搜一搜窗口。"""
    if hwnd:
        user32.PostMessageW(int(hwnd), 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(0.5)


def _force_soss_to_foreground(main_hwnd, soss_hwnd):
    """确保 SOSS 窗口完全在前台(解决搜索框路径打开 SOSS 后主窗口跳回的问题)。
    优先级: 先直接提升 SOSS 前台(不最小化主窗口,避免无谓的"弹出又隐藏");
    仅当直接置前失败(主窗口抢焦点)时才最小化主窗口兜底。
    手段: AttachThreadInput + BringWindowToTop 提升 Z 序 + SetForegroundWindow 抢前台锁。"""
    # Step 1: 先直接尝试把 SOSS 带到前台(不碰主窗口)
    if _force_foreground(soss_hwnd):
        print('SOSS_ACTIVATED_OK')
        return

    # Step 2 (兜底): 直接置前失败 -> 最小化主窗口剥夺其焦点资格,再抢一次
    user32.ShowWindow(main_hwnd, 6)                   # SW_MINIMIZE
    time.sleep(0.3)
    if _force_foreground(soss_hwnd):
        print('SOSS_ACTIVATED_OK (主窗口已最小化兜底)')
    else:
        print('SOSS_ACTIVATION_PARTIAL')


def _force_foreground(hwnd, tries=3):
    """可靠地把窗口带到前台(后台进程 SetForegroundWindow 常被前台锁拦截)。

    组合技巧(逐步增强,任一成功即返回):
      1) AttachThreadInput: 把当前线程输入队列接到目标窗口线程,
         使 SetForegroundWindow 不再受"仅前台进程可抢前台"限制;
      2) BringWindowToTop: 提升 Z 序;
      3) SetForegroundWindow。
    每次尝试后验证 GetForegroundWindow()==hwnd,失败重试。
    返回是否已在前台。"""
    for _ in range(tries):
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)      # SW_RESTORE
            time.sleep(0.3)
        if not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 5)      # SW_SHOW
            time.sleep(0.3)
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        cur_tid = kernel32.GetCurrentThreadId()
        attached = False
        if fg and fg_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_tid, cur_tid, False)
        time.sleep(0.4)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return user32.GetForegroundWindow() == hwnd


def ensure_foreground(hwnd):
    """惰性激活: 截图/OCR/点击前调用。窗口已在前台则零开销,
    否则强制带到前台并验证。返回是否已在前台。"""
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    return _force_foreground(hwnd)


def activate(hwnd):
    """激活窗口;若窗口最小化(IsIconic)或隐藏(托盘,WS_VISIBLE 清除)则先还原/显示。
    用 _force_foreground 确保真正到达前台(仅 ShowWindow/SetForegroundWindow
    在后台进程下常被 Windows 前台锁拦截,窗口虽"打开"但被其他窗口盖住,
    导致截图/点击打到错误窗口)。"""
    _force_foreground(hwnd)
    time.sleep(SLEEP_ACTIVATE)


def win_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


# ================================================================ 鼠标/键盘
# SendInput 结构定义(真实输入队列,微信对 mouse_event 合成点击不响应)
_INPUT_MOUSE = 0
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', ctypes.c_long), ('dy', ctypes.c_long),
                ('mouseData', ctypes.c_long), ('dwFlags', ctypes.c_ulong),
                ('time', ctypes.c_ulong), ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    _fields_ = [('type', ctypes.c_ulong), ('mi', _MOUSEINPUT)]


def sendinput_click(abs_x, abs_y, right=False):
    """SendInput 真实点击: 走系统输入队列,微信搜索框等控件只响应这种点击。
    与 click_at 的区别: mouse_event 是合成消息,部分微信 UI 会忽略;SendInput
    是真实硬件级输入,行为等同人手点击。"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)

    def _inp(flags):
        i = _INPUT()
        i.type = _INPUT_MOUSE
        i.mi.dx = int(int(abs_x) * 65535 / (sw - 1))
        i.mi.dy = int(int(abs_y) * 65535 / (sh - 1))
        i.mi.dwFlags = flags
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))

    user32.SetCursorPos(int(abs_x), int(abs_y))
    time.sleep(0.2)  # 移动后稍候,保证命中目标
    if right:
        _inp(_MOUSEEVENTF_RIGHTDOWN)
        time.sleep(0.08)
        _inp(_MOUSEEVENTF_RIGHTUP)
    else:
        _inp(_MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.08)
        _inp(_MOUSEEVENTF_LEFTUP)
    time.sleep(0.1)  # 点击后稍候,让界面响应


def click_at(abs_x, abs_y, right=False):
    user32.SetCursorPos(int(abs_x), int(abs_y))
    time.sleep(0.1)  # 移动后稍候,保证命中目标
    if right:
        user32.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
        user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
    else:
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.1)  # 点击后稍候,让界面响应


def hotkey(*vks):
    """模拟组合键,如 hotkey(0x11, 0x41) = Ctrl+A"""
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def scroll_wheel(abs_x, abs_y, clicks, direction='down'):
    """SendInput 真实滚轮: 逐格发送 MOUSEEVENTF_WHEEL(每格 -120/120 WHEEL_DELTA)。

    与点击同理: 微信等桌面应用只响应真实硬件级输入队列。
    旧实现用 mouse_event(合成消息)一次发多格 delta,微信只解释为 1 格
    (表现为"一格一格滚、滚不到目标距离");改为 SendInput 逐格发送,
    模拟人手快速滚动,微信把连续格合并为一次平滑滚动到位。
    clicks 为滚动格数(1 格 = 120 WHEEL_DELTA)。"""
    user32.SetCursorPos(int(abs_x), int(abs_y))
    time.sleep(0.1)
    delta = -120 if direction == 'down' else 120
    for _ in range(max(1, int(clicks))):
        i = _INPUT()
        i.type = _INPUT_MOUSE
        i.mi.dx = 0
        i.mi.dy = 0
        i.mi.mouseData = delta
        i.mi.dwFlags = 0x0800   # MOUSEEVENTF_WHEEL
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))
        time.sleep(0.03)        # 逐格间隔,模拟真实滚轮节奏
    time.sleep(SLEEP_WHEEL)


def scroll_px(abs_x, abs_y, px, px_per_click):
    """按"像素距离"滚动: 把目标像素换算成滚轮格数(1 格 = px_per_click 像素)。
    保证跨机器/跨分辨率一致: 像素目标是绝对的,格数是换算结果。"""
    clicks = max(1, int(round(px / px_per_click)))
    scroll_wheel(abs_x, abs_y, clicks, 'down')
    return clicks


# ---- 滚轮 1 格像素动态校准 ----
def _anchor_title(hwnd, items):
    """从当前屏解析结果里挑一个稳定的锚点标题(取列表中部,避免顶部残行/底部半截)。
    返回 (归一化标题, cy) 或 None。"""
    vis = parse_list_items(items, min_y=0)
    if not vis:
        return None
    # 取中间偏上的一条(滚动后仍在屏内概率大,且不是顶部残行)
    idx = min(len(vis) // 2, len(vis) - 1)
    it = vis[idx]
    nt = _norm_title(it.get('title', ''))
    if not nt:
        return None
    return nt, it.get('cy', 0)


def _calibrate_scroll_px(hwnd, l, t, r, b, tries=3):
    """实测"滚轮 1 格 = 多少像素": 锚定一个已知标题 -> 滚动 1 格 ->
    重新 OCR 定位同一标题的 cy -> 两次 cy 差值即 1 格像素。
    多次取中位数抗抖。失败返回 None(调用方用 SCROLL_PX_PER_CLICK 兜底)。
    注意: 这会真实滚动列表,调用方需在已进列表页后执行。"""
    # 滚动前: 找锚点标题及其 cy
    items, _ = list_ocr(hwnd)
    anchor = _anchor_title(hwnd, items)
    if not anchor:
        return None
    nt, cy0 = anchor
    scroll_x = l + int((r - l) * 0.5)
    scroll_y = t + int((b - t) * 0.7)
    diffs = []
    for i in range(tries):
        scroll_wheel(scroll_x, scroll_y, 1, 'down')
        time.sleep(SLEEP_WHEEL)
        items2, _ = list_ocr(hwnd)
        cy1 = None
        for it in parse_list_items(items2, min_y=0):
            if _norm_title(it.get('title', '')) == nt:
                cy1 = it.get('cy')
                break
        if cy1 is not None:
            d = abs(cy1 - cy0)   # 向下滚动标题上移(cy 变小),差取绝对值
            if 30 < d < 400:   # 合理范围过滤(非 0/过大异常值)
                diffs.append(d)
        cy0 = cy1 if cy1 is not None else cy0
    if not diffs:
        return None
    diffs.sort()
    return float(diffs[len(diffs) // 2])


def get_scroll_px(hwnd, l, t, r, b, refresh=False):
    """获取滚轮 1 格像素: 优先读统一缓存 scroll 分区;无缓存或 refresh 时实测。
    实测成功写缓存(跨运行复用)。全部失败返回 SCROLL_PX_PER_CLICK 兜底。"""
    calib = read_cache(CACHE_SCROLL)
    if not refresh and calib.get('px_per_click'):
        px = float(calib['px_per_click'])
        print('SCROLL_PX_FROM_CACHE=%.1f' % px)
        return px
    px = _calibrate_scroll_px(hwnd, l, t, r, b)
    if px and px > 0:
        calib['px_per_click'] = px
        calib['measured_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        write_cache(CACHE_SCROLL, calib)   # 保留 item_height,勿整体覆盖
        print('SCROLL_PX_CALIBRATED=%.1f (已缓存 %s)' % (px, CACHE_FILE))
        return px
    print('SCROLL_PX_CALIB_FAIL - 用兜底 %.1f px' % SCROLL_PX_PER_CLICK)
    return SCROLL_PX_PER_CLICK


# ================================================================ 公共动作(找+点+日志)
def click_template(hwnd, template, region=None, threshold=THRESHOLD_TEMPLATE,
                   label=''):
    """找模板 -> 点击 -> 打日志。返回命中 (abs_x, abs_y, score) 或 None。
    label 用于日志前缀,缺省取模板文件名。"""
    hit = find_template(hwnd, template, region=region, threshold=threshold)
    if not hit:
        return None
    click_at(hit[0], hit[1])
    print('CLICKED_%s @ (%d,%d) score=%.2f'
          % (label or os.path.splitext(os.path.basename(template))[0],
             hit[0], hit[1], hit[2]))
    return hit


def click_ocr_text(hwnd, region, keyword, label='', offset_y=0,
                   prefer_exact=True, max_x=None):
    """OCR 区域内找关键字文本 -> 点击其中心 -> 打日志。
    返回命中的 (cy, x0, x1, txt) 或 None。offset_y 为点击纵坐标附加偏移;
    max_x 限制只匹配 x0 小于该值的候选(如搜索框只找左侧文本)。"""
    l, t, _, _ = win_rect(hwnd)
    items, _ = ocr_region(hwnd, *region)
    cands = find_text(items, keyword, prefer_exact=prefer_exact)
    if max_x is not None:
        cands = [c for c in cands if c[1] < max_x]
    if not cands:
        return None
    cy, x0, x1, txt = cands[0]
    abs_x = l + int((x0 + x1) / 2)
    abs_y = t + int(cy) + offset_y
    click_at(abs_x, abs_y)
    print('CLICKED_%s %r @ (%d,%d)' % (label or keyword, txt, abs_x, abs_y))
    return cands[0]


def move_cursor_to_tabbar(l, t, r, b=None):
    """鼠标移到窗口顶部标签栏(按宽度比例),避免悬停详情内容区弹出悬浮层"""
    user32.SetCursorPos(l + int((r - l) * POS_TABBAR_RATIO[0]),
                        t + POS_TABBAR_RATIO[1])


# ================================================================ OCR
_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ocr_image(img):
    """img: PIL.Image 或 ndarray -> [(cy, x0, x1, text)] 按 y 升序"""
    res, _ = get_ocr()(np.array(img))
    out = []
    if res:
        for box, text, conf in res:
            t = (text or '').strip()
            if not t:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append(((min(ys) + max(ys)) / 2, min(xs), max(xs), t))
    out.sort()
    return out


def find_text(items, keyword, min_y=0, max_y=10 ** 9, prefer_exact=True):
    """在 OCR 结果中找含 keyword 的文本,优先精确匹配,返回按 y 升序候选"""
    exact, sub = [], []
    for cy, x0, x1, t in items:
        if cy < min_y or cy > max_y:
            continue
        if t == keyword:
            exact.append((cy, x0, x1, t))
        elif keyword in t:
            sub.append((cy, x0, x1, t))
    if prefer_exact and exact:
        return exact
    return sub if sub else exact


def ocr_region(hwnd, x0, y0, x1, y1, path=None):
    """截取窗口内指定区域并 OCR,返回 (带窗口偏移的 items, 窗口rect)。
    区域越小 OCR 越快,调用方无需关心裁剪偏移。
    越界区域会 clamp 到窗口范围内(REGION 常量按 1920 宽设计,
    小窗口下避免截到窗口外的桌面/其他程序)。
    截图前确保窗口在前台,否则截到的是盖住它的其他窗口内容。"""
    ensure_foreground(hwnd)
    l, t, r, b = win_rect(hwnd)
    # clamp 到窗口边界
    x0 = max(x0, 0)
    y0 = max(y0, 0)
    x1 = min(x1, max(r - l, 10))
    y1 = min(y1, max(b - t, 10))
    w = max(x1 - x0, 10)
    h = max(y1 - y0, 10)
    img = ImageGrab.grab(bbox=(l + x0, t + y0, l + x0 + w, t + y0 + h))
    if path:
        img.save(path)
    raw = ocr_image(img)
    items = [(cy + y0, x + x0, x2 + x0, txt) for cy, x, x2, txt in raw]
    items.sort()
    return items, (l, t, r, b)


def find_template(hwnd, template_path, region=None, threshold=0.82):
    """在窗口(或指定区域内)用模板匹配找小图标。

    region: (x0, y0, x1, y1) 窗口内相对坐标;None=整个窗口
    返回 (abs_cx, abs_cy, score) 或 None。score 为归一化相关系数。
    截图前确保窗口在前台,否则匹配到的是盖住它的其他窗口内容。"""
    import cv2

    if not os.path.isfile(template_path):
        print('ERROR - TEMPLATE_FILE_MISSING %s' % template_path)
        print('WX_DIR=%s files=%s' % (WX_DIR, sorted(os.listdir(WX_DIR))))
        raise FileNotFoundError('template file not found: %s' % template_path)

    ensure_foreground(hwnd)
    l, t, r, b = win_rect(hwnd)
    if region:
        rx0, ry0, rx1, ry1 = region
        sx0, sy0, sx1, sy1 = l + rx0, t + ry0, l + rx1, t + ry1
    else:
        sx0, sy0, sx1, sy1 = l, t, r, b
    screen = ImageGrab.grab(bbox=(sx0, sy0, sx1, sy1))
    tpl = Image.open(template_path)
    screen_g = cv2.cvtColor(np.array(screen.convert('RGB')), cv2.COLOR_RGB2GRAY)
    tpl_g = cv2.cvtColor(np.array(tpl.convert('RGB')), cv2.COLOR_RGB2GRAY)
    if screen_g.shape[0] < tpl_g.shape[0] or screen_g.shape[1] < tpl_g.shape[1]:
        return None
    res = cv2.matchTemplate(screen_g, tpl_g, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    tx, ty = max_loc
    abs_cx = sx0 + tx + tpl_g.shape[1] // 2
    abs_cy = sy0 + ty + tpl_g.shape[0] // 2
    return int(abs_cx), int(abs_cy), float(max_val)


def find_templates(hwnd, template_path, region=None, threshold=0.82,
                   min_gap=25):
    """在窗口(或指定区域内)用模板匹配找所有相似图标(如多个标签的 × 按钮)。

    region: (x0, y0, x1, y1) 窗口内相对坐标;None=整个窗口
    min_gap: 合并重叠匹配的最小像素间距(px)
    返回 [(abs_cx, abs_cy, score)] 按 x 升序,空列表表示没找到。
    """
    import cv2

    if not os.path.isfile(template_path):
        print('ERROR - TEMPLATE_FILE_MISSING %s' % template_path)
        print('WX_DIR=%s files=%s' % (WX_DIR, sorted(os.listdir(WX_DIR))))
        raise FileNotFoundError('template file not found: %s' % template_path)

    ensure_foreground(hwnd)
    l, t, r, b = win_rect(hwnd)
    if region:
        rx0, ry0, rx1, ry1 = region
        sx0, sy0, sx1, sy1 = l + rx0, t + ry0, l + rx1, t + ry1
    else:
        sx0, sy0, sx1, sy1 = l, t, r, b
    screen = ImageGrab.grab(bbox=(sx0, sy0, sx1, sy1))
    tpl = Image.open(template_path)
    screen_g = cv2.cvtColor(np.array(screen.convert('RGB')), cv2.COLOR_RGB2GRAY)
    tpl_g = cv2.cvtColor(np.array(tpl.convert('RGB')), cv2.COLOR_RGB2GRAY)
    if screen_g.shape[0] < tpl_g.shape[0] or screen_g.shape[1] < tpl_g.shape[1]:
        return []
    res = cv2.matchTemplate(screen_g, tpl_g, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    hits = []
    for x, y in zip(*loc[::-1]):
        hits.append((x, y, float(res[y, x])))
    # 按 score 降序合并重叠
    hits.sort(key=lambda h: -h[2])
    merged = []
    for x, y, s in hits:
        if not any(abs(x - mx) < min_gap and abs(y - my) < min_gap
                   for mx, my, _ in merged):
            merged.append((x, y, s))
    merged.sort(key=lambda h: h[0])
    tw, th = tpl_g.shape[1], tpl_g.shape[0]
    return [(int(sx0 + x + tw // 2), int(sy0 + y + th // 2), float(s))
            for x, y, s in merged]


def screen_shot(hwnd, path=None):
    """截取窗口区域,可选保存,返回 (PIL.Image, (l,t,r,b))。
    截图前确保窗口在前台,否则截到的是盖住它的其他窗口内容。"""
    ensure_foreground(hwnd)
    l, t, r, b = win_rect(hwnd)
    shot = ImageGrab.grab(bbox=(l, t, r, b))
    if path:
        shot.save(path)
    return shot, (l, t, r, b)


def list_ocr(hwnd, path=None):
    """整窗口截图后 OCR(与 tag1 首屏识别完全一致)。
    返回与 tag1 相同的全窗口 items(带窗口偏移)。tag2 滚动后识别/点击
    坐标错误曾因 REGION_LIST 区域截断 + 残行混入,统一走整窗口可消除。"""
    shot, (l, t, r, b) = screen_shot(hwnd, path)
    raw = ocr_image(shot)
    items = [(cy, x0, x1, txt) for cy, x0, x1, txt in raw]
    items.sort()
    return items, (l, t, r, b)


# ================================================================ 动态布局(去硬编码)
# 原 REGION_* 常量按 1920 宽设计,换机器/窗口尺寸变化会导致区域错位。
# 现改为: 区域按窗口宽高比例生成(get_region);列表布局参数(col_split 左右列分界、
# min_y 列表起始 y)由首屏 OCR 自动学习并缓存(cache.json 的 layout 分区),跨运行复用。
_DEFAULT_COL_SPLIT = 720     # 左右列分界兜底(双列瀑布流布局)
_DEFAULT_LIST_MIN_Y = 250    # 列表起始 y 兜底(顶部标签栏/搜索区之下)
_LAYOUT = None               # 缓存: {'col_split': int, 'list_top': int}
_TAB_BAR_MARGIN = 8          # 标签栏行下方余量: 列表起始 y 至少 = tab_bar_y + 该值


def get_region(kind, hwnd=None, w=0, h=0):
    """按窗口尺寸比例生成 OCR/模板区域(替代按 1920 宽写死的 REGION_*)。
    返回 (x0, y0, x1, y1) 窗口内相对坐标。hwnd 或 (w,h) 提供实际尺寸。
    kind: tabbar / menu / article_tab / searchbox / searchbox_ocr /
          home_icon / account_ocr。"""
    if hwnd is not None:
        l, t, r, b = win_rect(hwnd)
        w, h = max(r - l, 1), max(b - t, 1)
    w = max(w, 1)
    h = max(h, 1)
    r = {
        # 顶部标签栏(更多按钮): 顶部一条
        'tabbar': (0, 0, w, max(60, int(h * 0.06))),
        # 更多菜单弹出区: 顶部向下约半屏
        'menu': (0, max(40, int(h * 0.04)), w, int(h * 0.55)),
        # "文章"标签: 上部中部偏左
        'article_tab': (int(w * 0.15), int(h * 0.08), int(w * 0.85), int(h * 0.35)),
        # 搜索框(模板匹配): 上部。注意上下界都必须留足模板高度余量,
        # 否则模板任一侧被裁剪 -> TM_CCOEFF_NORMED 分数崩盘 (实测 1.00->0.28/0.48)。
        # 实测: wx_search.png(70x25) 中心在窗口内 (116,57), 顶边 y=45;
        # 若上界取 h*0.08(=51) 会裁掉模板顶 6px -> 分数 1.00->0.48 匹配失败。
        # 故上界放宽到 0(顶部整条), 下界取 h*0.55 保证完整包含。
        'searchbox': (0, 0, w, int(h * 0.55)),
        # 搜索框(OCR 兜底)
        'searchbox_ocr': (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.55)),
        # 微信侧边栏 home 图标: 最左侧窄条
        'home_icon': (0, 0, max(70, int(w * 0.06)), int(h * 0.7)),
        # 搜索结果公众号区
        'account_ocr': (int(w * 0.15), int(h * 0.08), int(w * 0.85), int(h * 0.35)),
    }
    return r.get(kind, (0, 0, w, h))


# ================================================================
# 侦查层 (recon): 流程开始前/每个阶段先定位全部模板,
# 写入 recon_<phase>.json, 供 tag 原生 click 与 py 块共用。
# 用户要求: 开源项目不写死坐标 -> 每个图标都在运行时用模板匹配现找,
# 找不到立即降级 OCR/比例 fallback, 每级打印清晰原因。
# ================================================================

# 各阶段需要侦查的模板: {模板文件名: (region_kind, 用途)}
RECON_PHASES = {
    'main':  {'home.png':        ('home_icon', '主窗口侧边栏 home 图标(进入搜一搜)')},
    'soss':  {'input_field.png': ('searchbox', '搜一搜搜索框(输入公众号名)')},
    'article': {'article.png':   ('article_tab', '结果页"文章"标签(切换文章列表)')},
    'detail': {'more.png':       ('tabbar', '详情页"更多"菜单按钮'),
               'copy_url.png':   ('menu', '菜单中"复制链接"项')},
}


def recon_layout(phase, hwnd):
    """对指定阶段做模板侦查: 在当前窗口内定位该阶段全部模板,
    返回 {模板名: (abs_cx, abs_cy, score)} 并写 recon_<phase>.json。
    score 低于阈值的不收录。用于 preflight 校验 + 原生 click 前的准备确认。"""
    found = {}
    for tpl, (region_kind, usage) in RECON_PHASES.get(phase, {}).items():
        path = os.path.join(WX_DIR, tpl)
        hit = find_template(hwnd, path, region=get_region(region_kind, hwnd))
        if hit:
            found[tpl] = list(hit)
            print('RECON[%s] %s -> (%d,%d) score=%.3f (%s)'
                  % (phase, tpl, hit[0], hit[1], hit[2], usage))
        else:
            print('RECON[%s] %s -> NOT_FOUND (%s)'
                  % (phase, tpl, usage))
    try:
        write_json('recon_%s.json' % phase, {
            'phase': phase,
            'window_rect': win_rect(hwnd),
            'templates': {k: {'x': v[0], 'y': v[1], 'score': v[2]}
                          for k, v in found.items()},
        })
    except Exception as e:
        print('RECON_WRITE_FAIL %s: %s' % (phase, e))
    return found


def get_template_coord(hwnd, template_name, region_kind, section,
                       label, refresh=False):
    """获取某模板图标在窗口内的绝对屏幕坐标(通用缓存侦查)。

    与 input_field 同模式: 优先读统一缓存 cache.json 对应分区
    (绑定窗口 rect, 位置一致才复用); 无缓存/窗口移动/refresh 时用模板匹配
    侦查并写缓存。返回 (abs_x, abs_y, score) 或 None。跨运行复用缓存,
    免去每次 TagUI 原生 SikuliX 全屏扫描(0.5-2s)。"""
    rect = win_rect(hwnd)
    sec = read_cache(section)
    if not refresh and sec.get('window_rect') == list(rect):
        hit = sec.get('coord')
        if hit and len(hit) == 3:
            print('%s_FROM_CACHE @ (%d,%d) score=%.3f'
                  % (label, hit[0], hit[1], hit[2]))
            return tuple(hit)
    hit = find_template(hwnd, os.path.join(WX_DIR, template_name),
                        region=get_region(region_kind, hwnd))
    if hit:
        try:
            write_cache(section, {
                'window_rect': list(rect),
                'coord': list(hit),
                'recon_at': datetime.datetime.now().isoformat(timespec='seconds'),
            })
            print('%s_RECON @ (%d,%d) score=%.3f (已缓存 %s)'
                  % (label, hit[0], hit[1], hit[2], CACHE_FILE))
        except Exception as e:
            print('%s_CACHE_WRITE_FAIL %s' % (label, e))
    return hit


def get_input_field(hwnd, refresh=False):
    """获取搜一搜搜索框(input_field.png)的绝对屏幕坐标(委托通用版)。"""
    return get_template_coord(hwnd, 'input_field.png', 'searchbox',
                              CACHE_INPUT_FIELD,
                              'INPUT_FIELD', refresh=refresh)


def get_article_coord(hwnd):
    """获取"文章"标签(article.png)的绝对屏幕坐标(与 input_field 同缓存模式)。

    缓存分区 article 按文章类型命名, 新机器首次自动侦查写缓存,
    后续复用坐标点击, 免去 TagUI 原生 SikuliX 全屏扫描(0.5-2s)。"""
    return get_template_coord(hwnd, 'article.png', 'article_tab',
                              CACHE_ARTICLE, 'ARTICLE')


def preflight_main(main_hwnd=None):
    """流程前置侦查: 验证主窗口 home 图标可定位。
    返回 (ok, found)。ok=False 时调用方应回退到搜索框方案或中止。
    注意: 微信主窗口可能是隐藏/托盘状态,必须先强制带到前台,
    否则 find_template 截图截到的是盖住微信的其他窗口 -> 误判无图标。"""
    mh = main_hwnd or find_weixin_main()
    if not mh:
        print('ERROR - NO_WECHAT_MAIN_WINDOW')
        return False, {}
    if not _force_foreground(mh):
        print('PREFLIGHT_MAIN WARN - 主窗口未能带到前台,后续截图可能截到其他窗口')
    found = recon_layout('main', mh)
    ok = 'home.png' in found
    print('PREFLIGHT_MAIN %s (home_icon_score=%.3f)'
          % ('OK' if ok else 'FAIL',
             found.get('home.png', [0, 0, 0])[2]))
    return ok, found


def _load_layout():
    """读统一缓存 cache.json 的 layout 分区(失败/不存在返回 None)"""
    try:
        return read_cache(CACHE_LAYOUT) or None
    except Exception:
        return None


def _probe_window_rect():
    """探测当前可用窗口(SOSS 优先,其次微信主窗口)的尺寸。
    返回 (w, h);无窗口可探测时返回 (0, 0)。
    用于布局兜底按窗口比例计算,避免绝对像素在不同分辨率/窗口尺寸下失效。"""
    hwnd = find_wx_window() or find_weixin_main()
    if hwnd:
        l, t, r, b = win_rect(hwnd)
        return max(r - l, 1), max(b - t, 1)
    return 0, 0


def _layout_fallback(kind):
    """布局兜底值: 优先按当前窗口尺寸比例计算,窗口不可探测时回退绝对常量。
    kind: 'col_split' -> 双列分界 ≈ 窗口宽 37.5%(等价 720/1920);
          'list_top'  -> 列表起始 ≈ 窗口高 26%(等价 250/960)。"""
    w, h = _probe_window_rect()
    if kind == 'col_split' and w:
        return int(w * 0.375)
    if kind == 'list_top' and h:
        return int(h * 0.26)
    return _DEFAULT_COL_SPLIT if kind == 'col_split' else _DEFAULT_LIST_MIN_Y


def get_col_split():
    """当前左右列分界 x(窗口内相对坐标)。优先 cache.json 的 layout 分区学习值,
    否则按当前窗口宽度比例兜底(双列瀑布流分界 ≈ 37.5% 窗口宽)。"""
    global _LAYOUT
    if _LAYOUT is None:
        _LAYOUT = _load_layout() or {}
    return int(_LAYOUT.get('col_split') or _layout_fallback('col_split'))


def get_list_min_y():
    """当前列表起始 y(窗口内相对坐标)。优先 cache.json 的 layout 分区学习值,
    否则按当前窗口高度比例兜底(列表起始 ≈ 26% 窗口高)。"""
    global _LAYOUT
    if _LAYOUT is None:
        _LAYOUT = _load_layout() or {}
    return int(_LAYOUT.get('list_top') or _layout_fallback('list_top'))


def _learn_layout(items, anchor_y=None):
    """从首屏 OCR 结果自动学习列表布局,写入统一缓存 cache.json 的 layout 分区。
    1) col_split: 取所有文本 x0 分布的最大间隙中点(左右列分界);
    2) list_top:  取最顶部文章标题的 cy,下修一个余量(避开标签栏/搜索区)。
    anchor_y: 点击"文章"标签时鼠标停留位置的窗口内相对 y(标签栏 y 即
    列表起始锚点,最准)。优先用 anchor_y + _TAB_BAR_MARGIN 作为 list_top;
    无锚点才用 OCR 推断(首条标题 cy - 30)。
    学习失败时保持原值,调用方继续用兜底(按窗口比例)。
    所有内部阈值均按 OCR 覆盖范围(w_est/h_est)比例化,不依赖绝对像素。"""
    global _LAYOUT
    cur = _load_layout() or {}
    # 估算窗口尺寸: OCR 覆盖范围近似窗口内容区(绝对像素阈值按此比例化)
    h_est = max((cy for cy, _, _, _ in items), default=0) or 960
    w_est = max((x1 for _, _, x1, _ in items), default=0) or 1200
    xs = sorted(x0 for _, x0, _, _ in items if x0 > 0)
    if len(xs) >= 2:
        # 找相邻 x0 的最大间隙(双列布局: 左列约 28%宽,右列约 75%宽)
        max_gap, split = 0, None
        for i in range(len(xs) - 1):
            gap = xs[i + 1] - xs[i]
            if gap > max_gap:
                max_gap, split = gap, (xs[i] + xs[i + 1]) / 2
        if split and max_gap > w_est * 0.25:   # 间隙足够大(≥25%窗宽)才视为列分界
            cur['col_split'] = int(split)
    # 列表顶部: 优先用点击"文章"标签的鼠标位置(标签栏 y 即列表起始锚点)
    top_cy = int(h_est * 0.08)      # 顶部 8% 视为标签栏/搜索区,标题须在其下
    if anchor_y is not None and anchor_y > 0:
        cur['list_top'] = int(anchor_y) + _TAB_BAR_MARGIN
        print('LAYOUT_LIST_TOP_ANCHOR=%d (文章标签 y=%d + margin=%d)'
              % (cur['list_top'], int(anchor_y), _TAB_BAR_MARGIN))
    else:
        # 无锚点(非点击路径/锚点异常): OCR 推断最顶部标题位置
        min_w = int(w_est * 0.12)   # 标题行一般明显宽于标签(≥12%窗宽)
        tops = [cy for cy, x0, x1, t in items
                if cy > top_cy and not _is_noise_line(t)
                and not ('阅读' in t or '赞' in t)
                and x1 - x0 > min_w]
        if tops:
            cur['list_top'] = max(top_cy, int(tops[0]) - 30)
    if cur.get('col_split') or cur.get('list_top'):
        write_cache(CACHE_LAYOUT, {
            'col_split': cur.get('col_split'),
            'list_top': cur.get('list_top'),
            'learned_at': datetime.datetime.now().isoformat(timespec='seconds'),
        })
        _LAYOUT = cur
        print('LAYOUT_LEARNED col_split=%s list_top=%s'
              % (cur.get('col_split'), cur.get('list_top')))
    return cur


# ================================================================ 工作目录 / JSON / 剪贴板
def get_work_dir():
    """当前任务的工作目录: 读 workdir.txt(由 setup 阶段创建)。
    每次执行使用独立临时工作目录,完成后移除;文件不存在则回退 WX_DIR。"""
    path = WORKDIR_FILE
    try:
        with open(path, encoding='utf-8') as f:
            d = f.read().strip()
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return WX_DIR


def get_work_dir_or_none():
    """读 workdir.txt 获取当前任务工作目录;无则 None"""
    try:
        with open(WORKDIR_FILE, encoding='utf-8') as f:
            d = f.read().strip()
        return d if d and os.path.isdir(d) else None
    except Exception:
        return None


def read_json(name, default=None):
    path = os.path.join(get_work_dir(), name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json(name, data):
    path = os.path.join(get_work_dir(), name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_cache(section):
    """读统一缓存 cache.json 中某分区(不存在/损坏返回 {})。"""
    cache = read_json(CACHE_FILE, {}) or {}
    return cache.get(section) or {}


def write_cache(section, data):
    """合并写统一缓存 cache.json 某分区(保留其他分区,勿整体覆盖)。"""
    cache = read_json(CACHE_FILE, {}) or {}
    cache[section] = data
    write_json(CACHE_FILE, cache)


def get_clipboard():
    import pyperclip
    return pyperclip.paste() or ''


def set_clipboard(text, tries=10, delay=0.5):
    """写入剪贴板,带重试。微信(WeChatAppEx)/其他进程可能持有剪贴板
    (OpenClipboard 失败,WinError 0),立即重试常失败;反复尝试+清空可恢复。
    返回是否成功;全部失败抛出异常(调用方需处理)。"""
    import pyperclip
    import ctypes
    user32 = ctypes.windll.user32
    for i in range(tries):
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            # 尝试强制清空(EmptyClipboard 需先 OpenClipboard 成功)
            try:
                if user32.OpenClipboard(0):
                    user32.EmptyClipboard()
                    user32.CloseClipboard()
            except Exception:
                pass
            time.sleep(delay)
    # 最后一次直接抛
    pyperclip.copy(text)
    return True


def log(msg):
    print(msg, flush=True)


# ================================================================ 日期/阅读数解析
def today_str():
    return datetime.date.today().strftime('%Y-%m-%d')


def _weekday_offset(weekday_cn):
    """中文星期X -> 距今天数(过去7天内最近的那个星期X)"""
    names = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
    if weekday_cn not in names:
        return None
    target = names[weekday_cn]
    today = datetime.date.today()
    # Python weekday(): 周一=0 ... 周日=6,与 names 映射一致
    today_wd = today.weekday()
    diff = (today_wd - target) % 7
    if diff == 0:
        diff = 7  # 今天的"星期X"通常指向上一周
    return (today - datetime.timedelta(days=diff)).strftime('%Y-%m-%d')


def parse_date(text):
    """从文本中提取发布日期,返回 'YYYY-MM-DD' 或 None"""
    if not text:
        return None
    today = datetime.date.today()

    # 绝对日期
    m = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', text)
    if m:
        try:
            return '%04d-%02d-%02d' % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # X月X日(今年)
    m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if m:
        try:
            d = datetime.date(today.year, int(m.group(1)), int(m.group(2)))
            return d.strftime('%Y-%m-%d')
        except ValueError:
            pass

    # N小时前 / N分钟前 -> 今天
    if re.search(r'\d+\s*(小时|分钟)前', text):
        return today_str()

    # N天前
    m = re.search(r'(\d+)\s*天前', text)
    if m:
        d = today - datetime.timedelta(days=int(m.group(1)))
        return d.strftime('%Y-%m-%d')

    # 昨天 / 前天
    if '前天' in text:
        return (today - datetime.timedelta(days=2)).strftime('%Y-%m-%d')
    if '昨天' in text:
        return (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

    # 星期X
    m = re.search(r'星期([一二三四五六日天])', text)
    if m:
        return _weekday_offset(m.group(1))

    return None


def parse_read_count(text):
    """从文本中提取阅读数: '阅读1308' -> 1308; '阅读5.3万' -> 53000; 返回 int 或 None"""
    if not text:
        return None
    m = re.search(r'阅读\s*(\d+(?:\.\d+)?)\s*(万\+?)?', text)
    if m:
        num = float(m.group(1))
        if m.group(2):  # 万
            num *= 10000
        return int(num)
    # 纯数字形式 "阅读 2.8万" 已覆盖; 再试 "阅读1308"
    m = re.search(r'阅读\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return None


def _is_noise_line(t):
    """是否非标题噪音行(按钮/标签/正文片段/账号头部)"""
    if t in ('关注', '私信', '全部', '贴图', '文章', '视频号', '更多', '复制链接', '刷新', '展开'):
        return True
    # 日期/星期分组行: 微信搜一搜公众号列表按日期分组,
    # "7月15日" / "星期五" / "昨天" 等是分组标题,不是文章标题。
    if re.fullmatch(r'\d{1,2}月\d{1,2}日', t):
        return True
    if re.fullmatch(r'星期[一二三四五六日天]', t):
        return True
    if t in ('今天', '昨天', '前天'):
        return True
    # 账号头部噪音: 简介正文片段/原创内容统计/视频号账号行
    if ('原创内容' in t or '视频号：' in t or t.startswith('视频号')
            or re.search(r'篇原创', t)):
        return True
    # 账号简介: 公众号简介是完整陈述句(以句号结尾 + 标点密集 + 长度偏长),
    # 而文章标题通常较短且不带句号/无标点结构。简介常被 OCR 拆成多行,
    # 这里按"句号结尾的完整陈述句"特征识别,避免简介抢占 pending_title。
    if ('。' in t or '；' in t) and ('，' in t or '、' in t) and len(t) >= 12:
        return True
    # 标签栏行: 纯标签词组合(OCR 可能拆成 "全部贴图" / "文章视频号" 等块)
    if sum(1 for w in TAB_WORDS if w in t) >= 3:
        return True
    # 纯标签词组合(1-2个词): "全部贴图" "文章视频号" "全部" 等
    if re.fullmatch(r'[全部贴图文章视频号服务号小程序朋友圈公众号]+', t):
        return True
    return False


def _parse_single_column(col_items):
    """单列内解析: 标题行 + 元信息行(日期 阅读X 赞Y) 成对出现。
    col_items: [(cy, x0, x1, text)] 已按 y 升序(且同属一列)。
    微信搜一搜公众号列表为"日期分组"结构:
        7月15日            <- 日期分组行(独立,无阅读/赞)
        35.5%！隆基再次...  <- 文章标题(可能被 OCR 拆成多行)
        阅读7741 赞53      <- 元信息行(闭合一条)
    日期分组行不作为标题;文章条目的 date 从上方最近的分组行继承。
    返回: [{title, date, read_count, cy, cx, cx0}]"""
    items = []
    pending_title = None
    pending_cy = None
    pending_cx = None
    pending_cx0 = None
    cur_date = None   # 最近看到的日期分组行(7月X日 / 星期X),供文章继承
    for cy, x0, x1, t in col_items:
        # 日期/星期分组行: 记录为当前分组日期,不作为标题
        d = parse_date(t)
        if d and ('阅读' not in t) and ('赞' not in t):
            cur_date = d
            continue
        # 元信息行: 含 阅读 或 赞
        if ('阅读' in t) or ('赞' in t):
            if pending_title is not None:
                items.append({
                    'title': pending_title,
                    'date': parse_date(t) or cur_date,
                    'read_count': parse_read_count(t),
                    'cy': pending_cy,
                    'cx': pending_cx,
                    'cx0': pending_cx0,
                })
                pending_title = None
                pending_cy = None
                pending_cx = None
                pending_cx0 = None
        else:
            if _is_noise_line(t):
                continue
            if pending_title is None:
                pending_title = t
                pending_cy = cy
                pending_cx = int((x0 + x1) / 2)
                pending_cx0 = int(x0)   # 标题左缘: detail 点击用,避开"复制成功"弹窗遮挡
            # 标题行可能被 OCR 拆成多行,保留第一行作为标题
    return items


def _tab_bar_y(ocr_items):
    """标签栏行 y(窗口内相对坐标): '文章/全部贴图/视频号' 等标签词组合行。
    搜一搜账号头部(简介/关注/私信/标签栏)整体位于文章列表之上,标签栏行是
    头部与列表的分界锚点。滚动后头部可能仍残留在顶部,故每次 OCR 都重新锚定。
    OCR 常把标签栏拆成多个独立词块('全部' '贴图' '文章' '视频号' 各成一块),
    单块只含 1 个标签词导致按行判断永远不满足 >=2。故先按 y 聚类合并同行的
    词块,再统计合并文本中的标签词数(>=2 即视为标签栏,含 '文章' 优先)。
    返回 cy 或 None。"""
    if not ocr_items:
        return None
    # 按 y 聚类(±10px 视为同行): 合并 OCR 拆散的标签栏词块
    rows = []  # [{'cy': float, 'text': str}]
    for cy, x0, x1, t in ocr_items:
        if not t:
            continue
        for row in rows:
            if abs(row['cy'] - cy) <= 10:
                row['text'] += t
                row['cy'] = (row['cy'] + cy) / 2
                break
        else:
            rows.append({'cy': float(cy), 'text': t})
    rows.sort(key=lambda r: r['cy'])
    for row in rows:
        txt = row['text']
        if not _is_noise_line(txt):
            continue
        tag_cnt = sum(1 for w in TAB_WORDS if w in txt)
        if tag_cnt >= 2 or ('文章' in txt and tag_cnt >= 1):
            return row['cy']
    return None


def parse_list_items(ocr_items, min_y=0, col_split=None):
    """从文章列表 OCR 结果解析条目。

    ocr_items: [(cy, x0, x1, text)] 按 y 升序
    微信搜一搜文章列表为双列/瀑布流布局: 左列标题 x0≈280,右列标题 x0≈970。
    必须先按 x 分列、每列内独立做"标题+元信息"配对,再合并按 y 排序;
    否则左右两列交错会把右列标题吞掉、元信息错配(滚动后坐标全错的根因)。
    col_split 缺省时用布局学习值(get_col_split),兜底 720。
    有效 min_y = max(min_y, 标签栏行 y + _TAB_BAR_MARGIN): 账号头部
    (简介/关注/私信/标签栏)整体位于标签栏行之上,标签栏行是列表起始锚点,
    避免把账号简介误当第一篇文章(点击坐标错位的根因)。
    返回: [{title, date, read_count, cy, cx, cx0}] (date/read_count 可能为 None)
    """
    if col_split is None:
        col_split = get_col_split()
    tby = _tab_bar_y(ocr_items)
    if tby is not None:
        min_y = max(min_y, tby + _TAB_BAR_MARGIN)
    left, right = [], []
    for cy, x0, x1, t in ocr_items:
        if cy < min_y:
            continue
        if x0 < col_split:
            left.append((cy, x0, x1, t))
        else:
            right.append((cy, x0, x1, t))
    left.sort()
    right.sort()
    items = _parse_single_column(left) + _parse_single_column(right)
    items.sort(key=lambda it: it['cy'])
    return items


def in_range(date_str, start, end):
    """date_str 是否在 [start, end] 范围内;start/end 为 'YYYY-MM-DD' 或 None"""
    if not date_str:
        return False
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


# ================================================================ 文章落库
def gen_article_id(title):
    """按标题生成稳定唯一 id(同标题 id 不变,增量落库可去重)"""
    return hashlib.md5(title.encode('utf-8')).hexdigest()[:12]


def is_tab_bar(title):
    """是否标签栏误解析行(纯标签词组合)"""
    if not title:
        return True
    if sum(1 for w in TAB_WORDS if w in title) >= 2:
        return True
    return False


def load_articles():
    path = os.path.join(get_work_dir(), ARTICLES_FILE)
    if not os.path.exists(path):
        return {'account': '', 'tab': '文章', 'start': None, 'end': None,
                'earliest_visible': None, 'passed_start': False, 'items': []}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'account': '', 'tab': '文章', 'start': None, 'end': None,
                'earliest_visible': None, 'passed_start': False, 'items': []}


def save_articles(data):
    path = os.path.join(get_work_dir(), ARTICLES_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def upsert(parsed_items, account='', tab='文章', start=None, end=None):
    """增量落库。parsed_items: parse_list_items 的输出(含 title/date/read_count/cy/cx)。
    只落库日期在 [start,end] 内的条目;已存在 title 跳过。
    返回 (total, added, pending_url, earliest_visible, passed_start)"""
    data = load_articles()
    if account:
        data['account'] = account
    if tab:
        data['tab'] = tab
    if start is not None:
        data['start'] = start
    if end is not None:
        data['end'] = end

    # 按归一化标题去重: 滚动后 OCR 标题可能与首屏有微小差异(截断/空格/标点),
    # 直接用原始标题会导致同一篇文章重复落库(重复抓 URL)。
    by_title = {_norm_title(a.get('title', '')): a for a in data['items']}
    added = 0
    for it in parsed_items:
        title = it.get('title')
        if not title or is_tab_bar(title):
            continue
        date = it.get('date')
        if not date or not in_range(date, start, end):
            continue
        ntitle = _norm_title(title)
        if ntitle in by_title:
            # 滚动后同一文章可能仍在屏幕且位置变化: 刷新坐标(保留已抓取的 url)
            ex = by_title[ntitle]
            if it.get('cy') is not None:
                ex['cy'] = it['cy']
            if it.get('cx') is not None:
                ex['cx'] = it['cx']
            if it.get('cx0') is not None:
                ex['cx0'] = it['cx0']
            continue
        by_title[ntitle] = {
            'id': gen_article_id(title),
            'title': title,
            'date': date,
            'read_count': it.get('read_count'),
            'cy': it.get('cy'),
            'cx': it.get('cx'),
            'cx0': it.get('cx0'),
            'url': '',          # detail 阶段回写
        }
        added += 1

    data['items'] = list(by_title.values())
    data['items'].sort(key=lambda x: x.get('date', '') or '', reverse=True)

    dates = [it.get('date') for it in parsed_items
             if it.get('date') and not is_tab_bar(it.get('title', ''))]
    earliest = min(dates) if dates else None
    data['earliest_visible'] = earliest
    data['passed_start'] = bool(start and earliest and earliest < start)

    save_articles(data)
    pending = sum(1 for a in data['items'] if not a.get('url'))
    return len(data['items']), added, pending, earliest, data['passed_start']


# ================================================================ 全选复制文本解析
def clean_head(text):
    """去掉搜索框提示、分类标签、筛选标签等头部噪音"""
    idx = text.find(HEAD_NOISE_END)
    if idx != -1:
        return text[idx + len(HEAD_NOISE_END):]
    return text


def split_items(text):
    """按 'N篇原创内容' 结尾标志切分为条目块"""
    # 用前瞻切分:每个 "N篇原创内容" 后是下一条目开头
    pattern = re.compile(r'(\d+篇原创内容(?:\s*\d+[小时天]+前更新)?)')
    parts = pattern.split(text)
    items = []
    current = ''
    for part in parts:
        if pattern.fullmatch(part.strip()):
            if current.strip():
                items.append((current.strip(), part.strip()))
            current = ''
        else:
            current += part
    if current.strip():
        items.append((current.strip(), ''))
    return items


def extract_first_line(body):
    """条目正文第一段 = 名称 + 认证主体(通常同一行,用空格分隔)"""
    # 去掉换行,压缩空格
    flat = re.sub(r'\s+', ' ', body).strip()
    # 第一段通常是 "名称 认证主体" 或 "名称"
    return flat


def parse_items_from_text(text, target=None):
    text = clean_head(text)
    items = split_items(text)
    results = []
    for i, (body, tail) in enumerate(items):
        flat = extract_first_line(body)
        results.append({'index': i + 1, 'body': flat, 'tail': tail})
    return results


# ================================================================ 工作目录管理
def setup_work_dir():
    """创建独立临时工作目录,拷贝流程/脚本/模板,写 workdir.txt。返回目录路径。
    拷贝后校验必需素材是否齐全: 任一缺失立即中止,避免 tag 运行到一半才崩溃。"""
    base = os.path.join(WX_DIR, '.tasks')
    os.makedirs(base, exist_ok=True)
    wd = tempfile.mkdtemp(prefix='wx_task_', dir=base)
    copied = 0
    for f in os.listdir(WX_DIR):
        src = os.path.join(WX_DIR, f)
        if not os.path.isfile(src):
            continue
        if f.endswith(COPY_EXTS):
            shutil.copy2(src, os.path.join(wd, f))
            copied += 1
    required = list(REQUIRED_TEMPLATES) + ['tag_all.tag', 'wx_article.py']
    missing = [f for f in required
               if not os.path.isfile(os.path.join(wd, f))]
    if missing:
        print('ERROR - WORK_DIR_COPY_INCOMPLETE missing=%s' % missing)
        print('SOURCE_WX_DIR=%s files=%s'
              % (WX_DIR, sorted(os.listdir(WX_DIR))))
        shutil.rmtree(wd, ignore_errors=True)
        if os.path.exists(WORKDIR_FILE):
            os.remove(WORKDIR_FILE)
        raise SystemExit(1)
    with open(WORKDIR_FILE, 'w', encoding='utf-8') as fh:
        fh.write(wd)
    print('WORK_DIR=%s' % wd)
    print('COPIED=%d' % copied)
    return wd


def cleanup_work_dir():
    """移除临时工作目录内的全部拷贝件,仅保留 JSON 结果文件(如 search_result.json /
    articles.json / agent_config.json),并删除 workdir.txt。
    因句柄占用导致的删除失败会列出残留供诊断,不再静默忽略。"""
    wd = get_work_dir_or_none()
    if wd and os.path.isdir(wd):
        for name in sorted(os.listdir(wd)):
            # 保留 JSON 与 TagUI 运行日志(_tag_stdout.log),便于排查滚动/抓取问题
            if name.lower().endswith('.json') or name == '_tag_stdout.log':
                continue  # 这些文件保留在临时目录中
            p = os.path.join(wd, name)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError as e:
                print('WARN - CLEANUP_FAILED %s: %s' % (p, e))
        leftover = [n for n in os.listdir(wd)
                    if n != '_tag_stdout.log' and not n.lower().endswith('.json')]
        if leftover:
            print('WARN - WORK_DIR_PARTIAL_CLEANUP leftover=%s' % leftover)
        else:
            print('KEPT_IN_WORK_DIR=%s' % sorted(os.listdir(wd)))
    if os.path.exists(WORKDIR_FILE):
        os.remove(WORKDIR_FILE)


def write_config(account='', tab='文章', start=None, end=None, limit=50):
    """写入 agent_config.json(工作目录内)。返回 cfg dict"""
    prev = read_json('agent_config.json', {}) or {}
    cfg = {
        'account': account or prev.get('account', ''),
        'tab': tab or prev.get('tab', '文章'),
        'start': start or prev.get('start') or None,
        'end': end or prev.get('end') or None,
        'limit': limit if limit is not None else prev.get('limit', 50),
    }
    write_json('agent_config.json', cfg)
    return cfg


# ================================================================ 中断清理
# Ctrl+C / 关闭控制台窗口 / Ctrl+Break 时,停止整个自动化:
# 杀掉 TagUI 进程树 -> 关闭搜一搜窗口 -> 移除临时目录 -> 退出
_ACTIVE_PROC = None       # 当前正在运行的 TagUI 子进程(供信号清理)
_CTRL_HANDLER = None      # 保持回调引用,防被 GC 回收

_CTRL_C_EVENT = 0
_CTRL_BREAK_EVENT = 1
_CTRL_CLOSE_EVENT = 2


def _kill_active_tag():
    """杀掉当前 TagUI 进程整棵树(连根清除,防孤儿 node 残留)"""
    global _ACTIVE_PROC
    if _ACTIVE_PROC is None:
        return
    try:
        pid = _ACTIVE_PROC.pid
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                       capture_output=True, timeout=15)
        try:
            _ACTIVE_PROC.wait(timeout=5)
        except Exception:
            pass
        print('KILLED_TAGUI_TREE pid=%d' % pid)
    except Exception as e:
        print('ERROR - KILL_TAGUI_FAILED: %s' % e)
    finally:
        _ACTIVE_PROC = None


def _interrupt_cleanup(reason):
    """统一中断收尾: 杀进程树 + 关搜一搜窗口 + 清理临时目录"""
    print('==== 收到 %s,停止整个自动化 ====' % reason)
    try:
        _kill_active_tag()
    except Exception:
        pass
    try:
        close_phase()
    except Exception as e:
        print('WARN - INTERRUPT_CLOSE_PHASE: %s' % e)
    try:
        os._exit(130)
    except BaseException:
        pass


def _console_ctrl_handler(ctrl_type):
    """SetConsoleCtrlHandler 回调: CTRL_C / CTRL_CLOSE(关窗口) / CTRL_BREAK"""
    if ctrl_type in (_CTRL_C_EVENT, _CTRL_BREAK_EVENT, _CTRL_CLOSE_EVENT):
        _interrupt_cleanup({_CTRL_C_EVENT: 'Ctrl+C',
                            _CTRL_BREAK_EVENT: 'Ctrl+Break',
                            _CTRL_CLOSE_EVENT: '控制台窗口关闭'}[ctrl_type])
    return True   # 已处理,阻止默认终止行为


def install_ctrl_handler():
    """注册 Windows 控制台事件处理器(每次主流程启动时调用一次)"""
    global _CTRL_HANDLER
    if _CTRL_HANDLER is not None:
        return
    try:
        Proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        _CTRL_HANDLER = Proto(_console_ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, True)
        print('CTRL_HANDLER_INSTALLED')
    except Exception as e:
        print('WARN - CTRL_HANDLER_INSTALL_FAILED: %s' % e)


def run_tag(tag_file, timeout=180):
    """在临时工作目录内执行 tag 流程: 流程/脚本/模板均已拷贝到临时目录,
    通过 WX_WORKDIR 环境变量注入临时目录路径(tag 内 py 块据此加载本文件并落库)。
    timeout: 单次 tag 执行上限秒数,超时强制终止整棵进程树(返回 rc=124 及已捕获输出)。

    注意: TagUI 是 cmd -> tagui.cmd -> node 的多级进程树。若用 subprocess.run(timeout=)
    只会杀掉顶层 cmd,孤儿 node 仍持有 stdout 管道,导致 communicate() 永不返回。
    因此这里把输出重定向到文件(避免管道),超时后用 taskkill /T 连根清除。"""
    wd = get_work_dir()
    env = os.environ.copy()
    env['WX_WORKDIR'] = wd
    env['WX_SOURCE_DIR'] = WX_DIR   # 指回真实源码目录: 子进程副本的 __file__ 指向任务目录,
    # 持久化缓存(cache.json)需写到真实目录才能跨运行复用
    cmd = 'chcp 65001 >nul & "%s" %s -n -q' % (TAGUI_CMD, tag_file)
    log_path = os.path.join(wd, '_tag_stdout.log')
    with open(log_path, 'w', encoding='utf-8', errors='replace') as fh:
        proc = subprocess.Popen(cmd, cwd=wd, shell=True,
                                stdout=fh, stderr=subprocess.STDOUT, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        global _ACTIVE_PROC
        _ACTIVE_PROC = proc
        try:
            proc.wait(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           capture_output=True)
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            rc = 124
        finally:
            _ACTIVE_PROC = None
    with open(log_path, encoding='utf-8', errors='replace') as fh:
        out = fh.read()
    return rc, out


# ================================================================ 环境自检
# 换电脑/首次部署时,一键确认依赖、模板素材、TagUI 启动器、DPI 感知均就绪,
# 避免跑到一半才因缺依赖/缺素材失败。main() 开头调用,发现问题打印原因并退出。
REQUIRED_TEMPLATES = ('home.png', 'wx_search.png', 'input_field.png',
                      'article.png', 'more.png', 'copy_url.png')


def check_environment():
    """启动自检: 返回 (ok, problems)。ok=False 时 main() 应中止。
    检查项: Python 依赖 / 模板素材 / tag_all.tag / TagUI 启动器 / DPI 感知。
    每项只做 import / 文件存在性检查,不弹窗、不启动任何外部程序。"""
    problems = []
    # 1) Python 依赖(延迟 import 逐个验证,给出缺失包名)
    for mod, pkg in (('numpy', 'numpy'), ('PIL', 'pillow'), ('cv2', 'opencv-python'),
                     ('rapidocr_onnxruntime', 'rapidocr_onnxruntime'),
                     ('pyperclip', 'pyperclip')):
        try:
            __import__(mod)
        except Exception:
            problems.append('缺依赖 %s(pip install %s)' % (mod, pkg))
    # 2) 模板素材(tag 流程实际要用的 png)
    for tpl in REQUIRED_TEMPLATES:
        if not os.path.exists(os.path.join(WX_DIR, tpl)):
            problems.append('缺模板素材 %s(应位于 flows/wx/article/)' % tpl)
    # 3) 主流程 tag 文件
    if not os.path.exists(os.path.join(WX_DIR, 'tag_all.tag')):
        problems.append('缺主流程 tag_all.tag(应位于 flows/wx/article/)')
    # 4) TagUI 启动器
    if not os.path.exists(TAGUI_CMD):
        problems.append('找不到 TagUI 启动器 tagui.cmd(当前路径: %s)' % TAGUI_CMD)
    # 5) DPI 感知(截图/坐标正确性的前提)
    if not _DPI_AWARE:
        problems.append('DPI 感知未启用(将导致截图与点击坐标偏移)')
    if problems:
        print('==== 环境自检未通过 ====')
        for p in problems:
            print('  - %s' % p)
        print('请先解决上述问题再运行。')
        return False, problems
    print('ENV_CHECK_OK deps=%d templates=%d tag=%s tagui=%s dpi=%s'
          % (5, len(REQUIRED_TEMPLATES),
             os.path.join(WX_DIR, 'tag_all.tag'), TAGUI_CMD, _DPI_AWARE))
    return True, []


# ================================================================
# 一体化状态机(原 tag_all.tag 的 py 块,由 tag_all.tag 调用 run_pipeline())
# ================================================================
# 模块级上下文,由 run_pipeline() 初始化;step_* 函数只读这些变量
_hwnd = None
_lt = _tt = _rt = _bt = 0      # 搜一搜窗口 rect
_cfg = {}
_account = ''
_start = None
_end = None
_MORE_TPL = ''
_COPY_URL_TPL = ''


def _arts():
    return read_json(ARTICLES_FILE, {'items': []}) or {'items': []}


def _covered(arts):
    """覆盖完成判定: 优先用 upsert 写入的 passed_start(基于原始可见列表,
    含被日期范围过滤掉的早于 start 的文章);无该字段时退回看 items 最小日期。"""
    ps = arts.get('passed_start')
    if ps is not None:
        return bool(ps)
    if not _start:
        return True
    dates = [a['date'] for a in arts['items'] if a.get('date')]
    return bool(dates) and min(dates) < _start


def _pending_ids(arts):
    return [a['id'] for a in arts['items'] if not a.get('url')]


def _locate_account(hwnd, l, t):
    """在搜索结果页 OCR 中定位目标公众号并点击其左缘。
    返回 True/False。"""
    shot, _ = screen_shot(hwnd, os.path.join(WX_DIR, 'tag_all_results.png'))
    res_items = ocr_image(shot)
    EXCLUDE_PREFIX = ('视频号', '公众号:', '小程序', '表情', '文章', '音乐', '朋友圈')
    cands = []
    for cy, x0, x1, txt in res_items:
        if cy < 210:
            continue
        if txt == _account:
            cands.append((cy, x0, x1, txt))
            continue
        if _account in txt and not txt.startswith(EXCLUDE_PREFIX):
            cands.append((cy, x0, x1, txt))
    cands.sort(key=lambda c: c[0])
    if not cands:
        print('ERROR - OCR_TARGET_NOT_FOUND: %s' % _account)
        print('OCR_ITEMS=%s' % [t for _, _, _, t in res_items if t][:20])
        return False
    cy, x0, x1, txt = cands[0]
    abs_x = l + int(x0 - 40)
    abs_y = t + int(cy)
    click_at(abs_x, abs_y)
    print('CLICKED_ACCOUNT %s @ (%d,%d)' % (txt, abs_x, abs_y))
    time.sleep(SLEEP_SEARCH_RESULT)
    return True


# ================================================================
# Flow 级步骤: tag_all.tag 用原生 click 图标 + py 块交错调用。
# 原生 click 由 SikuliX 全屏扫描,不经 get_region(不受 region 裁剪影响);
# py 块负责侦查(确认图标可定位)、粘贴、OCR 定位、滚动、详情抓取。
# 每个 flow_* 均返回 JSON 字符串供 tag 的 `py_result` 输出。
# ================================================================

def _flow_json(ok, **kw):
    d = dict(kw)
    d['ok'] = bool(ok)
    try:
        return json.dumps(d, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({'ok': False, 'error': 'json_dump_failed'})


def flow_begin():
    """阶段A(主窗口)侦查: 确认 home 图标可定位,供 tag 原生 click home.png。
    返回 JSON: {ok, home:(x,y,score), recon:'recon_main.json'}"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end, _MORE_TPL, _COPY_URL_TPL
    wd = os.environ.get('WX_WORKDIR', '')
    if not wd or not os.path.isdir(wd):
        print('ERROR - WX_WORKDIR_NOT_SET')
        raise SystemExit(1)
    sys.path.insert(0, wd)
    _cfg = read_json('agent_config.json', {}) or {}
    _account = _cfg.get('account', '')
    _start = _cfg.get('start')
    _end = _cfg.get('end')
    _MORE_TPL = os.path.join(WX_DIR, 'more.png')
    _COPY_URL_TPL = os.path.join(WX_DIR, 'copy_url.png')
    # fallback 路径: main() 已通过 open_soss_from_main 打开并激活 SOSS。
    # 此时若再 preflight_main(会 _force_foreground 微信主窗口),会导致窗口
    # 焦点从搜一搜跳回微信(用户可见的"弹出又隐藏/来回跳"),且 fallback 根本不
    # 需要 home.png 侦查 -> 直接跳过主窗口侦查,保持 SOSS 在前台。
    if find_wx_window():
        print('FLOW_BEGIN SOSS_ALREADY_OPEN - skip main preflight')
        return _flow_json(True, phase='begin', home=None,
                          recon=None)
    mh = find_weixin_main()
    if not mh:
        print('ERROR - NO_WECHAT_MAIN_WINDOW')
        raise SystemExit(1)
    ok, found = preflight_main(mh)
    print('FLOW_BEGIN %s' % ('OK' if ok else 'FAIL'))
    return _flow_json(ok, phase='begin', home=found.get('home.png'),
                      recon='recon_main.json')


def flow_wait_soss(timeout=30):
    """等待 SOSS 窗口出现并激活,侦查阶段B(input_field 搜索框)并点击。
    侦查坐标优先读缓存(见 get_input_field),命中直接用 SendInput 点击
    (微信搜索框只响应真实输入);无缓存首次自动模板侦查并写缓存。
    供 tag 在 click home.png 后调用(替代原生 click input_field.png)。
    返回 JSON: {ok, hwnd, input_field}"""
    global _hwnd, _lt, _tt, _rt, _bt
    t0 = time.time()
    hwnd = None
    while time.time() - t0 < timeout:
        hwnd = find_wx_window()
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        print('ERROR - SOSS_WINDOW_TIMEOUT')
        raise SystemExit(1)
    activate(hwnd)
    _hwnd = hwnd
    _lt, _tt, _rt, _bt = win_rect(hwnd)
    hit = get_input_field(hwnd)
    ok = hit is not None
    if ok:
        # SendInput 真实点击(不能 click_at: 微信搜索框忽略合成鼠标消息)
        sendinput_click(int(hit[0]), int(hit[1]))
        print('CLICKED_INPUT_FIELD @ (%d,%d) score=%.3f'
              % (int(hit[0]), int(hit[1]), hit[2]))
        time.sleep(SLEEP_UI_SHORT)   # 点击后等待搜索框聚焦(原 tag wait 1)
    print('FLOW_WAIT_SOSS %s hwnd=%s elapsed=%.1fs'
          % ('OK' if ok else 'FAIL', hwnd, time.time() - t0))
    return _flow_json(ok, phase='wait_soss', hwnd=hwnd,
                      input_field=list(hit) if hit else None,
                      recon='recon_soss.json')


def flow_fill_search():
    """阶段B动作: 粘贴账号 -> 回车 -> OCR 定位目标公众号并点击。
    由 tag 在原生 click input_field.png 后调用(纯 py 逻辑块)。
    返回 JSON: {ok, account, located}"""
    global _hwnd, _lt, _tt
    hwnd, l, t = _hwnd, _lt, _tt
    time.sleep(0.2)
    hotkey(VK_CTRL, VK_A)          # ctrl+a 全选(清空输入框)
    hotkey(VK_CTRL, VK_V)          # ctrl+v 粘贴(账号已在 main() 复制到剪贴板)
    time.sleep(SLEEP_UI_SHORT)
    hotkey(VK_ENTER)               # enter 搜索
    print('PASTED_ACCOUNT_AND_ENTER')
    time.sleep(SLEEP_SEARCH_RESULT)
    located = _locate_account(hwnd, l, t)
    if not located:
        print('ERROR - ACCOUNT_LOCATE_FAILED')
        raise SystemExit(1)
    print('FLOW_FILL_SEARCH OK account=%s' % _account)
    return _flow_json(True, phase='fill_search', account=_account,
                      located=True)


def flow_articles():
    """阶段C: 点击"文章"标签 -> 解析首屏 -> 落库 -> 返回状态。
    由 tag 在进入结果页后调用(article 点击已在 py 内用缓存坐标 SendInput 完成,
    tag 不再原生 click article.png)。返回 JSON: {ok, ...}"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    # 点"文章"标签(缓存优先: 首次侦查写 cache.json 的 article 分区, 后续复用坐标;重试)
    art = None
    for attempt in range(RETRY_ARTICLE_TAB):
        art = get_article_coord(hwnd)
        if art:
            # SendInput 真实点击(与搜索框同模式,微信 UI 忽略合成鼠标消息)
            sendinput_click(int(art[0]), int(art[1]))
            print('CLICKED_ARTICLE_TAB @ (%d,%d) score=%.3f (attempt=%d)'
                  % (int(art[0]), int(art[1]), art[2], attempt + 1))
            break
        time.sleep(1.5)
    if not art:
        print('ERROR - ARTICLE_TEMPLATE_NOT_FOUND')
        raise SystemExit(1)
    time.sleep(SLEEP_SEARCH_RESULT)
    # 解析首屏列表并落库;同时学习列表布局供后续滚动复用。
    # 锚点: 点击"文章"标签后鼠标正停在标签上,该 y(窗口内相对)即列表起始。
    art_y = int(art[1]) - t          # 绝对屏幕 y -> 窗口内相对 y
    shot, _ = screen_shot(hwnd, os.path.join(WX_DIR, 'tag_all_articles.png'))
    res_items = ocr_image(shot)
    _learn_layout(res_items, anchor_y=art_y)
    items = parse_list_items(res_items, min_y=get_list_min_y())
    print('VISIBLE_ITEMS=%d' % len(items))
    # tag1 分析列表时动态计算单篇报告高度并缓存,滚动(tag2)直接复用
    item_h = _item_height_from_items(items)
    if item_h and item_h > 0:
        calib = read_cache(CACHE_SCROLL)
        calib['item_height'] = item_h
        write_cache(CACHE_SCROLL, calib)
        print('ITEM_HEIGHT_CACHED_FROM_TAG1=%.1f' % item_h)
    else:
        print('ITEM_HEIGHT_CALC_FAIL_FROM_TAG1 (滚动时兜底估算)')
    for it in items[:5]:
        print('  - %s | %s | %s' % (it['title'][:30], it['date'], it['read_count']))
    result = {'status': 'ok', 'account': _account, 'tab': _cfg.get('tab', '文章'),
              'visible_items': items, 'screenshot': 'tag_all_articles.png'}
    write_json('search_result.json', result)
    total, added, pending, earliest, passed = upsert(
        items, account=_account, tab=_cfg.get('tab', '文章'), start=_start, end=_end)
    print('ARTICLES total=%d added=%d pending_url=%d earliest=%s passed_start=%s'
          % (total, added, pending, earliest, passed))
    print('SEARCH_DONE')
    # 首屏落库后继续完整状态机: detail(抓 URL) <-> scroll(滚动收集),
    # 返回最终结果 JSON(含 articles 全量)
    final = _run_detail_scroll()
    print('FLOW_ARTICLES_FINAL status=%s total=%d with_url=%d pending=%d'
          % (final.get('status'), final.get('articles_total'),
             final.get('articles_with_url'), final.get('articles_pending')))
    return _flow_json(final.get('status') == 'ok', phase='articles',
                      **{k: final.get(k) for k in (
                          'scroll_rounds', 'articles_total', 'articles_with_url',
                          'articles_pending')})


def _run_detail_scroll(max_rounds=40):
    """首屏落库后的完整状态机: detail(抓 pending URL) <-> scroll(滚动收集)。
    返回最终结果 dict(与 run_pipeline 收尾 JSON 同构)。
    covered=True(时间范围覆盖完成)后停止滚动。"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end
    arts = _arts()
    covered = _covered(arts)
    pending = _pending_ids(arts)
    dates = [a['date'] for a in arts['items'] if a.get('date')]
    print('=== ALL: total=%d pending=%d earliest=%s covered=%s ==='
          % (len(arts['items']), len(pending), min(dates) if dates else None, covered))
    if not pending:
        print('=== ALL: 无待抓文章,列表无符合条件数据,视为完成,结束 ===')
        arts = _arts()
        return {'status': 'ok', 'scroll_rounds': 0,
                'articles_total': len(arts['items']),
                'articles_with_url': sum(1 for a in arts['items'] if a.get('url')),
                'articles_pending': 0, 'articles': arts['items']}
    # ---- 滚动校准前置(每个任务一次): 校准会真实滚动列表(tries 格),置于正式滚动循环前,
    # 避免混入"一个一个滚"的视觉卡顿与校准+span 两次滚动叠加滚过头;
    # 无缓存才实测,实测后滚动回顶还原基线,保证后续每轮 span 从列表顶部量起;
    # px_per_click 已持久化到 WX_DIR,跨运行直接命中缓存不再校准。 ----
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    calib = read_cache(CACHE_SCROLL)
    if calib.get('px_per_click'):
        print('SCROLL_PX_PRELOOP_FROM_CACHE=%.1f' % calib['px_per_click'])
    else:
        px = get_scroll_px(hwnd, l, t, r, b)
        print('SCROLL_PX_PRELOOP_CALIBRATED=%.1f' % px)
        _scroll_to_top(hwnd, l, t, r, b)   # 校准滚了 tries 格,回顶还原基线(向上滚 10 格,顶部自然钳制)
        _wait_list_stable(hwnd, min_y=get_list_min_y())
    rounds = 0
    while rounds < max_rounds:
        # a) detail: 抓取当前所有 pending 文章的链接
        arts = _arts()
        pending = _pending_ids(arts)
        if pending:
            print('=== ALL: detail 抓取 %d 篇 pending ===' % len(pending))
            _step_detail()
        else:
            print('=== ALL: 无 pending 待抓文章 ===')
        # b) 判断是否还需要滚动
        arts = _arts()
        if covered:
            print('=== ALL: 覆盖完成,不再滚动,结束 ===')
            break
        # covered=False => 当前列表全在范围内,滚动看下一页
        res = _step_scroll()
        rounds += 1
        arts = _arts()
        covered = _covered(arts)
        print('=== ALL: scroll round=%d new=%d covered=%s no_new=%s limit=%s ==='
              % (rounds, res.get('new_count', 0), covered,
                 res.get('no_new'), res.get('limit_reached')))
        # 列表解析无符合条件的数据 => 没有报告可看了,直接视为完成
        if res.get('no_new'):
            print('=== ALL: scroll 列表解析无符合条件数据,视为完成,结束 ===')
            break
        if covered:
            print('=== ALL: scroll 覆盖完成,结束 ===')
            break
        # 无论 covered 是否变 True,循环回到 detail 抓取刚落库的新文章
    # ---- 收尾: 回顶补抓(有界,至多回顶一次+下滚一屏,绝不循环滚动) ----
    # 主循环一路向下滚,早期屏失败的 pending 已滚出视野(被 SKIP_NOT_ONSCREEN 跳过)。
    # 回顶让首屏文章重新可见,_step_detail 会做一次当前屏 OCR 后直接点坐标。
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    arts = _arts()
    pending_left = sum(1 for a in arts['items'] if not a.get('url'))
    if pending_left:
        print('=== ALL: 收尾回顶补抓 (pending=%d) ===' % pending_left)
        _scroll_to_top(hwnd, l, t, r, b)
        # 回顶后列表有滚动动画,等稳定再做 OCR 定位,否则首屏标题抓不到
        _wait_list_stable(hwnd, min_y=get_list_min_y())
        _step_detail()
        # 回顶只覆盖首屏;若还有 pending 在更下方,至多再下滚一屏抓一次
        arts = _arts()
        pending_left = sum(1 for a in arts['items'] if not a.get('url'))
        if pending_left:
            print('=== ALL: 收尾再滚一屏补抓 (pending=%d) ===' % pending_left)
            _step_scroll()
            _step_detail()
    # ---- 最终落库状态 ----
    arts = _arts()
    # URL 去重: OCR 拼写噪声可能把同一篇识别成两个条目(LONGieHome vs LUINGiEHoIme),
    # 但同一篇文章的复制链接 URL 必然相同 -> 以 url 为主键合并,保留先抓到的。
    seen_url = {}
    merged = []
    for a in arts['items']:
        u = a.get('url')
        if u and u in seen_url:
            print('DEDUP_URL %s "%s" == "%s" (保留先抓到的)'
                  % (u[:50], seen_url[u].get('title', '')[:24], a.get('title', '')[:24]))
            continue
        if u:
            seen_url[u] = a
        merged.append(a)
    arts['items'] = merged
    write_json(ARTICLES_FILE, arts)
    done = sum(1 for a in arts['items'] if a.get('url'))
    pending_left = sum(1 for a in arts['items'] if not a.get('url'))
    return {
        'status': 'ok' if pending_left == 0 else 'partial',
        'scroll_rounds': rounds,
        'articles_total': len(arts['items']),
        'articles_with_url': done,
        'articles_pending': pending_left,
        'articles': arts['items'],
    }


def _scroll_to_top(hwnd, l, t, r, b):
    """回滚到列表顶部: 向上滚动足够多格(3 个视口高度),等列表稳定。
    用于收尾扫描时让滚出视野的早期文章重新回到屏内。"""
    px = get_scroll_px(hwnd, l, t, r, b, refresh=False)
    viewport_h = b - t
    clicks = max(10, int(viewport_h * 3 / max(px, 1.0)))
    x = l + int((r - l) * 0.5)
    y = t + int((b - t) * 0.7)
    print('SCROLL_TO_TOP clicks=%d' % clicks)
    scroll_wheel(x, y, clicks, 'up')
    time.sleep(SLEEP_UI_MID)


def _step_search():
    """= 原 tag1: 搜索公众号 -> 进文章列表 -> 落库首屏"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    # 1) 点搜索框(模板优先,OCR 兜底)
    inp = click_template(hwnd, os.path.join(WX_DIR, 'input_field.png'),
                         region=get_region('searchbox', hwnd), label='INPUT_FIELD')
    if not inp:
        hit = click_ocr_text(hwnd, get_region('searchbox_ocr', hwnd), '搜索公众号',
                             label='SEARCHBOX_OCR')
        if not hit:
            hit = click_ocr_text(hwnd, get_region('searchbox_ocr', hwnd), '搜索',
                                 label='SEARCHBOX_OCR', prefer_exact=False,
                                 max_x=1000)
        if not hit:
            hit = click_ocr_text(hwnd, get_region('searchbox_ocr', hwnd), '搜一搜',
                                 label='BELOW_TITLE', offset_y=95)
        if not hit:
            click_at(l + (r - l) // 2, t + int((b - t) * 0.2))
            print('CLICKED_SEARCHBOX_FALLBACK')
    # 2) 粘贴 + 回车
    time.sleep(0.2)
    hotkey(VK_CTRL, VK_A)          # ctrl+a
    hotkey(VK_CTRL, VK_V)          # ctrl+v
    time.sleep(SLEEP_UI_SHORT)
    hotkey(VK_ENTER)               # enter
    print('PASTED_ACCOUNT_AND_ENTER')
    time.sleep(SLEEP_SEARCH_RESULT)
    # 3) OCR 定位目标公众号并点击
    if not _locate_account(hwnd, l, t):
        raise SystemExit(1)
    # 4) 点击"文章"标签(重试 RETRY_ARTICLE_TAB 次)
    art = None
    for attempt in range(RETRY_ARTICLE_TAB):
        art = click_template(hwnd, os.path.join(WX_DIR, 'article.png'),
                             region=get_region('article_tab', hwnd),
                             label='ARTICLE_TEMPLATE')
        if art:
            break
        time.sleep(1.5)
    if not art:
        print('ERROR - ARTICLE_TEMPLATE_NOT_FOUND')
        raise SystemExit(1)
    time.sleep(SLEEP_SEARCH_RESULT)
    # 5) 解析首屏列表并落库;同时学习列表布局(col_split/min_y)供后续滚动复用。
    #    锚点: 点击"文章"标签后鼠标正停在标签上,该 y(窗口内相对)即列表起始。
    art_y = int(art[1]) - t          # 绝对屏幕 y -> 窗口内相对 y
    shot, _ = screen_shot(hwnd, os.path.join(WX_DIR, 'tag_all_articles.png'))
    res_items = ocr_image(shot)
    _learn_layout(res_items, anchor_y=art_y)
    items = parse_list_items(res_items, min_y=get_list_min_y())
    print('VISIBLE_ITEMS=%d' % len(items))
    for it in items[:5]:
        print('  - %s | %s | %s' % (it['title'][:30], it['date'], it['read_count']))
    result = {'status': 'ok', 'account': _account, 'tab': _cfg.get('tab', '文章'),
              'visible_items': items, 'screenshot': 'tag_all_articles.png'}
    write_json('search_result.json', result)
    total, added, pending, earliest, passed = upsert(
        items, account=_account, tab=_cfg.get('tab', '文章'), start=_start, end=_end)
    print('ARTICLES total=%d added=%d pending_url=%d earliest=%s passed_start=%s'
          % (total, added, pending, earliest, passed))
    print('SEARCH_DONE')
    return _arts()


def _close_detail_tab():
    """关闭当前详情标签页(Ctrl+W),并等待 1s 标签页完全关闭后再继续。
    所有失败分支与成功收尾共用,保证状态一致。"""
    hotkey(VK_CTRL, VK_W)
    _t_close = time.time()
    time.sleep(SLEEP_TAB_CLOSE)
    print('TAB_CLOSED wait=%.1fs' % (time.time() - _t_close))


def _find_copy_url(hwnd, aid, round_no):
    """一轮尝试: 点击 more 弹出菜单,最多重试 3 次查找"复制链接"。
    成功返回 (cu, None); more 未找到返回 (None, 'MORE_BTN_NOT_FOUND');
    3 次均未找到返回 (None, 'COPY_URL_NOT_FOUND')。"""
    more = click_template(hwnd, _MORE_TPL, region=get_region('tabbar', hwnd),
                          label='MORE')
    if not more:
        print('ERROR - MORE_BTN_NOT_FOUND id=%s round=%d' % (aid, round_no))
        return None, 'MORE_BTN_NOT_FOUND'
    print('  (round%d)' % round_no)
    time.sleep(SLEEP_PAGE_OPEN)
    cu = None
    for attempt in range(RETRY_COPY_URL):
        cu = find_template(hwnd, _COPY_URL_TPL, region=get_region('menu', hwnd),
                           threshold=THRESHOLD_TEMPLATE)
        if cu:
            break
        time.sleep(SLEEP_PAGE_OPEN)
    if not cu:
        cu = find_template(hwnd, _COPY_URL_TPL,
                           threshold=THRESHOLD_COPY_URL_FALLBACK)
    if not cu:
        print('ERROR - COPY_URL_NOT_FOUND id=%s round=%d' % (aid, round_no))
        return None, 'COPY_URL_NOT_FOUND'
    return cu, None


def _norm_title(t):
    """标题归一化: 去掉空格/标点/大小写差异,用于 OCR 标题匹配"""
    return re.sub(r'[\s\u3000,，。.！!?？:：;；\'"“”‘’()（）\-—_]+', '',
                  (t or '')).lower()


def find_article_onscreen(title):
    """在当前列表区实时 OCR,按标题(归一化)定位文章当前屏幕坐标。
    滚动后列表坐标会变,落库坐标可能过期,因此点击前现场定位。
    OCR 存在拼写噪声(LONGieHome vs LUINGIeHoIme),故用 SequenceMatcher
    相似度匹配(>= TITLE_FUZZY_RATIO),精确匹配命中时优先。
    返回 (abs_x, abs_y) 或 None。"""
    global _hwnd, _lt, _tt
    hwnd, l, t = _hwnd, _lt, _tt
    res_items, _ = list_ocr(hwnd)
    vis = parse_list_items(res_items, min_y=get_list_min_y())
    target = _norm_title(title)
    if not target:
        return None
    best = None
    best_ratio = 0.0
    for it in vis:
        cand = _norm_title(it.get('title', ''))
        if not cand:
            continue
        if cand == target:   # 精确命中: 直接返回
            cx0 = it.get('cx0')
            if cx0 is None:
                cx0 = it.get('cx', 0)
            return l + int(cx0) + 10, t + int(it.get('cy', 0))
        ratio = difflib.SequenceMatcher(None, target, cand).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = it
    if best and best_ratio >= TITLE_FUZZY_RATIO:
        cx0 = best.get('cx0')
        if cx0 is None:
            cx0 = best.get('cx', 0)
        print('TITLE_FUZZY ratio=%.2f "%s"~"%s"' % (best_ratio, title[:18], best.get('title', '')[:18]))
        return l + int(cx0) + 10, t + int(best.get('cy', 0))
    return None


def _step_detail():
    """= 原 tag3: 遍历 pending 文章,抓链接回写。
    坐标直接取列表落库坐标(快路径): 本函数开始时做一次当前屏 OCR,
    刷新当前屏可见文章的坐标(滚动后落库坐标会过期),然后对可见的
    pending 直接用刷新后的坐标点击。不可见的 pending 跳过(留待后续
    滚动/收尾回顶),绝不用过期坐标硬点。
    每篇最多尝试两轮: 首次进详情页 -> 点更多找复制链接(重试3次);
    失败则正常关标签,重新点击该报告再试一轮;两轮均失败才跳到下一篇。"""
    global _hwnd, _lt, _tt, _rt, _bt
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    arts = _arts()
    by_id = {a['id']: a for a in arts['items']}
    ids = _pending_ids(arts)
    if not ids:
        print('DETAIL_NO_PENDING')
        return
    print('DETAIL_BATCH=%s' % ids)
    # 一次 OCR 刷新当前屏所有可见文章的坐标(滚动后落库坐标会过期)
    res_items, _ = list_ocr(hwnd)
    vis = parse_list_items(res_items, min_y=get_list_min_y())
    live_by_title = {}
    for it in vis:
        nt = _norm_title(it.get('title', ''))
        if not nt:
            continue
        cx0 = it.get('cx0')
        if cx0 is None:
            cx0 = it.get('cx', 0)
        live_by_title[nt] = (l + int(cx0) + 10, t + int(it.get('cy', 0)))
    for aid in ids:
        item = by_id.get(aid)
        if not item:
            print('ERROR - ID_NOT_FOUND %s' % aid)
            continue
        title = item.get('title', '')
        print('==== ID %s: %s' % (aid, title[:36]))
        t0 = time.time()
        target = _norm_title(title)
        # 快路径: 用当前屏刷新坐标(精确匹配优先,模糊兜底 OCR 拼写噪声)
        coord = live_by_title.get(target)
        if coord is None:
            best, best_ratio = None, 0.0
            for nt2, c2 in live_by_title.items():
                ratio = difflib.SequenceMatcher(None, target, nt2).ratio()
                if ratio > best_ratio:
                    best_ratio, best = ratio, c2
            if best and best_ratio >= TITLE_FUZZY_RATIO:
                coord = best
                print('TITLE_FUZZY ratio=%.2f "%s"~"%s"' % (best_ratio, title[:18], title[:18]))
        if coord is None:
            print('SKIP_NOT_ONSCREEN id=%s (当前屏不可见,留待后续轮次/回顶)' % aid)
            continue
        abs_x, abs_y = coord
        cu = None
        for rnd in range(RETRY_DETAIL_ROUNDS):
            # 重试轮(极少): 列表可能又变动,现场再定位一次
            if rnd > 0:
                live = find_article_onscreen(title)
                if live:
                    abs_x, abs_y = live
                    print('RELOCATED_LIVE @ (%d,%d)' % (abs_x, abs_y))
                else:
                    print('RELOCATE_MISS,沿用刷新坐标 (%d,%d)' % (abs_x, abs_y))
            click_at(abs_x, abs_y)
            print('CLICKED_BY_COORD (%d,%d) round=%d' % (abs_x, abs_y, rnd))
            time.sleep(SLEEP_DETAIL_LOAD)   # 等文章正文加载出来,再点"更多"按钮
            move_cursor_to_tabbar(l, t, r, b)   # 鼠标移到顶部标签栏,避免悬停内容区
            cu, _ = _find_copy_url(hwnd, aid, rnd)
            if cu:
                break
            _close_detail_tab()   # 本轮失败: 正常关标签,下一轮重新点击该报告
        if not cu:
            print('ERROR - COPY_URL_FAILED_2ROUNDS id=%s' % aid)
            continue
        click_at(cu[0], cu[1])
        print('CLICKED_COPY_URL @ (%d,%d) score=%.2f' % (cu[0], cu[1], cu[2]))
        time.sleep(0.2)
        url = get_clipboard().strip()
        print('URL=%s' % url[:80])
        if not url or 'http' not in url:
            print('ERROR - URL_NOT_IN_CLIPBOARD id=%s' % aid)
            _close_detail_tab()
            continue
        item['url'] = url
        out = {k: arts.get(k) for k in ('account', 'tab', 'start', 'end',
                                         'earliest_visible', 'passed_start')}
        out['items'] = list(by_id.values())
        write_json(ARTICLES_FILE, out)
        # 成功: 关标签后等 1s 完全关闭,再点下一篇
        _close_detail_tab()
        print('ID_%s_DONE (%.1fs): %s' % (aid, time.time() - t0, url[:60]))
    arts = _arts()
    done = sum(1 for a in arts['items'] if a.get('url'))
    print('DETAIL_ALL_DONE total=%d with_url=%d' % (len(arts['items']), done))


def _wait_list_stable(hwnd, min_y=None, max_tries=5, settle=1.5):
    """滚动后等待列表稳定: 连续两次 OCR 的可见标题集合一致才返回当前屏条目。
    微信滚动动画/自动加载期间坐标会移动,此时抓取会得到过期坐标(点错位置的根因)。
    最多 max_tries 次(每次 settle 秒),超时则用最后一次 OCR 结果兜底。
    每次 OCR 都会把当前屏截图存为 scroll_probe_N.png(仅诊断用,覆盖写)。"""
    if min_y is None:
        min_y = get_list_min_y()
    prev_titles = None
    prev_items = None
    for i in range(max_tries):
        shot_path = os.path.join(WX_DIR, 'scroll_probe_%d.png' % i)
        items, _ = list_ocr(hwnd, path=shot_path)
        vis_items = parse_list_items(items, min_y=min_y)
        titles = [it['title'] for it in vis_items if it['title']]
        if prev_titles is not None and titles and titles == prev_titles:
            print('LIST_STABLE try=%d visible=%d shot=%s' % (i, len(vis_items), shot_path))
            return vis_items
        prev_titles = titles
        prev_items = vis_items
        if i < max_tries - 1:
            time.sleep(settle)
    print('LIST_STABLE_GIVEUP (用最后一次 OCR 结果)')
    return prev_items or []


def _item_height_from_items(vis_items):
    """从已解析的列表条目(parse_list_items 输出)计算单篇高度(px):
    同列相邻 cy 差的中位数(瀑布流双列按列分组)。返回正数或 None。"""
    by_col = {}
    for it in vis_items:
        col = 'L' if it.get('cx0', 0) < get_col_split() else 'R'
        by_col.setdefault(col, []).append(it['cy'])
    diffs = []
    for col, cys in by_col.items():
        cys.sort()
        for i in range(len(cys) - 1):
            d = cys[i + 1] - cys[i]
            if d >= 30:   # 过滤粘连/重复行造成的过小间距
                diffs.append(d)
    if not diffs:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]   # 中位数


def _measure_item_height(hwnd, min_y=None):
    """动态测量单篇文章高度(px): 从当前列表 OCR 取相邻两条 cy 差的中位数。
    列表为瀑布流双列时,同列内相邻差才是行高,故按列分组后取同列差。
    返回正数 px;测量不到时返回 None(调用方用兜底估算)。"""
    if min_y is None:
        min_y = get_list_min_y()
    items, _ = list_ocr(hwnd)
    vis = parse_list_items(items, min_y=min_y)
    return _item_height_from_items(vis)


def _scroll_by_items(hwnd, l, t, r, b, n_items=SCROLL_ITEMS_PER_PAGE, target_px=None):
    """按"滚动 n_items 篇文章高度"或"直接指定目标像素"的距离滚动。
    target_px 缺省时 = n_items x 单篇高度(优先读缓存,无缓存动态测量一次并写回);
    换算滚轮格数 = 目标像素 / 每格像素(动态实测,缓存复用),至少 1 格。
    返回实际滚动的格数。"""
    calib = read_cache(CACHE_SCROLL)
    if target_px is None:
        item_h = calib.get('item_height')
        if not item_h or item_h <= 0:
            item_h = _measure_item_height(hwnd)
            if not item_h or item_h <= 0:
                item_h = SCROLL_PX_PER_CLICK   # 兜底: 1 格 ≈ 1 篇
                print('ITEM_HEIGHT_MEASURE_FAIL - 用估算 %.1f px' % item_h)
            else:
                calib['item_height'] = item_h
                write_cache(CACHE_SCROLL, calib)
                print('ITEM_HEIGHT_CACHED=%.1f' % item_h)
        else:
            print('ITEM_HEIGHT_FROM_CACHE=%.1f' % item_h)
        target_px = n_items * item_h
    px_per_click = get_scroll_px(hwnd, l, t, r, b)
    clicks = max(1, int(round(target_px / px_per_click)))
    scroll_abs_x = l + int((r - l) * 0.5)
    scroll_abs_y = t + int((b - t) * 0.7)
    print('SCROLL_BY_ITEMS n=%d item_h=%.1fpx px/click=%.1f target=%.1fpx clicks=%d'
          % (n_items, calib.get('item_height', 0) or 0, px_per_click, target_px, clicks))
    scroll_wheel(scroll_abs_x, scroll_abs_y, clicks, 'down')
    return clicks


def _step_scroll():
    """= 原 tag2: 向下滚动"当前屏报告的垂直跨距" -> 等 0.5s -> 与 tag1 完全相同的
    列表分析(整窗口截图 + OCR + parse_list_items) -> 去重落库。
    滚动距离 = 每次列表分析后动态计算: 当前屏最上面报告 cy 与最下面报告 cy 的
    差值(即一屏报告的实际内容高度),避免固定 4 篇高与实际屏距不符导致漏页/重复。
    先分析后滚动(用分析结果定滚动距离),滚动后再分析落库。"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end
    hwnd, l, t, r, b = _hwnd, _lt, _tt, _rt, _bt
    state = read_json('scroll_state.json', {})
    round_no = state.get('rounds', 0) + 1
    # 去重基准: 已落库标题(归一化),防止把 tag1 已入库文章当新条目重复处理
    arts0 = load_articles()
    seen_titles = {_norm_title(a.get('title', '')) for a in arts0['items']
                   if a.get('title')}
    # 1) 先分析当前屏: 计算滚动距离(最下 - 最上报告的 cy 差,即一屏内容跨距)
    shot0, _ = screen_shot(hwnd, os.path.join(WX_DIR, 'tag_all_pre_scroll.png'))
    items0 = parse_list_items(ocr_image(shot0), min_y=get_list_min_y())
    if items0:
        span_px = float(items0[-1]['cy']) - float(items0[0]['cy'])
        print('SCROLL_SPAN_CALC first=%d last=%d span=%.1fpx'
              % (items0[0]['cy'], items0[-1]['cy'], span_px))
    else:
        span_px = None
        print('SCROLL_SPAN_CALC_FAIL - 用固定 4 篇高兜底')
    # 1b) 边界检测: 当前屏底部已出现日期范围外的文章(早于 start)说明已到列表
    # 末尾,再滚动只会看到更早(更在范围外)的数据,直接视为完成,不滚动。
    # 注意列表按日期倒序(新的在上),一旦屏内可见最早日期 < start 即达边界。
    if _start and items0:
        d0 = [it['date'] for it in items0 if it.get('date')]
        if d0 and min(d0) < _start:
            print('SCROLL_BOUNDARY_REACHED - 当前屏已见范围外数据,不再滚动')
            arts = load_articles()
            arts['passed_start'] = True   # 让 covered 判定生效,主循环直接结束
            save_articles(arts)
            write_json('scroll_state.json', {
                'seen_titles': list(seen_titles), 'rounds': round_no})
            result = {'status': 'ok', 'round': round_no, 'new_count': 0,
                      'earliest_visible': min(d0), 'no_new': True,
                      'limit_reached': False, 'boundary': True}
            write_json('matched_items.json', result)
            return result
    # 2) 按该跨距滚动(滚到底触发微信自动加载下一页)。
    #    无需额外等待: 主循环先 detail(tag3)抓完才进入本函数,列表已稳定。
    _scroll_by_items(hwnd, l, t, r, b,
                     SCROLL_ITEMS_PER_PAGE,
                     target_px=span_px if span_px and span_px > 0 else None)
    # 3) 与 tag1 完全相同的列表分析: 整窗口截图 -> OCR -> parse_list_items
    shot, _ = screen_shot(hwnd, os.path.join(WX_DIR, 'tag_all_scroll.png'))
    res_items = ocr_image(shot)
    items = parse_list_items(res_items, min_y=get_list_min_y())
    # 4) 去重 + 落库: 只保留符合条件(非标签栏、日期在范围内)且未落库的条目
    new_items = [it for it in items
                 if it['title'] and not is_tab_bar(it['title'])
                 and it.get('date') and in_range(it['date'], _start, _end)
                 and _norm_title(it['title']) not in seen_titles]
    for it in new_items:
        seen_titles.add(_norm_title(it['title']))
        print('SCROLL_NEW: %s | %s' % (it['title'][:30], it['date']))
    added = 0
    if new_items:
        total, added, pending, _, _ = upsert(
            new_items, account=_account, tab=_cfg.get('tab', '文章'), start=_start, end=_end)
        print('SCROLL_UPSERT total=%d added=%d pending_url=%d' % (total, added, pending))
    dates = [it['date'] for it in items if it['date']]
    earliest = min(dates) if dates else None
    # 列表解析无符合条件的数据(全为标签栏/无日期/不在范围内/已落库)
    # -> 视为完成,不再继续滚动与抓取
    no_new = not new_items
    if no_new:
        print('SCROLL_NO_MATCHING - 列表无符合条件数据,视为完成')
    arts = load_articles()
    pending = sum(1 for a in arts['items'] if not a.get('url'))
    write_json('scroll_state.json', {
        'seen_titles': list(seen_titles), 'rounds': round_no})
    result = {'status': 'ok', 'round': round_no, 'new_count': len(new_items),
              'earliest_visible': earliest, 'no_new': no_new,
              'limit_reached': pending >= _cfg.get('limit', 50)}
    write_json('matched_items.json', result)
    print('SCROLL_DONE round=%d new=%d added=%d earliest=%s no_new=%s'
          % (round_no, len(new_items), added, earliest, no_new))
    return result


def run_pipeline():
    """一体化状态机主入口(由 tag_all.tag 的 py 块调用)。
    search -> detail <-> scroll,按落库状态自动决策,结束后打印结果 JSON。"""
    global _hwnd, _lt, _tt, _rt, _bt, _cfg, _account, _start, _end, _MORE_TPL, _COPY_URL_TPL
    wd = os.environ.get('WX_WORKDIR', '')
    if not wd or not os.path.isdir(wd):
        print('ERROR - WX_WORKDIR_NOT_SET')
        raise SystemExit(1)
    sys.path.insert(0, wd)
    # 注意: 本文件被拷贝进临时目录后由 tag 导入,__file__ 指向临时目录,
    # WX_DIR 因此即临时目录(模板/落库文件都在其中),无需再切换。
    hwnd = find_wx_window()
    if not hwnd:
        print('ERROR - NO_WECHATAPPEX_WINDOW')
        raise SystemExit(1)
    activate(hwnd)
    _hwnd = hwnd
    _lt, _tt, _rt, _bt = win_rect(hwnd)
    _cfg = read_json('agent_config.json', {}) or {}
    _account = _cfg.get('account', '')
    _start = _cfg.get('start')
    _end = _cfg.get('end')
    _MORE_TPL = os.path.join(WX_DIR, 'more.png')
    _COPY_URL_TPL = os.path.join(WX_DIR, 'copy_url.png')

    # ---- 1) search: 搜索公众号 -> 文章列表 -> 落库首屏 ----
    arts = _step_search()
    covered = _covered(arts)
    pending = _pending_ids(arts)
    dates = [a['date'] for a in arts['items'] if a.get('date')]
    print('=== ALL/tag1: total=%d pending=%d earliest=%s covered=%s ==='
          % (len(arts['items']), len(pending), min(dates) if dates else None, covered))
    if not pending:
        print('=== ALL: tag1 无待抓文章,无需滚动与抓取,结束 ===')
        arts = _arts()
        print(json.dumps({'status': 'ok', 'phase': 'all',
                          'message': 'tag1 无待抓文章',
                          'articles_total': len(arts['items']),
                          'articles': arts['items']}, ensure_ascii=False, indent=2))
        return

    # ---- 2) 主循环: detail(抓 pending) <-> scroll(滚动) ----
    rounds = 0
    max_rounds = 40
    while rounds < max_rounds:
        # a) detail: 抓取当前所有 pending 文章的链接
        arts = _arts()
        pending = _pending_ids(arts)
        if pending:
            print('=== ALL: detail 抓取 %d 篇 pending ===' % len(pending))
            _step_detail()
        else:
            print('=== ALL: 无 pending 待抓文章 ===')
        # b) 判断是否还需要滚动
        arts = _arts()
        if covered:
            print('=== ALL: 覆盖完成,不再滚动,结束 ===')
            break
        # covered=False => 当前列表全在范围内,滚动看下一页
        res = _step_scroll()
        rounds += 1
        arts = _arts()
        covered = _covered(arts)
        print('=== ALL: scroll round=%d new=%d covered=%s no_new=%s limit=%s ==='
              % (rounds, res.get('new_count', 0), covered,
                 res.get('no_new'), res.get('limit_reached')))
        # 列表解析无符合条件的数据 => 没有报告可看了,直接视为完成
        if res.get('no_new'):
            print('=== ALL: scroll 列表解析无符合条件数据,视为完成,结束 ===')
            break
        if covered:
            print('=== ALL: scroll 覆盖完成,结束 ===')
            break
        # 无论 covered 是否变 True,循环回到 detail 抓取刚落库的新文章
        # 若 covered=True,下一次循环 detail 后直接 break

    # ---- 3) 收尾: 最终落库状态 ----
    arts = _arts()
    done = sum(1 for a in arts['items'] if a.get('url'))
    pending_left = sum(1 for a in arts['items'] if not a.get('url'))
    print(json.dumps({
        'status': 'ok' if pending_left == 0 else 'partial',
        'phase': 'all',
        'scroll_rounds': rounds,
        'articles_total': len(arts['items']),
        'articles_with_url': done,
        'articles_pending': pending_left,
        'articles': arts['items'],
    }, ensure_ascii=False, indent=2))


# ================================================================ 主入口
def close_phase():
    """收尾: 保存 articles.json 到本目录 -> 关闭搜一搜窗口 -> 移除临时目录"""
    print('==== close 开始: 保存结果 + 关闭搜一搜窗口 + 移除临时工作目录 ====')
    wd = get_work_dir_or_none()
    if wd and os.path.isdir(wd):
        src = os.path.join(wd, ARTICLES_FILE)
        if os.path.exists(src):
            dst = os.path.join(WX_DIR, ARTICLES_FILE)
            shutil.copy2(src, dst)
            print('ARTICLES_SAVED %s' % dst)
    hwnd = find_wx_window()
    if hwnd:
        close_window(hwnd)
        print('SOSS_WINDOW_CLOSED hwnd=%s' % hwnd)
    else:
        print('SOSS_WINDOW_ALREADY_GONE')
    cleanup_work_dir()


def main():
    enable_dpi_awareness()   # 必须在任何窗口/截图操作前
    parser = argparse.ArgumentParser(
        description='微信搜一搜公众号文章自动抓取 - 一体化单命令')
    parser.add_argument('--account', default='', help='公众号名称')
    parser.add_argument('--tab', default='文章', help='内容标签: 文章/贴图/视频号')
    parser.add_argument('--start', default='', help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', default='', help='结束日期 YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=50, help='滚动收集上限')
    parser.add_argument('--phase', default='',
                        choices=['', 'close', 'status', 'env'],
                        help='可选: close=仅收尾; status=查看结果; env=仅环境自检; 缺省=完整流程')
    args = parser.parse_args()

    if args.phase == 'env':
        ok, problems = check_environment()
        print(json.dumps({'status': 'ok' if ok else 'failed',
                          'problems': problems}, ensure_ascii=False, indent=2))
        return 0 if ok else 2

    if args.phase == 'status':
        arts = read_json(ARTICLES_FILE, {'items': []}) or {'items': []}
        print(json.dumps({
            'articles_total': len(arts['items']),
            'articles_with_url': sum(1 for a in arts['items'] if a.get('url')),
            'articles_pending': sum(1 for a in arts['items'] if not a.get('url')),
            'articles': arts['items'],
        }, ensure_ascii=False, indent=2))
        return 0

    # 1) 环境自检: 依赖/素材/TagUI/DPI 任一缺失,提前中止并给出修复指引
    ok, problems = check_environment()
    if not ok:
        print(json.dumps({'status': 'failed', 'reason': 'env_check_failed',
                          'problems': problems}, ensure_ascii=False, indent=2))
        return 2

    # 2) 检测微信主窗口是否打开
    if not find_weixin_main():
        print(json.dumps({
            'status': 'failed',
            'reason': 'no_weixin_main',
            'hint': '请先打开微信并登录,然后重新执行',
        }, ensure_ascii=False, indent=2))
        return 2

    if args.phase == 'close':
        close_phase()
        return 0

    # 2) 完整流程: 需要 account
    if not args.account:
        print(json.dumps({'status': 'failed', 'reason': 'account_required'},
                         ensure_ascii=False))
        return 2

    # ---- 注册中断处理器: Ctrl+C / 关窗 / Ctrl+Break 时停止整个自动化 ----
    install_ctrl_handler()

    # ---- 建独立临时工作目录(拷贝 .tag/.py/.png) ----
    setup_work_dir()
    cfg = write_config(args.account, args.tab, args.start or None,
                       args.end or None, args.limit)
    set_clipboard(cfg['account'])          # 带重试,微信可能持有剪贴板
    print('已复制公众号名称到剪贴板: %s' % cfg['account'])

    # ---- 前置侦查: 确认主窗口 home 图标可定位(原生 click 前的健康检查) ----
    main_hwnd = find_weixin_main()
    ok, found = preflight_main(main_hwnd)
    if not ok:
        # 侧边栏无 home 图标(部分微信版本): 回退搜索框 + "搜索网络结果"方案
        print('HOME_ICON_PATH_FAILED - 回退搜索框 + 搜索网络结果方案')
        soss = open_soss_from_main(main_hwnd, cfg['account'])
        if not soss:
            print(json.dumps({'status': 'failed',
                              'reason': 'soss_open_failed',
                              'hint': '点击微信侧边栏图标/搜索框后未出现搜一搜窗口'},
                             ensure_ascii=False))
            return 2
        print('SOSS_OPENED hwnd=%s (fallback)' % soss)
        # fallback 方案已直接打开 SOSS: 后续 py 块从已开窗口继续
        rc, stdout = run_tag('tag_all.tag', timeout=900)
        print(stdout)
        print('TagUI tag_all 退出码: %d' % rc)
        if rc == 124:
            print(json.dumps({'status': 'failed', 'phase': 'all',
                              'reason': 'tag_all_timeout'},
                             ensure_ascii=False, indent=2))
            close_phase()
            return 2
        close_phase()
        return 0 if rc == 0 else 2

    # ---- 单次 TagUI 进程执行 tag_all.tag: 内部 flow_begin 侦查 ->
    #     原生 click home.png -> flow_wait_soss -> click input_field.png ->
    #     flow_fill_search -> click article.png -> flow_articles ----
    print('==== phase=all account=%s tab=%s range=%s~%s ===='
          % (cfg['account'], cfg['tab'], cfg['start'], cfg['end']))
    rc, stdout = run_tag('tag_all.tag', timeout=900)
    print(stdout)
    print('TagUI tag_all 退出码: %d' % rc)
    if rc == 124:
        print(json.dumps({'status': 'failed', 'phase': 'all',
                          'reason': 'tag_all_timeout'}, ensure_ascii=False, indent=2))
        close_phase()
        return 2

    # ---- 自动收尾: 保存结果 + 关窗 + 清理 ----
    close_phase()
    return 0 if rc == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
