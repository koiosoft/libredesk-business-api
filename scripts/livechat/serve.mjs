// Static server minimal para la pagina del widget. Sin dependencias.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 8790);

http.createServer((req, res) => {
  if (req.url === '/' || req.url.startsWith('/widget')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(fs.readFileSync(path.join(dir, 'widget.html')));
    return;
  }
  res.writeHead(404); res.end('not found');
}).listen(port, () => console.log(`widget page: http://localhost:${port}`));
