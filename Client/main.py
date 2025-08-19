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

from database import SessionLocal, ClientDB, create_db_and_tables, generate_unique_keys

load_dotenv()

st.set_page_config(page_title="Smriti | Client Portal", page_icon=":key:", layout="centered")
st.title("Smriti :) Client Portal")

def get_bucket_name() -> str:
    return (
        st.secrets.aws.s3_bucket_name
    )

def new_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=st.secrets["aws"]["access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
        region_name=st.secrets["aws"]["s3_region"],
    )

BUCKET = get_bucket_name()
if not BUCKET:
    st.stop()

create_db_and_tables()

def send_welcome_email(recipient_email: str, client_passkey: str, user_passkey: str) -> None:
    try:
        sender_email = st.secrets["email"]["senders_email"]
        brevo_api_key = st.secrets["email"]["brevo_api_key"]
    except KeyError:
        st.warning("Email services not fully configured; welcome email was not sent.")
        return

    if not sender_email or not brevo_api_key:
        st.warning("Email services not fully configured; welcome email was not sent.")
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
          <li>Client Passkey (for uploads): <code>{client_passkey}</code></li>
          <li>User Passkey (share with guests): <code>{user_passkey}</code></li>
      </ul>
      <p>We're excited to be a part of your celebration!</p>
      <p>The Smriti Team</p>
    </body></html>
    """
    payload = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email}],
        html_content=html_content,
        sender={"name": "Smriti", "email": sender_email},
        subject=subject,
    )

    try:
        api.send_transac_email(payload)
        st.success("Onboarding email with your new keys has been sent!")
    except ApiException as e:
        st.error(f"Error sending email: {getattr(e, 'reason', str(e))}")


def ensure_s3_prefix_exists(s3_client, bucket: str, prefix: str) -> None:
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    try:
        s3_client.put_object(Bucket=bucket, Key=prefix)
    except (NoCredentialsError, ClientError) as e:
        raise RuntimeError(f"Failed to create S3 folder prefix '{prefix}': {e}")

def guess_content_type(filename: str, streamlit_file) -> str:
    ct = getattr(streamlit_file, "type", None)
    if ct:
        return ct

    ext = os.path.splitext(filename)[1].lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".dng": "image/dng",
        ".nef": "image/x-nikon-nef",
        ".cr2": "image/x-canon-cr2",
        ".raw": "application/octet-stream",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".webp": "image/webp",
    }
    return mapping.get(ext, "application/octet-stream")

def upload_via_presigned_post(s3_client, bucket: str, key: str, file_name: str, file_bytes: bytes, content_type: str) -> requests.Response:
    presigned = s3_client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}],
        ExpiresIn=3600,
    )

    files = {"file": (file_name, file_bytes, content_type)}
    resp = requests.post(presigned["url"], data=presigned["fields"], files=files, timeout=120)
    return resp

if "client_email" not in st.session_state:
    st.session_state.client_email = ""
if "client_verified" not in st.session_state:
    st.session_state.client_verified = False
if "current_client" not in st.session_state:
    st.session_state.current_client = None

with SessionLocal() as db:
    if not st.session_state.client_email:
        st.header("Onboarding & Login")
        email_input = st.text_input("Please enter your email address to begin:", placeholder="you@example.com")

        if st.button("Continue", type="primary"):
            if not email_input:
                st.warning("Please enter an email address.")
                st.stop()

            client = db.query(ClientDB).filter(ClientDB.email == email_input).first()
            s3_client = new_s3_client()

            if client:
                st.session_state.current_client = client
                st.info("Welcome back! Please enter your Client Passkey to continue.")
            else:
                with st.spinner("Setting up your new account..."):
                    client_key, user_key, s3_folder, rekog_collection = generate_unique_keys()
                    new_client = ClientDB(
                        email=email_input,
                        client_passkey=client_key,
                        user_passkey=user_key,
                        s3_folder_path=s3_folder,
                        rekognition_collection_id=rekog_collection,
                    )
                    db.add(new_client)
                    db.commit()
                    db.refresh(new_client)

                    try:
                        ensure_s3_prefix_exists(s3_client, BUCKET, new_client.s3_folder_path)
                    except RuntimeError as e:
                        st.error(str(e))
                        st.stop()

                    st.session_state.current_client = new_client
                    send_welcome_email(email_input, client_key, user_key)

            st.session_state.client_email = email_input
            st.rerun()

    elif st.session_state.client_email and not st.session_state.client_verified:
        st.header("Verification Required")
        passkey_input = st.text_input("Enter your Client Passkey:", type="password")

        if st.button("Verify & Upload", type="primary"):
            client = st.session_state.current_client
            if not client:
                st.error("Session error: missing client. Please restart.")
                st.session_state.client_email = ""
                st.rerun()

            if passkey_input.strip() == (client.client_passkey or "").strip():
                st.session_state.client_verified = True
                st.rerun()
            else:
                st.error("The Client Passkey you entered is incorrect.")

    if st.session_state.client_verified:
        client = st.session_state.current_client
        if not client:
            st.error("Session error: missing client. Please restart.")
            st.session_state.client_email = ""
            st.session_state.client_verified = False
            st.rerun()

        s3_client = new_s3_client()
        prefix = client.s3_folder_path

        st.header(f"Upload Photos for {client.email}")
        st.info(f"These photos will be available for guests with the User Passkey: **{client.user_passkey}**")

        try:
            ensure_s3_prefix_exists(s3_client, BUCKET, prefix)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        uploaded_files = st.file_uploader(
            "Choose photos to upload",
            type=["jpg", "jpeg", "png", "heic", "raw", "cr2", "dng", "nef", "tif", "tiff", "webp"],
            accept_multiple_files=True,
        )

        if st.button("Upload Photos", type="primary", use_container_width=True):
            if not uploaded_files:
                st.warning("Please select files to upload first.")
            else:
                success = 0
                failed = 0
                progress = st.progress(0, text="Preparing uploads...")

                total = len(uploaded_files)
                for i, up in enumerate(uploaded_files, start=1):
                    filename = up.name
                    s3_key = f"{prefix}/{filename}"

                    try:
                        s3_client.head_object(Bucket=BUCKET, Key=s3_key)
                        root, ext = os.path.splitext(filename)
                        unique_name = f"{root}-{int(time.time())}-{uuid.uuid4().hex[:6]}{ext}"
                        s3_key = f"{prefix}/{unique_name}"
                        display_name = unique_name
                    except ClientError:
                        display_name = filename

                    content_type = guess_content_type(filename, up)

                    try:
                        file_bytes = up.read()
                        up.seek(0)

                        with st.spinner(f"Uploading {display_name}..."):
                            resp = upload_via_presigned_post(
                                s3_client, BUCKET, s3_key, display_name, file_bytes, content_type
                            )

                        if resp.status_code in (200, 204):
                            success += 1
                        else:
                            failed += 1
                            st.error(f"Upload failed for {display_name} (HTTP {resp.status_code}).")

                    except Exception as e:
                        failed += 1
                        st.error(f"Error uploading {display_name}: {e}")

                    progress.progress(i / total, text=f"Uploaded {i}/{total}: {display_name}")

                progress.empty()
                if success:
                    st.success(f"Upload complete! {success} photo(s) uploaded successfully.")
                if failed:
                    st.error(f"{failed} photo(s) failed to upload. Check file types and try again.")