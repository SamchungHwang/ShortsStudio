@echo off
rem ASS console launcher. Activates the "ass" conda environment, then opens the console.
cd /d "%~dp0"
set "CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=conda"
call "%CONDA_BAT%" activate ass
if errorlevel 1 (
  echo.
  echo Could not activate the "ass" conda environment.
  echo Create it first:  conda create -n ass python=3.13 -y
  echo Then install:     conda activate ass ^&^& pip install -e ".[dev]"
  pause
  exit /b 1
)
python -m ass console
if errorlevel 1 pause
