#!/bin/bash
# AlgoGPT Ultimate - Quick Deploy to Render
# פשוט תעתיק ותדביק את הסקריפט הזה בטרמינל של Replit

echo "🚀 AlgoGPT Ultimate - Quick Deploy"
echo "=================================="
echo ""

# Step 1: Git push
echo "📤 Step 1/2: Pushing code to GitHub..."
cd /home/runner/$REPL_SLUG
git add .
git commit -m "🚀 AlgoGPT Ultimate Edition - Production Ready" || echo "No changes to commit"
git push origin main

if [ $? -eq 0 ]; then
    echo "✅ Code pushed to GitHub successfully!"
else
    echo "❌ Git push failed. Please check your git configuration."
    exit 1
fi

echo ""
echo "🎯 Step 2/2: Now go to Render Dashboard:"
echo "   1. Open: https://dashboard.render.com"
echo "   2. Select: algogpt-docker"
echo "   3. Click: 'Manual Deploy' → 'Deploy latest commit'"
echo "   4. Wait: 5-10 minutes"
echo ""
echo "🌐 Your Dashboard will be ready at:"
echo "   https://algogpt-docker.onrender.com/static/dashboard/index.html"
echo ""
echo "=================================="
echo "✅ Git push complete! Now deploy in Render Dashboard."
