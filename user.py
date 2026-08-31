# add_user.py
import json
import hashlib
import secrets

def hash_password(password):
    salt = secrets.token_hex(16)
    iterations = 390000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"

# Change these values
USERNAME = "umarwani484@gmail.com"
PASSWORD = "your_password_here"  # Change this!
ROLE = "ADMIN"  # or "AUDIT"

# Generate hash
password_hash = hash_password(PASSWORD)

# Load users.json
try:
    with open('users.json', 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    data = {"users": []}

# Check if user exists
for user in data['users']:
    if user['username'] == USERNAME:
        print(f"❌ User '{USERNAME}' already exists!")
        print(f"   Role: {user['role']}")
        print(f"   Hash: {user['password_hash'][:30]}...")
        exit()

# Add user
data['users'].append({
    "username": USERNAME,
    "role": ROLE,
    "password_hash": password_hash
})

# Save
with open('users.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"✅ User added successfully!")
print(f"   Username: {USERNAME}")
print(f"   Password: {PASSWORD}")
print(f"   Role: {ROLE}")
print(f"   Hash: {password_hash[:30]}...")