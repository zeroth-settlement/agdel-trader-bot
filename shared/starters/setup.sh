#!/bin/bash
# Pyrana Demo — Setup Script
#
# Run this after cloning a demo repo:
#   ./setup.sh
#
# Initializes the shared submodule (pyrana-playground-shared).

set -e

echo "Initializing shared submodule..."
git submodule update --init

echo ""
echo "Setup complete. Shared assets available at:"
echo "  shared/design-guide/   — CSS theme, utilities, logos"
echo "  shared/components/     — Reusable UI components"
echo "  shared/starters/       — Boilerplate source files"
echo ""
echo "Next steps:"
echo "  1. Edit project.json with your project details"
echo "  2. Run: python start.py"
echo "  3. Open: http://localhost:9002"
