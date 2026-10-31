# 读取数据

`tp.read_station()` 读入导出文件并统一成标准字段；`tp.prep_visits()` 再整理成访问记录。所有监控函数都可以直接传入文件夹、原始数据或这两个函数的结果。

## 支持的文件

- CSV 和 TXT：自动识别分隔符（逗号、分号、制表符），编码 UTF-8 或 GBK；
- Excel：`.xlsx`（`.xls` 请另存为 `.xlsx` 或 CSV）；
- 传入文件夹时，读入其中（含子文件夹）所有 `.csv`、`.txt`、`.xlsx` 文件。

耳标号按文本读入，开头的 0 不会丢。

## 标准字段和单位

| 字段 | 单位 | NEDAP 列 | FIRE 列 |
|---|---|---|---|
| `responder` | 文本 | `responder` | `Tag` |
| `location` | 文本 | `location` | `Location` |
| `entry_time` | 时间 | `visit_time` | `Date` + `Entry` |
| `exit_time` | 时间 | （由时长计算） | `Date` + `Exit` |
| `duration` | 秒 | `duration`（秒） | （由进出站时间计算） |
| `feed_intake` | g | `feed_intake`（g） | `Consumed`（kg） |
| `weight` | kg | `weight`（g 或 kg，自动判断） | `Weight`（kg） |
| `trough_in`、`trough_out`、`topup` | g | — | `Ent Wt`、`Ext Wt`、`Topup Amount` |

## 时区

有些 NEDAP 导出的时间带时区标记，例如 `2025-01-24T00:34:17Z`：`Z` 表示 UTC 时间，北京时间是 08:34:17。tidypptsdm 会把带时区的时间换算成**这台电脑所在时区**的本地时间，再按天统计，这样每天从本地 0 点算起。日志里会提示 “Visit times with time zone UTC converted to local time …”。不带时区标记的时间不换算。

| `time_zone` | 含义 |
|---|---|
| `"local"`（默认） | 换算到这台电脑的时区 |
| `"Asia/Shanghai"` 等 | 换算到指定时区，例如在别的时区的电脑上处理国内的数据 |
| `"UTC"` | 不换算，按原样使用（与 R 版 tidypptsda 的做法相同） |

**怎么确认 `Z` 真的是 UTC**：看报告里的分小时图。猪一般在凌晨吃得最少。如果用 `--time-zone UTC` 原样读入后，采食最少的时段在 16–21 点（北京时间 0–5 点），说明确实是 UTC，应该用默认的换算；如果原样读入后最少的时段就在 0–5 点，说明导出的其实已是本地时间，请用 `--time-zone UTC`。

!!! note "与 R 版的差别"
    R 包 tidypptsda 读入 `...Z` 的时间时不做换算，按 UTC 划分日期。对这类数据，Python 版默认的结果与 R 版相差 8 小时的日期划分；用 `time_zone="UTC"` 时两者一致。

## 整理规则（`prep_visits()`）

- 耳标号为空或 0 的访问是**未识别访问**：保留，`identified = False`，用于计算未识别比例；
- 体重为 0 或负数表示没有称重，记为空；
- FIRE 的出站时刻早于进站时刻、修正后时长不超过 1 小时的，是跨午夜的访问，出站日期加一天；
- 没有进站时间的行和完全重复的行删除；
- **转栏与误读**：一头猪按时间排序后，如果在另一台测定站上只有连续不超过 2 次（`misread_max_visits`）的访问，夹在本站的访问之间，视为耳标误读，这些访问改为未识别访问；更长的连续访问视为真正的转栏，保留在实际的测定站。

## 列名不同的导出文件

用格式文件指定每个字段对应哪一列：

```python
tp.station_format("fire", file="fire_format.txt")   # 写出模板，编辑后使用
d = tp.read_station("D:/exports", station="fire", format="fire_format.txt")
```

格式文件是制表符分隔的三列：`field`、`column`、`unit`。`column` 可以是列名或列号，多个候选用 `|` 分隔（`Tag|耳标号`），日期和时刻两列用 `,` 连接（`日期,进站`），`-` 表示没有这一列。`unit`：质量为 `kg`、`g` 或 `auto`，时长为 `s` 或 `min`，时间为 `-`（自动识别）或 strptime 格式（如 `%d/%m/%Y %H:%M`）。

格式文件与 R 包 tidypptsda 的格式文件通用。
