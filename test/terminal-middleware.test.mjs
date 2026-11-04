import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';

// Read pure auth helper logic or evaluate matcher
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

test('preview auth: correctly passes password containing a colon', async () => {
  const { checkPreviewAuth } = await import('../terminal/src/lib/propstein/auth.ts');
  const passwordWithColon = 'my:special:pass:word';
  const env = { PREVIEW_AUTH_PASSWORD: passwordWithColon, PREVIEW_AUTH_USER: 'propstein' };
  const header = 'Basic ' + Buffer.from(`propstein:${passwordWithColon}`).toString('base64');
  const res = checkPreviewAuth(header, env);
  assert.equal(res.authorized, true);
});

test('preview auth: matcher protects /api routes as well as pages', () => {
  const middlewareFile = fs.readFileSync('terminal/src/middleware.ts', 'utf8');
  assert.ok(middlewareFile.includes('matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]'));
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
