"""Extra Markdown separators must not create empty body paragraphs or pages."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from long_report.rendering import render_docx

class RenderWhitespaceTests(unittest.TestCase):
    def test_extra_separators_preserve_content_without_adding_body_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmp, patch('long_report.rendering._installed_fonts',return_value={'仿宋'}):
            root=Path(tmp);template=root/'template.docx';Document().save(template)
            presentation={'body_font':'仿宋','heading_font':'仿宋','latin_font':'仿宋','allow_font_fallback':False}
            markdown='# 第一章\n\n正文。\n\n# 第二章\n\n后续正文。'
            results=[]
            for n,text in enumerate([markdown,markdown.replace('\n\n','\n\n\n\n')]):
                output=root/f'output-{n}.docx'
                render_docx(text,template,output,'报告',presentation=presentation)
                results.append([(p.text,p.paragraph_format.keep_together,p.paragraph_format.keep_with_next) for p in Document(output).paragraphs])
            self.assertEqual(results[0],results[1],'Formatting-only blank lines must not consume a page before a chapter break')
