### Releasing Harbor

This is a helper documentation on release workflow.

### Seed values

Includes:
- seeding "current" version everywhere
- project scope for poetry for PyPi publishing

```bash
deno run -A ./.scripts/seed.ts
```

### Publish to npm

```bash
# Test
npm publish --dry-run

# Publish
npm whoami
npm publish --access public
```

### Publish to PyPI

```bash
# System python
poetry env use system
# Build
poetry build -v
# Publish
poetry publish -v
```

### App/Docker builds

- Actions on GH, attached to a tag