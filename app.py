import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

# --- PAGE CONFIG ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- THEME CSS ---
st.markdown("""
<style>
/* Theme-aware app background */
.stApp {
  background:
    radial-gradient(800px circle at 50% 0%,
      rgba(0, 212, 255, 0.08),
      rgba(0, 212, 255, 0.00) 60%),
    var(--background-color);
  color: var(--text-color);
}

/* Glowing title */
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
  text-shadow:
    0 0 6px rgba(0, 212, 255, 0.55),
    0 0 18px rgba(0, 212, 255, 0.35),
    0 0 42px rgba(0, 212, 255, 0.20);
  animation: helix-glow 2.2s ease-in-out infinite;
}

@keyframes helix-glow {
  0%, 100% {
    text-shadow:
      0 0 6px rgba(0, 212, 255, 0.45),
      0 0 18px rgba(0, 212, 255, 0.28),
      0 0 42px rgba(0, 212, 255, 0.16);
  }
  50% {
    text-shadow:
      0 0 8px rgba(0, 212, 255, 0.75),
      0 0 24px rgba(0, 212, 255, 0.45),
      0 0 54px rgba(0, 212, 255, 0.24);
  }
}

.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
}

/* Thinking Animation */
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

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

MODEL_TEXT = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-3-pro-image-preview"

# --- SETTINGS YOU ASKED FOR ---
MAX_TURNS = 7
THINK_STEP_SECONDS = 3
CACHE_TTL = "3600s"  # 60 minutes

# --- SYSTEM INSTRUCTIONS (your full block) ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

***REMEMBER VERY IMPORTANT!!!!!: The moment you recieve the user prompt, wait 4 seconds and read the prompt fully. If you are 90% sure that the user's query is not related to the book sources, don't bother checking the books, answer based on internet/your own way. If you aren't sure, check the books.***

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: The textbooks were too big, so I split each into 2. The names would have ..._1.pdf or ..._2.pdf. The ... area would have the year. Check both when queries come up.
ALSO: In MCQs, randomize the answers, because in a previous test I did using you, the answers were 1)C, 2)C, 3)C, 4)C. REMEMBER, RANDOMIZE MCQ ANSWERS
ALSO: Use BOTH WB (Workbook) AND TB (Textbook) because the WB has questions mainly, but SB has theory. Using BOTH WILL GIVE YOU A WIDE RANGE OF QUESTIONS.
ALSO: DO NOT INTRODUCE YOURSELF LIKE "I am Helix!" as I have already created and introduction message. Just get to the user's query immediately.
ALSO:

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
- The subject is seen in the last part, like this: _Eng.pdf, _Math.pdf, _Sci.pdf

### RULE 2: STAGE 9 ENGLISH TB/WB: ***IMPORTANT, VERY***
- I couldn't find the TB/WB source for Stage 9 English, so you will go off of this table of contents:
Chapter 1 • Writing to explore and reflect
1.1 What is travel writing?

1.2 Selecting and noting key information in travel texts

1.3 Comparing tone and register in travel texts

1.4 Responding to travel writing

1.5 Understanding grammatical choices in travel writing

1.6 Varying sentences for effect

1.7 Boost your vocabulary

1.8 Creating a travel account

Chapter 2 • Writing to inform and explain
2.1 Matching informative texts to audience and purpose

2.2 Using formal and informal language in information texts

2.3 Comparing information texts

2.4 Using discussion to prepare for a written assignment

2.5 Planning information texts to suit different audiences

2.6 Shaping paragraphs to suit audience and purpose

2.7 Crafting sentences for a range of effects

2.8 Making explanations precise and concise

2.9 Writing encyclopedia entries

Chapter 3 • Writing to argue and persuade
3.1 Reviewing persuasive techniques

3.2 Commenting on use of language to persuade

3.3 Exploring layers of persuasive language

3.4 Responding to the use of persuasive language

3.5 Adapting grammar choices to create effects in argument writing

3.6 Organising a whole argument effectively

3.7 Organising an argument within each paragraph

3.8 Presenting and responding to a question

3.9 Producing an argumentative essay

Chapter 4 • Descriptive writing
4.1 Analysing how atmospheres are created

4.2 Developing analysis of a description

4.3 Analysing atmospheric descriptions

4.4 Using images to inspire description

4.5 Using language to develop an atmosphere

4.6 Sustaining a cohesive atmosphere

4.7 Creating atmosphere through punctuation

4.8 Using structural devices to build up atmosphere

4.9 Producing a powerful description

Chapter 5 • Narrative writing
5.1 Understanding story openings

5.2 Exploring setting and atmosphere

5.3 Introducing characters in stories

5.4 Responding to powerful narrative

5.5 Pitching a story

5.6 Creating narrative suspense and climax

5.7 Creating character

5.8 Using tenses in narrative

5.9 Using pronouns and sentence order for effect

5.10 Creating a thriller

Chapter 6 • Writing to analyse and compare
6.1 Analysing implicit meaning in non-fiction texts

6.2 Analysing how a play's key elements create different effects

6.3 Using discussion skills to analyse carefully

6.4 Comparing effectively through punctuation and grammar

6.5 Analysing two texts

Chapter 7 • Testing your skills
7.1 Reading and writing questions on non-fiction texts

7.2 Reading and writing questions on fiction texts

7.3 Assessing your progress: non-fiction reading and writing

7.4 Assessing your progress: fiction reading and writing

### RULE 3: IMAGE GENERATION (STRICT)
- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart", or a infographic or mindmap, or a mind map for math, you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]

### RULE 4: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Science (Checkpoint style): produce Paper 1 and/or Paper 2 (default both) as a 50‑mark, ~45‑minute structured written paper with numbered questions showing marks like “(3)”, mixing knowledge/application plus data handling (tables/graphs) and at least one investigation/practical-skills question (variables, fair test, reliability, improvements) and at least one diagram task; then include a point-based mark scheme with working/units for calculations.
  - Mathematics (Checkpoint style): produce Paper 1 non‑calculator and Paper 2 calculator (default both), each ~45 minutes and 50 marks, mostly structured questions with marks shown, covering arithmetic/fractions/percent, algebra, geometry, and data/statistics, including at least one multi-step word problem and requiring “show working”; then give an answer key with method marks for 2+ mark items.
  - English (Checkpoint style): produce Paper 1 Non‑fiction and Paper 2 Fiction (default both), each ~45 minutes and 50 marks, using original passages you write (no copyrighted extracts), with structured comprehension (literal + inference + writer’s effect) and one longer directed/creative writing task per paper; then include a mark scheme (acceptable reading points per mark) plus a simple writing rubric (content/organisation/style & accuracy) and a brief high-scoring outline.

### RULE 5: ARMAAN STYLE
If a user asks you to reply in Armaan Style, you have to explain in expert physicist/chemist/biologist/mathematician/writer terms, with difficult out of textbook sources. You can then simple it down if the user wishes.
"""

# --- Thinking Animation ---
def show_thinking_animation(message="Helix is thinking"):
    thinking_html = f"""
    <div class="thinking-container">
        <span class="thinking-text">{message}</span>
        <div class="thinking-dots">
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
        </div>
    </div>
    """
    return st.markdown(thinking_html, unsafe_allow_html=True)

# --- Chat memory (rolling window + optional summary) ---
def build_history_contents(messages, max_turns=MAX_TURNS):
    text_msgs = [m for m in messages if (not m.get("is_image")) and m.get("role") in ("user", "assistant")]
    window = text_msgs[-(2 * max_turns):]
    contents = []
    for m in window:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return contents

def maybe_summarize_old_chat(messages, keep_last_msgs=22):
    if len(messages) <= keep_last_msgs:
        return
    old = [m for m in messages[:-keep_last_msgs] if (not m.get("is_image")) and m.get("role") in ("user", "assistant")]
    if not old:
        return
    old_text = "\n".join([f'{m["role"].upper()}: {m["content"]}' for m in old])[-12000:]
    prompt = (
        "Summarize the conversation so far in <= 10 bullet points.\n"
        "Keep: grade/stage, subjects, chapters, constraints, decisions.\n"
        "Do NOT add new facts.\n\n"
        f"{old_text}"
    )
    resp = client.models.generate_content(
        model=MODEL_TEXT,
        contents=[prompt],
        config=types.GenerateContentConfig(system_instruction="You are a precise summarizer.")
    )
    st.session_state.chat_summary = (resp.text or "").strip()

# --- PDF discovery (ALL PDFs committed in repo) ---
BASE_DIR = Path(__file__).resolve().parent

def find_all_pdfs():
    pdfs = sorted([p for p in BASE_DIR.rglob("*.pdf") if p.is_file()])
    return pdfs

# --- Upload PDFs to Gemini Files API (once per session) ---
def upload_pdfs_to_gemini(pdf_paths):
    uploaded_file_names = []
    for p in pdf_paths:
        try:
            f = client.files.upload(file=str(p))
            while f.state.name == "PROCESSING":
                time.sleep(1)
                f = client.files.get(name=f.name)
            uploaded_file_names.append(f.name)
        except Exception as e:
            st.sidebar.error(f"Upload failed {p.name}: {e}")
    return uploaded_file_names

def get_uploaded_files(file_names):
    files = []
    for name in file_names:
        try:
            files.append(client.files.get(name=name))
        except Exception:
            pass
    return files

# --- Explicit cache (ALL PDFs + system instruction) ---
def ensure_textbook_cache(uploaded_pdf_file_names):
    if not uploaded_pdf_file_names:
        st.error("0 PDFs uploaded to Gemini, so the cache cannot be created. Check PDF discovery / paths.")
        st.stop()

    cache_name = st.session_state.get("textbook_cache_name", "")
    if cache_name:
        try:
            _ = client.caches.get(name=cache_name)
            return cache_name
        except Exception:
            st.session_state.textbook_cache_name = ""

    uploaded_files = get_uploaded_files(uploaded_pdf_file_names)
    if not uploaded_files:
        st.error("Could not re-fetch uploaded PDF handles from Gemini. Refresh and try again.")
        st.stop()

    cache = client.caches.create(
        model=MODEL_TEXT,
        config=types.CreateCachedContentConfig(
            display_name="helix-all-pdfs",
            system_instruction=SYSTEM_INSTRUCTION,
            contents=uploaded_files,
            ttl=CACHE_TTL,
        ),
    )
    st.session_state.textbook_cache_name = cache.name
    return cache.name

# --- Sidebar tools ---
with st.sidebar:
    st.subheader("Helix Debug")
    if st.button("Rebuild cache (force)"):
        st.session_state.textbook_cache_name = ""
        st.rerun()
    if st.button("Re-upload PDFs (force)"):
        if "uploaded_pdf_file_names" in st.session_state:
            del st.session_state.uploaded_pdf_file_names
        st.session_state.textbook_cache_name = ""
        st.rerun()

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nWhat are we learning today?"}
    ]

if "chat_summary" not in st.session_state:
    st.session_state.chat_summary = ""

if "uploaded_pdf_file_names" not in st.session_state:
    pdf_paths = find_all_pdfs()
    with st.sidebar:
        st.caption(f"PDFs discovered on disk: {len(pdf_paths)}")
        if len(pdf_paths) > 0:
            st.caption("Example PDFs:")
            for p in pdf_paths[:8]:
                st.write("•", str(p.relative_to(BASE_DIR)))

    if not pdf_paths:
        st.error("No PDFs found in the deployed filesystem. Put PDFs in the repo (same branch) and redeploy.")
        st.stop()

    with st.spinner("Uploading ALL PDFs to Gemini (one-time per session)..."):
        st.session_state.uploaded_pdf_file_names = upload_pdfs_to_gemini(pdf_paths)

if "textbook_cache_name" not in st.session_state:
    st.session_state.textbook_cache_name = ""

if not st.session_state.textbook_cache_name:
    with st.spinner("Building explicit context cache (one-time per session)..."):
        ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask Helix a question from your books, create diagrams, quizzes and more..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()

        try:
            # Keep thinking bubble + change text (animation continues in browser)
            with thinking_placeholder:
                show_thinking_animation("🔍 Helix is checking ALL textbooks 📚")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("🧾 Helix is confirming sources…")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("🧠 Helix is connecting ideas…")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("✍️ Helix is forming your answer…")

            # Rolling context (like Perplexity trimming oldest)
            maybe_summarize_old_chat(st.session_state.messages, keep_last_msgs=22)
            history_contents = build_history_contents(st.session_state.messages, max_turns=MAX_TURNS)

            request_contents = []
            if st.session_state.chat_summary.strip():
                request_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Conversation summary:\n" + st.session_state.chat_summary.strip())],
                    )
                )
            request_contents.extend(history_contents)

            cache_name = ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

            text_response = client.models.generate_content(
                model=MODEL_TEXT,
                contents=request_contents,
                config=types.GenerateContentConfig(
                    cached_content=cache_name,
                    tools=[{"google_search": {}}],
                ),
            )

            bot_text = text_response.text or ""

            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # Optional: show cache hit info (if available in your SDK response)
            try:
                cc = getattr(text_response.usage_metadata, "cached_content_token_count", None)
                if cc is not None:
                    st.sidebar.caption(f"cached_content_token_count: {cc}")
            except Exception:
                pass

            # --- IMAGE GENERATION ---
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\\n")[0]

                img_status = st.empty()
                with img_status:
                    show_thinking_animation("🖌️ Helix is painting a diagram 🎨")

                for attempt in range(2):
                    try:
                        image_response = client.models.generate_content(
                            model=MODEL_IMAGE,
                            contents=[img_desc],
                            config=types.GenerateContentConfig(
                                response_modalities=["TEXT", "IMAGE"]
                            ),
                        )
                        for part in image_response.parts:
                            if part.inline_data:
                                img_bytes = part.inline_data.data
                                img_status.empty()
                                st.image(img_bytes, caption="Generated by Helix")
                                st.session_state.messages.append(
                                    {"role": "assistant", "content": img_bytes, "is_image": True}
                                )
                        break
                    except Exception as inner_e:
                        if "503" in str(inner_e) and attempt == 0:
                            time.sleep(2)
                            continue
                        img_status.empty()
                        st.error(f"Image generation failed: {inner_e}")

        except Exception as e:
            thinking_placeholder.empty()
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Helix's connection timed out. Please refresh the page!")
                st.session_state.textbook_cache_name = ""
            else:
                st.error(f"Helix encountered a technical glitch: {e}")

