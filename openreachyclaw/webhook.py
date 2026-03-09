"""FastAPI webhook server — receives inbound messages from OpenClaw.

Also serves a /health endpoint that reports integration statuses
and a /people endpoint for the web UI to list known people.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openreachyclaw.config import get_webhook_port, validate_config, get_data_dir

if TYPE_CHECKING:
    from openreachyclaw.text_brain import TextBrain

logger = logging.getLogger(__name__)

app = FastAPI(title="OpenReachyClaw Webhook")


class IncomingMessage(BaseModel):
    channel: str
    sender: str
    text: str
    display_name: str = ""
    thread_id: str = ""


class OutgoingReply(BaseModel):
    reply: str


# The text brain is injected at startup via set_text_brain().
_text_brain: TextBrain | None = None


def set_text_brain(brain: TextBrain) -> None:
    global _text_brain
    _text_brain = brain


# ── Health & status ───────────────────────────────────────────

@app.get("/health")
async def health():
    """Quick liveness check."""
    return {"status": "ok", "brain_ready": _text_brain is not None}


@app.get("/health/detailed")
async def health_detailed():
    """Detailed integration health report."""
    from openreachyclaw.memory import get_memory_store

    status = validate_config()

    # Check memory store
    try:
        store = get_memory_store()
        people = await store.get_all_people()
        memories = await store.recall_all()
        status["memory_store"] = True
        status["known_people"] = len(people)
        status["total_memories"] = len(memories)
    except Exception as exc:
        status["memory_store"] = False
        status["memory_error"] = str(exc)

    # Check OpenClaw connectivity
    try:
        import httpx
        from openreachyclaw.config import get_openclaw_url
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{get_openclaw_url()}/api/health")
            status["openclaw"] = resp.status_code == 200
    except Exception:
        status["openclaw"] = False

    # Check log file
    log_file = get_data_dir() / "rosie.log"
    status["log_file"] = log_file.exists()
    if log_file.exists():
        status["log_size_kb"] = round(log_file.stat().st_size / 1024, 1)

    status["brain_ready"] = _text_brain is not None

    return status


# ── Incoming messages ─────────────────────────────────────────

@app.post("/incoming", response_model=OutgoingReply)
async def incoming(msg: IncomingMessage):
    if _text_brain is None:
        logger.error("Text brain not initialised — dropping message from %s", msg.sender)
        return OutgoingReply(reply="Sorry, I'm not ready yet. Try again in a moment.")

    logger.info("[%s] %s: %s", msg.channel, msg.display_name or msg.sender, msg.text)
    reply = await _text_brain.handle_message(
        channel=msg.channel,
        sender=msg.sender,
        display_name=msg.display_name or msg.sender,
        text=msg.text,
        thread_id=msg.thread_id,
    )
    return OutgoingReply(reply=reply)


# ── People & faces API (for web UI and photo uploads) ─────────

@app.get("/api/people")
async def list_people():
    """List all known people with their face counts and memories."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    people = await store.get_all_people()
    return {"people": people}


@app.get("/api/people/{name}/memories")
async def person_memories(name: str):
    """Get all memories about a specific person."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    memories = await store.recall(name)
    return {"name": name, "memories": memories}


@app.post("/api/people/{name}/face")
async def upload_face(name: str, file: UploadFile = File(...)):
    """Upload a face photo for a person (learn their face from an uploaded image)."""
    from openreachyclaw.memory import get_memory_store

    faces_dir = get_data_dir() / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    filename = f"face_{safe_name}_upload{ext}"
    filepath = faces_dir / filename

    content = await file.read()
    filepath.write_bytes(content)

    store = get_memory_store()
    person_id = await store.add_person(name)
    await store.add_face_sighting(person_id, str(filepath))
    await store.remember(name, f"Face photo uploaded: {filename}", "face")

    face_count = len(await store.get_face_sightings(person_id))

    logger.info("Uploaded face photo for %s (%s, %d bytes)", name, filename, len(content))
    return {
        "status": "success",
        "person": name,
        "filename": filename,
        "total_photos": face_count,
    }


@app.post("/api/people/{name}/learn-from-directory")
async def learn_faces_from_directory(name: str, directory: str = Form(...)):
    """Learn face photos for a person from a directory of images."""
    from openreachyclaw.memory import get_memory_store
    import shutil

    src_dir = Path(directory)
    if not src_dir.is_dir():
        return JSONResponse({"error": f"Directory not found: {directory}"}, status_code=404)

    faces_dir = get_data_dir() / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)

    store = get_memory_store()
    person_id = await store.add_person(name)

    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    imported = 0

    for img_file in sorted(src_dir.iterdir()):
        if img_file.suffix.lower() not in image_exts:
            continue
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
        dest = faces_dir / f"face_{safe_name}_{imported:03d}{img_file.suffix}"
        shutil.copy2(img_file, dest)
        await store.add_face_sighting(person_id, str(dest))
        imported += 1

    if imported:
        await store.remember(name, f"Imported {imported} face photos from {directory}", "face")

    logger.info("Imported %d face photos for %s from %s", imported, name, directory)
    return {
        "status": "success",
        "person": name,
        "imported": imported,
        "total_photos": len(await store.get_face_sightings(person_id)),
    }


@app.get("/api/memories")
async def list_memories():
    """List all memories (last 200, with IDs for admin editing)."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    memories = await store.recall_all_with_ids()
    return {"memories": memories}


# ── Admin: People CRUD ────────────────────────────────────────

@app.put("/api/people/{person_id}/name")
async def rename_person(person_id: int, body: dict):
    """Rename a person."""
    from openreachyclaw.memory import get_memory_store
    new_name = body.get("name", "").strip()
    if not new_name:
        return JSONResponse({"error": "Name is required"}, status_code=400)
    store = get_memory_store()
    result = await store.update_person_name(person_id, new_name)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@app.delete("/api/people/{person_id}")
async def delete_person(person_id: int):
    """Delete a person and all their face sightings and memories."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    result = await store.delete_person(person_id)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


# ── Admin: Faces CRUD ─────────────────────────────────────────

@app.get("/api/people/{person_id}/faces")
async def list_person_faces(person_id: int):
    """List all face sightings for a person."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    faces = await store.get_person_faces(person_id)
    return {"person_id": person_id, "faces": faces}


@app.delete("/api/faces/{sighting_id}")
async def delete_face_sighting(sighting_id: int):
    """Delete a single face sighting."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    result = await store.delete_face_sighting(sighting_id)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


# ── Admin: Memories CRUD ──────────────────────────────────────

@app.put("/api/memories/{memory_id}")
async def update_memory(memory_id: int, body: dict):
    """Update a memory's fact and/or category."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    result = await store.update_memory(
        memory_id,
        fact=body.get("fact"),
        category=body.get("category"),
    )
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: int):
    """Delete a single memory."""
    from openreachyclaw.memory import get_memory_store
    store = get_memory_store()
    result = await store.delete_memory(memory_id)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


# ── Tools & Skills registration ───────────────────────────────

# Registered tools list — populated at startup via set_registered_tools()
_registered_tools: list[dict] = []


def set_registered_tools(tools: list[dict]) -> None:
    """Set the list of registered tools for the /api/tools endpoint."""
    global _registered_tools
    _registered_tools = tools


@app.get("/api/tools")
async def list_tools():
    """List all registered tools (for the Tools & Skills tab)."""
    return {"tools": _registered_tools}


# ── Server lifecycle ──────────────────────────────────────────

async def start_webhook_server() -> asyncio.Task:
    """Start the webhook server in the background and return its task."""
    port = get_webhook_port()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    logger.info("Webhook server starting on port %d", port)
    return task
