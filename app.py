import streamlit as st
import google.generativeai as genai
import requests
import urllib.parse

# --- PAGE SETUP ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")
st.title("🔬 Cambridge Science Tutor")

# --- API SETUP ---
# 1. Google Gemini Key
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Missing Google API Key.")
    st.stop()

# 2. Pollinations Key
pollinations_key = None
if "POLLINATIONS_API_KEY" in st.secrets:
    pollinations_key = st.secrets["POLLINATIONS_API_KEY"]
    st.sidebar.success("✅ Pollinations API Key loaded")
else:
    st.sidebar.warning("⚠️ Using Free Image Mode (No Key Found)")

# --- THE BRAIN (Gemini) ---
system_instruction = """
You are a Science Tutor.
1. Answer science questions clearly.
2. If asked for a diagram/image, output this EXACT command:
   IMAGE_GEN: [Detailed description of the image, photorealistic, NO TEXT]
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", 
    system_instruction=system_instruction
)

# --- SMART IMAGE DOWNLOADER ---
def get_image_smart(prompt):
    # Clean the prompt for URLs
    encoded_prompt = urllib.parse.quote(prompt)
    
    # STRATEGY A: Try Authenticated (Private) API first
    if pollinations_key:
        url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        headers = {"Authorization": f"Bearer {pollinations_key}"}
        
        try:
            st.toast(f"Trying Private API...", icon="🔒")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.content
            else:
                # PRINT THE ERROR SO WE CAN SEE IT
                st.warning(f"Private API Failed (Error {response.status_code}). Switching to Public...")
                st.write(f"Debug Info: {response.text}") # specific debug info
        except Exception as e:
            st.warning(f"Private API Connection Error: {e}")

    # STRATEGY B: Fallback to Public API
    url_public = f"https://image.pollinations.ai/prompt/{encoded_prompt}?nologo=true"
    try:
        st.toast(f"Using Public API...", icon="🌍")
        response = requests.get(url_public, timeout=15)
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"Public API also failed: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Total Failure: {e}")
        return None

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"], caption=message.get("caption"))
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask for a diagram..."):
    
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Text Generation
                history = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.messages if not m.get("is_image")]
                chat = model.start_chat(history=history)
                response = chat.send_message(prompt)
                response_text = response.text.strip()
                
                # Image Check
                if response_text.startswith("IMAGE_GEN:"):
                    image_prompt = response_text.replace("IMAGE_GEN:", "").strip()
                    st.markdown(f"🎨 *Generating: {image_prompt}...*")
                    
                    # CALL THE SMART FUNCTION
                    image_data = get_image_smart(image_prompt)
                    
                    if image_data:
                        st.image(image_data, caption=image_prompt)
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": image_data, 
                            "is_image": True, 
                            "caption": image_prompt
                        })
                else:
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text, "is_image": False})
                
            except Exception as e:
                st.error(f"Error: {e}")
