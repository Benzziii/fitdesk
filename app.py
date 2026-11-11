import hashlib
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


def hash_pin(pin_str):
    return hashlib.sha256(pin_str.strip().encode("utf-8")).hexdigest()


def get_stored_pin_hash():
    """Mengecek apakah ada hash Secret Sync Key / PIN di environment variable atau di database."""
    env_pin = (os.environ.get("SYNC_PIN") or os.environ.get("APP_SYNC_PIN") or "").strip()
    if env_pin:
        return hash_pin(env_pin)

    url, key = get_supabase_creds()
    if url and key:
        rows, err = sb_request("GET", "workout_logs", "day_key=eq.__pin_guard__&order=id.desc&limit=1")
        if not err and rows and len(rows) > 0:
            return (rows[0].get("notes") or "").strip()
        return ""

    conn = get_db_connection()
    row = conn.execute("SELECT notes FROM workout_logs WHERE day_key = '__pin_guard__' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return (row["notes"] or "").strip() if row else ""


def verify_request_pin():
    """
    Memverifikasi header X-Sync-Key dari browser.
    - Jika database sudah dikunci dengan Secret Sync Key / PIN, maka setiap perangkat
      wajib mengirimkan X-Sync-Key yang cocok untuk membaca atau menulis data.
    """
    stored_hash = get_stored_pin_hash()
    if not stored_hash:
        return True, ""
    client_pin = (request.headers.get("X-Sync-Key") or "").strip()
    if not client_pin:
        return False, "Website ini diproteksi dengan Secret Sync Key / PIN. Masukkan PIN pribadi Anda untuk membuka dan menyinkronkan data."
    if hash_pin(client_pin) != stored_hash:
        return False, "Secret Sync Key / PIN tidak cocok! Masukkan PIN yang sama seperti di perangkat utama Anda."
    return True, ""


@app.route("/")
@app.route("/app.py")
@app.route("/index.html")
def index():
    return render_template("index.html")


@app.route("/api/pin", methods=["POST"])
def manage_pin():
    """Mengatur, memverifikasi, atau membuka kunci Secret Sync Key / PIN Cloud."""
    data = request.get_json() or {}
    action = data.get("action", "verify")
    new_pin = (data.get("pin") or "").strip()
    current_pin = (request.headers.get("X-Sync-Key") or data.get("current_pin") or "").strip()

    stored_hash = get_stored_pin_hash()
    url, key = get_supabase_creds()

    if action == "set":
        if not new_pin or len(new_pin) < 3:
            return jsonify({"ok": False, "message": "Secret Sync Key / PIN minimal 3 karakter (contoh: DCA2029-RAHASIA)."}), 400

        # Jika di database sudah ada PIN, dan new_pin cocok dengan stored_hash -> berarti user sedang login di perangkat baru (HP/Laptop)
        if stored_hash and hash_pin(new_pin) == stored_hash:
            return jsonify({
                "ok": True,
                "pin_protected": True,
                "message": "Secret Sync Key cocok! Perangkat ini berhasil terhubung & tersinkronisasi."
            })

        # Jika di database sudah ada PIN, dan user ingin mengganti PIN baru, harus tahu current_pin lama
        if stored_hash and hash_pin(current_pin) != stored_hash:
            return jsonify({
                "ok": False,
                "locked": True,
                "message": "Database Cloud sudah dikunci dengan Secret Sync Key lain. Masukkan Sync Key yang sama dengan yang Anda atur di perangkat pertama!"
            }), 401

        new_hash = hash_pin(new_pin)
        if url and key:
            sb_request("DELETE", "workout_logs", "day_key=eq.__pin_guard__")
            guard_row = {
                "date": "2099-12-31",
                "day_key": "__pin_guard__",
                "focus_area": "SYSTEM_PIN_GUARD",
                "duration_min": 0,
                "avg_weight_kg": 0,
                "total_sets": 0,
                "total_reps": 0,
                "total_volume_kg": 0,
                "calories_burned": 0,
                "rpe": 1,
                "avg_hr": 0,
                "notes": new_hash,
            }
            sb_request("POST", "workout_logs", body=guard_row)
        else:
            conn = get_db_connection()
            conn.execute("DELETE FROM workout_logs WHERE day_key = '__pin_guard__'")
            conn.execute(
                """
                INSERT INTO workout_logs
                (date, day_key, focus_area, duration_min, avg_weight_kg, total_sets, total_reps, total_volume_kg, calories_burned, rpe, avg_hr, notes)
                VALUES ('2099-12-31', '__pin_guard__', 'SYSTEM_PIN_GUARD', 0, 0, 0, 0, 0, 0, 1, 0, ?)
                """,
                (new_hash,),
            )
            conn.commit()
            conn.close()

        return jsonify({
            "ok": True,
            "pin_protected": True,
            "message": "Secret Sync Key / PIN berhasil dikunci di Cloud! Masukkan kode yang sama di perangkat lain (HP/Desktop)."
        })

    if action == "unlock_off":
        if stored_hash and hash_pin(current_pin) != stored_hash:
            return jsonify({"ok": False, "message": "Secret Sync Key saat ini tidak cocok."}), 401
        if url and key:
            sb_request("DELETE", "workout_logs", "day_key=eq.__pin_guard__")
        else:
            conn = get_db_connection()
            conn.execute("DELETE FROM workout_logs WHERE day_key = '__pin_guard__'")
            conn.commit()
            conn.close()
        return jsonify({"ok": True, "pin_protected": False, "message": "Kunci PIN Cloud dinonaktifkan."})

    ok, msg = verify_request_pin()
    return jsonify({"ok": ok, "pin_protected": bool(stored_hash), "message": msg or "PIN valid"}), (200 if ok else 401)


@app.route("/api/status", methods=["GET"])
def api_status():
    url, key = get_supabase_creds()
    stored_hash = get_stored_pin_hash()
    pin_ok, pin_msg = verify_request_pin()
    if not url or not key:
        return jsonify({
            "cloud_connected": False,
            "pin_protected": bool(stored_hash),
            "pin_verified": pin_ok,
            "storage_mode": "local_fallback",
            "reason": "Environment Variable SUPABASE_URL atau SUPABASE_KEY belum terbaca di Vercel."
        })
    rows, err = sb_request("GET", "workout_logs", "select=id&limit=1")
    if err:
        return jsonify({
            "cloud_connected": False,
            "pin_protected": bool(stored_hash),
            "pin_verified": pin_ok,
            "storage_mode": "supabase_error",
            "reason": f"Koneksi ke Supabase gagal ({err})."
        })
    return jsonify({
        "cloud_connected": True,
        "pin_protected": bool(stored_hash),
        "pin_verified": pin_ok,
        "storage_mode": "supabase_cloud",
        "reason": pin_msg if not pin_ok else "Terhubung penuh ke Supabase PostgreSQL (HP & Laptop Sinkron Otomatis)"
    })


@app.route("/api/workouts", methods=["GET", "POST"])
def handle_workouts():
    pin_ok, pin_msg = verify_request_pin()
    if not pin_ok:
        return jsonify({"error": pin_msg, "pin_required": True}), 401

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
        rows, err = sb_request("GET", "workout_logs", "day_key=not.in.(__sync_state__,__pin_guard__)&order=date.desc,id.desc")
        if not err and rows is not None:
            return jsonify(rows)

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM workout_logs WHERE day_key NOT IN ('__sync_state__', '__pin_guard__') ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/workouts/<int:log_id>", methods=["DELETE"])
def delete_workout(log_id):
    pin_ok, pin_msg = verify_request_pin()
    if not pin_ok:
        return jsonify({"error": pin_msg, "pin_required": True}), 401

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
    pin_ok, pin_msg = verify_request_pin()
    if not pin_ok:
        return jsonify({"error": pin_msg, "pin_required": True}), 401

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
    pin_ok, pin_msg = verify_request_pin()
    if not pin_ok:
        return jsonify({"error": pin_msg, "pin_required": True}), 401

    url, key = get_supabase_creds()
    if request.method == "POST":
        data = request.get_json() or {}
        state_str = json.dumps(data)
        if url and key:
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
