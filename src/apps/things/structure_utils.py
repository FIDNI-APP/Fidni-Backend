"""
Pure functions that operate on a structure dict.
No model imports — fully testable in isolation.

Structure shape:
{
    "version": "2.0",
    "blocks": [
        {"type": "context"|"question"|"section", "id": "...", "content": {"html": "..."}, "points": N,
         "subQuestions": [
             {"id": "...", "points": N, "parts": [{"id": "...", "points": N}]}
         ]}
    ]
}
"""


def get_all_item_paths(structure: dict) -> list[str]:
    paths = []
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        block_id = block.get('id', '')
        if block_id:
            paths.append(block_id)
            for sub in block.get('subQuestions', []):
                sub_id = sub.get('id', '')
                if sub_id:
                    sub_path = f"{block_id}.{sub_id}"
                    paths.append(sub_path)
                    for part in sub.get('parts', []):
                        part_id = part.get('id', '')
                        if part_id:
                            paths.append(f"{sub_path}.{part_id}")
    return paths


def get_total_points(structure: dict) -> int:
    total = 0
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        block_points = block.get('points', 0) or 0
        sub_points = sum(
            (sub.get('points', 0) or 0) + sum(
                (part.get('points', 0) or 0) for part in sub.get('parts', [])
            )
            for sub in block.get('subQuestions', [])
        )
        total += sub_points if sub_points > 0 else block_points
    return total


def get_item_count(structure: dict) -> int:
    return len(get_all_item_paths(structure))


def get_section_count(structure: dict) -> int:
    return sum(
        1 for b in (structure or {}).get('blocks', [])
        if b.get('type') == 'section'
    )


def get_preview(structure: dict) -> str:
    for block in (structure or {}).get('blocks', []):
        if block.get('type') in ('context', 'question'):
            html = block.get('content', {}).get('html', '')
            if html:
                return html[:500]
    return ''
