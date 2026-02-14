import streamlit as st
import google.generativeai as genai
import os
import requests
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Epistemo ScienceGPT", page_icon="🔬")
st.title("🔬 Epistemo ScienceGPT (CIE Stage 7-9)")
st.write("Ask me for explanations, question papers, or diagrams!")

# --- API SETUP ---
# 1. Google Gemini Key
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except KeyError:
    st.error("🔴 Missing Google API Key! Please add it to your Streamlit Secrets.")
    st.stop()

# --- THE BRAIN (System Instructions for Gemini) ---
system_instruction = """
You are a Cambridge Science Tutor for Stage 7-9 students. You are friendly, encouraging, and precise.

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: Remind the user ONLY ONCE that their stage is their grade + 1, so if they are 8th, their stage is 9th.
ALSO: If the user mentions their stage in the beginning, remember that stage for all future queries and answers, unless they mention a different stage.

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
- When you answer using the textbook, you MUST cite the source like this: "(Source: [display_name of the file])".

### RULE 2: IMAGE GENERATION (STRICT)
- **IF THE USER ASKS FOR LABELS/TEXT:** If the user's prompt includes words like "with labels", "labeled", or "with text", you MUST reply with this exact sentence and nothing else:
  "I'm sorry, the text generation in images isn't great, so I can't fix it. It was developed by a 10yr old, so what more can you expect?"

- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart" (without mentioning labels), you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality scientific illustration of the topic, detailed, white background, no text, no words, no labels.]

### RULE 3: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Title: [Topic] Assessment
  - Section A: 5 Multiple Choice Questions/Fill in the blanks, etc. (1 mark each).
  - Section B: 10 Short Answer Questions (3 marks each).
  - Section C: 6 Long Answer Questions (5 marks each).
  - Section D: 2 Think Like a Scientist Questions (2.5 marks each).
  - A complete Answer Key at the very end.
"""

# --- MODEL INITIALIZATION ---
# Use 'gemini-1.5-flash-latest' to ensure you have the newest version
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", 
    system_instruction=system_instruction
)

# --- FILE HANDLING ---
@st.cache_resource
def get_textbook_content():
    
    pdf_files = ["CIE_9_WB.pdf", "CIE_8_WB.pdf", "CIE_7_WB.pdf"]
    
    uploaded_parts = []
    st.write("Checking for textbooks in the repository...") # Status message
    
    for pdf in pdf_files:
        if os.path.exists(pdf):
            try:
                # The API uses the "display_name" for citations in the prompt
                sample_file = genai.upload_file(path=pdf, display_name=pdf)
                uploaded_parts.append(sample_file)
                st.success(f"✅ Successfully loaded '{pdf}'!")
            except Exception as e:
                st.error(f"⚠️ Could not process '{pdf}'. Error: {e}")
        else:
            st.warning(f"🟡 Could not find the file '{pdf}'. Make sure it's uploaded to GitHub!")
            
    return uploaded_parts

# Load files once and cache them
if "files" not in st.session_state:
    with st.spinner("Loading and reading textbooks... This might take a moment."):
        st.session_state.files = get_textbook_content()
        if not st.session_state.files:
            st.error("No textbooks were loaded. The bot will rely on general knowledge only.")

# --- HELPER FUNCTION: IMAGE GENERATION ---
@st.cache_data
def get_image_from_pollinations(prompt):
    url = f"https://image.pollinations.ai/prompt/{prompt}?nologo=true"
    try:
        response = requests.get(url)
        response.raise_for_status() # Raises an error for bad responses (4xx or 5xx)
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"Pollinations request failed: {e}")
        return None

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"], caption=message.get("caption", "Generated Diagram"))
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("What is your science question?"):
    
    # 1. Show user's message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    # 2. Prepare content for Gemini (Text + Files)
    full_prompt_content = st.session_state.files + [prompt]

    # 3. Generate response
    with st.chat_message("assistant"):
        with st.spinner("🔬 Thinking..."):
            try:
                response = model.generate_content(full_prompt_content)
                response_text = response.text.strip()
                
                # 4. Check for IMAGE_GEN command
                if response_text.startswith("IMAGE_GEN:"):
                    image_prompt = response_text.replace("IMAGE_GEN:", "").strip()
                    st.markdown(f"🎨 *Painting: {image_prompt}...*")
                    
                    image_data = get_image_from_pollinations(image_prompt)
                    
                    if image_data:
                        st.image(image_data, caption=image_prompt)
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": image_data, 
                            "is_image": True,
                            "caption": image_prompt
                        })
                    else:
                        st.error("Sorry, the image generator is busy or failed. Please try again.")
                    
                else:
                    # Normal Text Answer (or the apology)
                    st.markdown(response_text)
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": response_text, 
                        "is_image": False
                    })
                
            except Exception as e:
                st.error(f"An error occurred with the AI model: {e}")
