# gooaye-pipeline

股癌（Gooaye）Podcast 自動分析 Pipeline。定時偵測新集數、下載音訊、語音轉文字、AI 分析摘要，並透過 Telegram Bot 推播。

## 功能

- 自動偵測股癌 YouTube 頻道新集數
- 下載音訊並以 Faster Whisper 轉繁體中文逐字稿
- 使用 Grok API 進行結構化財經摘要分析
- 透過 Telegram Bot 推播分析結果
- 排程於每週三、六自動執行

## 系統需求

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- （選用）NVIDIA GPU — 有 GPU 時自動使用 `large-v3` 模型，無 GPU 則降為 `medium`

## 安裝

```bash
git clone git@github.com:meng-chiang/gooaye-pipeline.git
cd gooaye-pipeline
poetry install
```

## 設定

複製範本並填入金鑰：

```bash
cp .env.example .env
```

| 變數 | 說明 |
|------|------|
| `GROK_API_KEY` | xAI Grok API 金鑰 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（從 @BotFather 取得） |
| `TELEGRAM_CHAT_ID` | 推播目標的 Chat ID |
| `TELEGRAM_ALLOWED_USERS` | 允許使用 Bot 的 Telegram User ID，逗號分隔（留空不限制） |

其他設定（頻道 ID、Whisper 模型、排程時間等）在 `config/settings.yaml`。

## 使用

```bash
# 啟動 Bot + 排程（正式環境）
gooaye serve

# 只啟動 Telegram Bot（不含排程）
gooaye bot

# 手動執行完整 pipeline（處理最新一集）
gooaye run-pipeline

# 手動執行單一階段
gooaye run-stage download    --video-id <id>
gooaye run-stage transcribe  --video-id <id>
gooaye run-stage analyze     --video-id <id>
gooaye run-stage notify      --video-id <id>

# 檢查是否有新集數
gooaye check-new
```

## 專案結構

```
src/gooaye/
├── main.py        # CLI 入口
├── pipeline.py    # 完整 pipeline 流程
├── crawler.py     # YouTube RSS 爬取與音訊下載
├── transcriber.py # Faster Whisper 語音轉文字
├── analyzer.py    # Grok API 分析
├── notifier.py    # Telegram 推播
├── bot.py         # Telegram Bot 指令處理
├── scheduler.py   # APScheduler 排程
├── store.py       # SQLite 資料儲存
├── models.py      # Pydantic 資料模型
├── validator.py   # 輸入驗證
└── config.py      # 設定載入
```
