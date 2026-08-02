# wechat-soss-scraper — 微信搜一搜公众号文章自动抓取

基于 [TagUI](https://github.com/aisingapore/TagUI) + Python 的微信「搜一搜」公众号文章采集工具。全自动完成:搜索公众号 → 进入文章列表 → 滚动翻页 → 逐篇点开详情 → 复制链接 → 落库 `articles.json`。

**跨机器 / 跨版本自适应**:不依赖任何写死的屏幕坐标,DPI、窗口尺寸、滚轮行距、列表布局均由程序在运行时动态实测与自校准。整个目录可直接拷贝到新电脑使用。

---

## 项目结构

本仓库自带 TagUI 运行时(官方引擎),开箱即用:

```
wechat-soss-scraper/
├── tagui/                    # TagUI 运行时(官方引擎,包含 src)
│   ├── src/                  # TagUI 运行时(tagui.cmd / php / node / sikulix)
│   └── flows/
│       └── wx/               # ★ 微信抓取模块(本项目全部业务代码)
│           ├── wx_all.py     # 一体化状态机(全部逻辑)
│           ├── tag_all.tag   # TagUI 流程入口
│           ├── requirements.txt
│           ├── home.png      # 微信侧边栏"搜一搜"图标模板
│           ├── wx_search.png # 微信主窗口顶部搜索框模板
│           ├── input_field.png  # 搜一搜窗口搜索框模板
│           ├── article.png   # "文章"标签模板
│           ├── more.png      # 详情页"..."更多按钮模板
│           ├── copy_url.png  # "复制链接"菜单模板
│           ├── articles.json # 抓取结果(自动生成)
│           ├── scroll_calib.json  # 滚轮行距校准缓存(自动生成)
│           └── layout.json   # 列表布局学习缓存(自动生成)
└── README.md
```

> **图标出处**:所有 `.png` 模板素材均为微信桌面版界面控件的局部截图(20~90 像素),仅用于 OpenCV 模板匹配定位,版权归原应用(腾讯微信)所有。如微信改版导致某步定位失败,重新截取对应控件图覆盖原 png 即可。
>
> **窗口缩放大小**:**仅支持 100% 系统缩放**(Windows "显示设置" → "缩放与布局" → "100%")。125%/150%/175% 缩放会导致截图坐标与实际渲染像素不一致,模板匹配和 OCR 解析全面失效,整个流程无法运行。若主屏高分辨率必须用缩放,请将微信窗口拖到一台独立设置 100% 缩放的副屏再执行抓取。首次使用或更换缩放后,删除 `scroll_calib.json` 与 `layout.json` 让程序重新校准。

---

## 特性

- **一键全流程**:单条命令完成搜索、滚动、详情、取链、落库;中断后再次运行自动去重续跑。
- **零硬编码坐标**:
  - 搜索框/更多按钮/复制链接等 UI 元素用 **PNG 模板匹配** 定位,不写绝对像素。
  - OCR 区域按 **窗口宽高比例** 生成(`get_region`),窗口大小随意。
  - 滚轮 1 格滚动的像素数 **首屏动态实测** 并缓存(`scroll_calib.json`),换电脑 / 换鼠标无需改代码。
  - 列表双列布局分界线、列表起始 Y 由 **首屏 OCR 自动学习** 并缓存(`layout.json`)。
- **DPI 感知**:进程声明 Per-Monitor DPI Aware,125%/150% 缩放下截图与点击坐标一致。
- **容错状态机**:标题续行过滤(防止滚动后点错文章)、列表稳定探测、自动加载确认、超时/中断清理。
- **环境自检**:`--phase env` 一键检查依赖、模板素材、TagUI 启动器、DPI 是否就绪。

---

## 环境要求

| 组件 | 说明 |
|---|---|
| Windows | Win10 / Win11(实测) |
| Python | 3.9+(`pip install -r requirements.txt`) |
| Node.js | TagUI 运行依赖 |
| 微信 | 桌面版,已登录 |

依赖清单:`numpy`、`pillow`、`opencv-python`、`rapidocr_onnxruntime`(OCR 引擎)、`pyperclip`。

---

## 安装

1. 安装 Python 3.9+ 与 Node.js。
2. 克隆 / 拷贝本目录到任意位置(路径无硬编码,整目录可迁移)。
3. 安装 Python 依赖:

   ```bash
   cd tagui/flows/wx
   pip install -r requirements.txt
   ```

4. **配置环境变量**:将仓库内的 `tagui\src` 目录添加到系统 PATH,使 `tagui` 命令全局可用。

   **GUI 方式**(永久生效,重启终端后生效):
   - 打开"系统属性" → "环境变量" → "系统变量"中的 `Path` → "新建"
   - 添加本仓库的 `tagui\src` 绝对路径,例如:`E:\SoftWare\wechat-soss-scraper\tagui\src`
   - "确定"保存,重新打开 CMD/PowerShell

   **PowerShell 临时方式**(仅当前会话生效):
   ```powershell
   $env:Path = "E:\SoftWare\wechat-soss-scraper\tagui\src;" + $env:Path
   tagui --version   # 验证
   ```

5. 打开微信并登录(**保持窗口可见,不要最小化到托盘,且系统缩放必须为 100%**)。

---

## 使用

```bash
cd tagui/flows/wx

# 环境自检(首次运行建议先跑)
python wx_all.py --phase env

# 抓取某个公众号的文章(按发布日期过滤)
python wx_all.py --account "隆基绿能" --start 2025-01-01 --end 2025-12-31

# 不限制日期范围(抓取全部可见历史文章)
python wx_all.py --account "光伏行业观察"

# 查看已抓取结果
python wx_all.py --phase status

# 仅收尾:保存结果 + 关闭搜一搜窗口 + 清理临时目录
python wx_all.py --phase close
```

参数:

| 参数 | 说明 | 默认 |
|---|---|---|
| `--account` | 公众号名称(必填,完整流程) | 空 |
| `--start` / `--end` | 日期范围 `YYYY-MM-DD`,超出范围的文章自动跳过 | 空 |
| `--tab` | 内容标签:`文章` / `贴图` / `视频号` | `文章` |
| `--limit` | 滚动收集上限(篇) | `50` |
| `--phase` | `close` 收尾 / `status` 查看结果 / `env` 环境自检 | 完整流程 |

> 流程运行期间请勿移动鼠标 / 切换窗口 / 锁屏,自动化需要控制焦点。

---

## 工作原理

### 流程总览

```
搜索公众号 → 进文章列表(首屏落库) → 逐篇点开详情取链接
   ↕ 滚动下一页 → 新文章落库 → 循环
   └─ 直到: 时间范围覆盖完成 且 所有文章已取到链接
```

### 状态机(`run_pipeline`)

- `covered=True`:列表已出现早于 `start` 的文章 → 时间覆盖完成 → 不再滚动。
- 未覆盖 → 滚动一屏 → 新文章落库 → 回到详情取链,循环直至到底或超上限。
- 中断后重跑:按标题去重,只补抓缺链接的文章(`pending_url`)。

### 关键自适应机制

| 机制 | 实现 |
|---|---|
| UI 定位 | OpenCV 模板匹配(`click_template` / `find_template`),失败按窗口比例回退 |
| OCR 区域 | `get_region(kind, hwnd)` 按窗口宽高比例生成,替代旧版 1920 宽写死的区域常量 |
| 滚轮校准 | `_calibrate_scroll_px`:滚动前后 OCR 锚定同一标题,取位移中位数 → 缓存 `scroll_calib.json` |
| 布局学习 | `_learn_layout`:首屏 OCR 的 x0 分布最大间隙 → `col_split`;最顶标题 y → `list_top`,缓存 `layout.json` |
| 行高测量 | `_measure_item_height`:同列相邻条目 cy 差中位数(瀑布流双列需分列) |
| 防点错 | 滚动前后收集"标题续行"文本并过滤;列表稳定探测(连续两次 OCR 一致才点击) |
| DPI | `enable_dpi_awareness()` 声明 Per-Monitor DPI Aware(截图/取窗/点击统一物理像素) |

### 为什么这样设计(踩过的坑)

- **滚动后点错位置**:滚动动画未结束就抓坐标 → 点击落在旧位置(点到别的文章)。解决:滚动后等列表稳定 + 续行过滤。
- **双列瀑布流错配**:左右列交错会把右列标题吞掉、元信息错配。解决:先按 x 分列,每列独立配对再合并。
- **系统缩放坐标偏移**:125%/150% 缩放下截图与点击坐标互相矛盾。解决:进程声明 DPI 感知。
- **换机器全部失灵**:写死的 `SCROLL_PX_PER_CLICK`、`POS_MAIN_SEARCHBOX`、`REGION_*` 区域。解决:全部改为动态实测 + 模板匹配 + 比例区域。

---

## 输出格式

`articles.json`:

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

## 故障排查

| 现象 | 处理 |
|---|---|
| `--phase env` 报缺依赖 | `cd tagui/flows/wx && pip install -r requirements.txt` |
| 报缺模板素材 | 检查 `tagui/flows/wx/` 下 6 个 png 是否齐全,缺失时重新截图 |
| 找不到 tagui.cmd | 确认 `flows/wx/` 位于 `tagui/` 下(启动器自动向上两级定位,勿移动目录层级) |
| 某步模板匹配失败(微信改版) | 重新截取对应控件图覆盖原 png |
| 点击位置偏移 | 运行 `--phase env` 确认 DPI=True;删除 `scroll_calib.json`、`layout.json` 让其重新校准 |
| 抓取中断 | 直接重新运行同一条命令,自动去重续跑 |

---

## 免责声明

本工具仅用于个人学习与研究。请遵守微信平台用户协议与相关法律法规,勿将抓取内容用于商业用途或高频抓取。
