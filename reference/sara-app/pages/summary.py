import streamlit as st
from utils.login_manager import LoginManager
from utils.graphs import PRISMAFlowchart
import json
from streamlit_lottie import st_lottie
from st_aggrid import AgGrid, GridOptionsBuilder
from st_aggrid.grid_options_builder import GridOptionsBuilder
from supabase import create_client
from st_pages import hide_pages
from supabase import create_client, Client

# --- Constants ---
SUPABASE_URL = st.secrets["urls"]["supabase_url"]
SUPABASE_KEY = st.secrets["api_keys"]["supabase_key"]
LOTTIE_PATH = "./static/ai_brain.json"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- Require Authentication ---
login_manager = LoginManager(supabase)
login_manager.check_authentication()

# --- Main Function ---
def main():
    st.title("Review Overview")
    col1, col2 = st.columns([3, 1])
    with col1:
        with st.container(border=True):
            st.info("""
                This page provides an overview of the review process, including the number of studies included and excluded at each stage.
                It also allows you to download the PRISMA chart as a PNG file.
                
                **Note:** The PRISMA chart is automatically generated based on the data collected during the review process.
                """)
            st.markdown("### Results Overview")
            page_size = 5
            if "results_df" in st.session_state:
                st.markdown("**Here is a preview of your entries:**")
                gb = GridOptionsBuilder.from_dataframe(st.session_state.results_df)
                gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
                gb.configure_default_column(groupable=True, sortable=True, filter=True)
                gridOptions = gb.build()

                AgGrid(st.session_state.results_df, gridOptions=gridOptions, height=200, fit_columns_on_grid_load=True)

                # download results
                csv = st.session_state.results_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download Results as CSV",
                    data=csv,
                    file_name='review_results.csv',
                    mime='text/csv'
                )
            else:
                st.warning("No results found. Please upload files and run the model to see the results.")
        
    with col2:
        # --- Lottie Animation ---
        with open(LOTTIE_PATH, "r") as f:
            lottie_data = json.load(f)
        st_lottie(lottie_data, speed=1, height=200, key="robot_animation", loop=True, quality="high")
    
    with st.container(border=True):
        st.subheader("PRISMA Flowchart")    

        review_counts = {
            "total_imported": 2000,
            "duplicates_removed": 300,
            "title_abstract_screened": 1700,
            "excluded_title_abstract": {
                "not_relevant": 1200,
                "wrong_population": 100,
                "no_outcome": 50,
            },
            "full_text_assessed": 350,
            "excluded_full_text": {
                "not_relevant": 100,
                "wrong_population": 50,
                "no_outcome": 50,
            },
            "included_in_review": 150
        }

        flowchart = PRISMAFlowchart(review_counts)
        png_bytes = flowchart.get_png_bytes()
        st.image(png_bytes)
        st.download_button("Download PRISMA Flowchart", png_bytes, "prisma_flowchart.png", "image/png")

    col1, col2, _ = st.columns([1.5, 1.5, 5])
    with col1:
        if st.button("Previous Page", key="previous_page_criteria"):
            st.switch_page("pages/criteria.py")

if __name__ == "__main__":
    main()