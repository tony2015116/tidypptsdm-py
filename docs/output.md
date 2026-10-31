# 表格与警报

所有日表都有一个共同点：**窗口内每个单位每天都有一行，没有访问的日子也在**，计数为 0、其他列为空。停机的测定站、不吃料的猪因此不会从表里“消失”。

列名的后缀就是单位：`_kg` 千克、`_h` 小时、`_min` 分钟、`pct_` 百分比、`n_` 计数。

## 测定站：`stations`

| 列 | 含义 |
|---|---|
| `location`、`date` | 测定站、日期 |
| `n_pigs` | 当天有识别访问的猪数 |
| `n_visits` | 全部访问次数（含未识别） |
| `n_unidentified`、`pct_unidentified` | 未读到耳标的访问次数和百分比 |
| `occupation_h` | 测定站被占用的总时间，小时 |
| `feed_kg` | 全部访问的采食量，kg |
| `feed_per_pig_kg` | 识别访问的采食量 ÷ `n_pigs` |
| `weight_kg` | 每头猪当天体重中位数（去掉异常值）的平均 |
| `pct_weight_outlier` | 体重异常值的百分比：同一头猪同一天的体重中，超出四分位数 ± `iqr_k` × 四分位距（Tukey fences）的记录；少于 4 次称重时不判异常 |

列出的测定站是窗口内或窗口前 14 天内有访问的测定站：停止记录的测定站会显示两周（并报警），早已撤出测定的不再列出。

## 栋：`houses`

栋由测定站编号的前 `house_width` 个字符决定。列：`house`、`date`、`n_stations`、`n_pigs`、`n_visits`、`feed_kg`、`feed_per_pig_kg`、`weight_kg`。

## 猪：`pigs` 和 `pig_summary`

`pigs` 每头猪每天一行，从这头猪第一次出现（或窗口开始）到最后一天：

| 列 | 含义 |
|---|---|
| `location` | 窗口内这头猪访问最多的测定站 |
| `n_visits`、`feed_kg`、`occupation_min` | 当天访问次数、采食量、占用时间（分钟） |
| `weight_kg` | 当天体重的中位数 |
| `status` | `no_visit`（无访问）、`low_feed`（低于 `low_feed_kg`）或 `ok` |

`pig_summary` 每头猪一行：`days`、`no_visit_days`、`low_feed_days`、`mean_feed_kg`（无访问的日子按 0 计）、`last_feed_kg`、`last_visits`、`last_weight_kg`、`days_since_visit`、`status`（最后一天）。

## 每小时：`hours`

最后一天每台测定站 0–23 时每小时一行：`n_pigs`、`n_visits`、`occupation_min`、`feed_kg`。小时按进站时间计。

## 警报：`alerts`

| type | level | 条件（默认参数） |
|---|---|---|
| `station_down` | danger | 测定站一整天没有任何访问 |
| `unidentified` | warning | 未识别访问超过 `max_unidentified_pct` = 5% |
| `feed_drop` | warning | 测定站采食量比窗口内前几天的平均低 `max_feed_drop_pct` = 30% 以上 |
| `pig_no_visit` | danger | 窗口内出现过的猪当天没有访问 |
| `pig_low_feed` | warning | 猪当天采食量低于 `low_feed_kg` = 0.5 kg |

停机测定站上的猪不再逐头报警，由 `station_down` 一条警报说明（括号里是受影响的猪数）。列：`level`、`type`、`location`、`responder`（猪只警报）、`value`（触发的数值）、`message`。

## Excel 工作簿 { #excel }

`write_monitor_tables(mon, path)` 写出 `monitor.xlsx`。长表原样写出；宽表加三色色阶，红色表示可能有问题。

| 工作表 | 内容 | 红色表示 |
|---|---|---|
| `Alerts` | 警报 | |
| `Stations`、`Houses`、`Pigs`、`Pig days` | 长表（`Pigs` 是 `pig_summary`，`Pig days` 是 `pigs`） | |
| `Visits` | 每站每天访问次数 | 偏低 |
| `Unidentified pct` | 未识别访问 % | 偏高 |
| `Feed kg`、`Feed per pig kg` | 采食量、头均采食量 | 偏低 |
| `Occupation h` | 占用时间 | 偏低 |
| `Weight outliers pct` | 体重异常值 % | 偏高 |
| `House feed per pig kg` | 每栋头均采食量 | 偏低 |
| `House weight kg` | 每栋平均体重 | （蓝色色阶） |
| `Pig feed kg` | 每头猪每天采食量 | 偏低 |
| `Hours visits`、`Hours feed kg` | 最后一天每小时 | （蓝色色阶） |

`format="csv"` 则写出 6 个 CSV 文件（`monitor_alerts.csv` 等），带 BOM，Excel 直接打开不乱码。
