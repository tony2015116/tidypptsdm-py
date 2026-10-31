# 更新日志

## 1.1.0

第一个 Python 版本，对应 R 包 tidypptsdm 1.1.0。

- 读取 NEDAP 和 FIRE 导出文件（CSV、TXT、Excel），格式文件与 tidypptsda 通用；整理规则与 `tidypptsda::prep_visits()` 相同（未识别访问、跨午夜、转栏与误读）。
- `run_monitor()`：每站、每栋、每猪、每小时的日表和最后一天的警报；与 R 版逐表一致。
- 五种图：趋势（含体重）、采食量堆叠柱状图、热图、体重箱线图、分小时图。
- HTML 报告（与 R 版页面相同）、Excel 工作簿（带色阶）或 CSV。
- 每天定时运行：Windows 任务计划程序或 crontab。
- 命令行 `tidypptsdm` 和桌面程序（Windows exe，不需要安装 Python）。
