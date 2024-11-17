#!/bin/bash

# Update the desktop entry to use absolute path
exec_patch="Exec=env PATH=$HOME/.local/bin:/config/.local/bin:$PATH harbor-app"

echo "Updating Harbor.desktop"

# Update original desktop entry
sed -i "s|^Exec=harbor-app$|Exec=$exec_patch|" "/usr/share/applications/Harbor.desktop"
