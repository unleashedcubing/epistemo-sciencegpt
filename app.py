import streamlit as st
import os
import time
import io
from google import genai
from google.genai import types

# --- PAGE CONFIG ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- THEME CSS ---
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

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """PUT YOUR FULL SYSTEM INSTRUCTION HERE (exactly as you wrote it)"""

# --- Thinking bubble ---
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

# --- Rolling chat context (last 7 turns) ---
def build_history_contents(messages, max_turns=7):
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
        model="gemini-2.5-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(system_instruction="You are a precise summarizer.")
    )
    st.session_state.chat_summary = (resp.text or "").strip()

# --- Upload ALL PDFs once per session ---
def upload_textbooks():
    pdf_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    handles = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                f = client.files.upload(file=fn)
                while f.state.name == "PROCESSING":
                    time.sleep(1)
                    f = client.files.get(name=f.name)
                handles.append(f)
            except Exception as e:
                st.sidebar.error(f"Error loading {fn}: {e}")
    return handles

# --- Explicit cache for ALL PDFs ---
def ensure_textbook_cache(all_pdf_handles):
    """
    Creates (or re-creates) an explicit cache containing ALL PDFs + system instruction.
    Stored in st.session_state.textbook_cache_name.
    """
    cache_name = st.session_state.get("textbook_cache_name", "")
    if cache_name:
        try:
            _ = client.caches.get(name=cache_name)
            return cache_name
        except Exception:
            st.session_state.textbook_cache_name = ""

    cache = client.caches.create(
        model="gemini-2.5-flash",
        config=types.CreateCachedContentConfig(
            display_name="helix-all-pdfs",
            system_instruction=SYSTEM_INSTRUCTION,
            contents=all_pdf_handles,
            ttl="3600s"  # explicit caching default is 1 hour if not set; setting it makes it obvious [page:0]
        )
    )
    st.session_state.textbook_cache_name = cache.name
    return cache.name

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content":
         "👋 **Hey there! I'm Helix!**\n\n"
         "I'm your friendly CIE tutor here to help you ace your exams! 📖\n\n"
         "**Quick Reminder:** Stage is usually **Grade + 1**.\n"
         "*(Example: Grade 7 → Stage 8)*\n\n"
         "What are we learning today?"}
    ]

if "chat_summary" not in st.session_state:
    st.session_state.chat_summary = ""

if "all_pdf_handles" not in st.session_state:
    with st.spinner("Helix is uploading all PDFs (one-time)..."):
        st.session_state.all_pdf_handles = upload_textbooks()

if "textbook_cache_name" not in st.session_state:
    st.session_state.textbook_cache_name = ""

if not st.session_state.textbook_cache_name:
    with st.spinner("Helix is building the context cache (one-time)..."):
        ensure_textbook_cache(st.session_state.all_pdf_handles)

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
            # Keep animated bubble + change text (no dropdown)
            with thinking_placeholder:
                show_thinking_animation("🔍 Helix is checking ALL textbooks 📚")
            time.sleep(3)

            with thinking_placeholder:
                show_thinking_animation("🧾 Helix is confirming sources…")
            time.sleep(3)

            with thinking_placeholder:
                show_thinking_animation("🧠 Helix is connecting ideas…")
            time.sleep(3)

            with thinking_placeholder:
                show_thinking_animation("✍️ Helix is forming your answer…")
            # (We keep this bubble visible while the API call runs.)

            # Conversation trimming (Perplexity-like)
            maybe_summarize_old_chat(st.session_state.messages, keep_last_msgs=22)
            history_contents = build_history_contents(st.session_state.messages, max_turns=7)

            summary_note = ""
            if st.session_state.chat_summary.strip():
                summary_note = "Conversation summary (for context):\n" + st.session_state.chat_summary.strip()

            request_contents = []
            if summary_note:
                request_contents.append(summary_note)
            request_contents.extend(history_contents)

            # Ensure cache still exists (TTL expiry / errors)
            cache_name = ensure_textbook_cache(st.session_state.all_pdf_handles)

            # Use cached PDFs (ALL PDFs) instead of re-sending them every time
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=request_contents,
                config=types.GenerateContentConfig(
                    cached_content=cache_name
                )
            )

            bot_text = text_response.text or ""

            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # Debug: show whether caching hit (optional)
            try:
                cc = getattr(text_response.usage_metadata, "cached_content_token_count", None)
                if cc is not None:
                    st.sidebar.caption(f"cached_content_token_count: {cc}")  # should be > 0 on cache hits [page:0]
            except Exception:
                pass

            # --- IMAGE GENERATION (unchanged) ---
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\\n")[0]

                img_status = st.empty()
                with img_status:
                    show_thinking_animation("🖌️ Helix is painting a diagram 🎨")

                for attempt in range(2):
                    try:
                        image_response = client.models.generate_content(
                            model="gemini-3-pro-image-preview",
                            contents=[img_desc],
                            config=types.GenerateContentConfig(
                                response_modalities=['TEXT', 'IMAGE']
                            )
                        )
                        for part in image_response.parts:
                            if part.inline_data:
                                img_bytes = part.inline_data.data
                                img_status.empty()
                                st.image(img_bytes, caption="Generated by Helix")
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": img_bytes,
                                    "is_image": True
                                })
                        break
                    except Exception as inner_e:
                        if "503" in str(inner_e) and attempt == 0:
                            time.sleep(2)
                            continue
                        else:
                            img_status.empty()
                            st.error(f"Image generation failed: {inner_e}")

        except Exception as e:
            thinking_placeholder.empty()
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Helix's connection to the books timed out. Please refresh the page!")
                if "all_pdf_handles" in st.session_state:
                    del st.session_state.all_pdf_handles
                if "textbook_cache_name" in st.session_state:
                    st.session_state.textbook_cache_name = ""
            else:
                st.error(f"Helix encountered a technical glitch: {e}")
