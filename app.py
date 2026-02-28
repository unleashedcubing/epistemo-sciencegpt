import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- 2. API CLIENT SETUP ---
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

# --- 3. THEME CSS & TITLE ---
st.markdown("""
<style>
.stApp {
  background: radial-gradient(800px circle at 50% 0%, rgba(0, 212, 255, 0.08), rgba(0, 212, 255, 0.00) 60%), var(--background-color);
  color: var(--text-color);
}
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.55);
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
}
.thinking-container {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  background-color: var(--secondary-background-color);
  border-radius: 8px; margin: 10px 0; border-left: 3px solid #fc8404;
}
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

# --- 4. HELPER: FORMAT FILE NAMES ---
def get_friendly_name(filename):
    """Translates 'CIE_7_WB_Sci.pdf' into 'Cambridge Science Workbook 7'"""
    if not filename: return "Cambridge Textbook"
    name = filename.replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    
    if len(parts) < 3 or parts[0] != "CIE": return filename
        
    grade = parts[1]
    book_type = "Workbook" if "WB" in parts else "Textbook"
    if "ANSWERS" in parts: book_type += " Answers"
    
    subject = "Science" if "Sci" in parts else "Math" if "Math" in parts else "English" if "Eng" in parts else "Subject"
    
    part_str = ""
    if "1" in parts[2:]: part_str = " (Part 1)"
    if "2" in parts[2:]: part_str = " (Part 2)"
    
    return f"Cambridge {subject} {book_type} {grade}{part_str}"

# --- 5. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE TWO-STEP SEARCH (CRITICAL)
- STEP 1: You MUST search the attached PDF textbooks FIRST. If you find the answer, base your response on the book and cite it at the end like this: (Source: Cambridge Science Textbook 7). Do NOT include page numbers.
- STEP 2: If (and ONLY if) the textbooks do not contain the answer, you must explicitly state: "I couldn't find this in your textbook, but here is what I found:" and then provide the best possible answer using your general knowledge or web search.

### RULE 2: SOURCE PRIORITY & MCQ FORMAT
- Use BOTH WB (Workbook) AND TB (Textbook) to provide a wide range of questions/answers.
- In MCQs, ALWAYS randomize the options. Do not make all correct answers the same letter.

### RULE 3: STAGE 9 ENGLISH TB/WB (CRITICAL)
- I couldn't find the TB/WB source for Stage 9 English, so you will go off of this table of contents:
Chapter 1 • Writing to explore and reflect (1.1 What is travel writing?, 1.2 Selecting info, 1.3 Tone/register, 1.8 Creating account)
Chapter 2 • Writing to inform and explain (2.1 Matching texts, 2.2 Formal/informal, 2.9 Encyclopedia entries)
Chapter 3 • Writing to argue and persuade (3.1 Persuasive techniques, 3.6 Organising whole argument, 3.9 Argumentative essay)
Chapter 4 • Descriptive writing (4.1 Atmospheres, 4.4 Images to inspire, 4.9 Powerful description)
Chapter 5 • Narrative writing (5.1 Story openings, 5.2 Setting/atmosphere, 5.6 Suspense/climax, 5.10 Thriller)
Chapter 6 • Writing to analyse and compare (6.1 Implicit meaning, 6.2 Plays, 6.5 Analysing two texts)
Chapter 7 • Testing your skills (7.1-7.4 Reading and writing questions)

### RULE 4: IMAGE GENERATION (STRICT)
- IF THE USER ASKS FOR A NORMAL DIAGRAM (e.g., "diagram of a cell", infographic, mindmap), output ONLY this exact command:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]

### RULE 5: QUESTION PAPERS (CRITICAL FORMATTING)
- CITATION RULE: When making a question paper/quiz, list the source(s) ONLY ONCE at the very bottom of the entire paper/test. Do NOT add citations after individual questions, and do NOT use page numbers.
- Science: Paper 1 & 2 (50‑mark, ~45‑min). Structured questions "(3)", mixing knowledge/data handling. Includes investigation/practical skills & diagram tasks. Provide point-based mark scheme.
- Mathematics: Paper 1 (non-calc) & Paper 2 (calc). 50 marks each. Cover arithmetic, algebra, geometry, data. Include multi-step word problems requiring "show working". Give answer key with method marks.
- English: Paper 1 (Non‑fiction) & Paper 2 (Fiction). Original passages. Structured comprehension + one longer directed/creative writing task. Provide rubric (content/organisation/style).

### RULE 6: ARMAAN STYLE
- If a user asks to reply in "Armaan Style", explain in expert physicist/chemist/biologist/mathematician/writer terms, using complex, out-of-textbook vocabulary. You can simplify it if the user asks later.
"""

# --- 6. ROBUST FILE UPLOADER & CACHING ---
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
            <span class="thinking-text">🔄 Connecting to Library & Checking Google Servers...</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    # 1. Check existing files on Google's Server to prevent re-uploading
    existing_server_files = {}
    try:
        for f in client.files.list():
            if f.display_name:
                existing_server_files[f.display_name.lower()] = f
    except Exception as e:
        print("Could not list server files:", e)

    # 2. Get Local Files
    try:
        cwd = Path.cwd()
        all_pdfs = list(cwd.rglob("*.pdf"))
        pdf_map = {p.name.lower(): p for p in all_pdfs}
    except Exception:
        pdf_map = {}

    # 3. Process
    for target_name in target_filenames:
        t_lower = target_name.lower()
        
        # Scenario A: Already uploaded to Gemini Server!
        if t_lower in existing_server_files:
            server_file = existing_server_files[t_lower]
            if server_file.state.name == "ACTIVE":
                if "sci" in t_lower: active_files["sci"].append(server_file)
                elif "math" in t_lower: active_files["math"].append(server_file)
                elif "eng" in t_lower: active_files["eng"].append(server_file)
                continue

        # Scenario B: Need to upload
        found_path = pdf_map.get(t_lower)
        if found_path:
            try:
                if found_path.stat().st_size == 0: continue
                uploaded_file = client.files.upload(
                    file=str(found_path),
                    config={'mime_type': 'application/pdf', 'display_name': found_path.name}
                )
                
                # Wait for API to process PDF (Max 180s)
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

def select_relevant_books(query, file_dict):
    """Smartly filters books so we don't overwhelm the AI with 20 textbooks at once."""
    query = query.lower()
    selected = []
    
    is_math = any(k in query for k in ["math", "algebra", "geometry", "calculate", "equation", "number"])
    is_sci = any(k in query for k in ["science", "cell", "biology", "physics", "chemistry", "atom", "force"])
    is_eng = any(k in query for k in ["english", "poem", "story", "essay", "writing", "grammar"])
    
    # Default to Math/Sci if unclear
    if not is_math and not is_sci and not is_eng:
        is_math, is_sci = True, True

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
                selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)
    
    # Cap at 4 books to prevent AI token overload ignoring the books
    return selected[:4] 

# --- 7. HISTORY FORMATTING ---
def get_recent_history_contents(messages, max_messages=6):
    history_contents = []
    text_msgs = [m for m in messages if not m.get("is_image") and not m.get("is_greeting")]
    for msg in text_msgs[-max_messages:]:
        role = "user" if msg["role"] == "user" else "model"
        history_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
    return history_contents

# --- 8. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizes! 📚\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?",
            "is_greeting": True
        }
    ]

if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

# --- 9. DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- 10. MAIN LOOP ---
if prompt := st.chat_input("Ask Helix a question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            # Gather relevant files
            relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)
            
            # Show the user exactly which books the AI is reading using friendly names
            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning: {', '.join(book_names)}*")
            else:
                st.caption("🔍 *No specific textbooks found for this query. Using general knowledge.*")

            thinking_placeholder = st.empty()
            thinking_placeholder.markdown(f"""
                <div class="thinking-container">
                    <span class="thinking-text">🧠 Reading & Thinking...</span>
                    <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                </div>
            """, unsafe_allow_html=True)
            
            chat_history_contents = get_recent_history_contents(st.session_state.messages[:-1], max_messages=6)
            
            # Build current prompt
            current_prompt_parts = []
            for book in relevant_books:
                # Give the AI the Friendly Name so it cites it beautifully
                friendly_name = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly_name}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))
            
            # TWO-STEP PROMPT INJECTION
            enhanced_prompt = f"Please check the attached Cambridge textbooks for the answer to this query FIRST. If it is NOT in the books, answer using your general knowledge/web search.\n\nQuery: {prompt}"
            current_prompt_parts.append(types.Part.from_text(text=enhanced_prompt))
            
            current_content = types.Content(role="user", parts=current_prompt_parts)
            full_contents = chat_history_contents + [current_content]

            # Generate (Temperature 0.4 and google_search active for out-of-book questions)
            text_response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=full_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.4, 
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
            if "403" in str(e): st.warning("⚠️ Session expired. Refresh page.")
            elif "429" in str(e): st.warning("⚠️ Too many requests. Please wait a moment.")
            elif "400" in str(e): st.warning("⚠️ Request Error. Ensure the Google API key has File permissions enabled.")
