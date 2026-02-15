import streamlit as st
import google.generativeai as genai
import requests
import io
import urllib.parse
import os
import base64

# --- PAGE SETUP ---
st.set_page_config(page_title="EpiSTEMo Science Tutor", page_icon="🧬", layout="centered")

# --- CUSTOM ICONS (SVG Base64 to ensure they always load) ---
def get_icon(color):
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="48" fill="{color}" />
        <circle cx="50" cy="35" r="15" fill="white" opacity="0.9"/>
        <path d="M25 80c0-15 10-25 25-25s25 10 25 25" stroke="white" stroke-width="5" fill="none" stroke-linecap="round" opacity="0.9"/>
    </svg>
    """
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

USER_ICON = get_icon("#007bff") # Vibrant Blue
AI_ICON = get_icon("#2dd4bf")   # Greenish Teal

# --- CSS STYLING (Green Theme & Inter Black) ---
st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@900&display=swap');

    /* Global Green Background */
    .stApp {{
        background-color: #022c22;
        color: white;
    }}

    /* Top and Bottom Bars - Dark Green to match theme */
    header[data-testid="stHeader"], div[data-testid="stBottom"] {{
        background-color: #022c22 !important;
    }}

    /* Chat Input Box */
    div[data-testid="stChatInput"] textarea {{
        background-color: #064e3b !important;
        color: white !important;
        border: 1px solid #10b981 !important;
        border-radius: 12px !important;
    }}

    /* Title Styling - Inter Black */
    .main-title {{
        font-family: 'Inter', sans-serif;
        font-weight: 900;
        font-size: 72px;
        letter-spacing: -5px;
        color: #ffffff;
        text-align: center;
        margin-top: -20px;
        text-transform: uppercase;
    }}

    .subtitle {{
        font-family: 'Inter', sans-serif;
        text-align: center;
        color: #2dd4bf;
        font-size: 14px;
        font-weight: bold;
        letter-spacing: 3px;
        margin-bottom: 30px;
        text-transform: uppercase;
    }}

    /* Chat Bubble Design - Clean and Modern */
    [data-testid="stChatMessage"] {{
        background-color: #064e3b;
        border-radius: 15px;
        padding: 15px;
        margin-bottom: 10px;
        border: 1px solid #065f46;
    }}

    /* Adjust avatar size */
    [data-testid="stChatMessageAvatar"] {{
        width: 40px;
        height: 40px;
    }}
    </style>
    
    <div class="main-title">EPISTEMO</div>
    <div class="subtitle">Cambridge Science Intelligence</div>
    """, unsafe_allow_html=True)

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Missing Google API Key in Secrets.")
    st.stop()

pollinations_key = st.secrets.get("POLLINATIONS_API_KEY")

# --- SYSTEM INSTRUCTIONS ---
system_instructions = """
You are Epi, a friendly and brilliant Cambridge Science Tutor for Stage 7-9 students.

IDENTITY:
- Name: Epi.
- Remind user ONCE: "Reminder: Stage = Grade + 1 (e.g., 8th Grade = Stage 9)."

SOURCE RULES:
- Priority 1: Use CIE_7_WB.pdf, CIE_8_WB.pdf, or CIE_9_WB.pdf. Cite as "(Source: [File Name])".
- Priority 2: If not in books, use Google Search and say "Not in workbook, but my sensors found...".

IMAGE_GEN:
- Output: IMAGE_GEN: [Detailed description, white background, with labels]

EXAM STRUCTURE:
- Section A: 5 MCQ (1 mark).
- Section B: 10 Short (2 marks).
- Section C: 6 Long (3 marks).
- Section D: 2 Think Like a Scientist (5 marks).
- Include full Answer Key.
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", 
    system_instruction=system_instructions
)

# --- FILE HANDLING ---
@st.cache_resource
def upload_textbooks():
    pdf_filenames = ["CIE_7_WB.pdf", "CIE_8_WB.pdf", "CIE_9_WB.pdf"] 
    active_files = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                uploaded_file = genai.upload_file(path=fn, display_name=fn)
                active_files.append(uploaded_file)
            except Exception:
                pass
    return active_files

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "textbook_handles" not in st.session_state:
    with st.spinner("Epi is syncing Science Workbooks..."):
        st.session_state.textbook_handles = upload_textbooks()

# --- IMAGE FUNCTION ---
def get_image_authenticated(prompt):
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}?nologo=true"
    headers = {}
    if pollinations_key:
        headers["Authorization"] = f"Bearer {pollinations_key}"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.content
    except:
        return None
    return None

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    avatar = USER_ICON if message["role"] == "user" else AI_ICON
    with st.chat_message(message["role"], avatar=avatar):
        if message.get("is_image"):
            st.image(message["content"], caption=message.get("caption"))
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Message Epi..."):
    # User Message
    st.chat_message("user", avatar=USER_ICON).markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    # Assistant Message
    with st.chat_message("assistant", avatar=AI_ICON):
        with st.spinner("Processing..."):
            try:
                history = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.messages if not m.get("is_image")]
                chat = model.start_chat(history=history)
                
                response = chat.send_message(st.session_state.textbook_handles + [prompt])
                response_text = response.text.strip()
                
                if "IMAGE_GEN:" in response_text:
                    text_parts = response_text.split("IMAGE_GEN:")[0].strip()
                    if text_parts: st.markdown(text_parts)
                    
                    image_prompt = response_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    st.write(f"🧬 *Epi is rendering: {image_prompt}*")
                    image_data = get_image_authenticated(image_prompt)
                    
                    if image_data:
                        st.image(image_data, caption=image_prompt)
                        st.session_state.messages.append({
                            "role": "assistant", "content": image_data, 
                            "is_image": True, "caption": image_prompt
                        })
                else:
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text, "is_image": False})
                
            except Exception as e:
                st.error(f"Epi connection error: {e}")
