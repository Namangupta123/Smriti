import os
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Smriti | Finding Your Precious Moments", page_icon=":sparkles:", layout="centered")

BATCH_SIZE = 25
MAX_WORKERS = 8
FACE_MATCH_THRESHOLD = 90
COLLECTION_ID = "wedding_faces"
SELFIE_EXTERNAL_ID = "selfie_user"

def make_clients():
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("S3_REGION"),
        )
        rekog = boto3.client(
            "rekognition",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("S3_REGION"),
        )
        return s3, rekog
    except (KeyError, NoCredentialsError):
        return None, None

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION")
S3_WEDDING_PHOTOS_FOLDER = os.getenv("S3_WEDDING_PHOTOS_FOLDER")

s3_client, rekognition = make_clients()
if not all([s3_client, rekognition, S3_BUCKET_NAME, S3_REGION, S3_WEDDING_PHOTOS_FOLDER]):
    st.error("Error in credentials contact client")
    st.stop()

def ensure_collection(collection_id: str):
    """Create Rekognition collection if it doesn't exist."""
    try:
        rekognition.describe_collection(CollectionId=collection_id)
    except rekognition.exceptions.ResourceNotFoundException:
        rekognition.create_collection(CollectionId=collection_id)


def purge_faces_with_external_id(collection_id: str, external_id: str):
    """Delete any existing faces with the given ExternalImageId (cleanup from previous runs)."""
    next_token = None
    faces_to_delete = []
    while True:
        kwargs = {"CollectionId": collection_id, "MaxResults": 4096}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = rekognition.list_faces(**kwargs)
        for f in resp.get("Faces", []):
            if f.get("ExternalImageId") == external_id:
                faces_to_delete.append(f["FaceId"])
        next_token = resp.get("NextToken")
        if not next_token:
            break

    for i in range(0, len(faces_to_delete), 100):
        chunk = faces_to_delete[i:i+100]
        if chunk:
            rekognition.delete_faces(CollectionId=collection_id, FaceIds=chunk)


def index_selfie(selfie_bytes: bytes, collection_id: str, external_id: str):
    """Index selfie; returns True if at least one face indexed."""
    resp = rekognition.index_faces(
        CollectionId=collection_id,
        Image={"Bytes": selfie_bytes},
        ExternalImageId=external_id,
        DetectionAttributes=["DEFAULT"],
        MaxFaces=1,
        QualityFilter="AUTO",
    )
    return len(resp.get("FaceRecords", [])) > 0

@st.cache_data(ttl=3600, show_spinner=False)
def list_all_s3_photos(bucket: str, folder: str):
    """List image object keys under a prefix."""
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=folder):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".jpeg", ".png")):
                keys.append(key)
    return keys


def retry_search_faces_by_image(bucket: str, key: str, collection_id: str, max_retries: int = 5):
    """Call search_faces_by_image with simple exponential backoff to handle throttling."""
    delay = 0.2
    for attempt in range(max_retries):
        try:
            resp = rekognition.search_faces_by_image(
                CollectionId=collection_id,
                Image={"S3Object": {"Bucket": bucket, "Name": key}},
                FaceMatchThreshold=FACE_MATCH_THRESHOLD,
                MaxFaces=1,
            )
            return resp.get("FaceMatches", [])
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in {"ThrottlingException", "ProvisionedThroughputExceededException"}:
                time.sleep(delay)
                delay = min(delay * 2, 2.0)
                continue
            if code in {"InvalidImageFormatException", "ImageTooLargeException"}:
                return []
            raise
    return []


def process_batch_parallel(batch_keys, bucket, collection_id, max_workers=MAX_WORKERS):
    """Run Rekognition searches concurrently for a batch of keys."""
    matches = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        fut_to_key = {
            executor.submit(retry_search_faces_by_image, bucket, key, collection_id): key
            for key in batch_keys
        }
        for fut in as_completed(fut_to_key):
            key = fut_to_key[fut]
            try:
                face_matches = fut.result()
                if face_matches:
                    matches.append(key)
            except Exception as e:
                st.sidebar.warning(f"Error on {key}: {e}")
    return matches


def build_zip_for_keys(bucket: str, keys: list[str]) -> io.BytesIO:
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "a", zipfile.ZIP_DEFLATED, False) as zf:
        for k in keys:
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=k)
                zf.writestr(os.path.basename(k), obj["Body"].read())
            except Exception as e:
                st.sidebar.warning(f"Could not add {k} to zip: {e}")
    buff.seek(0)
    return buff


st.title("Smriti :) Find your moments")
st.markdown("Take a clear selfie and I’ll find all your photos from the wedding collection.")

for key, default in [
    ("search_active", False),
    ("all_photo_keys", []),
    ("matched_s3_keys", []),
    ("processed_index", 0),
    ("collection_id", COLLECTION_ID),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.header("Take Your Selfie")
selfie_picture = st.camera_input("Center your face and take a photo to begin the search")

start_disabled = not (selfie_picture and s3_client and rekognition)
if st.button("Start Search", type="primary", use_container_width=True, disabled=start_disabled):
    st.session_state.search_active = True
    st.session_state.matched_s3_keys = []
    st.session_state.processed_index = 0

    with st.spinner("Preparing..."):
        try:
            ensure_collection(st.session_state.collection_id)
            purge_faces_with_external_id(st.session_state.collection_id, SELFIE_EXTERNAL_ID)

            indexed = index_selfie(selfie_picture.getvalue(), st.session_state.collection_id, SELFIE_EXTERNAL_ID)
            if not indexed:
                st.error("No face detected in the selfie. Please try again with better lighting.")
                st.session_state.search_active = False
                st.stop()

            st.session_state.all_photo_keys = list_all_s3_photos(S3_BUCKET_NAME, S3_WEDDING_PHOTOS_FOLDER)
            if not st.session_state.all_photo_keys:
                st.warning("No images found in storage. Please contact Client")
                st.session_state.search_active = False
                st.stop()

        except Exception as e:
            st.error(f"Error starting search: {e} Please contact Client")
            st.session_state.search_active = False
            st.stop()

total = len(st.session_state.all_photo_keys)
if st.session_state.search_active and st.session_state.processed_index < total:
    start = st.session_state.processed_index
    end = min(start + BATCH_SIZE, total)

    st.progress(start / total)
    st.caption(f"Analyzing photos... ({start} / {total})")

    batch_keys = st.session_state.all_photo_keys[start:end]
    batch_matches = process_batch_parallel(batch_keys, S3_BUCKET_NAME, st.session_state.collection_id, MAX_WORKERS)

    if batch_matches:
        st.session_state.matched_s3_keys = sorted(set(st.session_state.matched_s3_keys).union(batch_matches))

    st.session_state.processed_index = end
    st.rerun()

if st.session_state.matched_s3_keys:
    st.header(f"Found you in {len(st.session_state.matched_s3_keys)} photos!")
    zip_buffer = build_zip_for_keys(S3_BUCKET_NAME, st.session_state.matched_s3_keys)
    st.download_button(
        label="Download All Matched Moments (.zip)",
        data=zip_buffer,
        file_name="smriti_matched_moments.zip",
        mime="application/zip",
        use_container_width=True,
    )

    cols = st.columns(4)
    for i, key in enumerate(st.session_state.matched_s3_keys):
        with cols[i % 4]:
            try:
                url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET_NAME, "Key": key},
                    ExpiresIn=3600,
                )
                st.image(url, caption=os.path.basename(key), use_container_width=True)
            except Exception:
                st.error(f"Could not display {os.path.basename(key)}")

if st.session_state.search_active and st.session_state.processed_index >= len(st.session_state.all_photo_keys):
    st.success("All photos have been processed!")
    if not st.session_state.matched_s3_keys:
        st.info("No matches were found in the entire collection.")
    st.session_state.search_active = False
