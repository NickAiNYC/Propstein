import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';

test('preview auth: fails closed with 503 when PREVIEW_AUTH_PASSWORD is unset in non-dev', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const res = checkPreviewAuth(null, { NODE_ENV: 'production' });
  assert.equal(res.authorized, false);
  assert.equal(res.status, 503);
  assert.equal(res.reason, 'Preview not configured');
});

test('preview auth: allows passthrough in development when PREVIEW_AUTH_PASSWORD is unset', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const res = checkPreviewAuth(null, { NODE_ENV: 'development' });
  assert.equal(res.authorized, true);
});

test('preview auth: returns 401 when no credentials are provided', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const env = { PREVIEW_AUTH_PASSWORD: 'secret-password' };
  const res = checkPreviewAuth(null, env);
  assert.equal(res.authorized, false);
  assert.equal(res.status, 401);
});

test('preview auth: returns 401 when wrong password is provided', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const env = { PREVIEW_AUTH_PASSWORD: 'correct-password', PREVIEW_AUTH_USER: 'propstein' };
  const badAuth = 'Basic ' + Buffer.from('propstein:wrong-password').toString('base64');
  const res = checkPreviewAuth(badAuth, env);
  assert.equal(res.authorized, false);
  assert.equal(res.status, 401);
});

test('preview auth: returns 401 when wrong username is provided', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const env = { PREVIEW_AUTH_PASSWORD: 'correct-password', PREVIEW_AUTH_USER: 'propstein' };
  const badAuth = 'Basic ' + Buffer.from('wronguser:correct-password').toString('base64');
  const res = checkPreviewAuth(badAuth, env);
  assert.equal(res.authorized, false);
  assert.equal(res.status, 401);
});

test('preview auth: correctly passes password containing a colon', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const passwordWithColon = 'my:special:pass:word';
  const env = { PREVIEW_AUTH_PASSWORD: passwordWithColon, PREVIEW_AUTH_USER: 'propstein' };
  const header = 'Basic ' + Buffer.from(`propstein:${passwordWithColon}`).toString('base64');
  const res = checkPreviewAuth(header, env);
  assert.equal(res.authorized, true);
});

test('preview auth: handlePreviewMiddleware sets WWW-Authenticate headers on 401 and returns 503 on unconfigured', async () => {
  const { handlePreviewMiddleware } = await import('../terminal/src/lib/propstein/auth.ts');

  // 1. Unconfigured in production -> 503
  const reqUnconfigured = { headers: new Map() };
  const res503 = handlePreviewMiddleware(
    { headers: { get: () => null } },
    { NODE_ENV: 'production' }
  );
  assert.equal(res503.authorized, false);
  assert.equal(res503.status, 503);
  assert.equal(res503.reason, 'Preview not configured');

  // 2. Unauthorized request -> 401 with WWW-Authenticate header
  const env = { PREVIEW_AUTH_PASSWORD: 'secret-password', PREVIEW_AUTH_USER: 'propstein' };
  const res401 = handlePreviewMiddleware(
    { headers: { get: (name) => (name === 'authorization' ? null : null) } },
    env
  );
  assert.equal(res401.authorized, false);
  assert.equal(res401.status, 401);
  assert.equal(res401.headers?.['WWW-Authenticate'], 'Basic realm="PropStein Terminal Preview"');

  // 3. Authorized request -> 200/authorized
  const validHeader = 'Basic ' + Buffer.from('propstein:secret-password').toString('base64');
  const resAuth = handlePreviewMiddleware(
    { headers: { get: (name) => (name === 'authorization' ? validHeader : null) } },
    env
  );
  assert.equal(resAuth.authorized, true);
});

test('preview auth: middleware.ts delegates to handlePreviewMiddleware and protects /api', () => {
  const middlewareFile = fs.readFileSync('terminal/src/middleware.ts', 'utf8');
  assert.ok(
    middlewareFile.includes('handlePreviewMiddleware'),
    'middleware.ts must delegate request authentication to handlePreviewMiddleware'
  );
  assert.ok(
    middlewareFile.includes('matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]'),
    'middleware.ts must use standard matcher protecting routes'
  );
  assert.doesNotMatch(middlewareFile, /\?!api/);

  // Test regex directly
  const matcherRegex = new RegExp("^/((?!_next/static|_next/image|favicon.ico).*)$");
  assert.equal(matcherRegex.test('/api/v1/quotes'), true);
  assert.equal(matcherRegex.test('/api/research'), true);
  assert.equal(matcherRegex.test('/performance'), true);
  assert.equal(matcherRegex.test('/players/00-0033090'), true);
  assert.equal(matcherRegex.test('/_next/static/chunks/main.js'), false);
  assert.equal(matcherRegex.test('/favicon.ico'), false);
});
