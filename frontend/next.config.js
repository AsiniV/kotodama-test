/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  // В dev-режиме оптимизация изображений не требуется (sharp может быть недоступен)
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
      // Примечание: WebSocket (/ws) НЕ проксируется через rewrites —
      // Next.js rewrites не поддерживают ws://. WebSocket проксируется
      // из клиентского кода (NEXT_PUBLIC_WS_URL) или через Nginx в production.
    ];
  },
};

module.exports = nextConfig;
