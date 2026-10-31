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
