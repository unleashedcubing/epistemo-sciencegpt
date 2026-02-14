import streamlit as st
import google.generativeai as genai
import requests  # New library to handle the API key securely
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Cambridge Science Tutor", page_icon="🔬")
st.title("🔬 Cambridge Science Tutor (Stage 7-9)")
st.write("Ask me for explanations or diagrams! Remember to mention CIE Stage (your grade + 1, so if you're 6th grade, your stage is 7). ")
# --- API SETUP ---
# 1. Google Gemini Key
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Missing Google API Key! Please add it to Streamlit Secrets.")
    st.stop()

# 2. Pollinations Key (Optional but recommended if you have one)
pollinations_key = st.secrets.get("POLLINATIONS_API_KEY", None)

# --- THE BRAIN (System Instructions) ---
system_instruction = """
You are a Cambridge Science Tutor for Stage 7-9 students.

IMPORTANT: If stage isn't given, ask for clarification of stage and then do. Remember them in the first message that the stage number is their grade plus 1.
### RULES FOR TEXTBOOKS:
1. Answer questions based on the uploaded textbooks first.
2. If the answer is NOT in the textbook, search the internet.

### RULES FOR IMAGES (STRICT):
1. **IF THE USER ASKS FOR LABELS/TEXT:** 
   If the user asks for a diagram "with labels", "labeled", or "with text", you MUST reply with this exact sentence:
   "I'm sorry, the text generation in images isn't great, so I can't fix it. It was developed by a 10yr old, so what more can you expect?"
   (Do not generate an image command in this case).

2. **IF THE USER ASKS FOR A NORMAL DIAGRAM:**
   If they just ask for a "diagram of a cell" or "picture of a heart" (without mentioning labels), output this command:
   IMAGE_GEN: [Detailed description of the image, photorealistic, NO TEXT, NO LABELS]
   (Do not say anything else, just that line).

3. **QUESTION PAPERS:**
   Format normally with Section A, B, C.
   Section A - 15 marks with fill in the blank questions, mcqs, and more basic questions.
   Section B - 15 marks with short writing answers.
   Section C - 15 marks with long writing answers.
   Section D - 5 marks with HOTS questions.

   IMPORTANT: Make papers based on grade and lessons given by user and books given as sources.
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", 
    system_instruction=system_instruction
)

# --- HELPER FUNCTION: DOWNLOAD IMAGE ---
def get_image_from_pollinations(prompt):
    # Base URL
    url = f"https://image.pollinations.ai/prompt/{prompt}?nologo=true"
    
    # If you have a key, we pass it safely in the header or URL depending on their API docs.
    # Usually, for Pollinations, simply having the URL is enough, but if you have a pro key,
    # we can add it to the headers if required, or as a parameter.
    # Assuming standard usage, we just fetch the URL.
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.content # Return the image data
        else:
            return None
    except Exception as e:
        return None

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask for a definition or a diagram..."):
    
    # 1. Show User Message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt, "is_image": False})

    # 2. Ask Gemini
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Prepare history
                history = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.messages if not m.get("is_image")]
                
                chat = model.start_chat(history=history)
                response = chat.send_message(prompt)
                response_text = response.text.strip()
                
                # 3. Check for IMAGE_GEN command
                if response_text.startswith("IMAGE_GEN:"):
                    image_prompt = response_text.replace("IMAGE_GEN:", "").strip()
                    st.markdown(f"🎨 *Painting: {image_prompt}...*")
                    
                    # Download image securely on the server
                    image_data = get_image_from_pollinations(image_prompt)
                    
                    if image_data:
                        st.image(image_data, caption="Generated Diagram")
                        # Save image data to history implies saving bytes which is heavy.
                        # Instead, we will save the PROMPT to history so it doesn't break, 
                        # but logically we just showed it. 
                        st.session_state.messages.append({"role": "assistant", "content": image_data, "is_image": True})
                    else:
                        st.error("Sorry, the image generator is busy!")
                    
                else:
                    # Normal Text Answer
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text, "is_image": False})
                
            except Exception as e:
                st.error(f"Error: {e}")