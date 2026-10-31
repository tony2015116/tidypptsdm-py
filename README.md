# tidypptsdm (Python) <img src="docs/assets/logo.svg" align="right" height="120" alt="logo" />

[![tests](https://github.com/tony2015116/tidypptsdm-py/actions/workflows/tests.yml/badge.svg)](https://github.com/tony2015116/tidypptsdm-py/actions/workflows/tests.yml)
[![docs](https://github.com/tony2015116/tidypptsdm-py/actions/workflows/docs.yml/badge.svg)](https://tony2015116.github.io/tidypptsdm-py/)

**种猪性能测定站日常监控**：读取 NEDAP 或 FIRE 测定站的导出文件，按测定站、栋、猪和小时汇总最近几天的数据，列出最后一天的警报（测定站停机、耳标读不到、采食量骤降、猪不来吃料或吃得太少），并生成可以逐站翻页浏览的 HTML 报告和带色阶的 Excel 工作簿。

Daily monitoring of automatic pig feeding stations (NEDAP and FIRE): daily
tables per station, house, pig and hour, alerts of the last day, an offline
HTML report and an Excel workbook.

这是 R 包 [tidypptsdm](https://github.com/tony2015116/tidypptsdm) 的 Python 版本，**计算结果与 R 版逐表一致**（测试中用两份示例数据对比）。

文档：<https://tony2015116.github.io/tidypptsdm-py/>　·　R 版：<https://tony2015116.github.io/tidypptsdm/>

## 三种用法

### 1. 桌面程序（Windows，不需要安装 Python）

从 [Releases](https://github.com/tony2015116/tidypptsdm-py/releases) 下载 `tidypptsdm-windows.zip`，解压后双击 `tidypptsdm.exe`：选择导出文件夹和结果文件夹，点“运行监控”，报告自动在浏览器中打开；点“设为每天定时”即可每天自动生成报告。

### 2. 命令行

```bash
pip install tidypptsdm
tidypptsdm run D:/nedap/exports --out D:/nedap/monitor --days 7
tidypptsdm schedule D:/nedap/exports --out D:/nedap/monitor --time 07:30
```

### 3. Python

```python
import tidypptsdm as tp

mon = tp.run_monitor("D:/nedap/exports", days=7)   # or tp.load_example("nedap")
mon.alerts
tp.wide_table(mon.stations, "feed_kg")
tp.write_monitor_report(mon, "monitor/2024-05-25", open=True)
tp.write_monitor_tables(mon, "monitor/2024-05-25")
```

## 依赖

pandas、numpy、matplotlib、openpyxl。图形界面用 Python 自带的 tkinter。
