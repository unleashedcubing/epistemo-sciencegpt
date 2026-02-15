import streamlit as st
import google.generativeai as genai
import requests
import io
import urllib.parse

# --- PAGE SETUP ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")
st.title("🔬 Cambridge Science Tutor")
st.write("Ask for explanations or diagrams! (I am now using your Private Image API)")

# --- API SETUP ---
# 1. Google Gemini Key
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Missing Google API Key.")
    st.stop()

# 2. Pollinations Key (CRITICAL for the new endpoint)
if "POLLINATIONS_API_KEY" in st.secrets:
    pollinations_key = st.secrets["POLLINATIONS_API_KEY"]
else:
    st.warning("⚠️ No Pollinations Key found. Images might be slow or fail.")
    pollinations_key = None

# --- THE BRAIN (Gemini Instructions) ---
system_instructions = """
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
    system_instruction=system_instructions
)

# --- NEW FUNCTION: AUTHENTICATED IMAGE DOWNLOAD ---
def get_image_authenticated(prompt):
    # 1. URL Encode the prompt (e.g., "blue sky" -> "blue%20sky")
    encoded_prompt = urllib.parse.quote(prompt)
    
    # 2. Use the PRIVATE endpoint you found
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
    
    # 3. Add the Authorization Header (The specific fix)
    headers = {}
    if pollinations_key:
        headers["Authorization"] = f"Bearer {pollinations_key}"
        # print(f"Using Authenticated API for: {prompt}") # Debugging
    
    try:
        # Send the request with the headers
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"Image API Error: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"], caption=message.get("caption"))
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask a science question..."):
    
    # 1. Show User Message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    # 2. Ask Gemini
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Get text response
                history = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.messages if not m.get("is_image")]
                chat = model.start_chat(history=history)
                response = chat.send_message(prompt)
                response_text = response.text.strip()
                
                # 3. Check for IMAGE_GEN command
                if response_text.startswith("IMAGE_GEN:"):
                    image_prompt = response_text.replace("IMAGE_GEN:", "").strip()
                    st.markdown(f"🎨 *Generating high-quality image: {image_prompt}...*")
                    
                    # CALL THE NEW AUTHENTICATED FUNCTION
                    image_data = get_image_authenticated(image_prompt)
                    
                    if image_data:
                        st.image(image_data, caption=image_prompt)
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": image_data, 
                            "is_image": True,
                            "caption": image_prompt
                        })
                    else:
                        st.error("Could not generate image.")
                else:
                    # Normal Text
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text, "is_image": False})
                
            except Exception as e:
                st.error(f"Error: {e}")
