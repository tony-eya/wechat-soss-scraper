<div align="center">

# WeChat SOSS Scraper

### 微信「搜一搜」公众号文章自动抓取

**完全开源 | 免费使用 | 跨机器自适应 | 零硬编码坐标 | 自动去重续跑**

[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![TagUI](https://img.shields.io/badge/TagUI-RPA%20Engine-orange?style=for-the-badge)](https://github.com/aisingapore/TagUI)
[![OpenCV](https://img.shields.io/badge/OpenCV-Template%20Match-green?style=for-the-badge)](https://opencv.org/)
[![OCR](https://img.shields.io/badge/OCR-RapidOCR-red?style=for-the-badge)](https://github.com/RapidAI/RapidOCR)

> 基于 [TagUI](https://github.com/aisingapore/TagUI) + Python 实现微信桌面版「搜一搜」公众号文章的全自动抓取：搜索公众号 → 进入文章列表 → 滚动翻页 → 逐篇点开详情 → 复制链接 → 落库 `articles.json`。代码完全公开，可自由修改与自部署。

</div>

---

## 功能特性

- **一键全流程** — 单条命令完成搜索、滚动、详情、取链、落库；中断后再次运行**自动去重续跑**，只补抓缺链接的文章
- **跨机器 / 跨版本自适应** — **零硬编码坐标**：DPI、窗口尺寸、滚轮行距、列表布局全部由程序运行时**动态实测与自校准**，整个目录可直接拷贝到新电脑使用
- **UI 智能定位** — 搜索框 / "文章"标签等关键控件用 **PNG 模板匹配 + 侦查缓存** 定位：首次运行自动侦查并缓存坐标（统一存 `cache.json`），后续直接复用，**免去每次全屏扫描**；缓存绑定窗口位置，窗口移动自动重新侦查
- **OCR 按窗口比例自适应** — 滚动翻页、列表解析区域按窗口宽高比例生成，窗口大小随意
- **滚动自校准** — 滚轮 1 格滚动像素数首屏动态实测并缓存（`cache.json` 的 scroll 分区），换电脑 / 换鼠标无需改代码
- **双列瀑布流容错** — 列表布局自动学习分列（`cache.json` 的 layout 分区）、行高实测、标题续行过滤，防止滚动后点错文章
- **环境自检** — `--phase env` 一键检查依赖、模板素材、TagUI 启动器

---

## 效果演示

[![点击播放演示视频](https://i0.hdslb.com/bfs/archive/f962fee44cef9c703f4bf945688ba7cee32ae2a5.jpg)](https://www.bilibili.com/video/BV1vWuA6dEFG?t=5.2)

> 点击上图跳转 B 站观看演示视频（GitHub 不支持内嵌播放器，故用封面图 + 链接形式展示）

---

## 环境要求

| 组件 | 说明 |
|---|---|
| Windows | Win10 / Win11（实测），**显示缩放必须 100%**（显示设置 → 缩放与布局 → 100%） |
| Python | 3.9+（`pip install -r requirements.txt`） |
| Node.js | TagUI 运行依赖 |
| JDK | 17+ |
| 微信 | 桌面版（**版本 4.1.12.26**），已登录，**保持窗口可见** |

依赖清单：`numpy`、`pillow`、`opencv-python`、`rapidocr_onnxruntime`（OCR 引擎）、`pyperclip`。

---

## 快速开始

> ### ⚠️ 使用前必读（两条硬性前提）
>
> **① 必须替换 PNG 素材库**：仓库自带的 `*.png` 是作者本机微信界面的截图，**只保证在作者的微信版本 / 皮肤 / 窗口布局下工作**。你的微信可能因版本、深浅色主题、自定义皮肤、图标改版而**无法匹配**（`--phase env` 会报缺素材 / 模板匹配失败）。请按下方「素材模板说明」一节，用你自己的微信截图**逐一替换** `tagui/flows/wx/article/` 下的 6 个 png 后再使用。
>
> **② 系统窗口缩放必须是 100%**：Windows "显示设置 → 缩放与布局" 必须为 **100%**。125% / 150% / 175% 缩放会使截图与点击坐标不一致，模板匹配和 OCR 解析**全面失效**。若主屏分辨率高必须用缩放，请把微信窗口拖到一台独立设置 100% 缩放的副屏再执行。更换缩放后删除 `cache.json` 重新校准。

**第一步：安装依赖**

```bash
# 1. 安装 Python 3.9+ 与 Node.js
# 2. 安装 JDK 17+（TagUI 图像识别依赖 Java）
#    官方搜索 "JDK 17 download"（Oracle / Temurin 均可），配置 JAVA_HOME 并加入 PATH
#    验证: java -version 显示 17 及以上
# 3. 安装 Microsoft Visual C++ 2012 Redistributable(x86 & x64)
#    官方搜索 "Visual C++ Redistributable for Visual Studio 2012" 下载
#    验证: .\tagui\src\unx\grep.exe --version 不再报 dll 缺失
# 4. 安装 Python 依赖
cd tagui/flows/wx/article
pip install -r requirements.txt
```

**第二步：配置 PATH**

将仓库内的 `tagui\src` 目录添加到系统 PATH，使 `tagui` 命令全局可用：

```powershell
# PowerShell 临时方式（仅当前会话生效）
$env:Path = "E:\SoftWare\wechat-soss-scraper\tagui\src;" + $env:Path
tagui --version   # 验证
```

> GUI 方式：系统属性 → 环境变量 → 系统变量 `Path` → 新建 → 添加 `tagui\src` 绝对路径。

**第三步：开始抓取**

```bash
cd tagui/flows/wx/article

# 环境自检（首次运行建议先跑）
python wx_article.py --phase env

# 抓取某个公众号的文章（按发布日期过滤）
python wx_article.py --account "隆基绿能" --tab 文章 --start 2026-07-30 --end 2026-08-01

# 不限制日期范围（抓取全部可见历史文章）
python wx_article.py --account "光伏行业观察"

# 查看已抓取结果
python wx_article.py --phase status

# 仅收尾：保存结果 + 关闭搜一搜窗口 + 清理临时目录
python wx_article.py --phase close
```

**参数说明：**

| 参数 | 说明 | 默认 |
|---|---|---|
| `--account` | 公众号名称（必填，完整流程） | 空 |
| `--start` / `--end` | 日期范围 `YYYY-MM-DD`，超出范围的文章自动跳过 | 空 |
| `--tab` | 内容标签：`文章` / `贴图` / `视频号` | `文章` |
| `--limit` | 滚动收集上限（篇） | `50` |
| `--phase` | `close` 收尾 / `status` 查看结果 / `env` 环境自检 | 完整流程 |

> 流程运行期间请勿移动鼠标 / 切换窗口 / 锁屏，自动化需要控制焦点。

---

## 项目结构

```
wechat-soss-scraper/
├── tagui/                    # TagUI 运行时（官方引擎，包含 src）
│   ├── src/                  # TagUI 运行时（tagui.cmd / php / node / sikulix）
│   └── flows/
│       └── wx/               # ★ 微信抓取模块（本项目全部业务代码）
│           └── article/      # ★ 公众号「文章」类别（按类别分子目录，未来可扩展 sticker/ 贴图、video/ 视频号 等）
│               ├── wx_article.py # 一体化状态机（文章类别脚本，全部逻辑）
│               ├── tag_all.tag   # TagUI 流程入口
│               ├── requirements.txt
│               ├── home.png      # 侧边栏「搜一搜」图标模板（需自行截图替换）
│               ├── wx_search.png # 主窗口顶部搜索框模板（需自行截图替换，回退方案用）
│               ├── input_field.png  # 搜一搜窗口搜索框模板（需自行截图替换）
│               ├── article.png   # 「文章」标签模板（需自行截图替换）
│               ├── more.png      # 详情页「…」按钮模板（需自行截图替换）
│               ├── copy_url.png  # 「复制链接」菜单项模板（需自行截图替换）
│               ├── articles.json # 抓取结果（自动生成，已 gitignore）
│               └── cache.json    # 统一运行时缓存：滚轮校准/布局学习/控件坐标（自动生成，已 gitignore）
└── README.md
```

---

## 素材模板说明（PNG）

> **为什么必须自己截图替换**：所有 `.png` 都是作者本机微信界面控件的**局部截图**（20~90 像素），仅用于 OpenCV 模板匹配定位。微信版本更新、深浅色主题、自定义皮肤、DPI 缩放都会改变控件外观，**作者机器的截图在你的微信上几乎必然匹配失败**。所以拿到仓库后第一步就是用**你自己的微信、100% 缩放**下重新截图替换（用系统截图工具 `Win+Shift+S` 截取对应控件即可，无需精确尺寸，会自动缩放匹配）。
>
> 版权归原应用（腾讯微信）所有，仅用于定位，请勿商用。

| 文件名 | 控件 | 用途 | 截图要求 |
|---|---|---|---|
| `home.png` | 微信主窗口左侧侧边栏的「搜一搜」图标，没有则忽略 | 进入搜一搜入口 | 只截图标本身（放大镜图形），不含文字；匹配失败时程序自动回退「顶部搜索框 → 搜索网络结果」方案 |
| `wx_search.png` | 微信主窗口**顶部**的搜索输入框 | 回退方案中点击顶部搜索框 | 截搜索框左端（含"搜索"占位文字区域即可）；若 `home.png` 匹配成功则用不到 |
| `input_field.png` | 搜一搜窗口搜索框下面的公众号 | 定位后自动粘贴公众号名称并回车 | 截标签文字"公众号" |
| `article.png` | 某个公众号详细页「文章」标签，说明：标签栏是这个样子 【全部 贴图 文章 视频号】 | 切换到文章列表页 | 截标签文字"文章" |
| `more.png` | 文章详情页右上角的「…」更多按钮 | 点开后出现复制链接菜单 | 只截"…"三个点按钮本体，背景尽量纯色 |
| `copy_url.png` | 更多菜单弹层中的「复制链接」菜单项 | 复制当前文章 URL | 截菜单项文字"复制链接"一行（含左侧图标可选）；注意是弹出的**菜单**，不是页面内元素 |

> **替换步骤**：截好图后，把新 png 覆盖到 `tagui/flows/wx/article/` 下同名文件 → 删除 `cache.json`（没有则忽略，否则仍用旧坐标）→ 运行 `python wx_article.py --phase env` 验证 `templates=6` 且无报错 → 开始抓取。如某步仍匹配失败，按报错提示重截对应控件。微信改版导致某步失效时同理，重新截取覆盖即可。

---

## 工作原理

### 流程总览

```
搜索公众号 → 进文章列表(首屏落库) → 逐篇点开详情取链接
   ↕ 滚动下一页 → 新文章落库 → 循环
   └─ 直到: 时间范围覆盖完成 且 所有文章已取到链接
```

### 状态机（`run_pipeline`）

- `covered=True`：列表已出现早于 `start` 的文章 → 时间覆盖完成 → 不再滚动。
- 未覆盖 → 滚动一屏 → 新文章落库 → 回到详情取链，循环直至到底或超上限。
- 中断后重跑：按标题去重，只补抓缺链接的文章（`pending_url`）。

### 关键自适应机制

| 机制 | 实现 |
|---|---|
| UI 定位 | OpenCV 模板匹配（`click_template` / `find_template`），失败按窗口比例回退 |
| 侦查缓存 | `get_template_coord`：搜索框 / "文章"标签首次侦查写缓存，窗口未动则直接复用坐标 + **SendInput 真实点击**（微信 UI 只响应真实输入），免去 TagUI 原生 SikuliX 全屏扫描（0.5-2s） |
| OCR 区域 | `get_region(kind, hwnd)` 按窗口宽高比例生成，替代旧版 1920 宽写死的区域常量 |
| 滚轮校准 | `_calibrate_scroll_px`：滚动前后 OCR 锚定同一标题，取位移中位数 → 缓存 `cache.json` 的 scroll 分区 |
| 布局学习 | `_learn_layout`：首屏 OCR 的 x0 分布最大间隙 → `col_split`；最顶标题 y → `list_top`，缓存 `cache.json` 的 layout 分区 |
| 行高测量 | `_measure_item_height`：同列相邻条目 cy 差中位数（瀑布流双列需分列） |
| 防点错 | 滚动前后收集"标题续行"文本并过滤；列表稳定探测（连续两次 OCR 一致才点击） |

### 为什么这样设计（踩过的坑）

- **滚动后点错位置**：滚动动画未结束就抓坐标 → 点击落在旧位置（点到别的文章）。解决：滚动后等列表稳定 + 续行过滤。
- **双列瀑布流错配**：左右列交错会把右列标题吞掉、元信息错配。解决：先按 x 分列，每列独立配对再合并。
- **换机器全部失灵**：写死的 `SCROLL_PX_PER_CLICK`、`POS_MAIN_SEARCHBOX`、`REGION_*` 区域。解决：全部改为动态实测 + 模板匹配 + 比例区域。
- **全屏扫描太慢**：TagUI 原生 `click xx.png` 每次 SikuliX 全屏扫描 0.5-2s。解决：搜索框 / "文章"标签改用侦查缓存 + SendInput 真实点击。

---

## 输出格式

`articles.json`：

```json
{
  "items": [
    {
      "id": "md5(title)",
      "title": "文章标题",
      "date": "2025-03-12",
      "read_count": "10万+",
      "url": "https://mp.weixin.qq.com/s/xxxx",
      "account": "公众号名",
      "tab": "文章",
      "scraped_at": "2026-08-02T10:00:00"
    }
  ],
  "passed_start": true,
  "earliest": "2024-06-01"
}
```

---

## 常见问题

<details>
<summary><b>报缺依赖</b></summary>

`cd tagui/flows/wx/article && pip install -r requirements.txt`
</details>

<details>
<summary><b>报缺模板素材</b></summary>

检查 `tagui/flows/wx/article/` 下 6 个 png 是否齐全，缺失时重新截图。
</details>

<details>
<summary><b>报 MSVCR110.dll 缺失 / not found</b></summary>

TagUI 自带的 `src\unx\*`、`src\php\*`、`phantomjs\phantomjs.exe` 为原生 exe，依赖 `MSVCR110.dll`。缺失时运行报 `MSVCR110.dll not found`。该 dll 位于 Windows 系统目录（如 `C:\Windows\System32\MSVCR110.dll`），确保系统已安装 VC++ 2012 运行库。
</details>

<details>
<summary><b>找不到 tagui.cmd</b></summary>

确认 `flows/wx/article/` 位于 `tagui/` 下（启动器自动向上三级定位 TagUI 根目录，勿移动目录层级）。
</details>

<details>
<summary><b>某步模板匹配失败（微信改版）</b></summary>

重新截取对应控件图覆盖原 png。
</details>

<details>
<summary><b>点击位置偏移</b></summary>

运行 `--phase env` 确认 DPI=True；删除 `cache.json` 让其重新校准。
</details>

<details>
<summary><b>抓取中断了怎么办</b></summary>

直接重新运行同一条命令，自动去重续跑。
</details>

---

## 开源协议

本项目采用 **MIT** 协议开源，所有功能代码完整公开，私有化使用完全免费。

### 免责声明

- 本软件按"原样"提供，不提供任何形式的担保
- 本项目仅供学习和研究目的，请遵守微信平台用户协议与相关法律法规，勿将抓取内容用于商业用途或高频抓取
- 使用者对自己的操作承担全部责任

---

## 参与贡献

非常欢迎：

- **提交 Issue** — 报告 Bug、提出功能建议
- **Fork 项目** — 自由修改和定制
- **Star 支持** — 给项目点 Star，让更多人看到

---

## 云端版 · Client Intel

本地版适合自己掌控一切；想省事的话，同一引擎已经在 **[Client Intel](https://intelcrm.cn/)** 云端跑起来了——**直接订阅，开箱即用**，无需任何环境配置：智能 Agent 调度多源数据爬虫（含微信公众号文章），自动过滤垃圾与噪声，每天定时把 HTML 情报简报发到你的邮箱。

| | 本地版（本仓库） | 云端版（Client Intel） |
|---|---|---|
| 部署 | 自己装 Python / TagUI 环境 | 免部署，浏览器打开即用 |
| 微信抓取 | 同源引擎（本工具） | 同源引擎（本工具） |
| 数据 | `articles.json` 落本地 | 多源聚合 + 每日情报简报 |
| 覆盖 | 单号单次抓取 | 8,800+ 企业目标，动态解析准确率 99.8% |
| 场景 | 个人 / 学习 / 深度定制 | 企业新闻监测 / 竞品分析 / 市场追踪 |
| 费用 | 免费（开源） | 直接订阅 · 7 天免费试用 |

[🚀 前往 Client Intel](https://intelcrm.cn/) · [平台功能介绍](https://intelcrm.cn/)

---

## 联系方式

<table>
  <tr>
    <td align="center">
      <img src="https://intelcrm.cn/minio/intelligence/6e0ae534dcc1258688780273246c060e.jpg" width="200"><br>
      <b>个人微信</b><br>
      <em>技术交流 · 问题反馈</em>
    </td>
    <td align="center">
      <img src="https://intelcrm.cn/minio/intelligence/pay.jpg" width="200"><br>
      <b>赞赏码</b><br>
      <em>开源不易，感谢支持</em>
    </td>
  </tr>
</table>

---

<div align="center">

**如果觉得项目有用，请给个 Star 支持一下！**

Made with ❤️

</div>
