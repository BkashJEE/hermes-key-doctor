// Test harness only: mimics the parts of @hermes/plugin-sdk that hermes-key-doctor uses.
// ?state=before shows the state Key Doctor found on 2026-10-12; default is the live reading saved after the reset.
const state = new URLSearchParams(location.search).get('state') === 'before' ? 'before' : 'after'
const payload = await fetch(`./${state}.json`).then((r) => r.json())
export const ROUTES_AREA = 'routes', SIDEBAR_NAV_AREA = 'sidebar.nav', PALETTE_AREA = 'palette', STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const host = {
  state: { focusedSessionOwner: { get: () => null } },
  navigate: (p) => console.log('navigate', p),
  profileRoutes: async () => [{ connectionId: 'local', mode: 'local', primary: true, profile: 'ceo', targetProfile: 'ceo' }],
  requestProfile: async (route, method, params) => {
    window.__calls = (window.__calls || []).concat([{ method, argv: params.argv }])
    return { code: 0, output: 'some log line\n' + JSON.stringify(payload) }
  },
}
