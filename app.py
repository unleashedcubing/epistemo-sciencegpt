import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

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

# --- 3. HELPER: FORMAT FILE NAMES ---
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

# --- 4. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE MULTIMODAL & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, analyze it carefully (e.g., solve the math problem, identify the biology diagram).
- If the user provides AUDIO, listen to their question and answer it directly.
- You MUST search the attached PDF textbooks using OCR to verify your answers and align with the Cambridge syllabus. Cite the book (Source: Cambridge Science Textbook 7).
- If the answer is not in the books, explicitly state: "I couldn't find this in your textbook, but here is what I know:" and use your general knowledge.

### RULE 2: ASSESSMENTS
- If making a question paper/quiz, list the source(s) ONLY ONCE at the very bottom.

### RULE 3: IMAGE GENERATION
- IF THE USER ASKS FOR A DIAGRAM, output ONLY this exact command:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]
"""

# --- 5. GOOGLE FILE API (OCR-CAPABLE RAG) ---
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

# --- 7. MULTIMODAL SIDEBAR (NEW) ---
with st.sidebar:
    st.title("📎 Multimodal Inputs")
    st.caption("Helix can see your homework and hear your questions!")
    
    # Vision: Upload Photo
    user_image = st.file_uploader("📸 Upload a Photo", type=["jpg", "jpeg", "png"])
    
    # Voice: Record Audio natively in Streamlit
    user_audio = st.audio_input("🎤 Record Voice Question")

# --- 8. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor! You can now **upload photos** of your homework or **ask me questions using your voice** using the sidebar on the left! 📸🎤\n\nWhat are we learning today?",
            "is_greeting": True
        }
    ]

if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

# --- 9. DISPLAY CHAT (UPDATED FOR MEDIA) ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        # Show AI generated images
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])
            # Display user uploaded media back to them in the chat log
            if message.get("user_image"):
                st.image(message["user_image"], width=300)
            if message.get("user_audio"):
                st.audio(message["user_audio"])

# --- 10. MAIN LOOP ---
# Tip: Tell users they can just type "Audio" if they only want to send a voice note
if prompt := st.chat_input("Ask Helix... (Tip: Add a photo in the sidebar!)"):
    
    # Save the user's message, plus any attached media
    user_msg_dict = {"role": "user", "content": prompt}
    
    img_bytes = user_image.getvalue() if user_image else None
    audio_bytes = user_audio.getvalue() if user_audio else None
    
    if img_bytes: user_msg_dict["user_image"] = img_bytes
    if audio_bytes: user_msg_dict["user_audio"] = audio_bytes
        
    st.session_state.messages.append(user_msg_dict)
    
    with st.chat_message("user"):
        st.markdown(prompt)
        if img_bytes: st.image(img_bytes, width=300)
        if audio_bytes: st.audio(audio_bytes)

    with st.chat_message("assistant"):
        try:
            relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)
            
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
            
            # --- ATTACH MULTIMODAL INPUTS ---
            if img_bytes:
                current_prompt_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=user_image.type))
            if audio_bytes:
                # Gemini can natively listen to wav files!
                current_prompt_parts.append(types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"))
            
            # Attach PDFs
            for book in relevant_books:
                friendly_name = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly_name}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))
            
            # Attach Text
            enhanced_prompt = f"Please read the user query, look at the images (if provided), and listen to the audio (if provided). Check the attached Cambridge textbooks for syllabus accuracy.\n\nQuery: {prompt}"
            current_prompt_parts.append(types.Part.from_text(text=enhanced_prompt))
            
            current_content = types.Content(role="user", parts=current_prompt_parts)
            
            # Formatting history (text only to save bandwidth, omitting giant files)
            history_contents = []
            text_msgs = [m for m in st.session_state.messages[:-1] if not m.get("is_image") and not m.get("is_greeting")]
            for msg in text_msgs[-4:]:
                history_contents.append(types.Content(role="user" if msg["role"] == "user" else "model", parts=[types.Part.from_text(text=msg["content"])]))
            
            full_contents = history_contents + [current_content]

            # Generate response
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
            st.error(f"Helix Error: {e}")
