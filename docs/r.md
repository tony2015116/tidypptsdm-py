# 与 R 版的关系

| | R | Python |
|---|---|---|
| 包 | [tidypptsdm](https://github.com/tony2015116/tidypptsdm)（监控）+ [tidypptsda](https://tony2015116.github.io/tidypptsda/)（读取、整理，以及 ADG、ADFI、FCR） | tidypptsdm（读取、整理、监控） |
| 适合 | 在 R 中分析，测定结束后计算 ADG / ADFI / FCR | 每日监控；桌面程序给不用 R 的同事 |
| 结果 | — | 与 R 版逐表一致 |

## 函数对应

| R | Python |
|---|---|
| `run_monitor()` | `run_monitor()`，返回 `Monitor`，表格用属性访问：`mon.stations` |
| `monitor_stations()` 等 | 同名 |
| `wide_table()` | 同名 |
| `plot_monitor()` | 同名，返回 matplotlib 图的列表 |
| `save_monitor_plots()` | 同名 |
| `write_monitor_report()`、`write_monitor_tables()` | 同名；HTML 报告页面相同 |
| `schedule_monitor()` | 同名；Windows 上用 `schtasks`，不需要 taskscheduleR |
| `tidypptsda::read_station()`、`prep_visits()`、`station_format()` | 同名 |
| `tidypptsda::nedap`、`fire` | `load_example("nedap")`、`load_example("fire")` |
| — | `monitor_to_folder()`、命令行、桌面程序 |

参数名与 R 版相同（`days`、`end_date`、`house_width`、`low_feed_kg` 等），默认值也相同。

## 结果一致性

测试 `tests/test_parity.py` 用 R 版在两份示例数据上的结果（`tests/fixtures`）逐表对比：访问记录、测定站、栋、猪、猪只汇总、每小时、警报和宽表，7 天和 21 天两种窗口，以及一个人为制造测定站停机和猪不访问的场景。数值允许相差最后一位小数的一个单位（例如 20.265 这样正好在进位边界上的值，浮点数按不同顺序相加时可能落在边界两侧）。

为了做到一致，Python 版专门复现了 R 的两个细节：

- **四舍五入**：R 按数值的精确二进制值取整，`round(0.15, 1)` 得 0.1；numpy 得 0.2。
- **分位数**：体重异常值用 R 的 `quantile(type = 7)` 算法，正好落在界线上的体重判断与 R 相同。

## 不包含的部分

tidypptsda 中测定结束后的分析（体重清洗、ADG、饲喂错误判定、ADFI 校正、FCR、方法验证）没有移植，请继续使用 R 包。
