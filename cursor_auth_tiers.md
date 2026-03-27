# boolab — Auth & User Tiers

## Overview
Three-tier access system: Owner, Member, Guest. Single owner account via env var. Owner can create member accounts. Guests are IP-tracked, no login required.

---

## 1. Schema Changes (`schema.sql`)

### New tables

```sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member')),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS guest_message_counts (
    ip TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    last_seen TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS member_message_counts (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);
```

### Alter existing tables

```sql
-- personas: add owner_id (null = default/global, visible to all)
ALTER TABLE personas ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;

-- daws: add owner_id (null = default/global, visible to all)
ALTER TABLE daws ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
```

---

## 2. Auth System (`routers/auth.py`)

New router mounted at `/api/auth`.

### Owner login
- `POST /api/auth/login` — body: `{ username: "owner", password: "..." }`
- Verify password against `OWNER_PASSWORD` env var using `bcrypt` (hash on first compare, or use `secrets.compare_digest` for plain)
- On success: return signed JWT (`HS256`, secret from `JWT_SECRET` env var, 30-day expiry)
- JWT payload: `{ sub: "owner", role: "owner", exp: ... }`

### Member login
- Same endpoint — if username != "owner", look up `users` table, verify `bcrypt` hash
- JWT payload: `{ sub: user_id, role: "member", exp: ... }`

### Token format
- Stored in `localStorage` on frontend as `boolab_token`
- Sent as `Authorization: Bearer <token>` header on all API requests

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login (owner or member) |
| POST | `/api/auth/logout` | Client-side only (clear localStorage) |
| GET | `/api/auth/me` | Return current user info from token |

### `get_current_user()` dependency (`auth.py`)
```python
async def get_current_user(request: Request) -> dict | None:
    """Returns user dict or None for unauthenticated requests."""
```
Returns:
- `{ role: "owner" }` for valid owner JWT
- `{ role: "member", user_id: "...", username: "..." }` for valid member JWT
- `None` for missing/invalid/expired token

### `require_owner()` dependency
Raises `403` if not owner.

### `require_auth()` dependency
Raises `401` if not owner or member (guest).

---

## 3. Owner-Only: Member Management (`routers/users.py`)

Mounted at `/api/users`. All routes require `require_owner()`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/users` | List all members |
| POST | `/api/users` | Create member `{ username, password }` — bcrypt hash password |
| DELETE | `/api/users/{id}` | Delete member + cascade |

---

## 4. Access Control per Route

### `routers/chats.py`
- `POST /api/chats` — open to all (owner, member, guest)
- `POST /api/chats/{id}/messages` — open to all, but enforce caps:
  - **Guest:** check `guest_message_counts` by `request.client.host`. If count >= 20, return `429` with `{ detail: "guest_limit_reached" }`
  - **Member:** check `member_message_counts` for today. If count >= 200, return `429` with `{ detail: "member_daily_limit_reached" }`. Reset is automatic (new date = new row).
  - Increment count on every successful message insert.
- `GET /api/chats` — owner sees all their chats; member sees only their own; guest gets `[]`
- Chats must store `owner_id` (user UUID or null for guest/owner)

### `routers/personas.py`
- `GET /api/personas` — return global personas (`owner_id IS NULL`) + own personas if member
- `POST /api/personas` — member can create (max check: count where `owner_id = user_id` <= 10, no hard limit specified but reasonable); owner unlimited
- `PUT/PATCH /api/personas/{id}` — owner can edit any; member can only edit own (`owner_id = user_id`); cannot edit globals
- `DELETE /api/personas/{id}` — same scope rules; cannot delete globals
- `POST /api/personas/{id}/set-default` — owner only
- Persona create for members: ignore `default_model` field — always use site default model from Ollama settings

### `routers/daws.py`
- `GET /api/daws` — return global DAWs (`owner_id IS NULL`) + own DAWs if member
- `POST /api/daws` — member limited to 2 per mode (`booops`, `808notes`). Check count before insert, return `429` with `{ detail: "daw_limit_reached" }` if exceeded.
- `PUT/PATCH /api/daws/{id}` — owner: any; member: own only
- `DELETE /api/daws/{id}` — owner: any; member: own only; cannot delete globals

### Protected routes (owner only — return `403` for member/guest):
- All of `routers/branding.py` PUT/PATCH/POST/DELETE
- All of `routers/memory.py`
- All of `routers/custom_instructions.py`
- `GET/PUT /api/settings/*`
- `routers/users.py` (all)

### File uploads
- Owner: no limit
- Member: 5MB per file, max 10 files total (check in upload endpoint)
- Guest: no file upload — return `403`

---

## 5. New `.env` vars

```env
OWNER_PASSWORD=changeme
JWT_SECRET=replace-with-random-256-bit-secret
```

Add to `.env.example` with placeholder values.

---

## 6. Frontend

### Auth state (`store/index.js`)
Add to Zustand store:
```js
token: localStorage.getItem('boolab_token') || null,
currentUser: null,   // populated from GET /api/auth/me on load
setToken(token) { ... localStorage.setItem('boolab_token', token) },
clearToken() { ... localStorage.removeItem('boolab_token') },
```

On app load: if token present, call `GET /api/auth/me` and set `currentUser`. If 401, clear token.

### API calls (`api/*.js`)
All fetch calls must include `Authorization: Bearer {token}` header if token present.

### Login UI
- Small login modal or dedicated `/login` page
- Username + password fields
- On success: store token, set `currentUser`, redirect to home
- Show login option in sidebar footer (lock icon or "Sign in") when not authenticated

### Access gating (frontend)
- **Settings tab/link:** hidden for guest + member
- **AI Settings tab/link:** hidden for guest + member  
- **Persona edit/delete buttons:** hidden for guest; shown for member only on own personas
- **DAW edit/delete buttons:** same as personas
- **Model selector:** hidden for member + guest — use site default silently
- **File upload:** hidden/disabled for guest
- **Chat input:** show message cap warning when approaching limit (guest: 18/20+, member: 180/200+)
- **Guest cap hit:** show "Create an account or ask the owner for access" message

### Guest cap tracking (belt-and-suspenders)
Also track in `localStorage` as `boolab_guest_count` for immediate UI feedback before server 429 fires.

---

## 7. Constraints

- Never expose `password_hash` in any API response
- JWT secret must come from env — never hardcode
- `owner_id IS NULL` = global/default — never assign owner_id to seed personas/DAWs
- Members cannot see owner's chats, memory, custom instructions, or owner-scoped personas/DAWs
- Check `schema.sql` for exact column names before writing any query
- All cap enforcement must be server-side — frontend is UI only
- Use `bcrypt` via `passlib[bcrypt]` — add to `requirements.txt`
- Use `python-jose[cryptography]` for JWT — add to `requirements.txt`

---

## 8. Verify

```bash
docker compose up --build -d
docker logs -f boolab_api
```

Test matrix:
1. `POST /api/auth/login` with owner creds → get token
2. `GET /api/auth/me` with token → `{ role: "owner" }`
3. `POST /api/users` (owner token) → create member
4. `POST /api/auth/login` with member creds → get token
5. `GET /api/personas` as member → see globals only
6. `POST /api/personas` as member → create personal persona
7. `POST /api/chats/{id}/messages` with no token 21 times from same IP → 429 on 21st
8. Member: 201 messages in one day → 429 on 201st
9. `PUT /api/branding/booops` as member → 403
10. `DELETE /api/personas/{global_id}` as member → 403
