@echo off
REM Double-clickable wrapper: exports the deck's slides to PNG so the layout can
REM be eyeballed. Windows opens .ps1 in an editor by default, so this .cmd is the
REM thing to double-click; it also keeps the window open to read the result.
setlocal
set SCRIPT=%~dp0export-slides.ps1
echo Exporting slides via PowerPoint...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
echo ---------------------------------------------------------------
echo Done. Press any key to close.
pause >nul
