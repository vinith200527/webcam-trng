#!/usr/bin/env python3
"""
check_webcams.py
----------------
Verifica la “salud” de las webcams listadas en `webcams.txt`.
  • Descarga la imagen/stream actual.
  • Repite cada *interval* segundos (default = 60) hasta *attempts* (default = 5).
  • Si el hash BLAKE2b de la imagen no cambia en todos los intentos o la cámara
    falla, comenta la línea anteponiendo ‘# ’ en el fichero.

Uso:
    python check_webcams.py                # revisa con valores por defecto
    python check_webcams.py --interval 30 --attempts 3 --file otras.txt
"""

import asyncio
import hashlib
import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()  # si algún proxy o credencial viniese de .env

DEFAULT_FILE = "webcams.txt"
MAX_BYTES = 4 * 1024 * 1024        # 4 MB por snapshot
TIMEOUT = aiohttp.ClientTimeout(total=10)
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
TCP_LIMIT = 100  # limita conexiones totales para no saturar

# ---------- utilidades -------------------------------------------------------


async def _read_first_jpeg_from_mjpeg(response: aiohttp.ClientResponse) -> Optional[bytes]:
    """
    Lee el primer frame JPEG de un MJPEG buscando el marcador EOI (FF D9).
    Limita el escaneo a MAX_BYTES.
    """
    try:
        data = bytearray()
        bytes_scanned = 0
        eoi = b"\xff\xd9"
        soi = b"\xff\xd8"
        async for chunk in response.content.iter_chunked(2048):
            bytes_scanned += len(chunk)
            if bytes_scanned > MAX_BYTES:
                return None
            data.extend(chunk)
            pos = data.find(eoi)
            if pos != -1:
                frame = data[:pos + 2]
                soi_pos = frame.find(soi)
                if soi_pos != -1:
                    return bytes(frame[soi_pos:])
                return bytes(frame)
    except Exception:
        return None
    return None


async def fetch_image(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    """Devuelve bytes de una imagen (snapshot o primer frame mjpeg)."""
    try:
        async with session.get(url, timeout=TIMEOUT, headers=HEADERS) as r:
            if r.status < 200 or r.status >= 300:
                return None
            ct = r.headers.get("content-type", "").lower()
            if "image" in ct:
                data = await r.content.read(MAX_BYTES + 1)
                return data if len(data) <= MAX_BYTES else None
            if "multipart/x-mixed-replace" in ct or "mjpeg" in ct:
                return await _read_first_jpeg_from_mjpeg(r)
    except Exception:
        return None
    return None


def digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


# ---------- lógica principal -------------------------------------------------


async def _fetch_and_tag(session: aiohttp.ClientSession, url: str) -> Tuple[str, Optional[bytes]]:
    """Wrapper que devuelve (url, bytes|None) para mapear resultados a su URL."""
    img = await fetch_image(session, url)
    return url, img


async def check_urls(urls: List[str], interval: int, attempts: int) -> Dict[str, bool]:
    """
    Devuelve un dict {url: is_alive_and_updates}.
    • True  -> la cámara actualizó al menos una vez.
    • False -> nunca actualizó o devolvió error.
    """
    results = {u: False for u in urls}
    last_hash: Dict[str, Optional[bytes]] = {u: None for u in urls}

    connector = aiohttp.TCPConnector(limit=TCP_LIMIT)
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(attempts):
            tasks = [asyncio.create_task(_fetch_and_tag(session, u)) for u in urls]
            for aw in asyncio.as_completed(tasks):
                url, img = await aw
                if img:
                    h = digest(img)
                    if last_hash[url] is None:
                        # primer éxito
                        last_hash[url] = h
                    elif h != last_hash[url]:
                        results[url] = True  # cambió => cámara viva
                # si img es None dejamos results[url] como está
            if attempt < attempts - 1:
                await asyncio.sleep(interval)
    return results


def rewrite_file(path: Path, alive: Dict[str, bool]) -> None:
    """Comenta en disco las líneas de webcams que no están vivas."""
    out_lines = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                out_lines.append(line)
                continue
            if stripped in alive and not alive[stripped]:
                out_lines.append(f"# {stripped}\n")
            else:
                out_lines.append(line)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(out_lines), encoding="utf-8")
    tmp.replace(path)  # atomic swap


# ---------- CLI --------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Revisa webcams y comenta las que no actualizan.")
    parser.add_argument("--file", "-f", default=DEFAULT_FILE, help="Fichero de webcams.txt")
    parser.add_argument("--interval", "-i", type=int, default=60, help="Segundos entre comprobaciones (default 60)")
    parser.add_argument("--attempts", "-a", type=int, default=5, help="Número de comprobaciones (default 5)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: {path} no existe", file=sys.stderr)
        sys.exit(1)

    # Cargamos URLs (ignoramos comentadas)
    urls = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]

    if not urls:
        print("No hay URLs activas para revisar.")
        return

    print(f"Comprobando {len(urls)} webcams… ({args.attempts} intentos cada {args.interval}s)")
    alive = asyncio.run(check_urls(urls, args.interval, args.attempts))

    bad = [u for u, ok in alive.items() if not ok]
    if bad:
        print(f"{len(bad)} cámaras no actualizan → se comentarán en {path}")
        rewrite_file(path, alive)
    else:
        print("Todas las cámaras actualizan correctamente 🎉")


if __name__ == "__main__":
    main()