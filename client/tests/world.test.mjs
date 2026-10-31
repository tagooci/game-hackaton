import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { sha256 } from '../src/world/sha256.js';

const root = new URL('../public/', import.meta.url);
const manifest = JSON.parse(await readFile(new URL('content/world/manifest.json', root)));

test('published map resource sizes and hashes match the manifest', async () => {
  const unique = new Map();
  for (const resource of manifest.resources) {
    const bytes = await readFile(new URL(resource.url.slice(1), root));
    assert.equal(bytes.length, resource.bytes, resource.id);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), resource.sha256, resource.id);
    assert.equal(sha256(bytes), resource.sha256, resource.id);
    unique.set(resource.sha256, resource.bytes);
  }
  assert.equal([...unique.values()].reduce((sum, size) => sum + size, 0), manifest.worldBytes);
  assert.equal(manifest.cacheBudgetBytes, Math.floor(manifest.worldBytes / 10));
});

test('every map chunk fits the budget with its required models', () => {
  const registry = new Map(manifest.resources.map(resource => [resource.id, resource]));
  for (const chunk of manifest.chunks) {
    const ids = [manifest.overviewResourceId, chunk.resourceId, ...chunk.assetIds];
    const unique = new Map(ids.map(id => {
      const resource = registry.get(id);
      assert.ok(resource, id);
      return [resource.sha256, resource.bytes];
    }));
    assert.ok([...unique.values()].reduce((sum, size) => sum + size, 0) <= manifest.cacheBudgetBytes, chunk.id);
  }
});
