// ============================================================
// tag_all.tag - 混合流程: 原生 click 图标 + py 逻辑块交错
//
// 执行序列:
//   py flow_begin()          侦查阶段A(主窗口 home 图标)
//   (若 SOSS 未开) click home.png     原生 SikuliX 全屏点击打开搜一搜
//   py flow_wait_soss()      等待 SOSS + 侦查阶段B(input_field 搜索框)
//   click input_field.png    原生点击搜索框
//   py flow_fill_search()    粘贴账号 + 回车 + OCR 定位公众号并点击
//   click article.png        原生点击"文章"标签
//   py flow_articles()       解析首屏 -> 落库 -> 状态机(滚动+详情)
//
// 侦查层(recon)保证每个图标先侦查确认可定位;已定位的图标由 tag 原生
// click 完成(不经 get_region,不受区域裁剪影响);py 块负责侦查/粘贴/
// OCR定位/滚动/详情等逻辑。坐标全部运行时定位,不写死 -> 开源安全。
//
// 兼容两条入口路径:
//   A) 正常路径: SOSS 未开,py flow_begin 后由 click home.png 打开;
//   B) fallback 路径: SOSS 已由 open_soss_from_main 打开,
//      py 块输出 SOSS_ALREADY_OPEN=True,跳过 click home.png。
// ============================================================

py begin
import sys, os, json
_wd = os.environ.get('WX_WORKDIR', '')
if not _wd or not os.path.isdir(_wd):
    print('ERROR - WX_WORKDIR_NOT_SET')
    raise SystemExit(1)
sys.path.insert(0, _wd)
import wx_all
_r = json.loads(wx_all.flow_begin())
print('FLOW_BEGIN ok=%s' % _r.get('ok'))
print('SOSS_ALREADY_OPEN=%s' % bool(wx_all.find_wx_window()))
py finish

if py_result contains "SOSS_ALREADY_OPEN=False"
    click home.png
    wait 2
echo "AFTER_HOME_CLICK"

py begin
import sys, os, json
sys.path.insert(0, os.environ.get('WX_WORKDIR', ''))
import wx_all
_r = json.loads(wx_all.flow_wait_soss())
print('FLOW_WAIT_SOSS ok=%s hwnd=%s' % (_r.get('ok'), _r.get('hwnd')))
py finish

click input_field.png
wait 1

py begin
import sys, os, json
sys.path.insert(0, os.environ.get('WX_WORKDIR', ''))
import wx_all
_r = json.loads(wx_all.flow_fill_search())
print('FLOW_FILL_SEARCH ok=%s' % _r.get('ok'))
py finish

click article.png
wait 2

py begin
import sys, os, json
sys.path.insert(0, os.environ.get('WX_WORKDIR', ''))
import wx_all
_r = json.loads(wx_all.flow_articles())
print('FLOW_ARTICLES ok=%s' % _r.get('ok'))
py finish

echo "TAG_ALL_DONE"
