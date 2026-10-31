import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const clientDirectory = dirname(fileURLToPath(import.meta.url));
const certificatePath = resolve(clientDirectory, 'certs/lan-cert.pem');
const keyPath = resolve(clientDirectory, 'certs/lan-key.pem');
const hasCertificate = existsSync(certificatePath) && existsSync(keyPath);
const hasPartialCertificate = existsSync(certificatePath) !== existsSync(keyPath);

if (hasPartialCertificate) {
  console.warn(
    'HTTPS is disabled: both client/certs/lan-cert.pem and client/certs/lan-key.pem are required.',
  );
}

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5179,
    strictPort: true,
    ...(hasCertificate
      ? {
          https: {
            cert: readFileSync(certificatePath),
            key: readFileSync(keyPath),
          },
        }
      : {}),
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
});
