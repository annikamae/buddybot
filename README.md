# Buddy

**Buddy is a local-first cybersecurity chat sidekick** with a cute floating
knight avatar. Ask secure-coding questions, review code and documents, inspect
images with a local vision model, or request a read-only sample review of a
public GitHub repository.

Buddy is a Streamlit app. Text chat and analysis use Ollama models running on
your computer by default. Attachments are processed in the app process and go
only to the selected model provider. OpenAI cloud models are optional and
require an explicit opt-in. Public repository files are retrieved from GitHub’s
public API only when you request a review.

## What Buddy can do

| Feature | Behavior |
|---|---|
| Chat | Multiple conversations, saved locally between browser sessions and app restarts |
| Code review | Paste code or attach source/configuration files; request findings, fixes, or secure alternatives |
| Image review | Attach images; Buddy uses a detected local vision model such as `llava:latest` |
| Documents | Extract text from PDF and DOCX files; read common text/source formats |
| GitHub | Read-only review of eligible files from a public repository’s default branch; skip sensitive filenames and redact likely credential values |
| Website check | Make a passive HTTP `HEAD` request and inspect common response security headers |
| Knowledge base | Retrieve relevant excerpts from local `.txt` and `.md` files in `knowledge_base/` |
| Interface | Floating knight avatar, subtly animated conversation-specific stars, and optional soft click sounds |

## Processing limits

These are Buddy’s application limits, not security or completeness guarantees.

| Input | Current limit |
|---|---:|
| Typed prompt | 12,000 characters |
| Extracted text from attachments | 12,000 characters total per message |
| One attachment | 8 MiB |
| Total attachments in one message | 20 MiB |
| PDF extraction | First 30 pages |
| Image sent to vision model | Resized to at most 1,600 × 1,600 pixels |
| Public GitHub review | Up to 50 eligible files, 12,000 characters per file, and 100,000 characters total; files over 32 KB are skipped |
| Conversation context sent to the model | Most recent 10 messages |
| Website check | One passive `HEAD` request; no redirects followed |

Conversation history, including attached image data, is saved in a local SQLite
database under `%LOCALAPPDATA%\Buddy` on Windows (or the user’s home directory
on macOS/Linux). This data is not encrypted. Set `BUDDY_DATA_DIR` before
starting Buddy to use another local directory. The Chroma knowledge-base index
is stored alongside the database; neither is kept in the project or OneDrive
by default.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer
- [Ollama](https://ollama.com/) installed and running
- A text model installed in Ollama (the default is `llama3.2:latest`)
- `llava:latest` in Ollama if you want image analysis

## Install and run on Windows

Open PowerShell in the Buddy project folder, then run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull llama3.2:latest
ollama pull llava:latest
.\.venv\Scripts\python.exe -m streamlit run main.py
```

Image-model installation is optional. If you skip `ollama pull llava:latest`,
text chat and code reviews still work, but image questions will report that the
vision model is unavailable. The first knowledge-base load may download the
`all-MiniLM-L6-v2` embedding model.

Streamlit prints a local address—usually `http://localhost:8501`—to open in a
browser. Keep the terminal and Ollama running while you use Buddy. To stop the
app, focus the terminal and press **Ctrl+C**.

### If PowerShell says script activation is disabled

The commands above use the virtual environment’s Python executable directly;
they do not require activating the environment. If you prefer activation, run
`.\.venv\Scripts\Activate.ps1` in PowerShell first.

## Using Buddy

### Conversations

Use **New conversation** in the sidebar to start a separate chat. Select and
rename chats from the sidebar, clear the current chat, or delete it. Chats
persist locally across app restarts. Anyone with access to the Windows account
and its app-data files may be able to read them.

Buddy has a gently floating knight avatar and a slow, subtle starfield that
varies by conversation. Use **Soft interface sounds** in the sidebar to enable
or mute short, locally generated click chimes. Browsers may wait for your first
click before allowing sound. The animations respect your operating system's
reduced-motion preference.

### Code and file reviews

Type or paste code into the composer, or attach files using its attachment
control. Supported inputs include common source/configuration and text formats,
PDF, DOCX, and PNG/JPEG/WebP/GIF images. PDF and DOCX are converted to text;
image attachments are resized and sent to the local vision model. Buddy does
not execute uploaded files.

Ask Buddy to identify issues and provide a corrected version or a step-by-step
fix. Review the result carefully: model output can be incomplete or incorrect,
and generated code should be tested before use.

### Public GitHub repositories

In the sidebar, enter a repository’s main URL, such as
`https://github.com/owner/repository`, then choose **Fetch & review repository**.
Buddy reads the default branch at a pinned commit and reviews up to 50 eligible
source/configuration files within the limits above. If GitHub truncates its
recursive file listing, Buddy attempts a bounded directory-by-directory walk.
It skips common dependency/build directories and obvious secret/key filenames,
and redacts common credential assignments and private-key blocks before adding
retrieved content to a chat. Review the displayed file list and notes for
omissions, filtering, truncation, or redaction. Redaction is best-effort, not a
guarantee that every secret is detected. No GitHub token is requested or stored;
private repositories are not supported. Large repositories may exceed Buddy's
file, tree traversal, or text limits, so this is not a full repository audit.

### Website header checks

Enter a standalone `http://` or `https://` URL in chat and confirm in the
sidebar that you own the site or have permission to check it. Buddy inspects
common response headers with a passive `HEAD` request. It does not crawl,
download page content, follow redirects, or inspect source code. Requests are
limited to public hosts on standard HTTP(S) ports.

Missing headers are not by themselves proof of an exploitable vulnerability,
and present headers do not prove that a site is secure.

### Local security references

Add trusted `.txt` or `.md` security references to `knowledge_base/`, then
choose **Rebuild reference library** in the sidebar. The first build may
download the `all-MiniLM-L6-v2` embedding model. If the knowledge base fails to
load, direct chat and reviews remain available.

## Privacy and safe use

- `keys.env`, `.env` files, virtual environments, local databases, and generated
  indexes are excluded by `.gitignore`. Buddy does not load `.env` or
  `keys.env`; cloud credentials are read from the process environment only.
- Local Ollama is the default. OpenAI models are offered only when
  `OPENAI_API_KEY` is present in the process environment and **Allow OpenAI
  cloud requests** is explicitly enabled. Cloud mode sends prompts, code,
  repository samples, and attachments to OpenAI. Uncheck the option to return
  to local inference. Do not enable cloud use for sensitive content.
- Buddy is a single-user local app without authentication. Keep the server
  bound to `127.0.0.1`; Buddy refuses non-loopback Streamlit server addresses.
  The local database and image attachments are not encrypted.
- To enable cloud access, add `OPENAI_API_KEY` to your Windows user environment
  variables, then start a new terminal and restart Buddy. Do not put the key in
  this project, `.env.example`, or a command you intend to share.
- Do not submit passwords, API keys, access tokens, session cookies, or private
  customer data. Rotate any credentials accidentally exposed in a file.
- Repository content, uploaded files, images, and retrieved references are
  treated as untrusted input. Buddy is instructed not to follow embedded
  instructions from those materials.
- Use website checks and repository reviews only when authorized.
- Buddy is an assistant, not a penetration-testing tool, compliance
  certification, or substitute for human security review.

### If a secret was pushed to a public repository

1. Revoke or rotate every credential that may have been in the file. Deleting
   the file from the latest version does not make an exposed credential safe.
2. Keep local credentials out of Git. `.gitignore` is configured for `keys.env`
   and `.env` variants; verify with `git check-ignore -v keys.env`.
3. If the file is still tracked, remove it from Git's index without deleting
    the local copy: `git rm --cached -- keys.env`, then commit the removal.
4. Treat prior commits, forks, clones, caches, and pull-request references as
   potentially retaining the old contents. If history cleanup is needed,
   coordinate a repository-wide history rewrite and force-push carefully; this
   changes commit IDs and does not erase existing clones or cached copies.
5. Review the repository's other files and GitHub secret-scanning alerts for
   additional exposed credentials.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `ollama` is not recognized | Install Ollama, then open a new PowerShell window |
| Model is unavailable | Run `ollama pull llama3.2:latest`; for images also run `ollama pull llava:latest` |
| Buddy cannot connect to Ollama | Confirm Ollama is running locally, then retry |
| GitHub request fails | Check the URL is a public repository main page and retry later if rate-limited |
| Attachment is rejected | Check its file type and the size limits above |
| Reference library fails | Use **Rebuild reference library**; chat/review can still run without it |
| OpenAI is unavailable | Set `OPENAI_API_KEY` in the process environment, restart Buddy, and enable cloud requests |

## Development checks

Install the development tools and run the test suite and lint checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

GitHub Actions runs the same tests and lint checks on pushes and pull requests.

## Project files

- `main.py` — Streamlit interface and Buddy workflows
- `buddy_avatar.svg` — Buddy’s knight avatar
- `requirements.txt` — Python dependencies
- `knowledge_base/` — optional local security-reference documents
- `buddy_attachments.py`, `buddy_github.py`, `buddy_models.py`, `buddy_storage.py` — bounded input handling, model selection, and local persistence
- `tests/` — automated unit tests
