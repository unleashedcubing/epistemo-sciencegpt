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
        st.error("🚨 Critical Error: GOOGLE_API_KEY not found. Please set it in Secrets or Environment Variables.")
        st.stop()

try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"🚨 Failed to initialize Gemini Client: {e}")
    st.stop()

# --- 3. THEME CSS ---
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
(Keep the rest of your instructions here as they were...)
"""

# --- 5. ROBUST FILE FINDER & UPLOADER ---
def find_file_robust(target_filename):
    """
    Searches for a file recursively in the current directory.
    Handles case-sensitivity mismatches.
    """
    target_lower = target_filename.lower()
    root_dir = Path.cwd()
    
    # 1. Direct check
    if (root_dir / target_filename).exists():
        return root_dir / target_filename
        
    # 2. Walk through all directories
    for path in root_dir.rglob("*"):
        if path.is_file():
            if path.name == target_filename:
                return path
            if path.name.lower() == target_lower:
                return path
    return None

def upload_textbooks():
    """
    Finds and uploads textbooks.
    """
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    
    active_files = []
    
    # 🔍 DEBUG: Show what files actually exist in the environment
    st.sidebar.markdown("### 📂 File System Debug")
    cwd = Path.cwd()
    st.sidebar.code(f"Current Dir: {cwd}")
    
    all_pdfs = list(cwd.rglob("*.pdf"))
    st.sidebar.write(f"📄 Total PDFs found in tree: {len(all_pdfs)}")
    if len(all_pdfs) > 0:
        st.sidebar.json([p.name for p in all_pdfs[:5]]) # Show first 5 found
    else:
        st.sidebar.error("❌ ZERO PDFs found. Did you commit them to Git?")
        st.sidebar.info("Common fix: Make sure files are not in .gitignore")
        return []

    # Progress bar
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    for i, target_name in enumerate(target_filenames):
        progress = (i + 1) / len(target_filenames)
        progress_bar.progress(progress)
        
        # Use robust finder
        found_path = find_file_robust(target_name)
        
        if found_path:
            try:
                # Check size
                file_size_mb = found_path.stat().st_size / (1024 * 1024)
                status_text.text(f"⬆️ Uploading: {found_path.name} ({file_size_mb:.1f} MB)...")
                
                # UPLOAD
                uploaded_file = client.files.upload(
                    file=found_path,
                    config={'mime_type': 'application/pdf'}
                )
                
                # WAIT
                start_time = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - start_time > 30:
                        st.sidebar.warning(f"⚠️ Timeout: {target_name}")
                        break
                    time.sleep(1)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                
                if uploaded_file.state.name == "ACTIVE":
                    active_files.append(uploaded_file)
                else:
                    st.sidebar.error(f"❌ Failed: {target_name} ({uploaded_file.state.name})")
                    
            except Exception as e:
                st.sidebar.error(f"🚨 Error {target_name}: {e}")
        else:
            # File truly not found
            # Optional: warn only for specific missing files to reduce clutter
            if i < 3: # Only show first few missing to avoid spamming
                st.sidebar.warning(f"⚠️ Not found: {target_name}")
    
    status_text.empty()
    progress_bar.empty()
    
    if active_files:
        st.sidebar.success(f"📚 {len(active_files)} Books Ready!")
    else:
        st.sidebar.error("❌ No books loaded.")
        
    return active_files

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
        thinking_html = f"""
        <div class="thinking-container">
            <span class="thinking-text">{message}</span>
            <div class="thinking-dots">
                <div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div>
            </div>
        </div>
        """
        placeholder.markdown(thinking_html, unsafe_allow_html=True)
        time.sleep(3)

def show_thinking_animation(message="Helix is thinking"):
    return st.markdown(f"""
    <div class="thinking-container">
        <span class="thinking-text">{message}</span>
        <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
    </div>
    """, unsafe_allow_html=True)

# --- 7. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizes! 📚\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?"}
    ]

# Start upload if needed
if "textbook_handles" not in st.session_state:
    st.sidebar.info("🚀 Searching for Books...")
    st.session_state.textbook_handles = upload_textbooks()

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
            # 1. Warn if no files
            if not st.session_state.textbook_handles:
                st.warning("⚠️ Helix couldn't find your textbooks. Answering with general knowledge.")
            
            # 2. Generate
            text_response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=st.session_state.textbook_handles + [prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # 3. Image Gen
            if "IMAGE_GEN:" in bot_text:
                try:
                    img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    img_thinking = st.empty()
                    with img_thinking: show_thinking_animation("🖌️ Painting diagram...")
                    
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
                except Exception as e:
                    st.error(f"Image error: {e}")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")
            if "403" in str(e):
                st.warning("⚠️ Session expired. Refresh page.")
