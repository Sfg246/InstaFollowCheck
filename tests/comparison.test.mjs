import test from 'node:test';
import assert from 'node:assert/strict';
import { compareRelationships, filterRelationships } from '../site/assets/comparison.js';

test('comparison finds non-followers, mutuals, and followers not followed back', () => {
  const followers = [
    { id: '1', username: 'alice', full_name: 'Alice' },
    { id: '2', username: 'bob', full_name: 'Bob' },
    { id: '4', username: 'dana', full_name: 'Dana' }
  ];
  const following = [
    { id: '1', username: 'alice', full_name: 'Alice' },
    { id: '2', username: 'bob', full_name: 'Bob' },
    { id: '3', username: 'charlie', full_name: 'Charlie' }
  ];
  const result = compareRelationships(followers, following);
  assert.deepEqual(result.notFollowingBack.map(x => x.username), ['charlie']);
  assert.deepEqual(result.mutuals.map(x => x.username), ['alice', 'bob']);
  assert.deepEqual(result.youDontFollowBack.map(x => x.username), ['dana']);
});

test('comparison prefers stable ids and removes duplicates', () => {
  const followers = [{ id: '1', username: 'newname' }, { id: '1', username: 'newname' }];
  const following = [{ id: '1', username: 'oldname' }];
  const result = compareRelationships(followers, following);
  assert.equal(result.mutuals.length, 1);
  assert.equal(result.notFollowingBack.length, 0);
});

test('filter matches username and full name case-insensitively', () => {
  const items = [{ username: 'andy_1', full_name: 'Andrew Hana' }, { username: 'bob', full_name: 'Robert' }];
  assert.equal(filterRelationships(items, 'ANDY').length, 1);
  assert.equal(filterRelationships(items, 'hana').length, 1);
  assert.equal(filterRelationships(items, 'zzz').length, 0);
});
