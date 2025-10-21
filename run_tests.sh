#!/bin/bash
# Run tests script

echo "Running subtitle generation tests..."
pytest tests/test_subtitles.py -v

echo "All tests completed!"
