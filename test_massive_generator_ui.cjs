const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const html = fs.readFileSync('engine/static/index.html', 'utf8');
const generate = html.slice(html.indexOf('async function doGenerate()'), html.indexOf('async function doMutate()'));
const choose = html.slice(html.indexOf('async function chooseGenerationCandidate('), html.indexOf('async function doGenerate()'));

test('both web targets parse and remain identical', () => {
  assert.equal(html, fs.readFileSync('docs/index.html', 'utf8'));
  for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    if (match[0].startsWith('<script type="application/ld+json"')) continue;
    new vm.Script(match[1]);
  }
});

test('Massive opens ordered candidates without replacing the current preset', async () => {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      checked: ['gen-type-fm', 'gen-type-subtractive'].includes(id),
      value: id === 'tuning-system' ? '12-TET' : 'C',
      classList: { add() {} }, focus() {},
    });
    return elements.get(id);
  };
  const oldPreset = { name: 'Keep until selection' };
  let request;
  let renders = 0;
  const ctx = vm.createContext({
    selectedMood: 'massive', currentParams: oldPreset, activeHistoryNodeId: null,
    $: element, document: { getElementById: element },
    trackUsage() {}, setStatus() {}, stopAudio() {}, stopGalleryAudition: async () => {},
    renderGenerationCandidates() { renders++; },
    candidateDescriptor(params, index, context) { return { params, index, generationContext: context }; },
    api: async (path, options) => {
      request = JSON.parse(options.body);
      ctx.selectedMood = 'dark'; // Changes while the request is in flight must not misroute it.
      return { ok: true, candidates: ['Weight', 'Pressure', 'Space'].map(role => ({
        role, description: role, seed: 71, params: { name: role, layers: [] },
      })) };
    },
  });
  await vm.runInContext(generate + '\ndoGenerate()', ctx);
  assert.equal(request.mood, 'massive');
  assert.deepEqual(request.allowed_types, ['fm', 'subtractive']);
  assert.equal(ctx.currentParams, oldPreset);
  assert.equal(renders, 1);
  assert.equal(ctx.generationCandidates.map(c => c.role).join(','), 'Weight,Pressure,Space');
  assert.ok(ctx.generationCandidates.every(c => c.previewSeed === 71 && c.previewSeconds === 20));
});

test('selecting a candidate applies it, records history and preserves its preview seed', async () => {
  let history;
  let playback;
  const ctx = vm.createContext({
    generationCandidates: [{ params: { name: 'Pressure' }, previewSeed: 71,
      generationContext: { mood: 'massive', strategy: 'scratch' } }],
    stopGalleryAudition: async () => {},
    addToGenerationHistory(entry) { history = entry; },
    applyParamsToUI() {}, markClean() {}, trackUsage() {}, updateNowPlaying() {},
    setStatus() {}, stopAudio() {}, doPreview(options) { playback = options; },
    $() { return { classList: { remove() {} } }; },
  });
  await vm.runInContext(choose + '\nchooseGenerationCandidate(0)', ctx);
  assert.equal(ctx.currentParams.name, 'Pressure');
  assert.equal(history.mood, 'massive');
  assert.equal(playback.seed, 71);
});
