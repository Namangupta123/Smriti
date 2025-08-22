import os
import time
import uuid
import requests
import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

# This will require a new PhotosDB table in your database file
from database import SessionLocal, ClientDB, PhotosDB, create_db_and_tables, generate_unique_keys

# --- Initial Configuration ---
load_dotenv()
st.set_page_config(page_title="Smriti | Client Portal", page_icon="🔑", layout="centered")
st.title("Smriti :) Client Portal")

# --- Function Definitions ---

@st.cache_resource
def get_s3_client():
    """Initializes and caches the S3 client."""
    try:
        return boto3.client(
            "s3",
            aws_access_key_id=st.secrets["aws"]["access_key_id"],
            aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
            region_name=st.secrets["aws"]["s3_region"],
        )
    except (KeyError, NoCredentialsError):
        st.error("S3 credentials not found. Please contact the administrator.")
        return None

def send_welcome_email(recipient_email: str, client_passkey: str, user_passkey: str) -> None:
    """Sends the onboarding email using Brevo."""
    try:
        sender_email = st.secrets["email"]["senders_email"]
        brevo_api_key = st.secrets["email"]["brevo_api_key"]
    except KeyError:
        st.warning("Email services are not fully configured; the welcome email was not sent.")
        return

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_api_key
    api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    subject = "Welcome to Smriti! Your Access Keys are Here"
    html_content = f"""
    <html><body>
      <p>Hi there,</p>
      <p>Thank you for choosing Smriti to find your precious moments!</p>
      <p>Here are your unique keys for your event:</p>
      <ul>
          <li>To upload photos to this portal, please use this <strong>Client Passkey:</strong> <code>{client_passkey}</code></li>
          <li>To share with your guests so they can find their photos, use this <strong>User Passkey:</strong> <code>{user_passkey}</code></li>
      </ul>
      <p>We're excited to be a part of your celebration!</p>
      <p>The Smriti Team</p>
    </body></html>
    """
    payload = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email}], html_content=html_content,
        sender={"name": "Smriti", "email": sender_email}, subject=subject
    )

    try:
        api.send_transac_email(payload)
        st.success("Onboarding email with your new keys has been sent!")
    except ApiException as e:
        st.error(f"Could not send welcome email. Please contact support. Error: {e.reason}")


def ensure_s3_prefix_exists(s3_client, bucket: str, prefix: str) -> None:
    """Creates an empty object to simulate a folder if it doesn't exist."""
    if not prefix.endswith("/"):
        prefix += "/"
    try:
        s3_client.put_object(Bucket=bucket, Key=prefix)
    except (NoCredentialsError, ClientError) as e:
        raise RuntimeError(f"Failed to create S3 folder for your account: {e}")

def get_unique_s3_key(s3_client, bucket: str, prefix: str, filename: str) -> str:
    """Checks if a file exists and returns a unique key if it does."""
    s3_key = f"{prefix}/{filename}"
    try:
        s3_client.head_object(Bucket=bucket, Key=s3_key)
        root, ext = os.path.splitext(filename)
        unique_id = uuid.uuid4().hex[:6]
        new_filename = f"{root}-{unique_id}{ext}"
        return f"{prefix}/{new_filename}"
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return s3_key
        else:
            raise
    return s3_key

def upload_file(s3_client, bucket: str, s3_key: str, uploaded_file) -> requests.Response:
    """Generates a presigned URL and uploads a file directly to S3."""
    content_type = uploaded_file.type or "application/octet-stream"
    presigned_post = s3_client.generate_presigned_post(
        Bucket=bucket, Key=s3_key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}],
        ExpiresIn=3600
    )
    files = {'file': (s3_key, uploaded_file, content_type)}
    return requests.post(presigned_post['url'], data=presigned_post['fields'], files=files, timeout=120)

@st.cache_data(ttl=600)
def list_all_s3_photos(_s3_client, bucket: str, folder: str):
    """Lists all image files in a specific S3 folder. Caches for 10 minutes."""
    paginator = _s3_client.get_paginator('list_objects_v2')
    s3_keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=folder):
        if "Contents" in page:
            for obj in page["Contents"]:
                key = obj["Key"]
                if key.lower().endswith(('png', 'jpg', 'jpeg')):
                    s3_keys.append(key)
    return s3_keys

def toggle_highlight_status(db_session: Session, client_id: int, s3_key: str):
    """Finds a photo in the DB or creates it, then toggles its highlight status."""
    photo = db_session.query(PhotosDB).filter_by(client_id=client_id, s3_key=s3_key).first()
    if photo:
        photo.is_highlighted = not photo.is_highlighted
    else:
        photo = PhotosDB(client_id=client_id, s3_key=s3_key, is_highlighted=True)
        db_session.add(photo)
    db_session.commit()
    # Clear the cache to force a refresh of the photo list
    st.cache_data.clear()


# --- Application State and Initialization ---
if "auth_step" not in st.session_state:
    st.session_state.auth_step = "email_input"
if "current_client" not in st.session_state:
    st.session_state.current_client = None

create_db_and_tables()
db: Session = SessionLocal()

# --- Authentication Flow ---

if st.session_state.auth_step == "email_input":
    st.header("Onboarding & Login")
    email_input = st.text_input("Please enter your email address to begin:", placeholder="you@example.com")
    if st.button("Continue", type="primary"):
        # ... (rest of the email input logic is unchanged) ...
        if not email_input:
            st.warning("Please enter an email address.")
        else:
            client = db.query(ClientDB).filter(ClientDB.email == email_input).first()
            if client:
                st.session_state.current_client = client
                st.session_state.auth_step = "passkey_verification"
                st.info("Welcome back! Please enter your Client Passkey to continue.")
                st.rerun()
            else:
                with st.spinner("Setting up your new account..."):
                    s3_client = get_s3_client()
                    if not s3_client: st.stop()
                    
                    client_key, user_key, s3_folder, rekog_collection = generate_unique_keys()
                    new_client = ClientDB(
                        email=email_input, client_passkey=client_key, user_passkey=user_key,
                        s3_folder_path=s3_folder, rekognition_collection_id=rekog_collection
                    )
                    
                    try:
                        ensure_s3_prefix_exists(s3_client, st.secrets["aws"]["s3_bucket_name"], new_client.s3_folder_path)
                        db.add(new_client)
                        db.commit()
                        db.refresh(new_client)
                        st.session_state.current_client = new_client
                        st.session_state.auth_step = "passkey_verification"
                        send_welcome_email(email_input, client_key, user_key)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))
                        db.rollback()

elif st.session_state.auth_step == "passkey_verification":
    st.header("Verification Required")
    client = st.session_state.current_client
    st.caption(f"Verifying account for: {client.email}")
    passkey_input = st.text_input("Enter your Client Passkey:", type="password")
    if st.button("Verify & Continue", type="primary"):
        if passkey_input.strip() == client.client_passkey.strip():
            st.session_state.auth_step = "uploader"
            st.rerun()
        else:
            st.error("The Client Passkey you entered is incorrect.")

elif st.session_state.auth_step == "uploader":
    client = st.session_state.current_client
    s3_client = get_s3_client()
    S3_BUCKET = st.secrets["aws"]["s3_bucket_name"]

    st.header(f"Manage Event for {client.email}")
    st.info(f"Guest User Passkey: **{client.user_passkey}**")

    tab1, tab2 = st.tabs(["📤 Upload Photos", "✨ Manage Highlights"])

    with tab1:
        st.subheader("Upload New Photos")
        uploaded_files = st.file_uploader(
            "Choose photos to upload",
            type=["jpg", "jpeg", "png", "heic", "raw", "cr2", "dng", "nef", "tif", "tiff", "webp"],
            accept_multiple_files=True,
            key="file_uploader"
        )
        if st.button("Upload Photos", type="primary", use_container_width=True, disabled=(not uploaded_files)):
            # ... (rest of the upload logic is unchanged) ...
            success_count = 0
            error_count = 0
            progress_bar = st.progress(0, text="Preparing uploads...")

            for i, uploaded_file in enumerate(uploaded_files, 1):
                try:
                    s3_key = get_unique_s3_key(s3_client, S3_BUCKET, client.s3_folder_path, uploaded_file.name)
                    with st.spinner(f"Uploading {os.path.basename(s3_key)}..."):
                        response = upload_file(s3_client, S3_BUCKET, s3_key, uploaded_file)
                    if response.status_code in [200, 204]:
                        success_count += 1
                    else:
                        st.error(f"Upload failed for {os.path.basename(s3_key)} (HTTP {response.status_code}).")
                        error_count += 1
                except Exception as e:
                    st.error(f"An error occurred with {uploaded_file.name}: {e}")
                    error_count += 1
                progress_bar.progress(i / len(uploaded_files), text=f"Processed {i}/{len(uploaded_files)} files")

            progress_bar.empty()
            if success_count > 0:
                st.success(f"✅ Upload complete! {success_count} photos uploaded successfully.")
            if error_count > 0:
                st.error(f"❌ {error_count} photos failed to upload.")


    with tab2:
        st.subheader("Select Photos for Guest Slideshow")
        all_photos = list_all_s3_photos(s3_client, S3_BUCKET, client.s3_folder_path)
        
        if not all_photos:
            st.info("You haven't uploaded any photos yet. Upload photos in the tab above to manage them here.")
        else:
            # Fetch all highlight statuses in one go for efficiency
            highlighted_photos_q = db.query(PhotosDB.s3_key).filter_by(client_id=client.id, is_highlighted=True).all()
            highlighted_s3_keys = {p.s3_key for p in highlighted_photos_q}

            cols = st.columns(4)
            for i, s3_key in enumerate(all_photos):
                with cols[i % 4]:
                    is_highlighted = s3_key in highlighted_s3_keys
                    
                    url = s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': s3_key}, ExpiresIn=3600)
                    st.image(url, use_container_width=True)

                    button_label = "🌟 Un-highlight" if is_highlighted else "✨ Highlight"
                    button_type = "primary" if is_highlighted else "secondary"

                    st.button(
                        button_label, 
                        key=s3_key, 
                        on_click=toggle_highlight_status, 
                        args=(db, client.id, s3_key),
                        use_container_width=True,
                        type=button_type
                    )

db.close()
