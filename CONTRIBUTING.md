# Contributing to DV2Plex

Thank you for your interest in contributing to DV2Plex! 🎉

This document describes how you can contribute to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How can I contribute?](#how-can-i-contribute)
- [Setting up Development Environment](#setting-up-development-environment)
- [Development Process](#development-process)
- [Coding Standards](#coding-standards)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)

## Code of Conduct

This project follows a Code of Conduct. By participating, you are expected to uphold this.

### Our Standards

- Use respectful and inclusive language
- Respect different viewpoints and experiences
- Give and accept constructive feedback
- Focus on what is best for the community

## How can I contribute?

### 🐛 Bug Reports

If you find a bug:

1. Check if the issue already exists
2. Create a new issue with:
   - Clear, descriptive title
   - Detailed description of the problem
   - Steps to reproduce
   - Expected vs. actual behavior
   - System information (OS, Python version, etc.)
   - Screenshots (if relevant)

### 💡 Feature Requests

For new features:

1. Check if the feature has already been suggested
2. Create an issue with:
   - Clear description of the feature
   - Justification for why it's useful
   - Possible implementation approaches (optional)

### 📝 Documentation

Documentation improvements are always welcome:

- Fix typos
- Clearer explanations
- Additional examples
- Translations

### 🔧 Code Contributions

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test your changes
5. Submit a pull request

## Setting up Development Environment

### Prerequisites

- Python 3.8+
- Git
- (Optional) Virtual Environment

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/dv2plex.git
cd dv2plex

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Start development
python -m dv2plex
```

## Development Process

### Branch Strategy

- `main`: Stable, production-ready version
- `develop`: Development branch (if present)
- `feature/*`: New features
- `fix/*`: Bug fixes
- `docs/*`: Documentation changes

### Workflow

1. **Create Issue** (optional, but recommended)
2. **Create Branch**:
   ```bash
   git checkout -b feature/my-feature
   # or
   git checkout -b fix/bug-description
   ```

3. **Make Changes**:
   - Write code
   - Add tests (if possible)
   - Update documentation

4. **Create Commits**:
   ```bash
   git add .
   git commit -m "feat: Description of change"
   ```

5. **Push and Pull Request**:
   ```bash
   git push origin feature/my-feature
   ```

## Coding Standards

### Python

- Follow **PEP 8**
- **Type Hints** for new functions
- **Docstrings** in Google-style:

```python
def example_function(param1: str, param2: int) -> bool:
    """
    Short description of the function.
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When something goes wrong
    """
    pass
```

### Code Formatting

- **Maximum line length**: 100 characters (if possible)
- **Imports**: Sorted and grouped (stdlib, third-party, local)
- **Naming**:
  - Functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`

### Example

```python
"""Module documentation."""

import os
from pathlib import Path
from typing import Optional

import numpy as np

from dv2plex.config import Config


class ExampleClass:
    """Short class description."""
    
    def __init__(self, config: Config):
        """
        Initialize the class.
        
        Args:
            config: Configuration object
        """
        self.config = config
    
    def example_method(self, value: int) -> Optional[str]:
        """
        Example method.
        
        Args:
            value: An integer value
        
        Returns:
            Optional string value
        """
        if value < 0:
            return None
        return str(value)
```

## Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) standard:

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation
- `style`: Code formatting (no logic changes)
- `refactor`: Code refactoring
- `test`: Adding/changing tests
- `chore`: Build process, dependencies, etc.

### Examples

```bash
feat(capture): Add support for multiple capture parts
fix(upscale): Fix memory leak in upscaling engine
docs(readme): Update installation instructions
refactor(config): Simplify configuration loading
```

### Rules

- **Subject**: Maximum 50 characters, imperative ("Add" not "Added")
- **Body**: Explain the "what" and "why", not the "how"
- **Footer**: References to issues (e.g., `Closes #123`)

## Pull Requests

### Before Pull Request

- [ ] Code follows coding standards
- [ ] Self-tested
- [ ] Comments and docstrings added
- [ ] Documentation updated (if necessary)
- [ ] No new warnings
- [ ] Commit messages follow standard

### Creating Pull Request

1. **Description**:
   - What was changed?
   - Why was it changed?
   - How was it tested?

2. **References**:
   - Link to relevant issues
   - `Closes #123` for automatic closing

3. **Screenshots**:
   - For UI changes

4. **Checklist**:
   - Use the PR template checklist

### Review Process

- Maintainers will review the PR
- Feedback may be given
- Changes may be requested
- After approval, the PR will be merged

## Tests

Tests are currently still planned. If you add tests:

- Unit tests for individual functions
- Integration tests for workflows
- Use `pytest` as test framework

## Questions?

If you have questions:

- Open an issue with the label "question"
- Discuss in GitHub Discussions
- Contact the maintainers

## Thank you! 🙏

Every contribution, no matter how small, is valuable. Thank you for making DV2Plex better!
