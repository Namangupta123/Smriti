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
from database import SessionLocal, ClientDB, create_db_and_tables

load_dotenv()
st.set_page_config(page_title="Smriti | Finding Your Precious Moments", page_icon=":sparkles:", layout="centered")

BATCH_SIZE = 25
MAX_WORKERS = 8
FACE_MATCH_THRESHOLD = 90
SELFIE_EXTERNAL_ID = "selfie_user_runtime"

def make_clients():
    try:
        s3 = boto3.client("s3", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), region_name=os.getenv("S3_REGION"))
        rekog = boto3.client("rekognition", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), region_name=os.getenv("S3_REGION"))
        return s3, rekog
    except (KeyError, NoCredentialsError):
        return None, None

s3_client, rekognition = make_clients()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

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

st.title("Smriti :) Find your moments")

for key, default in [("passkey_verified", False), ("current_client", None), ("search_active", False), ("all_photo_keys", []), ("matched_s3_keys", []), ("processed_index", 0)]:
    if key not in st.session_state: st.session_state[key] = default

db: Session = SessionLocal()
create_db_and_tables()

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

client_config = st.session_state.current_client
S3_WEDDING_PHOTOS_FOLDER = client_config.s3_folder_path
COLLECTION_ID = client_config.rekognition_collection_id

st.markdown("Take a clear selfie and I’ll find all your photos from the wedding collection.")
st.header("Take Your Selfie")
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
