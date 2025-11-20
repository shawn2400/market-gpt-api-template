#!/bin/bash

echo "🚀 Starting deployment to Render.com..."
echo ""

echo "📦 Staging all changes..."
git add -A

echo ""
echo "✍️ Creating commit..."
git commit -m "Lower MinRR to 0.9 for CHOPPY markets - enable more trades"

echo ""
echo "📤 Pushing to GitHub (auto-deploys to Render)..."
git push origin main

echo ""
echo "✅ Deployment initiated! Render will auto-deploy in ~2-3 minutes"
echo "📊 Check Render dashboard for deployment status"
echo ""
