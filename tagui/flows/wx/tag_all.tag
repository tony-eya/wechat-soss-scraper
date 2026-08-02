// ============================================================
// tag_all.tag - 一体化流程(search -> detail -> scroll 状态机)
// 单次 TagUI 进程内完成全部步骤,不反复创建进程。
//
// 全部业务逻辑已合并到 wx_all.py(run_pipeline),本文件仅作为
// TagUI 进程入口: 注入 WX_WORKDIR -> import wx_all -> 执行状态机。
// 状态机规则(见 wx_all.run_pipeline):
//   * covered=True : 已出现早于 start 的文章 -> 时间范围覆盖完成
//                    -> 之后永远不再执行 scroll
//   * need_scroll  : 当前列表全部在时间范围内 -> 下一页可能还有符合条件的
//                    -> 先 detail 抓取链接,再 scroll 滚动
//   * scroll 后    : 新列表出现超出范围文章 -> covered=True,停止滚动
//                   但仍需再执行一次 detail 抓取刚落库的新文章
//   * 结束条件     : covered=True 且所有 pending url 已抓完(无需再 scroll)
// ============================================================

py begin
import sys, os
_wd = os.environ.get('WX_WORKDIR', '')
if not _wd or not os.path.isdir(_wd):
    print('ERROR - WX_WORKDIR_NOT_SET')
    raise SystemExit(1)
sys.path.insert(0, _wd)
import wx_all
wx_all.run_pipeline()
py finish
echo `py_result`

echo "TAG_ALL_DONE"
