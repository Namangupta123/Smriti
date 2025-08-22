# Client Module: main.py

This file implements the client-facing Streamlit portal for Smriti, allowing event organizers to manage their event photo collections, upload images, and select highlights for their guests. It integrates with AWS S3 for storage, uses a database for event/user management, and provides onboarding via email.

## Key Features
- **Onboarding & Login:** Organizers sign up or log in using their email. New accounts are provisioned with unique S3 folders and Rekognition collections.
- **Passkey Verification:** Secure access to event management using a client passkey.
- **Photo Upload:** Upload multiple photos directly to a dedicated S3 folder for the event.
- **Highlight Selection:** Select and manage highlighted photos for the guest-facing slideshow.
- **Email Onboarding:** Sends welcome emails with access keys using Brevo (Sendinblue).

## Technologies Used
- [Streamlit](https://streamlit.io/) for the web interface
- [AWS S3](https://aws.amazon.com/s3/) for photo storage
- [SQLAlchemy](https://www.sqlalchemy.org/) for database ORM
- [boto3](https://boto3.amazonaws.com/) for AWS integration
- [Brevo (Sendinblue)](https://www.brevo.com/) for transactional emails

## How It Works
1. **Account Setup:** Organizer enters their email. If new, a unique S3 folder and Rekognition collection are created, and access keys are generated.
2. **Passkey Verification:** Organizer verifies their identity with a client passkey.
3. **Photo Management:** Upload photos to S3 and select highlights for the event slideshow.
4. **Guest Sharing:** A user passkey is provided for guests to access their photos via the user portal.

## Setup & Configuration
- Requires AWS and email credentials in Streamlit secrets.
- Database tables are created automatically on first run.

See `main.py` for detailed implementation and customization options.