; Inno Setup 脚本：把 PyInstaller 产物 dist\portfolio_rebalance.exe 打成 Windows 安装包
; 用法（在 Windows 上，需先装 Inno Setup 6 https://jrsoftware.org/isdl.php）：
;   1) 先 pyinstaller build\调仓工具.spec --noconfirm --clean  生成 dist\portfolio_rebalance.exe
;   2) ISCC build\installer.iss
;   产物：dist\portfolio_rebalance_setup_v1.1.4.exe（双击安装，带开始菜单/桌面快捷方式/卸载）
; 注：文件名用 ASCII（GitHub Release 会吞掉中文附件名）；安装后的程序名/快捷方式仍是中文「调仓工具」。

#define MyAppName "调仓工具"
#define MyAppVersion "1.1.4"
#define MyAppPublisher "Portfolio Adjust"
#define MyAppExeName "portfolio_rebalance.exe"

[Setup]
AppId={{B7C3A1E2-9D4F-4A6B-8C12-PORTFOLIOADJUST}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=portfolio_rebalance_setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
; 安装到 Program Files 需要管理员；如想免管理员装到用户目录，把上面 DefaultDirName 改成 {userpf}\{#MyAppName} 并设 PrivilegesRequired=lowest
PrivilegesRequired=admin
; 自动更新时静默升级会用到：升级时自动关闭正在运行的旧程序（配置/新增证券存在注册表与用户目录，不在安装目录，不受影响）
CloseApplications=yes
RestartApplications=no

[Languages]
; 用 Inno Setup 自带的英文 Default.isl（向导是英文，软件本身仍是中文）；
; 如需中文向导，下载 ChineseSimplified.isl 放进 Inno Setup\Languages 后改成它。
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[InstallDelete]
; 清理 v1.1.1 旧文件名 exe（exe 已由「调仓工具.exe」改名为 portfolio_rebalance.exe），
; 否则原地升级后安装目录会同时残留新旧两个程序，看起来像"没覆盖"。
Type: files; Name: "{app}\调仓工具.exe"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 装完自动启动（去掉 skipifsilent，使自动更新的静默安装也会重新拉起程序，做到"无感"重开）；
; runasoriginaluser：以普通用户身份重开，而非继承安装器的管理员权限。
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall runasoriginaluser
