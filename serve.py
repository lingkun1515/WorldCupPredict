"""Simple HTTP server for the static site — avoids uvicorn issues."""
import asyncio, json, os, mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

SITE_DIR = Path(__file__).parent / '_site'

CONTENT_TYPES = {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml','.png':'image/png','.json':'application/json'}.copy()

async def handle(reader, writer):
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=15)
        if not line:
            writer.close(); return
        parts = line.decode().split()
        if len(parts) < 2:
            writer.close(); return
        method, path = parts[0], unquote(parts[1])
        if path == '/': path = '/index.html'
        if path == '/archive': path = '/archive.html'
        if path == '/api/today':
            body = await _api_today()
            header = f'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'
            writer.write(header.encode())
            writer.write(body)
            await writer.drain()
            writer.close()
            return

        # /export — generate standalone HTML
        if path == '/export':
            import html as _html
            index_html = (SITE_DIR / 'index.html').read_text()
            css = (SITE_DIR / 'static' / 'css' / 'style.css').read_text()
            js = (SITE_DIR / 'static' / 'js' / 'app.js').read_text()
            
            # Inline CSS and JS
            standalone = index_html
            standalone = standalone.replace(
                '<link rel="stylesheet" href="./static/css/style.css">',
                f'<style>\n{css}\n</style>'
            )
            standalone = standalone.replace(
                '<script src="./static/js/app.js"></script>',
                f'<script>\n{js}\n</script>'
            )
            
            body = standalone.encode()
            writer.write(f'HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Disposition: attachment; filename="WorldCupPredict_Report.html"\r\nContent-Length: {len(body)}\r\n\r\n'.encode())
            writer.write(body)
            await writer.drain()
            writer.close()
            return
        
        # /api/save-export — save to data/exports/
        if path == '/api/save-export':
            today = datetime.now().strftime('%Y-%m-%d')
            export_dir = Path(__file__).parent / 'data' / 'exports'
            export_dir.mkdir(parents=True, exist_ok=True)
            
            index_html = (SITE_DIR / 'index.html').read_text()
            css = (SITE_DIR / 'static' / 'css' / 'style.css').read_text()
            standalone = index_html.replace(
                '<link rel="stylesheet" href="./static/css/style.css">',
                f'<style>\n{css}\n</style>'
            )
            export_path = export_dir / f'report_{today}.html'
            export_path.write_text(standalone)
            
            body = json.dumps({"ok": True, "path": str(export_path)}).encode()
            writer.write(f'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'.encode())
            writer.write(body)
            await writer.drain()
            writer.close()
            return
        else:
            filepath = SITE_DIR / path.lstrip('/')
            if filepath.exists() and filepath.is_file():
                ext = os.path.splitext(path)[1]
                ct = CONTENT_TYPES.get(ext, 'application/octet-stream')
                data = filepath.read_bytes()
                header = f'HTTP/1.0 200 OK\r\nContent-Type: {ct}\r\nContent-Length: {len(data)}\r\n\r\n'
                writer.write(header.encode())
                writer.write(data)
            else:
                writer.write(b'HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n')
        await writer.drain()
    except Exception:
        pass  # Connection errors are expected in simple HTTP server
    finally:
        writer.close()

async def _api_today():
    """Return cached report JSON."""
    today = datetime.now().strftime('%Y-%m-%d')
    archive = Path(__file__).parent / 'data' / 'archive' / f'report_{today}.json'
    if archive.exists():
        return archive.read_bytes()
    return b'{"error":"no report yet"}'

async def main():
    server = await asyncio.start_server(handle, '0.0.0.0', 8080)
    print('Server running on http://0.0.0.0:8080')
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
