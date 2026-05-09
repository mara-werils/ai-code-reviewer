#!/usr/bin/env bash
# setup-github-app.sh — Interactive setup for AI Code Reviewer GitHub App
#
# Usage:
#   chmod +x scripts/setup-github-app.sh
#   ./scripts/setup-github-app.sh

set -euo pipefail

echo "============================================"
echo "  AI Code Reviewer — GitHub App Setup"
echo "============================================"
echo ""

# Step 1: Create the GitHub App
echo "Step 1: Create a GitHub App"
echo ""
echo "  1. Go to: https://github.com/settings/apps/new"
echo "     (or for an org: https://github.com/organizations/YOUR_ORG/settings/apps/new)"
echo ""
echo "  2. Fill in:"
echo "     - App name: AI Code Reviewer (or your preferred name)"
echo "     - Homepage URL: https://github.com/mara-werils/ai-code-reviewer"
echo "     - Webhook URL: https://YOUR_SERVER/webhooks/github"
echo "     - Webhook secret: (generate one below)"
echo ""

# Generate webhook secret
WEBHOOK_SECRET=$(openssl rand -hex 20)
echo "  Generated webhook secret: $WEBHOOK_SECRET"
echo "  (save this — you'll need it for both GitHub and your server)"
echo ""

echo "  3. Permissions:"
echo "     - Contents: Read & write"
echo "     - Issues: Read & write"
echo "     - Pull requests: Read & write"
echo "     - Metadata: Read-only"
echo ""

echo "  4. Subscribe to events:"
echo "     - Pull request"
echo "     - Issue comment"
echo "     - Pull request review comment"
echo ""

echo "  5. Where can this GitHub App be installed? → Any account"
echo ""

read -rp "Press Enter after creating the app..."
echo ""

# Step 2: Get App ID
echo "Step 2: App credentials"
echo ""
read -rp "  Enter your App ID (from the app settings page): " APP_ID

# Step 3: Generate private key
echo ""
echo "  Now generate a private key:"
echo "  → Go to your app settings → Private keys → Generate a private key"
echo "  → Save the .pem file to this directory as 'private-key.pem'"
echo ""
read -rp "Press Enter after saving private-key.pem..."

if [ ! -f "private-key.pem" ]; then
    echo "  Warning: private-key.pem not found in current directory."
    read -rp "  Enter path to private key file: " KEY_PATH
    cp "$KEY_PATH" private-key.pem
    echo "  Copied to private-key.pem"
fi

# Step 4: LLM API key
echo ""
echo "Step 3: LLM Provider"
echo ""
echo "  Choose a provider:"
echo "  1) Groq (free tier, recommended)"
echo "  2) OpenAI (GPT-4o)"
echo "  3) Anthropic (Claude)"
echo "  4) Google (Gemini)"
echo ""
read -rp "  Choice [1]: " PROVIDER_CHOICE
PROVIDER_CHOICE=${PROVIDER_CHOICE:-1}

case $PROVIDER_CHOICE in
    1)
        PROVIDER="groq"
        KEY_NAME="GROQ_API_KEY"
        echo "  Get a free key at: https://console.groq.com"
        ;;
    2)
        PROVIDER="openai"
        KEY_NAME="OPENAI_API_KEY"
        ;;
    3)
        PROVIDER="anthropic"
        KEY_NAME="ANTHROPIC_API_KEY"
        ;;
    4)
        PROVIDER="google"
        KEY_NAME="GOOGLE_API_KEY"
        ;;
    *)
        PROVIDER="groq"
        KEY_NAME="GROQ_API_KEY"
        ;;
esac

read -rp "  Enter your $KEY_NAME: " API_KEY

# Step 5: Write .env
echo ""
echo "Step 4: Writing .env file"

cat > .env <<EOF
# GitHub App
GITHUB_APP_ID=$APP_ID
GITHUB_WEBHOOK_SECRET=$WEBHOOK_SECRET
GITHUB_PRIVATE_KEY_PATH=./private-key.pem

# LLM Provider
PROVIDER=$PROVIDER
${KEY_NAME}=$API_KEY

# Optional
REVIEW_STYLE=concise
MAX_COMMENTS=15
EOF

echo "  Created .env file"
echo ""

# Step 6: Deploy
echo "Step 5: Deploy"
echo ""
echo "  Option A — Docker (recommended):"
echo "    docker compose -f docker-compose.app.yml up -d"
echo ""
echo "  Option B — Fly.io:"
echo "    fly launch --config fly.toml"
echo "    fly secrets set GITHUB_APP_ID=$APP_ID \\"
echo "      GITHUB_WEBHOOK_SECRET=$WEBHOOK_SECRET \\"
echo "      GITHUB_PRIVATE_KEY=\"\$(cat private-key.pem)\" \\"
echo "      ${KEY_NAME}=$API_KEY"
echo "    fly deploy"
echo ""
echo "  Option C — Local (for testing):"
echo "    pip install -e '.[core]' uvicorn PyJWT cryptography"
echo "    uvicorn src.github.app_webhook:app --port 8000"
echo "    # Use ngrok for webhook URL: ngrok http 8000"
echo ""

# Step 7: Install the App
echo "Step 6: Install the App"
echo ""
echo "  1. Go to: https://github.com/apps/YOUR_APP_NAME/installations/new"
echo "  2. Select repositories to review"
echo "  3. Open a PR — the bot will review it automatically!"
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
