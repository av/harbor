#!/bin/sh
# Initialize SQLite database for MCP Context Forge
# This script ensures the database file exists before starting the service

DB_FILE="/app/data/mcp.db"

# Create directory if it doesn't exist
mkdir -p /app/data

# Create empty database file if it doesn't exist
if [ ! -f "$DB_FILE" ]; then
    echo "Creating empty SQLite database at $DB_FILE"
    touch "$DB_FILE"
    chmod 666 "$DB_FILE"
fi

# Make sure directory is writable
chmod 777 /app/data 2>/dev/null || true

# Execute the original entrypoint
exec /app/docker-entrypoint.sh "$@"
