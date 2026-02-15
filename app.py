import streamlit as st
import os
import io
from google import genai
from google.genai import types
from PIL import Image

# --- PAGE CONFIG ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")

st.title("🔬 Cambridge Science Tutor")
st.write("Powered by Gemini 2.5 Flash & Gemini 3 Pro")

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Please add your GOOGLE_API_KEY to Streamlit Secrets.")
    st.stop()

# Initialize the new Client
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

# --- TEXTBOOK LOADING ---
@st.cache_resource
def load_textbooks():
    # Update these filenames to match your PDFs uploaded to GitHub
    pdf_filenames = ["CIE_7_WB.pdf", "CIE_8_WB.pdf", "CIE_9_WB.pdf"] 
    files_to_attach = []
    
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                # FIX: Use 'file' instead of 'path'
                uploaded_file = client.files.upload(file=fn)
                files_to_attach.append(uploaded_file)
            except Exception as e:
                st.warning(f"Could not load {fn}: {e}")
    return files_to_attach

# --- INITIALIZE SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "textbook_handles" not in st.session_state:
    with st.spinner("Loading Science Textbooks..."):
        st.session_state.textbook_handles = load_textbooks()

# --- DISPLAY CHAT HISTORY ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- CHAT INPUT ---
if prompt := st.chat_input("Ask a science question..."):
    # 1. Display User Message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            # --- STEP 1: TEXT GENERATION (Gemini 2.5 Flash) ---
            # Using the exact model name you requested
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

            # --- STEP 2: IMAGE GENERATION (Gemini 3 Pro) ---
            if "IMAGE_GEN:" in bot_text:
                # Extract image description
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                
                with st.status("🎨 Creating Diagram with Gemini 3 Pro..."):
                    image_response = client.models.generate_content(
                        model="gemini-3-pro-image-preview",
                        contents=[img_desc],
                        config=types.GenerateContentConfig(
                            response_modalities=['IMAGE']
                        )
                    )
                    
                    for part in image_response.parts:
                        # Check if part has image data
                        if image := part.as_image():
                            st.image(image)
                            
                            # Save to history
                            buf = io.BytesIO()
                            image.save(buf, format="PNG")
                            st.session_state.messages.append({
                                "role": "assistant", 
                                "content": buf.getvalue(), 
                                "is_image": True
                            })

        except Exception as e:
            st.error(f"Error: {e}")
