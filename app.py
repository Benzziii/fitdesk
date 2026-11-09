import json
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

# Cek apakah kredensial Supabase tersedia di Environment Variables (Vercel / .env)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip() or os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
supabase_client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print("Warning: gagal inisialisasi Supabase client, beralih ke SQLite fallback:", e)

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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state_json TEXT NOT NULL
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
    return jsonify({
        "cloud_connected": bool(supabase_client),
        "storage_mode": "supabase_cloud" if supabase_client else "local_sqlite"
    })


@app.route("/api/workouts", methods=["GET", "POST"])
def handle_workouts():
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

        if supabase_client:
            res = supabase_client.table("workout_logs").insert(record).execute()
            return jsonify({"status": "success", "storage": "supabase", "data": res.data}), 201

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
        new_id = cur.lastrowid
        conn.close()
        record["id"] = new_id
        return jsonify({"status": "success", "storage": "sqlite", "data": [record]}), 201

    if supabase_client:
        res = supabase_client.table("workout_logs").select("*").order("date", desc=True).order("id", desc=True).execute()
        return jsonify(res.data)

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM workout_logs ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/workouts/<int:log_id>", methods=["DELETE"])
def delete_workout(log_id):
    if supabase_client:
        supabase_client.table("workout_logs").delete().eq("id", log_id).execute()
        return jsonify({"status": "deleted", "storage": "supabase", "id": log_id})

    conn = get_db_connection()
    conn.execute("DELETE FROM workout_logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted", "storage": "sqlite", "id": log_id})


@app.route("/api/weights", methods=["GET", "POST"])
def handle_weights():
    if request.method == "POST":
        data = request.get_json() or {}
        record = {
            "date": data.get("date") or datetime.now().strftime("%Y-%m-%d"),
            "weight_kg": float(data.get("weight_kg", 70.5)),
            "waist_cm": float(data.get("waist_cm", 82.0)),
            "sleep_hrs": float(data.get("sleep_hrs", 7.0)),
            "notes": data.get("notes", ""),
        }
        if supabase_client:
            res = supabase_client.table("weight_logs").insert(record).execute()
            return jsonify({"status": "success", "storage": "supabase", "data": res.data}), 201

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO weight_logs (date, weight_kg, waist_cm, sleep_hrs, notes) VALUES (?, ?, ?, ?, ?)",
            tuple(record.values()),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        record["id"] = new_id
        return jsonify({"status": "success", "storage": "sqlite", "data": [record]}), 201

    if supabase_client:
        res = supabase_client.table("weight_logs").select("*").order("date", desc=False).order("id", desc=False).execute()
        return jsonify(res.data)

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM weight_logs ORDER BY date ASC, id ASC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/state", methods=["GET", "POST"])
def handle_state():
    """Menyinkronkan checklist gerakan harian, bonus overload, dan profil antar HP & Laptop."""
    if request.method == "POST":
        data = request.get_json() or {}
        state_str = json.dumps(data)
        if supabase_client:
            try:
                supabase_client.table("user_state").upsert({"id": 1, "state_json": state_str}).execute()
                return jsonify({"status": "synced", "storage": "supabase"})
            except Exception:
                pass
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO user_state (id, state_json) VALUES (1, ?)", (state_str,))
        conn.commit()
        conn.close()
        return jsonify({"status": "synced", "storage": "sqlite"})

    if supabase_client:
        try:
            res = supabase_client.table("user_state").select("state_json").eq("id", 1).execute()
            if res.data and len(res.data) > 0:
                return jsonify(json.loads(res.data[0]["state_json"]))
        except Exception:
            pass

    conn = get_db_connection()
    row = conn.execute("SELECT state_json FROM user_state WHERE id = 1").fetchone()
    conn.close()
    if row:
        return jsonify(json.loads(row["state_json"]))
    return jsonify({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
