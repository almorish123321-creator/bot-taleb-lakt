# Makefile Documentation

This document explains the available make commands and their purposes.

## Installation Commands

- `make install`: Creates a virtual environment and installs all required dependencies
  - Sets up Python virtual environment
  - Installs project dependencies from requirements.txt
  - Installs development dependencies (ruff, mypy)

## Development Commands

- `make lint`: Runs all linting checks
  - Runs ruff for code style and error checking
  - Runs mypy for type checking
- `make format`: Formats code using ruff
  - Automatically fixes code style issues
- `make test`: Runs test suite
  - Executes all tests in the tests/ directory
- `make clean`: Cleans up temporary files and caches
  - Removes Python cache files
  - Removes testing/linting cache directories
  - Removes Telegram session files

## Docker Commands

- `make docker-build`: Builds the Docker image
- `make docker-run`: Runs the application in Docker
- `make docker-stop`: Stops the Docker containers

## Development Shortcuts

- `make dev-setup`: Complete development environment setup
  - Runs install, format, and lint commands
- `make run`: Runs the application locally

## Usage Examples

Initial setup for development:
```bash
make dev-setup
```

Regular development workflow:
```bash
make format  # Format code
make lint    # Check for issues
make run     # Run the application
```

Docker deployment:
```bash
make docker-build
make docker-run
```
