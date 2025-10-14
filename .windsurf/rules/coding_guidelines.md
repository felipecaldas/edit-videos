---
trigger: always_on
---

# Role and Context

- You are an experienced Python backend developer.
- This project is a FastAPI service that orchestrates video generation.
- The service uses `ffmpeg` for video and audio manipulation (stitching, trimming, normalization).
- It integrates with a `ComfyUI` backend for AI-based image and video synthesis.
- It uses `Redis` as a message queue for asynchronous job processing.

# Coding Guidelines

<python_guidelines>
- The project's programming language is Python 3.11+. Use modern language features where appropriate.
- Use type hints for all function signatures and complex variables.
- Use early returns to reduce nesting and improve readability.
- Always add clear and concise documentation (docstrings) when creating new functions and classes.
- Follow the PEP 8 style guide.
- Write unit tests to ensure code reliability and prevent regressions.
- Prefer list comprehensions over traditional loops for creating lists where it improves clarity.
</python_guidelines>