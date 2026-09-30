import streamlit as st
from utils.login_manager import LoginManager
from supabase import create_client, Client

# --- Constants ---
SUPABASE_URL = st.secrets["urls"]["supabase_url"]
SUPABASE_KEY = st.secrets["api_keys"]["supabase_key"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Require Authentication ---
login_manager = LoginManager(supabase)
login_manager.check_authentication()

# --- Main Function ---
def main():

    intro_text = """
    
        ### 💡 Innovative elements of this project
        The innovation behind SARA lies in its role as a **digital peer**, integrating existing 
        **large language models (LLMs)** to automate the screening process in literature reviews. 
        Most current solutions fail to maintain the systematic approach required in literature 
        research and lack transparency in their decision-making processes. SARA fills this gap by 
        providing specific justifications for each decision made during the **title, abstract, and 
        full-text screening**, ensuring that every step in the process remains transparent and 
        reproducible. Our goal is to provide a tool to support the scientific community at 
        ZHAW in future reviews, improving quality and reducing costs.

        ### 📚 PRISMA Literature Review System

        This project provides an interactive **PRISMA-based** literature review system.  
        It allows researchers to **import, screen, and filter scientific studies** following a **structured step-by-step process**.

        The system ensures **transparency and reproducibility** by logging each step, enabling researchers to track **how and when** studies were included or excluded.

        ### ✨ **Features**
        ✔ Import scientific literature from **RIS/BibTeX** files  
        ✔ Define **research questions, inclusion & exclusion criteria**  
        ✔ Automatically **detect & remove duplicates**  
        ✔ Perform **Title/Abstract screening** using an LLM  
        ✔ Conduct **Full-Text screening** using an LLM  
        ✔ Export results in **CSV, JSON, RIS, and BibTeX**  
        ✔ Generate detailed **logs for reproducibility**  

        ### 📌 **Workflow Overview**
        The PRISMA workflow is executed in **six key steps**, ensuring a **systematic and transparent** review process.

        1️⃣ **Define Research Objectives & Criteria**  
        - Enter the **research objectives**.  
        - Specify **inclusion & exclusion criteria**. 
        
        2️⃣ **Upload Literature Sources**  
        - Import multiple **RIS/BibTeX** files (e.g., PubMed, IEEE Xplore, PsycInfo). 
        
        3️⃣ **Remove Duplicates**  
        - Identify and remove duplicates **within** and **across** sources.  

        4️⃣ **Title & Abstract Screening**  
        - Each study is **screened by an LLM** based on the defined criteria.  
        - Studies are either **included or excluded** with a reasoning log.  

        5️⃣ **Full-Text Screening**  
        - The full text is **analyzed by an LLM**, ensuring only relevant studies remain.  

        6️⃣ **Export Results**  
        - Final dataset can be exported as **CSV, JSON, RIS, and BibTeX**.  
        - **Intermediate results** (after Title/Abstract screening) are also available.  

        ### 🚨 **Disclaimer**

        The tool is currently in the development phase and may not be fully functional. This is a
        prototype and should be used for demonstration purposes only. All research results should be
        verified by a human expert. 
        """

    st.title("Welcome to SARA")
    with st.container(border=True):
        st.markdown(intro_text)

    # if st.button("Next Page :material/arrow_forward_ios:"):
    #     st.switch_page("page/review_setup.py")

if __name__ == "__main__":
    main()