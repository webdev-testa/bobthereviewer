# Build all targets and copy output for the Python package
$ErrorActionPreference = 'Stop'

Write-Host "Building developer bundle..."
npm run build

Write-Host "Building judge HTML..."
npm run build:judge

Write-Host "Done. Built assets are in ../src/bobthereviewer/frontend/"
