# 🧠 Agent Plan README — Image Upload Service (HLD → LLD + Monitoring)

This document defines a complete **system design + implementation + observability plan** for a scalable Instagram-like image service using AWS-style serverless architecture and LocalStack for local development.

---

# 1. 🎯 Problem Statement

Build a backend system that supports:

- Image upload with metadata
- Image listing with filters
- Image retrieval (download/view)
- Image deletion

Constraints:
- Multi-user concurrency
- Horizontal scalability
- Low latency
- Cloud-native design
- Observable (monitoring + logging + tracing)

---

# 2. 🏗️ High-Level Design (HLD)

## 2.1 Architecture Overview

```text
Client
  │
  ▼
API Gateway
  │
  ▼
Lambda Functions
  │
  ├──────────────► S3 (Image Storage)
  │
  ├──────────────► DynamoDB (Metadata)
  │
  └──────────────► Observability Stack
                     ├── Logs
                     ├── Metrics
                     └── Traces