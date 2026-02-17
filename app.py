import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

# ---------------------------
# PAGE CONFIG
# ---------------------------
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# ---------------------------
# THEME CSS
# ---------------------------
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

# ---------------------------
# API SETUP
# ---------------------------
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

MODEL_TEXT = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-3-pro-image-preview"

# ---------------------------
# SETTINGS
# ---------------------------
MAX_TURNS = 7
SUMMARY_TRIGGER_MSGS = 22
THINK_STEP_SECONDS = 3

ENABLE_GOOGLE_SEARCH_TOOL = True

UPLOAD_RETRIES = 4
UPLOAD_BASE_SLEEP = 1.5
UPLOAD_BETWEEN_FILES = 0.4

CACHE_TTL = "3600s"
CACHE_CHUNK_PARTS = 20  # PDFs per Content chunk in cache creation

# ---------------------------
# SYSTEM INSTRUCTION
# ---------------------------
SYSTEM_INSTRUCTION = """
PASTE YOUR FULL SYSTEM INSTRUCTION HERE (exactly as you wrote it)
"""

# ---------------------------
# UI helper
# ---------------------------
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

# ---------------------------
# Chat memory
# ---------------------------
def build_history_contents(messages, max_turns=MAX_TURNS):
    text_msgs = [m for m in messages if (not m.get("is_image")) and m.get("role") in ("user", "assistant")]
    window = text_msgs[-(2 * max_turns):]
    contents = []
    for m in window:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return contents

def maybe_summarize_old_chat(messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS):
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

# ---------------------------
# PDF discovery (AUTO)
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent

def _skip_path(p: Path) -> bool:
    s = str(p)
    bad = ("/.git/", "/__pycache__/", "/.venv/", "/venv/", "/site-packages/")
    return any(x in s for x in bad)

def find_all_pdfs():
    pdfs = []
    for p in BASE_DIR.rglob("*.pdf"):
        if p.is_file() and (not _skip_path(p)):
            pdfs.append(p)
    return sorted(pdfs)

def mb(nbytes):
    return round(nbytes / (1024 * 1024), 2)

# ---------------------------
# Upload PDFs to Gemini with retries/backoff
# ---------------------------
def upload_one_pdf(path: Path):
    last_err = None
    for attempt in range(UPLOAD_RETRIES):
        try:
            if attempt > 0:
                time.sleep(UPLOAD_BASE_SLEEP * (2 ** (attempt - 1)))

            f = client.files.upload(
                file=str(path),
                config=dict(mime_type="application/pdf"),
            )
            while f.state.name == "PROCESSING":
                time.sleep(1)
                f = client.files.get(name=f.name)

            return f.name, None
        except Exception as e:
            last_err = e
    return None, last_err

def upload_all_pdfs(pdf_paths):
    uploaded_names = []
    failures = []
    for p in pdf_paths:
        name, err = upload_one_pdf(p)
        if name:
            uploaded_names.append(name)
        else:
            failures.append((p, err))
        time.sleep(UPLOAD_BETWEEN_FILES)
    return uploaded_names, failures

def get_uploaded_files(file_names):
    out = []
    for n in file_names:
        try:
            out.append(client.files.get(name=n))
        except Exception:
            pass
    return out

def chunk_list(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

# ---------------------------
# Explicit cache (ALL PDFs)
# ---------------------------
def ensure_textbook_cache(uploaded_pdf_file_names):
    if not uploaded_pdf_file_names:
        st.error("0 PDFs uploaded to Gemini, so the cache cannot be created. See sidebar for upload failures.")
        st.stop()

    # Reuse cache if it still exists
    cache_name = st.session_state.get("textbook_cache_name", "")
    if cache_name:
        try:
            cache_obj = client.caches.get(name=cache_name)
            with st.sidebar:
                st.write("CACHE (reused):", cache_obj.name)
                st.write("CACHE usage_metadata:", getattr(cache_obj, "usage_metadata", None))
            return cache_obj.name
        except Exception:
            st.session_state.textbook_cache_name = ""

    uploaded_files = get_uploaded_files(uploaded_pdf_file_names)
    if not uploaded_files:
        st.error("Could not re-fetch uploaded file handles via client.files.get(). Force re-upload from sidebar.")
        st.stop()

    parts = [types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf") for f in uploaded_files]
    contents = [types.Content(role="user", parts=chunk) for chunk in chunk_list(parts, CACHE_CHUNK_PARTS)]

    cache = client.caches.create(
        model=MODEL_TEXT,
        config=types.CreateCachedContentConfig(
            contents=contents,
            system_instruction=SYSTEM_INSTRUCTION,
            display_name="helix-all-pdfs",
            ttl=CACHE_TTL,
        ),
    )
    st.session_state.textbook_cache_name = cache.name

    with st.sidebar:
        st.write("CACHE (created):", cache.name)
        st.write("CACHE usage_metadata:", getattr(cache, "usage_metadata", None))

    return cache.name

# ---------------------------
# Sidebar controls + debug
# ---------------------------
with st.sidebar:
    st.subheader("Helix Debug")

    if st.button("Force re-upload PDFs"):
        for k in ("uploaded_pdf_file_names", "upload_failures", "textbook_cache_name"):
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    if st.button("Force rebuild cache"):
        st.session_state.textbook_cache_name = ""
        st.rerun()

# ---------------------------
# INITIALIZE SESSION
# ---------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nWhat are we learning today?"}
    ]

if "chat_summary" not in st.session_state:
    st.session_state.chat_summary = ""

if "textbook_cache_name" not in st.session_state:
    st.session_state.textbook_cache_name = ""

# ---------------------------
# Discover PDFs
# ---------------------------
if "pdf_paths" not in st.session_state:
    st.session_state.pdf_paths = find_all_pdfs()

with st.sidebar:
    st.caption(f"BASE_DIR: {BASE_DIR}")
    st.caption(f"PDFs discovered on disk: {len(st.session_state.pdf_paths)}")
    for p in st.session_state.pdf_paths[:10]:
        try:
            sz = p.stat().st_size
        except Exception:
            sz = 0
        st.write(f"• {p.relative_to(BASE_DIR)} ({mb(sz)} MB)")

if not st.session_state.pdf_paths:
    st.error("No PDFs found in the deployed filesystem. Ensure PDFs are committed on the same branch Streamlit deploys.")
    st.stop()

# ---------------------------
# Upload PDFs once
# ---------------------------
if "uploaded_pdf_file_names" not in st.session_state:
    with st.spinner("Uploading ALL PDFs to Gemini (one-time per session)..."):
        uploaded, failures = upload_all_pdfs(st.session_state.pdf_paths)

    st.session_state.uploaded_pdf_file_names = uploaded
    st.session_state.upload_failures = failures

with st.sidebar:
    st.caption(f"PDFs uploaded to Gemini: {len(st.session_state.uploaded_pdf_file_names)}")
    if st.session_state.get("upload_failures"):
        st.error(f"Upload failures: {len(st.session_state.upload_failures)}")
        for p, err in st.session_state.upload_failures[:10]:
            st.write(f"- {p.name}: {type(err).__name__} — {err}")

# ---------------------------
# Build / reuse cache once
# ---------------------------
if not st.session_state.textbook_cache_name:
    with st.spinner("Building explicit context cache (one-time per session)..."):
        ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

# ---------------------------
# DISPLAY CHAT
# ---------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# ---------------------------
# MAIN CHAT LOOP
# ---------------------------
if prompt := st.chat_input("Ask Helix a question from your books, create diagrams, quizzes and more..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()

        try:
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

            maybe_summarize_old_chat(st.session_state.messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS)
            history_contents = build_history_contents(st.session_state.messages, max_turns=MAX_TURNS)

            req_contents = []
            if st.session_state.chat_summary.strip():
                req_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Conversation summary:\n" + st.session_state.chat_summary.strip())],
                    )
                )
            req_contents.extend(history_contents)

            cache_name = ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

            tools = [{"google_search": {}}] if ENABLE_GOOGLE_SEARCH_TOOL else None

            text_response = client.models.generate_content(
                model=MODEL_TEXT,
                contents=req_contents,
                config=types.GenerateContentConfig(
                    cached_content=cache_name,
                    tools=tools,
                ),
            )

            # ---- CACHE HIT DEBUG (THIS is the key place) ----
            with st.sidebar:
                um = getattr(text_response, "usage_metadata", None)
                st.write("RESPONSE usage_metadata:", um)
                st.write("cached_content_token_count:", getattr(um, "cached_content_token_count", None))

            bot_text = text_response.text or ""
            thinking_placeholder.empty()

            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # IMAGE GENERATION
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
                                img_status.empty()
                                img_bytes = part.inline_data.data
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
            st.error(f"Helix encountered a technical glitch: {type(e).__name__}: {e}")
