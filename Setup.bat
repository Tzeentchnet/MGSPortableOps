@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 goto directory_error

where py >nul 2>nul
if errorlevel 1 goto python_command
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto python_command
py -3 tools\mgspo\manager.py %*
set "manager_exit=%errorlevel%"
goto finished

:python_command
where python >nul 2>nul
if errorlevel 1 goto python_missing
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto python_version
python tools\mgspo\manager.py %*
set "manager_exit=%errorlevel%"
goto finished

:python_missing
echo ERROR: Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/ and try again.
set "manager_exit=1"
goto finished

:python_version
echo ERROR: Python 3.11 or newer is required.
set "manager_exit=1"
goto finished

:directory_error
echo ERROR: Could not open the repository directory.
set "manager_exit=1"
goto report_error

:finished
popd

:report_error
if "%manager_exit%"=="0" exit /b 0
echo.
echo Setup manager exited with code %manager_exit%.
pause
exit /b %manager_exit%
