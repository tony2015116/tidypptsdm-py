# 命令行

安装 Python 包后有 `tidypptsdm` 命令；桌面程序 `tidypptsdm.exe` 带参数运行时也是同一个命令行。

## run：运行一次

```bash
tidypptsdm run D:/nedap/exports --out D:/nedap/monitor --days 7 --open
```

读入导出文件夹，结果写到 `D:/nedap/monitor/<最后一天>/`：`index.html`、`img/` 和 `monitor.xlsx`。

| 参数 | 含义 | 默认 |
|---|---|---|
| `--out` | 结果文件夹（必填） | |
| `--format` | `xlsx` 或 `csv` | `xlsx` |
| `--open` | 完成后在浏览器中打开报告 | |
| `-q` | 不打印信息 | |
| `--days` | 监控天数 | 7 |
| `--end-date` | 最后一天，`YYYY-MM-DD` | 最后一个完整日 |
| `--house-width` | 栋号位数 | 1 |
| `--low-feed-kg` | 低采食阈值，kg | 0.5 |
| `--max-unidentified-pct` | 未识别访问报警阈值，% | 5 |
| `--max-feed-drop-pct` | 采食下降报警阈值，% | 30 |
| `--iqr-k` | 体重异常值的 Tukey 系数 | 1.5 |
| `--station` | `nedap` 或 `fire` | 自动识别 |
| `--time-zone` | 带时区的时间（如 `…T00:34:17Z`）换算到的时区：`local`、`Asia/Shanghai`，或 `UTC`（不换算），见[读取数据](data.md#时区) | `local` |

返回码：`0` 正常；`2` 有 danger 级别的警报（测定站停机或猪没有访问），方便在脚本里接着发通知；`1` 出错。

## schedule / unschedule：每天定时

```bash
tidypptsdm schedule D:/nedap/exports --out D:/nedap/monitor --time 07:30 --days 7
tidypptsdm unschedule
```

见[每天定时运行](schedule.md)。

## example：示例数据

```bash
tidypptsdm example D:/try/exports --station fire
```

## gui：桌面程序

```bash
tidypptsdm gui
```

或者 `tidypptsdm-gui`。不带任何参数运行 `tidypptsdm.exe` 也会打开桌面程序。
