(function (root) {
  'use strict';

  const WORKFLOWS = Object.freeze(['play', 'shape', 'finish']);
  const ENGINE_COLORS = Object.freeze({
    fm: 'var(--engine-fm)',
    subtractive: 'var(--engine-subtractive)',
    granular: 'var(--engine-granular)',
    wavetable: 'var(--engine-wavetable)',
  });

  function normalizeWorkflow(value) {
    return WORKFLOWS.includes(value) ? value : 'play';
  }

  function workflowContains(attribute, workflow) {
    return String(attribute || '').split(/\s+/).includes(normalizeWorkflow(workflow));
  }

  function contextLabel(params, layerIndex) {
    const layers = params?.layers || [];
    if (!layers.length) return 'Load a preset to begin';
    const index = Math.min(Math.max(0, layerIndex || 0), layers.length - 1);
    const layer = layers[index] || {};
    const presetName = params?.name || 'Current sound';
    const layerName = layer.name || `Layer ${index + 1}`;
    return `${presetName} · ${layerName} · ${layers.length} layer${layers.length === 1 ? '' : 's'}`;
  }

  function layerColor(layer, index) {
    const type = typeof layer === 'object' ? layer?.type : null;
    return ENGINE_COLORS[type] || Object.values(ENGINE_COLORS)[(index || 0) % 4];
  }

  root.ManticeUI = Object.freeze({
    WORKFLOWS,
    normalizeWorkflow,
    workflowContains,
    contextLabel,
    layerColor,
  });
})(window);
