"""Bounded PDF text extraction subprocess; never executes embedded content."""
import json, resource, sys
resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
from pypdf import PdfReader
reader=PdfReader(sys.argv[1])
if reader.is_encrypted:raise ValueError('PDF protegido por senha.')
if len(reader.pages)>40:raise ValueError('Use PDFs com até 40 páginas por envio.')
pages=[];size=0
for number,page in enumerate(reader.pages,1):
    text=(page.extract_text() or '').strip();size+=len(text)
    if size>80000:raise ValueError('Texto excede 80.000 caracteres; divida o PDF.')
    if text:pages.append({'page':number,'text':text})
if not pages or size<40:raise ValueError('PDF sem texto extraível. Faça OCR antes do envio.')
print(json.dumps({'pages':pages,'page_count':len(reader.pages)},ensure_ascii=False))
