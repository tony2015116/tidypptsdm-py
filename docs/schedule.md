# 每天定时运行

`schedule_monitor()`（命令行 `tidypptsdm schedule`，桌面程序“设为每天定时”）做两件事：

1. 写一个小脚本（Windows 上是 `.bat`，其他系统是 `.sh`），运行 `tidypptsdm run`：读入导出文件夹，把报告和表格写到 `结果文件夹/<最后一天>/`；
2. 让它每天定时运行：Windows 上注册到“任务计划程序”，Linux 和 macOS 上打印一行 crontab 配置。

## Windows

```bash
tidypptsdm schedule D:/nedap/exports --out D:/nedap/monitor --time 07:30 --days 7 --house-width 1
```

或在 Python 中：

```python
tp.schedule_monitor("D:/nedap/exports", "D:/nedap/monitor", time="07:30", days=7)
```

任务名默认为 `tidypptsdm_monitor`，可以在“任务计划程序”里查看、手动运行或修改。脚本 `tidypptsdm_monitor.bat` 保存在结果文件夹（可用 `script_dir` 改），运行日志追加到旁边的 `tidypptsdm_monitor.log`。删除任务：

```bash
tidypptsdm unschedule
```

## Linux 和 macOS

同样运行 `tidypptsdm schedule …`，它会打印一行，例如：

```text
30 7 * * * /data/monitor/tidypptsdm_monitor.sh
```

运行 `crontab -e`，把这一行加进去。tidypptsdm 不会自己改动 crontab。

## 只写脚本

`--no-register`（Python 中 `register=False`）只写脚本，可以先检查，或放进别的调度工具。

## 注意

- 报告以最后一个完整的日期命名：导出数据的最后一天如果是今天，取昨天。所以把运行时间设在导出之后即可。
- 每次都会重新读入文件夹中的全部导出文件。文件很多时，可以把已经结束的批次移到别的文件夹。
- 到时间时电脑需要开着。桌面程序挪到别的文件夹后，需要重新“设为每天定时”。

## 定时任务没有出结果？

1. **数据没有更新**：结果文件夹以数据的最后一天命名。导出文件夹里没有新数据时，每次运行都写到同一个日期文件夹（覆盖），看起来像没有运行。看日志 `结果文件夹\tidypptsdm.log`：每次运行都会写一行 “run started 时间”，并提示 “The latest data are from … days ago”。
2. **看任务状态**：桌面程序点“查看定时状态”，或命令行 `tidypptsdm status --out 结果文件夹`。“上次运行时间”是空的说明还没到时间；“上次结果”0 表示成功。
3. **马上试一次**：桌面程序点“立即运行一次”，一两分钟后再看状态和日志。
4. **电脑**：到时间时需要开机并登录（可以锁屏）。关机或睡眠错过的运行，会在开机后补跑一次；用电池时也会运行。
5. **挪动了程序**：任务记录的是 exe 的完整路径。把程序文件夹挪到别处后，需要重新“设为每天定时”。
