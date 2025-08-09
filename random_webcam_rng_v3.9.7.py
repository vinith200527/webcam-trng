"""
random_webcam_rng_v3.9.7.py
---------------------

This module implements a true-random number generator inspired by
Cloudflare's LavaRand project.

Version 3.9.7 Enhancements:
- Added support for binary output format for NIST SP800-90B testing
- Configurable output format (binary/text) via command line parameter
- Fixed NIST test compatibility issues

Version 3.9.6 (minor) Enhancements:
- Optimización: cropear primero y convertir después a RGB (se reduce el coste de conversión).
- Mantiene (2) mezcla en streaming, (3) coordenadas de recorte derivadas, (5) anti-caché y
  (6) deduplicación suave introducidas en 3.9.5.

Version 3.9.5 (minor) Enhancements:
- (2) Mezcla en streaming: el hash BLAKE2b ahora se alimenta por trozos (crops/metadata)
  sin acumular todo en memoria antes de hashear.
- (3) Coordenadas de recorte derivadas: x,y se derivan con una PRF (BLAKE2b) sobre el
  digest del frame + un contador de salida, en lugar de depender solo de secrets.randbelow.
- (5) Anti-caché y selección aleatoria de <img> en HTML: headers no-cache y elección
  aleatoria entre múltiples imágenes embebidas en páginas HTML.
- (6) Deduplicación suave: ventana de últimos k digests por URL (k=4) para evitar
  alternancias de frames repetidos.

Version 3.9.4 Enhancements:
- Bugfix: Fixed a KeyError crash that occurred when disabling a camera that
  had never successfully returned a frame. Switched from `del` to a safe
  `.pop()` for cleanup.

Version 3.9.3 Enhancements:
- Bugfix: Re-added missing `urljoin` import.

Version 3.9.2 Enhancements:
- NIST Bugfix, Security Hardening (keyed BLAKE2b), Robustness (read limits,
  Pillow protection), Entropy Quality (deduplication), Compatibility.
"""

import asyncio
import hashlib
import os
import random
import logging
import logging.handlers
import argparse
import math
import time
import sqlite3
import io
import secrets
from collections import deque, defaultdict
from typing import List, Tuple, NamedTuple, Optional
from urllib.parse import urljoin

# Third-party libraries
import aiohttp
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError, ImageFile
from bs4 import BeautifulSoup

# --- Configuración ---
load_dotenv()

Image.MAX_IMAGE_PIXELS = 10000 * 10000
ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Constantes ---
WEBCAM_FILE = "webcams.txt"
DB_FILE = "rng_buffer.db"
LOG_FILE = "webcam_rng.log"
NUM_SUCCESSFUL_CAMERAS_GOAL = 100
NUM_RANDOMS_PER_FETCH = 10
CROP_SIZE = (100, 100)
RANDOM_BYTES = 64
FETCH_TIMEOUT = 10
BUFFER_SIZE = 50
FAILURE_THRESHOLD = 10
NIST_OUTPUT_FILE = "nist_data"  # Se añadirá .txt o .bin según el formato
FETCH_CONCURRENCY = 50
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_MJPEG_SCAN_BYTES = 2 * 1024 * 1024

# --- Configuración de Logging Rotativo ---
handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())


# --- Estado Global ---
_buffer: deque[str] = deque()
_active_camera_urls: List[str] = []
_failure_counts: defaultdict[str, int] = defaultdict(int)
_db_lock = asyncio.Lock()
_rng_system = secrets.SystemRandom()
_startup_secret = os.urandom(32)
_last_frame_digests: defaultdict[str, bytes] = defaultdict(bytes)

# (6) Ventana de deduplicación por URL (últimos k digests)
_recent_digests: defaultdict[str, deque] = defaultdict(lambda: deque(maxlen=4))


class ProcessedFrame(NamedTuple):
    image: Image.Image
    size_bytes: int
    latency_micros: int
    digest: bytes  # (3) Digest del frame para derivar coordenadas


# --- Lógica de Base de Datos y Ficheros ---
def _init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS random_buffer (hex_value TEXT PRIMARY KEY)")
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error on init: {e}")

def _load_buffer_from_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("SELECT hex_value FROM random_buffer").fetchall()
            _buffer.extend(row[0] for row in rows)
        logger.info(f"Loaded {len(_buffer)} numbers from '{DB_FILE}'.")
    except sqlite3.Error as e:
        logger.error(f"Database error on load: {e}")

async def _add_to_buffer_and_db(hex_value: str):
    async with _db_lock:
        _buffer.append(hex_value)
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute("INSERT OR IGNORE INTO random_buffer (hex_value) VALUES (?)", (hex_value,))
        except sqlite3.Error as e:
            logger.error(f"Database error on add: {e}")

async def _pop_from_buffer_and_db() -> Optional[str]:
    if not _buffer: return None
    async with _db_lock:
        value = _buffer.popleft()
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute("DELETE FROM random_buffer WHERE hex_value = ?", (value,))
        except sqlite3.Error as e:
            logger.error(f"Database error on pop: {e}")
    return value

def _load_and_filter_camera_urls():
    global _active_camera_urls
    try:
        with open(WEBCAM_FILE, 'r') as f:
            all_lines = [line.strip() for line in f if line.strip()]
            _active_camera_urls = [line for line in all_lines if not line.startswith('#')]
        logger.info(f"Loaded {len(_active_camera_urls)} active URLs.")
    except FileNotFoundError:
        _active_camera_urls = []

# --- Utilidades nuevas ---

def _derive_crop_xy(frame_digest: bytes, width: int, height: int, ctr: int) -> Tuple[int, int]:
    """
    (3) Deriva coordenadas (x, y) mediante BLAKE2b sobre (digest || ctr) con clave de arranque.
    """
    max_x = max(width - CROP_SIZE[0], 0) + 1
    max_y = max(height - CROP_SIZE[1], 0) + 1
    seed = hashlib.blake2b(
        frame_digest + ctr.to_bytes(8, 'big'),
        key=_startup_secret,
        digest_size=8,
        person=b'crop-v1'
    ).digest()
    x = int.from_bytes(seed[:4], 'big') % max_x
    y = int.from_bytes(seed[4:], 'big') % max_y
    return x, y

# --- Lógica de Obtención y Procesamiento ---

async def _handle_mjpeg_stream(response: aiohttp.ClientResponse) -> Optional[bytes]:
    try:
        data = bytearray()
        bytes_scanned = 0
        eoi_marker = b'\xff\xd9'
        async for chunk in response.content.iter_chunked(1024):
            bytes_scanned += len(chunk)
            if bytes_scanned > MAX_MJPEG_SCAN_BYTES:
                logger.warning(f"MJPEG stream from {response.url} exceeded scan limit of {MAX_MJPEG_SCAN_BYTES} bytes.")
                return None
            data.extend(chunk)
            if eoi_marker in data:
                frame = data[:data.find(eoi_marker) + 2]
                soi_marker = b'\xff\xd8'
                soi_pos = frame.find(soi_marker)
                if soi_pos != -1: return frame[soi_pos:]
                return frame
    except Exception as e:
        logger.warning(f"Error processing MJPEG stream from {response.url}: {type(e).__name__}")
    return None

async def _handle_html_page(session: aiohttp.ClientSession, response: aiohttp.ClientResponse) -> Optional[bytes]:
    """
    (5) Elige aleatoriamente entre múltiples <img> y usa headers anti-caché.
    """
    try:
        raw_body = await response.content.read(MAX_SNAPSHOT_BYTES)
        soup = BeautifulSoup(raw_body, 'lxml')
        imgs = [img.get('src') for img in soup.find_all('img') if img.get('src')]
        if not imgs:
            return None
        _rng_system.shuffle(imgs)  # selección aleatoria
        for img_src in imgs:
            img_url = urljoin(str(response.url), img_src)
            try:
                async with session.get(
                    img_url,
                    timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    }
                ) as img_resp:
                    if img_resp.status == 200 and 'image' in img_resp.headers.get('Content-Type', ''):
                        image_data = await img_resp.content.read(MAX_SNAPSHOT_BYTES + 1)
                        if len(image_data) > MAX_SNAPSHOT_BYTES:
                            logger.warning(f"Image from HTML at {img_url} is too large.")
                            continue
                        return image_data
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Error parsing HTML page {response.url}: {type(e).__name__}")
    return None

async def _fetch_and_process_frame(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore) -> Tuple[str, Optional[ProcessedFrame]]:
    async with semaphore:
        start_time = time.monotonic()
        try:
            # (5) Headers anti-caché
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                latency_micros = int((time.monotonic() - start_time) * 1_000_000)
                content_type = resp.headers.get('Content-Type', '').lower()
                image_data = None
                if 'image' in content_type:
                    image_data = await resp.content.read(MAX_SNAPSHOT_BYTES + 1)
                    if len(image_data) > MAX_SNAPSHOT_BYTES:
                        logger.warning(f"Snapshot from {url} is too large (>{MAX_SNAPSHOT_BYTES} bytes).")
                        return url, None
                elif 'multipart/x-mixed-replace' in content_type:
                    image_data = await _handle_mjpeg_stream(resp)
                elif 'text/html' in content_type:
                    image_data = await _handle_html_page(session, resp)
                
                if not image_data:
                    return url, None

                current_digest = hashlib.blake2b(image_data, digest_size=16).digest()

                # (6) Deduplicación por ventana
                window = _recent_digests[url]
                if current_digest in window:
                    logger.debug(f"Duplicate frame detected in recent window from {url}. Discarding.")
                    return url, None
                window.append(current_digest)

                # Mantiene compatibilidad con limpieza posterior
                _last_frame_digests[url] = current_digest

                try:
                    image = Image.open(io.BytesIO(image_data))
                    image.load()
                    if image.width >= CROP_SIZE[0] and image.height >= CROP_SIZE[1]:
                        return url, ProcessedFrame(
                            image=image,
                            size_bytes=len(image_data),
                            latency_micros=latency_micros,
                            digest=current_digest
                        )
                except (UnidentifiedImageError, OSError) as e:
                    logger.warning(f"Could not process image data from {url}. Reason: {e}")
        except asyncio.CancelledError:
            logger.debug(f"Fetch task for {url} cancelled gracefully.")
        except Exception as e:
            logger.debug(f"Generic fetch error for {url}: {type(e).__name__}")
    return url, None

async def _collect_successful_frames() -> List[ProcessedFrame]:
    global _active_camera_urls, _failure_counts
    if not _active_camera_urls: return []
    
    successful_frames = []
    shuffled_urls = list(_active_camera_urls)
    _rng_system.shuffle(shuffled_urls)
    
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(_fetch_and_process_frame(session, url, semaphore)) for url in shuffled_urls]
        for future in asyncio.as_completed(tasks):
            try:
                url, processed_frame = await future
                if processed_frame:
                    successful_frames.append(processed_frame)
                    if url in _failure_counts: _failure_counts[url] = 0
                    if len(successful_frames) >= NUM_SUCCESSFUL_CAMERAS_GOAL:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        break
                else:
                    _failure_counts[url] += 1
            except asyncio.CancelledError:
                logger.debug("Main collection loop caught a cancellation.")

    urls_to_disable = {url for url, count in _failure_counts.items() if count >= FAILURE_THRESHOLD}
    if urls_to_disable:
        _active_camera_urls = [u for u in _active_camera_urls if u not in urls_to_disable]
        for url in urls_to_disable:
            # Limpieza segura
            _failure_counts.pop(url, None)
            _last_frame_digests.pop(url, None)
            _recent_digests.pop(url, None)

    logger.info(f"\rCollected {len(successful_frames)} valid frames.")
    return successful_frames

def _mix_entropy(raw_data: bytes) -> str:
    # Mantener función original por compatibilidad (no usada con la mezcla en streaming)
    h = hashlib.blake2b(
        raw_data + os.urandom(64),
        key=_startup_secret,
        digest_size=RANDOM_BYTES,
        person=b'webcam-rng-v3'
    ).digest()
    return h.hex()

async def _generate_and_store_numbers():
    """
    (2) Mezcla en streaming + (3) derivación de coordenadas de recorte.
    Optimización 3.9.6: cropear primero y convertir el recorte a RGB después.
    """
    processed_frames = await _collect_successful_frames()
    if len(processed_frames) < NUM_SUCCESSFUL_CAMERAS_GOAL: return
    
    for out_idx in range(NUM_RANDOMS_PER_FETCH):
        # Hash en streaming
        h = hashlib.blake2b(
            key=_startup_secret,
            digest_size=RANDOM_BYTES,
            person=b'webcam-rng-v3'
        )

        any_chunk = False

        for frame in processed_frames:
            try:
                # Usar imagen en modo nativo, cropear primero
                img = frame.image

                max_x = img.width - CROP_SIZE[0]
                max_y = img.height - CROP_SIZE[1]
                if max_x < 0 or max_y < 0:
                    continue

                # (3) Derivar coordenadas determinísticamente desde el digest del frame + contador de salida
                x, y = _derive_crop_xy(frame.digest, img.width, img.height, out_idx)

                crop = img.crop((x, y, x + CROP_SIZE[0], y + CROP_SIZE[1]))

                # Convertir solo el recorte a RGB para bytes consistentes
                crop_rgb = crop.convert('RGB')

                h.update(crop_rgb.tobytes())
                h.update(frame.size_bytes.to_bytes(4, 'big'))
                h.update(frame.latency_micros.to_bytes(4, 'big'))
                any_chunk = True
            except (OSError, ValueError) as e:
                logger.warning(f"Skipping a corrupted frame during final processing: {e}")
                continue

        if any_chunk:
            # Mantiene mezcla de OS RNG como en versiones previas
            h.update(os.urandom(64))
            await _add_to_buffer_and_db(h.hexdigest())

    logger.info(f"Batch generation complete. Buffer size: {len(_buffer)}.")

async def _refill_buffer():
    if len(_buffer) < BUFFER_SIZE: await _generate_and_store_numbers()

def hex_to_binary_string(hex_string: str) -> str:
    """Convert hex string to ASCII binary string (for text format)"""
    return "".join(bin(int(c, 16))[2:].zfill(4) for c in hex_string)

async def generate_nist_file(total_bits: int, output_format: str = "binary"):
    """
    Generate NIST test file in either binary or text format.
    
    Args:
        total_bits: Total number of bits to generate
        output_format: "binary" for raw binary file, "text" for ASCII 0s and 1s
    """
    _init_db()
    _load_and_filter_camera_urls()
    
    # Determine output filename based on format
    if output_format == "binary":
        output_file = NIST_OUTPUT_FILE + ".bin"
        mode = 'ab'  # append binary
    else:
        output_file = NIST_OUTPUT_FILE + ".txt"
        mode = 'a'   # append text
    
    # Check existing file size
    bits_generated = 0
    if os.path.exists(output_file):
        if output_format == "binary":
            bits_generated = os.path.getsize(output_file) * 8
        else:
            bits_generated = os.path.getsize(output_file)
        logger.info(f"Found existing '{output_file}' with {bits_generated} bits. Resuming.")
    
    if bits_generated >= total_bits:
        logger.info("Target number of bits already generated. Nothing to do.")
        return
    
    # Generate and write data
    with open(output_file, mode) as f:
        while bits_generated < total_bits:
            if not _buffer:
                await _generate_and_store_numbers()
            
            while _buffer and bits_generated < total_bits:
                hex_val = await _pop_from_buffer_and_db()
                if not hex_val:
                    break
                
                if output_format == "binary":
                    # Write raw bytes for binary format
                    byte_data = bytes.fromhex(hex_val)
                    f.write(byte_data)
                    bits_written = len(byte_data) * 8
                else:
                    # Write ASCII 0s and 1s for text format
                    binary_str = hex_to_binary_string(hex_val)
                    f.write(binary_str)
                    bits_written = len(binary_str)
                
                f.flush()
                bits_generated += bits_written
                
                # Show progress
                progress = min(1.0, bits_generated / total_bits)
                print(f"\rProgress: [{'#' * int(progress * 40):<40}] {progress:.1%}", end="")
    
    print("\n")
    logger.info(f"Finished. Total bits in file '{output_file}': {bits_generated}.")
    logger.info(f"Output format: {output_format}")

app = FastAPI(title="Webcam True RNG v3.9.7", version="3.9.7")

@app.on_event("startup")
async def startup_event():
    _init_db()
    _load_buffer_from_db()
    _load_and_filter_camera_urls()
    if len(_buffer) < BUFFER_SIZE:
        asyncio.create_task(_refill_buffer())

class RandomResponse(BaseModel):
    random_hex: str

@app.get("/random", response_model=RandomResponse)
async def get_random():
    if not _buffer:
        await _refill_buffer()
    value = await _pop_from_buffer_and_db()
    if not value:
        raise HTTPException(status_code=503, detail="Service unavailable.")
    if len(_buffer) < BUFFER_SIZE:
        asyncio.create_task(_refill_buffer())
    return RandomResponse(random_hex=value)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Webcam-based True Random Number Generator v3.9.7")
    parser.add_argument('--generate-nist-file', type=int, metavar='NUM_BITS', 
                       help="NIST file generation mode. Specify number of bits to generate.")
    parser.add_argument('--output-format', type=str, choices=['binary', 'text'], 
                       default='binary',
                       help="Output format for NIST file: 'binary' (raw bytes) or 'text' (ASCII 0s and 1s). Default: binary")
    args = parser.parse_args()
    
    if args.generate_nist_file:
        asyncio.run(generate_nist_file(args.generate_nist_file, args.output_format))
    else:
        import uvicorn
        uvicorn.run("random_webcam_rng_v3.9.7:app", host="0.0.0.0", port=8000)