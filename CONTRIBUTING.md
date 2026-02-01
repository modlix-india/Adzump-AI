# Contributing Guidelines

## Branch Naming

```
<type>/<short-description>
```

| Type | Use Case |
|------|----------|
| `feature/` | New functionality |
| `bugfix/` | Bug fixes |
| `hotfix/` | Urgent production fixes |
| `refactor/` | Code restructuring without behavior change |
| `docs/` | Documentation only |
| `test/` | Adding or updating tests |

**Examples:**
- `feature/meta-campaign-agent`
- `bugfix/session-timeout-handling`
- `refactor/cleanup-business-service`

**Rules:**
- Use lowercase with hyphens (kebab-case)
- Keep it short but descriptive
- No special characters except hyphens

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <description>
```

| Type | Use Case |
|------|----------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change without feature/fix |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `chore` | Build, config, dependencies |

**Examples:**
- `feat: add meta campaign generation endpoint`
- `fix: session expiry not triggering logout`
- `refactor: cleanup business service`

**Rules:**
- Lowercase type and description
- No period at end
- Keep under 72 characters
- Use imperative mood ("add" not "added")

## Pull Requests

- Target `master` branch
- Ensure no merge conflicts before requesting review
- Keep PRs focused - one feature/fix per PR
- Include brief description of changes
- Link related issues if applicable

## Code Style

- Formatter: Ruff (auto-configured in `.vscode/settings.json`)
- Follow existing patterns in the codebase
- No unnecessary comments - code should be self-explanatory
- Type hints for function signatures

## Testing

- Run `pytest` before pushing
- Add tests for new features when applicable
- Don't break existing tests
