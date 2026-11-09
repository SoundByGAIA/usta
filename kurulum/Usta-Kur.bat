@echo off
chcp 65001 >nul
title Usta kurulumu
echo.
echo  Usta kuruluyor. Bu pencereyi kapatma, birkac dakika surebilir.
echo.

python --version >nul 2>nul
if errorlevel 1 (
  echo  Bilgisayarinda Python bulunamadi. Usta'nin calismasi icin Python gerekiyor.
  echo  Acilan sayfadan Python'u indir ve kur. Kurulumda en alttaki
  echo  "Add python.exe to PATH" kutusunu ISARETLE. Sonra bu dosyayi tekrar cift tikla.
  start "" https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

python -m pip install --upgrade usta
if errorlevel 1 (
  echo.
  echo  Kurulum basarisiz oldu. Internet baglantini kontrol edip tekrar dene.
  echo  Yine olmazsa, bu penceredeki yazilarin fotografini cekip bize gonder.
  pause
  exit /b 1
)

python -m usta --kisayol
if errorlevel 1 (
  echo  Masaustu simgesi konulamadi ama Usta kuruldu. Elle acmak icin: python -m usta
  pause
  exit /b 1
)

for /f "delims=" %%D in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set DESK=%%D
echo.
echo  Hazir! Masaustunde "Usta" simgesi olustu. Simdi aciliyor...
start "" "%DESK%\Usta.lnk"
echo.
echo  Bundan sonra Usta'yi acmak icin masaustundeki "Usta" simgesine cift tikla.
echo.
pause
