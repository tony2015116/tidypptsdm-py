# 快速入门

```python
import tidypptsdm as tp
```

## 1. 一次巡检

```python
mon = tp.run_monitor("D:/nedap/exports", days=7)
```

`run_monitor()` 读入文件夹中的全部导出文件（也包括子文件夹），整理成统一的访问记录，计算最近 `days` 天的各张日表，并列出最后一天的警报。屏幕上会打印摘要：

```text
-- Monitoring NEDAP stations: 2024-05-19 to 2024-05-25 (7 days) --------
i 2 stations, 28 pigs; on 2024-05-25: 190 visits, 39.5 kg feed
! 2 alerts: 2 danger, 0 warning
  x Station 102: No visits on 2024-05-25 (15 pigs)
  x Pig 15983 (station 101): No visit for 2 days (last weight 143.0 kg)
```

没有自己的数据时，可以用自带的示例数据：`tp.run_monitor(tp.load_example("nedap"))`，或者 `tp.load_example("fire")`。

监控窗口是截至 `end_date` 的 `days` 天（含首尾）。`end_date` 默认取数据里的最后一天；如果最后一天就是今天，则取昨天，因为白天导出的数据当天还不完整。也可以自己指定，如 `end_date="2024-05-20"`。

## 2. 结果

`mon` 是一个 [`Monitor`](reference.md#tidypptsdm.Monitor)，各张表都是 pandas DataFrame：

| 属性 | 内容 |
|---|---|
| `mon.stations` | 每台测定站每天一行 |
| `mon.houses` | 每栋每天一行（栋 = 测定站编号的前 `house_width` 位） |
| `mon.pigs` | 每头猪每天一行，没有访问的日子也在 |
| `mon.pig_summary` | 每头猪一行：低采食天数、无访问天数、最后一天的状态等 |
| `mon.hours` | 最后一天每台测定站每小时一行 |
| `mon.alerts` | 最后一天的警报 |
| `mon.visits` | 窗口内的访问记录 |
| `mon.settings` | 参数和窗口 |

每一列的含义见[表格与警报](output.md)。

## 3. 宽表

```python
tp.wide_table(mon.stations, "feed_kg")
```

```text
  location   05-19   05-20   05-21   05-22  05-23   05-24   05-25    total
0      101  50.923  49.585  46.784  44.780  47.12  44.424  42.030  325.646
1      102  58.752  56.385  47.664  53.857  50.52  55.163  42.784  365.125
```

## 4. 报告和表格

```python
out = "D:/nedap/monitor/2024-05-25"
tp.write_monitor_report(mon, out, open=True)   # index.html + img/
tp.write_monitor_tables(mon, out)               # monitor.xlsx
```

或者一步完成，自动写到以最后一天命名的子文件夹：

```python
tp.monitor_to_folder("D:/nedap/exports", "D:/nedap/monitor", days=7, open=True)
```

## 5. 作图

```python
plots = tp.plot_monitor(mon, "intake")   # 每台测定站一张
plots[0].figure                           # matplotlib Figure
tp.save_monitor_plots(plots, "plots")
```

五种图见[图与报告](plots.md)。
