import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import os
import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

from database import SessionLocal, ClientDB, create_db_and_tables, generate_unique_keys

load_dotenv()

st.set_page_config(page_title="Smriti | Client Portal", page_icon="🔑", layout="centered")

def send_welcome_email(recipient_email, client_passkey, user_passkey):
    """Sends the onboarding email using Brevo."""
    sender_email = st.secrets["email"]["senders_email"]
    sender_name = "Smriti"
    brevo_api_key = st.secrets["email"]["brevo_api_key"]

    if not all([sender_email, brevo_api_key]):
        st.warning("Email services are not fully configured. The welcome email will not be sent.")
        return

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = brevo_api_key
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

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
    sender = {"name": sender_name, "email": sender_email}
    to = [{"email": recipient_email}]
    
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(to=to, html_content=html_content, sender=sender, subject=subject)

    try:
        api_instance.send_transac_email(send_smtp_email)
        st.success("Onboarding email with your new keys has been sent!")
    except ApiException as e:
        st.error(f"An error occurred while sending the email: {e.reason}")



st.title("Smriti :) Client Portal")

create_db_and_tables()
db: Session = SessionLocal()

if "client_email" not in st.session_state:
    st.session_state.client_email = ""
if "client_verified" not in st.session_state:
    st.session_state.client_verified = False
if "current_client" not in st.session_state:
    st.session_state.current_client = None


if not st.session_state.client_email:
    st.header("Onboarding & Login")
    email_input = st.text_input("Please enter your email address to begin:")
    
    if st.button("Continue"):
        if email_input:
            client = db.query(ClientDB).filter(ClientDB.email == email_input).first()
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
                        rekognition_collection_id=rekog_collection
                    )
                    db.add(new_client)
                    db.commit()
                    db.refresh(new_client)
                    st.session_state.current_client = new_client
                    send_welcome_email(email_input, client_key, user_key)
            
            st.session_state.client_email = email_input
            st.rerun()
        else:
            st.warning("Please enter an email address.")

elif st.session_state.client_email and not st.session_state.client_verified:
    st.header("Verification Required")
    passkey_input = st.text_input("Enter your Client Passkey:", type="password")

    if st.button("Verify & Upload"):
        client = st.session_state.current_client
        if passkey_input == client.client_passkey:
            st.session_state.client_verified = True
            st.rerun()
        else:
            st.error("The Client Passkey you entered is incorrect.")

if st.session_state.client_verified:
    client = st.session_state.current_client
    S3_WEDDING_PHOTOS_FOLDER = client.s3_folder_path
    
    st.header(f"Upload Photos for {client.email}")
    st.info(f"These photos will be available for guests with the User Passkey: **{client.user_passkey}**")
    
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=st.secrets["aws"]["access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
        region_name=st.secrets["aws"]["s3_region"]
    )
    
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
                        Bucket=os.getenv("S3_BUCKET_NAME"),
                        Key=s3_key,
                        Fields={"Content-Type": uploaded_file.type},
                        Conditions=[{"Content-Type": uploaded_file.type}],
                        ExpiresIn=3600
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
                        st.error(f"Upload failed for {uploaded_file.name}. Status: {response.status_code}")
                        error_count += 1
                except Exception as e:
                    st.error(f"An error occurred with {uploaded_file.name}: {e}")
                    error_count += 1
                
                progress_text = f"Uploaded {i+1}/{len(uploaded_files)}: {uploaded_file.name}"
                progress_bar.progress((i + 1) / len(uploaded_files), text=progress_text)

            progress_bar.empty()
            st.success(f"Upload complete! {success_count} photos uploaded successfully.")
            if error_count > 0:
                st.error(f"{error_count} photos failed to upload.")

db.close()
