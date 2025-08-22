## User Module: main.py

This file implements the user-facing Streamlit web application for Smriti, a platform to help event attendees find and download their photos using facial recognition. The app connects to AWS S3 for photo storage and AWS Rekognition for face matching, and uses a database to manage event and user data.

### Key Features
- **Event Access:** Users enter a passkey to access their event photos.
- **Event Highlights:** Displays a slideshow of highlighted photos for the event.
- **Photo Search:** Users take a selfie, which is matched against the event's photo collection using AWS Rekognition. Matching photos are displayed and can be downloaded as a ZIP file.
- **Batch Processing:** Photos are processed in batches for efficient face search.
- **Secure & Private:** Uses presigned URLs for secure photo access and does not store user selfies.

### Technologies Used
- [Streamlit](https://streamlit.io/) for the web interface
- [AWS S3](https://aws.amazon.com/s3/) for photo storage
- [AWS Rekognition](https://aws.amazon.com/rekognition/) for face recognition
- [SQLAlchemy](https://www.sqlalchemy.org/) for database ORM
- [boto3](https://boto3.amazonaws.com/) for AWS integration

### How It Works
1. **User Authentication:** User enters a passkey to access their event.
2. **Highlights Slideshow:** Shows event highlights if available.
3. **Selfie Search:** User takes a selfie, which is indexed and matched against event photos.
4. **Results:** Matching photos are shown in a gallery and can be downloaded.

### Setup & Configuration
- Requires AWS credentials and event configuration in Streamlit secrets.
- Database models and tables are created automatically on first run.

See `main.py` for detailed implementation and customization options.
