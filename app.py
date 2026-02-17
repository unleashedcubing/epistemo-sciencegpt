import os
import time
from pathlib import Path

# --- ROBUST TEXTBOOK UPLOADER ---
def upload_textbooks():
    """
    Uploads textbooks with extensive debugging to find path/permission errors.
    """
    pdf_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    
    active_files = []
    
    # 🔍 DEBUG: Print environment info to Sidebar
    st.sidebar.markdown("### 📂 File System Debug")
    cwd = os.getcwd()
    st.sidebar.code(f"Current Dir: {cwd}")
    
    # List all files in current directory to verify presence
    all_files = os.listdir(cwd)
    pdf_files_found = [f for f in all_files if f.lower().endswith('.pdf')]
    st.sidebar.write(f"📄 PDFs Found: {len(pdf_files_found)}")
    
    if not pdf_files_found:
        st.sidebar.error("❌ No PDF files found in the current directory!")
        return []

    # Progress bar for uploads
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    for i, fn in enumerate(pdf_filenames):
        # Update progress
        progress = (i + 1) / len(pdf_filenames)
        progress_bar.progress(progress)
        
        # Robust path handling
        file_path = Path(cwd) / fn
        
        if file_path.exists():
            try:
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                status_text.text(f"⬆️ Uploading: {fn} ({file_size_mb:.1f} MB)...")
                
                # UPLOAD FILE
                uploaded_file = client.files.upload(path=str(file_path))
                
                # Wait for processing (Timeout after 30s)
                start_time = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - start_time > 30:
                        st.sidebar.warning(f"⚠️ Timeout processing {fn}")
                        break
                    time.sleep(1)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                
                # Check final state
                if uploaded_file.state.name == "ACTIVE":
                    active_files.append(uploaded_file)
                    # Optional: Print success to console/logs
                    print(f"✅ Successfully loaded: {fn}")
                else:
                    st.sidebar.error(f"❌ Failed: {fn} (State: {uploaded_file.state.name})")
                    print(f"❌ Failed to load: {fn}")
                    
            except Exception as e:
                st.sidebar.error(f"🚨 Error with {fn}: {str(e)}")
                print(f"🚨 Exception uploading {fn}: {e}")
        else:
            # Only warn if it was expected but missing
            if fn in pdf_filenames:
                st.sidebar.warning(f"⚠️ File missing: {fn}")
    
    status_text.empty()
    progress_bar.empty()
    
    if active_files:
        st.sidebar.success(f"📚 {len(active_files)} Textbooks Ready!")
    else:
        st.sidebar.error("❌ No textbooks could be loaded.")
        
    return active_files
