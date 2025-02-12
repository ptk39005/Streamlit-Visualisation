import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from firebase_admin import storage
import pandas as pd
from datetime import datetime
import json
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin.exceptions import FirebaseError
import time
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Visualization Creator", layout="wide")


def initialize_firebase():
    """Initialize Firebase if not already initialized"""
    if not firebase_admin._apps:
        try:
            service_account = {
                "type": st.secrets["firebase_service_account"]["type"],
                "project_id": st.secrets["firebase_service_account"]["project_id"],
                "private_key_id": st.secrets["firebase_service_account"]["private_key_id"],
                "private_key": st.secrets["firebase_service_account"]["private_key"],
                "client_email": st.secrets["firebase_service_account"]["client_email"],
                "client_id": st.secrets["firebase_service_account"]["client_id"],
                "auth_uri": st.secrets["firebase_service_account"]["auth_uri"],
                "token_uri": st.secrets["firebase_service_account"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["firebase_service_account"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["firebase_service_account"]["client_x509_cert_url"]
            }
            cred = credentials.Certificate(service_account)
            firebase_admin.initialize_app(cred, {
    'storageBucket': 'file-processing-app.firebasestorage.app'  # ✅ Correct
})


            # Explicitly initialize session state variables
            st.session_state.db = firestore.client()
            st.session_state.storage_bucket = storage.bucket()

            st.session_state.firebase_initialized = True  # Set only if initialization succeeds
            logger.info("Firebase initialized successfully.")
            return True
        
        except ValueError as ve:
            st.error(f"Value error during Firebase initialization: {str(ve)}")
            logger.error(f"ValueError: {str(ve)}")
            return False
        except FirebaseError as fe:
            st.error(f"Firebase error during initialization: {str(fe)}")
            logger.error(f"FirebaseError: {str(fe)}")
            return False
        except KeyError as ke:
            st.error(f"Missing Firebase configuration key: {str(ke)}")
            logger.error(f"KeyError: {str(ke)}")
            return False
        except Exception as e:
            st.error(f"Unexpected error during Firebase initialization: {str(e)}")
            logger.exception("Unexpected error")
            return False
    
    # Ensure storage bucket is set even if Firebase is already initialized
    if 'storage_bucket' not in st.session_state:
        try:
            st.session_state.storage_bucket = storage.bucket()
            logger.info("Storage bucket accessed successfully.")
        except FirebaseError as fe:
            st.error(f"Firebase error accessing storage bucket: {str(fe)}")
            logger.error(f"FirebaseError: {str(fe)}")
        except Exception as e:
            st.error(f"Unexpected error accessing storage bucket: {str(e)}")
            logger.exception("Unexpected error")
    
    return True


def get_firestore_client():
    """Get Firestore client from session state"""
    if 'db' not in st.session_state:
        initialize_firebase()
    return st.session_state.db

def get_storage_bucket():
    """Ensure Firebase is initialized before accessing storage bucket"""
    if 'storage_bucket' not in st.session_state or st.session_state.storage_bucket is None:
        st.warning("Storage bucket is missing or not initialized. Attempting to reinitialize Firebase...")
        if not initialize_firebase():  # Try to reinitialize Firebase
            st.error("Firebase initialization failed. Cannot access storage bucket.")
            logger.error("Failed to initialize Firebase when accessing storage bucket.")
            return None  # Prevent further errors

    try:
        bucket = st.session_state.storage_bucket
        if not bucket:
            raise FirebaseError("Storage bucket is not set in session state.")
        
        # 🔥 Removing `bucket.reload()`, as it's unnecessary and might cause API errors
        logger.info("Storage bucket accessed successfully.")
        return bucket

    except FirebaseError as fe:
        st.error(f"Firebase error accessing storage bucket: {str(fe)}")
        logger.error(f"FirebaseError: {str(fe)}")
        return None
    except Exception as e:
        st.error(f"Unexpected error accessing storage bucket: {str(e)}")
        logger.exception("Unexpected error")
        return None

class VisualizationSession:
    def __init__(self, user_email):
        self.user_email = user_email
        self.init_session_state()
        
    def init_session_state(self):
        """Initialize session state variables"""
        if 'line_bar_series' not in st.session_state:
            st.session_state.line_bar_series = []
        if 'horizontal_bar_series' not in st.session_state:
            st.session_state.horizontal_bar_series = []
        if 'current_visualization' not in st.session_state:
            st.session_state.current_visualization = None
        if 'selected_columns' not in st.session_state:
            st.session_state.selected_columns = {}
            
    def load_data(self, file_name, sheet_name=None):
        """Load data from Firebase Storage"""
        bucket = get_storage_bucket()
        blob_path = f"users/{self.user_email}/data/{file_name}"
        blob = bucket.blob(blob_path)
        
        # Download to temporary file
        local_path = f"/tmp/{file_name}"
        blob.download_to_filename(local_path)
        
        if file_name.endswith('.csv'):
            return pd.read_csv(local_path)
        elif file_name.endswith(('.xlsx', '.xls')):
            return pd.read_excel(local_path, sheet_name=sheet_name)
        else:
            raise ValueError("Unsupported file format")

    def save_visualization(self, config):
        """Save visualization config to Firebase"""
        bucket = get_storage_bucket()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_path = f"users/{self.user_email}/visualizations/viz_{timestamp}.json"
        blob = bucket.blob(blob_path)
        
        blob.upload_from_string(
            json.dumps(config),
            content_type='application/json'
        )
        return blob_path

    def render_visualization_interface(self, df):
        """Render the visualization interface"""
        st.header("Visualization")

        # Select File
        file_options = list(st.session_state.selected_columns.keys())
        selected_file = st.selectbox("Select File", file_options)
        
        if not selected_file:
            return

        # Step 1: Select Visualization Type
        visualization_type = st.radio(
            "Select the type of visualization",
            [
                "Line / Vertical Bars / Stacked Vertical Bars / Combination",
                "Horizontal Bars / Stacked Horizontal Bars",
                "Donut / Pie"
            ]
        )

        if visualization_type == "Line / Vertical Bars / Stacked Vertical Bars / Combination":
            self.render_line_bar_interface(df, selected_file)
        elif visualization_type == "Horizontal Bars / Stacked Horizontal Bars":
            self.render_horizontal_bar_interface(df, selected_file)
        elif visualization_type == "Donut / Pie":
            self.render_pie_donut_interface(df, selected_file)

    def render_line_bar_interface(self, df, selected_file):
        st.subheader("Line / Vertical Bars / Stacked Vertical Bars / Combination")

        # Chart Title
        chart_title = st.text_input("Enter Chart Title")

        # X Axis Selection
        x_axis = st.selectbox("Select X Axis", st.session_state.selected_columns[selected_file]["columns"])

        # Display existing series
        for idx, series in enumerate(st.session_state.line_bar_series):
            col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
            series["column"] = col1.selectbox(
                f"Series {idx + 1}",
                st.session_state.selected_columns[selected_file]["columns"],
                key=f"line_bar_series_column_{idx}"
            )
            series["type"] = col2.selectbox(
                "Visualization Type",
                ["Line", "Bar"],
                key=f"line_bar_series_type_{idx}"
            )
            series["axis"] = col3.selectbox(
                "Axis",
                ["Left", "Right"],
                key=f"line_bar_series_axis_{idx}"
            )
            series["color"] = col4.text_input(
                "Colour (Hex Code)",
                key=f"line_bar_series_color_{idx}"
            )

        # Add Series Button
        if st.button("Add Series", key="add_line_bar"):
            st.session_state.line_bar_series.append({
                "column": None,
                "type": "Line",
                "axis": "Left",
                "color": "#000000"
            })

        # Bar Type Selection
        bar_type = None
        if any(series["type"] == "Bar" for series in st.session_state.line_bar_series):
            bar_type = st.radio(
                "Bar Type",
                ["Stacked Bars", "Side-by-Side Bars"]
            )

        # Preview Chart
        if st.session_state.line_bar_series:
            self.preview_line_bar_chart(df, x_axis, chart_title, bar_type)

    def render_horizontal_bar_interface(self, df, selected_file):
        st.subheader("Horizontal Bars / Stacked Horizontal Bars")

        # Chart Title
        chart_title = st.text_input("Enter Chart Title")

        # X Axis Selection
        x_axis = st.selectbox("Select X Axis", st.session_state.selected_columns[selected_file]["columns"])

        # Display existing series
        for idx, series in enumerate(st.session_state.horizontal_bar_series):
            col1, col2 = st.columns([2, 2])
            series["column"] = col1.selectbox(
                f"Series {idx + 1}",
                st.session_state.selected_columns[selected_file]["columns"],
                key=f"horizontal_bar_series_column_{idx}"
            )
            series["color"] = col2.text_input(
                "Colour (Hex Code)",
                key=f"horizontal_bar_series_color_{idx}"
            )

        # Add Series Button
        if st.button("Add Series", key="add_horizontal_bar"):
            st.session_state.horizontal_bar_series.append({
                "column": None,
                "color": "#000000"
            })

        # Bar Type Selection
        bar_type = None
        if len(st.session_state.horizontal_bar_series) > 1:
            bar_type = st.radio(
                "Bar Type",
                ["Stacked Bars", "Side-by-Side Bars"]
            )

        # Preview Chart
        if st.session_state.horizontal_bar_series:
            self.preview_horizontal_bar_chart(df, x_axis, chart_title, bar_type)

    def render_pie_donut_interface(self, df, selected_file):
        st.subheader("Donut / Pie")

        # Chart Type
        chart_type = st.radio("Select Chart Type", ["Donut", "Pie"])

        # Chart Title
        chart_title = st.text_input("Enter Chart Title")

        # Labels and Values
        labels = st.selectbox("Select Labels", st.session_state.selected_columns[selected_file]["columns"])
        values = st.selectbox(
            "Select Values",
            [col for col in st.session_state.selected_columns[selected_file]["columns"] if col != labels]
        )

        # Number of Largest Items
        largest_items = st.number_input(
            "Enter number of largest items to show (Optional)",
            min_value=1,
            step=1
        )

        # Colour Theme
        colour_theme = st.selectbox(
            "Select Colour Theme",
            ["Blue-Grey", "Yellow-Green", "Red-Orange"]
        )

        # Preview Chart
        if labels and values:
            self.preview_pie_donut_chart(df, labels, values, chart_title, chart_type, largest_items, colour_theme)

    def preview_line_bar_chart(self, df, x_axis, title, bar_type):
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        for series in st.session_state.line_bar_series:
            if series["type"] == "Line":
                fig.add_trace(
                    go.Scatter(
                        x=df[x_axis],
                        y=df[series["column"]],
                        name=series["column"],
                        line=dict(color=series["color"])
                    ),
                    secondary_y=(series["axis"] == "Right")
                )
            else:
                fig.add_trace(
                    go.Bar(
                        x=df[x_axis],
                        y=df[series["column"]],
                        name=series["column"],
                        marker_color=series["color"]
                    ),
                    secondary_y=(series["axis"] == "Right")
                )

        if bar_type == "Stacked Bars":
            fig.update_layout(barmode='stack')
        
        fig.update_layout(title=title)
        st.plotly_chart(fig, use_container_width=True)

    def preview_horizontal_bar_chart(self, df, x_axis, title, bar_type):
        fig = go.Figure()
        
        for series in st.session_state.horizontal_bar_series:
            fig.add_trace(
                go.Bar(
                    y=df[x_axis],
                    x=df[series["column"]],
                    name=series["column"],
                    marker_color=series["color"],
                    orientation='h'
                )
            )

        if bar_type == "Stacked Bars":
            fig.update_layout(barmode='stack')
        
        fig.update_layout(title=title)
        st.plotly_chart(fig, use_container_width=True)

    def preview_pie_donut_chart(self, df, labels, values, title, chart_type, largest_items, colour_theme):
        df_grouped = df.groupby(labels)[values].sum().reset_index()
        
        if largest_items:
            df_grouped = df_grouped.nlargest(largest_items, values)
            
        fig = go.Figure(data=[
            go.Pie(
                labels=df_grouped[labels],
                values=df_grouped[values],
                hole=0.4 if chart_type == "Donut" else 0
            )
        ])
        
        fig.update_layout(title=title)
        st.plotly_chart(fig, use_container_width=True)

    def render_preview(self, df, config):
        """Render just the visualization based on config"""
        visualization_type = config.get('type')
        
        if visualization_type == "Line / Vertical Bars / Stacked Vertical Bars / Combination":
            x_axis = config.get('xAxis')
            chart_title = config.get('title', '')
            bar_type = config.get('barType')
            series = config.get('series', [])
            
            # Set the series in session state for preview
            st.session_state.line_bar_series = series
            
            # Preview the chart
            self.preview_line_bar_chart(df, x_axis, chart_title, bar_type)
            
        elif visualization_type == "Horizontal Bars / Stacked Horizontal Bars":
            x_axis = config.get('xAxis')
            chart_title = config.get('title', '')
            bar_type = config.get('barType')
            series = config.get('series', [])
            
            # Set the series in session state for preview
            st.session_state.horizontal_bar_series = series
            
            # Preview the chart
            self.preview_horizontal_bar_chart(df, x_axis, chart_title, bar_type)
            
        elif visualization_type == "Donut / Pie":
            labels = config.get('labels')
            values = config.get('values')
            chart_title = config.get('title', '')
            chart_type = config.get('chartType')
            largest_items = config.get('largestItems')
            colour_theme = config.get('colorTheme')
            
            # Preview the chart
            self.preview_pie_donut_chart(
                df, labels, values, chart_title, 
                chart_type, largest_items, colour_theme
            )

def get_available_files(user_email):
    """List available files for the user from Firebase Storage"""
    bucket = get_storage_bucket()
    if not bucket:
        logger.warning("Storage bucket is not available. Cannot list files.")
        return []
    
    try:
        files = []
        # Corrected prefix to target user-specific data
        blobs = bucket.list_blobs(prefix=f"users/{user_email}/data/")
        for blob in blobs:
            # Extract just the filename from the full path
            filename = blob.name.split('/')[-1]
            if filename:  # Ensure we don't add empty strings
                files.append(filename)
        
        logger.info(f"Retrieved {len(files)} files for user {user_email}.")
        return files
    except FirebaseError as fe:
        st.error(f"Firebase error while listing files: {str(fe)}")
        logger.error(f"FirebaseError: {str(fe)}")
        return []
    except Exception as e:
        st.error(f"Unexpected error while listing files: {str(e)}")
        logger.exception("Unexpected error")
        return []

def main():
    # Set page config as the first command
    # Get parameters from URL
    query_params = st.query_params
    
    # Get and validate session_id
    session_id = query_params.get("session_id")
    if isinstance(session_id, list):
        session_id = session_id[0]
    
    # Get and validate mode
    mode = query_params.get("mode", "full")
    if isinstance(mode, list):
        mode = mode[0]
    
    # Get and validate email
    email = query_params.get("email")
    if isinstance(email, list):
        email = email[0]

    logger.info(f"Session ID: {session_id}")
    logger.info(f"Mode: {mode}")
    logger.info(f"Email: {email}")


    if not session_id:
        st.error("No session ID provided. Please provide a valid session ID in the URL.")
        logger.error("Session ID is missing from query parameters.")
        return
    
    try:
        # Initialize Firebase
        if not initialize_firebase():
            st.error("Failed to initialize Firebase. Please check your configuration.")
            logger.critical("Firebase initialization failed in main function.")
            return

        # Load session data based on mode
        bucket = get_storage_bucket()
        if not bucket:
            st.error("Cannot access storage bucket. Please verify your Firebase configuration.")
            logger.critical("Storage bucket is inaccessible in main function.")
            return    
        
        logger.info(bucket)
        blobs = bucket.list_blobs()
        logger.info(blobs)
        logging.info("Listing all files in Firebase Storage bucket:")

        file_count = 0
        for blob in blobs:
            logging.info(blob.name)
            file_count += 1

        logging.info(f"Total files: {file_count}")
        # For preview sessions, poll for configuration
        if session_id.startswith('preview_'):
            config_blob = bucket.blob(f"streamlit_sessions/{session_id}/config.json")
            logger.info(f"streamlit_sessions/{session_id}/config.json")
            start_time = time.time()
            config_found = False
            
            with st.spinner('Waiting for configuration...'):
                while time.time() - start_time < 15:  # Poll for 15 seconds
                    if config_blob.exists():
                        config_found = True
                        session_data = json.loads(config_blob.download_as_string())
                        logger.info("Configuration found for preview session.")
                        break
                    time.sleep(1)  # Wait 1 second before next check
            
            if not config_found:
                st.error("Configuration not found after 15 seconds. Please try again.")
                logger.warning("Configuration not found within timeout period.")
                return
        else:
            # For non-preview sessions, load existing config
            config_blob = bucket.blob(f"streamlit_sessions/{session_id}/config.json")
            if not config_blob.exists():
                st.error(f"Configuration file not found for session: {session_id}")
                logger.error(f"Configuration file does not exist for session: {session_id}")
                return
            session_data = json.loads(config_blob.download_as_string())
            logger.info("Configuration loaded for full session.")

        # Initialize visualization session with email from query params if available
        viz_session = VisualizationSession(email or session_data.get("email"))
        
        # Placeholder for DataFrame (Assuming 'df' is loaded elsewhere; handle if not)
        df = pd.DataFrame()  # Update this as per your actual data loading mechanism
        if df.empty:
            st.warning("DataFrame is empty. Please ensure data is loaded correctly.")
            logger.warning("DataFrame is empty in main function.")
        
        if mode == "preview":
            # For preview, just render the visualization based on config
            viz_session.render_preview(df, session_data.get("visualizationConfig", {}))
        else:
            # For full mode, render the full interface
            viz_session.render_visualization_interface(df)
            
    except FirebaseError as fe:
        st.error(f"Firebase error in main function: {str(fe)}")
        logger.error(f"FirebaseError: {str(fe)}")
    except json.JSONDecodeError as je:
        st.error(f"Error decoding JSON configuration: {str(je)}")
        logger.error(f"JSONDecodeError: {str(je)}")
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
        logger.exception("Unexpected error in main function")

if __name__ == "__main__":
    main() 