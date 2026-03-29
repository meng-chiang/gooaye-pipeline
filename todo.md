# TODO List

## Phase 1: Project Scaffold
- [ ] `poetry init` + `pyproject.toml` with all dependencies
- [ ] Create directory structure (`src/gooaye/`, `config/`, `data/`, `tests/`)
- [ ] `.env.example` (GROK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_USERS)
- [ ] `.gitignore` (data/, logs/, .env, __pycache__, *.db, whisper model cache)
- [ ] `config/settings.yaml` with defaults + prompt template + Q&A markers
- [ ] `config.py` — pydantic-settings loader (YAML + env)
- [ ] `models.py` — Episode, Transcript, Analysis dataclasses

## Phase 2: State Management (`store.py`)
- [ ] SQLite DB 初始化 (WAL mode)
- [ ] `episodes` table: video_id, title, publish_date, status, analysis_result, created_at
- [ ] `rate_limits` table: user_id, last_request_at
- [ ] CRUD methods: add_episode, get_episode, is_processed, update_status
- [ ] Cache lookup: 相同 video_id 直接返回已有結果

## Phase 3: Input Validation (`validator.py`)
- [ ] YouTube URL 正則白名單 (youtube.com/watch, youtu.be/, youtube.com/shorts/)
- [ ] 從 URL 提取 video_id → 重組為 canonical URL
- [ ] Reject 非 YouTube domain

## Phase 4: YouTube Crawler (`crawler.py`)
- [ ] `check_new_videos()` — RSS feed (`/feeds/videos.xml?channel_id=...`) + filter against SQLite
- [ ] `download_audio(video_id)` — yt-dlp extract audio to mp3
- [ ] `download_audio_by_url(url)` — 先經 `validator.py` → 提取 video_id → download

## Phase 5: Transcription (`transcriber.py`)
- [ ] GPU auto-detect → 選擇 model size (large-v3 float16 / medium int8)
- [ ] `transcribe(audio_path)` — faster-whisper with `language="zh"`, `initial_prompt="以下是繁體中文的內容。"`
- [ ] Segment concatenation → save to `data/transcripts/{video_id}.txt`
- [ ] `opencc` 簡轉繁 post-processing（必要，非 optional）
- [ ] Bot 模式下 model 常駐記憶體（singleton pattern）

## Phase 6: Grok Analysis (`analyzer.py`)
- [ ] `trim_qa_section(text)` — keyword scan + 位置驗證 (>40%) + 無 Q&A 則使用全文
- [ ] Token counting — `tiktoken` 計算 token 數
- [ ] Chunking — 超過 context window 時按段落邊界切分 (~8K tokens/chunk)
- [ ] `analyze(transcript)` — openai SDK with Grok base_url, chunk→summarize→merge
- [ ] Save to `data/analyses/{video_id}.json`

## Phase 7: Telegram Notification (`notifier.py`)
- [ ] `send_message(chat_id, text)` — Telegram sendMessage API
- [ ] `send_progress(chat_id, stage)` — 進度回報（每階段更新）
- [ ] 4096-char limit handling — split at paragraph boundaries
- [ ] Format: title, date, summary, key topics
- [ ] Error notification — 發送到觸發 pipeline 的同一 chat

## Phase 8: Telegram Bot Interactive Mode (`bot.py`)
- [ ] `python-telegram-bot` Application setup with polling
- [ ] `/url` CommandHandler — validator 驗證 → SQLite 快取查詢 → pipeline 觸發
- [ ] 進度回報 — 每階段完成時更新 Telegram 訊息
- [ ] `/status`, `/latest`, `/help` 指令 handlers
- [ ] Rate limiting — per-user cooldown (SQLite `rate_limits` table)
- [ ] 並行控制 — asyncio.Semaphore 限制同時 1 個 pipeline
- [ ] 安全性 — `TELEGRAM_ALLOWED_USERS` user ID 白名單過濾

## Phase 9: Scheduler (`scheduler.py`)
- [ ] `APScheduler` setup — CronTrigger for Wed/Sat (configurable)
- [ ] Job: `check_new_videos()` → for each new → `run_pipeline()`
- [ ] `misfire_grace_time` — missed job 補執行
- [ ] Timezone handling — Asia/Taipei

## Phase 10: Pipeline Orchestrator (`pipeline.py` + `main.py`)
- [ ] `pipeline.py` — `run_pipeline(video_id_or_url, progress_callback=None)` 共用邏輯
- [ ] Pipeline flow: validate → cache check → download → transcribe → analyze → notify → cleanup → mark processed
- [ ] `main.py` CLI subcommands:
  - `run-pipeline` — 手動觸發單次 pipeline
  - `run-stage <stage> --video-id <id>` — 單獨執行某階段
  - `check-new` — 檢查新影片
  - `bot` — 僅啟動 Telegram Bot
  - `serve` — 啟動 Bot + Scheduler（主要 production 模式）
- [ ] structlog logging (JSON to file, human to stderr)
- [ ] Per-stage error handling + retry (exponential backoff)
- [ ] Data cleanup — 保留最近 N 筆，刪除舊檔

## Phase 11: Deployment (WSL2)
- [ ] `sudo apt install ffmpeg`
- [ ] `poetry install` + pre-download whisper model
- [ ] 啟動方式: `tmux` session 或 Windows Task Scheduler (`wsl -e ...`)
- [ ] End-to-end test with real episode
- [ ] 驗證 scheduler 自動觸發 + bot `/url` 互動

## Verification
1. `poetry run python -m gooaye.main check-new` — 確認 RSS 偵測新影片
2. `poetry run python -m gooaye.main run-stage download --video-id <id>` — 確認音訊下載
3. `poetry run python -m gooaye.main run-stage transcribe --video-id <id>` — 確認語音轉文字 + 繁中
4. `poetry run python -m gooaye.main run-stage analyze --video-id <id>` — 確認 Grok 分析
5. `poetry run python -m gooaye.main run-stage notify --video-id <id>` — 確認 Telegram 推送
6. `poetry run python -m gooaye.main run-pipeline` — 完整 pipeline 端到端測試
7. `poetry run python -m gooaye.main bot` — Bot 互動測試 (`/url`, `/status`, `/latest`)
8. `poetry run python -m gooaye.main serve` — 驗證 Bot + Scheduler 同時運行
