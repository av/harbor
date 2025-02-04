#!/bin/bash

# Get absolute path of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create symbolic link to make harbor globally accessible
echo "Creating harbor executable..."
cat > harbor << 'EOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec "$SCRIPT_DIR/harbor.sh" "$@"
EOF

chmod +x harbor

# Ensure harbor.sh is executable
chmod +x harbor.sh

# Ensure common.sh is executable
chmod +x harbor/common.sh

echo "Harbor has been set up successfully!"
echo "You can now use 'harbor doctor' to run diagnostics"