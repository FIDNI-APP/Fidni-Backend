"""
pdf_parser.py — Parse a PDF with opendataloader-pdf and map to our blocks format.

Rule-based mapping (no LLM):
  - heading level 1  → used as document title if no explicit title
  - heading level 2+ → context block (section separator)
  - paragraph that starts with a digit pattern (1., 2., a), b), etc.)
                     → question block
  - any other paragraph attached to the previous question
                     → appended to that question's content
  - formula elements → preserved as LaTeX inline in the html
"""

import os
import re
import tempfile
import json
import uuid
import logging

logger = logging.getLogger('django')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_Q_PATTERN = re.compile(
    r'^(?:'
    r'\d+[\.\)]\s+'          # 1. or 1)
    r'|\d+\.\d+[\.\)]\s+'    # 1.1. or 1.1)
    r'|[a-zA-Z][\.\)]\s+'    # a. or a)
    r')'
)

def _gen_id() -> str:
    return f"block-{uuid.uuid4().hex[:12]}"


def _strip_leading_numbering(text: str) -> str:
    """Remove the leading numbering prefix (1. / a) / 1.1.) from question text."""
    return _Q_PATTERN.sub('', text, count=1).strip()


def _to_html(text: str) -> str:
    """Wrap plain text in a <p> tag. Escape minimal HTML."""
    if not text:
        return ''
    escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<p>{escaped}</p>'


def _element_to_text(el: dict) -> str:
    """Extract plain text from an opendataloader element."""
    content = el.get('content', '')
    if isinstance(content, list):
        # Table cells etc.
        parts = []
        for row in content:
            if isinstance(row, list):
                parts.append(' | '.join(str(c) for c in row))
            else:
                parts.append(str(row))
        return '\n'.join(parts)
    return str(content) if content else ''


# ---------------------------------------------------------------------------
# Core converter: opendataloader JSON → our blocks structure
# ---------------------------------------------------------------------------

def _odl_elements_to_blocks(elements: list, content_type: str) -> dict:
    """
    Convert a flat list of opendataloader elements into our versioned blocks structure.
    content_type: 'exercise' | 'exam' | 'lesson'
    """
    if content_type == 'lesson':
        return _build_lesson_structure(elements)
    return _build_exercise_structure(elements)


def _build_exercise_structure(elements: list) -> dict:
    blocks = []
    pending_context_lines = []

    def _flush_context():
        if pending_context_lines:
            html = ''.join(f'<p>{ln}</p>' for ln in pending_context_lines if ln.strip())
            if html:
                blocks.append({
                    'id': _gen_id(),
                    'type': 'context',
                    'content': {'type': 'text', 'html': html},
                })
            pending_context_lines.clear()

    for el in elements:
        el_type = el.get('type', '')
        text = _element_to_text(el).strip()
        if not text:
            continue

        if el_type == 'heading':
            _flush_context()
            # h1 is typically the doc title — treat as context intro
            # h2+ are section separators → context block
            blocks.append({
                'id': _gen_id(),
                'type': 'context',
                'content': {'type': 'text', 'html': f'<p><strong>{text}</strong></p>'},
            })

        elif el_type == 'formula':
            # Keep formula attached to pending context or last question
            formula_html = f'<p>$${text}$$</p>'
            if blocks and blocks[-1]['type'] == 'question':
                existing = blocks[-1]['content']['html']
                blocks[-1]['content']['html'] = existing + formula_html
            else:
                pending_context_lines.append(f'$${text}$$')

        elif el_type in ('paragraph', 'list'):
            if _Q_PATTERN.match(text):
                _flush_context()
                clean = _strip_leading_numbering(text)
                blocks.append({
                    'id': _gen_id(),
                    'type': 'question',
                    'content': {'type': 'text', 'html': _to_html(clean)},
                    'solution': None,
                    'points': None,
                    'subQuestions': [],
                })
            else:
                # Continuation: attach to last question if one exists, else context
                if blocks and blocks[-1]['type'] == 'question':
                    existing = blocks[-1]['content']['html']
                    blocks[-1]['content']['html'] = existing + _to_html(text)
                else:
                    pending_context_lines.append(text)

        elif el_type == 'table':
            table_html = _table_to_html(el)
            if blocks and blocks[-1]['type'] == 'question':
                blocks[-1]['content']['html'] += table_html
            else:
                pending_context_lines.append(table_html)

    _flush_context()

    # If no question blocks were detected, treat everything as context
    if not any(b['type'] == 'question' for b in blocks):
        all_html = ''.join(b['content']['html'] for b in blocks)
        blocks = [{
            'id': _gen_id(),
            'type': 'context',
            'content': {'type': 'text', 'html': all_html},
        }]

    return {'version': '2.0', 'blocks': blocks}


def _build_lesson_structure(elements: list) -> dict:
    sections = []
    current_section = None

    for el in elements:
        el_type = el.get('type', '')
        text = _element_to_text(el).strip()
        if not text:
            continue

        if el_type == 'heading':
            level = el.get('level', 1)
            if level <= 2:
                # New top-level section
                current_section = {
                    'id': _gen_id(),
                    'title': text,
                    'content': {'type': 'text', 'html': ''},
                    'subSections': [],
                }
                sections.append(current_section)
            else:
                # Sub-section
                sub = {
                    'id': _gen_id(),
                    'title': text,
                    'content': {'type': 'text', 'html': ''},
                }
                if current_section is None:
                    current_section = {
                        'id': _gen_id(),
                        'title': '',
                        'content': {'type': 'text', 'html': ''},
                        'subSections': [],
                    }
                    sections.append(current_section)
                current_section['subSections'].append(sub)
        else:
            html = _to_html(text)
            if current_section is None:
                current_section = {
                    'id': _gen_id(),
                    'title': '',
                    'content': {'type': 'text', 'html': ''},
                    'subSections': [],
                }
                sections.append(current_section)
            # Append to deepest active sub-section or section itself
            if current_section['subSections']:
                current_section['subSections'][-1]['content']['html'] += html
            else:
                current_section['content']['html'] += html

    return {'version': '1.0', 'sections': sections}


def _table_to_html(el: dict) -> str:
    content = el.get('content', [])
    if not content or not isinstance(content, list):
        return ''
    rows_html = ''
    for i, row in enumerate(content):
        if not isinstance(row, list):
            continue
        tag = 'th' if i == 0 else 'td'
        cells = ''.join(f'<{tag}>{str(c)}</{tag}>' for c in row)
        rows_html += f'<tr>{cells}</tr>'
    return f'<table>{rows_html}</table>'


# ---------------------------------------------------------------------------
# Extract title from elements
# ---------------------------------------------------------------------------

def _extract_title(elements: list) -> str:
    for el in elements:
        if el.get('type') == 'heading' and el.get('level', 99) == 1:
            return _element_to_text(el).strip()
    # Fallback: first non-empty text
    for el in elements:
        t = _element_to_text(el).strip()
        if t:
            return t[:80]
    return 'Sans titre'


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_pdf(pdf_bytes: bytes, content_type: str, filename: str = 'document.pdf') -> dict:
    """
    Parse a PDF file and return our simplified JSON format:
    {
        "title": "...",
        "blocks": [...],   # for exercise/exam
        "sections": [...], # for lesson
    }
    Raises RuntimeError if opendataloader-pdf is not available or parsing fails.
    """
    try:
        import opendataloader_pdf
    except ImportError:
        raise RuntimeError(
            'opendataloader-pdf is not installed. '
            'Run: pip install opendataloader-pdf  (requires Java 11+)'
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, filename)
        output_dir = os.path.join(tmpdir, 'out')
        os.makedirs(output_dir, exist_ok=True)

        with open(input_path, 'wb') as f:
            f.write(pdf_bytes)

        try:
            opendataloader_pdf.convert(
                input_path=[input_path],
                output_dir=output_dir,
                format='json',
                quiet=True,
            )
        except Exception as e:
            raise RuntimeError(f'PDF conversion failed: {e}')

        # Find the output JSON file
        json_path = None
        for root, _, files in os.walk(output_dir):
            for fname in files:
                if fname.endswith('.json'):
                    json_path = os.path.join(root, fname)
                    break

        if not json_path or not os.path.exists(json_path):
            raise RuntimeError('opendataloader-pdf produced no JSON output')

        with open(json_path, 'r', encoding='utf-8') as f:
            odl_data = json.load(f)

    # opendataloader JSON can be a list of elements or {"elements": [...]}
    if isinstance(odl_data, list):
        elements = odl_data
    elif isinstance(odl_data, dict):
        elements = odl_data.get('elements', odl_data.get('content', []))
    else:
        elements = []

    title = _extract_title(elements)
    structure = _odl_elements_to_blocks(elements, content_type)

    result = {'title': title}
    if content_type == 'lesson':
        result['sections'] = structure['sections']
    else:
        result['blocks'] = structure['blocks']

    return result
