#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "Usatopolosato"
#endif
#ifndef AppId
  #define AppId "{{9DCCFFED-8EE9-46B9-BDE0-3CCBAFC08C91}"
#endif

[Setup]
AppId={#AppId}
AppName=САПР BAR
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppPublisher}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Установка САПР BAR
VersionInfoProductName=САПР BAR
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\SAPR BAR
DefaultGroupName=САПР BAR
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern dynamic
WizardSizePercent=110,110
SetupIconFile=..\src\sapr\resources\icons\app.ico
UninstallDisplayIcon={app}\SAPR BAR.exe
OutputDir=..\dist
OutputBaseFilename=SAPR-BAR-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
UninstallDisplayName=САПР BAR

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
SetupWindowTitle=Установка - %1

[Types]
Name: "full"; Description: "Приложение и примеры задач"
Name: "compact"; Description: "Только приложение"
Name: "custom"; Description: "Выборочная установка"; Flags: iscustom

[Components]
Name: "application"; Description: "САПР BAR"; Types: full compact custom; Flags: fixed
Name: "examples"; Description: "11 примеров задач в папке Документы"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "..\dist\SAPR BAR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: application
Source: "..\build\examples\*"; DestDir: "{userdocs}\САПР BAR\Примеры"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs; Components: examples
Source: "..\docs\Руководство.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: application

[Icons]
Name: "{group}\САПР BAR"; Filename: "{app}\SAPR BAR.exe"; AppUserModelID: "Usatopolosato.SaprBar"
Name: "{group}\Руководство"; Filename: "{app}\Руководство.txt"
Name: "{group}\Удалить САПР BAR"; Filename: "{uninstallexe}"
Name: "{autodesktop}\САПР BAR"; Filename: "{app}\SAPR BAR.exe"; Tasks: desktopicon; AppUserModelID: "Usatopolosato.SaprBar"

[Run]
Filename: "{app}\SAPR BAR.exe"; Description: "Запустить САПР BAR"; Flags: nowait postinstall skipifsilent
