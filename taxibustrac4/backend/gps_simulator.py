# gps_simulator.py

vehicle_locations = {
    "TAXI001": [12.9716, 77.5946],
    "TAXI002": [12.9352, 77.6146],
    "TAXI003": [12.9487, 77.5725],
    "TAXI004": [12.9256, 77.6301],
    "TAXI005": (12.9864, 77.6035),
    "TAXI006": (12.9129, 77.6444),
    "TAXI007": (13.0012, 77.5706)
}

vehicle_types = {
    "TAXI001": "sedan",
    "TAXI002": "SUV",
    "TAXI003": "mini",
    "TAXI004": "SUV",
    "TAXI005":"mini",
    "TAXI006":"sedan",
    "TAXI007":"SUV"
}

DESTINATIONS = {}
ARRIVAL_STATUS = {}
PICKUP_POINTS = {}
REACHED_PICKUP = set()

def get_location(vehicle_id):
    return vehicle_locations.get(vehicle_id, (None, None))

def update_location(vehicle_id):
    pass  # reserved for future use

def move_towards_destination(vehicle_id, step_size=0.0005):
    current = vehicle_locations.get(vehicle_id)
    if not current:
        return

    # Decide the target location: pickup or drop
    if vehicle_id in PICKUP_POINTS and vehicle_id not in REACHED_PICKUP:
        target = PICKUP_POINTS[vehicle_id]
    elif vehicle_id in DESTINATIONS:
        target = DESTINATIONS[vehicle_id]
    else:
        return

    lat1, lon1 = current
    lat2, lon2 = target

    # Check if already close enough to the destination
    if abs(lat2 - lat1) < 0.0001 and abs(lon2 - lon1) < 0.0001:
        vehicle_locations[vehicle_id] = [lat2, lon2]
        if vehicle_id in PICKUP_POINTS and vehicle_id not in REACHED_PICKUP:
            REACHED_PICKUP.add(vehicle_id)
        return

    # Move gradually toward target
    new_lat = lat1 + step_size if lat1 < lat2 else lat1 - step_size
    new_lon = lon1 + step_size if lon1 < lon2 else lon1 - step_size
    vehicle_locations[vehicle_id] = [new_lat, new_lon]
