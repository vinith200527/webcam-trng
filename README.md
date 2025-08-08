# 📷 Webcam True Random Number Generator (TRNG)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![NIST Test: Passed](https://img.shields.io/badge/NIST%20Test-Passed-success.svg)](#nist-test-results)

A true random number generator inspired by Cloudflare's LavaRand project that harvests entropy from public webcam images worldwide. The system combines visual noise from multiple sources with cryptographic functions to produce high-quality random numbers.

## 🎯 Key Features

- **Multi-source entropy collection** from 100+ public webcams simultaneously
- **Cryptographically secure** mixing using BLAKE2b with ephemeral keys
- **NIST STS validated** - passes all randomness tests
- **FastAPI REST API** for easy integration
- **Persistent buffer** using SQLite for reliability
- **Intelligent deduplication** to avoid static frames
- **Automatic failover** for unreliable cameras

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or higher
- pip package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/jordicor/webcam-trng.git
cd webcam-trng

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

1. **Start the API server:**
```bash
python random_webcam_rng_v3.9.6.py
```
The server will run on `http://localhost:8000`

2. **Get random numbers via API:**
```bash
curl http://localhost:8000/random
```
Response:
```json
{
  "random_hex": "a3f2b8c9d4e5f6a7b8c9d0e1f2a3b4c5..."
}
```

## 🔧 Advanced Usage

### Generate NIST Test Data

```bash
python random_webcam_rng_v3.9.6.py --generate-nist-file 10000000
```
This generates a file with 10 million random bits for statistical testing.

### Verify Webcam Health

Check and update the status of webcam sources:
```bash
python check_webcams.py --interval 60 --attempts 5
```
This tool will:
- Test each webcam multiple times
- Detect static/broken cameras
- Automatically comment out non-functional sources

## 📊 NIST Test Results

The generator has been validated using the NIST Statistical Test Suite. All tests passed successfully:

| Test | P-Value | Result |
|------|---------|--------|
| **Frequency (Monobit)** | 0.1929 | ✅ Random |
| **Frequency within Block** | 0.3622 | ✅ Random |
| **Runs Test** | 0.5233 | ✅ Random |
| **Longest Run of Ones** | 0.9429 | ✅ Random |
| **Binary Matrix Rank** | 0.7605 | ✅ Random |
| **Discrete Fourier Transform** | 0.8328 | ✅ Random |
| **Non-overlapping Template** | 0.2324 | ✅ Random |
| **Overlapping Template** | 0.1140 | ✅ Random |
| **Maurer's Universal Statistical** | 0.7274 | ✅ Random |
| **Linear Complexity** | 0.2927 | ✅ Random |
| **Serial Test** | 0.0949 / 0.0667 | ✅ Random |
| **Approximate Entropy** | 0.5290 | ✅ Random |
| **Cumulative Sums (Forward)** | 0.3351 | ✅ Random |
| **Cumulative Sums (Backward)** | 0.1505 | ✅ Random |
| **Random Excursions** | All states | ✅ Random |
| **Random Excursions Variant** | All states | ✅ Random |

[View full test results](result_test-nist_data_v3.9.6.txt)

## 🏗️ Architecture

### How It Works

1. **Entropy Collection**
   - Fetches images from multiple webcam sources in parallel
   - Supports JPEG snapshots, MJPEG streams, and HTML-embedded images
   - Implements anti-caching headers to ensure fresh data

2. **Entropy Processing**
   - Extracts 100x100 pixel crops from random positions
   - Position determined by cryptographic PRF based on frame digest
   - Converts crops to RGB for consistent byte representation

3. **Cryptographic Mixing**
   - Streams data through keyed BLAKE2b hash function
   - Mixes in latency and size metadata
   - Adds OS entropy (`os.urandom`) for defense in depth
   - Produces 512-bit (64-byte) output per batch

4. **Buffer Management**
   - Maintains FIFO buffer in SQLite database
   - Pre-generates random numbers for instant API responses
   - Automatically refills when buffer drops below threshold

### Security Model

- **Multi-source redundancy**: Even if some cameras are compromised, others provide entropy
- **Cryptographic extraction**: BLAKE2b with per-boot secret ensures unpredictability
- **Defense in depth**: OS RNG mixing provides additional security layer
- **Temporal variation**: Network latency adds timing-based entropy

## 📁 Project Structure

```
webcam-trng/
├── random_webcam_rng_v3.9.6.py  # Main TRNG implementation
├── check_webcams.py              # Webcam health verification tool
├── webcams.txt                   # List of webcam URLs
├── requirements.txt              # Python dependencies
├── rng_buffer.db                # SQLite buffer (auto-generated)
├── webcam_rng.log               # Rotating log file (auto-generated)
└── nist_data.txt                # NIST test data (when generated)
```

## ⚙️ Configuration

Key parameters can be adjusted in the source code:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NUM_SUCCESSFUL_CAMERAS_GOAL` | 100 | Target cameras per batch |
| `NUM_RANDOMS_PER_FETCH` | 10 | Random numbers generated per batch |
| `CROP_SIZE` | (100, 100) | Pixel dimensions of extracted crops |
| `RANDOM_BYTES` | 64 | Output size in bytes (512 bits) |
| `BUFFER_SIZE` | 50 | Minimum buffer before refill |
| `FETCH_TIMEOUT` | 10 | Seconds before timeout |
| `FETCH_CONCURRENCY` | 50 | Maximum parallel connections |

## 📋 Requirements

Create a `requirements.txt` file with:

```txt
aiohttp>=3.8.0
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
python-dotenv>=1.0.0
Pillow>=10.0.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pydantic>=2.0.0
```

## ⚠️ Important Notes

### Limitations

- **Not cryptographically proven**: While it passes statistical tests, this is an experimental implementation
- **Dependent on external sources**: Webcams may be offline, static, or manipulated
- **Not reproducible**: Each restart generates new ephemeral keys
- **Educational purposes**: Not recommended for production cryptographic applications without thorough review

### Ethical Considerations

- Only use publicly accessible webcams
- Respect rate limits and terms of service
- Avoid excessive load on any single source
- Consider privacy implications of webcam usage

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by [Cloudflare's LavaRand](https://blog.cloudflare.com/randomness-101-lavarand-in-production/)
- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Statistical testing by [NIST STS](https://csrc.nist.gov/projects/random-bit-generation/documentation-and-software)

## 📞 Assistance

Created with the assistance of Gemini 2.5 Pro and GPT-5

## 🔍 Where to Find Webcams

Finding reliable public webcams is crucial for entropy quality. Here are some tips for building your webcam list:

### Recommended Sources

#### 🚦 **Traffic Cameras**
- Search for "[your state/country] DOT traffic cameras"
- Most transportation departments provide public feeds
- Examples: 
  - US state DOT websites (UDOT, WSDOT, etc.)
  - City traffic management sites
  - Highway information systems

#### 🌤️ **Weather Stations**
- National weather services often have webcam networks
- University meteorology departments
- Mountain resort weather cams
- Search: "weather webcam [location]"

#### 🏔️ **Tourism & Landmarks**
- Ski resorts (snow conditions)
- Beach and surf cameras
- National park webcams
- City skyline cameras
- Harbor and marina views

#### 🏛️ **Educational Institutions**
- University campus cameras
- Research station feeds
- Observatory webcams
- Weather research facilities

#### 🌐 **Webcam Aggregators**
- **Windy.com** - Weather cameras worldwide
- **Webcamtaxi** - Global directory
- **EarthCam** - Landmark cameras
- **Insecam** - (Use ethically - only truly public feeds)
- **Opentopia** - Public camera directory

### Search Techniques

```bash
# Google dorks for finding webcams (use responsibly!)
inurl:"axis-cgi/mjpg/video.cgi"
inurl:"view/index.shtml"
inurl:"ViewerFrame?Mode="
inurl:"/webcam.jpg"
intitle:"webcam" "Live view"

# Combine with location for better results
site:*.gov inurl:camera
site:*.edu webcam
"traffic camera" site:*.org
```

### URL Patterns to Look For

Common webcam URL patterns that often work:
- `/axis-cgi/mjpg/video.cgi` - Axis cameras
- `/mjpg/video.mjpg` - Generic MJPEG
- `/nphMotionJpeg` - Panasonic cameras
- `/snapshot.jpg` - Static snapshots
- `/image.jpg` - Simple image endpoints
- `/cam_1.jpg` - Numbered camera feeds
- `/live.jpg` - Live image feeds

### ⚠️ Important Guidelines

#### ✅ **DO:**
- Use only publicly accessible cameras (no login required)
- Prefer government and official sources
- Diversify geographically for better entropy
- Test cameras before adding to your list
- Respect robots.txt if present
- Use reasonable fetch intervals (10+ seconds)

#### ❌ **DON'T:**
- Access cameras that require authentication
- Use cameras from private property without permission
- Overload servers with rapid requests
- Share lists that might compromise security
- Use cameras showing private spaces or individuals
- Bypass any access restrictions

### Testing Your Cameras

Use the included tool to verify your webcam list:
```bash
# Test all cameras in your list
python check_webcams.py --file webcams.txt --interval 60 --attempts 5

# This will:
# - Check if cameras are responding
# - Verify they're actually updating (not static)
# - Automatically comment out dead cameras
```

### Quality Tips

For best entropy quality:
- **Aim for 100+ diverse sources** from different networks
- **Mix different types**: traffic, weather, nature, urban
- **Global distribution**: different time zones = different lighting
- **Avoid similar cameras**: not all from same network/vendor
- **Prefer dynamic scenes**: traffic, water, trees (movement = entropy)
- **Regular maintenance**: run check_webcams.py weekly

### Sample Categories for a Balanced List

A good webcam list might include:
- 20% Traffic cameras (constant movement)
- 20% Weather/sky cameras (cloud movement)
- 20% Nature cameras (trees, water, wildlife)
- 20% Urban/city cameras (people, vehicles)
- 10% Maritime (harbors, beaches)
- 10% Special (volcanos, northern lights, etc.)

### Ethical Considerations

Remember that even public webcams deserve respectful use:
- Don't analyze or store footage of people
- Avoid cameras near sensitive locations
- Consider the impact of your traffic
- If asked to stop using a source, comply immediately
- Give credit to camera operators where appropriate

---

*⚡ Remember: True randomness is a precious resource. Use it wisely!*