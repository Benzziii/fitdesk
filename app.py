import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

def get_supabase_creds():
    url = (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        or os.environ.get("VITE_SUPABASE_URL")
        or ""
    ).strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        or ""
    ).strip()
    # Allow runtime override from X-Supabase-Url / X-Supabase-Key headers if user configured via UI modal
    req_url = request.headers.get("X-Supabase-Url", "").strip().rstrip("/")
    req_key = request.headers.get("X-Supabase-Key", "").strip()
    if req_url and req_key:
        return req_url, req_key
    return url, key


def sb_request(method, table, query="", body=None, prefer="return=representation"):
    url, key = get_supabase_creds()
    if not url or not key:
        return None, "SUPABASE_URL atau SUPABASE_KEY belum diset di Vercel Environment Variables"
    endpoint = f"{url}/rest/v1/{table}"
    if query:
        endpoint += f"?{query}"
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    # If key is a JWT (starts with eyJ), also send Authorization Bearer
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else []), None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return None, f"HTTP {e.code}: {err_body}"
    except Exception as e:
        return None, str(e)


IS_VERCEL = os.environ.get("VERCEL") == "1"
DB_PATH = "/tmp/fitdesk.db" if IS_VERCEL else os.path.join(os.path.dirname(__file__), "fitdesk.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_sqlite_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            day_key TEXT NOT NULL,
            focus_area TEXT NOT NULL,
            duration_min INTEGER NOT NULL,
            avg_weight_kg REAL NOT NULL,
            total_sets INTEGER NOT NULL,
            total_reps INTEGER NOT NULL,
            total_volume_kg REAL NOT NULL,
            calories_burned INTEGER NOT NULL,
            rpe INTEGER NOT NULL,
            avg_hr INTEGER DEFAULT 122,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weight_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            waist_cm REAL NOT NULL,
            sleep_hrs REAL DEFAULT 7.0,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_sqlite_db()


@app.route("/")
@app.route("/app.py")
@app.route("/index.html")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def api_status():
    url, key = get_supabase_creds()
    if not url or not key:
        return jsonify({
            "cloud_connected": False,
            "storage_mode": "local_fallback",
            "reason": "Environment Variable SUPABASE_URL atau SUPABASE_KEY belum terbaca di Vercel (pastikan sudah Redeploy setelah menambah Environment Variables, atau masukkan langsung lewat tombol Pengaturan Cloud di aplikasi)."
        })
    rows, err = sb_request("GET", "workout_logs", "select=id&limit=1")
    if err:
        return jsonify({
            "cloud_connected": False,
            "storage_mode": "supabase_error",
            "reason": f"Koneksi ke Supabase gagal ({err}). Pastikan Anda sudah menjalankan supabase_schema.sql di SQL Editor Supabase."
        })
    return jsonify({
        "cloud_connected": True,
        "storage_mode": "supabase_cloud",
        "reason": "Terhubung penuh ke Supabase PostgreSQL (HP & Laptop Sinkron Otomatis)"
    })


@app.route("/api/workouts", methods=["GET", "POST"])
def handle_workouts():
    url, key = get_supabase_creds()
    if request.method == "POST":
        data = request.get_json() or {}
        date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
        day_key = data.get("day_key", "senin")
        focus_area = data.get("focus_area", "Latihan Harian")
        duration_min = int(data.get("duration_min", 35))
        avg_weight_kg = float(data.get("avg_weight_kg", 6.0))
        total_sets = int(data.get("total_sets", 15))
        total_reps = int(data.get("total_reps", 225))
        rpe = int(data.get("rpe", 7))
        avg_hr = int(data.get("avg_hr", 124))
        notes = data.get("notes", "")

        total_volume_kg = 0.0 if day_key == "rabu" else round(avg_weight_kg * total_reps, 1)
        met = 4.8 if day_key == "rabu" else 5.5
        calories_burned = int(round((met * 3.5 * 71.0 / 200.0) * duration_min))

        record = {
            "date": date,
            "day_key": day_key,
            "focus_area": focus_area,
            "duration_min": duration_min,
            "avg_weight_kg": avg_weight_kg,
            "total_sets": total_sets,
            "total_reps": total_reps,
            "total_volume_kg": total_volume_kg,
            "calories_burned": calories_burned,
            "rpe": rpe,
            "avg_hr": avg_hr,
            "notes": notes,
        }

        if url and key:
            res_data, err = sb_request("POST", "workout_logs", body=record)
            if not err:
                return jsonify({"status": "success", "storage": "supabase", "data": res_data}), 201

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workout_logs
            (date, day_key, focus_area, duration_min, avg_weight_kg, total_sets, total_reps, total_volume_kg, calories_burned, rpe, avg_hr, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(record.values()),
        )
        conn.commit()
        record["id"] = cur.lastrowid
        conn.close()
        return jsonify({"status": "success", "storage": "sqlite", "data": [record]}), 201

    if url and key:
        rows, err = sb_request("GET", "workout_logs", "day_key=neq.__sync_state__&order=date.desc,id.desc")
        if not err and rows is not None:
            return jsonify(rows)

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM workout_logs WHERE day_key != '__sync_state__' ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/workouts/<int:log_id>", methods=["DELETE"])
def delete_workout(log_id):
    url, key = get_supabase_creds()
    if url and key:
        _, err = sb_request("DELETE", "workout_logs", f"id=eq.{log_id}")
        if not err:
            return jsonify({"status": "deleted", "storage": "supabase", "id": log_id})

    conn = get_db_connection()
    conn.execute("DELETE FROM workout_logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted", "storage": "sqlite", "id": log_id})


@app.route("/api/weights", methods=["GET", "POST"])
def handle_weights():
    url, key = get_supabase_creds()
    if request.method == "POST":
        data = request.get_json() or {}
        record = {
            "date": data.get("date") or datetime.now().strftime("%Y-%m-%d"),
            "weight_kg": float(data.get("weight_kg", 70.5)),
            "waist_cm": float(data.get("waist_cm", 82.0)),
            "sleep_hrs": float(data.get("sleep_hrs", 7.0)),
            "notes": data.get("notes", ""),
        }
        if url and key:
            res_data, err = sb_request("POST", "weight_logs", body=record)
            if not err:
                return jsonify({"status": "success", "storage": "supabase", "data": res_data}), 201

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO weight_logs (date, weight_kg, waist_cm, sleep_hrs, notes) VALUES (?, ?, ?, ?, ?)",
            tuple(record.values()),
        )
        conn.commit()
        record["id"] = cur.lastrowid
        conn.close()
        return jsonify({"status": "success", "storage": "sqlite", "data": [record]}), 201

    if url and key:
        rows, err = sb_request("GET", "weight_logs", "order=date.asc,id.asc")
        if not err and rows is not None:
            return jsonify(rows)

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM weight_logs ORDER BY date ASC, id ASC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/state", methods=["GET", "POST"])
def handle_state():
    """
    Menyinkronkan checklist gerakan harian, bonus overload, dan profil antar HP & Laptop.
    Menyimpan state di dalam tabel workout_logs dengan day_key='__sync_state__' agar
    bekerja otomatis tanpa perlu membuat tabel baru di Supabase!
    """
    url, key = get_supabase_creds()
    if request.method == "POST":
        data = request.get_json() or {}
        state_str = json.dumps(data)
        if url and key:
            # Hapus state lama lalu masukkan state terbaru di workout_logs (day_key = '__sync_state__')
            sb_request("DELETE", "workout_logs", "day_key=eq.__sync_state__")
            dummy_row = {
                "date": "2099-12-31",
                "day_key": "__sync_state__",
                "focus_area": "SYSTEM_SYNC_STATE",
                "duration_min": 0,
                "avg_weight_kg": 0,
                "total_sets": 0,
                "total_reps": 0,
                "total_volume_kg": 0,
                "calories_burned": 0,
                "rpe": 1,
                "avg_hr": 0,
                "notes": state_str,
            }
            _, err = sb_request("POST", "workout_logs", body=dummy_row)
            if not err:
                return jsonify({"status": "synced", "storage": "supabase"})

        conn = get_db_connection()
        conn.execute("DELETE FROM workout_logs WHERE day_key = '__sync_state__'")
        conn.execute(
            """
            INSERT INTO workout_logs
            (date, day_key, focus_area, duration_min, avg_weight_kg, total_sets, total_reps, total_volume_kg, calories_burned, rpe, avg_hr, notes)
            VALUES ('2099-12-31', '__sync_state__', 'SYSTEM_SYNC_STATE', 0, 0, 0, 0, 0, 0, 1, 0, ?)
            """,
            (state_str,),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "synced", "storage": "sqlite"})

    if url and key:
        rows, err = sb_request("GET", "workout_logs", "day_key=eq.__sync_state__&order=id.desc&limit=1")
        if not err and rows and len(rows) > 0:
            try:
                return jsonify(json.loads(rows[0].get("notes") or "{}"))
            except Exception:
                return jsonify({})

    conn = get_db_connection()
    row = conn.execute("SELECT notes FROM workout_logs WHERE day_key = '__sync_state__' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row and row["notes"]:
        try:
            return jsonify(json.loads(row["notes"]))
        except Exception:
            pass
    return jsonify({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
