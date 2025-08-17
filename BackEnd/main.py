import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import os
from dotenv import load_dotenv
import requests

load_dotenv()

st.set_page_config(
    page_title="Smriti :) Find your moments",
    page_icon=":camera:",
    layout="centered"
)

def check_password():
    """Returns `True` if the user entered the correct password."""
    if "password_correct" not in st.session_state:
        st.header("Client Portal Login")
        password = st.text_input("Enter password", type="password")
        if st.button("Login"):
            correct_password = os.getenv("PORTAL_PASSWORD")
            if not correct_password:
                st.error("Password not configured. Please contact the administrator.")
            elif password == correct_password:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("The password you entered is incorrect.")
    return st.session_state.get("password_correct", False)

st.title("Smriti :) Find your moments")

if not check_password():
    st.stop()

try:
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    S3_REGION = os.getenv("S3_REGION")
    S3_WEDDING_PHOTOS_FOLDER = os.getenv("S3_WEDDING_PHOTOS_FOLDER")

    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION, S3_WEDDING_PHOTOS_FOLDER]):
        raise KeyError("Error in storage configuration contact administrator (404 Not Found)")

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )
except (KeyError, NoCredentialsError) as e:
    st.error(f"AWS credentials not configured properly: {e}")
    s3_client = None

if s3_client:
    st.header("Upload Photos")
    st.info("These photos will be available for users to search through in the User Portal.")

    uploaded_files = st.file_uploader(
        "Choose photos to upload",
        type=['jpg', 'jpeg', 'png', 'HEIC', 'raw', 'cr2', 'dng', 'nef'],
        accept_multiple_files=True
    )

    if st.button("Upload Photos", type="primary", use_container_width=True):
        if not uploaded_files:
            st.warning("Please select files to upload first.")
        else:
            success_count = 0
            error_count = 0
            progress_bar = st.progress(0, text="Preparing uploads...")

            for i, uploaded_file in enumerate(uploaded_files):
                s3_key = f"{S3_WEDDING_PHOTOS_FOLDER}/{uploaded_file.name}"
                
                try:
                    presigned_post = s3_client.generate_presigned_post(
                        Bucket=S3_BUCKET_NAME,
                        Key=s3_key,
                        Fields={"Content-Type": uploaded_file.type},
                        Conditions=[{"Content-Type": uploaded_file.type}],
                        ExpiresIn=6200
                    )

                    files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                    
                    with st.spinner(f"Uploading {uploaded_file.name}..."):
                        response = requests.post(
                            presigned_post['url'], 
                            data=presigned_post['fields'], 
                            files=files
                        )

                    if response.status_code in [200, 204]:
                        success_count += 1
                    else:
                        st.error(f"Error uploading {uploaded_file.name} contact administrator: {response.status_code}")
                        error_count += 1
                
                except ClientError as e:
                    st.error(f"Error uploading {uploaded_file.name} contact administrator: {e}")
                    error_count += 1
                except Exception as e:
                    st.error(f"Error uploading {uploaded_file.name} contact administrator: {e}")
                    error_count += 1
                
                progress_text = f"Uploaded {i+1}/{len(uploaded_files)}: {uploaded_file.name}"
                progress_bar.progress((i + 1) / len(uploaded_files), text=progress_text)

            progress_bar.empty()
            st.success(f"Upload complete! {success_count} photos uploaded successfully.")
            if error_count > 0:
                st.error(f"{error_count} photos failed to upload. Please contact administrator.")
