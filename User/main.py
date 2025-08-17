import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError
import face_recognition
import os
import io
import zipfile
from dotenv import load_dotenv

load_dotenv()
# --- Page Configuration ---
st.set_page_config(
    page_title="Smriti - Wedding Photo Sorter",
    page_icon="📸",
    layout="wide"
)

# --- AWS S3 Configuration ---
try:
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    S3_REGION = os.getenv("S3_REGION")
    S3_WEDDING_PHOTOS_FOLDER = os.getenv("S3_WEDDING_PHOTOS_FOLDER")

    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )
except (KeyError, NoCredentialsError):
    st.error("AWS credentials, bucket name, or folder not found. Please configure your Streamlit secrets.")
    s3_client = None

# --- Helper Functions ---

def list_all_s3_photos(bucket, folder):
    """Lists all image files in a specific S3 folder."""
    paginator = s3_client.get_paginator('list_objects_v2')
    s3_keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=folder):
        if "Contents" in page:
            for obj in page["Contents"]:
                key = obj["Key"]
                if key.lower().endswith(('png', 'jpg', 'jpeg')):
                    s3_keys.append(key)
    return s3_keys

def process_images_from_s3(selfie_encoding, s3_keys):
    """Downloads images one-by-one from S3, finds matches, and discards from memory."""
    matched_s3_keys = []
    progress_bar = st.progress(0, text="Scanning wedding photos...")
    total_images = len(s3_keys)
    if total_images == 0:
        st.warning(f"No images found in the configured S3 folder: '{S3_WEDDING_PHOTOS_FOLDER}'")
        return []
    for i, s3_key in enumerate(s3_keys):
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            image_bytes = response['Body'].read()
            current_image = face_recognition.load_image_file(io.BytesIO(image_bytes))
            current_encodings = face_recognition.face_encodings(current_image)
            if not current_encodings: continue
            matches = face_recognition.compare_faces(current_encodings, selfie_encoding, tolerance=0.6)
            if True in matches:
                matched_s3_keys.append(s3_key)
        except Exception as e:
            st.warning(f"Could not process file {os.path.basename(s3_key)}: {e}")
            continue
        progress_text = f"Analyzing photo {i+1}/{total_images}: {os.path.basename(s3_key)}"
        progress_bar.progress((i + 1) / total_images, text=progress_text)
    progress_bar.empty()
    return matched_s3_keys

# --- Main Application UI ---
st.title("📸 Smriti - Your Personal Photo Sorter")
st.markdown("Welcome! Take a clear selfie, and I'll find all your photos from the wedding collection.")

if 'matched_s3_keys' not in st.session_state:
    st.session_state.matched_s3_keys = []
if 'search_triggered' not in st.session_state:
    st.session_state.search_triggered = False

st.header("Take Your Selfie")
# --- MODIFIED LINE: Changed from st.file_uploader to st.camera_input ---
selfie_picture = st.camera_input("Center your face and take a photo to begin the search")

# --- MODIFIED LINE: Changed disabled check from selfie_file to selfie_picture ---
if st.button("✨ Find My Photos", type="primary", use_container_width=True, disabled=(not selfie_picture or not s3_client)):
    st.session_state.search_triggered = True
    with st.spinner('Analyzing... This might take a moment.'):
        try:
            # --- MODIFIED LINE: Changed variable from selfie_file to selfie_picture ---
            selfie_image = face_recognition.load_image_file(selfie_picture)
            selfie_encodings = face_recognition.face_encodings(selfie_image)
            if not selfie_encodings:
                st.error("No face could be detected in the selfie. Please try again with a clearer picture.")
                st.stop()
            selfie_encoding = selfie_encodings[0]
        except Exception as e:
            st.error(f"Error processing selfie: {e}")
            st.stop()
        
        all_photo_keys = list_all_s3_photos(S3_BUCKET_NAME, S3_WEDDING_PHOTOS_FOLDER)
        st.session_state.matched_s3_keys = process_images_from_s3(selfie_encoding, all_photo_keys)

# --- Display Results ---
if st.session_state.matched_s3_keys:
    st.header(f"Results: Found you in {len(st.session_state.matched_s3_keys)} photos!")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for s3_key in st.session_state.matched_s3_keys:
            response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            zip_file.writestr(os.path.basename(s3_key), response['Body'].read())
    st.download_button(label="⬇️ Download All Matched Photos (.zip)", data=zip_buffer.getvalue(), file_name="smriti_matched_photos.zip", mime="application/zip", use_container_width=True)
    cols = st.columns(4)
    for i, s3_key in enumerate(st.session_state.matched_s3_keys):
        with cols[i % 4]:
            try:
                url = s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_key}, ExpiresIn=3600)
                st.image(url, caption=os.path.basename(s3_key), use_column_width=True)
            except Exception as e:
                st.error(f"Could not display {os.path.basename(s3_key)}")
elif st.session_state.search_triggered:
    st.info("No matches found in the wedding photo collection.")