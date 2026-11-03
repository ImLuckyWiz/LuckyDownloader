; Inno Setup script for LuckyDownloader (Windows installer)
; Build with:  iscc /DAppVersion=1.0 installer.iss   (run after Nuitka)
; Pre-release versions (containing '-', e.g. v0.8.0-beta.1) get their own AppId and install folder
; so they can be installed side-by-side without overwriting a stable LuckyDownloader installation.
#ifndef AppVersion
  #define AppVersion "1.0"
#endif

#if Pos("-", AppVersion) > 0
  #define EffectiveAppId "{{9C4A8D2E-7B1F-4E63-8A5D-3F2E1C9B7D44}}"
  #define EffectiveAppName "LuckyDownloader (Beta)"
  #define EffectiveDirName "LuckyDownloader-Beta"
#else
  #define EffectiveAppId "{{6E2B6B0C-3F0D-4C57-9B6A-1A7C2E0D4F11}}"
  #define EffectiveAppName "LuckyDownloader"
  #define EffectiveDirName "LuckyDownloader"
#endif

[Setup]
AppId={#EffectiveAppId}
AppName={#EffectiveAppName}
AppVersion={#AppVersion}
AppPublisher=LuckyDownloader
; Per-user install: no admin rights needed, goes to %LOCALAPPDATA%\Programs\LuckyDownloader (or LuckyDownloader-Beta)
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#EffectiveDirName}
DefaultGroupName={#EffectiveAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=LuckyDownloader-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LuckyDownloader.exe
SetupIconFile=assets\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
en.CreateDesktopIcon=Create a desktop shortcut
es.CreateDesktopIcon=Crear un acceso directo en el escritorio
en.ShortcutsGroup=Shortcuts:
es.ShortcutsGroup=Accesos directos:
en.WebLinksDesc=Open luckydownloader:// links from web pages with LuckyDownloader
es.WebLinksDesc=Abrir enlaces luckydownloader:// desde páginas web con LuckyDownloader
en.LinksGroup=Links:
es.LinksGroup=Enlaces:
en.LaunchApp=Launch {#EffectiveAppName}
es.LaunchApp=Ejecutar {#EffectiveAppName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:ShortcutsGroup}"
Name: "weblinks"; Description: "{cm:WebLinksDesc}"; GroupDescription: "{cm:LinksGroup}"

[Files]
Source: "dist\LuckyDownloader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

; Web pages can offer luckydownloader:// or luckytwitch:// links. Per user (HKCU), so no admin rights; the app writes the same
; entries from Options > Tools > Links from web pages (see weblink.py: the command must stay identical).
[Registry]
Root: HKCU; Subkey: "Software\Classes\luckydownloader"; ValueType: string; ValueName: ""; ValueData: "URL:LuckyDownloader Link"; Flags: uninsdeletekey; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckydownloader"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckydownloader\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LuckyDownloader.exe,0"; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckydownloader\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LuckyDownloader.exe"" ""%1"""; Tasks: weblinks

Root: HKCU; Subkey: "Software\Classes\luckytwitch"; ValueType: string; ValueName: ""; ValueData: "URL:LuckyDownloader Link"; Flags: uninsdeletekey; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckytwitch"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckytwitch\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LuckyDownloader.exe,0"; Tasks: weblinks
Root: HKCU; Subkey: "Software\Classes\luckytwitch\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LuckyDownloader.exe"" ""%1"""; Tasks: weblinks

[Icons]
Name: "{autoprograms}\{#EffectiveAppName}"; Filename: "{app}\LuckyDownloader.exe"
Name: "{autodesktop}\{#EffectiveAppName}"; Filename: "{app}\LuckyDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LuckyDownloader.exe"; Description: "Launch {#EffectiveAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\LuckyDownloader.exe"; Flags: nowait; Check: IsRelaunch

[Code]
function IsRelaunch(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function ExtractExePath(Cmd: String): String;
var
  S: String;
  P: Integer;
begin
  S := Trim(Cmd);
  if (Length(S) > 0) and (S[1] = '"') then
  begin
    Delete(S, 1, 1);
    P := Pos('"', S);
    if P > 0 then
      Result := Copy(S, 1, P - 1)
    else
      Result := S;
  end
  else
  begin
    P := Pos(' ', S);
    if P > 0 then
      Result := Copy(S, 1, P - 1)
    else
      Result := S;
  end;
  Result := RemoveQuotes(Trim(Result));
end;

procedure RunUninstaller(UninstExe: String);
var
  ResultCode: Integer;
begin
  if (UninstExe <> '') and FileExists(UninstExe) then
  begin
    Exec(UninstExe, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CheckAndUninstallRegistryKey(RootKey: Integer; const SubKeyName: String);
var
  FullSubKey: String;
  DisplayName, InstallLoc, Cmd, ExePath: String;
begin
  FullSubKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + SubKeyName;
  DisplayName := '';
  InstallLoc := '';
  Cmd := '';

  RegQueryStringValue(RootKey, FullSubKey, 'DisplayName', DisplayName);
  RegQueryStringValue(RootKey, FullSubKey, 'InstallLocation', InstallLoc);
  if InstallLoc = '' then
    RegQueryStringValue(RootKey, FullSubKey, 'Inno Setup: App Path', InstallLoc);

  // Must match LuckyTwitch and never match LuckyDownloader
  if (Pos('LuckyTwitch', DisplayName) > 0) or (Pos('LuckyTwitch', InstallLoc) > 0) or
     (SubKeyName = '{6E2B6B0C-3F0D-4C57-9B6A-1A7C2E0D4F11}_is1') or
     (SubKeyName = '{9C4A8D2E-7B1F-4E63-8A5D-3F2E1C9B7D44}_is1') then
  begin
    if (Pos('LuckyDownloader', DisplayName) = 0) and (Pos('LuckyDownloader', InstallLoc) = 0) then
    begin
      if RegQueryStringValue(RootKey, FullSubKey, 'QuietUninstallString', Cmd) or
         RegQueryStringValue(RootKey, FullSubKey, 'UninstallString', Cmd) then
      begin
        ExePath := ExtractExePath(Cmd);
        RunUninstaller(ExePath);
      end;
    end;
  end;
end;

procedure ScanAndUninstallRoot(RootKey: Integer);
var
  Names: TArrayOfString;
  I: Integer;
begin
  // Check known GUIDs directly
  CheckAndUninstallRegistryKey(RootKey, '{6E2B6B0C-3F0D-4C57-9B6A-1A7C2E0D4F11}_is1');
  CheckAndUninstallRegistryKey(RootKey, '{9C4A8D2E-7B1F-4E63-8A5D-3F2E1C9B7D44}_is1');

  // Enumerate all uninstall subkeys to catch any renamed or custom installs
  if RegGetSubkeyNames(RootKey, 'Software\Microsoft\Windows\CurrentVersion\Uninstall', Names) then
  begin
    for I := 0 to GetArrayLength(Names) - 1 do
    begin
      CheckAndUninstallRegistryKey(RootKey, Names[I]);
    end;
  end;
end;

procedure CheckAndCleanFolder(const FolderPath: String);
var
  UninstExe: String;
begin
  if DirExists(FolderPath) then
  begin
    UninstExe := FolderPath + '\unins000.exe';
    if FileExists(UninstExe) then
      RunUninstaller(UninstExe);
    // If folder still exists and contains LuckyTwitch files, clean it up
    if DirExists(FolderPath) and FileExists(FolderPath + '\LuckyTwitch.exe') then
      DelTree(FolderPath, True, True, True);
  end;
end;

procedure CleanLegacyShortcuts();
begin
  DeleteFile(ExpandConstant('{autodesktop}\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{autodesktop}\LuckyTwitch (Beta).lnk'));
  DeleteFile(ExpandConstant('{userdesktop}\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{commondesktop}\LuckyTwitch.lnk'));

  DeleteFile(ExpandConstant('{autoprograms}\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{autoprograms}\LuckyTwitch (Beta).lnk'));
  DeleteFile(ExpandConstant('{userprograms}\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{commonprograms}\LuckyTwitch.lnk'));

  DeleteFile(ExpandConstant('{autoprograms}\LuckyTwitch\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{autoprograms}\LuckyTwitch\Uninstall LuckyTwitch.lnk'));
  RemoveDir(ExpandConstant('{autoprograms}\LuckyTwitch'));

  DeleteFile(ExpandConstant('{userprograms}\LuckyTwitch\LuckyTwitch.lnk'));
  DeleteFile(ExpandConstant('{userprograms}\LuckyTwitch\Uninstall LuckyTwitch.lnk'));
  RemoveDir(ExpandConstant('{userprograms}\LuckyTwitch'));
end;

procedure UninstallLegacyLuckyTwitch();
begin
  // 1. Scan HKCU and HKLM
  ScanAndUninstallRoot(HKCU);
  ScanAndUninstallRoot(HKLM);
  if IsWin64 then
  begin
    ScanAndUninstallRoot(HKLM32);
  end;

  // 2. Check default install folders
  CheckAndCleanFolder(ExpandConstant('{autopf}\LuckyTwitch'));
  CheckAndCleanFolder(ExpandConstant('{localappdata}\Programs\LuckyTwitch'));
  CheckAndCleanFolder(ExpandConstant('{autopf}\LuckyTwitch-Beta'));
  CheckAndCleanFolder(ExpandConstant('{localappdata}\Programs\LuckyTwitch-Beta'));

  // 3. Remove legacy desktop and start menu shortcuts
  CleanLegacyShortcuts();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  UninstallLegacyLuckyTwitch();
end;
