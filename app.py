import streamlit as st
import os
import time
import base64
from pathlib import Path
from google import genai
from google.genai import types
from audio_recorder_streamlit import audio_recorder
from gtts import gTTS

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered", initial_sidebar_state="expanded")

api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("🚨 Critical Error: GOOGLE_API_KEY not found.")
        st.stop()

try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"🚨 Failed to initialize Gemini Client: {e}")
    st.stop()

# --- 2. THEME CSS & TITLE ---
st.markdown("""
<style>
.stApp { background: radial-gradient(800px circle at 50% 0%, rgba(0, 212, 255, 0.08), rgba(0, 212, 255, 0.00) 60%), var(--background-color); color: var(--text-color); }
.big-title { font-family: 'Inter', sans-serif; color: #00d4ff; text-align: center; font-size: 48px; font-weight: 1200; letter-spacing: -3px; margin-bottom: 0px; text-shadow: 0 0 6px rgba(0, 212, 255, 0.55); }
.subtitle { text-align: center; opacity: 0.60; font-size: 18px; margin-bottom: 30px; }
.thinking-container { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background-color: var(--secondary-background-color); border-radius: 8px; margin: 10px 0; border-left: 3px solid #fc8404; }
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot { width: 6px; height: 6px; border-radius: 50%; background-color: #fc8404; animation: thinking-pulse 1.4s infinite; }
.thinking-dot:nth-child(2){ animation-delay: 0.2s; }
.thinking-dot:nth-child(3){ animation-delay: 0.4s; }
@keyframes thinking-pulse { 0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); } 30% { opacity: 1; transform: scale(1.2); } }
</style>
<div class="big-title">📚 helix.ai</div>
<div class="subtitle">Your CIE Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)

# --- 3. HELPER FUNCTIONS ---
def get_friendly_name(filename):
    if not filename: return "Cambridge Textbook"
    name = filename.replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "CIE": return filename
    grade = parts[1]
    book_type = "Workbook" if "WB" in parts else "Textbook"
    if "ANSWERS" in parts: book_type += " Answers"
    subject = "Science" if "Sci" in parts else "Math" if "Math" in parts else "English" if "Eng" in parts else "Subject"
    part_str = " (Part 1)" if "1" in parts[2:] else " (Part 2)" if "2" in parts[2:] else ""
    return f"Cambridge {subject} {book_type} {grade}{part_str}"

def autoplay_audio(text):
    """Converts AI text to speech and plays it automatically."""
    try:
        # Clean text so the AI doesn't read out markdown symbols like asterisks
        clean_text = text.replace("*", "").replace("#", "")
        # Remove image generation tags from being spoken
        clean_text = clean_text.split("IMAGE_GEN:")[0].strip()
        
        tts = gTTS(clean_text, lang='en')
        tts.save("response.mp3")
        
        with open("response.mp3", "rb") as f:
            data = f.read()
            b64 = base64.b64encode(data).decode()
            
        md = f"""
            <audio autoplay="true" style="display:none;">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            """
        st.markdown(md, unsafe_allow_html=True)
    except Exception as e:
        pass # Silently fail if TTS encounters an error so it doesn't break the chat

# --- 4. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE MULTIMODAL & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, analyze it carefully.
- If the user provides AUDIO, listen to their question and answer it directly in a conversational, spoken tone.
- You MUST search the attached PDF textbooks using OCR to verify your answers. Cite the book (Source: Cambridge Science Textbook 7).
- If the answer is not in the books, say: "I couldn't find this in your textbook, but here is what I know:" and answer normally.

### RULE 2: ASSESSMENTS
- If making a question paper/quiz, list the source(s) ONLY ONCE at the very bottom.
- Provide a point-based mark scheme.

### RULE 3: IMAGE GENERATION
- IF THE USER ASKS FOR A DIAGRAM, output ONLY this exact command:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]
"""

# --- 5. GOOGLE FILE API ---
@st.cache_resource(show_spinner=False)
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    active_files = {"sci": [], "math": [], "eng": []}
    
    msg_placeholder = st.empty()
    with msg_placeholder.chat_message("assistant"):
        st.markdown(f"""
        <div class="thinking-container">
            <span class="thinking-text">🔄 Connecting to Google Cloud & Scanning Library...</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    existing_server_files = {f.display_name.lower(): f for f in client.files.list() if f.display_name}
    pdf_map = {p.name.lower(): p for p in Path.cwd().rglob("*.pdf")}

    for target_name in target_filenames:
        t_lower = target_name.lower()
        if t_lower in existing_server_files:
            server_file = existing_server_files[t_lower]
            if server_file.state.name == "ACTIVE":
                if "sci" in t_lower: active_files["sci"].append(server_file)
                elif "math" in t_lower: active_files["math"].append(server_file)
                elif "eng" in t_lower: active_files["eng"].append(server_file)
                continue

        found_path = pdf_map.get(t_lower)
        if found_path:
            try:
                uploaded_file = client.files.upload(file=str(found_path), config={'mime_type': 'application/pdf', 'display_name': found_path.name})
                start_time = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - start_time > 180: break
                    time.sleep(3)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                
                if uploaded_file.state.name == "ACTIVE":
                    if "sci" in t_lower: active_files["sci"].append(uploaded_file)
                    elif "math" in t_lower: active_files["math"].append(uploaded_file)
                    elif "eng" in t_lower: active_files["eng"].append(uploaded_file)
            except Exception:
                continue

    msg_placeholder.empty()
    return active_files

# --- 6. STRICT ROUTING LOGIC ---
def select_relevant_books(query, file_dict):
    query = query.lower()
    selected = []
    is_math = any(k in query for k in ["math", "algebra", "geometry", "calculate", "equation"])
    is_sci = any(k in query for k in ["science", "cell", "biology", "physics", "chemistry"])
    is_eng = any(k in query for k in ["english", "poem", "story", "essay", "writing"])
    if not is_math and not is_sci and not is_eng: is_sci = True
    stage_7 = any(k in query for k in ["stage 7", "grade 6"])
    stage_8 = any(k in query for k in ["stage 8", "grade 7"])
    stage_9 = any(k in query for k in ["stage 9", "grade 8"])
    has_stage = stage_7 or stage_8 or stage_9

    def add_books(subject_key, is_active):
        if not is_active: return
        for book in file_dict.get(subject_key, []):
            name = (book.display_name or "").lower()
            if has_stage:
                if stage_7 and "cie_7" in name: selected.append(book)
                if stage_8 and "cie_8" in name: selected.append(book)
                if stage_9 and "cie_9" in name: selected.append(book)
            else:
                if "cie_8" in name: selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)
    return selected[:3] 

# --- 7. SIDEBAR (VISION & VOICE MODE) ---
with st.sidebar:
    st.title("👁️ Vision & Voice")
    
    # Vision 
    st.write("**1. Upload Homework (Optional)**")
    user_image = st.file_uploader("Show Helix a problem:", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
    
    st.divider()
    
    # Voice Mode
    st.write("🎙️ **Voice Mode**")
    st.caption("Click the mic, speak your question, then click again to send!")
    
    # The recorder widget
    voice_bytes = audio_recorder(
        text="", 
        recording_color="#e81e1e", 
        neutral_color="#00d4ff", 
        icon_name="microphone", 
        icon_size="3x"
    )
    
    # Toggle for AI speaking back
    st.write("")
    use_tts = st.toggle("🔊 AI Voice Response", value=True)

# --- 8. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor! You can type in the chat box, or use **Voice Mode** in the sidebar to talk to me natively! 🗣️\n\nWhat are we learning today?",
            "is_greeting": True
        }
    ]

# Keep track of the last voice note so it doesn't process the same one twice
if "last_voice_bytes" not in st.session_state:
    st.session_state.last_voice_bytes = None

if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

# --- 9. DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])
            if message.get("user_image"):
                st.image(message["user_image"], width=300)
            if message.get("user_audio"):
                st.audio(message["user_audio"])

# --- 10. MAIN LOGIC (AUTO-SEND) ---
process_query = False
user_msg_dict = {}
prompt = ""
img_bytes = user_image.getvalue() if user_image else None
audio_to_send = None

# Scenario A: User typed a message
if text_prompt := st.chat_input("Ask Helix..."):
    prompt = text_prompt
    user_msg_dict = {"role": "user", "content": prompt}
    if img_bytes: user_msg_dict["user_image"] = img_bytes
    process_query = True

# Scenario B: User used Voice Mode (Auto-triggers when recording stops)
elif voice_bytes and voice_bytes != st.session_state.last_voice_bytes:
    st.session_state.last_voice_bytes = voice_bytes  # Update tracker
    prompt = "Listen to my voice message and answer my question."
    user_msg_dict = {"role": "user", "content": "🎙️ *(Voice Message Sent)*"}
    user_msg_dict["user_audio"] = voice_bytes
    audio_to_send = voice_bytes
    if img_bytes: user_msg_dict["user_image"] = img_bytes
    process_query = True

# Process the request if either A or B happened
if process_query:
    st.session_state.messages.append(user_msg_dict)
    
    with st.chat_message("user"):
        st.markdown(user_msg_dict["content"])
        if img_bytes: st.image(img_bytes, width=300)
        if audio_to_send: st.audio(audio_to_send)

    with st.chat_message("assistant"):
        try:
            # We assume science as a default subject for voice if text parsing fails
            relevant_books = select_relevant_books(prompt + " science", st.session_state.textbook_handles)
            
            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning Curriculum: {', '.join(book_names)}*")
            else:
                st.caption("🔍 *Scanning generalized database.*")

            thinking_placeholder = st.empty()
            thinking_placeholder.markdown(f"""
                <div class="thinking-container">
                    <span class="thinking-text">🧠 Reading, Looking, & Listening...</span>
                    <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                </div>
            """, unsafe_allow_html=True)
            
            current_prompt_parts = []
            
            if img_bytes:
                current_prompt_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=user_image.type))
            if audio_to_send:
                current_prompt_parts.append(types.Part.from_bytes(data=audio_to_send, mime_type="audio/wav"))
            
            for book in relevant_books:
                friendly_name = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly_name}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))
            
            enhanced_prompt = f"Please read the user query, look at the images (if provided), and listen to the audio (if provided). Check the attached Cambridge textbooks for syllabus accuracy.\n\nQuery: {prompt}"
            current_prompt_parts.append(types.Part.from_text(text=enhanced_prompt))
            
            current_content = types.Content(role="user", parts=current_prompt_parts)
            
            history_contents = []
            text_msgs = [m for m in st.session_state.messages[:-1] if not m.get("is_image") and not m.get("is_greeting")]
            for msg in text_msgs[-4:]:
                history_contents.append(types.Content(role="user" if msg["role"] == "user" else "model", parts=[types.Part.from_text(text=msg["content"])]))
            
            full_contents = history_contents + [current_content]

            text_response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=full_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3, 
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # Play AI Voice automatically if toggle is enabled
            if use_tts:
                autoplay_audio(bot_text)

            # Image Gen
            if "IMAGE_GEN:" in bot_text:
                try:
                    img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    img_thinking = st.empty()
                    img_thinking.markdown("*🖌️ Painting diagram...*")
                    
                    img_resp = client.models.generate_content(
                        model="gemini-3-pro-image-preview",
                        contents=[img_desc],
                        config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])
                    )
                    
                    for part in img_resp.parts:
                        if part.inline_data:
                            st.image(part.inline_data.data, caption="Generated by Helix")
                            st.session_state.messages.append({"role": "assistant", "content": part.inline_data.data, "is_image": True})
                            img_thinking.empty()
                except Exception:
                    st.error("Image generation failed.")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")
