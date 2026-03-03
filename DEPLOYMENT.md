# Spend Analyzer - Deployment Guide

## 🚀 Quick Start Deployment (Railway.app)

Railway is the recommended platform: **cheap, easy, and secure**.

### Why Railway?
- ✅ **$5/month** (includes database)
- ✅ **PostgreSQL included** (more secure than SQLite)
- ✅ **Automatic HTTPS** with custom domains
- ✅ **One-click GitHub deployments**
- ✅ **Environment variable management**
- ✅ **Automatic backups**

---

## Step-by-Step Deployment to Railway

### **Step 1: Prepare Your Code**

1. **Create `.env.production` file** with production variables:
```bash
FLASK_ENV=production
SECRET_KEY=<generate-random-key>
DATABASE_URL=<railway-will-provide>
```

2. **Push to GitHub**:
```bash
git init
git add .
git commit -m "Initial Spend Analyzer commit"
git remote add origin https://github.com/YOUR-USERNAME/spend-analyzer.git
git branch -M main
git push -u origin main
```

### **Step 2: Create Railway Account**

1. Go to **https://railway.app**
2. Sign up (GitHub login recommended)
3. Create a new project

### **Step 3: Connect GitHub Repository**

1. Click "New Project" → "Deploy from GitHub"
2. Authorize Railway to access your GitHub
3. Select your `spend-analyzer` repository
4. Railway will auto-detect this is a Python project

### **Step 4: Add PostgreSQL Database**

1. Click "Add Plugin" → "PostgreSQL"
2. Railway auto-creates a database and sets `DATABASE_URL`

### **Step 5: Set Environment Variables**

In Railway dashboard → Variables:

```
FLASK_ENV=production
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
```

### **Step 6: Deploy!**

1. Click "Deploy" button
2. Watch the logs for successful deployment
3. Railway assigns you a URL: `https://your-app-xxx.railway.app`

---

## 🔒 SECURITY FEATURES (Already Implemented!)

### **Login Security** ✅
- Passwords **hashed** with Werkzeug security
- Session cookies are **httpOnly** (can't be accessed by JavaScript)
- Session cookies are **secure** (HTTPS only in production)
- Sessions expire after **7 days** of inactivity

### **Database Security** ✅
- PostgreSQL is more secure than SQLite
- All data encrypted in transit (SSL/TLS)
- Password hashing: `werkzeug.security.check_password_hash()`
- Each user's data isolated by `user_id`

### **Application Security** ✅
- CSRF protection ready with Flask-WTF (optional)
- File upload limits (5MB max)
- SQL injection prevention (SQLAlchemy ORM)
- No sensitive data in logs

---

## 🔐 How Login Security Works

When a user logs in:

1. **Password submitted** → Flask receives it
2. **Hashed** using Werkzeug security → Never stored in plain text
3. **Compared to hash** using `check_password_hash()` → Can't be reversed
4. **Session created** with user ID → Secure cookie
5. **Cookie stored** as httpOnly + Secure flags → Can't be stolen via JavaScript

Your DB stores:
```
User 'john'
├─ password_hash = "scrypt$14$16$29$$..." (not reversible!)
├─ receipts (john's data only)
└─ recommendations
```

---

## 📊 Database Migration

### Development → Production:

```bash
# 1. Export existing SQLite data
python -c "
from spend_analyzer.db import get_session
from spend_analyzer.models import User

db = get_session('sqlite:///spend_data.db')
users = db.query(User).all()
for user in users:
    print(f'{user.username}: {len(user.receipts)} receipts')
db.close()
"

# 2. Railway creates PostgreSQL database
# 3. On first deploy, SQLAlchemy creates all tables
# 4. Manually migrate data if needed (see below)
```

### Manual Data Migration Script:

```python
# migrate_to_production.py
from spend_analyzer.db import get_session
from spend_analyzer.models import User, Location, Receipt, LineItem

DEV_DB = "sqlite:///spend_data.db"
PROD_DB = "postgresql://..."  # Set DATABASE_URL env var

def migrate():
    # Read from development
    dev_session = get_session(DEV_DB)
    users = dev_session.query(User).all()
    
    # Write to production
    prod_session = get_session(PROD_DB)
    
    for user in users:
        # Copy user
        new_user = User(username=user.username)
        new_user.password_hash = user.password_hash
        prod_session.add(new_user)
        prod_session.flush()
        
        # Copy receipts and items
        for receipt in user.receipts:
            new_receipt = Receipt(...)
            # ... copy all fields
            prod_session.add(new_receipt)
    
    prod_session.commit()
    print(f"Migrated {len(users)} users successfully!")

if __name__ == '__main__':
    migrate()
```

---

## 🌐 Custom Domain (Optional)

1. Buy domain from **Namecheap** (~$1/year) or **Google Domains** (~$12/year)
2. In Railway Dashboard → Settings → Domains
3. Add your custom domain
4. Railway provides DNS records to add
5. DNS propagates in 24 hours
6. **HTTPS auto-enabled** with Railway's certificate

Example: `spend-analyzer.yourdomain.com`

---

## 📱 Alternative Hosting Options

### **PythonAnywhere** (Free + $5/mo)
- **Pros**: Simple, built-in Python environment
- **Cons**: Limited resources on free tier
- **Deploy**: Upload code via web interface or Git
- **Database**: MySQL + PostgreSQL available

### **Render.com** ($7+/month)
- **Pros**: Fast, great documentation
- **Cons**: No free tier (but trial credits)
- **Deploy**: GitHub integration, auto-deploys on push
- **Database**: PostgreSQL built-in

### **Heroku** ($7+/month, formerly free)
- **Pros**: Industry standard, reliable
- **Cons**: More expensive than alternatives
- **Deploy**: Git push to Heroku
- **Database**: PostgreSQL add-on

---

## 🚨 Pre-Deployment Checklist

- [ ] GitHub repo created and pushed
- [ ] `.env.example` filled out
- [ ] `requirements.txt` updated with production packages
- [ ] `Procfile` present (gunicorn configured)
- [ ] `config.py` created with production settings
- [ ] Database environment variable set
- [ ] SECRET_KEY is a random secure value
- [ ] No sensitive data in code (use env vars)
- [ ] Tested login locally with production config
- [ ] PostgreSQL driver installed locally to test

---

## ✅ After Deployment

1. **Test login**: Create account on live site
2. **Add receipt**: Verify data saves to production DB
3. **Check analytics**: Confirm calculations work
4. **Test edit/delete**: Verify soft delete works
5. **Monitor logs**: Watch for errors in Railway dashboard

---

## 📞 Troubleshooting

### "ModuleNotFoundError: No module named 'xxx'"
- Update `requirements.txt` and redeploy

### "DATABASE_URL not set"
- Check Railway → Variables tab
- Make sure PostgreSQL plugin is attached

### "Application Error"
- Check Railway logs for stack traces
- Common: Missing environment variable
- Solution: Add it in Railway dashboard

### "Login fails in production"
- Verify password hashing works: `werkzeug.security.check_password_hash()`
- Check session cookies are secure
- Ensure SECRET_KEY is set

### "Database connection timeout"
- PostgreSQL still initializing
- Wait 30 seconds and refresh
- Check if Railway is showing resource issues

---

## 💰 Monthly Cost Estimate

### Railway (Recommended)
- **Compute**: $5/month
- **PostgreSQL**: Free up to 10GB
- **Total**: ~$5/month

### Namecheap Domain
- **Domain**: ~$10-15/year (~$0.85/month)

### **Total: ~$6/month** ✨

---

## 🔄 Continuous Deployment

Once you push to GitHub, Railway auto-deploys:

```bash
# Make changes locally
git add .
git commit -m "Add new feature"
git push origin main

# Railway sees the push
# Automatically rebuilds and deploys
# Your live site updates in ~2 minutes!
```

---

## 📚 Helpful Resources

- **Railway Docs**: https://docs.railway.app
- **Flask Deployment**: https://flask.palletsprojects.com/deployment/
- **SQLAlchemy + PostgreSQL**: https://docs.sqlalchemy.org/
- **Werkzeug Security**: https://werkzeug.palletsprojects.com/security/

