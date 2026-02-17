from google import genai
import os
import time

api_key = "YOUR_API_KEY_HERE"
client = genai.Client(api_key=api_key)

# Test with ONE file
test_file = "CIE_7_SB_Math.pdf"  # Pick one that exists

print(f"Uploading {test_file}...")
uploaded = client.files.upload(file=test_file)

print(f"File URI: {uploaded.uri}")
print(f"File State: {uploaded.state.name}")

# Wait for active
while uploaded.state.name == "PROCESSING":
    time.sleep(1)
    uploaded = client.files.get(name=uploaded.name)
    print(f"Waiting... State: {uploaded.state.name}")

print(f"Final State: {uploaded.state.name}")

# Try to use it
response = client.models.generate_content(
    model="gemini-1.5-flash",
    contents=[uploaded, "What subject is this textbook about?"]
)

print(f"Response: {response.text}")
