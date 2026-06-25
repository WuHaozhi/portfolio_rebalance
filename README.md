# 批量调仓下单工具

给基金经理用的批量调仓工具：读取每个产品的实时监控持仓 → 在界面上按「买入组 / 卖出组」录入调仓意图 → 自动取价算股数 → 一键生成可直接发券商的交易指令 Excel。

---

## 一、它能做什么

1. **自动读取产品文件夹**：启动后自动加载上次用过的 `product/` 文件夹（首次手动选一次即记住）。每个 `.xlsx` = 一个产品（如 `稳进9号-实时监控20260610.xlsx`），解析其持仓、价格、汇率。
2. **分组录入调仓**：新建「买入组 / 卖出组」，填该组**总金额**、选**方式**（等金额 / 当前持仓比例），再往组里加股票。
3. **自动取价算股数**：股票价格自动取自 product 文件（昨日收盘/公允价格，统一为人民币单价）；按金额自动算出股数（取整到手、科创板≥200）。
4. **允许手工调整股数**：如某股当天涨停买不进，可在「调整」列改股数（清零或加大别的票）。
5. **确认并导出**：点「确认并导出」核对下单指令（卖出标黄、在前），导出券商下单格式 Excel。

> 本工具是**直接交易指令**模型：买入组就是要买、卖出组就是要卖，金额是本次该方向的成交总额——不与当前持仓比目标算差额。

---

## 二、给基金经理：怎么用

> 已拿到打包好的 `调仓工具.exe`，无需安装 Python。

1. 双击 `调仓工具.exe`。首次点「📁 选择产品文件夹」选到放产品 Excel 的文件夹（之后自动记住）。
2. 点 **＋买入组** 或 **＋卖出组** 新建一个交易组：
   - 选**产品**、确认**方向**、填**金额(元)**、选**方式**（等金额 / 当前持仓比例，**必填**）。
3. 选中该组，点 **＋添加股票**：
   - 来源选 **当前产品**（该产品持仓里挑）/ **全部产品**（所有产品合并池里挑）/ **新增**（手输代码+价格）；可一次多选。
   - 价格自动填好；**股数**自动按金额算出。
4. 如需手工指定某只的数量，直接在 **调整** 列填（填了就以「调整」为准）。改完点 **↻重算股数**。
5. 点 **✓确认并导出** → 核对弹出的下单指令（卖出标黄、在前）→ 选「确认并导出」（单文件多 sheet）或「按产品分别导出」→ 把生成的 Excel 发给券商。

> 调仓输入全部在界面上直接录入/编辑，不需要也没有 Excel 导入步骤；只有最终的下单指令是导出成 Excel 发券商。

---

## 三、计算规则

- **组金额按方式分到每只**：
  - `等金额`：组金额 ÷ 股票数，每只均分。
  - `当前持仓比例`：按各股**当前持仓市值**占比分配（组内未持仓的股票占比为 0，建仓请用等金额）。
- **股数** = 分得金额 ÷ 人民币单价，取整到「手」：A股/ETF 100 股；港股默认 100 股；科创板（688）最小买入 200 股。
- **卖出**不超过当前持仓；接近清仓时一次性全卖（含零股）。手填「调整」超过持仓会自动封顶并提示。
- **最终下单数量 = 调整(若填) 否则 股数**。
- 港股的「公允价格」是港币、「持仓市值」是人民币，工具用 `持仓市值/数量` 反推人民币单价，自动处理汇率；价格列展示的就是人民币单价。
- 新增（不在任何产品里的）标的需手填价格。

---

## 四、给开发/IT：怎么打包

> PyInstaller 不能跨系统打包：Windows 版要在 Windows 上打，Mac 版要在 Mac 上打。

### macOS（.app）
在 Mac 上双击 **`build/build_mac.command`**（或终端 `bash build/build_mac.command`），产物为 `dist/调仓工具.app`，双击即可运行。
- 未做苹果签名/公证，首次打开若被拦截：在「访达」里右键应用→打开，或到「系统设置→隐私与安全性」点「仍要打开」。
- 产物为构建机的 CPU 架构（Apple Silicon 上打出的是 arm64）。要给 Intel Mac 用，请在 Intel 机器上打包。

### Windows（.exe 绿色版 + 安装包）
- **本地一键**：在装有 Python 3.10+ 的 Windows 电脑上双击 **`build/build_windows.bat`**，产出：
  - `dist\调仓工具.exe` —— 绿色版，双击即用，无需安装；
  - `dist\调仓工具_安装包_v1.1.1.exe` —— 正式安装包（开始菜单/桌面快捷方式/卸载程序），需先装 [Inno Setup 6](https://jrsoftware.org/isdl.php)，bat 会自动调用它打包。
- **GitHub Actions（无需本地 Windows）**：推到 GitHub 后，到 **Actions** 页面下载产物 `调仓工具-windows-绿色版` 与 `调仓工具-windows-安装包`（CI 会自动装 Inno Setup 并打安装包）；打 `v*` 标签则自动发到 Release。

安装包脚本：`build/installer.iss`（Inno Setup）。手动打安装包：`ISCC build\installer.iss`（exe 需已在 `dist\`）。

### 命令行手动打包（两平台通用）
```bash
pip install -r requirements.txt pyinstaller
pyinstaller build/调仓工具.spec --noconfirm --clean
```

---

## 五、开发与测试

```bash
pip install -r requirements.txt pytest
pytest -q              # 运行单元测试
python app.py          # 本地启动界面
python app.py --selftest   # 无界面自检（CI/打包后冒烟）
```

源码模式快速运行（Windows）：双击 `build/运行(源码模式).bat`。

### 目录结构
```
portfolio_adjust/
├── app.py                      # 桌面界面（PySide6，三级树录入）
├── rebalancer/                 # 核心逻辑（与界面解耦，可单独测试）
│   ├── config.py               # 手数/汇率/列名/方式/更新源 等可调参数
│   ├── models.py               # 数据模型
│   ├── reader.py               # 读取产品监控 Excel（容错表头/参差行/日期）
│   ├── pools.py                # 当前产品 / 全部产品 证券池
│   ├── engine.py               # 交易组 -> 下单指令 计算引擎
│   └── excel_io.py             # 写券商下单指令 Excel
├── tests/                      # pytest 测试
├── build/                      # 构建相关（脚本 + 配置）
│   ├── 调仓工具.spec            #   PyInstaller 配置
│   ├── installer.iss           #   Inno Setup 安装包脚本
│   ├── build_windows.bat       #   Windows 一键打包（exe + 安装包）
│   ├── build_mac.command       #   macOS 一键打包（.app）
│   └── 运行(源码模式).bat       #   源码直接运行（开发用）
├── .github/workflows/build-windows.yml   # CI：Win/Mac 自动构建
├── requirements.txt
├── README.md
├── product/                    # 放产品监控 Excel（已 .gitignore，不入库）
└── doc/                        # 参考文档/规格/审查报告（已 .gitignore）
dist/                           # 构建产物 exe/app/安装包（已 .gitignore）
```

### 可调参数（`rebalancer/config.py`）
- `DEFAULT_LOT` / `HK_DEFAULT_LOT` / `STAR_BOARD_MIN_BUY` / `LOT_OVERRIDES`：交易手数规则。
- `FX_FALLBACK`：外币兜底汇率（默认优先用持仓反推的隐含汇率）。
- `METHODS` / `DIRECTIONS`：方式、方向的别名识别。
