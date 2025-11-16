# 🚀 Push ל-Render (2GB) - 3 פקודות בלבד!

## ✅ מה מוכן:
1. ✅ `render.yaml` - Web service על 2GB
2. ✅ `start_all_services.sh` - FastAPI + 10 workers
3. ✅ `Dockerfile` - מריץ את הכל

---

## 📝 העתק והדבק ב-Replit Shell:

```bash
# הסר git lock
rm -f /home/runner/$REPL_SLUG/.git/index.lock

# Reset + Pull + Add + Commit
cd /home/runner/$REPL_SLUG
git reset --hard origin/main
git pull origin main
git add render.yaml start_all_services.sh Dockerfile
git commit -m "🚀 Render 2GB: Complete deployment with all 10 workers"

# Push
git push https://$GITHUB_TOKEN@github.com/shawn2400/market-gpt-api-template.git main
```

---

## ✅ אחרי Push:

**Render Dashboard:** https://dashboard.render.com

תראה **"Deploying..."** → אחרי 5-10 דקות → **"Live"**

**הכל ירוץ 24/7 על ה-2GB שלך!** 🎉
