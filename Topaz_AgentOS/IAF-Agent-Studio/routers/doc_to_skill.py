"""
Doc-to-Skill Pipeline — convert business documents into SKILL.md definitions.

SCOPE: This generator produces ONLY a SKILL.md (behaviour + workflow). Context
files (reference data, lookup tables, policies) are NOT generated here — those
are owned by domain SMEs and added separately via the Studio Knowledge tab.
This separation prevents hallucinated context with invented filenames and
keeps the quality bar high for actual business reference material.

Endpoints:
  POST /api/skills/from-document      — extract + LLM-generate SKILL.md only
  POST /api/skills/save-context-files — kept for compatibility; receives empty
                                        list from this flow but still works if
                                        called from other paths
  GET  /api/skill-creator/templates   — starter templates for manual creation
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.config import DATA_ROOT, TENANT_ID
from shared.file_utils import atomic_write_text

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_TOTAL_CHARS  = 20_000
_MAX_SINGLE_CHARS = 12_000

_MARKITDOWN_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xlsm", ".xls"}
_TEXT_EXTS       = {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
_VIDEO_EXTS      = {".mp4", ".mov", ".avi", ".mkv"}
_AUDIO_EXTS      = {".mp3", ".wav", ".m4a", ".ogg"}
_VSDX_EXTS       = {".vsdx"}
_SUPPORTED_EXTS  = _MARKITDOWN_EXTS | _TEXT_EXTS | _VIDEO_EXTS | _AUDIO_EXTS | _VSDX_EXTS


def _clean_nan(text: str) -> str:
    """Remove NaN artefacts produced by pandas/markitdown when converting Excel."""
    text = re.sub(r'\| NaN', '|', text)
    text = re.sub(r'NaN \|', '|', text)
    text = re.sub(r'\bNaN\b', '', text)
    text = re.sub(r'\| +\|', '| |', text)
    lines = []
    for line in text.splitlines():
        stripped = re.sub(r'[\|\s]', '', line)
        if stripped or not line.strip().startswith('|'):
            lines.append(line)
    return "\n".join(lines)


def _extract_with_markitdown(file_bytes: bytes, ext: str, filename: str) -> str:
    """Convert office/PDF bytes to markdown text via markitdown."""
    try:
        from markitdown import MarkItDown
        converter = MarkItDown()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            result = converter.convert(tmp_path)
            text = result.text_content or ""
            if ext in (".xlsx", ".xlsm", ".xls"):
                text = _clean_nan(text)
            return text
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except ImportError:
        return f"[markitdown not installed — cannot extract {filename}]"
    except Exception as e:
        return f"[markitdown error on {filename}: {e}]"


def _extract_vsdx(file_bytes: bytes, filename: str) -> str:
    """Extract shape text from Visio .vsdx (ZIP-based XML)."""
    stem = Path(filename).stem
    lines = [f"# {stem}", ""]
    try:
        with tempfile.NamedTemporaryFile(suffix=".vsdx", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path, "r") as z:
                names = z.namelist()
                page_files = sorted([n for n in names if re.match(r"visio/pages/page\d+\.xml", n)])
                if not page_files:
                    return f"# {stem}\n\n_No page content found._\n"
                for page_file in page_files:
                    page_num = re.search(r"page(\d+)", page_file).group(1)
                    lines.append(f"## Page {page_num}")
                    xml = z.read(page_file).decode("utf-8", errors="replace")
                    texts = re.findall(r"<Text>(.*?)</Text>", xml, re.DOTALL)
                    cleaned, seen = [], set()
                    for t in texts:
                        t = re.sub(r"<[^>]+>", " ", t).strip()
                        t = re.sub(r"\s+", " ", t)
                        if t and len(t) > 1 and t not in seen:
                            seen.add(t)
                            cleaned.append(t)
                    if cleaned:
                        lines.append("\n**Shape Labels:**")
                        lines.extend(f"- {t}" for t in cleaned)
                    else:
                        lines.append("_No shape text found._")
                    lines.append("")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        return f"# {stem}\n\n_VSDX parse error: {e}_\n"
    return "\n".join(lines)


_whisper_model_cache = {}

def _transcribe_audio_video(file_bytes: bytes, ext: str, filename: str) -> str:
    """Transcribe audio/video using ffmpeg + openai-whisper."""
    if shutil.which("ffmpeg") is None:
        return f"[ffmpeg not installed — cannot transcribe {filename}]"
    try:
        import whisper
    except ImportError:
        return f"[openai-whisper not installed — cannot transcribe {filename}]"

    whisper_model_name = os.getenv("WHISPER_MODEL", "base")
    if whisper_model_name not in _whisper_model_cache:
        try:
            logger.info("Loading Whisper model '%s'…", whisper_model_name)
            _whisper_model_cache[whisper_model_name] = whisper.load_model(whisper_model_name)
        except Exception as e:
            return f"[Whisper model load failed for {filename}: {e}]"

    model = _whisper_model_cache[whisper_model_name]

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as src_tmp:
        src_tmp.write(file_bytes)
        src_path = src_tmp.name

    wav_path = src_path + ".wav"
    try:
        _ffmpeg_kwargs: dict = {}
        if sys.platform == "win32":
            _ffmpeg_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path,
             "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, check=True, **_ffmpeg_kwargs,
        )
        result = model.transcribe(wav_path, language="en", verbose=False)
        segments = result.get("segments", [])
        duration = segments[-1]["end"] if segments else 0

        lines = [
            f"# Transcript: {Path(filename).stem}", "",
            f"**Duration:** {int(duration // 60)}m {int(duration % 60)}s",
            f"**Language:** {result.get('language', 'en')}",
            "", "## Transcript", ""
        ]
        for seg in segments:
            ts = f"[{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}]"
            lines.append(f"{ts} {seg['text'].strip()}")
        return "\n".join(lines)

    except subprocess.CalledProcessError as e:
        return f"[ffmpeg error transcribing {filename}: {e.stderr.decode()[:200]}]"
    except Exception as e:
        return f"[Transcription error for {filename}: {e}]"
    finally:
        for p in (src_path, wav_path):
            try:
                os.unlink(p)
            except Exception:
                pass


def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Dispatch to the right extractor based on file extension."""
    ext = Path(filename).suffix.lower()

    if ext in _TEXT_EXTS:
        return file_bytes.decode("utf-8", errors="replace")
    if ext in _MARKITDOWN_EXTS:
        return _extract_with_markitdown(file_bytes, ext, filename)
    if ext in _VSDX_EXTS:
        return _extract_vsdx(file_bytes, filename)
    if ext in _VIDEO_EXTS | _AUDIO_EXTS:
        return _transcribe_audio_video(file_bytes, ext, filename)
    return f"[Unsupported: {ext}]"


def _get_llm():
    """Return an LLM instance for document → skill extraction.

    Delegates to ModelProviderAdapter so this honours whichever provider the user
    has configured (azure | openai | vertex). Falls back to a direct Azure
    construction only if the adapter is unavailable.
    """
    # Preferred: use the platform's model provider — same provider as the agent.
    try:
        from iaf_agent_skills.model_provider import default_model_provider
        # Use 'primary' role — this matches what the agent uses for reasoning,
        # which is what we want for the extraction quality (full model, not light).
        llm = default_model_provider.get("primary")
        if llm is not None:
            return llm
    except Exception as e:
        logger.warning("ModelProviderAdapter.get('primary') failed: %s — trying direct Azure", e)

    # Fallback: direct Azure construction (legacy path for envs without the adapter)
    try:
        from langchain_openai import AzureChatOpenAI
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT",
                               os.getenv("AZURE_OPENAI_DEPLOYMENT_LIGHT", "gpt-4o"))
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        if not (api_key and endpoint):
            return None
        return AzureChatOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            azure_deployment=deployment,
            temperature=0.1,
            max_tokens=4096,
        )
    except Exception as e:
        logger.warning("LLM unavailable: %s", e)
        return None


def _llm_call(system: str, user: str) -> str:
    llm = _get_llm()
    if llm is None:
        raise RuntimeError(
            "LLM not configured — check LLM_PRIMARY_PROVIDER / AZURE_OPENAI_* "
            "env vars in agent_os/config.env"
        )
    from langchain_core.messages import HumanMessage, SystemMessage
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    try:
        from iaf_agent_skills import llm_tracker as _lt
        _lt.record("doc_to_skill", resp, 0.0,
                   getattr(llm, "azure_deployment", getattr(llm, "model_name", "")))
    except Exception:
        pass
    return resp.content.strip()


_SYSTEM_PROMPT = """\
You are an expert enterprise AI architect converting business documents into agent skill definitions.

A SKILL.md defines how an AI agent handles a specific business domain. It has:
1. YAML frontmatter — metadata (name, description, version, triggers, tools, business_context, execution_mode)
2. Markdown body — instructions TO the agent (capabilities, data locations, process steps, rules, output format)

EXECUTION MODES — pick the best one based on the document:
- react: AI reasons freely with tools. Best for open-ended Q&A, analysis, advisory tasks.
- workflow: Fixed sequential steps. Best for clearly defined SOPs with ordered steps.
- parallel: Concurrent independent steps. Best for gathering data from multiple sources simultaneously.
- supervisor: Orchestrates other skills. Best for complex end-to-end processes spanning multiple domains.

RULES:
- skill_name: lowercase + underscores only, ≤30 chars. Reflect the process, not the document title.
- description: One clear sentence — what does the agent do for the user?
- keywords: 8–15 real phrases a user would type. Be specific ("approve invoice", not just "invoice").
- tools: always ["shell","query_memory"]. Add "run_sql_query" ONLY if a database is explicitly mentioned.
- business_context: extract REAL values from the document. No generic placeholders.
- skill_md_body: second-person instructions TO the agent. Include: ## Capabilities, ## Data Location,
  ## Process Steps, ## Business Rules, ## Output Format. Embed key reference data (tables, thresholds,
  matrices, SLAs) directly in the body. DO NOT reference external context files — they are added
  separately by SMEs through the Studio Knowledge tab, not by this generator.
- For workflow/parallel: populate steps[] with name+action+command/task.
- For supervisor: populate worker_skills[] naming the sub-skills to delegate to.

Return ONLY valid JSON — no markdown fences, no preamble. Start with { end with }.

{
  "skill_name": "...",
  "description": "...",
  "version": "1.0",
  "execution_mode": "react|workflow|parallel|supervisor",
  "keywords": ["...", "..."],
  "tools": ["shell", "query_memory"],
  "business_context": {
    "domain": "...",
    "process": "...",
    "rules": [{"id": "r1", "description": "..."}],
    "roles": [{"name": "...", "responsibility": "..."}],
    "entity_types": ["..."]
  },
  "steps": [],
  "worker_skills": [],
  "skill_md_body": "# Title\\n\\n## Capabilities\\n\\n...\\n\\n## Data Location\\n\\n...\\n\\n## Process Steps\\n\\n...\\n\\n## Business Rules\\n\\n...\\n\\n## Output Format\\n\\n...",
  "suggested_category": "operations|implementation|discovery|itops|platform"
}
"""


def _build_skill_md(data: dict) -> str:
    """Build a valid SKILL.md string from generated/edited skill data."""
    import yaml as _yaml

    name            = data.get("skill_name") or data.get("name", "untitled")
    description     = data.get("description", "")
    version         = data.get("version", "1.0")
    execution_mode  = data.get("execution_mode", "react")
    keywords        = data.get("keywords", [])
    tools           = data.get("tools", ["shell", "query_memory"])
    biz             = data.get("business_context", {})
    steps           = data.get("steps", [])
    worker_skills   = data.get("worker_skills", [])
    body            = data.get("skill_md_body", "")

    frontmatter: dict = {
        "name":           name,
        "version":        str(version),
        "description":    description,
        "execution_mode": execution_mode,
    }
    if keywords:
        frontmatter["triggers"] = keywords
    if tools:
        frontmatter["tools"] = tools
    if biz:
        frontmatter["business_context"] = biz
    if steps:
        frontmatter["steps"] = steps
    if worker_skills:
        frontmatter["worker_skills"] = worker_skills

    fm_str = _yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    return f"---\n{fm_str}---\n\n{body}\n"


@router.post("/api/skills/from-document")
async def generate_skill_from_document(
    files: List[UploadFile] = File(...),
    domain_hint: Optional[str]   = Form(""),
    process_hint: Optional[str]  = Form(""),
    category_hint: Optional[str] = Form(""),
):
    """
    Generate a complete SKILL.md package from one or more business documents.
    Supported: PDF, DOCX, PPTX, XLSX, TXT, MD, CSV, MP4, MOV, MP3, WAV, VSDX
    """
    if not files:
        raise HTTPException(400, "At least one file is required")

    extracted_parts, skipped = [], []

    for upload in files:
        fname = upload.filename or "unknown"
        ext   = Path(fname).suffix.lower()
        if ext not in _SUPPORTED_EXTS:
            skipped.append(fname)
            continue

        raw = await upload.read()
        # Run in a worker thread: _extract_text blocks (PDF/DOCX/media parsing).
        text = await asyncio.to_thread(_extract_text, raw, fname)

        if not text.strip() or text.startswith("["):
            skipped.append(fname)
            if text:
                extracted_parts.append(f"=== FILE: {fname} ===\n{text}\n=== END ===")
            continue

        if len(text) > _MAX_SINGLE_CHARS:
            text = text[:_MAX_SINGLE_CHARS] + "\n\n[... truncated ...]"

        extracted_parts.append(f"=== FILE: {fname} ===\n{text}\n=== END ===")

    if not extracted_parts:
        detail = "No text could be extracted from the uploaded file(s)."
        if skipped:
            detail += f" Skipped: {', '.join(skipped)}"
        raise HTTPException(422, detail)

    combined = "\n\n".join(extracted_parts)
    if len(combined) > _MAX_TOTAL_CHARS:
        combined = combined[:_MAX_TOTAL_CHARS] + "\n\n[... total truncated ...]"

    user_parts = ["Document content:\n\n" + combined]
    if domain_hint:   user_parts.append(f"Domain hint: {domain_hint}")
    if process_hint:  user_parts.append(f"Process hint: {process_hint}")
    if category_hint: user_parts.append(f"Category hint: {category_hint}")
    user_parts.append("\nGenerate the complete skill package JSON.")

    raw_resp = ""
    try:
        # Offload to a thread: llm.invoke() is blocking and would freeze the event loop.
        raw_resp = await asyncio.to_thread(_llm_call, _SYSTEM_PROMPT, "\n".join(user_parts))
        json_text = re.sub(r"^```json\s*", "", raw_resp, flags=re.MULTILINE)
        json_text = re.sub(r"^```\s*$", "", json_text, flags=re.MULTILINE).strip()
        result = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s\n%.500s", e, raw_resp)
        raise HTTPException(502, f"LLM returned malformed JSON: {e}")
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("Generation error: %s", e)
        raise HTTPException(502, "An internal error occurred")

    # Skill-only generation: drop any context_md/context_files the LLM added; SMEs author those in the Knowledge tab.
    result.pop("context_md", None)
    result["context_files"] = []

    # Attach pre-built SKILL.md string so frontend can display raw view immediately
    result["skill_md_content"] = _build_skill_md(result)
    result["_source_files"] = [
        {"name": f.filename, "skipped": (f.filename in skipped)}
        for f in files
    ]

    logger.info("doc_to_skill: generated '%s' (%s mode) from %d file(s)",
                result.get("skill_name"), result.get("execution_mode"), len(files))
    return JSONResponse(result)


class ContextFileItem(BaseModel):
    filename: str
    content:  str

class SaveContextFilesRequest(BaseModel):
    skill_name:  str
    files:       List[ContextFileItem]
    tenant_id:   str = "company"

@router.post("/api/skills/save-context-files")
async def save_context_files(req: SaveContextFilesRequest):
    """
    Persist generated context .md files to
    enterprise_root/tenants/{tenant}/shared/contexts/{skill_name}/
    These are accessible inside the agent as /shared/contexts/{skill_name}/
    """
    if not req.skill_name or not re.match(r"^[a-z0-9_-]+$", req.skill_name):
        raise HTTPException(400, "skill_name must be lowercase alphanumeric + underscores/hyphens")

    context_dir = (
        Path(DATA_ROOT) / "tenants" / req.tenant_id
        / "shared" / "contexts" / req.skill_name
    )
    context_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for item in req.files:
        # Sanitise filename — only allow safe names
        safe = re.sub(r"[^\w.\-]", "_", item.filename)
        if not safe.endswith(".md"):
            safe = Path(safe).stem + ".md"
        dest = context_dir / safe
        atomic_write_text(dest, item.content)
        saved.append(str(dest.relative_to(Path(DATA_ROOT).parent)))

    logger.info("Saved %d context file(s) for skill '%s'", len(saved), req.skill_name)
    return {"saved": saved, "context_path": f"/shared/contexts/{req.skill_name}/"}


_TEMPLATES = [
    {
        "id": "invoice_approval",
        "label": "Invoice Approval",
        "category": "operations",
        "execution_mode": "react",
        "description": "Validate, approve or escalate invoices based on business rules",
        "keywords": ["invoice", "approve invoice", "pending invoices", "payment", "vendor invoice"],
        "tools": ["shell", "query_memory"],
        "skill_md_body": "# Invoice Approval Skill\n\n## Capabilities\n1. **List Pending Invoices** — show invoices awaiting approval\n2. **Validate Invoice** — check PO match, vendor status, amount thresholds\n3. **Approve / Reject** — process based on business rules\n4. **Escalate** — route high-value invoices to manager\n\n## Data Location\n- Pending: `/shared/invoices/pending/`\n- Approved: `/shared/invoices/approved/`\n- Vendors: `/shared/invoices/vendors.md`\n- Policy: `/shared/contexts/invoice_approval/context.md`\n\n## Business Rules\n- Auto-approve invoices under $1,000\n- AP Clerk approves $1,000–$5,000\n- Finance Manager required above $5,000\n- PO number must match for any approval\n\n## Output Format\nUse `ui:data_table` for invoice lists. Use `ui:alert` for flagged items.",
        "context_md": "# Invoice Approval Context\n\n## Approval Thresholds\n| Amount | Approver |\n|--------|----------|\n| < $1,000 | Auto-approve |\n| $1,000–$5,000 | AP Clerk |\n| > $5,000 | Finance Manager |\n\n## Vendor Status\n- preferred: expedited processing\n- known: standard processing\n- new: additional validation required\n- flagged: hold for review\n",
        "context_files": [],
        "business_context": {
            "domain": "Finance & Accounting",
            "process": "Invoice Processing",
            "rules": [
                {"id": "auto_approve", "description": "Auto-approve invoices under $1,000"},
                {"id": "po_required", "description": "PO number must match for approval"}
            ],
            "roles": [
                {"name": "AP Clerk", "responsibility": "Approves $1k–$5k invoices"},
                {"name": "Finance Manager", "responsibility": "Approves invoices over $5k"}
            ],
            "entity_types": ["invoice", "vendor", "purchase_order"]
        }
    },
    {
        "id": "it_helpdesk",
        "label": "IT Helpdesk",
        "category": "itops",
        "execution_mode": "react",
        "description": "Handle common IT support requests — password resets, access, hardware tickets",
        "keywords": ["it support", "password reset", "access request", "helpdesk", "ticket", "laptop issue"],
        "tools": ["shell", "query_memory"],
        "skill_md_body": "# IT Helpdesk Skill\n\n## Capabilities\n1. **Log Ticket** — create support ticket for user issue\n2. **Password Reset** — guide user through self-service reset\n3. **Access Request** — process system access requests\n4. **Status Check** — look up existing ticket status\n5. **Escalate** — route complex issues to L2/L3 support\n\n## Data Location\n- Tickets: `/shared/helpdesk/tickets/`\n- Knowledge base: `/shared/contexts/it_helpdesk/kb.md`\n- SLA policy: `/shared/contexts/it_helpdesk/sla.md`\n\n## Business Rules\n- P1 (system down): respond in 15 min, resolve in 4 hr\n- P2 (degraded): respond in 1 hr, resolve in 8 hr\n- P3 (standard): respond in 4 hr, resolve in 2 days\n\n## Output Format\nConfirm ticket number to user. Use `ui:alert` for P1 issues.",
        "context_md": "# IT Helpdesk Context\n\n## Priority Matrix\n| Priority | Response | Resolution | Example |\n|----------|----------|------------|---------|\n| P1 | 15 min | 4 hr | System down |\n| P2 | 1 hr | 8 hr | Performance issue |\n| P3 | 4 hr | 2 days | New access |\n",
        "context_files": [],
        "business_context": {
            "domain": "IT Operations",
            "process": "Helpdesk Ticketing",
            "rules": [
                {"id": "p1_sla", "description": "P1 tickets require 15-min response and 4-hr resolution"},
                {"id": "escalate_l2", "description": "Unresolved P2+ tickets escalate to L2 after SLA breach"}
            ],
            "roles": [
                {"name": "L1 Agent", "responsibility": "First response, standard tickets"},
                {"name": "L2 Engineer", "responsibility": "Complex technical issues"}
            ],
            "entity_types": ["ticket", "user", "asset"]
        }
    },
    {
        "id": "hr_leave_request",
        "label": "HR Leave Request",
        "category": "operations",
        "execution_mode": "workflow",
        "description": "Process employee leave requests — validate balance, get approval, update records",
        "keywords": ["leave request", "apply leave", "annual leave", "sick leave", "leave balance", "time off"],
        "tools": ["shell", "query_memory"],
        "steps": [
            {"name": "check_balance", "action": "shell", "command": "cat /shared/hr/leave_balances/${employee_id}.json"},
            {"name": "validate_request", "action": "shell", "command": "echo 'Validating leave dates and balance'"},
            {"name": "get_approval", "action": "skill", "skill": "general", "task": "Notify manager for leave approval"},
            {"name": "update_records", "action": "shell", "command": "echo 'Updating leave records'"}
        ],
        "skill_md_body": "# HR Leave Request Skill\n\n## Capabilities\n1. **Check Balance** — show available leave days by type\n2. **Submit Request** — process a new leave application\n3. **Get Approval** — notify manager and track response\n4. **Update Records** — record approved leave in system\n5. **Cancel Request** — withdraw a pending application\n\n## Data Location\n- Balances: `/shared/hr/leave_balances/`\n- Requests: `/shared/hr/leave_requests/`\n- Policy: `/shared/contexts/hr_leave_request/policy.md`\n\n## Business Rules\n- Minimum 2 days notice for annual leave\n- Medical certificate required for sick leave > 3 days\n- Manager approval required for any leave > 5 days\n\n## Output Format\nConfirm request ID. Show remaining balance after approval.",
        "context_md": "# HR Leave Policy Context\n\n## Leave Types\n| Type | Annual Entitlement | Notice Required |\n|------|-------------------|------------------|\n| Annual | 20 days | 2 days |\n| Sick | 10 days | Same day |\n| Maternity | 90 days | 4 weeks |\n| Paternity | 5 days | 1 week |\n",
        "context_files": [],
        "business_context": {
            "domain": "Human Resources",
            "process": "Leave Management",
            "rules": [
                {"id": "notice_period", "description": "Minimum 2 days notice for annual leave"},
                {"id": "medical_cert", "description": "Medical certificate required for sick leave >3 days"}
            ],
            "roles": [
                {"name": "Employee", "responsibility": "Submits leave request"},
                {"name": "Line Manager", "responsibility": "Approves/rejects requests"}
            ],
            "entity_types": ["employee", "leave_request", "leave_balance"]
        }
    },
]


@router.get("/api/skill-creator/templates")
async def get_templates():
    """Return starter skill templates for manual creation."""
    return {"templates": _TEMPLATES}
