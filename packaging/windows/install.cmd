@echo off
rem Installs or updates Docling Studio for you (no administrator rights needed). Double-click it.
title Docling Studio installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\packaging\windows\install.ps1" -Source "%~dp0app"
