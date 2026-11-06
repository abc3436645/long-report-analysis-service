"""Project explicit editorial notes and source locators into native Word comments."""

import re
import unicodedata
from docx.text.paragraph import Paragraph
from long_report.scenario import markdown_table_rows


NOTE = re.compile(r'<!-- review-note:\s*(.*?)\s*-->', re.DOTALL)
SOURCE = re.compile(r'〔(来源：(?>[^〔〕]+|〔[^〔〕]*〕)+)〕')


def annotated_blocks(markdown: str, presentation: dict | None = None) -> list[tuple[str, list[str]]]:
    enabled = (presentation or {}).get('annotations') == 'word_comments'
    result = []
    for block in markdown.strip().split('\n\n'):
        block = block.strip()
        if not block:
            continue
        if '<!--' in block or '-->' in block:
            match = NOTE.fullmatch(block)
            if not enabled:
                raise ValueError('review notes require presentation.annotations=word_comments')
            if not match or not match[1].strip() or '<!--' in match[1] or '-->' in match[1]:
                raise ValueError('invalid review-note block')
            if not result:
                raise ValueError('review note requires a preceding report anchor')
            result[-1][1].append('审阅提示：' + match[1].strip())
            continue
        notes = SOURCE.findall(block) if enabled else []
        text = SOURCE.sub('', block).strip() if enabled else block
        if enabled:
            text = re.sub(r'[\u2f00-\u2fd5]', lambda match: unicodedata.normalize('NFKC', match[0]), text)
        if text:
            result.append((text, notes))
        elif notes and result:
            result[-1][1].extend(notes)
        else:
            raise ValueError('source comment requires a preceding report anchor')
    return result


def verify_comments(document, blocks: list[tuple[str, list[str]]]) -> None:
    expected = [note for _, notes in blocks for note in notes]
    comments = list(document.comments)
    if [c.text for c in comments] != expected:
        raise ValueError('Word comments differ from reviewed notes and sources')
    ids = [str(c.comment_id) for c in comments]
    for tag in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
        found = document.element.xpath('//w:' + tag + '/@w:id')
        if sorted(found) != sorted(ids):
            raise ValueError('Word comment anchors are missing or duplicated')
    # Each comment must surround visible text; cover/TOC cannot be fallback anchors.
    anchors = {}
    for block, notes in blocks:
        if not notes:
            continue
        rows = markdown_table_rows(block)
        if rows is not None:
            text = next(cell for row in rows for cell in row if cell)
        else:
            text = re.sub(r'^#{1,4} ', '', block).replace('**', '')
            chart = re.fullmatch(r'!\[([^\]]+)\]\([^)]+\)', text)
            if chart:
                text = chart[1]
        for note in notes:
            anchors[str(len(anchors))] = text
    for start in document.element.xpath('//w:commentRangeStart'):
        paragraph = Paragraph(start.getparent(), document)
        identifier = start.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
        if (paragraph.text != anchors.get(identifier) or paragraph.style.name == 'Title'
                or paragraph.style.name.startswith(('TOC ', 'Cover '))):
            raise ValueError('Word comment is not anchored to its reviewed report block')
        following = list(start.itersiblings())
        end = next((i for i, node in enumerate(following) if node.tag.endswith('}commentRangeEnd')
                    and node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                    == start.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')), None)
        if end is None or not any(child.text for node in following[:end] for child in node.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')):
            raise ValueError('Word comment has no visible anchor')
