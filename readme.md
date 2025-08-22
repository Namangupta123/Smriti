# Smriti | Finding Your Precious Moments

**Smriti** is an intelligent, AI-powered web application that transforms the way guests and hosts experience event photos.  

Named after the Hindi word for "memory" (**स्मृति**), the platform is designed to instantly sort through thousands of event pictures, allowing guests to find every photo of themselves with just a quick selfie.

---

## The Problem
After a celebration, hosts are often left with a massive, unorganized digital album, and guests face the daunting task of sifting through hundreds or thousands of images to find their own moments.  

**Smriti eliminates this friction, turning a tedious search into a delightful discovery.**

---

## Key Features

The system is composed of two primary, independent portals:

### Guest Portal
- **Instant Selfie Search:** Use your device's camera to find your photos.  
- **AI-Powered Matching:** Leverages AWS Rekognition for fast and accurate facial recognition.  
- **Automated Batch Processing:** Efficiently handles massive photo collections without timing out by processing images in manageable chunks.  
- **Personalized Gallery:** Displays a beautiful, responsive grid of all your matched photos.  
- **Highlights Slideshow:** Enjoy a client-curated slideshow of the event's best moments upon entry.  
- **One-Click Download:** Download a `.zip` archive of all your found memories.
- **Link:** [User-Portal](https://user-smriti.streamlit.app)

### Client Portal
- **Secure & Private:** A password-protected interface for event hosts and photographers.  
- **Multi-Client Onboarding:** A professional onboarding system that uses a PostgreSQL database to manage multiple clients, each with unique passkeys and isolated storage.  
- **Automated Welcome Emails:** New clients automatically receive their unique access keys via email, powered by **Brevo**.  
- **Scalable S3 Uploads:** Upload entire photo collections directly to a private AWS S3 bucket using secure, high-performance presigned URLs.  
- **Slideshow Curation:** Clients can easily browse their uploaded photos and select their favorites to be featured in the guest portal's highlights slideshow.
- **Link:** [Client-Portal](https://client-smriti.streamlit.app)

---

## Technology Stack
- **Frontend:** Streamlit  
- **Cloud Storage:** AWS S3  
- **AI / Face Recognition:** AWS Rekognition  
- **Database:** PostgreSQL (managed via Supabase)  
- **Email API:** Brevo  
- **Core Language:** Python  

---

## Live Portals
- **Guest Portal (Find Your Photos):** [Link to your User Portal Here]  
- **Client Portal (Upload & Manage Photos):** [Link to your Client Portal Here]  

---

## About the Creator
This project was developed by **Naman Gupta** as a comprehensive, production-ready application showcasing a modern, serverless architecture.  

The focus was on creating a **scalable, secure, and user-friendly experience** from the ground up.

---

## Connect with Me
I'd love to connect and discuss technology, cloud architecture, or future projects!

- **LinkedIn:**  https://www.linkedin.com/in/naman-gupta-cse 
- **GitHub:** https://github.com/Namangupta123