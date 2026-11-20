; Usta'nın Windows kurulumu: PyInstaller'ın dist\Usta klasörünü kullanıcının kendi klasörüne kurar.
; Yönetici izni istemez; Başlat menüsüne ve isterse masaüstüne simge koyar, Programlar listesinden kaldırılır.
; Derleme: iscc /DVersion=0.9.1 kurulum\windows\usta.iss  (depo kökünden)

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6F3B2C1E-8A4D-4E57-9C1B-2D7A5E0F4B93}
AppName=Usta
AppVersion={#Version}
AppPublisher=SoundByGAIA
AppPublisherURL=https://github.com/SoundByGAIA/usta
DefaultDirName={localappdata}\Programs\Usta
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Usta-Kurulum-{#Version}
SetupIconFile=..\..\src\usta\web\usta.ico
UninstallDisplayIcon={app}\Usta.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; açık Usta güncelleme sırasında kapatılır, yoksa dosyalar kilitli kalır
CloseApplications=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "masaustu"; Description: "Masaüstüne Usta simgesi koy"

[Files]
Source: "..\..\dist\Usta\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Usta"; Filename: "{app}\Usta.exe"
Name: "{autodesktop}\Usta"; Filename: "{app}\Usta.exe"; Tasks: masaustu

[Run]
Filename: "{app}\Usta.exe"; Description: "Usta'yı şimdi aç"; Flags: nowait postinstall skipifsilent
