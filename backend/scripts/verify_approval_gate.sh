#!/usr/bin/env bash
# Verify the approval gate inserts a row and blocks a second POST (409).
# Requires the docker stack to be running (hlh_api must be live).
set -euo pipefail

BASE="http://localhost:9600/api"
PASS=0
FAIL=0

chat_id=$(docker exec hlh_api python3 -c "
import asyncio, httpx

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('$BASE/auth/login', json={'username':'admin','password':'admin'}, cookies=None)
        # create workspace
        r = await c.post('$BASE/workspaces/', json={'name':'approval-test'}, cookies=r.cookies)
        ws = r.json()
        # create chat
        r = await c.post('$BASE/chats/', json={'workspace_id': ws['id']}, cookies=r.cookies)
        chat = r.json()
        print(chat['id'])

asyncio.run(main())
" 2>/dev/null)

if [ -z "$chat_id" ]; then
    echo "FAIL: could not create test chat"
    exit 1
fi
echo "Test chat: $chat_id"

# Step 1: POST a message that should trigger the approval gate.
# The safeguard engine matches 'kill' as HIGH severity in tests.
response=$(docker exec hlh_api python3 -c "
import asyncio, httpx, json

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('$BASE/auth/login', json={'username':'admin','password':'admin'})
        cookies = r.cookies
        r = await c.post(
            '$BASE/chats/$chat_id/messages',
            json={'content': 'I want to kill all the processes on my server'},
            cookies=cookies,
        )
        print(json.dumps({'status_code': r.status_code, 'body': r.json()}))

asyncio.run(main())
" 2>/dev/null)

status_code=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['status_code'])")
body_status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['body'].get('status',''))")
assistant_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['body'].get('assistant_message_id',''))")

if [ "$status_code" = "202" ] && [ "$body_status" = "approval_pending" ] && [ -n "$assistant_id" ]; then
    PASS=$((PASS+1))
    echo "PASS: 202 with approval_pending and assistant_message_id=$assistant_id"
else
    FAIL=$((FAIL+1))
    echo "FAIL: expected 202+approval_pending, got status=$status_code body_status=$body_status"
fi

# Step 2: Verify the row exists in DB with approval_pending status
row_status=$(docker exec hlh_api python3 -c "
import asyncio, httpx, json

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('$BASE/auth/login', json={'username':'admin','password':'admin'})
        cookies = r.cookies
        r = await c.get('$BASE/chats/$chat_id/messages', cookies=cookies)
        items = r.json().get('items', [])
        for item in items:
            if item['id'] == '$assistant_id':
                print(item.get('status', ''))
                return
        print('NOT_FOUND')

asyncio.run(main())
" 2>/dev/null)

if [ "$row_status" = "approval_pending" ]; then
    PASS=$((PASS+1))
    echo "PASS: row exists with status=approval_pending"
else
    FAIL=$((FAIL+1))
    echo "FAIL: expected row status=approval_pending, got: $row_status"
fi

# Step 3: Second POST should return 409
response2=$(docker exec hlh_api python3 -c "
import asyncio, httpx, json

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('$BASE/auth/login', json={'username':'admin','password':'admin'})
        cookies = r.cookies
        r = await c.post(
            '$BASE/chats/$chat_id/messages',
            json={'content': 'test second message'},
            cookies=cookies,
        )
        print(json.dumps({'status_code': r.status_code}))

asyncio.run(main())
" 2>/dev/null)

status_code2=$(echo "$response2" | python3 -c "import sys,json; print(json.load(sys.stdin)['status_code'])")

if [ "$status_code2" = "409" ]; then
    PASS=$((PASS+1))
    echo "PASS: second POST returns 409"
else
    FAIL=$((FAIL+1))
    echo "FAIL: expected 409, got: $status_code2"
fi

# Cleanup: stop/discard the pending row
docker exec hlh_api python3 -c "
import asyncio, httpx

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('$BASE/auth/login', json={'username':'admin','password':'admin'})
        cookies = r.cookies
        try:
            await c.delete('$BASE/chats/$chat_id/messages/$assistant_id/stop', cookies=cookies)
        except Exception:
            pass

asyncio.run(main())
" 2>/dev/null || true

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
