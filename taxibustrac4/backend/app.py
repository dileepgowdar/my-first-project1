# app.py

from flask import Flask, jsonify, request, render_template, redirect, session, send_file, url_for
from flask_cors import CORS
from gps_simulator import get_location, update_location, vehicle_locations, vehicle_types, DESTINATIONS, ARRIVAL_STATUS, move_towards_destination, REACHED_PICKUP, PICKUP_POINTS
from math import radians, sin, cos, sqrt, atan2
import sqlite3, time, csv, requests

app = Flask(__name__)
app.secret_key = 'secret123'
CORS(app)

DB_PATH = 'vehicle_tracking.db'
USER_BOOKINGS = {}
USER_DESTINATIONS = {}
STATUSES = {}
RIDE_ACCEPTED={}
ADMIN_NOTIFIED = set()
already_notified = {}
# DB setup
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS location_history (vehicle_id TEXT, latitude REAL, longitude REAL, timestamp TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS destinations (vehicle_id TEXT PRIMARY KEY, latitude REAL, longitude REAL)")
    # Add this to your init_db() function
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        vehicle_id TEXT
        )
    """)
    # Inside init_db() after table creation
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, vehicle_id) VALUES (?, ?, ?, ?)",
              ('admin', 'admin123', 'admin', None))

    conn.commit()
    conn.close()

def load_destinations():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT vehicle_id, latitude, longitude FROM destinations")
    for v_id, lat, lng in c.fetchall():
        DESTINATIONS[v_id] = (lat, lng)
    conn.close()

init_db()
load_destinations()

# Helpers
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def geocode_place(place_name):
    url = f"https://nominatim.openstreetmap.org/search?q={place_name}, Bangalore&format=json&limit=1"
    response = requests.get(url, headers={'User-Agent': 'TaxiApp/1.0'})
    data = response.json()
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    return None, None

# Routes
@app.route('/welcome')
def welcome():
    return render_template("welcome.html")

@app.route('/')
def login_page():
    return render_template("taxilog.html")

@app.route('/admin_register', methods=['GET', 'POST'])
def admin_register():
    secret_key = request.args.get("key")  # like ?key=secure123
    if secret_key != "secure123":  # Replace with your real secret
        return "Unauthorized access", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, role, vehicle_id) VALUES (?, ?, 'admin', NULL)",
                      (username, password))
            conn.commit()
        except sqlite3.IntegrityError:
            return "Admin username already exists"
        conn.close()
        return redirect('/login')
    return render_template('admin_register.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        vehicle_id = request.form.get('vehicle_id', None)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, role, vehicle_id) VALUES (?, ?, ?, ?)",
                      (username, password, role, vehicle_id))
            conn.commit()
        except sqlite3.IntegrityError:
            return "Username already exists"
        conn.close()
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT password, role, vehicle_id FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        conn.close()

        if not result or result[0] != password:
            return "Invalid username or password"

        role, vehicle_id = result[1], result[2]
        session['username'] = username
        session['role'] = role
        session['vehicle_id'] = vehicle_id

        if role == 'admin':
            return redirect('/index')
        elif role == 'driver' and vehicle_id:
            return redirect(f"/driver?vehicle_id={vehicle_id}&driver={username}")
        elif role == 'user':
            return redirect("/user")
    return render_template('taxilog.html')

@app.route('/index')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template("index.html", role=session['role'], username=session['username'])

@app.route('/driver')
def driver():
    return render_template("driver.html")

@app.route('/user')
def user():
    return render_template("user.html", username=session.get("username"))

@app.route('/get_location/<vehicle_id>')
def get_vehicle_location(vehicle_id):
    if RIDE_ACCEPTED.get(vehicle_id):  # Only move if ride is accepted
        move_towards_destination(vehicle_id)
    
    lat, lng = get_location(vehicle_id)
    if lat is None:
        return jsonify({'error': 'Not Found'}), 404

    # Initialize notification flag if not already
    if vehicle_id not in already_notified:
        already_notified[vehicle_id] = False

    # Save location history
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO location_history VALUES (?, ?, ?, ?)",
              (vehicle_id, lat, lng, time.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

    # Check pickup/drop status
    at_pickup = False
    at_drop = False

    if vehicle_id in PICKUP_POINTS and vehicle_id not in REACHED_PICKUP:
        dest = PICKUP_POINTS[vehicle_id]
        dist_to_pickup = haversine(lat, lng, dest[0], dest[1])
        if dist_to_pickup < 0.05:
            at_pickup = True
    else:
        dest = DESTINATIONS.get(vehicle_id, (12.9352, 77.6146))
        dist_to_drop = haversine(lat, lng, dest[0], dest[1])
        if dist_to_drop < 0.05 and vehicle_id in REACHED_PICKUP:
            at_drop = True

    # Notify admin only once per vehicle at drop
    if at_drop and not already_notified[vehicle_id]:
        print(f"[INFO] Vehicle {vehicle_id} has reached the destination. Notify admin here.")
        already_notified[vehicle_id] = True

    # Distance/ETA update
    dist_km = haversine(lat, lng, dest[0], dest[1])
    eta_min = round((dist_km / 30) * 60, 2)
    ARRIVAL_STATUS[vehicle_id] = dist_km < 0.05

    return jsonify({
        "vehicle_id": vehicle_id,
        "latitude": lat,
        "longitude": lng,
        "eta_minutes": eta_min,
        "distance_km": round(dist_km, 2),
        "status": STATUSES.get(vehicle_id, "Not Set"),
        "destination": {"lat": dest[0], "lng": dest[1]},
        "arrived": ARRIVAL_STATUS[vehicle_id],
        "ride_accepted": RIDE_ACCEPTED.get(vehicle_id) == True,
        "waiting_for_user": vehicle_id in PICKUP_POINTS and vehicle_id in USER_BOOKINGS.values() and RIDE_ACCEPTED.get(vehicle_id) is None,
        "at_pickup": at_pickup,
        "at_drop": at_drop
    })

@app.route('/book_taxi_auto', methods=['POST'])
def book_taxi_auto():
    data = request.get_json()
    username = data.get("username")
    pickup_name = data.get("pickup")
    drop_name = data.get("drop")

    if not (username and pickup_name and drop_name):
        return jsonify({"success": False, "error": "Missing fields"}), 400

    pickup_lat, pickup_lng = geocode_place(pickup_name)
    drop_lat, drop_lng = geocode_place(drop_name)
    if pickup_lat is None or drop_lat is None:
        return jsonify({"success": False, "error": "Geocoding failed"}), 400

    # Auto-assign first available vehicle
    available_vehicles = {
        v_id: get_location(v_id)
        for v_id in vehicle_locations
        if v_id not in USER_BOOKINGS.values()
    }
    if not available_vehicles:
        return jsonify({"success": False, "error": "No available vehicles"}), 400

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))
    vehicle_id, _ = min(
        available_vehicles.items(),
        key=lambda item: haversine(pickup_lat, pickup_lng, item[1][0], item[1][1])
    )

    USER_BOOKINGS[username] = vehicle_id
    vehicle_lat, vehicle_lng = get_location(vehicle_id)
    dist_km = haversine(vehicle_lat, vehicle_lng, pickup_lat, pickup_lng)
    eta_min = round((dist_km / 30) * 60, 2)

    DESTINATIONS[vehicle_id] = (pickup_lat, pickup_lng)
    PICKUP_POINTS[vehicle_id] = (pickup_lat, pickup_lng)
    REACHED_PICKUP.discard(vehicle_id)
    USER_DESTINATIONS[vehicle_id] = {
        "pickup": (pickup_lat, pickup_lng),
        "drop": (drop_lat, drop_lng),
        "pickup_name": pickup_name,
        "drop_name": drop_name,
    }
    RIDE_ACCEPTED[vehicle_id] = None

    return jsonify({
        "success": True,
        "vehicle_id": vehicle_id,
        "eta": eta_min,
        "pickup": {"lat": pickup_lat, "lng": pickup_lng},
        "drop": {"lat": drop_lat, "lng": drop_lng}
    })

@app.route('/get_booking_info/<vehicle_id>')
def get_booking_info(vehicle_id):
    data = USER_DESTINATIONS.get(vehicle_id)
    if not data:
        return jsonify({})
    return jsonify({
        "pickup": {"lat": data["pickup"][0], "lng": data["pickup"][1]},
        "drop": {"lat": data["drop"][0], "lng": data["drop"][1]},
        "original_pickup": data.get("pickup_name"),
        "original_drop": data.get("drop_name"),
        "fare": data.get("fare", "N/A")
    })

@app.route('/estimate_fare')
def estimate_fare():
    pickup = request.args.get('pickup')
    drop = request.args.get('drop')
    vehicle_id = request.args.get('vehicle_id')

    try:
        pickup_lat, pickup_lng = map(float, pickup.split(','))
        drop_lat, drop_lng = map(float, drop.split(','))
    except:
        pickup_lat, pickup_lng = geocode_place(pickup)
        drop_lat, drop_lng = geocode_place(drop)

    if pickup_lat is None or drop_lat is None:
        return jsonify({"fare": "N/A"})

    distance_km = haversine(pickup_lat, pickup_lng, drop_lat, drop_lng)
    base_fare = 50
    per_km_rate = 15
    fare = base_fare + (distance_km * per_km_rate)

    return jsonify({"fare": round(float(fare), 2)})


@app.route('/get_user_booking/<username>')
def get_user_booking(username):
    vehicle_id = USER_BOOKINGS.get(username)
    if not vehicle_id:
        return jsonify({"vehicle_id": None})
    return jsonify({"vehicle_id": vehicle_id})

@app.route('/accept_ride', methods=['POST'])
def accept_ride():
    data = request.get_json()
    vehicle_id = data.get("vehicle_id")
    if vehicle_id:
        RIDE_ACCEPTED[vehicle_id] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Missing vehicle_id"}), 400

@app.route('/reject_ride', methods=['POST'])
def reject_ride():
    data = request.get_json()
    vehicle_id = data.get("vehicle_id")
    if vehicle_id:
        RIDE_ACCEPTED[vehicle_id] = False
        # Clear booking info
        for user, v_id in list(USER_BOOKINGS.items()):
            if v_id == vehicle_id:
                del USER_BOOKINGS[user]
        DESTINATIONS.pop(vehicle_id, None)
        USER_DESTINATIONS.pop(vehicle_id, None)
        PICKUP_POINTS.pop(vehicle_id, None)
        REACHED_PICKUP.discard(vehicle_id)
        return jsonify({"success": True, "message": "Ride rejected"})
    return jsonify({"success": False, "error": "Missing vehicle_id"}), 400

@app.route('/start_trip', methods=['POST'])
def start_trip():
    data = request.get_json()
    vehicle_id = data.get("vehicle_id")
    if vehicle_id:
        STATUSES[vehicle_id] = "Trip Started"
        return jsonify({"success": True, "message": "Trip started"})
    return jsonify({"success": False, "error": "Missing vehicle_id"}), 400

@app.route('/end_trip', methods=['POST'])
def end_trip():
    data = request.get_json()
    vehicle_id = data.get("vehicle_id")
    if vehicle_id:
        STATUSES[vehicle_id] = "Trip Ended"
        # Clear booking info after trip
        for user, v_id in list(USER_BOOKINGS.items()):
            if v_id == vehicle_id:
                del USER_BOOKINGS[user]
        DESTINATIONS.pop(vehicle_id, None)
        USER_DESTINATIONS.pop(vehicle_id, None)
        REACHED_PICKUP.discard(vehicle_id)
        ADMIN_NOTIFIED.discard(vehicle_id)
        PICKUP_POINTS.pop(vehicle_id, None)
        return jsonify({"success": True, "message": "Trip ended"})
    return jsonify({"success": False, "error": "Missing vehicle_id"}), 400

@app.route('/get_driver_profile/<username>')
def get_driver_profile(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, vehicle_id FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"username": row[0], "vehicle_id": row[1]})
    return jsonify({"error": "Driver not found"}), 404

@app.route('/get_passenger_for_vehicle/<vehicle_id>')
def get_passenger_for_vehicle(vehicle_id):
    for user, v_id in USER_BOOKINGS.items():
        if v_id == vehicle_id:
            return jsonify({"username": user})
    return jsonify({"username": None})

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.get_json()
    STATUSES[data['vehicle_id']] = data['status']
    return jsonify({"status": "updated"})

@app.route('/get_all_vehicles')
def get_all():
    return jsonify([
        {
            "vehicle_id": v,
            "latitude": get_location(v)[0],
            "longitude": get_location(v)[1],
            "type": vehicle_types.get(v, "unknown"),
            "status": STATUSES.get(v, "Not Set")
        } for v in vehicle_locations
    ])

@app.route('/get_history/<vehicle_id>')
def get_history(vehicle_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT latitude, longitude FROM location_history WHERE vehicle_id = ?", (vehicle_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"lat": r[0], "lng": r[1]} for r in rows])

@app.route('/export_csv/<vehicle_id>')
def export_csv(vehicle_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM location_history WHERE vehicle_id = ?", (vehicle_id,))
    rows = c.fetchall()
    conn.close()
    filename = f"{vehicle_id}_history.csv"
    with open(filename, "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["vehicle_id", "latitude", "longitude", "timestamp"])
        writer.writerows(rows)
    return send_file(filename, as_attachment=True)

@app.route('/confirm_pickup', methods=['POST'])
def confirm_pickup():
    data = request.get_json()
    vehicle_id = data.get("vehicle_id")
    if vehicle_id in USER_DESTINATIONS:
        DESTINATIONS[vehicle_id] = USER_DESTINATIONS[vehicle_id]["drop"]
        REACHED_PICKUP.add(vehicle_id) 
        PICKUP_POINTS.pop(vehicle_id, None)  # Clear pickup
    return jsonify({"success": True})

@app.route('/cancel_booking/<username>', methods=['POST'])
def cancel_booking(username):
    vehicle_id = USER_BOOKINGS.get(username)

    if vehicle_id:
        # ❌ Prevent cancellation after pickup to avoid data inconsistencies
        if vehicle_id in REACHED_PICKUP:
            return jsonify({"success": False, "message": "Cannot cancel after trip has started."})

        # ✅ Safe to cancel
        USER_BOOKINGS.pop(username, None)
        DESTINATIONS.pop(vehicle_id, None)
        USER_DESTINATIONS.pop(vehicle_id, None)
        PICKUP_POINTS.pop(vehicle_id, None)
        RIDE_ACCEPTED.pop(vehicle_id, None)

        return jsonify({"success": True, "message": "Booking canceled"})

    return jsonify({"success": False, "message": "No active booking found"})



if __name__ == '__main__':
    app.run(debug=True)
