@echo off
rem Installs or updates DocuFlow for you (no administrator rights needed). Double-click it.
title DocuFlow installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\packaging\windows\install.ps1" -Source "%~dp0app"
