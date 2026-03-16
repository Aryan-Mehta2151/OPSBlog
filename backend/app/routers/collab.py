import json
import asyncio
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.db.models import BlogPost, Membership, User, CollabInvite

router = APIRouter(tags=["collab"])


class Room:
	def __init__(self, blog_id: str):
		self.blog_id = blog_id
		self.clients: Set[WebSocket] = set()
		self.updates: list[bytes] = []
		self._lock = asyncio.Lock()


_rooms: Dict[str, Room] = {}
_rooms_lock = asyncio.Lock()


def evict_room(blog_id: str) -> None:
    """Synchronously evict a blog's collab room from the in-memory cache."""
    _rooms.pop(blog_id, None)


async def _get_room(blog_id: str) -> Room:
	async with _rooms_lock:
		if blog_id not in _rooms:
			room = Room(blog_id)
			db = SessionLocal()
			try:
				blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
				if blog and blog.ydoc_updates:
					stored = json.loads(blog.ydoc_updates)
					room.updates = [bytes.fromhex(h) for h in stored]
			except Exception as e:
				print(f"[collab] load error for {blog_id}: {e}")
			finally:
				db.close()
			_rooms[blog_id] = room
		return _rooms[blog_id]


def _persist(blog_id: str, updates: list[bytes]) -> None:
	db = SessionLocal()
	try:
		blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
		if blog:
			blog.ydoc_updates = json.dumps([u.hex() for u in updates])
			db.commit()
	except Exception as e:
		print(f"[collab] persist error for {blog_id}: {e}")
	finally:
		db.close()


MSG_SYNC = 0
MSG_AWARENESS = 1
SYNC_STEP1 = 0
SYNC_STEP2 = 1
SYNC_UPDATE = 2


def _write_varint(n: int) -> bytes:
	out = []
	while True:
		b = n & 0x7F
		n >>= 7
		if n:
			out.append(b | 0x80)
		else:
			out.append(b)
			break
	return bytes(out)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
	value, shift = 0, 0
	while offset < len(data):
		byte = data[offset]
		offset += 1
		value |= (byte & 0x7F) << shift
		if not (byte & 0x80):
			break
		shift += 7
	return value, offset


def _encode_sync_update(update: bytes) -> bytes:
	return bytes([MSG_SYNC, SYNC_UPDATE]) + _write_varint(len(update)) + update


def _encode_sync2(update: bytes) -> bytes:
	return bytes([MSG_SYNC, SYNC_STEP2]) + _write_varint(len(update)) + update


_EMPTY_YJS_UPDATE = bytes([0, 0])


def _parse_sync_update_payload(data: bytes) -> bytes | None:
	if len(data) < 3 or data[0] != MSG_SYNC or data[1] not in (SYNC_UPDATE, SYNC_STEP2):
		return None
	length, offset = _read_varint(data, 2)
	return data[offset: offset + length]


@router.websocket("/ws/collab/{blog_id}")
async def collab_ws(websocket: WebSocket, blog_id: str, token: str = Query(...)):
	print(f"[collab] connect attempt blog={blog_id} token_len={len(token) if token else 0}")
	try:
		user_id = decode_token(token)
	except Exception:
		print(f"[collab] auth failed blog={blog_id}")
		await websocket.close(code=4001)
		return

	db = SessionLocal()
	try:
		user = db.query(User).filter(User.id == user_id).first()
		blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
		if not user or not blog:
			print(f"[collab] not found user/blog blog={blog_id} user_id={user_id}")
			await websocket.close(code=4004)
			return
		# Access control: only the blog owner OR users with an accepted invite may collaborate
		is_owner = blog.author_id == user_id
		if not is_owner:
			accepted_invite = db.query(CollabInvite).filter(
				CollabInvite.blog_id == blog_id,
				CollabInvite.recipient_id == user_id,
				CollabInvite.status == "accepted",
			).first()
			if not accepted_invite:
				print(f"[collab] access denied (no invite) blog={blog_id} user_id={user_id}")
				await websocket.close(code=4003)
				return
		# Also verify org membership as a baseline security check
		membership = db.query(Membership).filter(
			Membership.user_id == user_id,
			Membership.org_id == blog.org_id,
		).first()
		if not membership:
			print(f"[collab] membership denied blog={blog_id} user_id={user_id}")
			await websocket.close(code=4003)
			return
	finally:
		db.close()

	await websocket.accept()
	print(f"[collab] accepted blog={blog_id} user_id={user_id}")
	room = await _get_room(blog_id)

	async with room._lock:
		room.clients.add(websocket)
		existing = list(room.updates)

	# Proactively complete initial sync on connect. This avoids pending-sync states
	# when client step1 timing is missed or arrives before listeners settle.
	for update in existing:
		try:
			await websocket.send_bytes(_encode_sync_update(update))
		except Exception as e:
			print(f"[collab] initial replay error: {e}")
			break
	try:
		await websocket.send_bytes(_encode_sync2(_EMPTY_YJS_UPDATE))
	except Exception as e:
		print(f"[collab] initial sync2 error: {e}")

	try:
		while True:
			data = await websocket.receive_bytes()
			if not data:
				continue

			msg_type = data[0]

			if msg_type == MSG_SYNC:
				sub = data[1] if len(data) > 1 else -1

				if sub == SYNC_STEP1:
					async with room._lock:
						existing = list(room.updates)
					for update in existing:
						try:
							await websocket.send_bytes(_encode_sync_update(update))
						except Exception as e:
							print(f"[collab] replay error: {e}")
							break
					await websocket.send_bytes(_encode_sync2(_EMPTY_YJS_UPDATE))

				elif sub in (SYNC_UPDATE, SYNC_STEP2):
					payload = _parse_sync_update_payload(data)
					if payload:
						async with room._lock:
							room.updates.append(payload)
							if len(room.updates) > 500:
								room.updates = room.updates[-500:]
							snapshot = list(room.updates)

						loop = asyncio.get_event_loop()
						loop.run_in_executor(None, _persist, blog_id, snapshot)

					async with room._lock:
						dead: Set[WebSocket] = set()
						for client in room.clients:
							if client is not websocket:
								try:
									await client.send_bytes(data)
								except Exception:
									dead.add(client)
						room.clients -= dead

			elif msg_type == MSG_AWARENESS:
				async with room._lock:
					dead: Set[WebSocket] = set()
					for client in room.clients:
						if client is not websocket:
							try:
								await client.send_bytes(data)
							except Exception:
								dead.add(client)
					room.clients -= dead

	except WebSocketDisconnect:
		print(f"[collab] disconnected blog={blog_id} user_id={user_id}")
	except Exception as e:
		print(f"[collab] ws error for blog {blog_id}: {e}")
	finally:
		async with room._lock:
			room.clients.discard(websocket)
