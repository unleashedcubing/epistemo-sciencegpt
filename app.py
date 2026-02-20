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

# --- 3. THEME CSS & STATUS INDICATOR ---
st.markdown("""
<style>
.stApp {
  background:
    radial-gradient(800px circle at 50% 0%,
      rgba(0, 212, 255, 0.08),
      rgba(0, 212, 255, 0.00) 60%),
    var(--background-color);
  color: var(--text-color);
}
.status-indicator {
  position: fixed;
  top: 60px;
  left: 15px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background-color: rgba(30, 30, 30, 0.8);
  border-radius: 20px;
  backdrop-filter: blur(8px);
  z-index: 100000;
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.1);
  transition: all 0.3s ease;
}
.book-icon { font-size: 24px; }
.spinner {
  width: 18px; height: 18px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  border-top-color: #00d4ff;
  animation: spin 1s ease-in-out infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status-loading { border-color: #ff4b4b; }
.status-loading .book-icon { animation: pulse-red 1.5s infinite; }
.status-ready { border-color: #00c04b; background-color: rgba(0, 192, 75, 0.15); }
.status-error { border-color: #ffa500; }
@keyframes pulse-red {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.7; }
  100% { transform: scale(1); opacity: 1; }
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
  animation: helix-glow 2.2s ease-in-out infinite;
}
@keyframes helix-glow {
  0%, 100% { text-shadow: 0 0 6px rgba(0, 212, 255, 0.45); }
  50% { text-shadow: 0 0 8px rgba(0, 212, 255, 0.75); }
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
}
.thinking-container {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background-color: var(--secondary-background-color);
  border-radius: 8px;
  margin: 10px 0;
  border-left: 3px solid #fc8404;
}
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background-color: #fc8404;
  animation: thinking-pulse 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(1){ animation-delay: 0s; }
.thinking-dot:nth-child(2){ animation-delay: 0.2s; }
.thinking-dot:nth-child(3){ animation-delay: 0.4s; }
@keyframes thinking-pulse {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1.2); }
}
</style>

<div class="big-title">📚 helix.ai</div>
<div class="subtitle">Your CIE Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)

# --- 4. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

***REMEMBER VERY IMPORTANT!!!!!: The moment you recieve the user prompt, wait 4 seconds and read the prompt fully. If you are 90% sure that the user's query is not related to the book sources, don't bother checking the books, answer based on internet/your own way. If you aren't sure, check the books.***

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: The textbooks were too big, so I split each into 2. The names would have ..._1.pdf or ..._2.pdf. The ... area would have the year. Check both when queries come up.
ALSO: In MCQs, randomize the answers, because in a previous test I did using you, the answers were 1)C, 2)C, 3)C, 4)C. REMEMBER, RANDOMIZE MCQ ANSWERS
ALSO: Use BOTH WB (Workbook) AND TB (Textbook) because the WB has questions mainly, but SB has theory. Using BOTH WILL GIVE YOU A WIDE RANGE OF QUESTIONS.
ALSO: DO NOT INTRODUCE YOURSELF LIKE "I am Helix!" as I have already created and introduction message. Just get to the user's query immediately.

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
- The subject is seen in the last part, like this: _Eng.pdf, _Math.pdf, _Sci.pdf

### RULE 2: STAGE 9 ENGLISH TB/WB
- I couldn't find the TB/WB source for Stage 9 English, so you will go off of this table of contents:
Chapter 1: Writing to explore and reflect
Chapter 2: Writing to inform and explain
Chapter 3: Writing to argue and persuade
Chapter 4: Descriptive writing
Chapter 5: Narrative writing
Chapter 6: Writing to analyse and compare
Chapter 7: Testing your skills

### RULE 3: IMAGE GENERATION (STRICT)
- If the user asks for a diagram, infographic, mindmap or illustration, output ONLY this command:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]

### RULE 4: QUESTION PAPERS
- Science (Checkpoint style): 50-mark, ~45-minute paper with structured questions, data handling, practical skills, and a mark scheme.
- Mathematics (Checkpoint style): Paper 1 non-calculator and Paper 2 calculator, each 50 marks ~45 mins, with an answer key.
- English (Checkpoint style): Paper 1 Non-fiction and Paper 2 Fiction, each 50 marks ~45 mins, using original passages, with a mark scheme.

### RULE 5: ARMAAN STYLE
If a user asks you to reply in Armaan Style, explain in expert physicist/chemist/biologist/mathematician/writer terms with difficult out-of-textbook sources. Simplify if the user wishes.
"""

# --- 5. ROBUST FILE UPLOADER & SMART SELECTOR ---
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf",
        "CIE_CBSE_8_SB_Hindi.pdf", "CIE_CBSE_7_SB_Hindi.pdf", "CIE:CBSE_6,7,8_SYLLABUS_CompSci.pdf",
        "CIE:CBSE_6,7,8_SB_French_2.pdf", "CIE:CBSE_6,7,8_SB_French_1.pdf", "CIE:CBSE_6_SB_Hindi_5.pdf",
        "CIE:CBSE_6_SB_Hindi_4.pdf", "CIE:CBSE_6_SB_Hindi_3.pdf", "CIE:CBSE_6_SB_Hindi_2.pdf", "CIE:CBSE_6_SB_Hindi_1.pdf"
    ]

    active_files = {"sci": [], "math": [], "eng": [], "hindi": [], "french": [], "cs": []}

    # --- Loading status indicator ---
    status_placeholder = st.empty()
    status_placeholder.markdown(
        '<div class="status-indicator status-loading">'
        '<span class="book-icon">📕</span>'
        '<div class="spinner"></div>'
        '</div>',
        unsafe_allow_html=True
    )

    # --- Loading message ---
    msg_placeholder = st.empty()
    with msg_placeholder.chat_message("assistant"):
        st.markdown(
            '<div class="thinking-container">'
            '<span class="thinking-text">🔄 Helix is loading your textbooks...</span>'
            '<div class="thinking-dots">'
            '<div class="thinking-dot"></div>'
            '<div class="thinking-dot"></div>'
            '<div class="thinking-dot"></div>'
            '</div></div>',
            unsafe_allow_html=True
        )

    try:
        cwd = Path.cwd()
        all_pdfs = list(cwd.rglob("*.pdf"))
        if len(all_pdfs) == 0:
            status_placeholder.markdown(
                '<div class="status-indicator status-error">'
                '<span class="book-icon">⚠️</span>'
                '</div>',
                unsafe_allow_html=True
            )
            msg_placeholder.empty()
            return {}
        pdf_map = {p.name.lower(): p for p in all_pdfs}

    except Exception:
        status_placeholder.markdown(
            '<div class="status-indicator status-error">'
            '<span class="book-icon">⚠️</span>'
            '</div>',
            unsafe_allow_html=True
        )
        msg_placeholder.empty()
        return {}

    for target_name in target_filenames:
        simple_name = target_name.split("/")[-1]
        found_path = pdf_map.get(simple_name.lower())

        if found_path:
            try:
                if found_path.stat().st_size == 0:
                    continue

                upload_success = False
                uploaded_file = None

                for attempt in range(2):
                    try:
                        uploaded_file = client.files.upload(
                            file=found_path,
                            config={"mime_type": "application/pdf"}
                        )
                        upload_success = True
                        break
                    except Exception:
                        if attempt == 0:
                            time.sleep(1)

                if not upload_success:
                    continue

                start_time = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - start_time > 45:
                        break
                    time.sleep(1)
                    uploaded_file = client.files.get(name=uploaded_file.name)

                if uploaded_file.state.name == "ACTIVE":
                    lname = simple_name.lower()
                    if "sci" in lname and "compsci" not in lname:
                        active_files["sci"].append(uploaded_file)
                    elif "math" in lname:
                        active_files["math"].append(uploaded_file)
                    elif "eng" in lname:
                        active_files["eng"].append(uploaded_file)
                    elif "hindi" in lname:
                        active_files["hindi"].append(uploaded_file)
                    elif "french" in lname:
                        active_files["french"].append(uploaded_file)
                    elif "compsci" in lname:
                        active_files["cs"].append(uploaded_file)

            except Exception:
                continue

    status_placeholder.markdown(
        '<div class="status-indicator status-ready">'
        '<span class="book-icon">📗</span>'
        '</div>',
        unsafe_allow_html=True
    )
    msg_placeholder.empty()
    return active_files


def select_relevant_books(query, file_dict):
    query = query.lower()
    selected = []

    math_keywords = ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"]
    sci_keywords = ["science", "cell", "biology", "physics", "chemistry", "atom", "energy", "force", "organism"]
    eng_keywords = ["english", "poem", "story", "essay", "writing", "grammar", "text", "author"]
    hindi_keywords = ["hindi", "kavita", "kahani"]
    french_keywords = ["french", "francais", "verb", "conjugate"]
    cs_keywords = ["computer", "python", "coding", "algorithm", "html", "css", "compsci"]

    if any(k in query for k in math_keywords):
        selected.extend(file_dict.get("math", []))
    if any(k in query for k in sci_keywords):
        selected.extend(file_dict.get("sci", []))
    if any(k in query for k in eng_keywords):
        selected.extend(file_dict.get("eng", []))
    if any(k in query for k in hindi_keywords):
        selected.extend(file_dict.get("hindi", []))
    if any(k in query for k in french_keywords):
        selected.extend(file_dict.get("french", []))
    if any(k in query for k in cs_keywords):
        selected.extend(file_dict.get("cs", []))

    if not selected:
        selected.extend(file_dict.get("math", []))
        selected.extend(file_dict.get("sci", []))

    return selected


# --- 6. ANIMATION FUNCTIONS ---
def show_thinking_animation_rotating(placeholder):
    thinking_messages = [
        "🔍 Helix is searching the textbooks 📚",
        "🧠 Helix is analyzing your question 💭",
        "✨ Helix is forming your answer 📝",
        "🔬 Helix is processing information 🧪",
        "📖 Helix is consulting the resources 📊"
    ]
    for message in thinking_messages:
        placeholder.markdown(
            '<div class="thinking-container">'
            '<span class="thinking-text">' + message + '</span>'
            '<div class="thinking-dots">'
            '<div class="thinking-dot"></div>'
            '<div class="thinking-dot"></div>'
            '<div class="thinking-dot"></div>'
            '</div></div>',
            unsafe_allow_html=True
        )
        time.sleep(3)


def show_thinking_animation(message="Helix is thinking"):
    st.markdown(
        '<div class="thinking-container">'
        '<span class="thinking-text">' + message + '</span>'
        '<div class="thinking-dots">'
        '<div class="thinking-dot"></div>'
        '<div class="thinking-dot"></div>'
        '<div class="thinking-dot"></div>'
        '</div></div>',
        unsafe_allow_html=True
    )


# --- 7. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Hey there! I'm Helix!**\n\n"
                "I'm your friendly CIE tutor here to help you ace your exams! 📖\n\n"
                "I can answer your doubts, draw diagrams, and create quizzes! 📚\n\n"
                "**Quick Reminder:** Always mention your grade in a query!\n\n"
                "What are we learning today?"
            )
        }
    ]

# --- Start upload if needed ---
if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()
else:
    st.markdown(
        '<div class="status-indicator status-ready">'
        '<span class="book-icon">📗</span>'
        '</div>',
        unsafe_allow_html=True
    )

# --- 8. DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- 9. MAIN LOOP ---
if prompt := st.chat_input("Ask Helix a question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        show_thinking_animation_rotating(thinking_placeholder)

        try:
            # 1. Select relevant books
            relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)

            # 2. Build contents correctly to avoid Part.from_text() error
            parts = []
            for f in relevant_books:
                parts.append(types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf"))
            parts.append(types.Part.from_text(text=prompt))

            user_content = types.Content(role="user", parts=parts)

            # 3. Generate response
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[user_content],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[{"google_search": {}}]
                )
            )

            bot_text = text_response.text
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # 4. Image Gen (Pollinations.ai - Free & Reliable)
            if "IMAGE_GEN:" in bot_text:
                import requests
                from io import BytesIO

                img_thinking = st.empty()
                try:
                    img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    img_desc = img_desc.replace("[", "").replace("]", "")

                    with img_thinking:
                        show_thinking_animation("🖌️ Painting diagram...")

                    encoded_desc = requests.utils.quote(img_desc)
                    image_url = f"https://image.pollinations.ai/prompt/{encoded_desc}?nologo=true"

                    response = requests.get(image_url, timeout=30)
                    if response.status_code == 200:
                        image_bytes = BytesIO(response.content)
                        img_thinking.empty()
                        st.image(image_bytes, caption=f"Generated: {img_desc}")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": image_bytes,
                            "is_image": True
                        })
                    else:
                        img_thinking.empty()
                        st.error("Image generation service busy. Try again.")

                except Exception as e:
                    img_thinking.empty()
                    st.error(f"Image generation failed: {e}")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")
            if "403" in str(e):
                st.warning("⚠️ Session expired. Refresh the page.")
            elif "429" in str(e):
                st.warning("⚠️ Too many requests. Please wait a moment.")
            elif "400" in str(e):
                st.warning("⚠️ Query too complex. Try asking about a specific subject.")
