export function normalizeRelationshipItem(item = {}) {
  const username = String(item.username || '').trim().replace(/^@/, '');
  return {
    id: item.id == null ? '' : String(item.id),
    username,
    full_name: String(item.full_name || ''),
    is_verified: Boolean(item.is_verified),
    is_private: Boolean(item.is_private),
    profile_pic_url: String(item.profile_pic_url || '')
  };
}

function keyFor(item) {
  const normalized = normalizeRelationshipItem(item);
  return normalized.id ? `id:${normalized.id}` : `user:${normalized.username.toLowerCase()}`;
}

function dedupe(items = []) {
  const map = new Map();
  for (const raw of items) {
    const item = normalizeRelationshipItem(raw);
    if (!item.username) continue;
    const key = keyFor(item);
    if (!map.has(key)) map.set(key, item);
  }
  return [...map.values()];
}

function alpha(a, b) {
  return a.username.localeCompare(b.username, undefined, { sensitivity: 'base' });
}

export function compareRelationships(followers = [], following = []) {
  const cleanFollowers = dedupe(followers);
  const cleanFollowing = dedupe(following);
  const followerKeys = new Set(cleanFollowers.map(keyFor));
  const followingKeys = new Set(cleanFollowing.map(keyFor));

  const notFollowingBack = cleanFollowing.filter((item) => !followerKeys.has(keyFor(item))).sort(alpha);
  const mutuals = cleanFollowing.filter((item) => followerKeys.has(keyFor(item))).sort(alpha);
  const youDontFollowBack = cleanFollowers.filter((item) => !followingKeys.has(keyFor(item))).sort(alpha);

  return {
    followers: cleanFollowers.sort(alpha),
    following: cleanFollowing.sort(alpha),
    notFollowingBack,
    mutuals,
    youDontFollowBack
  };
}

export function filterRelationships(items = [], query = '') {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) =>
    item.username.toLowerCase().includes(q) || item.full_name.toLowerCase().includes(q)
  );
}
