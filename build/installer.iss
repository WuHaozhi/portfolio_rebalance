; Inno Setup 脚本：把 PyInstaller 产物 dist\portfolio_rebalance.exe 打成 Windows 安装包
; 用法（在 Windows 上，需先装 Inno Setup 6 https://jrsoftware.org/isdl.php）：
;   1) 先 pyinstaller build\调仓工具.spec --noconfirm --clean  生成 dist\portfolio_rebalance.exe
;   2) ISCC build\installer.iss
;   产物：dist\portfolio_rebalance_setup_v1.1.1.exe（双击安装，带开始菜单/桌面快捷方式/卸载）
; 注：文件名用 ASCII（GitHub Release 会吞掉中文附件名）；安装后的程序名/快捷方式仍是中文「调仓工具」。

#define MyAppName "调仓工具"
#define MyAppVersion "1.1.1"
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

[Languages]
; 用 Inno Setup 自带的英文 Default.isl（向导是英文，软件本身仍是中文）；
; 如需中文向导，下载 ChineseSimplified.isl 放进 Inno Setup\Languages 后改成它。
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
