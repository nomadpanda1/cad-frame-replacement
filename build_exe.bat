@echo off
REM ===========================================================================
REM  打包成 exe（免装 Python 的同事用）
REM  注意：tkinter 在标准 managed venv(3.13) 里没有，必须用自带 tcl/tk 的
REM        Python 3.14 来打包，否则打出来的 exe 缺 tkinter 起不来。
REM  用法：双击本文件，或在 cmd 里执行。
REM ===========================================================================
setlocal
REM —— 改成你本机的 Python 3.14 路径（需已 pip install ezdxf pyinstaller）——
set PY=C:\Python314\python.exe

if not exist "%PY%" (
  echo [错误] 找不到 %PY%，请修改本脚本顶部的 PY 路径为你的 Python 3.14。
  pause
  exit /b 1
)

REM 清理旧构建
if exist build rmdir /s /q build
if exist dist\cad-frame-gui.exe del /q dist\cad-frame-gui.exe

"%PY%" -m PyInstaller --noconfirm --onefile --windowed --name cad-frame-gui ^
  --collect-all ezdxf --collect-all lib --collect-all win32com ^
  --add-data "templates;templates" ^
  gui_app.py

echo.
if exist dist\cad-frame-gui.exe (
  echo [完成] 产物在 dist\cad-frame-gui.exe
) else (
  echo [失败] 未生成 exe，请检查上面的报错。
)
pause
