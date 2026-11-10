@echo off
chcp 65001 >nul
title Usta kurulumu
echo.
echo  Usta kuruluyor. Bu pencereyi kapatma, birkaç dakika sürebilir.
echo  Ekranda bir şey yazmasa da çalışıyor.
echo.

rem Python'u bul: once "python", PATH'e eklenmemisse "py" baslaticisi
set PY=python
python --version >nul 2>nul
if not errorlevel 1 goto kur
set PY=py -3
py -3 --version >nul 2>nul
if not errorlevel 1 goto kur

echo  Bilgisayarında Python bulunamadı. Usta'nın çalışması için Python gerekiyor.
echo  Açılan sayfadan Python'u indir ve kur. Kurulumda en alttaki
echo  "Add python.exe to PATH" kutusunu İŞARETLE. Sonra bu dosyaya tekrar çift tıkla.
start "" https://www.python.org/downloads/
goto bitti_hata

:kur
%PY% -m pip install --upgrade --quiet --disable-pip-version-check --no-warn-script-location usta
if errorlevel 1 (
  echo.
  echo  Kurulum başarısız oldu. İnternet bağlantını kontrol edip tekrar dene.
  echo  Yine olmazsa, bu penceredeki yazıların fotoğrafını çekip bize gönder.
  goto bitti_hata
)

%PY% -m usta --kisayol >nul
if errorlevel 1 (
  echo  Masaüstü simgesi konulamadı ama Usta kuruldu. Elle açmak için: %PY% -m usta
  goto bitti_hata
)

for /f "delims=" %%D in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set DESK=%%D
echo  Hazır! Masaüstünde "Usta" simgesi oluştu. Şimdi açılıyor...
start "" "%DESK%\Usta.lnk"
echo.
echo  Bundan sonra Usta'yı açmak için masaüstündeki "Usta" simgesine çift tıkla.
echo.
echo  Bu pencereyi kapatmak için bir tuşa bas.
pause >nul
exit /b 0

:bitti_hata
echo.
echo  Bu pencereyi kapatmak için bir tuşa bas.
pause >nul
exit /b 1
