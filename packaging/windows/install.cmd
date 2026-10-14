@echo off
rem Installs or updates Paperlift for you (no administrator rights needed). Double-click it.
title Paperlift installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\packaging\windows\install.ps1" -Source "%~dp0app"
