import { describe, expect, it } from 'vitest';
import { parseProxyUrl } from './proxy';

describe('proxy URL input', () => {
  it.each([
    ['http://proxy.test:80', { server: 'http://proxy.test:80' }],
    ['https://proxy.test:443/', { server: 'https://proxy.test:443' }],
    ['socks5://[::1]:1080', { server: 'socks5://[::1]:1080' }],
    ['socks5h://u%40x:p%3Aa%2Fss@proxy.test:1080', { server: 'socks5h://proxy.test:1080', username: 'u@x', password: 'p:a/ss' }],
  ])('converts %s to the API contract', (url, expected) => {
    expect(parseProxyUrl(url)).toEqual(expected);
  });
  it.each([
    'proxy.test:1080', 'ftp://proxy.test:21', 'http://proxy.test',
    'http://proxy.test:0', 'http://proxy.test:65536',
    'http://proxy.test:80/path', 'http://proxy.test:80?key=secret',
    'http://proxy.test:80#secret', 'http://u:%ZZ@proxy.test:80',
    'http://u:secret password@proxy.test:80',
  ])('rejects invalid input without echoing secrets', (url) => {
    expect(() => parseProxyUrl(url)).toThrow('代理 URL 格式无效');
    try { parseProxyUrl(url); } catch (error) {
      expect((error as Error).message).not.toContain(url);
    }
  });
});
