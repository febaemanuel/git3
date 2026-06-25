#!/usr/bin/env python3
"""
Script para capturar screenshots estáticos dos templates HTML do projeto.
Renderiza os templates Jinja2 com dados fictícios e captura via Playwright.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR = Path(__file__).parent / "screenshots"

# Templates que são páginas completas (não fragments/modais)
SKIP_TEMPLATES = [
    "base.html",
    "campanha_consultas_modal_reagendar.html",  # modal fragment
]


def strip_jinja(html: str) -> str:
    """Remove/substitui tags Jinja2 por conteúdo estático placeholder."""

    # Remove {% extends ... %}
    html = re.sub(r'\{%[-\s]*extends\s+.*?%\}', '', html)

    # Remove {% block ... %} e {% endblock %}
    html = re.sub(r'\{%[-\s]*block\s+\w+\s*[-]?%\}', '', html)
    html = re.sub(r'\{%[-\s]*endblock\s*\w*\s*[-]?%\}', '', html)

    # Remove {% if ... %}, {% elif ... %}, {% else %}, {% endif %}
    html = re.sub(r'\{%[-\s]*if\s+.*?%\}', '', html)
    html = re.sub(r'\{%[-\s]*elif\s+.*?%\}', '', html)
    html = re.sub(r'\{%[-\s]*else\s*%\}', '', html)
    html = re.sub(r'\{%[-\s]*endif\s*%\}', '', html)

    # Remove {% for ... %} e {% endfor %}
    html = re.sub(r'\{%[-\s]*for\s+.*?%\}', '', html)
    html = re.sub(r'\{%[-\s]*endfor\s*%\}', '', html)

    # Remove {% with ... %} e {% endwith %}
    html = re.sub(r'\{%[-\s]*with\s+.*?%\}', '', html)
    html = re.sub(r'\{%[-\s]*endwith\s*%\}', '', html)

    # Remove {% set ... %}
    html = re.sub(r'\{%[-\s]*set\s+.*?%\}', '', html)

    # Remove {% include ... %}
    html = re.sub(r'\{%[-\s]*include\s+.*?%\}', '', html)

    # Remove qualquer outra tag {% ... %} restante
    html = re.sub(r'\{%.*?%\}', '', html)

    # Substitui {{ ... }} por texto placeholder baseado no conteúdo
    def replace_var(match):
        var = match.group(1).strip()
        # Tentar gerar placeholder legível
        if 'nome' in var.lower():
            return 'João Silva'
        if 'email' in var.lower():
            return 'joao@email.com'
        if 'telefone' in var.lower() or 'phone' in var.lower():
            return '(85) 99999-0000'
        if 'data' in var.lower() or 'date' in var.lower():
            return '10/03/2026'
        if 'hora' in var.lower() or 'time' in var.lower():
            return '14:30'
        if 'status' in var.lower():
            return 'Ativo'
        if 'total' in var.lower() or 'count' in var.lower() or 'qtd' in var.lower():
            return '42'
        if 'percent' in var.lower():
            return '75'
        if 'url_for' in var:
            return '#'
        if 'mensagem' in var.lower() or 'message' in var.lower():
            return 'Mensagem de exemplo'
        if 'titulo' in var.lower() or 'title' in var.lower():
            return 'Busca Ativa - HUWC'
        if 'campanha' in var.lower():
            return 'Campanha Exemplo'
        if 'paciente' in var.lower():
            return 'Maria Oliveira'
        if 'medico' in var.lower() or 'doctor' in var.lower():
            return 'Dr. Carlos'
        if 'especialidade' in var.lower():
            return 'Cardiologia'
        if 'hospital' in var.lower() or 'unidade' in var.lower():
            return 'HUWC'
        return 'Exemplo'

    html = re.sub(r'\{\{\s*(.*?)\s*\}\}', replace_var, html)

    return html


def build_full_page(template_content: str, base_content: str) -> str:
    """Combina o conteúdo do template com o base.html."""
    # Se o template já é uma página completa (tem <html>), usa direto
    if '<html' in template_content.lower():
        return strip_jinja(template_content)

    # Caso contrário, injeta no base.html
    base = strip_jinja(base_content)

    # Injeta o conteúdo do template no lugar do bloco content
    content = strip_jinja(template_content)

    # Inserir o conteúdo antes do fechamento do container
    base = base.replace(
        '</div>\n\n    <!-- Bootstrap JS -->',
        f'{content}\n</div>\n\n    <!-- Bootstrap JS -->'
    )

    return base


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    base_html = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")

    templates = sorted(TEMPLATES_DIR.glob("*.html"))
    templates = [t for t in templates if t.name not in SKIP_TEMPLATES]

    print(f"Encontrados {len(templates)} templates para capturar.\n")

    # Gerar HTMLs estáticos em pasta temporária
    tmp_dir = tempfile.mkdtemp(prefix="screenshots_")
    html_files = []

    for tmpl_path in templates:
        print(f"Processando: {tmpl_path.name}")
        content = tmpl_path.read_text(encoding="utf-8")
        full_html = build_full_page(content, base_html)

        out_html = os.path.join(tmp_dir, tmpl_path.name)
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(full_html)
        html_files.append((tmpl_path.stem, out_html))

    # Gerar script Playwright para capturar screenshots
    playwright_script = f"""
const {{ chromium }} = require('playwright');

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const context = await browser.newContext({{
        viewport: {{ width: 1366, height: 900 }}
    }});

    const pages = {str([(name, f"file://{path}") for name, path in html_files])};

    for (const [name, url] of pages) {{
        const page = await context.newPage();
        await page.goto(url, {{ waitUntil: 'networkidle', timeout: 15000 }}).catch(() => {{}});
        await page.waitForTimeout(1000);
        await page.screenshot({{
            path: `{OUTPUT_DIR}/${{name}}.png`,
            fullPage: true
        }});
        console.log(`Capturado: ${{name}}.png`);
        await page.close();
    }}

    await browser.close();
    console.log('\\nTodas as screenshots foram salvas em: {OUTPUT_DIR}');
}})();
"""

    script_path = os.path.join(tmp_dir, "capture.js")
    with open(script_path, "w") as f:
        f.write(playwright_script)

    print(f"\nCapturando screenshots com Playwright...")
    result = subprocess.run(
        ["node", script_path],
        capture_output=True, text=True, timeout=120
    )
    print(result.stdout)
    if result.stderr:
        print("Avisos:", result.stderr[:500])

    print(f"\nScreenshots salvos em: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
