import streamlit as st
import google.generativeai as genai
import requests
import urllib.parse
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")
st.title("🔬 Cambridge Science Tutor")
st.write("Ask for explanations or diagrams!")

# --- API SETUP ---
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("Missing GOOGLE_API_KEY in Secrets.")
    st.stop()

pollinations_key = st.secrets.get("POLLINATIONS_API_KEY")

# --- THE BRAIN (Gemini 2.5 Flash) ---
system_instruction = """
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
  IMAGE_GEN: [A high-quality scientific illustration of the topic, detailed, white background, no text, no words, no labels.] If you feel that the user is asking for a whole chapter mind map or diagram, create a infographic.

### RULE 3: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Title: [Topic] Assessment
  - Section A: 5 Multiple Choice Questions/Fill in the blanks, etc. (1 mark each).
  - Section B: 10 Short Answer Questions (2 marks each).
  - Section C: 6 Long Answer Questions (3 marks each).
  - Section D: 2 Think Like a Scientist Questions (HARD) (5 marks each).
  - A complete Answer Key at the very end.
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", 
    system_instruction=system_instruction
)

# --- PDF HANDLING ---
@st.cache_resource
def load_textbooks():
    # List your PDF filenames here
    pdf_filenames = ["textbook1.pdf", "textbook2.pdf"] 
    uploaded_files = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                f = genai.upload_file(path=fn, display_name=fn)
                uploaded_files.append(f)
            except Exception:
                pass
    return uploaded_files

if "textbook_data" not in st.session_state:
    st.session_state.textbook_data = load_textbooks()

# --- IMAGE GENERATOR (flux schnell) ---
def generate_image(prompt):
    encoded_prompt = urllib.parse.quote(prompt)
    model_param = urllib.parse.quote("flux")
    
    # Try Private API first
    if pollinations_key:
        url = f"https://gen.pollinations.ai/image/{encoded_prompt}?model={model_param}"
        headers = {"Authorization": f"Bearer {pollinations_key}"}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200: return r.content
        except: pass

    # Fallback to Public API
    url_pub = f"https://image.pollinations.ai/prompt/{encoded_prompt}?nologo=true"
    try:
        r = requests.get(url_pub, timeout=30)
        if r.status_code == 200: return r.content
    except: pass
    return None

# --- CHAT INTERFACE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("is_image"): st.image(msg["content"])
        else: st.markdown(msg["content"])

if prompt := st.chat_input("Ask a science question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            # Combine textbooks with prompt
            content = st.session_state.textbook_data + [prompt]
            response = model.generate_content(content)
            txt = response.text
            
            if "IMAGE_GEN:" in txt:
                img_prompt = txt.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                st.write(f"🎨 Generating: {img_prompt}...")
                img_data = generate_image(img_prompt)
                if img_data:
                    st.image(img_data)
                    st.session_state.messages.append({"role": "assistant", "content": img_data, "is_image": True})
                else:
                    st.error("Image generation failed.")
            else:
                st.markdown(txt)
                st.session_state.messages.append({"role": "assistant", "content": txt})
        except Exception as e:
            st.error(f"Error: {e}")
