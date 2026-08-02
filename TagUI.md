TagUI 是一款强大的**开源、免费**的 RPA 工具，它通过类似“人话”的语言来驱动浏览器、桌面软件以及视觉图像。

针对你之前控制“无端口、无 API 的微信”这类顽固桌面软件的需求，我为你总结了一份 **TagUI 全套操作教程（从入门到工业级进阶）**。

---

## 1. 基础篇：安装与核心概念

### 环境配置
1.  **安装包**：建议去 GitHub 的 `releases` 下载打包好的 Windows zip。
2.  **环境变量**：必须将 `src` 文件夹的绝对路径加入 Windows 的 **Path**。
3.  **前置依赖**：视觉识别依赖 **64 位 Java (JRE 8+)**，一定要确保在终端执行 `java -version` 成功。

### 脚本结构
TagUI 的脚本是 `.tag` 文件。每一行代表一个步骤，注释使用 `//`。执行时不需要 `-h` 即可操作桌面程序。

---

## 2. 操作指令全手册 (Cheat Sheet)

### A. 桌面交互 (万能键盘与鼠标)
当页面没有 ID 也没有代码调试接口时，用这套指令：

| 指令 | 语法 | 说明 |
| :--- | :--- | :--- |
| **keyboard** | `keyboard [win][d]` | 发送组合键、普通字符。常用的：`[ctrl]a`, `[enter]`, `[tab]` |
| **mouse** | `mouse down`, `mouse up` | 底层鼠标操作，适合长按、拖拽 |
| **scroll** | `scroll down` | 模拟滚轮下滑 |
| **wait** | `wait 3` | 给界面加载和缓存留出时间 (单位：秒) |

### B. 视觉自动化 (Visual Automation)
TagUI 最强大的地方——利用“图片”当选择器：

*   **图片点击**：`click logo.png` (寻找屏幕上的图片并点击中心)
*   **输入框操作**：`type input.png as content` (找到图片位置输入文字)
*   **坐标点击**：`click (100, 200)` (直接点击屏幕物理坐标)
*   **精准度设置**：`click icon.png (90%)` (要求图像相似度达到 90%)

### C. 数据提取与变量
*   **OCR 识别**：`read (x1, y1, x2, y2) to my_data` (扫描区域文字存入变量)
*   **读 DOM (如果可用)**：`read .css_class to var_name`
*   **打印数据**：`echo "获取到内容为：" + var_name`
*   **写入文件**：`dump `var_name` to result.csv` (写入 csv 或 txt)

---

## 3. 高级控制流：变量与逻辑

### 用户交互
`ask 请输入关键字：` 会弹出一个输入框。用户输入的内容会被保存在内置变量 **`ask_result`** 中。

### IF 条件判断
```text
if exist('ok_button.png')
    click ok_button.png
else
    echo "未找到确认按钮，正在尝试重启"
    keyboard [f5]
```

### 循环逻辑
*   **固定次数**：`for n from 1 to 5`
*   **死循环或带条件**：`while exist('more.png')`

---

## 4. 跨平台集成：打通 Python 和系统

### 集成 Python (RPA 之魂)
你可以利用 Python 的库处理中文或复杂数据：
```text
py_begin
import pyperclip
pyperclip.copy("我想说中文")
py_finish
// 随后可以在界面点击后粘贴
keyboard [ctrl]v
```

### 直接运行系统命令
`run python script.py` 允许你在流程中随时执行一个本地的 Python 脚本、CMD 或是 PowerShell 任务。
