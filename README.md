# FitDesk Pro v2 — Cloud Flask App (Vercel + Supabase PostgreSQL)

Aplikasi olahraga harian, pembentuk otot seluruh sisi tubuh (*All-Angle Muscle Split*), program perut ideal (*Anti-Belly Fat*), serta pelacak postur kerja & kesiapan futsal/bulu tangkis dengan tema **Modern Minimalist White & Blue**.

## Cara Deploy ke Cloud (GitHub + Supabase + Vercel) — Tanpa Bergantung Laptop

### Tahap 1: Buat Database Cloud Gratis di Supabase
1. Buka [Supabase Dashboard](https://supabase.com/docs/guides/getting-started/quickstarts/flask) dan klik **New Project**.
2. Masuk ke menu **SQL Editor** -> **New Query**, salin seluruh isi file `supabase_schema.sql`, lalu klik **Run**.
3. Masuk ke menu **Project Settings** -> **API**, lalu salin:
   - `Project URL` (`SUPABASE_URL`)
   - `anon public` key (`SUPABASE_KEY`)

### Tahap 2: Push Kode ke GitHub
Jalankan perintah berikut di terminal dalam folder `fitdesk_flask_app`:
```bash
git init
git add .
git commit -m "Initial commit FitDesk Pro Flask + Supabase"
git branch -M main
git remote add origin https://github.com/USERNAME_ANDA/fitdesk-pro.git
git push -u origin main
```

### Tahap 3: Deploy Otomatis di Vercel
1. Buka [Vercel Dashboard](https://vercel.com/docs/frameworks/backend/flask) dan klik **Add New... -> Project**.
2. Pilih repository GitHub `fitdesk-pro` yang baru Anda *push*.
3. Pada bagian **Environment Variables**, tambahkan:
   - `SUPABASE_URL` = *(URL proyek Supabase Anda)*
   - `SUPABASE_KEY` = *(Anon key Supabase Anda)*
4. Klik **Deploy**. Dalam ~45 detik aplikasi Anda akan aktif di domain `https://fitdesk-pro-anda.vercel.app` dan bisa diakses 24 jam dari smartphone tanpa perlu menyalakan laptop!
