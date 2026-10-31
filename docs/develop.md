# 开发与发布

## 本地开发

```bash
git clone https://github.com/tony2015116/tidypptsdm-py
cd tidypptsdm-py
pip install -e ".[test,docs]"
pytest                 # 全部测试，含与 R 版的对比
mkdocs serve           # 本地预览网站
```

## 自动化（GitHub Actions）

| 工作流 | 触发 | 作用 |
|---|---|---|
| `tests.yml` | 推送、PR | Windows / macOS / Linux，Python 3.10 和 3.13，运行全部测试 |
| `docs.yml` | 推送到 main | 构建网站并发布到 `gh-pages` 分支 |
| `build-exe.yml` | 推送、PR、发布 Release | 在 Windows 上用 PyInstaller 打包，冒烟测试后上传 `tidypptsdm-windows.zip`；发布 Release 时自动附到 Release 上 |
| `publish.yml` | 发布 Release | 构建并发布到 PyPI |

## 发布新版本

1. 修改 `src/tidypptsdm/_version.py` 的版本号，在 `docs/changelog.md` 写更新内容；
2. 推送到 main；
3. 在 GitHub 上新建 Release，tag 为 `v版本号`（例如 `v1.1.0`）。exe 和 PyPI 包会自动构建并发布。

## 第一次设置（只需一次）

- **网站**：Settings → Pages → Source 选 “Deploy from a branch”，分支选 `gh-pages`、`/ (root)`。`docs.yml` 第一次运行后才会有这个分支。
- **PyPI**：在 <https://pypi.org/manage/account/publishing/> 添加 “pending publisher”：PyPI project name `tidypptsdm`，Owner `tony2015116`，Repository `tidypptsdm-py`，Workflow `publish.yml`，Environment `pypi`。之后不需要任何密码或 token。

## R 版有修改时

R 版改了计算方法后，重新生成对比用的结果：

```r
# 在 R 中，安装新版 tidypptsdm 后运行
source("tests/make_fixtures.R")
```

然后修改 Python 代码直到 `pytest tests/test_parity.py` 通过。
