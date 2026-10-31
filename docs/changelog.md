# 更新日志

## 1.1.1

- 读取 ISO 8601 格式的时间，如 `2025-01-24T00:34:17Z`、`2025-01-24T08:34:17+08:00`。带时区的时间换算到本地时区后再按天统计；新参数 `time_zone`（命令行 `--time-zone`）。
- 桌面程序：先加载自带的 Tcl/Tk，避免其他软件的 Tk 干扰；窗口打不开时给出中文说明和诊断文件；新命令 `tidypptsdm selftest`。
- 测定站很多时，报告逐站作图并显示进度，内存占用更小。

## 1.1.0

第一个 Python 版本，对应 R 包 tidypptsdm 1.1.0。

- 读取 NEDAP 和 FIRE 导出文件（CSV、TXT、Excel），格式文件与 tidypptsda 通用；整理规则与 `tidypptsda::prep_visits()` 相同（未识别访问、跨午夜、转栏与误读）。
- `run_monitor()`：每站、每栋、每猪、每小时的日表和最后一天的警报；与 R 版逐表一致。
- 五种图：趋势（含体重）、采食量堆叠柱状图、热图、体重箱线图、分小时图。
- HTML 报告（与 R 版页面相同）、Excel 工作簿（带色阶）或 CSV。
- 每天定时运行：Windows 任务计划程序或 crontab。
- 命令行 `tidypptsdm` 和桌面程序（Windows exe，不需要安装 Python）。
