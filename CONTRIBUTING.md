# Contributing to Backup Camera

Thank you for your interest in contributing to **Backup Camera**!

## Getting Started

1.  Clone the repository.
2.  Install dependencies: `uv pip install -e .`
3.  Ensure you have Python 3.9+ and a Windows environment for full feature testing (WMI logic).

## Development Flow

1.  **Fork** the repository.
2.  Create a **new branch**: `git checkout -b feat/my-amazing-feature`.
3.  **Commit** your changes: `git commit -m 'feat: add amazing feature'`.
4.  **Push** to the branch: `git push origin feat/my-amazing-feature`.
5.  Open a **Pull Request**.

## Coding Style

- Use **Conventional Commits** for commit messages.
- Formatting: Follow PEP 8.
- Type Hints: Encouraged for new code.

## Testing

- Currently, manual verification is required for hardware integration.
- For logic changes, simple unit tests in `src` are welcome.
