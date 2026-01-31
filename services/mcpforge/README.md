# MCP Forge Configuration

This directory contains configuration for the MCP Forge (MCP Context Forge) service.

## Database Options

By default, MCP Forge uses SQLite for data storage, which is suitable for development and small deployments. The database file is stored in `./mcpforge/data/mcp.db`.

### SQLite Initialization

For first-time setup, you need to create an empty database file before starting the service:

```bash
mkdir -p ./mcpforge/data
touch ./mcpforge/data/mcp.db
chmod 666 ./mcpforge/data/mcp.db
chmod 777 ./mcpforge/data
```

Harbor will automatically handle this during the first `harbor up mcpforge` command.

### Using PostgreSQL (Recommended for Production)

For production deployments, PostgreSQL is recommended. You can configure it by:

1. Update `HARBOR_MCPFORGE_DATABASE_URL` in your `.env`:
   ```bash
   HARBOR_MCPFORGE_DATABASE_URL="postgresql+psycopg://user:password@postgres:5432/mcpforge"
   ```

2. Or add a cross-file to integrate with Harbor's postgres service

### Using MySQL/MariaDB

MySQL/MariaDB is also supported:
```bash
HARBOR_MCPFORGE_DATABASE_URL="mysql+pymysql://user:password@mysql:3306/mcpforge"
```

## Redis Caching (Optional)

For improved performance, you can enable Redis caching by adding to `override.env`:
```bash
REDIS_URL=redis://redis:6379/0
```

## Authentication

By default, authentication is disabled for localhost development (`AUTH_REQUIRED=false`).

**Warning**: If exposing this service externally, always enable authentication by setting:
```bash
HARBOR_MCPFORGE_AUTH_REQUIRED="true"
```

And update the credentials:
```bash
HARBOR_MCPFORGE_BASIC_AUTH_USER="your-username"
HARBOR_MCPFORGE_BASIC_AUTH_PASSWORD="your-secure-password"
HARBOR_MCPFORGE_JWT_SECRET="your-secret-key"
```

## Multi-Architecture Support

The MCP Forge container supports multiple architectures (amd64, arm64, s390x) automatically.
