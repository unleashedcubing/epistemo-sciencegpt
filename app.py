import streamlit as st
import os
import io
import time
from google import genai
from google.genai import types
from PIL import Image

# --- PAGE SETUP ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")
st.title("🔬 Cambridge Science Tutor")
st.caption("Powered by Gemini 2.5 Flash (Brain) & Gemini 3 Pro (Visuals)")

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Missing API Key in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- SYSTEM RULES ---
SYSTEM_INSTRUCTION = """
You are a Cambridge Science Tutor for Stage 7-9 students. You are friendly, encouraging, and precise.

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: Remind the user ONLY ONCE that their stage is their grade + 1, so if they are 8th, their stage is 9th.

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
- When you answer using the textbook, you MUST cite the source like this: "(Source: [display_name of the file])".

### RULE 2: IMAGE GENERATION (STRICT)

- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart", you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality scientific illustration of the topic, detailed, white background, with labels]

### RULE 3: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Title: [Topic] Assessment
  - Section A: 5 Multiple Choice Questions/Fill in the blanks, etc. (1 mark each).
  - Section B: 10 Short Answer Questions (2 marks each).
  - Section C: 6 Long Answer Questions (3 marks each).
  - Section D: 2 Think Like a Scientist Questions (HARD) (5 marks each).
  - A complete Answer Key at the very end.
"""

# --- TEXTBOOK UPLOADER ---
def upload_textbooks():
    pdf_filenames = ["CIE_7_WB.pdf", "CIE_8_WB.pdf", "CIE_9_WB.pdf"] 
    active_files = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                uploaded_file = client.files.upload(file=fn)
                active_files.append(uploaded_file)
            except Exception as e:
                st.sidebar.error(f"Error loading {fn}: {e}")
    return active_files

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "textbook_handles" not in st.session_state:
    with st.spinner("Preparing Cambridge Science Workbooks..."):
        st.session_state.textbook_handles = upload_textbooks()

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask a science question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            # 1. TEXT RESPONSE (Gemini 2.5 Flash)
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=st.session_state.textbook_handles + [prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # 2. IMAGE RESPONSE (Gemini 3 Pro)
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                
                with st.status("🎨 Gemini 3 Pro is creating your diagram..."):
                    # Retry loop for 503 errors
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
                                if part.image:
                                    # THE FIX: Open the raw data bytes using Pillow directly
                                    # This bypasses the attribute error entirely
                                    raw_data = part.image.data
                                    img = Image.open(io.BytesIO(raw_data))
                                    
                                    # Display to user
                                    st.image(img)
                                    
                                    # Convert to PNG bytes for chat history
                                    buf = io.BytesIO()
                                    img.save(buf, format="png")
                                    st.session_state.messages.append({
                                        "role": "assistant", 
                                        "content": buf.getvalue(), 
                                        "is_image": True
                                    })
                            break
                        except Exception as inner_e:
                            if "503" in str(inner_e) and attempt == 0:
                                time.sleep(2)
                                continue
                            else:
                                raise inner_e

        except Exception as e:
            if "503" in str(e):
                st.error("Google's servers are busy. Please wait 10 seconds and try again.")
            elif "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Session expired. Refreshing textbooks... please re-send your question.")
                del st.session_state.textbook_handles
            else:
                st.error(f"Something went wrong: {e}")
