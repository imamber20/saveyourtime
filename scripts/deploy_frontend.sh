#!/bin/bash
# One-time Vercel frontend deployment
# Run from the project root: bash scripts/deploy_frontend.sh

set -e
cd "$(dirname "$0")/.."

echo "🚀 Deploying Content Memory frontend to Vercel..."
echo ""

# Check if vercel CLI is available
if ! command -v vercel &>/dev/null; then
  echo "Installing Vercel CLI..."
  npm install -g vercel
fi

echo "📁 Root directory: frontend/"
echo "🔧 Framework:      Create React App"
echo ""
echo "Deploying to production..."
vercel --cwd frontend \
  --prod \
  --yes \
  --build-env REACT_APP_SUPABASE_URL="https://foktswfeqhzpyrbxzrkm.supabase.co" \
  --build-env REACT_APP_SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZva3Rzd2ZlcWh6cHlyYnh6cmttIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU0NjUyMzIsImV4cCI6MjA5MTA0MTIzMn0.JhmLVFXy3oCWpJzkMtb-5xmWlSNvoZP76_GuPwOE04c"

echo ""
echo "✅ Deployed! Set REACT_APP_BACKEND_URL in the Vercel dashboard:"
echo "   Vercel → Project → Settings → Environment Variables"
echo "   REACT_APP_BACKEND_URL = https://your-ngrok-or-railway-url.com"
