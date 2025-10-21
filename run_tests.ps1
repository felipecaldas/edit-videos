# Run tests PowerShell script

Write-Host "Running subtitle generation tests..." -ForegroundColor Green
pytest tests/test_subtitles.py -v

Write-Host "All tests completed!" -ForegroundColor Green
