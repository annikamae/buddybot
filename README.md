# Buddy

**Buddy is a local-first cybersecurity chat sidekick** with a cute floating
knight avatar. Ask secure-coding questions, review code and documents, inspect
images with a local vision model, or request a read-only sample review of a
public GitHub repository.

Buddy is a Streamlit app. Text chat and analysis use Ollama models running on
your computer. Attachments are processed in the app process and are not
intentionally uploaded to an AI cloud service. Public repository files are
retrieved from GitHub’s public API when you request a review.

## What Buddy can do

| Feature | Behavior |
|---|---|
| Chat | Separate conversations within the current Streamlit browser session |
| Code review | Paste code or attach source/configuration files; request findings, fixes, or secure alternatives |
| Image review | Attach images; Buddy uses the local `llava:latest` vision model |
| Documents | Extract text from PDF and DOCX files; read common text/source formats |
| GitHub | Fetch a bounded sample of eligible files from a public repository’s default branch |
| Website check | Make a passive HTTP `HEAD` request and inspect common response security headers |
| Knowledge base | Retrieve relevant excerpts from local `.txt` and `.md` files in `knowledge_base/` |

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
| Public GitHub sample | Up to 12 eligible files, 5,000 characters per file, and 30,000 sampled characters total |
| Conversation context sent to the model | Most recent 10 messages |
| Website check | One passive `HEAD` request; no redirects followed |

Conversation history is held in Streamlit session state. It is not saved as a
local chat archive and may disappear when the browser session ends or the app
restarts. The Chroma knowledge-base index is saved under `chroma_db/`.

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
rename chats from the sidebar, or delete the selected chat. Chats are isolated
in the current browser session and are not persisted to disk.

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
Buddy reads the default branch and samples up to 12 small source/configuration
files. It skips common dependency/build directories and obvious secret/key
filenames. No GitHub token is requested or stored; private repositories are not
supported. A sample review is not a full repository audit, and files outside the
sample may contain additional issues.

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

- Chat and code-review inference run through the local Ollama service by
  default. The optional GitHub feature retrieves public repository files from
  GitHub when explicitly requested.
- Do not submit passwords, API keys, access tokens, session cookies, or private
  customer data. Rotate any credentials accidentally exposed in a file.
- Repository content, uploaded files, images, and retrieved references are
  treated as untrusted input. Buddy is instructed not to follow embedded
  instructions from those materials.
- Use website checks and repository reviews only when authorized.
- Buddy is an assistant, not a penetration-testing tool, compliance
  certification, or substitute for human security review.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `ollama` is not recognized | Install Ollama, then open a new PowerShell window |
| Model is unavailable | Run `ollama pull llama3.2:latest`; for images also run `ollama pull llava:latest` |
| Buddy cannot connect to Ollama | Confirm Ollama is running locally, then retry |
| GitHub request fails | Check the URL is a public repository main page and retry later if rate-limited |
| Attachment is rejected | Check its file type and the size limits above |
| Reference library fails | Use **Rebuild reference library**; chat/review can still run without it |

## Project files

- `main.py` — Streamlit interface and Buddy workflows
- `buddy_avatar.svg` — Buddy’s knight avatar
- `requirements.txt` — Python dependencies
- `knowledge_base/` — optional local security-reference documents
- `chroma_db/` — local vector index generated from those references
