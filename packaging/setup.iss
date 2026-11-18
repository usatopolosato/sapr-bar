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
UninstallAppFullTitle=Удаление %1

[Types]
Name: "full"; Description: "Приложение и задачи в единичных величинах"
Name: "compact"; Description: "Только приложение"
Name: "custom"; Description: "Выборочная установка"; Flags: iscustom

[Components]
Name: "application"; Description: "САПР BAR"; Types: full compact custom; Flags: fixed
Name: "examples"; Description: "Сохранить 12 задач в единичных величинах в Документы\САПР BAR\Примеры"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "..\dist\SAPR BAR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: application
Source: "..\build\examples\*"; DestDir: "{userdocs}\САПР BAR\Примеры"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs; Components: examples
Source: "..\docs\Руководство.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: application

[Icons]
Name: "{group}\САПР BAR"; Filename: "{app}\SAPR BAR.exe"; AppUserModelID: "Usatopolosato.SaprBar"
Name: "{group}\Руководство"; Filename: "{app}\Руководство.txt"
Name: "{group}\Учебные задачи"; Filename: "{userdocs}\САПР BAR\Примеры"; Components: examples
Name: "{group}\Удалить САПР BAR"; Filename: "{uninstallexe}"
Name: "{autodesktop}\САПР BAR"; Filename: "{app}\SAPR BAR.exe"; Tasks: desktopicon; AppUserModelID: "Usatopolosato.SaprBar"

[Run]
Filename: "{app}\SAPR BAR.exe"; Description: "Запустить САПР BAR"; Flags: nowait postinstall skipifsilent

[Code]
var
  UninstallPath: String;
  UninstallStarted: Boolean;

procedure RemoveButtonClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if not FileExists(UninstallPath) then begin
    MsgBox('Файл удаления не найден. Нажмите «Далее», чтобы переустановить программу и восстановить его.', mbError, MB_OK);
    Exit;
  end;
  if ExecAsOriginalUser(UninstallPath, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then begin
    UninstallStarted := True;
    WizardForm.Close;
  end else
    MsgBox('Не удалось запустить удаление. ' + SysErrorMessage(ErrorCode), mbError, MB_OK);
end;

procedure InitializeWizard;
var
  RegistryKey: String;
  RemoveButton: TNewButton;
begin
  if WizardSilent then Exit;
  RegistryKey := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}_is1');
  if not RegQueryStringValue(HKCU, RegistryKey, 'UninstallString', UninstallPath) then Exit;
  UninstallPath := RemoveQuotes(UninstallPath);
  WizardForm.WelcomeLabel1.Caption := 'САПР BAR уже установлена';
  WizardForm.WelcomeLabel2.Caption := 'Для повторной установки нажмите «Далее». При удалении учебные задачи сохранятся в Документах.';
  WizardForm.WelcomeLabel2.AdjustHeight;
  RemoveButton := TNewButton.Create(WizardForm);
  RemoveButton.Parent := WizardForm.WelcomePage;
  RemoveButton.Caption := 'Удалить программу';
  RemoveButton.SetBounds(WizardForm.WelcomeLabel2.Left,
    WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + ScaleY(12),
    ScaleX(150), WizardForm.NextButton.Height);
  RemoveButton.OnClick := @RemoveButtonClick;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
    WizardForm.ActiveControl := WizardForm.NextButton;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if UninstallStarted then Confirm := False;
end;
