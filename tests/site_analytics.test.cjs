const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../site/assets/analytics.js'), 'utf8');
const validToken = '0123456789abcdef0123456789abcdef'; // synthetic public-token-shaped fixture
function run({host='votsie.github.io', protocol='https:', pathname='/instagram-obscura-mcp/',
              token=validToken, dnt='0', windowDnt='0', gpc=false, existing=false, current=true}={}) {
  const added = [];
  const script = {getAttribute: key => key === 'data-cf-token' ? token : null};
  const document = {
    currentScript: current ? script : null,
    querySelector: () => existing || added.length ? {} : null,
    createElement: () => ({setAttribute(key, value) { this[key] = value; }}),
    head: {appendChild: node => added.push(node)}
  };
  const context = {document, location: {hostname: host, protocol, pathname},
                   navigator: {doNotTrack: dnt, globalPrivacyControl: gpc},
                   window: {doNotTrack: windowDnt}};
  assert.doesNotThrow(() => vm.runInNewContext(source, context, {filename: path.join(__dirname, '../site/assets/analytics.js')}));
  return {added, context};
}

test('loads exactly the official Cloudflare beacon for the project scope', () => {
  const {added} = run();
  assert.equal(added.length, 1);
  assert.equal(added[0].src, 'https://static.cloudflareinsights.com/beacon.min.js');
  assert.deepEqual(JSON.parse(added[0]['data-cf-beacon']), {token: validToken});
  assert.equal(added[0].async, true);
  assert.equal(added[0]['data-instagram-mcp-cf-beacon'], '');
});

test('covers localized and guide pages but rejects similarly named projects', () => {
  for (const pathname of ['/instagram-obscura-mcp', '/instagram-obscura-mcp/ru/',
                           '/instagram-obscura-mcp/reels/'])
    assert.equal(run({pathname}).added.length, 1);
  for (const pathname of ['/', '/instagram-obscura-mcp-other/', '/foo/instagram-obscura-mcp/'])
    assert.equal(run({pathname}).added.length, 0);
});

test('does not track local, preview, non-HTTPS, foreign or missing context', () => {
  for (const input of [{host:'localhost'}, {host:'votsie.github.io.evil.test'},
                       {host:'preview.example.com'}, {protocol:'http:'}, {current:false}])
    assert.equal(run(input).added.length, 0);
});

test('respects browser DNT and global privacy control', () => {
  for (const input of [{dnt:'1'}, {windowDnt:'1'}, {gpc:true}])
    assert.equal(run(input).added.length, 0);
});

test('rejects absent or malformed site tokens and avoids duplicate loading', () => {
  for (const token of ['', null, 'undefined', 'a'.repeat(31), 'x'.repeat(32), 'a'.repeat(33)])
    assert.equal(run({token}).added.length, 0);
  assert.equal(run({existing:true}).added.length, 0);
  const {added,context} = run();
  vm.runInNewContext(source, context, {filename: path.join(__dirname, '../site/assets/analytics.js')});
  assert.equal(added.length, 1);
});
