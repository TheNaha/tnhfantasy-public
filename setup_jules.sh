#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "==================================="
echo "Starting Jules environment setup..."
echo "==================================="

# 1. Setup Backend (FastAPI / uvicorn)
echo "[1/2] Setting up Backend_v2..."
cd backend_v2

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Load environment variables from root .env if it exists
if [ -f "../.env" ]; then
    echo "Loading environment variables from root .env..."
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        [[ "$line" =~ ^#.*$ ]] && continue
        [[ -z "$line" ]] && continue
        export "$line"
    done < ../.env
fi

# Install the necessary pip requirements
pip install -r requirements.txt

# Start the backend server in the background
# It will run on port 8002 as configured in backend_v2/Dockerfile
echo "Starting Backend server..."
uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload &
BACKEND_PID=$!

cd ..


# 2. Setup Frontend (Vite / React)
echo "[2/2] Setting up Frontend_v2..."
cd frontend_v2

# Install Node dependencies
npm install

# Start the frontend dev server in the background
# Allowing it to be accessed externally via 0.0.0.0
echo "Starting Frontend server..."
npm run dev -- --host 0.0.0.0 --port 5174 &
FRONTEND_PID=$!

cd ..

echo "==================================="
echo "Setup complete! Services are running:"
echo "- Backend API: http://localhost:8002"
echo "- Frontend UI: http://localhost:5174"
echo "==================================="

# Keep the script running to prevent the background jobs from dying
wait $BACKEND_PID $FRONTEND_PID
