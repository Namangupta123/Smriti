import uuid
import os
import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from dotenv import load_dotenv

load_dotenv()

# It's better to get secrets from the environment rather than st.secrets in a non-Streamlit file
DATABASE_URL = st.secrets.database.database_url
if not DATABASE_URL:
    raise ValueError("No DATABASE_URL set in environment variables.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ClientDB(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    client_passkey = Column(String, unique=True, nullable=False)
    user_passkey = Column(String, unique=True, nullable=False)
    s3_folder_path = Column(String, unique=True, nullable=False)
    rekognition_collection_id = Column(String, unique=True, nullable=False)
    
    # Relationship to the new PhotosDB table
    photos = relationship("PhotosDB", back_populates="client")

# NEW: PhotosDB table to track individual photos and their highlight status
class PhotosDB(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True, index=True)
    s3_key = Column(String, index=True, nullable=False)
    is_highlighted = Column(Boolean, default=False, nullable=False)
    
    # Foreign key to link photos to a specific client
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    client = relationship("ClientDB", back_populates="photos")


def create_db_and_tables():
    """Creates all tables in the database if they don't already exist."""
    Base.metadata.create_all(bind=engine)

def generate_unique_keys():
    """Generates a full set of unique keys and paths for a new client."""
    client_key = f"smriti_client_{uuid.uuid4().hex[:8]}"
    user_key = f"smriti_user_{uuid.uuid4().hex[:8]}"
    s3_folder = f"Wedding_images/{uuid.uuid4().hex}"
    rekognition_collection_id = f"smriti-collection-{uuid.uuid4().hex}"
    return client_key, user_key, s3_folder, rekognition_collection_id
