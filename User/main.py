import os
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from dotenv import load_dotenv
from sqlalchemy.orm import Session

# You must have PhotosDB in your database file for this to work
from database import SessionLocal, ClientDB, PhotosDB, create_db_and_tables

# --- App Configuration ---
load_dotenv()
# Start with a centered layout for the login and slideshow
st.set_page_config(page_title="Smriti | Finding Your Precious Moments", page_icon="✨", layout="centered")

# --- Constants ---
BATCH_SIZE = 25
MAX_WORKERS = 8
FACE_MATCH_THRESHOLD = 90
SELFIE_EXTERNAL_ID = "selfie_user_runtime"
SLIDESHOW_DELAY_SECONDS = 4

# --- AWS Client Initialization ---
@st.cache_resource
def make_clients():
    """Initializes and caches AWS clients."""
    try:
        s3 = boto3.client("s3", aws_access_key_id=st.secrets["aws"]["access_key_id"], aws_secret_access_key=st.secrets["aws"]["secret_access_key"], region_name=st.secrets["aws"]["s3_region"])
        rekog = boto3.client("rekognition", aws_access_key_id=st.secrets["aws"]["access_key_id"], aws_secret_access_key=st.secrets["aws"]["secret_access_key"], region_name=st.secrets["aws"]["s3_region"])
        return s3, rekog
    except (KeyError, NoCredentialsError):
        st.error("Could not connect to AWS. Please contact the event host.")
        return None, None

s3_client, rekognition = make_clients()
S3_BUCKET_NAME = st.secrets["aws"]["s3_bucket_name"]

# --- Helper Functions ---
@st.cache_data(ttl=600, show_spinner="Fetching event highlights...")
def get_highlighted_photos(_db_session: Session, client_id: int):
    """Fetches a list of S3 keys for highlighted photos from the database."""
    highlighted_photos = _db_session.query(PhotosDB.s3_key).filter_by(client_id=client_id, is_highlighted=True).all()
    return [p.s3_key for p in highlighted_photos]

def ensure_collection(collection_id: str):
    try:
        rekognition.describe_collection(CollectionId=collection_id)
    except rekognition.exceptions.ResourceNotFoundException:
        rekognition.create_collection(CollectionId=collection_id)

def purge_faces_with_external_id(collection_id: str, external_id: str):
    faces_to_delete = []
    paginator = rekognition.get_paginator('list_faces')
    for page in paginator.paginate(CollectionId=collection_id):
        for face in page.get("Faces", []):
            if face.get("ExternalImageId") == external_id:
                faces_to_delete.append(face["FaceId"])
    if faces_to_delete:
        rekognition.delete_faces(CollectionId=collection_id, FaceIds=faces_to_delete)

def index_selfie(selfie_bytes: bytes, collection_id: str, external_id: str):
    resp = rekognition.index_faces(CollectionId=collection_id, Image={"Bytes": selfie_bytes}, ExternalImageId=external_id, MaxFaces=1, QualityFilter="AUTO")
    return len(resp.get("FaceRecords", [])) > 0

@st.cache_data(ttl=3600, show_spinner=False)
def list_all_s3_photos(_bucket: str, _folder: str):
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=_bucket, Prefix=_folder):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".jpeg", ".png")):
                keys.append(key)
    return keys

def search_faces_with_retry(bucket: str, key: str, collection_id: str, max_retries: int = 3):
    delay = 0.25
    for _ in range(max_retries):
        try:
            resp = rekognition.search_faces_by_image(CollectionId=collection_id, Image={"S3Object": {"Bucket": bucket, "Name": key}}, FaceMatchThreshold=FACE_MATCH_THRESHOLD, MaxFaces=5)
            return resp.get("FaceMatches", [])
        except ClientError as e:
            if e.response['Error']['Code'] in ('ProvisionedThroughputExceededException', 'ThrottlingException'):
                time.sleep(delay)
                delay *= 2
            else: return []
    return []

def process_batch_parallel(batch_keys, bucket, collection_id):
    matches = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_key = {executor.submit(search_faces_with_retry, bucket, key, collection_id): key for key in batch_keys}
        for future in as_completed(future_to_key):
            if future.result():
                matches.append(future_to_key[future])
    return matches

def build_zip_for_keys(bucket: str, keys: list[str]) -> io.BytesIO:
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "a", zipfile.ZIP_DEFLATED, False) as zf:
        for k in keys:
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=k)
                zf.writestr(os.path.basename(k), obj["Body"].read())
            except ClientError: continue
    buff.seek(0)
    return buff

# --- Main Application Logic ---
st.title("Smriti :) Find your moments")

# Initialize session state
for key, default in [("passkey_verified", False), ("current_client", None), ("search_active", False), ("all_photo_keys", []), ("matched_s3_keys", []), ("processed_index", 0), ("slideshow_index", 0), ("slideshow_complete", False)]:
    if key not in st.session_state: st.session_state[key] = default

db: Session = SessionLocal()
create_db_and_tables()

# --- STEP 1: Passkey Verification ---
if not st.session_state.passkey_verified:
    st.header("Event Access")
    passkey_input = st.text_input("Please enter the User Passkey provided by the event host:", type="password")
    if st.button("Access Photos"):
        if passkey_input:
            client = db.query(ClientDB).filter(ClientDB.user_passkey == passkey_input).first()
            if client:
                st.session_state.passkey_verified = True
                st.session_state.current_client = client
                st.rerun()
            else:
                st.error("Invalid User Passkey. Please check the key and try again.")
        else:
            st.warning("Please enter a User Passkey.")
    st.stop()

# --- STEP 2: Slideshow of Highlights ---
client_config = st.session_state.current_client
highlight_keys = get_highlighted_photos(db, client_config.id)

if not st.session_state.slideshow_complete and highlight_keys:
    st.header("✨ Event Highlights")
    
    st.markdown("""<style> @keyframes fadeIn { 0% { opacity: 0; } 100% { opacity: 1; } } .slideshow-image { animation: fadeIn 1.5s; } </style>""", unsafe_allow_html=True)

    slideshow_placeholder = st.empty()
    
    if st.button("Skip to Photo Search →", use_container_width=True):
        st.session_state.slideshow_complete = True
        st.rerun()
        
    idx = st.session_state.slideshow_index
    
    with slideshow_placeholder.container():
        key = highlight_keys[idx]
        url = s3_client.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET_NAME, "Key": key}, ExpiresIn=60)
        st.image(url, caption=f"Highlight {idx + 1} of {len(highlight_keys)}", use_container_width=True)
        st.markdown('<div class="slideshow-image"></div>', unsafe_allow_html=True)
    
    st.session_state.slideshow_index = (idx + 1) % len(highlight_keys)
    
    time.sleep(SLIDESHOW_DELAY_SECONDS)
    st.rerun()

# --- STEP 3: Main Application ---
if st.session_state.slideshow_complete or not highlight_keys:
    S3_WEDDING_PHOTOS_FOLDER = client_config.s3_folder_path
    COLLECTION_ID = client_config.rekognition_collection_id

    if highlight_keys: # Only show the replay button if there are highlights
        if st.button("↩ Replay Highlights"):
            st.session_state.slideshow_complete = False
            st.session_state.slideshow_index = 0
            st.rerun()

    st.markdown("---")
    st.header("Find Your Photos")
    st.markdown("Take a clear selfie and I’ll find all your photos from the wedding collection.")
    selfie_picture = st.camera_input("Center your face and take a photo to begin the search")

    start_disabled = not (selfie_picture and s3_client and rekognition)
    if st.button("Start Search", type="primary", use_container_width=True, disabled=start_disabled):
        st.session_state.search_active = True
        st.session_state.matched_s3_keys = []
        st.session_state.processed_index = 0

        with st.spinner("Preparing..."):
            ensure_collection(COLLECTION_ID)
            purge_faces_with_external_id(COLLECTION_ID, SELFIE_EXTERNAL_ID)
            if not index_selfie(selfie_picture.getvalue(), COLLECTION_ID, SELFIE_EXTERNAL_ID):
                st.error("No face detected in the selfie. Please try again with better lighting.")
                st.session_state.search_active = False
                st.stop()
            st.session_state.all_photo_keys = list_all_s3_photos(S3_BUCKET_NAME, S3_WEDDING_PHOTOS_FOLDER)
            if not st.session_state.all_photo_keys:
                st.warning("No images found in storage. Please contact the event host.")
                st.session_state.search_active = False
                st.stop()

    total = len(st.session_state.all_photo_keys)
    if st.session_state.search_active and st.session_state.processed_index < total:
        start = st.session_state.processed_index
        end = min(start + BATCH_SIZE, total)

        st.progress(start / total, text=f"Analyzing photos... ({start} / {total})")
        batch_keys = st.session_state.all_photo_keys[start:end]
        batch_matches = process_batch_parallel(batch_keys, S3_BUCKET_NAME, COLLECTION_ID)

        if batch_matches:
            st.session_state.matched_s3_keys = sorted(set(st.session_state.matched_s3_keys).union(batch_matches))

        st.session_state.processed_index = end
        st.rerun()

    if st.session_state.matched_s3_keys:
        st.set_page_config(layout="wide") # Switch to wide layout for the results grid
        st.header(f"Found you in {len(st.session_state.matched_s3_keys)} photos!")
        zip_buffer = build_zip_for_keys(S3_BUCKET_NAME, st.session_state.matched_s3_keys)
        st.download_button(label="Download All Matched Moments (.zip)", data=zip_buffer, file_name="smriti_matched_moments.zip", mime="application/zip", use_container_width=True)
        
        cols = st.columns(4)
        for i, key in enumerate(st.session_state.matched_s3_keys):
            with cols[i % 4]:
                url = s3_client.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET_NAME, "Key": key}, ExpiresIn=3600)
                st.image(url, caption=os.path.basename(key), use_container_width=True)

    if st.session_state.search_active and st.session_state.processed_index >= total:
        st.success("All photos have been processed!")
        if not st.session_state.matched_s3_keys:
            st.info("No matches were found in the entire collection.")
        st.session_state.search_active = False

db.close()
