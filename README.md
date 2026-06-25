# 批量调仓下单工具

桌面工具：读取产品持仓 Excel → 在界面录入买/卖调仓意图 → 自动取价算股数 → 一键导出可直接发券商的下单指令 Excel。

> **直接交易指令**模型：买入组就是要买、卖出组就是要卖，金额是该方向的成交总额，不与目标比例算差额。

---

## 给用户：怎么用

> 拿到 `调仓工具.exe` 双击即用，无需安装 Python。

1. 首次点「选择产品文件夹」，选到放产品 Excel 的文件夹（之后自动记住）。每个 `.xlsx` = 一个产品。
2. 新增交易组：选**产品**、**方向**、填**金额(元)**、选**方式**（等金额 / 当前持仓比例，必填）。
3. 给组「＋添加股票」：来源可选 **当前产品** / **全部产品** / **新增**（手输代码+价格），可一次多选。价格自动填、股数自动算。
4. 想手工指定某只数量，就在「**调整**」列填（以调整为准）。
5. 点「**预览**」核对（卖出标黄、在前）→「确认并导出」（单文件多 sheet）或「分产品导出」→ 发券商。

调仓全部在界面录入，无 Excel 导入步骤；只有最终下单指令导出成 Excel。

---

## 计算规则

- **组金额分到每只**：等金额 = 均分；当前持仓比例 = 按各股当前持仓市值占比（未持仓占 0，建仓请用等金额）。
- **股数** = 分得金额 ÷ 人民币单价，取整到「手」：A股/ETF/港股默认 100 股，科创板（688）最小买入 200 股，可转债 10 张。
- **卖出**不超过当前持仓；接近清仓时一次性全卖（含零股）；手填「调整」超持仓会自动封顶并提示。
- **最终下单数量** = 调整（若填）否则 股数。
- 港股公允价为港币、市值为人民币，用 `市值/数量` 反推人民币单价（自动含汇率）；新增（不在任何产品里）的标的需手填价格。

---

## 给开发：打包与测试

> PyInstaller 不跨系统：Windows 版要在 Windows 上打，Mac 版要在 Mac 上打。

**最省事**：推到 GitHub 后由 Actions 自动构建——到 **Actions** 页下载绿色版 / 安装包；打 `v*` 标签自动发到 Release。

**本地打包**：

| 平台 | 操作 | 产物 |
| --- | --- | --- |
| Windows | 双击 `build/build_windows.bat` | `dist/调仓工具.exe`（绿色版）+ 安装包（需先装 [Inno Setup 6](https://jrsoftware.org/isdl.php)） |
| macOS | 双击 `build/build_mac.command` | `dist/调仓工具.app`（未签名，首次打开右键→打开） |
| 通用 | `pyinstaller build/调仓工具.spec --noconfirm --clean` | 按当前系统出对应产物 |

**开发 / 测试**：

```bash
pip install -r requirements.txt pytest
pytest -q                  # 单元测试
python app.py              # 启动界面
python app.py --selftest   # 无界面自检（CI/打包后冒烟）
```

### 目录结构

```
├── app.py                  # 桌面界面（PySide6，三级树录入）
├── rebalancer/             # 核心逻辑（与界面解耦，可单独测试）
│   ├── config.py           #   手数/汇率/列名/更新源 等可调参数
│   ├── models.py           #   数据模型
│   ├── reader.py           #   读取产品持仓 Excel（容错表头/单位/参差行）
│   ├── pools.py            #   全部产品合并证券池
│   ├── engine.py           #   交易组 → 下单指令 计算引擎
│   └── excel_io.py         #   写券商下单指令 Excel
├── tests/                  # pytest 测试
├── build/                  # 打包脚本 + 配置（spec / installer.iss / bat / command）
├── .github/workflows/      # CI：Windows/macOS 自动构建
├── product/                # 放产品持仓 Excel（已 .gitignore，不入库）
└── dist/                   # 构建产物 exe/app/安装包（已 .gitignore）
```

### 可调参数（`rebalancer/config.py`）

- `DEFAULT_LOT` / `HK_DEFAULT_LOT` / `STAR_BOARD_MIN_BUY` / `LOT_OVERRIDES`：交易手数规则。
- `FX_FALLBACK`：外币兜底汇率（默认优先用持仓反推的隐含汇率）。
- `UPDATE_REPO`：「检查更新」指向的 GitHub 仓库。
