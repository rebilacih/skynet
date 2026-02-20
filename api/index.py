from flask import Flask, request, jsonify, render_template, session, redirect
import psycopg2
import os
import datetime
import random
import string

app = Flask(__name__)
app.secret_key = 'super_secret_admin_key' # Change this
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'password123')

def get_db_connection():
    conn = psycopg2.connect(os.environ['POSTGRES_URL'])
    return conn

# --- API ROUTES (FOR AHK MACRO) ---
@app.route('/api/macro', methods=['POST'])
def macro_api():
    data = request.get_json()
    action = data.get('action')
    hwid = data.get('hwid')
    
    if not hwid:
        return jsonify({"error": "No HWID"}), 400

    conn = get_db_connection()
    c = conn.cursor()

    if action in ['check', 'heartbeat']:
        c.execute("SELECT * FROM users WHERE hwid=%s", (hwid,))
        user = c.fetchone()
        
        if user:
            if user[2]: # is_banned boolean
                conn.close()
                return jsonify({"banned": True})
            
            # Update last seen
            c.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE hwid=%s", (hwid,))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "username": user[1]})
        else:
            conn.close()
            return jsonify({"auth_required": True})

    elif action == 'activate':
        key = data.get('key')
        c.execute("SELECT * FROM keys WHERE key_string=%s AND is_used=FALSE", (key,))
        valid_key = c.fetchone()
        
        if valid_key:
            username = data.get('username', 'Unknown User')
            c.execute("INSERT INTO users (hwid, username) VALUES (%s, %s) ON CONFLICT (hwid) DO NOTHING", (hwid, username))
            c.execute("UPDATE keys SET is_used=TRUE, assigned_hwid=%s WHERE key_string=%s", (hwid, key))
            conn.commit()
            conn.close()
            return jsonify({"success": True})
        
        conn.close()
        return jsonify({"error": "Invalid Key"})

    return jsonify({"error": "Invalid Action"})

# --- WEBSITE ROUTES (GUI) ---
@app.route('/', methods=['GET', 'POST'])
def dashboard():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            
    is_admin = session.get('admin', False)
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    conn.close()
    
    online_count = 0
    formatted_users = []
    for u in users:
        # u = (hwid, username, is_banned, last_seen)
        is_online = (datetime.datetime.now() - u[3]).total_seconds() < 300 if u[3] else False
        if is_online: online_count += 1
        formatted_users.append({"hwid": u[0], "name": u[1], "online": is_online})

    return render_template('index.html', admin=is_admin, users=formatted_users, total=len(users), online=online_count)

@app.route('/generate_key')
def generate_key():
    if not session.get('admin'): return redirect('/')
    
    new_key = "SK-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO keys (key_string) VALUES (%s)", (new_key,))
    conn.commit()
    conn.close()

    return f"New Key Generated: {new_key} <br><a href='/'>Back to Dashboard</a>"
