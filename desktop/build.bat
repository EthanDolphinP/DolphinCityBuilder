@echo off
rem Builds DolphinCityBuilder.exe with the C# compiler that comes with Windows.
rem Nothing needs installing. Run make_icon.py first if game.ico is missing.
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
"%CSC%" /nologo /target:winexe /optimize+ /win32icon:game.ico /out:DolphinCityBuilder.exe /reference:System.Windows.Forms.dll Launcher.cs
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
echo Built DolphinCityBuilder.exe
