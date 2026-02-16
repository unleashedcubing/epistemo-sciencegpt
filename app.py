import streamlit as st
import os
import time
import io
from google import genai
from google.genai import types

# --- PAGE CONFIG ---
st.set_page_config(page_title="CIE Science Tutor", page_icon="🧬", layout="centered")

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

<div class="big-title">🧬 helix.ai</div>
<div class="subtitle">Your CIE Science Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)


# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science Tutor for Stage 7-9 students.

***REMEMBER VERY IMPORTANT!!!!!: The moment you recieve the user prompt, wait 4 seconds and read the prompt fully. If you are 90% sure that the user's query is not related to the book sources, don't bother checking the books, answer based on internet/your own way. If you aren't sure, check the books.***

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: The textbooks were too big, so I split each into 2. The names would have ..._1.pdf or ..._2.pdf. The ... area would have the year. Check both when queries come up.
ALSO: In MCQs, randomize the answers, because in a previous test I did using you, the answers were 1)C, 2)C, 3)C, 4)C. REMEMBER, RANDOMIZE MCQ ANSWERS
ALSO: Use BOTH WB (Workbook) AND TB (Textbook) because the WB has questions mainly, but SB has theory. Using BOTH WILL GIVE YOU A WIDE RANGE OF QUESTIONS.
ALSO: DO NOT INTRODUCE YOURSELF LIKE "I am Helix!" as I have already created and introduction message. Just get to the user's query immediately.

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
- When you answer using the textbook, you MUST cite the source like this: "(Source: [display_name of the file])", at the end of the response, not at every line.
- When you cite a textbook, don't mention the .1/.2 book part. Just the name of the book.

### RULE 2: IMAGE GENERATION (STRICT)
- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart", or a infographic or mindmap, you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality scientific illustration of the topic, detailed, white background, with labels]

### RULE 3: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Title: [Topic] Assessment
  - Section A: 5 Multiple Choice Questions/Fill in the blanks, etc. (1 mark each).
  - Section B: 10 Short Answer Questions (2 marks each).
  - Section C: 6 Long Answer Questions (3 marks each).
  - Section D: 2 Think Like a Scientist Questions (HARD) (5 marks each).
  - A complete Answer Key at the very end.

### RULE 4: ARMAAN STYLE
If a user asks you to reply in Armaan Style, you have to explain in expert physicist/chemist/biologist terms, with difficult out of textbook sources. You can then simple it down if the user wishes.
"""

# --- TEXTBOOK UPLOADER (No Cache, Direct Upload) ---
def upload_textbooks():
    pdf_filenames = ["CIE_9_WB_Sci.pdf","CIE_9_WB_Math.pdf","CIE_8_WB_ANS_Sci_Math.pdf","CIE_8_SB_Math.pdf","CIE_8_SB_1_Sci.pdf","CIE_8_SB_1_Eng.pdf","CIE_7_WB_Sci.pdf","CIE_7_WB_Eng.pdf","CIE_7_WB_ANS_Math.pdf","CIE_7_SB_2_Sci.pdf","CIE_7_SB_1_Eng.pdf","CIE_7_SB_Eng.pdf","CIE_9_SB_1_Sci.pdf","CIE_8_SB_2_Sci.pdf","CIE_8_SB_2_Eng.pdf","CIE_7_WB.pdf","CIE_7_SB.pdf","CIE_9_WB.pdf","CIE_7_SB_ANS.pdf","CIE_8_WB_Sci.pdf"]

    active_files = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                # Fresh upload for the session to ensure active permission handles
                uploaded_file = client.files.upload(file=fn)
                active_files.append(uploaded_file)
                
                # Wait for ACTIVE state (crucial for Gemini to read them)
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(1)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                    
            except Exception as e:
                st.sidebar.error(f"Error loading {fn}: {e}")
    return active_files

# --- THINKING ANIMATION ---
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

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly science tutor here to help you ace your CIE exams! 🧬\n\nI can answer your doubts, draw diagrams, and create quizes! 🧪\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?"}
    ]

if "textbook_handles" not in st.session_state:
    with st.spinner("Helix is reading the Cambridge Workbooks..."):
        st.session_state.textbook_handles = upload_textbooks()

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask Helix a question from your books, create diagrams, quizes and more..."):
    # 1. Show User Message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        # Show thinking animation
        thinking_placeholder = st.empty()
        with thinking_placeholder:
            show_thinking_animation("🔍 Helix is searching the textbooks 📚")
        
        try:
            # 2. TEXT RESPONSE (Gemini 2.5 Flash - Direct File Access)
            # We send the file handles + prompt directly. 2.5 Flash handles this.
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=st.session_state.textbook_handles + [prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            
            # Clear thinking animation and show response
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # 3. IMAGE GENERATION (Gemini 3 Pro Multimodal)
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\\n")[0]
                
                img_thinking_placeholder = st.empty()
                with img_thinking_placeholder:
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
                                img_thinking_placeholder.empty()
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
                            img_thinking_placeholder.empty()
                            st.error(f"Image generation failed: {inner_e}")

        except Exception as e:
            thinking_placeholder.empty()
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Helix's connection to the workbooks timed out. Please refresh the page!")
                del st.session_state.textbook_handles
            else:
                st.error(f"Helix encountered a technical glitch: {e}")
