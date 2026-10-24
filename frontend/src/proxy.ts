/** Convert a user-entered proxy URL to the existing encrypted API contract. */
export function parseProxyUrl(value: string) {
  try {
    const raw = value.trim();
    const url = new URL(raw);
    const authority = raw.split('://')[1]?.split('/')[0];
    const port = authority?.match(/:(\d+)$/)?.[1];
    if (
      !['http:', 'https:', 'socks5:', 'socks5h:'].includes(url.protocol) ||
      !url.hostname || !port || Number(port) < 1 || Number(port) > 65535 ||
      /\s/.test(raw) || url.search || url.hash ||
      (url.pathname !== '' && url.pathname !== '/')
    ) throw new Error();
    return {
      server: `${url.protocol === 'socks5h:' ? 'socks5:' : url.protocol}//${url.hostname}:${Number(port)}`,
      ...(url.username ? { username: decodeURIComponent(url.username) } : {}),
      ...(url.password ? { password: decodeURIComponent(url.password) } : {}),
    };
  } catch {
    throw new Error('代理 URL 格式无效，请填写 http://用户名:密码@主机:端口 或 socks5://主机:端口');
  }
}
