from flask import Flask, request, jsonify, render_template, session, redirect
import psycopg2
import os
import datetime
import random
import string

app = Flask(__name__, template_folder='templates')
app.secret_key = 'super_secret_admin_key' # Change this later if you want
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
    
    # Fetch Users
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    
    # Fetch Keys (Only if admin)
    keys = []
    if is_admin:
        c.execute("SELECT * FROM keys")
        keys = [{"key": k[0], "used": k[1], "hwid": k[2]} for k in c.fetchall()]
        
    conn.close()
    
    online_count = 0
    formatted_users = []
    for u in users:
        is_online = (datetime.datetime.now() - u[3]).total_seconds() < 300 if u[3] else False
        if is_online: online_count += 1
        formatted_users.append({"hwid": u[0], "name": u[1], "online": is_online})

    return render_template('index.html', admin=is_admin, users=formatted_users, keys=keys, total=len(users), online=online_count)

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect('/')

@app.route('/generate_key', methods=['POST'])
def generate_key():
    if not session.get('admin'): return redirect('/')
    new_key = "SK-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO keys (key_string) VALUES (%s)", (new_key,))
    conn.commit()
    conn.close()
    return redirect('/') # Reloads dashboard instantly

@app.route('/delete_key/<key_string>', methods=['POST'])
def delete_key(key_string):
    if not session.get('admin'): return redirect('/')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM keys WHERE key_string=%s", (key_string,))
    conn.commit()
    conn.close()
    return redirect('/')
