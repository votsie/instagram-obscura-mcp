/* Privacy-aware bootstrap for the Cloudflare Web Analytics beacon. */
(() => {
  'use strict';
  const script = document.currentScript;
  const token = script && script.getAttribute('data-cf-token');
  const project = '/instagram-obscura-mcp';
  const inProject = location.pathname === project || location.pathname.startsWith(project + '/');
  if (location.protocol !== 'https:' || location.hostname !== 'votsie.github.io' || !inProject ||
      navigator.globalPrivacyControl === true || navigator.doNotTrack === '1' || window.doNotTrack === '1' ||
      typeof token !== 'string' || !/^[0-9a-f]{32}$/i.test(token) ||
      document.querySelector('script[data-instagram-mcp-cf-beacon]')) return;

  const beacon = document.createElement('script');
  beacon.src = 'https://static.cloudflareinsights.com/beacon.min.js';
  beacon.async = true;
  beacon.setAttribute('data-cf-beacon', JSON.stringify({token}));
  beacon.setAttribute('data-instagram-mcp-cf-beacon', '');
  document.head.appendChild(beacon);
})();
