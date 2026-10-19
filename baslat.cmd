@echo off
rem ATLAS QUANT TERMINAL - tek tikla baslatma.
rem Ilk calistirmada kurulumu yapar, sonra API ve web sunucularini ayri pencerelerde acar ve tarayiciyi baslatir.
rem Web hizli modda acilir: kod degistiyse bir kez derlenir (~1 dk), sonra sayfalar aninda yuklenir. Gelistirme modu: gelistir.cmd
rem Kapatmak icin "ATLAS API" ve "ATLAS WEB" pencerelerini kapatin.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%apps\api\.venv\Scripts\python.exe"
set "ATLAS_LOG_JSON=false"

echo.
echo  ATLAS QUANT TERMINAL baslatiliyor...
echo.

rem --- API: ilk kurulum (yalnizca bir kez) ---
cd /d "%ROOT%apps\api"
if not exist "%PY%" (
  echo [1/4] Python ortami kuruluyor - ilk seferde birkac dakika surebilir...
  python -m venv .venv || goto :hata
  "%PY%" -m pip install --disable-pip-version-check -q -e ".[dev]" || goto :hata
  if not exist "%ROOT%apps\api\var" mkdir "%ROOT%apps\api\var"
  copy /y pyproject.toml "%ROOT%apps\api\var\.deps-stamp" >nul
)
rem Python bagimliliklari degistiyse - pyproject.toml - yeniden kur.
fc /b pyproject.toml "%ROOT%apps\api\var\.deps-stamp" >nul 2>&1 || (
  echo      Python bagimliliklari guncelleniyor...
  "%PY%" -m pip install --disable-pip-version-check -q -e ".[dev]" || goto :hata
  copy /y pyproject.toml "%ROOT%apps\api\var\.deps-stamp" >nul
)

rem --- Veritabani: tablolar her seferinde guncellenir, demo verisi yalnizca ilk seferde yuklenir ---
echo [2/4] Veritabani kontrol ediliyor...
if not exist "%ROOT%apps\api\var" mkdir "%ROOT%apps\api\var"
rem Guncellemeden once yedek alinir; son 7 yedek apps\api\var\backups altinda saklanir. Yedek alinamazsa uyarir, devam eder.
if exist "%ROOT%apps\api\var\atlas_dev.db" (
  "%PY%" -m app.workers.cli backup --keep 7 --quiet || echo      UYARI: yedek alinamadi, devam ediliyor.
)
"%PY%" -m alembic upgrade head || goto :hata
if not exist "%ROOT%apps\api\var\.seeded" (
  "%PY%" -m app.workers.cli ingest >nul || goto :hata
  echo seeded> "%ROOT%apps\api\var\.seeded"
)

rem --- Web: ilk kurulum (yalnizca bir kez) ---
cd /d "%ROOT%apps\web"
if not exist "node_modules" (
  echo [3/4] Web bagimliliklari kuruluyor - ilk seferde birkac dakika surebilir...
  call npm.cmd ci || goto :hata
  copy /y package-lock.json "node_modules\.atlas-lock" >nul
)
rem Web bagimliliklari degistiyse - package-lock.json - yeniden kur. Isaret dosyasi yoksa mevcut kurulum gecerli sayilir.
if not exist "node_modules\.atlas-lock" copy /y package-lock.json "node_modules\.atlas-lock" >nul
fc /b package-lock.json "node_modules\.atlas-lock" >nul 2>&1 || (
  echo      Web bagimliliklari guncelleniyor...
  call npm.cmd ci || goto :hata
  copy /y package-lock.json "node_modules\.atlas-lock" >nul
)

rem --- Sunuculari baslat (zaten calisiyorsa tekrar baslatma) ---
echo [4/4] Sunucular baslatiliyor...
curl.exe -s -o nul http://127.0.0.1:8000/health && (echo      API zaten calisiyor.) || start "ATLAS API" /d "%ROOT%apps\api" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

rem Web iki modda calisir: hizli mod (varsayilan, onceden derlenmis) ve gelistirme modu (gelistir.cmd, kod degisikligini aninda gosterir).
set "WEBMODE=hizli"
if /i "%~1"=="dev" set "WEBMODE=gelistirme"
set "NEXT_DIST_DIR=.next-prod"
if /i "%~1"=="dev" set "NEXT_DIST_DIR="
set "RUNNING="
if exist ".atlas-mode" set /p RUNNING=<".atlas-mode"
curl.exe -s -o nul http://127.0.0.1:3000/dashboard || goto :web_baslat
if not defined RUNNING set "RUNNING=gelistirme"
if /i "%RUNNING%"=="%WEBMODE%" (
  echo      Web zaten calisiyor - %WEBMODE% modu.
  goto :web_hazir
)
echo.
echo  Web su an %RUNNING% modunda calisiyor. %WEBMODE% moduna gecmek icin
echo  "ATLAS WEB" penceresini kapatip bu dosyayi tekrar calistirin.
echo.
goto :web_hazir

:web_baslat
if /i "%WEBMODE%"=="hizli" (
  node scripts\build-if-changed.mjs || goto :hata
  start "ATLAS WEB" /d "%ROOT%apps\web" cmd /k "node node_modules\next\dist\bin\next start -p 3000"
) else (
  start "ATLAS WEB" /d "%ROOT%apps\web" cmd /k "npm.cmd run dev"
)
echo %WEBMODE%> ".atlas-mode"

:web_hazir

rem --- Web hazir olana kadar bekle (en fazla ~2 dakika), sonra tarayiciyi ac ---
set /a TRIES=0
:bekle
curl.exe -s -o nul http://127.0.0.1:3000/dashboard && goto :hazir
set /a TRIES+=1
if %TRIES% geq 60 goto :zaman_asimi
timeout /t 2 /nobreak >nul
goto :bekle

:hazir
start "" http://localhost:3000/dashboard
echo.
echo  Hazir: http://localhost:3000
echo  Kapatmak icin "ATLAS API" ve "ATLAS WEB" pencerelerini kapatin.
timeout /t 5 >nul
exit /b 0

:zaman_asimi
echo.
echo  Web sunucusu 2 dakikada yanit vermedi. "ATLAS WEB" penceresindeki hataya bakin.
pause
exit /b 1

:hata
echo.
echo  HATA: Yukaridaki adim basarisiz oldu. Bu pencerenin metnini kopyalayip paylasin.
pause
exit /b 1
