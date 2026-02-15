import streamlit as st
import os
import io
from google import genai
from google.genai import types
from PIL import Image

# --- PAGE CONFIG ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")

st.title("🔬 Cambridge Science Tutor")
st.caption("Stage 7-9 Science Specialist")

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Please add your GOOGLE_API_KEY to Streamlit Secrets.")
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
- **IF THE USER ASKS FOR LABELS/TEXT:** If the user's prompt includes words like "with labels", "labeled", or "with text", you MUST reply with this exact sentence and nothing else:
  "I'm sorry, the text generation in images isn't great, so I can't fix it. It was developed by a 10yr old, so what more can you expect?"

- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart" (without mentioning labels), you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality scientific illustration of the topic, detailed, white background, no text, no words, no labels.] IF

### RULE 3: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Title: [Topic] Assessment
  - Section A: 5 Multiple Choice Questions/Fill in the blanks, etc. (1 mark each).
  - Section B: 10 Short Answer Questions (2 marks each).
  - Section C: 6 Long Answer Questions (3 marks each).
  - Section D: 2 Think Like a Scientist Questions (HARD) (5 marks each).
  - A complete Answer Key at the very end.
"""

# --- ROBUST FILE UPLOADER ---
def upload_textbooks():
    pdf_filenames = ["CIE_7_WB.pdf", "CIE_8_WB.pdf", "CIE_9_WB.pdf"] 
    active_files = []
    
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                # Uploading fresh for the session to avoid 403 errors
                uploaded_file = client.files.upload(file=fn)
                active_files.append(uploaded_file)
            except Exception as e:
                st.sidebar.error(f"Error loading {fn}: {e}")
    return active_files

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# We store handles in session_state, but if they are missing or error out, we re-upload
if "textbook_handles" not in st.session_state:
    with st.spinner("Preparing textbooks..."):
        st.session_state.textbook_handles = upload_textbooks()

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- CHAT INPUT ---
if prompt := st.chat_input("Ask a science question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            # Prepare contents: Textbooks + User Prompt
            # If handles exist, we pass them; if not, we just pass prompt
            contents = st.session_state.textbook_handles + [prompt]

            # 1. TEXT RESPONSE (Gemini 2.5 Flash)
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
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
                
                with st.status("🎨 Gemini 3 Pro is painting your diagram..."):
                    image_response = client.models.generate_content(
                        model="gemini-3-pro-image-preview",
                        contents=[img_desc],
                        config=types.GenerateContentConfig(
                            response_modalities=['IMAGE']
                        )
                    )
                    
                    for part in image_response.parts:
                        if image := part.as_image():
                            st.image(image)
                            # Store bytes for history
                            buf = io.BytesIO()
                            image.save(buf, format="PNG")
                            st.session_state.messages.append({
                                "role": "assistant", 
                                "content": buf.getvalue(), 
                                "is_image": True
                            })

        except Exception as e:
            # If we get a 403, it means the files expired. Clear them so they re-upload next time.
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Session expired. Refreshing textbooks... please try your question again in a moment.")
                del st.session_state.textbook_handles
            else:
                st.error(f"Something went wrong: {e}")
