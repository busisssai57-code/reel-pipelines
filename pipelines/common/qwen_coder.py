"""Qwen Coder: reads error + source → generates unified diff patches."""
from __future__ import annotations
import re, subprocess, logging
from pathlib import Path
from . import config, qwen_client

log = logging.getLogger("qwen_coder")

def extract_file_from_traceback(traceback_str: str) -> str | None:
    """Extract file path from Python traceback."""
    match = re.search(r'File "([^"]+\.py)", line (\d+)', traceback_str)
    if match:
        return match.group(1)
    return None

def generate_patch(file_path: str, error_traceback: str, context_lines: int = 50) -> str | None:
    """
    Read source file around the error, prompt Qwen Coder to generate a fix.
    Returns unified diff or None.
    """
    if not Path(file_path).exists():
        return None

    try:
        # Extract line number from traceback
        match = re.search(r'line (\d+)', error_traceback)
        line_num = int(match.group(1)) if match else 1
        line_num = max(1, line_num)

        # Read file, get context
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        start = max(0, line_num - context_lines)
        end = min(len(lines), line_num + context_lines)
        context = "".join(lines[start:end])

        # Prompt Qwen Coder
        system = (
            "You are an expert Python debugger. "
            "Given a traceback and source code, output ONLY a unified diff patch. "
            "Start with '---' and '+++' lines, then diff hunks. No explanation."
        )
        user = f"Traceback:\n{error_traceback}\n\nSource ({file_path}, lines {start+1}-{end}):\n{context}"

        response = _qwen_coder_call(system, user)
        if not response:
            return None

        # Extract diff block (starts with "--- ", ends at first non-diff line or EOF)
        diff_match = re.search(r'(---.*?)(?:^[^-+\s]|\Z)', response, re.MULTILINE | re.DOTALL)
        if diff_match:
            return diff_match.group(1).strip()

        return None
    except Exception as e:
        log.error(f"generate_patch failed: {e}")
        return None

def apply_patch(patch_diff: str, file_path: str) -> bool:
    """
    Apply unified diff patch to file using stdlib subprocess 'patch' command.
    Creates .bak backup first.
    """
    try:
        p = Path(file_path)
        bak = p.with_suffix(p.suffix + ".bak")

        # Backup
        with open(p, encoding="utf-8") as f:
            bak.write_text(f.read(), encoding="utf-8")

        # Apply patch via subprocess (portableish, not pure Python)
        # On Windows, patch command may not be available; fall back to manual parsing
        try:
            result = subprocess.run(
                ["patch", str(p), "-i", "-"],
                input=patch_diff.encode(),
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                log.info(f"Patch applied to {file_path}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # patch command not available; try manual application
            log.warning("patch command not found, attempting manual apply")
            return _apply_patch_manually(patch_diff, file_path)

        # Restore backup on failure
        with open(bak, encoding="utf-8") as f:
            p.write_text(f.read(), encoding="utf-8")
        return False

    except Exception as e:
        log.error(f"apply_patch failed: {e}")
        return False

def _apply_patch_manually(patch_diff: str, file_path: str) -> bool:
    """
    Fallback: parse unified diff and apply manually (basic implementation).
    Only handles simple single-file, linear patches.
    """
    try:
        lines = patch_diff.split("\n")
        p = Path(file_path)
        with open(p, encoding="utf-8") as f:
            file_lines = f.readlines()

        i = 0
        file_line_idx = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("@@"):
                # Hunk header: @@ -start,count +start,count @@
                match = re.search(r"@@ -(\d+)", line)
                if match:
                    file_line_idx = int(match.group(1)) - 1  # -1 for 0-indexing
                i += 1
            elif line.startswith("-"):
                # Remove line
                if file_line_idx < len(file_lines) and file_lines[file_line_idx].rstrip("\n") == line[1:]:
                    file_lines.pop(file_line_idx)
                else:
                    log.warning(f"Line mismatch at {file_line_idx}: {line}")
                i += 1
            elif line.startswith("+"):
                # Add line
                file_lines.insert(file_line_idx, line[1:] + "\n")
                file_line_idx += 1
                i += 1
            elif line and not line.startswith("\\"):
                # Context line
                file_line_idx += 1
                i += 1
            else:
                i += 1

        with open(p, "w", encoding="utf-8") as f:
            f.writelines(file_lines)
        log.info(f"Manual patch applied to {file_path}")
        return True
    except Exception as e:
        log.error(f"_apply_patch_manually failed: {e}")
        return False

def _qwen_coder_call(system: str, user: str) -> str:
    """Call Qwen Coder model (separate instance or same Ollama)."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.QWEN_API_KEY, base_url=config.QWEN_BASE_URL)
        resp = client.chat.completions.create(
            model=config.QWEN_CODER_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,  # lower temp for deterministic code
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Qwen Coder call failed: {e}")
        return ""
