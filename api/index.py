from flask import Flask, request, jsonify, render_template, session, redirect
import psycopg2
import os
import datetime
import random
import string

app = Flask(__name__, template_folder='templates')
app.secret_key = 'super_secret_admin_key' 
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'password123')

def get_db_connection():
    conn = psycopg2.connect(os.environ['POSTGRES_URL'])
    return conn

@app.route('/api/macro', methods=['POST'])
def macro_api():
    data = request.get_json()
    action = data.get('action')
    hwid = data.get('hwid')
    
    if not hwid: return jsonify({"error": "No HWID"}), 400

    conn = get_db_connection()
    c = conn.cursor()

    if action in ['check', 'heartbeat']:
        c.execute("SELECT * FROM users WHERE hwid=%s", (hwid,))
        user = c.fetchone()
        
        if user:
            if user[2]: # is_banned
                conn.close()
                return jsonify({"banned": True})
            c.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE hwid=%s", (hwid,))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "username": user[1]})
        else:
            # NEW: Create "Unknown User" profile on first-ever boot
            c.execute("INSERT INTO users (hwid, username, is_banned, last_seen) VALUES (%s, %s, FALSE, CURRENT_TIMESTAMP)", (hwid, "Unknown User"))
            conn.commit()
            conn.close()
            return jsonify({"auth_required": True})

    elif action == 'disconnect':
        past_time = datetime.datetime.now() - datetime.timedelta(minutes=10)
        c.execute("UPDATE users SET last_seen=%s WHERE hwid=%s", (past_time, hwid))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

   elif action == 'activate':
        key = data.get('key')
        
        # The crucial fix: Adding "AND is_used=FALSE" ensures a key can only be activated once
        c.execute("SELECT intended_username, use_count FROM keys WHERE key_string=%s AND is_used=FALSE", (key,))
        valid_key = c.fetchone()
        
        if valid_key:
            assigned_name = valid_key[0] or "Unknown User"
            new_use_count = (valid_key[1] or 0) + 1
            
            # Ensure the user exists, then update their profile with the assigned name
            c.execute("INSERT INTO users (hwid, username, is_banned, last_seen) VALUES (%s, %s, FALSE, CURRENT_TIMESTAMP) ON CONFLICT (hwid) DO NOTHING", (hwid, assigned_name))
            c.execute("UPDATE users SET username=%s WHERE hwid=%s", (assigned_name, hwid))
            
            # Lock the key so it can never be used by another device
            c.execute("UPDATE keys SET is_used=TRUE, assigned_hwid=%s, use_count=%s WHERE key_string=%s", (hwid, new_use_count, key))
            conn.commit()
            conn.close()
            return jsonify({"success": True})
        
        conn.close()
        return jsonify({"error": "Invalid or Already Used Key"})
# ... (Keep dashboard, logout, generate_key, delete_key, ban_user, unban_user, delete_user same as before)

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            
    is_admin = session.get('admin', False)
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT hwid, username, is_banned, last_seen FROM users")
    users = c.fetchall()
    
    keys = []
    if is_admin:
        c.execute("SELECT key_string, is_used, assigned_hwid, intended_username, use_count FROM keys")
        keys = [{"key": k[0], "used": k[1], "hwid": k[2], "intended": k[3], "uses": k[4] or 0} for k in c.fetchall()]
        
    conn.close()
    
    online_count = 0
    formatted_users = []
    for u in users:
        is_online = (datetime.datetime.now() - u[3]).total_seconds() < 300 if u[3] else False
        if is_online and not u[2]: online_count += 1
        formatted_users.append({"hwid": u[0], "name": u[1], "is_banned": u[2], "online": is_online})

    return render_template('index.html', admin=is_admin, users=formatted_users, keys=keys, total=len(users), online=online_count)

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect('/')

@app.route('/generate_key', methods=['POST'])
def generate_key():
    if not session.get('admin'): return redirect('/')
    intended_user = request.form.get('username', 'Unnamed User')
    new_key = "SK-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO keys (key_string, intended_username, use_count) VALUES (%s, %s, 0)", (new_key, intended_user))
    conn.commit()
    conn.close()
    return redirect('/')

# --- KEY MANAGEMENT ---
@app.route('/delete_key/<key_string>', methods=['POST'])
def delete_key(key_string):
    if not session.get('admin'): return redirect('/')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM keys WHERE key_string=%s", (key_string,))
    conn.commit()
    conn.close()
    return redirect('/')

# --- USER MANAGEMENT ---
@app.route('/ban_user/<hwid>', methods=['POST'])
def ban_user(hwid):
    if not session.get('admin'): return redirect('/')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=TRUE WHERE hwid=%s", (hwid,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/unban_user/<hwid>', methods=['POST'])
def unban_user(hwid):
    if not session.get('admin'): return redirect('/')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=FALSE WHERE hwid=%s", (hwid,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/delete_user/<hwid>', methods=['POST'])
def delete_user(hwid):
    if not session.get('admin'): return redirect('/')
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Detach the user's HWID from their key and make the key available again
    c.execute("UPDATE keys SET assigned_hwid=NULL, is_used=FALSE WHERE assigned_hwid=%s", (hwid,))
    
    # 2. Now that the link is broken, safely delete the user profile
    c.execute("DELETE FROM users WHERE hwid=%s", (hwid,))
    
    conn.commit()
    conn.close()
    return redirect('/')



