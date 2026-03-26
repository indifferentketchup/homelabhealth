# Cursor — Discord Tweak bot: Fetch persona from boolab

## Task
Wire Discord Tweak bot to fetch the Tweak persona from boolab instead of using hardcoded system prompt. On startup, fetch from boolab; on each message, use the fetched persona. Refresh hourly to catch any updates made in boolab.

---

## What's done
- ✅ Tweak bot running at `/opt/tweak/` with hardcoded personality
- ✅ Tweak persona seeded in boolab (from prompt 1)
- ❌ Discord bot doesn't fetch from boolab yet

---

## Implementation (2 steps)

### Step 1: Personality manager service (fetch + cache persona)

**File:** `/opt/tweak/backend/services/personality.py` (create new):

```python
import httpx
import json
import time
from typing import Dict, Optional

class PersonalityManager:
    """
    Fetch and cache Tweak persona from boolab.
    Periodically refresh to catch updates.
    """
    
    def __init__(
        self,
        boolab_url: str = "http://100.114.205.53:9300",
        refresh_interval: int = 3600  # 1 hour
    ):
        self.boolab_url = boolab_url
        self.refresh_interval = refresh_interval
        self.persona: Optional[Dict] = None
        self.last_refresh: float = 0
        self.fallback_persona = {
            "name": "Tweak",
            "emoji": "🤖",
            "system_prompt": (
                "You are Tweak, a pragmatic, snarky, science-first Discord bot. "
                "You respond directly, no fluff. "
                "Respond in a conversational Discord tone. "
                "You have access to knowledge from all your DAW sources and academic projects."
            ),
            "memory_blob": "{}",
            "mode": "booops"
        }
    
    async def fetch_persona(self) -> Dict:
        """
        Fetch Tweak persona from boolab.
        Falls back to hardcoded defaults if unreachable.
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                # Try to fetch Tweak persona for booops mode
                resp = await client.get(
                    f"{self.boolab_url}/api/personas/by-name/Tweak",
                    params={"mode": "booops"}
                )
                
                if resp.status_code == 200:
                    persona = resp.json()
                    print(f"✓ Fetched Tweak persona from boolab: {persona['name']} ({persona['emoji']})")
                    return persona
                else:
                    print(f"⚠ boolab returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"⚠ Error fetching Tweak persona from boolab: {e}")
        
        # Fallback
        print("→ Using fallback Tweak persona")
        return self.fallback_persona
    
    async def get_persona(self, force_refresh: bool = False) -> Dict:
        """
        Get current persona, refreshing from boolab if needed.
        
        Args:
            force_refresh: Force fetch even if cache is fresh
        
        Returns:
            Persona dict with name, emoji, system_prompt, memory_blob
        """
        now = time.time()
        
        # Refresh if: not loaded, forced, or interval exceeded
        if (
            force_refresh
            or self.persona is None
            or (now - self.last_refresh) > self.refresh_interval
        ):
            self.persona = await self.fetch_persona()
            self.last_refresh = now
        
        return self.persona
    
    async def get_system_prompt(self, force_refresh: bool = False) -> str:
        """Get Tweak's current system prompt."""
        persona = await self.get_persona(force_refresh=force_refresh)
        return persona.get('system_prompt', self.fallback_persona['system_prompt'])
    
    async def get_memory(self, force_refresh: bool = False) -> Dict:
        """
        Get Tweak's current memory blob.
        Parses as JSON if possible, returns dict.
        """
        persona = await self.get_persona(force_refresh=force_refresh)
        memory_str = persona.get('memory_blob', '{}')
        
        try:
            return json.loads(memory_str) if memory_str else {}
        except json.JSONDecodeError:
            return {}
    
    async def get_emoji(self, force_refresh: bool = False) -> str:
        """Get Tweak's emoji for display."""
        persona = await self.get_persona(force_refresh=force_refresh)
        return persona.get('emoji', '🤖')
```

---

### Step 2: Integrate into Discord bot

**File:** `/opt/tweak/bot.py` (modify main bot file):

```python
import discord
from discord.ext import commands, tasks
import asyncio
from backend.services.personality import PersonalityManager

# Initialize personality manager (global)
personality_manager = PersonalityManager(boolab_url="http://100.114.205.53:9300")

class TweakBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.personality_manager = personality_manager
        # Start background refresh task
        self.refresh_personality.start()
    
    @tasks.loop(hours=1)
    async def refresh_personality(self):
        """Refresh Tweak persona from boolab every hour."""
        print("🔄 Refreshing Tweak persona from boolab...")
        await self.personality_manager.get_persona(force_refresh=True)
    
    @refresh_personality.before_loop
    async def before_refresh(self):
        """Wait for bot to be ready before first refresh."""
        await self.bot.wait_ready()
    
    @commands.Cog.listener()
    async def on_ready(self):
        """On bot startup: fetch Tweak persona."""
        print(f"🤖 {self.bot.user} is online!")
        print("📥 Fetching Tweak persona from boolab...")
        await self.personality_manager.get_persona(force_refresh=True)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Handle messages: use Tweak persona from boolab.
        This replaces hardcoded logic with fetched persona.
        """
        if message.author == self.bot.user:
            return
        
        # Check if message is in a monitored channel or mentions bot
        if should_respond(message):  # Your existing logic
            # Get fresh system prompt from boolab
            system_prompt = await self.personality_manager.get_system_prompt()
            memory = await self.personality_manager.get_memory()
            
            # Build context (your existing logic)
            context = build_context(message, memory)  # Your function
            
            # Call Ollama with fetched system prompt
            response = await call_ollama(
                system_prompt=system_prompt,
                context=context,
                user_message=message.content,
                model="qwen3.5:9b"
            )
            
            # Stream response to Discord
            await stream_response(message, response)
    
    @commands.command()
    async def refresh(self, ctx):
        """Manual refresh: fetch latest Tweak persona from boolab."""
        await self.personality_manager.get_persona(force_refresh=True)
        emoji = await self.personality_manager.get_emoji()
        await ctx.send(f"{emoji} Persona refreshed from boolab!")

# In your main bot setup:
async def setup_bot():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
    await bot.add_cog(TweakBot(bot))
    return bot

# If using main.py:
async def main():
    bot = await setup_bot()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
```

**Alternative: If you have existing cogs structure**

**File:** `/opt/tweak/cogs/listener.py` (if this is where message handling is):

```python
from discord.ext import commands, tasks
from backend.services.personality import PersonalityManager

class ListenerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.personality_manager = PersonalityManager()
        self.refresh_personality.start()
    
    @tasks.loop(hours=1)
    async def refresh_personality(self):
        """Hourly refresh from boolab."""
        print("🔄 Refreshing Tweak persona...")
        await self.personality_manager.get_persona(force_refresh=True)
    
    @refresh_personality.before_loop
    async def before_refresh(self):
        await self.bot.wait_ready()
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Fetch on startup."""
        print("📥 Fetching Tweak persona from boolab...")
        await self.personality_manager.get_persona(force_refresh=True)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Use fetched persona in message handling."""
        if message.author == self.bot.user:
            return
        
        # Your existing logic, but use:
        system_prompt = await self.personality_manager.get_system_prompt()
        # Instead of hardcoded system prompt
        
        # ... rest of your message handling ...

async def setup(bot):
    await bot.add_cog(ListenerCog(bot))
```

---

### Step 3: Update environment / requirements

**File:** `/opt/tweak/requirements.txt` — ensure httpx is included:

```
discord.py==2.7.1
httpx==0.24.0
aiohttp==3.8.5
python-dotenv==1.0.0
# ... other deps ...
```

**Deploy:**
```bash
cd /opt/tweak
pip install -r requirements.txt

# Rebuild Docker image
docker compose build tweak
docker compose up -d
```

---

## Test workflow

### 1. Deploy changes
```bash
cd /opt/tweak

# Add personality.py service
# Modify bot.py or cogs/listener.py to use PersonalityManager
# Update requirements.txt

docker compose build tweak
docker compose up -d
```

### 2. Check logs on startup
```bash
docker logs -f tweak

# Expected output:
# 🤖 TweakBot#1234 is online!
# 📥 Fetching Tweak persona from boolab...
# ✓ Fetched Tweak persona from boolab: Tweak (🤖)
```

### 3. Test in Discord
```
User: @Tweak what's up?
Tweak: [responds with fetched system prompt + RAG context from all DAWs]
```

### 4. Test refresh
```
# In Discord (if you added !refresh command):
User: !refresh
Tweak: 🤖 Persona refreshed from boolab!

# Check logs:
docker logs -f tweak | grep "Refreshing"
# Should see refresh every hour automatically
```

### 5. Test persona sync
```
# In boolab web UI:
1. Edit Tweak persona emoji from 🤖 to 🤔
2. Save

# In Discord (or check logs):
Discord bot will pick up change on next message or within 1 hour
```

---

## Acceptance criteria
✅ PersonalityManager service fetches from boolab `/api/personas/by-name/Tweak`  
✅ Discord bot fetches on startup (log shows "Fetched Tweak persona")  
✅ System prompt used in message handling comes from fetched persona  
✅ Hourly refresh task runs (logs show "Refreshing...")  
✅ Fallback to hardcoded defaults if boolab unreachable  
✅ Manual `!refresh` command works (if implemented)  
✅ Changes in boolab persona appear in Discord within 1 hour  
✅ No errors in `docker logs tweak`  

---

## Notes
- **Refresh interval:** 1 hour (configurable in `PersonalityManager.__init__`)
- **Fallback:** Uses hardcoded defaults if boolab unreachable (graceful degradation)
- **Memory:** Not pushed back to boolab yet (bot stores locally in `data/memory.json`)
- **Mode awareness:** Fetches booops Tweak (general mode); could extend to 808notes later

---

## After this
Both prompts complete:
1. ✅ boolab Tweak persona with multi-DAW RAG
2. ✅ Discord bot fetches from boolab

**Result:** Edit Tweak in boolab → changes appear in Discord within 1 hour (or immediately on `!refresh`). Single source of truth.

**Next:** Wire tweak.boogaardmusic.com web UI to fetch + edit persona (fetch on load, save back to `/api/personas/{id}`).
