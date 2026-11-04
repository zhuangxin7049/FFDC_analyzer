"""Bounded text extraction for authoring references, separate from FFDC intake."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.pptx', '.txt', '.md', '.markdown', '.csv', '.json', '.xml', '.html', '.htm'}
DOCUMENT_MAX_BYTES = 24 * 1024 * 1024
DOCUMENT_MAX_CHARS = 24000
DOCUMENT_SESSION_CHARS = 64000
DOCUMENT_MAX_COUNT = 4
MAX_XML_BYTES = 8 * 1024 * 1024
DOCUMENT_VISION_MAX_PAGES = 12
DOCUMENT_VISION_MAX_IMAGE_BYTES = 4 * 1024 * 1024
DOCUMENT_VISION_MAX_TOTAL_BYTES = 16 * 1024 * 1024


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def safe_xml(data):
    if len(data) > MAX_XML_BYTES or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', data.replace(b'\x00', b''), re.I):
        raise ValueError('XML entities and oversized XML parts are not supported.')
    return ET.fromstring(data)


def xml_words(element):
    return ' '.join(node.text or '' for node in element.iter() if node.tag.rsplit('}', 1)[-1] == 't')


def office_sections(path, suffix):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2048 or sum(item.file_size for item in entries) > 32 * 1024 * 1024:
            raise ValueError('Office archive exceeds the extraction limit.')
        if any(item.file_size > MAX_XML_BYTES or item.file_size > max(1, item.compress_size) * 500 for item in entries):
            raise ValueError('Office archive contains an oversized or highly compressed part.')
        if suffix == '.docx':
            root = safe_xml(archive.read('word/document.xml'))
            body = next((item for item in root.iter() if item.tag.endswith('}body')), None)
            if body is None:
                raise ValueError('The DOCX has no document body.')
            for index, item in enumerate(body, 1):
                if item.tag.endswith('}tbl'):
                    rows = [' | '.join(xml_words(cell) for cell in row if cell.tag.endswith('}tc'))
                            for row in item if row.tag.endswith('}tr')]
                    yield {'location': f'Body block {index} (table)', 'text': '\n'.join(rows)}
                else:
                    yield {'location': f'Body block {index}', 'text': xml_words(item)}
        else:
            slides = sorted((name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)),
                            key=lambda name: int(re.search(r'(\d+)\.xml$', name)[1]))
            for name in slides:
                number = re.search(r'(\d+)\.xml$', name)[1]
                yield {'location': 'Slide ' + number, 'text': xml_words(safe_xml(archive.read(name)))}


def document_sections(path, suffix, warnings):
    if suffix == '.pdf':
        warnings.append('PDF text is extracted separately; visual pages are sent to the configured vision model for image, table and diagram interpretation.')
        try:
            from pypdf import PdfReader
        except ImportError:
            if not shutil.which('pdftotext'):
                raise ValueError('PDF extraction is unavailable. Ask the administrator to install pypdf or pdftotext.') from None
            output = path.with_suffix('.text')
            subprocess.run(['pdftotext', '-f', '1', '-l', '100', '-layout', str(path), str(output)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True)
            with output.open(encoding='utf-8', errors='replace') as stream:
                text = stream.read(DOCUMENT_MAX_CHARS + 1000)
            warnings.append('PDF extraction is limited to the first 100 pages and the text budget.')
            for page, text in enumerate(text.split('\f'), 1):
                yield {'location': f'Page {page}', 'text': text}
            return
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('Password-protected PDFs are not supported. Upload an unencrypted copy.')
        if len(reader.pages) > 100:
            warnings.append('Only the first 100 PDF pages were inspected. Upload a focused excerpt for later pages.')
        for index in range(min(100, len(reader.pages))):
            text = reader.pages[index].extract_text() or ''
            if not text.strip():
                warnings.append(f'Page {index + 1} has no readable text; visual analysis will be attempted.')
            yield {'location': f'Page {index + 1}', 'text': text}
    elif suffix in {'.docx', '.pptx'}:
        warnings.append('Text and table cells only; embedded images, diagrams, headers and speaker notes are not interpreted.')
        yield from office_sections(path, suffix)
    else:
        data = path.read_bytes()
        if suffix == '.xml':
            text = '\n'.join(safe_xml(data).itertext())
        else:
            encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = data.decode(encoding)
            if '\x00' in text:
                raise ValueError('The file does not appear to be a text document.')
            if suffix in {'.html', '.htm'}:
                parser = TextHTML()
                parser.feed(text)
                text = '\n'.join(parser.parts)
        lines = text.splitlines()
        for offset in range(0, len(lines), 40):
            yield {'location': f'Lines {offset + 1}-{min(offset + 40, len(lines))}', 'text': '\n'.join(lines[offset:offset + 40])}


def extract_in_worker(path):
    warnings, sections, remaining = [], [], DOCUMENT_MAX_CHARS
    truncated = False
    for section in document_sections(path, path.suffix.lower(), warnings):
        text = section['text'].replace('\x00', '').strip()
        if not text:
            continue
        if remaining <= 0 or len(sections) >= 200:
            truncated = True
            break
        if len(text) > remaining:
            truncated = True
        sections.append({'location': section['location'], 'text': text[:remaining]})
        remaining -= len(sections[-1]['text'])
        if truncated:
            break
    if not sections:
        if path.suffix.lower() == '.pdf':
            warnings.append('The PDF has no extractable text; visual page analysis is required.')
        else:
            raise ValueError('No readable text was found.')
    if truncated:
        warnings.append('Only the first 24,000 extracted characters are available. Upload a focused excerpt for omitted content.')
    return {'sections': sections, 'truncated': truncated, 'warnings': warnings[:105]}


def extract_document(filename, data):
    if not isinstance(filename, str) or not isinstance(data, (bytes, bytearray)):
        raise ValueError('A document file is required.')
    name = re.sub(r'[\x00-\x1f\x7f]', '', filename.replace('\\', '/').rsplit('/', 1)[-1])[:180]
    suffix = Path(name).suffix.lower()
    if suffix not in DOCUMENT_EXTENSIONS:
        raise ValueError('Supported documents: PDF, DOCX, PPTX, TXT, Markdown, CSV, JSON, XML and HTML.')
    if not data or len(data) > DOCUMENT_MAX_BYTES:
        raise ValueError('Knowledge documents must be non-empty and no larger than 24 MB.')
    if suffix == '.pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('The file does not have a PDF header.')
    with tempfile.TemporaryDirectory(prefix='ffdc-reference-') as directory:
        path = Path(directory) / ('reference' + suffix)
        path.write_bytes(data)
        path.chmod(0o600)
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path)],
                                    capture_output=True, timeout=25, check=True)
            parsed = json.loads(result.stdout)
        except (subprocess.SubprocessError, ValueError, OSError):
            raise ValueError('Document extraction failed or exceeded its resource limit. Try a smaller text-based excerpt.') from None
    if parsed.get('error'):
        raise ValueError(parsed['error'])
    return {**parsed, 'id': hashlib.sha256(data).hexdigest(), 'name': name, 'format': suffix[1:].upper()}


if __name__ == '__main__':
    # Limits are set in the child, never through preexec_fn in the threaded server.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    try:
        output = extract_in_worker(Path(sys.argv[1]))
    except ValueError as exc:
        output = {'error': str(exc)[:300]}
    except Exception:
        output = {'error': 'The document is damaged, encrypted, unsupported, or exceeds the extraction limit.'}
    print(json.dumps(output, ensure_ascii=True))
