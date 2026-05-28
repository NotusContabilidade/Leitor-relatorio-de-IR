"""
Run: python debug_pdf.py caminho\para\o\arquivo.pdf
"""
import sys
import pdfplumber

if len(sys.argv) < 2:
    print("Uso: python debug_pdf.py caminho_do_pdf.pdf")
    sys.exit(1)

path = sys.argv[1]

MARKERS = [
    'Rendimentos isentos e não tributáveis',
    'Rendimentos sujeitos a tributação exclusiva',
    'Renda variável',
]

with pdfplumber.open(path) as pdf:
    for i, page in enumerate(pdf.pages):
        texto = page.extract_text() or ""
        found = [m for m in MARKERS if m in texto]
        if found:
            print(f"\n--- Página {i+1} ---")
            for m in found:
                pos = texto.find(m)
                snippet = texto[max(0, pos-30):pos+len(m)+30].replace('\n', '↵')
                print(f"  [{m[:40]}] pos={pos}  contexto: ...{snippet}...")
            tbls = page.find_tables()
            print(f"  Tabelas na página: {len(tbls)}")
