# Gooaye 股癌 Podcast 自動分析 Pipeline

## Context

建立一個自動化 pipeline，每週三和六爬取股癌 YouTube 頻道最新 podcast，下載音訊後語音轉文字，再透過 Grok API 進行內容分析（忽略 Q&A 段落），最後將結果透過 Telegram Bot 推送到指定對話框。

**執行環境**: Windows WSL2 Ubuntu（機器可能重啟，不依賴 system cron）

**雙模式運作**:
1. **排程模式**: Python 內建排程器（`APScheduler`）每週三/六自動偵測新集數並處理
2. **互動模式**: Telegram Bot 長駐 polling，使用者可透過 `/url` 指令傳送 YouTube URL 觸發即時分析

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    main.py (CLI)                      │
│  Commands: run-pipeline | run-stage | bot | serve     │
└──────┬──────────┬──────────────────┬─────────────────┘
       │          │                  │
┌──────▼──────┐   │         ┌───────▼────────┐
│ serve Mode  │   │         │ bot Mode       │
│ APScheduler │   │         │ (long-running) │
│ Wed/Sat auto│   │         │ Telegram poll  │
│ + Bot embed │   │         │ /url command   │
└──────┬──────┘   │         └───────┬────────┘
       │          │                 │
       └──────────┴────────┬────────┘
                           │ video_id or URL
                           v
   ┌──────────────────────────────────────┐
   │         pipeline.py (orchestrator)    │
   │  validate → download → STT → analyze │
   │  → notify → cleanup                  │
   └──────┬───────────────────────────────┘
          │
          ├──> crawler.py    YouTube RSS/API + yt-dlp download
          ├──> transcriber.py  faster-whisper (auto model select) + opencc
          ├──> analyzer.py   trim Q&A + Grok API (chunked)
          ├──> notifier.py   Telegram sendMessage
          └──> store.py      SQLite state + file locking
```

## Directory Structure

```
youtube-gooaye-analysis/
├── pyproject.toml
├── .env.example
├── .gitignore
├── config/
│   └── settings.yaml            # channel ID, prompt template, Q&A markers
├── src/gooaye/
│   ├── __init__.py
│   ├── main.py                  # CLI entry: run-pipeline | run-stage | bot | serve
│   ├── pipeline.py              # Pipeline orchestrator (shared by scheduler & bot)
│   ├── crawler.py               # YouTube RSS + API + yt-dlp audio download
│   ├── transcriber.py           # faster-whisper STT + opencc
│   ├── analyzer.py              # Q&A trimming + Grok API (chunked)
│   ├── notifier.py              # Telegram sendMessage (push results)
│   ├── bot.py                   # Telegram Bot polling (interactive interface)
│   ├── scheduler.py             # APScheduler setup (Wed/Sat trigger)
│   ├── store.py                 # SQLite state management (replace processed.json)
│   ├── validator.py             # URL validation + input sanitization
│   ├── config.py                # pydantic-settings config loader
│   └── models.py                # dataclasses (Episode, Transcript, Analysis)
├── data/                        # runtime data (gitignored)
│   ├── audio/
│   ├── transcripts/
│   ├── analyses/
│   └── gooaye.db               # SQLite state DB
├── logs/                        # gitignored
└── tests/
    ├── test_crawler.py
    ├── test_transcriber.py
    ├── test_analyzer.py
    ├── test_validator.py
    └── test_notifier.py
```

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `yt-dlp` | Audio download |
| `faster-whisper` | STT (CTranslate2, ~4x faster than vanilla Whisper) |
| `opencc-python-reimplemented` | 簡體→繁體中文轉換（必要） |
| `openai` | Grok API client (base_url swap to `https://api.x.ai/v1`) |
| `python-telegram-bot` | Telegram Bot framework (polling + handlers) |
| `apscheduler` | Python-based scheduler (取代 system cron) |
| `pydantic-settings` | Config validation |
| `pyyaml` | YAML config parsing |
| `structlog` | Structured logging |
| `httpx` | RSS feed fetching + lightweight HTTP |
| System: `ffmpeg` | Required by yt-dlp |

**移除**: `google-api-python-client` — 改用 RSS feed 偵測新影片，節省 API 配額

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| STT | `faster-whisper` auto-select model | 有 GPU → `large-v3` float16；無 GPU → `medium` int8 (自動偵測) |
| 繁中處理 | `initial_prompt` hint + **`opencc` 必要** post-process | Whisper 經常輸出簡中，`initial_prompt` 效果有限 |
| Q&A 偵測 | Keyword markers + ratio fallback + **confidence check** | 若無 Q&A marker 且內容結構不符，使用全文 |
| Scheduling | **`APScheduler`** (Python module) | WSL 重啟後 cron 不自動恢復；APScheduler 隨 bot process 一起啟動 |
| 新集偵測 | **RSS feed** (`/feeds/videos.xml?channel_id=...`) | 免費、無配額限制、即時性足夠 |
| Telegram | `python-telegram-bot` | 需要 Bot polling + handlers 支援互動模式 |
| Grok model | `grok-4-1-fast-non-reasoning` | Summarization doesn't need reasoning |
| State | **SQLite** (取代 `processed.json`) | 支援 concurrent access、file locking、query 能力 |

## WSL2 Ubuntu 環境考量

- **ffmpeg 安裝**: `sudo apt install ffmpeg`
- **無 system cron 依賴**: 使用 `APScheduler`，隨 Python process 啟動。`serve` 指令同時啟動 scheduler + bot
- **GPU (optional)**: WSL2 支援 CUDA passthrough，`transcriber.py` 自動偵測 GPU 並選擇模型大小
- **路徑**: 所有路徑使用 Linux 格式，data 目錄放在 WSL filesystem（非 `/mnt/c`）以獲得較好 I/O 效能
- **whisper model cache**: 預設存放在 `~/.cache/huggingface/`，首次執行需下載 (~1.5GB medium / ~3GB large-v3)
- **Process 存活**: 建議用 `tmux`/`screen` session 或 Windows Task Scheduler 在 WSL 啟動時執行 `wsl -e poetry run python -m gooaye.main serve`

## Security

### URL 驗證 (`validator.py`)
- **正則白名單**: 僅接受 `youtube.com/watch?v=`、`youtu.be/`、`youtube.com/shorts/` 格式
- **Sanitize**: strip query params (保留 `v=`)，reject 任何非 YouTube domain
- **yt-dlp 安全**: 傳入前先提取 video_id，用 `https://www.youtube.com/watch?v={video_id}` 重組 URL

### Bot 安全
- **雙層過濾**: `TELEGRAM_ALLOWED_USERS` (user ID list) + `TELEGRAM_CHAT_ID`
- **Rate limiting**: 每個 user 每 10 分鐘最多 1 次 `/url` 請求（cooldown in SQLite）
- **並行控制**: 全域最多 1 個 pipeline 同時執行

### State 安全
- **SQLite WAL mode**: 支援 concurrent read，單一 writer lock 避免 race condition
- **API Key 管理**: YouTube API key（如仍需要）在 Google Cloud Console 設定 IP 限制

## Telegram Bot 互動模式

### Bot 指令

| 指令 | 說明 |
|------|------|
| `/url <YouTube URL>` | 觸發即時下載＋分析，Bot 回覆進度更新 |
| `/status` | 查看目前處理狀態 |
| `/latest` | 取得最近一次分析結果 |
| `/help` | 顯示使用說明 |

### 互動流程

```
User sends: /url https://www.youtube.com/watch?v=xxxxx
  Bot: "⏳ 開始處理... 下載音訊中"
  Bot: "🎙️ 語音轉文字中（約需 5-10 分鐘）"
  Bot: "🔍 AI 分析中..."
  Bot: "✅ 分析完成！\n\n[formatted analysis result]"
```

若未帶 URL 或格式錯誤：
```
User sends: /url
  Bot: "請提供 YouTube URL，例如: /url https://www.youtube.com/watch?v=xxxxx"
```

快取命中：
```
User sends: /url https://www.youtube.com/watch?v=already_processed
  Bot: "📋 此影片已有分析結果（2026-03-20），直接返回：\n\n[cached result]"
```

### 實作方式

- 使用 `python-telegram-bot` 的 `Application` + polling mode
- `/url` 用 `CommandHandler("url", ...)` 處理，解析 args 取得 URL
- URL 先經 `validator.py` 驗證 → 查 SQLite 快取 → 無快取才執行 pipeline
- 長時間任務用 `asyncio` 在背景執行，避免 blocking bot polling
- Rate limiting: per-user cooldown 記錄在 SQLite
- 僅允許 `TELEGRAM_ALLOWED_USERS` 白名單互動

## Performance

### STT 自動降級

```python
# transcriber.py pseudo logic
if torch.cuda.is_available():
    model_size = "large-v3"
    compute_type = "float16"
else:
    model_size = "medium"
    compute_type = "int8"
```

- `medium` model CPU 模式下約 10-15 分鐘/小時音訊（比 `large-v3` 的 20-40 分鐘快一倍）
- Bot 模式下 **model 常駐記憶體**，避免每次請求重新載入（cold start ~10-30s）

### 快取策略
- 相同 `video_id` 重複請求 → 直接返回 SQLite 中已存的分析結果
- 音訊/轉錄檔以 `video_id` 為 key，pipeline 開始前先檢查是否已有中間產物

### 資料清理
- **自動清理**: 保留最近 `N` 筆（預設 20）的 audio/transcript/analysis 檔案
- **清理時機**: 每次 pipeline 完成後觸發
- **設定**: `config/settings.yaml` 中 `data.max_keep_episodes: 20`

### Grok API Token 管理
- Podcast ~1-2hr → ~15K-30K tokens 逐字稿
- **Chunking 策略**: 依段落邊界切分為 ~8K token chunks → 各 chunk 分別摘要 → 最後合併摘要
- 使用 `tiktoken` 計算 token 數，確保不超過 model context window

## Q&A 偵測策略

1. **Keyword scan**: 搜尋 `Q&A`, `提問`, `聽眾問題`, `來看一下問題`, `觀眾提問` 等 markers
2. **位置驗證**: marker 必須出現在文本 **後半段 (>40%)** 才視為有效 Q&A 分界點
3. **無 Q&A fallback**: 若無 marker 命中，**使用全文**（而非 60% ratio 截斷），避免誤切正文
4. **Config 可調**: markers 和位置閾值皆可在 `settings.yaml` 中自訂

## Error Handling

| 階段 | 錯誤處理 | 通知 |
|------|---------|------|
| Download | retry 3 次 (exponential backoff) → fail | Telegram 通知 initiator + log |
| STT | retry 1 次 → fail（STT 失敗通常非暫時性） | Telegram 通知 initiator + log |
| Grok API | retry 3 次 (exponential backoff) → fail | Telegram 通知 initiator + log |
| Telegram send | retry 3 次 → log only（避免遞迴通知） | log only |
| Scheduler | missed job → next trigger 補執行 (`misfire_grace_time`) | log |

**錯誤通知**: 所有錯誤通知發送到觸發該 pipeline 的同一 chat（bot 模式下為使用者，scheduler 模式下為 `TELEGRAM_CHAT_ID`）

## Configuration

- **Secrets** (`.env`):
  - `GROK_API_KEY` — Grok API
  - `TELEGRAM_BOT_TOKEN` — Telegram Bot
  - `TELEGRAM_CHAT_ID` — 排程模式通知目標
  - `TELEGRAM_ALLOWED_USERS` — 允許互動的 user ID list (comma-separated)
- **Settings** (`config/settings.yaml`):
  - `youtube.channel_id` — 股癌頻道 ID (`UC23rnlQU_qE3cec9x709peA`)
  - `whisper.*` — model 設定 (auto/manual)
  - `analyzer.prompt_template` — Grok 分析 prompt
  - `analyzer.qa_markers` — Q&A 關鍵字列表
  - `analyzer.qa_min_position` — Q&A marker 最低位置 (0.4)
  - `data.max_keep_episodes` — 保留集數 (20)
  - `bot.cooldown_seconds` — rate limit cooldown (600)
  - `scheduler.trigger_days` — 排程日 (wed, sat)
  - `scheduler.trigger_hour` — 排程時間 (14, UTC+8)
- **State**: `data/gooaye.db` (SQLite) — 已處理影片、快取結果、rate limit 記錄
