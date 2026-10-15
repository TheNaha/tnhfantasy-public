# TNHComfy Documentation

Welcome to the comprehensive documentation for TNHComfy.

## Table of Contents
1. [Architecture Overview](architecture.md)
2. [Frontend Documentation](frontend.md)
3. [Backend Documentation](backend.md)
4. [Deployment Guide](deployment.md)
5. [API Reference](api.md)
6. [Provider Architecture](provider-architecture.md) — which tree runs where, and why it is split four ways
7. [LLM Provider Handoff](llm-provider-handoff.md) — the llama.cpp design brief and its open questions

## Introduction
TNHComfy is a serverless implementation of ComfyUI designed for scalability and user-friendly Web UI interaction. This project serves as a dynamic, containerized wrapper around ComfyUI that integrates provider-based serverless inferencing (Modal, Beam), a custom job queuing system, an image gallery, and a local model management system without permanently storing large checkpoints on the backend.
