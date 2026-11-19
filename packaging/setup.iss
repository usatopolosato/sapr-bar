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
AppName=UPS
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppPublisher}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Установка UPS
VersionInfoProductName=UPS
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\UPS
DefaultGroupName=UPS
UsePreviousGroup=no
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
UninstallDisplayIcon={app}\UPS.exe
OutputDir=..\dist
OutputBaseFilename=UPS-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
UninstallDisplayName=UPS

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
Name: "application"; Description: "UPS"; Types: full compact custom; Flags: fixed
Name: "examples"; Description: "Сохранить 12 задач в единичных величинах в Документы\UPS\JSON"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "..\dist\UPS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: application
Source: "..\build\examples\JSON\*.json"; DestDir: "{userdocs}\UPS\JSON"; Flags: onlyifdoesntexist uninsneveruninstall; Components: examples
Source: "..\docs\Руководство.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: application

[Icons]
Name: "{group}\UPS"; Filename: "{app}\UPS.exe"; AppUserModelID: "Usatopolosato.UPS"
Name: "{group}\Руководство"; Filename: "{app}\Руководство.txt"
Name: "{group}\Учебные задачи"; Filename: "{userdocs}\UPS\JSON"; Components: examples
Name: "{group}\Удалить UPS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\UPS"; Filename: "{app}\UPS.exe"; Tasks: desktopicon; AppUserModelID: "Usatopolosato.UPS"

[InstallDelete]
Type: files; Name: "{app}\SAPR BAR.exe"
Type: files; Name: "{userprograms}\САПР BAR\САПР BAR.lnk"
Type: files; Name: "{userprograms}\САПР BAR\Руководство.lnk"
Type: files; Name: "{userprograms}\САПР BAR\Учебные задачи.lnk"
Type: files; Name: "{userprograms}\САПР BAR\Удалить САПР BAR.lnk"
Type: dirifempty; Name: "{userprograms}\САПР BAR"
Type: files; Name: "{autodesktop}\САПР BAR.lnk"

[Run]
Filename: "{app}\UPS.exe"; Description: "Запустить UPS"; Flags: nowait postinstall skipifsilent

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
  WizardForm.WelcomeLabel1.Caption := 'UPS уже установлена';
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
