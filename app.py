# app.py - DIAGNOSTIC VERSION
import os
import requests
import streamlit as st
import socket
import ssl
import time
from datetime import datetime

st.set_page_config(
    page_title="DeepSeek Diagnostic",
    page_icon="🔍"
)

st.title("🔍 DeepSeek API Connection Diagnostic")
st.write(f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.write(f"**Render Instance:** {os.getenv('RENDER_INSTANCE_ID', 'Local')}")

# Check environment variables
st.header("1️⃣ Environment Variables Check")
api_key = os.getenv("OPENROUTER_API_KEY")
st.write(f"OPENROUTER_API_KEY exists: **{'✅ YES' if api_key else '❌ NO'}**")
if api_key:
    # Show first few characters to verify it's the right key
    st.write(f"Key starts with: `{api_key[:10]}...`")
    st.write(f"Key length: {len(api_key)} characters")

# Test basic internet connectivity
st.header("2️⃣ Basic Internet Connectivity")

def test_url(url, timeout=10):
    try:
        start = time.time()
        response = requests.get(url, timeout=timeout)
        end = time.time()
        return {
            "success": True,
            "status": response.status_code,
            "time": f"{end - start:.2f}s",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "status": None,
            "time": None,
            "error": str(e)
        }

# Test different endpoints
urls_to_test = [
    "https://www.google.com",
    "https://openrouter.ai",
    "https://api.openrouter.ai",
    "https://openrouter.ai/api/v1/chat/completions",
    "https://api.deepseek.com",
    "https://api.deepseek.com/v1/chat/completions"
]

for url in urls_to_test:
    result = test_url(url)
    if result["success"]:
        st.success(f"✅ {url} - Status {result['status']} ({result['time']})")
    else:
        st.error(f"❌ {url} - {result['error']}")

# Test DNS resolution
st.header("3️⃣ DNS Resolution Test")
domains = ["openrouter.ai", "api.openrouter.ai", "google.com"]

for domain in domains:
    try:
        ip = socket.gethostbyname(domain)
        st.success(f"✅ {domain} resolves to: {ip}")
    except Exception as e:
        st.error(f"❌ {domain} - {str(e)}")

# Test SSL/TLS
st.header("4️⃣ SSL/TLS Check")
try:
    context = ssl.create_default_context()
    with socket.create_connection(("openrouter.ai", 443), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname="openrouter.ai") as ssock:
            cert = ssock.getpeercert()
            st.success(f"✅ SSL OK - Certificate valid")
except Exception as e:
    st.error(f"❌ SSL Error: {str(e)}")

# Test actual API authentication
st.header("5️⃣ API Authentication Test")

if api_key:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Test 1: Simple key validation
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            st.success("✅ API key is valid!")
            st.json(response.json())
        else:
            st.error(f"❌ API key invalid: {response.status_code} - {response.text}")
    except Exception as e:
        st.error(f"❌ API key validation failed: {str(e)}")
    
    # Test 2: Test completion with minimal request
    st.header("6️⃣ Minimal API Test")
    
    minimal_payload = {
        "model": "deepseek/deepseek-chat-v3-0324:free",
        "messages": [
            {"role": "user", "content": "Say 'test successful' if you can read this"}
        ],
        "max_tokens": 10
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=minimal_payload,
            timeout=15
        )
        
        st.write(f"**Status Code:** {response.status_code}")
        st.write(f"**Response Headers:** {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            st.success("✅ API call successful!")
            st.write(f"**Response:** {result['choices'][0]['message']['content']}")
        else:
            st.error(f"❌ API Error: {response.text}")
            
    except requests.exceptions.Timeout:
        st.error("❌ Timeout - Request took too long")
    except requests.exceptions.ConnectionError as e:
        st.error(f"❌ Connection Error: {str(e)}")
    except Exception as e:
        st.error(f"❌ Other Error: {str(e)}")
else:
    st.warning("⚠️ No API key found. Add OPENROUTER_API_KEY to environment variables.")

# Network Info
st.header("7️⃣ Network Information")
try:
    # Get outbound IP
    ip_response = requests.get("https://api.ipify.org?format=json", timeout=10)
    st.write(f"**Outbound IP:** {ip_response.json()['ip']}")
    
    # Check if IP is blocked
    st.write("**Note:** Some cloud providers block AI API endpoints. If you see connection errors above,")
    st.write("you may need to contact Render support to whitelist OpenRouter domains.")
except:
    st.write("Could not determine outbound IP")

# Recommendations
st.header("8️⃣ Recommendations")

if api_key:
    if any("❌" in str(x) for x in st.session_state.values()):
        st.error("""
        **Issues detected! Try these solutions:**
        
        1. **Use DeepSeek directly instead** (Add this to your code):
        ```python
        # Switch to DeepSeek's official API
        api_url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
            "Content-Type": "application/json"
        }
        model = "deepseek-chat"
        ```
        
        2. **Contact Render Support** and ask them to whitelist:
           - openrouter.ai
           - api.openrouter.ai
        
        3. **Use a proxy** (Advanced)
        """)
    else:
        st.success("✅ All tests passed! Your configuration should work.")
else:
    st.error("""
    **❌ API Key Missing!**
    
    1. Go to Render Dashboard
    2. Select your app
    3. Click 'Environment' tab
    4. Add:
       - Key: `OPENROUTER_API_KEY`
       - Value: (your actual key from openrouter.ai)
    5. Click 'Save' and redeploy
    """)
