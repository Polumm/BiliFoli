# **BiliFoli**  
*Bilibili + Focus — a distraction-free way to browse your favourite Bilibili videos*

---

<table>
<tr><td>

### TL;DR

| :rocket: | Browse & search all your **Bili favourite folders** in one place |
| :tv:     | Sticky **mini-player** with Picture-in-Picture & **sleep-timer** |
| :inbox_tray: | Built-in **Mini-Dropbox** for quick file drops |
| :shield: | Local **HTTP & WebSocket proxy** (circumvents some region blocks) |
| :lock:   | Simple password login + signed server-side sessions            |
| :chart_with_upwards_trend: | Clean logging & configurable environment |
| :zap:    | Powered by **FastAPI + HTMX/Tailwind** — hot-reload out of the box |

</td></tr>
</table>

---

## 1. Features

| Area | What you get |
|------|--------------|
| **Folder explorer** | Infinite scroll, stats widgets, smart retries on API errors |
| **Video playback**  | HLS/MP4 direct-stream, PiP button, *⏰ Sleep timer* that pauses the player (and exits PiP) after N minutes |
| **Mini-Dropbox**    | Upload / download / delete files inside `./dropbox` with drag-&-drop UX |
| **Proxy layer**     | `/proxy/**` catch-all route fan-outs requests to any connected *proxy-client* via WebSocket and streams the first reply (not used for bilibili) |
| **Security**        | Secrets stored via env-vars, `SessionMiddleware` cookies, optional HTTPS proxy front-end |
| **Dev ergonomics**  | Structured logging (`logging_config.py`), hot-reload (`uvicorn --reload`), typed core helpers |

---

## 2. Getting Started

### 2.1 Prerequisites

| Requirement | Tested on |
|-------------|-----------|
| **Python**  | 3.10 – 3.12 |
| **pip / venv** | any recent version |
| **Browser** | Chrome > 93, Edge > 93, Safari 16, Firefox 117 |

### 2.2 Clone & install

```bash
git clone https://github.com/your-org/bilifoli.git
cd bilifoli
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
````

### 2.3 Environment variables

| Variable         | Required? | Description                                                         |
| ---------------- | --------- | ------------------------------------------------------------------- |
| `SESSDATA`       | ✅         | Your Bilibili cookie — **must be fresh**                            |
| `UP_MID`         | ✅         | UID of the Bilibili account that owns the favourite folders         |
| `BILI_JCT`       | ⏲️        | CSRF token — only needed for certain write calls                    |
| `LOGIN_SECRET`   | ✅         | Password for the `/login` page                                      |
| `SESSION_SECRET` | 🔒        | Server-side session signing key (defaults to “change-this-in-prod”) |

You can place them in a `.env` file or export them in your shell before launch.

### 2.4 Run

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000), log in with your `LOGIN_SECRET`, and enjoy!

<details>
<summary>Docker one-liner</summary>

```bash
docker build -t bilifoli .
docker run -p 8000:8000 \
  -e SESSDATA=xxx -e UP_MID=yyy -e LOGIN_SECRET=mysecret \
  bilifoli
```

</details>

---

## 3. Project Layout

```
.
├── app.py                # FastAPI application entry-point
├── proxy.py              # HTTP/WS proxy fan-out logic (not used for bilibili)
├── frontend_router.py    # UI routes & API endpoints
├── dropbox.py            # Mini Dropbox service
├── core/
│   ├── bilibili_api.py   # Thin async wrapper around Bilibili endpoints
│   ├── config.py         # Settings helper
│   └── templates.py      # Global Jinja environment & filters
├── templates/            # Jinja2 HTML templates
│   └── components/       # Mini-player, cards, …
├── static/               # JS/CSS assets (auto-created)
├── requirements.txt
└── README.md             # ← you are here
```

---

## 4. Sleep-Timer ⏰

* Click **Start** under the mini-player, choose minutes (1-180).
* A live `mm:ss` countdown appears.
* When it hits 00:00 the video pauses, PiP exits, and the timer clears.
* **Cancel** anytime to keep watching.

No cookies, no storage — pure in-memory JavaScript (see
`templates/components/mini_player.html`).

---

## 5. Extending BiliFoli

| Idea                   | Where to start                                                       |
| ---------------------- | -------------------------------------------------------------------- |
| 🎨 Add dark mode       | `templates/base.html` and Tailwind `@media (prefers-color-scheme)`   |
| 📱 PWA / mobile icon   | `static/manifest.json` + service-worker                              |
| 📊 Extra stats         | `frontend_router.index` → add new widgets                            |
| 🧩 Custom proxy client | Implement a WebSocket that listens to `/ws/backend` and answers JSON |

Pull requests & discussions welcome! Please open an issue first for major changes.

---

## 6. Troubleshooting

| Symptom                              | Checklist                                                        |
| ------------------------------------ | ---------------------------------------------------------------- |
| **Empty folder list**                | Is `SESSDATA` still valid? Region-locked?                        |
| **HTTP 504 on `/proxy/*`**           | No proxy-clients connected; check browser console                |
| **“Failed to start video” alert**    | Bilibili blocked the quality level; try again (auto-retry ×2)    |
| **Sleep-timer didn’t stop playback** | Some browsers throttle `setTimeout` in background tabs → use PiP |

---

## 7. Credits

* **Bilibili** for the public APIs
* **FastAPI**, **Jinja2**, **Tailwind CSS**
* Icons from [Font Awesome 6](https://fontawesome.com/)

> *Made with ☕ and a healthy dose of Focus.*

```
