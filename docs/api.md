# API Reference

The TNHComfy Backend exposes a robust REST API for managing jobs, models, parameters, and application state.

## Base URL
Typically `http://localhost:8002` (or whatever the backend is configured to listen on).

## Authentication
Currently, TNHComfy is a local/self-hosted application, meaning it expects to run in a secure environment without explicit user authentication mechanisms built into the API layer. Ensure you implement reverse-proxy level authentication if exposing to the public internet.

## Common Endpoints

### 1. Jobs (`/api/v2/jobs`)
Handles queuing, monitoring, and controlling image generation tasks.

#### GET `/api/v2/jobs`
- **Description:** Returns a list of jobs (all states: pending, processing, completed, failed).
- **Query Parameters:** Optional filters based on state, model, or timeframe.
- **Returns:** A JSON array of job objects.

#### POST `/api/v2/jobs`
- **Description:** Submits a new generation request.
- **Body:** JSON payload containing prompt, negative prompt, model, CFG scale, steps, LoRAs, and provider preferences.
- **Returns:** The created job ID and initial state.

#### GET `/api/v2/jobs/{job_id}`
- **Description:** Returns the status and details of a specific job.
- **Returns:** A job object including generated file URLs if completed.

#### DELETE `/api/v2/jobs/{job_id}`
- **Description:** Cancels a pending/processing job or deletes a completed job record (and potentially its output).
- **Returns:** Confirmation message.

### 2. Models (`/api/v2/models`)
Manages access to available checkpoints, LoRAs, and their parameters.

#### GET `/api/v2/models`
- **Description:** Retrieves a list of available models and LoRAs.
- **Returns:** A categorized JSON structure of models, their metadata, and required tags/trigger words.

### 3. Providers (`/api/v2/providers`)
Interacts with the configured serverless inference providers.

#### GET `/api/v2/providers`
- **Description:** Returns the status of active providers (Modal, Beam) and their available containers.
- **Returns:** A JSON list of provider statuses.

### 4. Configuration (`/api/v2/config`)
Retrieves system-wide configurations and generation defaults.

#### GET `/api/v2/config`
- **Description:** Returns default settings (e.g., default CFG, default steps, available samplers).
- **Returns:** A JSON object with configuration parameters.

### 5. WebSockets (`/ws`)
Real-time bi-directional communication.

#### Endpoint: `ws://localhost:8002/ws`
- **Description:** Connects to the backend WebSocket server.
- **Usage:** Clients subscribe to `job` events. The backend emits updates like `job.started`, `job.processing`, `job.completed`, and `job.failed`.
