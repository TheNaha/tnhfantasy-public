# TNHComfy

A serverless implementation of ComfyUI designed for scalability and user-friendly Web UI interaction.

## Overview
This project serves as a dynamic, containerized wrapper around ComfyUI that integrates provider-based serverless inferencing (Modal, Beam), a custom job queuing system, an image gallery, and a local model management system without permanently storing large checkpoints on the backend.

## Architecture
- **tnhcomfy-frontend** (Vite + React)
- **tnhcomfy-backend** (FastAPI)
- **provider-workers** (Serverless instances on Modal or Beam)

## Quick Start
1. Copy `.env.example` to `.env` and configure your API tokens (HF_TOKEN, CIVITAI_TOKEN).
2. Start the project using Docker Compose:
   ```bash
   docker-compose up -d
   ```
3. Access the Web UI via the configured frontend port (default: 5174).

## Project Maintenance
Built to scale seamlessly using serverless providers. Output images and localized SQLite states (`backend_v2/data/comfy.db`) are ignored from the version control for security.
