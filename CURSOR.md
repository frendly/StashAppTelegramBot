# StashApp Telegram Bot - Technical Reference

> **Compact version for Cursor AI**  
> Full docs: [CURSOR_FULL.md](CURSOR_FULL.md) | [README.md](README.md)  
> **⚠️ AI:** Always respond in Russian. Code comments must be in Russian.

---

## 📋 Quick Navigation

- **Architecture:** Modules, data flows, async patterns
- **Voting System:** Score, blacklist/whitelist, preferences
- **Performance:** Optimizations, caching, prefetch
- **Structure:** Files and their purpose

---

## Architecture

### Components

```
User ──→ Telegram Bot ──→ Handler ←── Scheduler (cron)
                           ↓   ↓
                 ┌─────────┴   └─────────┐
                 ↓                       ↓
           VotingManager            StashClient
                 ↓                       ↓
              Database              StashApp API
```

### Modules & Responsibilities

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `main.py` | Entry point, lifecycle | `Bot.initialize()`, `start()`, `stop()` |
| `telegram_handler.py` | Telegram commands | `random_command()`, `handle_vote_callback()`, `_send_random_photo()` |
| `voting.py` | Voting system | `process_vote()`, `get_filtering_lists()`, `get_preferences_summary()` |
| `stash_client.py` | GraphQL client | `get_random_image_weighted()`, `download_image()`, `update_image_rating()` |
| `database/` | SQLite DB (repositories) | `add_vote()`, `get_recent_image_ids()`, `update_performer_preference()` |
| `scheduler.py` | Cron scheduler | `start()`, `stop()` |
| `performance.py` | Profiling | `@timing_decorator`, `PerformanceTimer` |
| `config.py` | Configuration | `load_config()` → `BotConfig` |

### Data Flows

**Command /random:**
```
User → random_command() → Check auth → Get recent IDs (DB) 
→ Get all galleries from StashApp (cached) → Get gallery weights (Voting, cached)
→ Select gallery by weight (with coverage/freshness modifiers) → Get random image from selected gallery
→ Ensure gallery exists in DB (weight=1.0) → Check file_id cache (DB)
→ If cached: use file_id, else: Download thumbnail → Send to Telegram with 👍👎 buttons
→ Save file_id to DB → Save to DB → Prefetch next image (background)
→ Check exclusion threshold → Show exclusion button if threshold reached
```

**Voting:**
```
User clicks 👍/👎 → handle_vote_callback() → process_vote() (Voting)
→ update_image_rating() (StashClient) → add_vote() (DB)
→ update_performer_preference() (DB) → update_gallery_preference() (DB)
→ update_gallery_weight() (DB, k=0.2) → Invalidate weights cache
→ Check exclusion threshold → If reached: show exclusion button
→ Update button UI → Send result message → Auto-send next image if last
```

---

## Voting System

### Score Formula
```python
score = (positive_votes - negative_votes) / total_votes
# Range: -1.0 (only dislikes) to +1.0 (only likes)
```

### Filtering

- **Blacklist (score < 0):** Performers/galleries completely excluded
- **Whitelist (score > 0):** Prioritized, content not in whitelist skipped 50% of time

### Vote Processing

1. Update photo rating: 5 for 👍, 1 for 👎
2. Save vote to DB with context (gallery_id, performer_ids)
3. Update performer preferences
4. Update gallery preferences
5. Update gallery weight: +20% for 👍, -20% for 👎 (range: 0.1-10.0)
6. Auto-set gallery rating after 5+ votes (% positive → 1-5 stars)

### Gallery Weight System

- **Weight calculation:** Starts at 1.0, multiplies by 1.2 for 👍, 0.8 for 👎 (k=0.2)
- **Range:** 0.1 (minimum) to 10.0 (maximum)
- **Weighted selection:** Galleries with higher weights are more likely to be chosen
- **Auto-creation:** Galleries are automatically added to DB with weight 1.0 when first shown
- **Caching:** Weights cached for 60 seconds, invalidated after vote
- **Coverage penalty:** Weight reduced by up to 50% based on viewed/total images ratio
- **Freshness bonus:** Weight increased by up to 200% based on days since last selection
- **All galleries:** System considers all galleries from StashApp, not just those in DB

### Caching
- Filter lists cached for 60 seconds
- Invalidated after each vote
- Saves ~0.01-0.02 sec per request
- Gallery weights cached for 60 seconds
- Gallery list from StashApp cached for 1 hour

### Exclusion Thresholds
- **1 image gallery:** 1 negative vote → threshold reached
- **2 image gallery:** 1 negative vote → threshold reached
- **3+ images gallery:** ≥33.3% negative votes → threshold reached
- **Notification:** Shown once when threshold is reached
- **Exclusion button:** Appears when threshold is reached

**Details:** [`bot/voting.py`](bot/voting.py)

---

## Performance & Optimizations

### Key Optimizations

1. **Thumbnail instead of preview**
   - Size: ~15-30 KB vs ~50-100 KB
   - 3-5x faster download/upload
   - Priority: `thumbnail → preview → image`

2. **Next image prefetch**
   - Next photo loads in background after send
   - First `/random`: 2-4 sec
   - Subsequent: ~1 sec (from cache)
   - Auto cache validation

6. **File ID caching**
   - Telegram file_id saved to DB after first send
   - Reuse file_id for subsequent sends (no download needed)
   - Separate cache for thumbnail and high-quality images
   - Saves download time (~1-2 sec per image)

7. **Service channel preloading**
   - Optional: preload images to service channel for file_id
   - Runs every minute via scheduler
   - Preloads 2 high-quality images
   - Significantly speeds up scheduled sends

3. **Filter caching**
   - TTL: 60 seconds
   - Invalidation on vote
   - Saves DB queries

4. **GraphQL optimization**
   - 20 images instead of 50
   - Tags removed from query
   - ~60% less data

5. **HTTP timeout**
   - Total: 30 seconds
   - Connect: 10 seconds
   - Prevents hangs

### Target Metrics

**Good:** Total time < 3 sec  
**Acceptable:** 3-5 sec  
**Needs optimization:** > 5 sec

**Details:** [`bot/performance.py`](bot/performance.py), [`bot/telegram_handler.py:220-271`](bot/telegram_handler.py)

---

## Database

### Schema (key tables)

```sql
-- Sent photos history
sent_photos(id, image_id, sent_at, user_id, title)

-- User votes
votes(id, image_id, user_id, vote, voted_at, gallery_id, performer_ids)
UNIQUE(image_id, user_id)

-- Performer preferences
performer_preferences(performer_id, performer_name, positive_votes, 
                     negative_votes, total_votes, score, updated_at)

-- Gallery preferences
gallery_preferences(gallery_id, gallery_title, positive_votes,
                   negative_votes, total_votes, score, rating_set, updated_at,
                   weight, excluded, excluded_at, threshold_notification_shown,
                   total_images, images_count_updated_at)
```

### Indexes
- `idx_image_id` on `sent_photos(image_id)`
- `idx_sent_at` on `sent_photos(sent_at)`
- `idx_gallery_weight` on `gallery_preferences(weight)`

### Database Structure
- **Repository pattern:** Database split into repositories:
  - `base.py` - Base database class
  - `sent_photos.py` - Sent photos history
  - `votes.py` - Votes management
  - `preferences.py` - Performer/gallery preferences
  - `weights.py` - Gallery weights and statistics
  - `statistics.py` - Gallery statistics and image counts
- **Backward compatibility:** Main `Database` class delegates to repositories

**Details:** [`bot/database/`](bot/database/)

---

## Common Development Tasks

### Add New Command
1. In `telegram_handler.py`: create `new_command()` method
2. Register handler: `application.add_handler(CommandHandler("new", self.new_command))`
3. Update `/help` command with description

### Add DB Field
1. In appropriate repository (e.g., `database/preferences.py`): add to `CREATE TABLE` statement
2. Create method to work with field in repository
3. Add delegation in `database/__init__.py` if needed
4. Migration: users need to recreate DB or run migration script

### Change Filtering Logic
**File:** `bot/voting.py`  
**Method:** `get_filtering_lists()`  
**Used in:** `bot/stash_client.py:get_random_image_weighted()`

### Add Profiling
```python
from bot.performance import timing_decorator

@timing_decorator
async def my_function():
    pass
```

### Debug Prefetch Issues
**Check:** `telegram_handler.py:_prefetched_image` not None  
**Check:** `asyncio.Lock` initialized  
**Check:** Cache validation in `_send_random_photo()`

### Modify Vote Processing
**File:** `bot/voting.py`  
**Method:** `process_vote()`  
**Updates:** photo rating, votes table, performer/gallery preferences

---

## Troubleshooting

### Prefetch Not Working
- Check `_prefetched_image` is not None
- Verify `asyncio.Lock` initialized
- Check logs for "⚡ Using prefetched image"

### Filtering Not Applied
- Check filter cache (`_filtering_cache`)
- Verify `voting_manager` passed to `TelegramHandler`
- Check logs for "Using cached filtering lists"

### GraphQL Errors
- Verify StashApp API accessible
- Check query format in `stash_client.py:_execute_query()`
- Test connection: `await client.test_connection()`

### Slow Photo Sending
- Check Performance Report in logs
- See "Performance & Optimizations" section
- Verify thumbnail usage (not full image)

### Bot Not Responding
- Check user_id in `allowed_user_ids`
- Verify bot running: `docker-compose ps`
- Check logs: `docker-compose logs -f`

### Database Errors
- Check DB file permissions
- Verify path in config.yml
- Check disk space available

---

## Project Structure

```
bot/
├── main.py              # Entry point (~265 lines)
├── config.py            # Configuration (~125 lines)
├── database/            # SQLite DB (repository pattern)
│   ├── __init__.py      # Main Database class
│   ├── base.py          # Base database class
│   ├── sent_photos.py   # Sent photos repository
│   ├── votes.py         # Votes repository
│   ├── preferences.py   # Preferences repository
│   ├── weights.py       # Weights repository
│   └── statistics.py    # Statistics repository
├── stash_client.py      # GraphQL client (~1300 lines)
├── telegram_handler.py  # Telegram commands (~1425 lines)
├── scheduler.py         # Scheduler (~305 lines)
├── voting.py            # Voting system (~320 lines)
└── performance.py       # Profiling (~168 lines)

data/
└── sent_photos.db       # SQLite DB

docs/
├── DEPLOYMENT.md        # Deployment guide
└── GITHUB_REGISTRY.md   # CI/CD guide

config.yml               # Configuration (not in git)
docker-compose.yml       # Docker orchestration
requirements.txt         # Python dependencies
README.md                # Getting started
CHANGELOG.md             # Version history
```

**Total:** ~4000+ lines of code

---

## Important Patterns

### Async/await

```python
# Async context manager for StashClient
async with StashClient(api_url, api_key) as client:
    image = await client.get_random_image()

# Background tasks
asyncio.create_task(self._prefetch_next_image())
```

### Type hints + Dataclasses

```python
@dataclass
class StashImage:
    id: str
    title: str
    rating: int
    image_url: str
    gallery_id: Optional[str]
    performers: List[Dict[str, str]]

async def get_random_image(self, exclude_ids: List[str]) -> Optional[StashImage]:
```

### Error Handling

- **Retry logic:** Up to 5 attempts for StashApp API
- **Graceful degradation:** Bot continues on errors
- **Logging:** All errors logged with details
- **User notification:** Clear messages to user

### Performance Monitoring

```python
@timing_decorator  # Auto logging
async def some_function():
    pass

timer = PerformanceTimer("Operation")
timer.checkpoint("Stage 1")
# ... code ...
timer.checkpoint("Stage 2")
timer.report()  # Detailed report
```

### Database Patterns

```python
# Context manager for transactions
with sqlite3.connect(self.db_path) as conn:
    cursor = conn.cursor()
    cursor.execute(...)
    conn.commit()
```

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome and instructions |
| `/help` | Commands help and voting system info |
| `/random` | Random photo (with prefetch) |
| `/stats` | Sent photos statistics |
| `/preferences` | Top-5 favorite/disliked performers and galleries |

---

## Configuration

### Minimal config.yml

```yaml
telegram:
  bot_token: "YOUR_TOKEN"
  allowed_user_ids: [123456789]
  cache_channel_id: null  # Optional: Telegram channel ID for file_id caching

stash:
  api_url: "http://localhost:9999/graphql"
  api_key: ""  # Optional
  username: ""  # Optional: for Basic Auth
  password: ""  # Optional: for Basic Auth

scheduler:
  enabled: true
  cron: "0 10 * * *"  # Daily at 10:00
  timezone: "Europe/Moscow"

history:
  avoid_recent_days: 30

database:
  path: "/data/sent_photos.db"
```

**Cron examples:**
- `0 10 * * *` - daily at 10:00
- `0 9,21 * * *` - at 9:00 and 21:00
- `0 */3 * * *` - every 3 hours

---

## Dependencies

```txt
python-telegram-bot==20.7  # Telegram API
aiohttp==3.9.1            # Async HTTP
APScheduler==3.10.4       # Scheduler
PyYAML==6.0.1             # YAML
python-dotenv==1.0.0      # .env
```

---

## Quick Links

### For Development
- Full documentation: [CURSOR_FULL.md](CURSOR_FULL.md)
- Getting started: [README.md](README.md)
- Deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

### Key Files
- **Main logic:** [`bot/telegram_handler.py`](bot/telegram_handler.py)
- **Voting system:** [`bot/voting.py`](bot/voting.py)
- **StashApp API:** [`bot/stash_client.py`](bot/stash_client.py)
- **Database:** [`bot/database/`](bot/database/)

### External Resources
- [python-telegram-bot](https://docs.python-telegram-bot.org/)
- [StashApp](https://github.com/stashapp/stash)
- [APScheduler](https://apscheduler.readthedocs.io/)

---

## Security

- ✅ Whitelist auth by Telegram ID
- ✅ Tokens in environment variables
- ✅ Non-privileged user in Docker
- ✅ Read-only config mounting
- ✅ HTTP timeouts
- ✅ Rate limiting (2 sec between `/random`)

---

## Code Quality

- ✅ Type hints for all functions
- ✅ Docstrings for public methods
- ✅ PEP 8 compliance
- ✅ Async/await best practices
- ✅ Comprehensive error handling
- ✅ Performance monitoring built-in

---

**Version:** 1.1.0 (compact)  
**Date:** 2026-01-30  
**Status:** ✅ Production Ready  
**Last Updated:** 2026-01-30

*Compact version for efficient work in Cursor AI. Details → [CURSOR_FULL.md](CURSOR_FULL.md)*
