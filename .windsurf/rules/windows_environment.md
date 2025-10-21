---
trigger: always_on
---

# Development Environment

## Operating System
- The development machine is **Windows 11**.
- All development, testing, and deployment commands should be compatible with **Windows PowerShell**.
- Docker commands should use Windows-compatible syntax and paths.

## Command Line Guidelines

### Prohibited Commands
- **DO NOT** use bash-specific commands like `chmod +x`, `ls -la`, `mkdir -p`, etc.
- **DO NOT** use Linux-style path separators (`/`) in PowerShell commands.
- **DO NOT** assume Unix-like file permissions or executable scripts.

### Windows-Compatible Commands
- Use **Windows PowerShell** syntax for all commands.
- Use **backslashes (`\`)** for Windows file paths in commands.
- Use **forward slashes (`/`)** for Docker volume mounts and container paths.
- Use **Windows-style** commands like `Get-ChildItem`, `New-Item`, `Copy-Item`, etc. when appropriate.

### Docker Commands on Windows
```powershell
# Correct - Windows PowerShell with proper path handling
docker-compose up -d

# Correct - Use Windows paths in commands  
Get-ChildItem "C:\Projects\edit-videos"

# Correct - Use container paths in Docker configs (forward slashes)
# - "/app/data:/container/data"

# WRONG - Don't use bash commands
# chmod +x script.sh
# ls -la /path