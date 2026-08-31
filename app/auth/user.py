# add_user.py
import json
import subprocess
import sys

def generate_hash(password):
    """Generate password hash using the app's built-in method"""
    import hashlib
    import secrets
    
    salt = secrets.token_hex(16)
    iterations = 390000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        iterations,
    ).hex()
    
    return f"pbkdf2_sha256${iterations}${salt}${digest}"

def add_user(username, password, role="ADMIN"):
    """Add a user to users.json"""
    
    # Generate hash
    password_hash = generate_hash(password)
    
    # Load users.json
    try:
        with open('users.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"users": []}
    
    # Check if user exists
    for user in data['users']:
        if user['username'] == username:
            print(f"❌ User '{username}' already exists!")
            return
    
    # Add new user
    data['users'].append({
        "username": username,
        "role": role,
        "password_hash": password_hash
    })
    
    # Save
    with open('users.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ User '{username}' added successfully!")
    print(f"   Role: {role}")
    print(f"   Password: {password}")

if __name__ == "__main__":
    # Change these values
    USERNAME = "umarwani484@gmail.com"
    PASSWORD = "your_password_here"  # Change this!
    ROLE = "ADMIN"  # ADMIN or AUDIT
    
    add_user(USERNAME, PASSWORD, ROLE)