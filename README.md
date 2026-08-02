<div align="center">

# WeChat SOSS Scraper

### 微信「搜一搜」公众号文章自动抓取

**完全开源 | 免费使用 | 跨机器自适应 | 零硬编码坐标 | 自动去重续跑**

[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![TagUI](https://img.shields.io/badge/TagUI-RPA%20Engine-orange?style=for-the-badge)](https://github.com/aisingapore/TagUI)
[![OpenCV](https://img.shields.io/badge/OpenCV-Template%20Match-green?style=for-the-badge)](https://opencv.org/)
[![OCR](https://img.shields.io/badge/OCR-RapidOCR-red?style=for-the-badge)](https://github.com/RapidAI/RapidOCR)

> **100% 开源，100% 免费。** 基于 [TagUI](https://github.com/aisingapore/TagUI) + Python 实现微信桌面版「搜一搜」公众号文章的全自动抓取：搜索公众号 → 进入文章列表 → 滚动翻页 → 逐篇点开详情 → 复制链接 → 落库 `articles.json`。

</div>

---

## 功能特性

- **一键全流程** — 单条命令完成搜索、滚动、详情、取链、落库；中断后再次运行**自动去重续跑**，只补抓缺链接的文章
- **跨机器 / 跨版本自适应** — **零硬编码坐标**：DPI、窗口尺寸、滚轮行距、列表布局全部由程序运行时**动态实测与自校准**，整个目录可直接拷贝到新电脑使用
- **UI 智能定位** — 搜索框 / "文章"标签等关键控件用 **PNG 模板匹配 + 侦查缓存** 定位：首次运行自动侦查并缓存坐标（`input_field_cache.json` / `article_cache.json`），后续直接复用，**免去每次全屏扫描**；缓存绑定窗口位置，窗口移动自动重新侦查
- **OCR 按窗口比例自适应** — 滚动翻页、列表解析区域按窗口宽高比例生成，窗口大小随意
- **滚动自校准** — 滚轮 1 格滚动像素数首屏动态实测并缓存（`scroll_calib.json`），换电脑 / 换鼠标无需改代码
- **双列瀑布流容错** — 列表布局自动学习分列（`layout.json`）、行高实测、标题续行过滤，防止滚动后点错文章
- **DPI 感知** — 进程声明 Per-Monitor DPI Aware，125%/150% 缩放下截图与点击坐标一致
- **环境自检** — `--phase env` 一键检查依赖、模板素材、TagUI 启动器、DPI 是否就绪

---

## 环境要求

| 组件 | 说明 |
|---|---|
| Windows | Win10 / Win11（实测） |
| Python | 3.9+（`pip install -r requirements.txt`） |
| Node.js | TagUI 运行依赖 |
| VC++ 2012 运行库 | **必须**。TagUI 自带的 `src\unx\*`、`src\php\*`、`phantomjs\phantomjs.exe` 为原生 exe，依赖 `MSVCR110.dll`。缺失时运行报 `MSVCR110.dll not found` |
| 微信 | 桌面版，已登录，**保持窗口可见** |

依赖清单：`numpy`、`pillow`、`opencv-python`、`rapidocr_onnxruntime`（OCR 引擎）、`pyperclip`。

---

## 快速开始

**第一步：安装依赖**

```bash
# 1. 安装 Python 3.9+ 与 Node.js
# 2. 安装 Microsoft Visual C++ 2012 Redistributable(x86 & x64)
#    官方搜索 "Visual C++ Redistributable for Visual Studio 2012" 下载
#    验证: .\tagui\src\unx\grep.exe --version 不再报 dll 缺失
# 3. 安装 Python 依赖
cd tagui/flows/wx
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
cd tagui/flows/wx

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
│           ├── wx_article.py # 一体化状态机（文章类别脚本，全部逻辑）
│           ├── tag_all.tag   # TagUI 流程入口
│           ├── requirements.txt
│           ├── home.png      # 微信侧边栏"搜一搜"图标模板
│           ├── wx_search.png # 微信主窗口顶部搜索框模板
│           ├── input_field.png  # 搜一搜窗口搜索框模板
│           ├── article.png   # "文章"标签模板
│           ├── more.png      # 详情页"..."更多按钮模板
│           ├── copy_url.png  # "复制链接"菜单模板
│           ├── articles.json # 抓取结果（自动生成）
│           ├── input_field_cache.json # 搜索框坐标缓存（自动生成）
│           ├── article_cache.json     # "文章"标签坐标缓存（自动生成）
│           ├── scroll_calib.json      # 滚轮行距校准缓存（自动生成）
│           └── layout.json   # 列表布局学习缓存（自动生成）
└── README.md
```

> **图标出处**：所有 `.png` 模板素材均为微信桌面版界面控件的局部截图（20~90 像素），仅用于 OpenCV 模板匹配定位，版权归原应用（腾讯微信）所有。如微信改版导致某步定位失败，重新截取对应控件图覆盖原 png 即可。
>
> **窗口缩放大小**：**仅支持 100% 系统缩放**（Windows "显示设置" → "缩放与布局" → "100%"）。125%/150%/175% 缩放会导致截图坐标与实际渲染像素不一致，模板匹配和 OCR 解析全面失效，整个流程无法运行。若主屏高分辨率必须用缩放，请将微信窗口拖到一台独立设置 100% 缩放的副屏再执行抓取。首次使用或更换缩放后，删除 `scroll_calib.json`、`layout.json`、`input_field_cache.json`、`article_cache.json` 让程序重新校准。

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
| 滚轮校准 | `_calibrate_scroll_px`：滚动前后 OCR 锚定同一标题，取位移中位数 → 缓存 `scroll_calib.json` |
| 布局学习 | `_learn_layout`：首屏 OCR 的 x0 分布最大间隙 → `col_split`；最顶标题 y → `list_top`，缓存 `layout.json` |
| 行高测量 | `_measure_item_height`：同列相邻条目 cy 差中位数（瀑布流双列需分列） |
| 防点错 | 滚动前后收集"标题续行"文本并过滤；列表稳定探测（连续两次 OCR 一致才点击） |
| DPI | `enable_dpi_awareness()` 声明 Per-Monitor DPI Aware（截图/取窗/点击统一物理像素） |

### 为什么这样设计（踩过的坑）

- **滚动后点错位置**：滚动动画未结束就抓坐标 → 点击落在旧位置（点到别的文章）。解决：滚动后等列表稳定 + 续行过滤。
- **双列瀑布流错配**：左右列交错会把右列标题吞掉、元信息错配。解决：先按 x 分列，每列独立配对再合并。
- **系统缩放坐标偏移**：125%/150% 缩放下截图与点击坐标互相矛盾。解决：进程声明 DPI 感知。
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

`cd tagui/flows/wx && pip install -r requirements.txt`
</details>

<details>
<summary><b>报缺模板素材</b></summary>

检查 `tagui/flows/wx/` 下 6 个 png 是否齐全，缺失时重新截图。
</details>

<details>
<summary><b>报 MSVCR110.dll 缺失 / not found</b></summary>

新电脑未装 VC++ 2012 运行库。安装 "Microsoft Visual C++ 2012 Redistributable" 的 x86 与 x64 版（x64 系两个都装），见"快速开始"第一步。
</details>

<details>
<summary><b>找不到 tagui.cmd</b></summary>

确认 `flows/wx/` 位于 `tagui/` 下（启动器自动向上两级定位，勿移动目录层级）。
</details>

<details>
<summary><b>某步模板匹配失败（微信改版）</b></summary>

重新截取对应控件图覆盖原 png。
</details>

<details>
<summary><b>点击位置偏移</b></summary>

运行 `--phase env` 确认 DPI=True；删除 `scroll_calib.json`、`layout.json`、`input_field_cache.json`、`article_cache.json` 让其重新校准。
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

## SaaS 托管版 — 已上线 🚀

**不想折腾本地部署？浏览器打开就能用** 👉 **[intelcrm.cn](https://intelcrm.cn/)**

本开源工具已作为微信情报抓取核心引擎，集成进 **Client Intel** — 企业级商业智能情报分析平台：智能 Agent 调度多源数据爬虫（含微信公众号文章），自动过滤垃圾与噪声，每日定时生成 HTML 情报简报并投递至邮箱。

- **企业新闻监测** — 自动追踪目标企业与行业动态，重要信息不错过
- **市场动态 & 竞品分析** — 多源数据实时聚合，**100% 真实出处**，极速直达
- **每日情报简报** — 定时生成 HTML 报告邮件直达，告别手动翻找
- **AI 洞察** — 面向投研 / 市场 / 品牌场景的情报自动化
- **核心引擎同源** — 微信抓取与开源版同一代码，公开可审计，不放心可自行部署
- **免费试用** — 7 天免费体验，覆盖 8,800+ 企业目标，动态解析准确率 99.8%

[🚀 立即体验](https://intelcrm.cn/) · [查看平台介绍](https://intelcrm.cn/)

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
      <img src="https://intelcrm.cn/minio/intelligence/b7f56a1bf49b943045076dda15fce716.jpg" width="200"><br>
      <b>赞赏支持</b><br>
      <em>开源不易，感谢支持</em>
    </td>
  </tr>
</table>

---

<div align="center">

**如果觉得项目有用，请给个 Star 支持一下！**

Made with ❤️

</div>
