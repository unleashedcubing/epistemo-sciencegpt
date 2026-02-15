import streamlit as st
import google.generativeai as genai
import requests
import io
import urllib.parse
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="EpiSTEMo Science Tutor", page_icon="🧬", layout="centered")

# --- CUSTOM CSS (Themed Colors & Inter Black) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@900&display=swap');

    /* Main Background - Forest Green */
    .stApp {
        background-color: #022c22;
        color: white;
    }

    /* Top Bar Styling */
    header[data-testid="stHeader"] {
        background-color: #0f172a !important; /* Dark Blue Top Bar */
    }

    /* Bottom Bar & Input Container */
    div[data-testid="stBottom"] {
        background-color: #0f172a !important; /* Dark Blue Bottom Bar */
    }

    /* Chat Input Text Box */
    div[data-testid="stChatInput"] textarea {
        background-color: #1e293b !important; /* Slightly lighter Navy */
        color: white !important;
        border: 1px solid #334155 !important;
        border-radius: 10px !important;
    }

    /* Title Styling */
    .main-title {
        font-family: 'Inter', sans-serif;
        font-weight: 900;
        font-size: 72px;
        letter-spacing: -5px; /* Tight tracking */
        color: #f8fafc;
        text-align: center;
        padding-top: 20px;
        text-transform: uppercase;
    }

    .subtitle {
        font-family: 'Inter', sans-serif;
        text-align: center;
        color: #2dd4bf; /* Greenish Teal */
        font-size: 14px;
        font-weight: bold;
        letter-spacing: 3px;
        margin-bottom: 40px;
        text-transform: uppercase;
    }

    /* Chat Message Bubble Styling */
    .stChatMessage {
        border-radius: 15px;
        margin-bottom: 10px;
    }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    
    <div class="main-title">EPISTEMO</div>
    <div class="subtitle">Cambridge Science Intelligence</div>
    """, unsafe_allow_html=True)

# --- AVATAR DEFINITIONS (Blue User, Teal AI) ---
USER_AVATAR = "🔵" 
AI_AVATAR = "🟢" # We use colored emojis or SVG paths for colored icons

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

IDENTITY RULES:
- Your name is Epi.
- Remind the user ONLY ONCE per session: "Reminder: Your Stage is your Grade + 1 (e.g., if you are in 8th Grade, we use Stage 9 materials)."

CONTENT RULES:
- Priority 1 (Source): Use CIE_7_WB.pdf, CIE_8_WB.pdf, or CIE_9_WB.pdf. Cite as "(Source: [File Name])".
- Priority 2 (Web): If not in books, say "Epi couldn't find this in the workbook, but here is what my sensors found online:" then search.

IMAGE GENERATION:
- Output: IMAGE_GEN: [Detailed description, white background, with labels]

EXAM STRUCTURE:
- Section A: 5 MCQ (1 mark).
- Section B: 10 Short (2 marks).
- Section C: 6 Long (3 marks).
- Section D: 2 Think Like a Scientist (HARD) (5 marks).
- Provide Full Answer Key.
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", 
    system_instruction=system_instructions
)

# --- FILE HANDLING ---
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
        response = requests.get(url, headers=headers, timeout=25)
        if response.status_code == 200:
            return response.content
    except:
        return None
    return None

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    # Set avatar based on role
    avatar_color = USER_AVATAR if message["role"] == "user" else AI_AVATAR
    with st.chat_message(message["role"], avatar=avatar_color):
        if message.get("is_image"):
            st.image(message["content"], caption=message.get("caption"))
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Message Epi..."):
    # User message with Blue Avatar
    st.chat_message("user", avatar=USER_AVATAR).markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    # Assistant message with Teal Avatar
    with st.chat_message("assistant", avatar=AI_AVATAR):
        with st.spinner("Processing..."):
            try:
                history = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.messages if not m.get("is_image")]
                chat = model.start_chat(history=history)
                
                # Attaching the Workbooks to the message
                response = chat.send_message(st.session_state.textbook_handles + [prompt])
                response_text = response.text.strip()
                
                if "IMAGE_GEN:" in response_text:
                    # Show any text before the image command
                    text_parts = response_text.split("IMAGE_GEN:")[0].strip()
                    if text_parts:
                        st.markdown(text_parts)
                    
                    image_prompt = response_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    st.write(f"🧬 *Epi is rendering visual data for: {image_prompt}*")
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
